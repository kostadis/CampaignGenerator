from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.summary_native import synth
from pipelines.summary_native.authority import AuthorityLedger, AudienceGrant, Classification, EffectiveInterval, NoteRecord, Projection, SubjectRef, write_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.freshness import check_authority_output_fresh
from tests import conftest_party as cp
from tests import conftest_state as cs
from tests.test_summary_native_planning import PlanningModels


def test_metadata_only_authority_change_stales_a_planning_run():
    current = {
        "ledger_revision": 2,
        "records": [{"id": "plan", "metadata_sha256": "b" * 64, "section_sha256": "a" * 64}],
        "selection": {"membership_sha256": "c" * 64},
    }
    old = {
        "ledger_revision": 1,
        "records": [{"id": "plan", "metadata_sha256": "d" * 64, "section_sha256": "a" * 64}],
        "selection": {"membership_sha256": "c" * 64},
    }
    assert "authority inputs changed" in check_authority_output_fresh({"inputs": {"authority_manifest": old}}, current)


def test_selection_membership_change_stales_a_planning_run():
    old = {"records": [], "selection": {"membership_sha256": "a" * 64}}
    current = {"records": [], "selection": {"membership_sha256": "b" * 64}}
    assert check_authority_output_fresh({"inputs": {"authority_manifest": old}}, current)


def _planning_note(identifier: str, classification: Classification, anchor: str, text: bytes, *, claim: str, value: str) -> NoteRecord:
    return NoteRecord(
        id=identifier, kind="note", revision=1, classification=classification,
        subject=SubjectRef(kind="topic", id="gate-plan"),
        claim_key=claim, normalized_value=value,
        effective=EffectiveInterval(horizon="future"), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.PLANNING}, status="active", recorded_at="2026-10-09T00:00:00Z",
        recorded_by="GM", source={"path": "notes/authority-plan.md", "anchor": anchor},
        content_digest=hashlib.sha256(text).hexdigest(), planning_date="chapter-1", selection_label=identifier,
    )


def test_planning_uses_reviewed_selection_and_refuses_drift_stale_and_legacy_runs(tmp_path: Path, monkeypatch):
    """The production planning path receives only selected, precedence-resolved note sections."""
    root = cp.party_campaign(tmp_path)
    base = cp.fake_party_models(monkeypatch)
    assert cs.run_cli(cp.extract_args(root))[0] == 0
    models = PlanningModels(base)
    monkeypatch.setattr(synth, "render_part", models.render)

    notes_dir = root / "notes"; notes_dir.mkdir()
    source = notes_dir / "authority-plan.md"
    source.write_bytes(
        b"<!-- anchor: prep -->\nPREP: wait for the gate.\n### Overlay\n"
        b"<!-- anchor: overlay -->\nOVERLAY: act at the gate now.\n### Open\n"
        b"<!-- anchor: open -->\nOPEN: who carries the seal?\n"
    )
    prep = b"<!-- anchor: prep -->\nPREP: wait for the gate.\n"
    overlay = b"<!-- anchor: overlay -->\nOVERLAY: act at the gate now.\n"
    opened = b"<!-- anchor: open -->\nOPEN: who carries the seal?\n"
    records = [
        _planning_note("gate-prep", Classification.PREP, "prep", prep, claim="move", value="wait"),
        _planning_note("gate-overlay", Classification.OVERLAY, "overlay", overlay, claim="move", value="act"),
        _planning_note("gate-open", Classification.OPEN, "open", opened, claim="seal", value="unknown"),
        _planning_note("unselected-note", Classification.CANON, "prep", prep, claim="other", value="unused"),
    ]
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=1, records=records))
    planning = root / "config" / "planning.yaml"
    planning.write_text(planning.read_text(encoding="utf-8") + "notes:\n  - id: gate-authority\n    path: notes/authority-plan.md\n    record_ids: [gate-prep, gate-overlay, gate-open]\n", encoding="utf-8")

    # Preview produces the opaque reviewed selection SHA consumed by synthesis.
    from io import StringIO
    import contextlib
    capture = StringIO()
    with contextlib.redirect_stdout(capture):
        assert main(["authority", "notes", "preview", "--campaign-dir", str(root), "--audience", "gm", "--json"]) == 0
    preview = json.loads(capture.getvalue())
    selection_sha = preview["data"]["selection_sha256"]
    command = ["synth", "planning", *cp.common(root), "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1", "--recent-chapters", "2", "--fallback-npc-lines", "--authority-selection", selection_sha, "--force"]
    assert cs.run_cli(command)[0] == 0
    assert models.calls and all("REVIEWED PLANNING AUTHORITY" in call["user"] for call in models.calls)
    authority_text = models.calls[0]["user"]
    assert "gate-overlay" in authority_text and "gate-open" in authority_text
    assert "gate-prep" not in authority_text  # OVERLAY supersedes overlapping PREP.
    run = sorted((cp.range_dir(root) / "state" / "runs").glob("*/record.json"))[-1]
    record = json.loads(run.read_text(encoding="utf-8"))
    manifest = record["inputs"]["authority_manifest"]
    assert {entry["id"] for entry in manifest["records"]} == {"gate-prep", "gate-overlay", "gate-open"}
    assert manifest["selection"]["selection_sha256"] == selection_sha
    assert any("stale future planning authority" in warning for warning in record["inputs"]["authority_warnings"])

    # A ledger change through the accepted record-retire operation invalidates the draft even though the selected bytes stay put.
    from pipelines.summary_native.authority import ledger_digest
    assert main(["authority", "record", "retire", "unselected-note", "--reason", "obsolete", "--expected-revision", "1", "--expected-ledger-sha256", ledger_digest(root), "--campaign-dir", str(root), "--json"]) == 0
    rc, _, err = cs.run_cli(command[:-1])  # same reviewed SHA, no --force
    assert rc == 2 and "authority inputs changed since this output" in err

    # A previous-run record without the authority manifest is legacy and cannot be reused after selection is enabled.
    legacy = cp.range_dir(root) / "state" / "runs" / "legacy"; legacy.mkdir()
    (legacy / "record.json").write_text('{"inputs": {}}\n', encoding="utf-8")
    draft = cp.range_dir(root) / "state" / "drafts" / "planning.draft.md"
    draft.write_text("<!-- summary_native draft | record: runs/legacy/record.json -->\nlegacy\n", encoding="utf-8")
    rc, _, err = cs.run_cli(command[:-1])
    assert rc == 2 and "authority inputs changed since this output" in err

    # A new glob member changes materialized membership, so the old reviewed SHA refuses before a model call.
    (notes_dir / "later.md").write_text("later", encoding="utf-8")
    planning.write_text(planning.read_text(encoding="utf-8").replace("notes/authority-plan.md", "notes/*.md"), encoding="utf-8")
    rc, _, err = cs.run_cli(command)
    assert rc == 2 and "authority selection changed or was not reviewed" in err


