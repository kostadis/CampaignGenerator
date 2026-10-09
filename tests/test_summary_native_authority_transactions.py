from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, RulingRecord, ledger_path, load_ledger, sha256_bytes
from pipelines.summary_native.authority_apply import (
    append_authority_event,
    authority_dir,
    create_proposal,
    initialize_ledger,
    journal_path,
    ledger_tip_path,
    pending_transaction,
    prepare_transaction,
    recover_transaction,
    apply_proposal,
    validate_ledger_tip,
)


def test_recovery_resumes_forward_and_is_idempotent(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    assert target.read_bytes() == b"after"
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"


def test_recovery_refuses_unexpected_target_bytes(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])
    target.write_bytes(b"operator edit")
    with pytest.raises(AuthorityError, match="AUTH_UNEXPECTED_RECOVERY_BYTES"):
        recover_transaction(tmp_path, journal["id"])


def test_recovery_rejects_tampered_approved_snapshot(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])
    (tmp_path / journal["targets"][0]["after_snapshot"]).write_bytes(b"tampered")
    with pytest.raises(AuthorityError, match="snapshot digest"):
        recover_transaction(tmp_path, journal["id"])


def test_recovery_verifies_every_after_snapshot_before_writing_any_target(tmp_path: Path):
    first = tmp_path / "docs" / "summaries" / "chapter-001.md"
    second = tmp_path / "docs" / "summaries" / "chapter-002.md"
    first.parent.mkdir(parents=True)
    first.write_bytes(b"one-before")
    second.write_bytes(b"two-before")
    journal = prepare_transaction(
        tmp_path,
        proposal_id="rule-r1",
        proposal_sha256="a" * 64,
        targets=[(first, b"one-before", b"one-after"), (second, b"two-before", b"two-after")],
    )
    (tmp_path / journal["targets"][1]["after_snapshot"]).write_bytes(b"tampered-after")

    with pytest.raises(AuthorityError, match="snapshot digest"):
        recover_transaction(tmp_path, journal["id"])

    assert first.read_bytes() == b"one-before"
    assert second.read_bytes() == b"two-before"


def test_recovery_distinguishes_an_absent_target_from_an_empty_before_snapshot(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"", b"created")])

    assert not target.exists()
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    assert target.read_bytes() == b"created"


def test_recovery_refuses_deleted_file_that_existed_with_empty_before_bytes(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"", b"created")])
    target.unlink()

    with pytest.raises(AuthorityError, match="AUTH_UNEXPECTED_RECOVERY_BYTES"):
        recover_transaction(tmp_path, journal["id"])


def test_journal_target_and_snapshot_paths_cannot_escape_campaign(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])
    path = journal_path(tmp_path, journal["id"])
    encoded = json.loads(path.read_text())
    encoded["targets"][0]["path"] = "/tmp/authority-outside.md"
    path.write_text(json.dumps(encoded))

    with pytest.raises(AuthorityError, match="outside campaign root"):
        recover_transaction(tmp_path, journal["id"])


def test_nonterminal_journal_blocks_readers_and_event_artifacts_are_immutable(tmp_path: Path):
    target = tmp_path / "docs" / "summaries" / "chapter-001.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(tmp_path, proposal_id="rule-r1", proposal_sha256="a" * 64, targets=[(target, b"before", b"after")])

    assert pending_transaction(tmp_path)["id"] == journal["id"]
    event_path = append_authority_event(tmp_path, reason="record-stage", actor="GM", before=b"before-ledger", after=b"after-ledger", transaction_id=journal["id"])
    event = json.loads(event_path.read_text())
    assert event["transaction_id"] == journal["id"]
    before_snapshot = tmp_path / event["before_snapshot"]
    assert before_snapshot.read_bytes() == b"before-ledger"
    with pytest.raises(AuthorityError, match="immutable"):
        # Same immutable identifier may only ever carry the same bytes.
        from pipelines.summary_native.authority_apply import write_json_immutable
        write_json_immutable(event_path, {**event, "actor": "someone-else"})


def test_recovery_rejects_invalid_transaction_id(tmp_path: Path):
    with pytest.raises(AuthorityError, match="invalid transaction id"):
        recover_transaction(tmp_path, "../../bad")


def _source_apply_fixture(root: Path):
    source = root / "docs" / "summaries" / "054-earthstone.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Chapter 54\n\n## Scenes\n\n### 054.01 Earthstone\n"
        "<!-- anchor: earthstone -->\nThe false steward acted.\n",
        encoding="utf-8",
    )
    ruling = RulingRecord.model_validate({
        "id": "earthstone-ruling", "kind": "ruling", "revision": 1, "classification": "RULED",
        "subject": {"kind": "topic", "id": "earthstone"},
        "effective": {"from_chapter": 54, "through_chapter": 54},
        "audience": {"grants": ["gm"]}, "projections": ["world_state"], "status": "draft",
        "recorded_at": "2026-10-09T00:00:00Z", "recorded_by": "GM",
        "source": {"path": "docs/summaries/054-earthstone.md", "anchor": "earthstone"},
        "rejected_claim": "false steward", "replacement_fact": "correct actor",
    })
    initialize_ledger(root, AuthorityLedger(version=1, campaign="fixture", revision=1, records=[ruling]), actor="GM")
    proposal = create_proposal(root, ruling.id, summaries_dir=source.parent)
    return source, proposal


