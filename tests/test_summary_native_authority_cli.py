from __future__ import annotations

import json
import hashlib
from pathlib import Path

import yaml

from pipelines.summary_native.authority import (AuthorityLedger, NoteRecord, RulingRecord,
                                                ledger_bytes, ledger_digest, write_ledger)
from pipelines.summary_native.authority_apply import authority_dir, write_ledger_tip
from pipelines.summary_native.cli import main


def test_authority_init_validate_status_json(tmp_path, capsys):
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["code"] == "OK"
    assert main(["authority", "validate", "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert main(["authority", "status", "--campaign-dir", str(tmp_path), "--json"]) == 0


def _draft(state: Path, doc: str, run_id: str, ledger_sha256: str) -> Path:
    """A draft and the run record its header names, as synth lays them out."""
    run = state / "runs" / run_id
    run.mkdir(parents=True)
    (run / "record.json").write_text(json.dumps({
        "doc": doc, "inputs": {"authority_manifest": {"ledger_sha256": ledger_sha256}},
    }))
    draft = state / "drafts" / f"{doc}.draft.md"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(f"<!-- summary_native draft | doc: {doc} | record: runs/{run_id}/record.json -->\nGM-only prose\n")
    return draft


def test_authority_status_reports_stale_projection_metadata_only(tmp_path, capsys):
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    state = tmp_path / "docs" / "grounding" / "ch001-001" / "state"
    draft = _draft(state, "planning", "20261001T000000Z", first["data"]["sha256"])
    # A ledger digest change is enough to stale an existing derived draft.
    ledger = tmp_path / "docs" / "authority.yaml"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
    assert main(["authority", "status", "--campaign-dir", str(tmp_path), "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["data"]["stale_projections"] == [{
        "doc": "planning", "draft": str(draft), "reason": "authority inputs changed since this output",
    }]
    assert "GM-only prose" not in out


def test_stale_projections_follow_the_run_that_wrote_each_draft(tmp_path, capsys):
    """Old runs never linger, a later non-writing run never hides a stale draft, and audiences count."""
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    current = json.loads(capsys.readouterr().out)["data"]["sha256"]
    state = tmp_path / "docs" / "grounding" / "ch001-002" / "state"
    # world_state: an old stale run, then a fresh synth whose draft is current -> not listed.
    old = state / "runs" / "20261001T000000Z"; old.mkdir(parents=True)
    (old / "record.json").write_text(json.dumps({"doc": "world_state", "inputs": {"authority_manifest": {"ledger_sha256": "old"}}}))
    _draft(state, "world_state", "20261002T000000Z", current)
    # planning: the draft is stale; a later dump-only run with the current ledger wrote no draft.
    stale_planning = _draft(state, "planning", "20261001T000001Z", "old")
    later = state / "runs" / "20261003T000000Z"; later.mkdir()
    (later / "record.json").write_text(json.dumps({"doc": "planning", "inputs": {"authority_manifest": {"ledger_sha256": current}}}))
    # a players-audience draft lives under its own state directory.
    players = _draft(state / "audiences" / "players", "party", "20261001T000000Z", "old")
    # a run whose draft was removed is not reported.
    gone = state / "runs" / "20261004T000000Z"; gone.mkdir()
    (gone / "record.json").write_text(json.dumps({"doc": "campaign_state", "inputs": {"authority_manifest": {"ledger_sha256": "old"}}}))

    assert main(["authority", "status", "--campaign-dir", str(tmp_path), "--json"]) == 0
    stale = json.loads(capsys.readouterr().out)["data"]["stale_projections"]
    assert sorted(item["draft"] for item in stale) == sorted([str(stale_planning), str(players)])


def test_authority_apply_requires_digest_flag(tmp_path):
    # argparse itself enforces the digest checkpoint before backend work.
    try:
        main(["authority", "apply", "rule", "--campaign-dir", str(tmp_path)])
    except SystemExit as exc:
        assert exc.code == 2


def test_authority_notes_preview_returns_stable_membership_json(tmp_path, capsys):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "plan.md").write_text("GM plan\n")
    assert main([
        "authority", "notes", "preview", "--campaign-dir", str(tmp_path),
        "--selector", "current=notes/plan.md", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["audience"] == "gm"
    assert payload["data"]["members"][0]["reason"] == "selector:current"
    assert payload["data"]["membership_digest"]


def test_document_support_stage_requires_the_whole_file_digest(tmp_path, capsys):
    support = tmp_path / "config" / "players.yaml"
    support.parent.mkdir()
    support.write_text("players: []\n", encoding="utf-8")
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    record = tmp_path / "support.yaml"
    record.write_text("\n".join([
        "id: players-support", "kind: note", "revision: 1", "classification: CANON",
        "subject: {kind: topic, id: players-support}", "effective: {from_chapter: 1}",
        "audience: {grants: [players]}", "projections: [party]", "status: active",
        "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
        "source: {path: config/players.yaml, anchor: __document__}",
        f"content_digest: '{hashlib.sha256(support.read_bytes()).hexdigest()}'",
        "selection_label: Players support", "",
    ]), encoding="utf-8")
    assert main(["authority", "record", "stage", str(record), "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["record"]["source"]["anchor"] == "__document__"

    record.write_text(record.read_text(encoding="utf-8").replace(hashlib.sha256(support.read_bytes()).hexdigest(), "0" * 64), encoding="utf-8")
    assert main(["authority", "record", "stage", str(record), "--campaign-dir", str(tmp_path), "--json"]) == 2
    assert "whole-file SHA-256" in json.loads(capsys.readouterr().out)["message"]


def test_validate_refuses_manual_ledger_edit_after_staged_note_apply(tmp_path, capsys):
    """The event tip binds the live ledger, including note-only mutations."""
    note = tmp_path / "notes" / "plan.md"; note.parent.mkdir()
    section = b"<!-- anchor: plan -->\nUse the west gate.\n"
    note.write_bytes(section)
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    init = json.loads(capsys.readouterr().out)
    record_file = tmp_path / "note.yaml"
    record_file.write_text(
        "\n".join([
            "id: west-gate", "kind: note", "revision: 1", "classification: PREP",
            "subject: {kind: topic, id: gate}", "effective: {horizon: future}",
            "audience: {grants: [gm]}", "projections: [planning]", "status: active",
            "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
            "source: {path: notes/plan.md, anchor: plan}",
            f"content_digest: {hashlib.sha256(section).hexdigest()}",
            "planning_date: chapter-1", "selection_label: West gate", "",
        ]), encoding="utf-8")
    assert main(["authority", "record", "stage", str(record_file), "--campaign-dir", str(tmp_path), "--json"]) == 0
    stage = json.loads(capsys.readouterr().out)["data"]
    assert main([
        "authority", "record", "apply", stage["id"], "--stage-sha256", stage["sha256"],
        "--expected-ledger-sha256", init["data"]["sha256"], "--campaign-dir", str(tmp_path), "--json",
    ]) == 0
    capsys.readouterr()
    # The init event shares the directory, and glob order is the filesystem's: pick by reason.
    events = [json.loads(path.read_text()) for path in (tmp_path / "docs" / "authority" / "events").glob("event-*.json")]
    assert [event["record_id"] for event in events if event["reason"] == "record-apply"] == ["west-gate"]
    ledger = tmp_path / "docs" / "authority.yaml"
    ledger.write_text(ledger.read_text(encoding="utf-8") + "\n# unrecorded manual edit\n", encoding="utf-8")
    assert main(["authority", "validate", "--campaign-dir", str(tmp_path), "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "AUTH_STALE" and "mutation-history tip" in payload["message"]


def _stage_note(tmp_path, capsys, *, identifier: str, revision: int, digest: str):
    record = tmp_path / f"{identifier}-{revision}.yaml"
    record.write_text(
        "\n".join([
            f"id: {identifier}", "kind: note", f"revision: {revision}", "classification: PREP",
            "subject: {kind: topic, id: gate}", "effective: {horizon: future}",
            "audience: {grants: [gm]}", "projections: [planning]", "status: active",
            "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
            "source: {path: notes/plan.md, anchor: plan}",
            f"content_digest: {digest}", "planning_date: chapter-1", "selection_label: West gate", "",
        ]), encoding="utf-8")
    assert main(["authority", "record", "stage", str(record), "--campaign-dir", str(tmp_path), "--json"]) == 0
    return json.loads(capsys.readouterr().out)["data"]


def test_staged_note_revision_replaces_next_revision_and_refreshes_content_digest(tmp_path, capsys):
    note = tmp_path / "notes" / "plan.md"; note.parent.mkdir()
    first = b"<!-- anchor: plan -->\nUse the west gate.\n"
    note.write_bytes(first)
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    current = json.loads(capsys.readouterr().out)["data"]["sha256"]
    staged = _stage_note(tmp_path, capsys, identifier="west-gate", revision=1, digest=hashlib.sha256(first).hexdigest())
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", current, "--campaign-dir", str(tmp_path), "--json"]) == 0
    applied = json.loads(capsys.readouterr().out)["data"]
    assert applied == {"id": "west-gate", "revision": 1, "ledger_revision": 2}

    second = b"<!-- anchor: plan -->\nUse the east gate.\n"
    note.write_bytes(second)
    staged = _stage_note(tmp_path, capsys, identifier="west-gate", revision=2, digest=hashlib.sha256(second).hexdigest())
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)["data"]
    assert payload == {"id": "west-gate", "revision": 2, "ledger_revision": 3}
    assert main(["authority", "show", "west-gate", "--campaign-dir", str(tmp_path), "--json"]) == 0
    revised = json.loads(capsys.readouterr().out)["data"]["record"]
    assert revised["revision"] == 2
    assert revised["content_digest"] == hashlib.sha256(second).hexdigest()
    assert main(["authority", "history", "west-gate", "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert any(event["reason"] == "record-revise" for event in json.loads(capsys.readouterr().out)["data"]["events"])


def test_retire_refuses_draft_ruling_without_an_applied_receipt(tmp_path, capsys):
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    current = json.loads(capsys.readouterr().out)["data"]["sha256"]
    ruling = tmp_path / "draft-ruling.yaml"
    ruling.write_text("\n".join([
        "id: draft-ruling", "kind: ruling", "revision: 1", "classification: RULED",
        "subject: {kind: topic, id: gate}", "effective: {from_chapter: 1}",
        "audience: {grants: [gm]}", "projections: [world_state]", "status: draft",
        "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
        "source: {path: docs/summaries/001.md, anchor: gate}",
        "rejected_claim: west gate", "replacement_fact: east gate", "",
    ]), encoding="utf-8")
    assert main(["authority", "record", "stage", str(ruling), "--campaign-dir", str(tmp_path), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", current, "--campaign-dir", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert main(["authority", "record", "retire", "draft-ruling", "--reason", "bad draft",
                 "--expected-revision", "1", "--expected-ledger-sha256", ledger_digest(tmp_path),
                 "--campaign-dir", str(tmp_path), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "AUTH_VALIDATION"
    assert "only an applied ruling" in payload["message"]


def test_proposed_ruling_revision_resets_review_and_refuses_old_proposal(tmp_path, capsys):
    source = tmp_path / "docs" / "summaries" / "001-earthstone.md"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# Chapter 1\n\n## Scenes\n\n### 001.01 Earthstone\n<!-- anchor: earthstone -->\nThe false steward acted.\n")
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    initial_digest = json.loads(capsys.readouterr().out)["data"]["sha256"]
    draft = tmp_path / "earthstone-r1.yaml"
    draft.write_text("\n".join([
        "id: earthstone-ruling", "kind: ruling", "revision: 1", "classification: RULED",
        "subject: {kind: topic, id: earthstone}", "effective: {from_chapter: 1}",
        "audience: {grants: [gm]}", "projections: [world_state]", "status: draft",
        "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
        "source: {path: docs/summaries/001-earthstone.md, anchor: earthstone}",
        "rejected_claim: false steward", "replacement_fact: correct actor", "",
    ]), encoding="utf-8")
    assert main(["authority", "record", "stage", str(draft), "--campaign-dir", str(tmp_path), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", initial_digest, "--campaign-dir", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    assert main(["authority", "propose", "earthstone-ruling", "--summaries-dir", str(source.parent),
                 "--campaign-dir", str(tmp_path), "--json"]) == 0
    old_proposal = json.loads(capsys.readouterr().out)["data"]

    revised = tmp_path / "earthstone-r2.yaml"
    revised.write_text(draft.read_text(encoding="utf-8").replace("revision: 1", "revision: 2").replace("correct actor", "the true actor"), encoding="utf-8")
    assert main(["authority", "record", "stage", str(revised), "--campaign-dir", str(tmp_path), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["revision"] == 2
    assert main(["authority", "apply", "earthstone-ruling", "--proposal-sha256", old_proposal["proposal_sha256"],
                 "--campaign-dir", str(tmp_path), "--json"]) == 3
    refused = json.loads(capsys.readouterr().out)
    assert refused["code"] == "AUTH_STALE"
    assert "no staged proposal" in refused["message"]


def test_conflicts_json_resolution_and_history_use_exact_event_references(tmp_path, capsys):
    def note(identifier: str, value: str) -> NoteRecord:
        return NoteRecord.model_validate({
            "id": identifier, "kind": "note", "revision": 1, "classification": "CANON",
            "subject": {"kind": "topic", "id": "gate"}, "claim_key": "open",
            "normalized_value": value, "effective": {"from_chapter": 1, "through_chapter": 3},
            "audience": {"grants": ["gm"]}, "projections": ["planning"], "status": "active",
            "recorded_at": "2026-10-09T00:00:00Z", "recorded_by": "GM",
            "source": {"path": f"notes/{identifier}.md", "anchor": identifier},
            "content_digest": "0" * 64, "selection_label": identifier,
        })
    resolution = RulingRecord.model_validate({
        "id": "gate-resolution", "kind": "ruling", "revision": 1, "classification": "RULED",
        "subject": {"kind": "topic", "id": "gate"}, "effective": {"from_chapter": 1, "through_chapter": 3},
        "audience": {"grants": ["gm"]}, "projections": ["planning"], "status": "applied",
        "recorded_at": "2026-10-09T00:00:00Z", "recorded_by": "GM",
        "source": {"path": "docs/summaries/001.md", "anchor": "gate"}, "rejected_claim": "closed",
        "replacement_fact": "open", "proposal_id": "proposal-gate", "applied_receipt": "receipt-gate",
    })
    plan = note("plan", "open")
    ledger = AuthorityLedger(version=2, campaign="fixture", revision=1,
                             records=[plan, note("gate-open", "open"), note("gate-closed", "closed"), resolution])
    write_ledger(tmp_path, ledger)
    write_ledger_tip(tmp_path, event_id="seed", after=ledger_bytes(ledger))
    events = authority_dir(tmp_path) / "events"; events.mkdir(parents=True, exist_ok=True)
    (events / "event-unrelated.json").write_text(json.dumps({"id": "event-unrelated", "record_id": "plan-old", "reason": "mentions plan"}))
    (events / "event-plan.json").write_text(json.dumps({"id": "event-plan", "record_id": "plan", "reason": "ordinary"}))

    assert main(["authority", "conflicts", "--campaign-dir", str(tmp_path), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    conflict = next(item for item in listed["data"]["conflicts"] if item["basis"] == "structured_value")
    assert set(conflict["record_ids"]) == {"gate-open", "gate-closed"}

    resolution_file = tmp_path / "resolution.yaml"
    resolution_file.write_text(yaml.safe_dump(resolution.model_dump(mode="json", exclude_none=True), sort_keys=False), encoding="utf-8")
    assert main(["authority", "conflict", "resolve", conflict["id"], "--resolution-record", str(resolution_file),
                 "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"]) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["data"]["conflict"]["status"] == "resolved"
    assert main(["authority", "conflict", "history", conflict["id"], "--campaign-dir", str(tmp_path), "--json"]) == 0
    history = json.loads(capsys.readouterr().out)["data"]
    assert history["events"][0]["conflict_id"] == conflict["id"]

    assert main(["authority", "history", "plan", "--campaign-dir", str(tmp_path), "--json"]) == 0
    record_history = json.loads(capsys.readouterr().out)["data"]["events"]
    assert [event["id"] for event in record_history] == ["event-plan"]


def _ruling_yaml(path, *, identifier: str = "gate-ruling", status: str = "draft", extra: tuple[str, ...] = ()):
    path.write_text("\n".join([
        f"id: {identifier}", "kind: ruling", "revision: 1", "classification: RULED",
        "subject: {kind: topic, id: gate}", "effective: {from_chapter: 1}",
        "audience: {grants: [gm]}", "projections: [world_state]", f"status: {status}",
        "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
        "source: {path: docs/summaries/001.md, anchor: gate}",
        "rejected_claim: west gate", "replacement_fact: east gate", *extra, "",
    ]), encoding="utf-8")
    return path


def test_record_apply_refuses_a_new_ruling_staged_past_draft(tmp_path, capsys):
    """Applied is reached only through propose and apply, which rewrite the summary and write the receipt."""
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    current = json.loads(capsys.readouterr().out)["data"]["sha256"]
    ruling = _ruling_yaml(tmp_path / "applied.yaml", status="applied", extra=("proposal_id: made-up", "applied_receipt: made-up"))
    assert main(["authority", "record", "stage", str(ruling), "--campaign-dir", str(tmp_path), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    assert main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                 "--expected-ledger-sha256", current, "--campaign-dir", str(tmp_path), "--json"]) == 2
    assert "must be staged as a draft" in json.loads(capsys.readouterr().out)["message"]
    assert main(["authority", "list", "--campaign-dir", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["records"] == []


def test_record_and_conflict_mutations_refuse_a_pending_transaction_or_unrecorded_edit(tmp_path, capsys):
    from pipelines.summary_native.authority_apply import prepare_transaction

    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    ruling = _ruling_yaml(tmp_path / "draft.yaml")
    assert main(["authority", "record", "stage", str(ruling), "--campaign-dir", str(tmp_path), "--json"]) == 0
    staged = json.loads(capsys.readouterr().out)["data"]
    apply = lambda: main(["authority", "record", "apply", staged["id"], "--stage-sha256", staged["sha256"],
                          "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"])
    dismiss = lambda: main(["authority", "conflict", "dismiss", "any-conflict", "--reason", "noise",
                            "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"])

    # A hand edit is not accepted history: no new tip is written over it.
    ledger = tmp_path / "docs" / "authority.yaml"
    original = ledger.read_bytes()
    ledger.write_bytes(original + b"# unrecorded manual edit\n")
    for command in (apply, dismiss):
        assert command() == 3
        assert "mutation-history tip" in json.loads(capsys.readouterr().out)["message"]
    ledger.write_bytes(original)

    # A half-finished transaction must be recovered before anything else writes.
    pending = prepare_transaction(tmp_path, proposal_id="p", proposal_sha256="0" * 64,
                                  targets=[(tmp_path / "notes.txt", b"", b"pending\n")])
    for command in (apply, dismiss):
        assert command() == 4
        assert pending["id"] in json.loads(capsys.readouterr().out)["message"]
    assert ledger.read_bytes() == original


def test_malformed_input_is_reported_in_the_json_envelope_not_a_traceback(tmp_path, capsys):
    assert main(["authority", "init", "--campaign-dir", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    bad = _ruling_yaml(tmp_path / "bad.yaml", identifier="Gate_Ruling")
    assert main(["authority", "record", "stage", str(bad), "--campaign-dir", str(tmp_path), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False and payload["code"] == "AUTH_VALIDATION"
    assert "stable lowercase slug" in payload["message"]

    assert main(["authority", "record", "apply", "stage-missing", "--stage-sha256", "0" * 64,
                 "--expected-ledger-sha256", ledger_digest(tmp_path), "--campaign-dir", str(tmp_path), "--json"]) == 3
    assert "no readable staged record" in json.loads(capsys.readouterr().out)["message"]
