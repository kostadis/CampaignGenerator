from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path

import yaml

from pipelines.summary_native import synth
from pipelines.summary_native.authority import (AudienceGrant, AuthorityLedger, Classification,
                                                EffectiveInterval, NoteRecord, Projection,
                                                RulingRecord, SubjectRef, ledger_digest,
                                                load_ledger, sha256_bytes, write_ledger)
from pipelines.summary_native.authority_apply import apply_proposal, create_proposal
from pipelines.summary_native.authority_inputs import resolve_anchor_span
from pipelines.summary_native.cli import main
from tests import conftest_party as cp
from tests import conftest_state as cs
from tests.test_summary_native_synth import Models, build


TRUTH = "The correct actor broke against the gate."


def _ruling(source: Path) -> RulingRecord:
    data = source.read_bytes()
    return RulingRecord.model_validate({
        "id": "earthstone-ruling",
        "kind": "ruling",
        "revision": 1,
        "classification": "RULED",
        "subject": {"kind": "topic", "id": "earthstone"},
        "effective": {"from_chapter": 4, "through_chapter": 4},
        "audience": {"grants": ["gm"]},
        "projections": ["world_state", "campaign_state", "party", "planning"],
        "status": "draft",
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "source": {
            "path": "docs/summaries/004-the-ring.md",
            "anchor": "earthstone-responsible-actor",
            "before_sha256": sha256_bytes(data),
            "before_span_sha256": sha256_bytes(b"The Carver's march"),
        },
        "rejected_claim": "The Carver's march",
        "replacement_fact": "The correct actor",
    })


def _authority_extract(base, client, system, user, model, max_tokens):
    """The fake extraction backend reflects only bytes supplied in its real prompt."""
    result = base.extract_render(client, system, user, model, max_tokens)
    if "CHAPTERS IN THIS CHUNK: 004-004" not in user:
        return result
    assert TRUTH in user
    return (result
            .replace("The march breaks against the gate.", TRUTH)
            .replace("The Carver's march ends at the gate.", "The correct actor's assault ends at the gate.")
            .replace("**The Carver's march** — The march breaks against the gate.",
                     "**The correct actor** — " + TRUTH)
            .replace("**The horde** — It has broken against the gate.",
                     "**The correct actor** — " + TRUTH)
            .replace("**Daz** — Is wounded in the fight.",
                     "**Daz** — The correct actor broke against the gate.")
            .replace("**Party** — The party holds the gate of Brindol.",
                     "**Party** — The correct actor broke against the gate."))


def _authority_prose(models, client, system, user, model, max_tokens):
    output = models.render(client, system, user, model, max_tokens)
    if TRUTH not in user:
        return output
    heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
    return output.rstrip() + f"\n\n{TRUTH} [ch 004 / 004.01]\n" if heading else output