@pytest.mark.parametrize(
    ("failpoint", "after_targets"),
    [
        ("before-source", 0),
        ("source", 1),
        ("ledger", 2),
        ("receipt", 3),
        ("approval", 4),
        ("tip", 5),
    ],
)
def test_source_apply_transaction_recovery_matrix_preserves_approved_history(tmp_path: Path, monkeypatch, failpoint, after_targets):
    """Every durable apply boundary recovers forward from the already-approved bytes."""
    import pipelines.summary_native.authority_apply as authority_apply

    source, proposal = _source_apply_fixture(tmp_path)
    real_prepare = authority_apply._prepare_transaction_locked
    real_write = authority_apply.atomic_write_bytes
    captured: dict[str, object] = {}

    def capture_prepare(*args, **kwargs):
        journal = real_prepare(*args, **kwargs)
        if kwargs["proposal_id"] == proposal["id"]:
            captured["journal"] = journal
            captured["target_paths"] = [Path(target["path"]).resolve() for target in journal["targets"]]
        return journal

    monkeypatch.setattr(authority_apply, "_prepare_transaction_locked", capture_prepare)
    writes = 0

    def crash_at_target(path, data):
        nonlocal writes
        resolved = Path(path).resolve()
        if resolved in captured.get("target_paths", []):
            writes += 1
            if failpoint == "before-source" and writes == 1:
                raise RuntimeError("simulated crash before source write")
            real_write(path, data)
            if writes == after_targets:
                raise RuntimeError(f"simulated crash after {failpoint} write")
            return
        real_write(path, data)

    monkeypatch.setattr(authority_apply, "atomic_write_bytes", crash_at_target)
    with pytest.raises(RuntimeError, match="simulated crash"):
        apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])

    journal = captured["journal"]
    target_names = [Path(target["path"]).name for target in journal["targets"]]
    assert target_names[:2] == ["054-earthstone.md", "authority.yaml"]
    assert target_names[2].startswith("receipt-")
    assert target_names[3].startswith("approval-")
    assert target_names[4] == "tip.json"
    assert pending_transaction(tmp_path)["id"] == journal["id"]
    assert writes == after_targets if failpoint != "before-source" else writes == 1

    monkeypatch.setattr(authority_apply, "atomic_write_bytes", real_write)
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    assert source.read_text(encoding="utf-8").endswith("The correct actor acted.\n")
    validate_ledger_tip(tmp_path)

    receipt_path = Path(journal["targets"][2]["path"])
    approval_path = Path(journal["targets"][3]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    ledger = load_ledger(tmp_path)
    ruling = next(record for record in ledger.records if record.id == "earthstone-ruling")
    assert ruling.status == "applied" and ruling.applied_receipt == receipt["id"]
    assert approval["proposal_sha256"] == proposal["proposal_sha256"]
    assert receipt["after_source_sha256"] == sha256_bytes(source.read_bytes())
    assert ledger_tip_path(tmp_path).is_file()


def test_source_apply_recovery_refuses_unexpected_remaining_target_bytes(tmp_path: Path, monkeypatch):
    import pipelines.summary_native.authority_apply as authority_apply

    source, proposal = _source_apply_fixture(tmp_path)
    real_prepare = authority_apply._prepare_transaction_locked
    real_write = authority_apply.atomic_write_bytes
    captured: dict[str, object] = {}

    def capture_prepare(*args, **kwargs):
        journal = real_prepare(*args, **kwargs)
        if kwargs["proposal_id"] == proposal["id"]:
            captured["journal"] = journal
            captured["target_paths"] = [Path(target["path"]).resolve() for target in journal["targets"]]
        return journal

    monkeypatch.setattr(authority_apply, "_prepare_transaction_locked", capture_prepare)
    writes = 0

    def crash_after_source(path, data):
        nonlocal writes
        if Path(path).resolve() in captured.get("target_paths", []):
            writes += 1
            real_write(path, data)
            if writes == 1:
                raise RuntimeError("simulated crash after source write")
            return
        real_write(path, data)

    monkeypatch.setattr(authority_apply, "atomic_write_bytes", crash_after_source)
    with pytest.raises(RuntimeError, match="after source"):
        apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])

    journal = captured["journal"]
    ledger = ledger_path(tmp_path)
    operator_bytes = b"operator changed pending ledger\n"
    ledger.write_bytes(operator_bytes)
    monkeypatch.setattr(authority_apply, "atomic_write_bytes", real_write)
    with pytest.raises(AuthorityError, match="AUTH_UNEXPECTED_RECOVERY_BYTES"):
        recover_transaction(tmp_path, journal["id"])
    assert ledger.read_bytes() == operator_bytes
    assert source.read_text(encoding="utf-8").endswith("The correct actor acted.\n")