def test_planning_synth_blocks_only_selected_overlapping_structured_conflicts_before_model(tmp_path: Path, monkeypatch):
    """Exercise the production synth callsite, not only conflict detection helpers."""
    root = cp.party_campaign(tmp_path)
    base = cp.fake_party_models(monkeypatch)
    assert cs.run_cli(cp.extract_args(root))[0] == 0
    models = PlanningModels(base)
    monkeypatch.setattr(synth, "render_part", models.render)
    notes_dir = root / "notes"; notes_dir.mkdir()
    source = notes_dir / "authority-plan.md"
    first = b"<!-- anchor: first -->\nGate remains closed.\n"
    second = b"<!-- anchor: second -->\nGate is open.\n"
    selected = b"<!-- anchor: selected -->\nScout the gate.\n"
    source.write_bytes(first + b"### Second\n" + second + b"### Selected\n" + selected)
    left = _planning_note("gate-closed", Classification.CANON, "first", first, claim="gate-state", value="closed")
    right = _planning_note("gate-open", Classification.CANON, "second", second, claim="gate-state", value="open")
    third = _planning_note("selected-plan", Classification.PREP, "selected", selected, claim="scout", value="yes")
    # Canonical planning notes use a bounded scope here so disjoint evolution
    # is distinct from a current overlapping contradiction.
    left = left.model_copy(update={"effective": {"from_chapter": 1, "through_chapter": 5}})
    right = right.model_copy(update={"effective": {"from_chapter": 1, "through_chapter": 5}})
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=1, records=[left, right, third]))
    planning = root / "config" / "planning.yaml"
    planning.write_text(planning.read_text(encoding="utf-8") + "notes:\n  - id: selected\n    path: notes/authority-plan.md\n    record_ids: [gate-closed, gate-open]\n", encoding="utf-8")
    capture = __import__("io").StringIO()
    import contextlib
    with contextlib.redirect_stdout(capture):
        assert main(["authority", "notes", "preview", "--campaign-dir", str(root), "--audience", "gm", "--json"]) == 0
    selection = json.loads(capture.getvalue())["data"]["selection_sha256"]
    command = ["synth", "planning", *cp.common(root), "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1", "--recent-chapters", "2", "--fallback-npc-lines", "--authority-selection", selection, "--force"]
    rc, _, err = cs.run_cli(command)
    assert rc == 5 and "AUTH_CONFLICT: unresolved structured authority conflict" in err
    assert not models.calls

    # Disjoint intervals represent evolution and do not block the same synth.
    right = right.model_copy(update={"effective": {"from_chapter": 9, "through_chapter": 10}})
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=2, records=[left, right, third]))
    with contextlib.redirect_stdout(capture := __import__("io").StringIO()):
        assert main(["authority", "notes", "preview", "--campaign-dir", str(root), "--audience", "gm", "--json"]) == 0
    selection = json.loads(capture.getvalue())["data"]["selection_sha256"]
    rc, _, err = cs.run_cli([*command[:-2], selection, "--force"])
    assert rc == 0, err

    # A conflicting pair outside the reviewed selector never blocks its scope.
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=3, records=[left, left.model_copy(update={"id": "gate-open", "normalized_value": "open"}), third]))
    planning.write_text(planning.read_text(encoding="utf-8").replace("[gate-closed, gate-open]", "[selected-plan]"), encoding="utf-8")
    with contextlib.redirect_stdout(capture := __import__("io").StringIO()):
        assert main(["authority", "notes", "preview", "--campaign-dir", str(root), "--audience", "gm", "--json"]) == 0
    selection = json.loads(capture.getvalue())["data"]["selection_sha256"]
    rc, _, err = cs.run_cli([*command[:-2], selection, "--force"])
    assert rc == 0, err