def test_reviewed_source_correction_force_regenerates_all_projection_drafts(tmp_path: Path, monkeypatch):
    """Production build/extract/synth consumes the corrected source, never a draft patch."""
    root = cp.party_campaign(tmp_path)
    source = root / "docs" / "summaries" / "004-the-ring.md"
    source.write_text(source.read_text(encoding="utf-8").replace(
        "The Carver's march broke against the gate.",
        "<!-- anchor: earthstone-responsible-actor -->\nThe Carver's march broke against the gate.",
    ), encoding="utf-8")
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=1, records=[_ruling(source)]))

    generated = cp.range_dir(root) / "state" / "drafts" / "world_state.md"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated markdown is not an authority input\n", encoding="utf-8")
    proposal = create_proposal(root, "earthstone-ruling", summaries_dir=root / "docs" / "summaries")
    receipt = apply_proposal(root, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])
    receipt_path = root / "docs" / "authority" / "receipts" / f"{receipt['id']}.json"
    assert TRUTH in source.read_text(encoding="utf-8")
    assert generated.read_text(encoding="utf-8") == "generated markdown is not an authority input\n"

    base = cp.fake_party_models(monkeypatch)
    monkeypatch.setattr(cs.extract, "render_part", lambda *args: _authority_extract(base, *args))
    models = Models(base)
    monkeypatch.setattr(synth, "render_part", lambda *args: _authority_prose(models, *args))

    assert cs.run_cli(["build", *cp.common(root), "--force"])[0] == 0
    assert cs.run_cli(cp.extract_args(root, "--force"))[0] == 0
    for doc in ("world_state", "campaign_state", "party", "planning"):
        rc, _, err = cs.run_cli([*build(root, doc), "--force"])
        assert rc == 0, f"{doc}: {err}"
        draft = cp.range_dir(root) / "state" / "drafts" / f"{doc}.draft.md"
        assert TRUTH in draft.read_text(encoding="utf-8"), doc

    state = cp.range_dir(root) / "state"
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (state / "runs").glob("*/record.json")]
    synth_records = [r for r in records if r.get("step") == "synth"]
    assert {r["doc"] for r in synth_records} == {"world_state", "campaign_state", "party", "planning"}
    for record in synth_records:
        manifest = record["inputs"]["authority_manifest"]
        assert manifest["ledger_revision"] == 3
        assert manifest["records"][0]["id"] == "earthstone-ruling"
        assert manifest["records"][0]["source_sha256"] == receipt["after_source_sha256"]
        assert manifest["records"][0]["receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert generated.read_text(encoding="utf-8") == "generated markdown is not an authority input\n"

    # A metadata-only grant change leaves the authoritative source byte-for-byte
    # intact, yet makes the already-generated draft stale before it can be reused.
    before_metadata_change = source.read_bytes()
    ledger = load_ledger(root)
    updated = ledger.records[0].model_copy(update={
        "revision": ledger.records[0].revision + 1,
        "audience": AudienceGrant(grants={"gm", "players"}),
    })
    write_ledger(root, ledger.model_copy(update={"revision": ledger.revision + 1, "records": [updated]}))
    prose_calls = list(base.prose_calls)
    rc, _, err = cs.run_cli(build(root, "world_state"))
    assert rc == 2
    assert "authority inputs changed since this output" in err
    assert base.prose_calls == prose_calls
    assert source.read_bytes() == before_metadata_change

    # Rebuild once with the revised grant, then detect receipt byte drift while
    # the authoritative summary remains identical.
    assert cs.run_cli([*build(root, "world_state"), "--force"])[0] == 0
    changed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    changed_receipt["reviewer"] = "Second GM review"
    receipt_path.write_text(json.dumps(changed_receipt, sort_keys=True) + "\n", encoding="utf-8")
    prose_calls = list(base.prose_calls)
    rc, _, err = cs.run_cli(build(root, "world_state"))
    assert rc == 2
    assert "authority inputs changed since this output" in err
    assert base.prose_calls == prose_calls
    assert source.read_bytes() == before_metadata_change


def test_source_correction_requires_a_reviewed_note_digest_refresh_before_regeneration(tmp_path: Path, monkeypatch, capsys):
    """A correction changes source bytes; a classified note needs a visible revision."""
    root = cp.party_campaign(tmp_path)
    source = root / "docs" / "summaries" / "004-the-ring.md"
    source.write_text(source.read_text(encoding="utf-8").replace(
        "The Carver's march broke against the gate.",
        "<!-- anchor: earthstone-responsible-actor -->\nThe Carver's march broke against the gate.",
    ), encoding="utf-8")
    anchor = "earthstone-responsible-actor"
    classification = NoteRecord(
        id="earthstone-summary-classification", kind="note", revision=1,
        classification=Classification.CANON, subject=SubjectRef(kind="topic", id="earthstone"),
        effective=EffectiveInterval(from_chapter=4, through_chapter=4), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.WORLD_STATE, Projection.CAMPAIGN_STATE, Projection.PARTY, Projection.PLANNING},
        status="active", recorded_at="2026-10-09T00:00:00Z", recorded_by="GM",
        source={"path": "docs/summaries/004-the-ring.md", "anchor": anchor},
        content_digest=sha256_bytes(resolve_anchor_span(source.read_bytes(), anchor)),
        selection_label="Earthstone source classification",
    )
    write_ledger(root, AuthorityLedger(version=2, campaign="party-fixture", revision=1,
                                      records=[_ruling(source), classification]))
    proposal = create_proposal(root, "earthstone-ruling", summaries_dir=root / "docs" / "summaries")
    apply_proposal(root, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])

    base = cp.fake_party_models(monkeypatch)
    monkeypatch.setattr(cs.extract, "render_part", lambda *args: _authority_extract(base, *args))
    rc, _, err = cs.run_cli(cp.extract_args(root, "--force"))
    assert rc == 2 and "authority source section digest changed" in err

    revised = classification.model_copy(update={
        "revision": 2,
        "content_digest": sha256_bytes(resolve_anchor_span(source.read_bytes(), anchor)),
    })
    revision_file = root / "docs" / "authority" / "earthstone-summary-classification-r2.yaml"
    revision_file.parent.mkdir(parents=True, exist_ok=True)
    revision_file.write_text(yaml.safe_dump(revised.model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
    assert main(["authority", "record", "stage", str(revision_file), "--campaign-dir", str(root), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", ledger_digest(root), "--campaign-dir", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["revision"] == 2

    assert cs.run_cli(["build", *cp.common(root), "--force"])[0] == 0
    assert cs.run_cli(cp.extract_args(root, "--force"))[0] == 0
    models = Models(base)
    monkeypatch.setattr(synth, "render_part", lambda *args: _authority_prose(models, *args))
    for doc in ("world_state", "campaign_state", "party", "planning"):
        rc, _, err = cs.run_cli([*build(root, doc), "--force"])
        assert rc == 0, f"{doc}: {err}"
