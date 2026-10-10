from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    ConflictFinding,
    NoteRecord,
    ReviewDecisionRecord,
    detect_conflicts,
    load_ledger,
    sha256_bytes,
    validate_record_identity,
    write_ledger,
)
from pipelines.summary_native.authority_apply import prepare_transaction, recover_transaction
from pipelines.summary_native.authority_inputs import resolve_anchored_records, resolve_planning_precedence
from pipelines.summary_native.review.migrate import apply_authority_migration, plan_authority_migration
from pipelines.summary_native.review.models import ReviewItem, canonical_bytes


def _v1_ledger(*, proposed: bool = False) -> bytes:
    record = {
        "id": "earthstone-ruling",
        "kind": "ruling",
        "revision": 1,
        "classification": "RULED",
        "subject": {"kind": "topic", "id": "earthstone"},
        "effective": {"from_chapter": 54, "through_chapter": 54},
        "audience": {"grants": ["gm"]},
        "projections": ["world_state"],
        "status": "proposed" if proposed else "draft",
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "source": {"path": "docs/summaries/054.md", "anchor": "earthstone"},
        "rejected_claim": "false steward",
        "replacement_fact": "correct actor",
    }
    if proposed:
        record["proposal_id"] = "earthstone-proposal"
    return yaml.safe_dump(
        {"version": 1, "campaign": "fixture", "revision": 3, "records": [record], "conflicts": []},
        sort_keys=False,
    ).encode("utf-8")


def _campaign(tmp_path: Path, *, proposed: bool = False) -> tuple[Path, bytes, bytes]:
    ledger = tmp_path / "docs" / "authority.yaml"
    ledger.parent.mkdir(parents=True)
    before = _v1_ledger(proposed=proposed)
    ledger.write_bytes(before)
    tip = tmp_path / "docs" / "authority" / "events" / "tip.json"
    tip.parent.mkdir(parents=True)
    tip.write_text(json.dumps({"event_id": "legacy-tip", "ledger_sha256": sha256_bytes(before)}) + "\n")
    registry = tmp_path / "docs" / "entity_registry.yaml"
    registry_bytes = b"version: 1\nentities: []\n"
    registry.write_bytes(registry_bytes)
    return ledger, before, registry_bytes


def test_v1_to_v2_dry_run_is_digest_bound_and_preserves_archival_bytes(tmp_path: Path):
    ledger_path, before, registry_before = _campaign(tmp_path, proposed=True)

    plan = plan_authority_migration(tmp_path)
    assert plan["from_version"] == 1 and plan["to_version"] == 2
    assert plan["before_sha256"] == sha256_bytes(before)
    assert plan["stale_source_proposals"] == ["earthstone-proposal"]

    result = apply_authority_migration(tmp_path, plan_sha256=plan["plan_sha256"])
    migrated = load_ledger(tmp_path)
    assert migrated.version == 2 and migrated.revision == 4
    assert len(migrated.records) == 1 and len(migrated.conflicts) == 0
    archive = tmp_path / result["archive_path"]
    assert archive.read_bytes() == before
    assert (tmp_path / "docs" / "entity_registry.yaml").read_bytes() == registry_before
    assert result["before_sha256"] == sha256_bytes(before)
    assert result["after_sha256"] == sha256_bytes(ledger_path.read_bytes())

    repeated = apply_authority_migration(tmp_path, plan_sha256=plan["plan_sha256"])
    assert repeated["event_id"] == result["event_id"]
    assert ledger_path.read_bytes() == yaml.safe_dump(
        migrated.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True
    ).encode("utf-8")


def test_migration_refuses_stale_plan_without_writing(tmp_path: Path):
    ledger_path, _, _ = _campaign(tmp_path)
    plan = plan_authority_migration(tmp_path)
    ledger_path.write_bytes(_v1_ledger().replace(b"revision: 3", b"revision: 4"))
    changed = ledger_path.read_bytes()
    tip = tmp_path / "docs" / "authority" / "events" / "tip.json"
    tip.write_text(json.dumps({"event_id": "later-tip", "ledger_sha256": sha256_bytes(changed)}) + "\n")

    with pytest.raises(AuthorityError, match="MIGRATION_STALE"):
        apply_authority_migration(tmp_path, plan_sha256=plan["plan_sha256"])

    assert ledger_path.read_bytes() == changed


def test_migration_refuses_unknown_v1_fields(tmp_path: Path):
    ledger_path, before, _ = _campaign(tmp_path)
    raw = yaml.safe_load(before)
    raw["invented"] = True
    ledger_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    changed = ledger_path.read_bytes()
    tip = tmp_path / "docs" / "authority" / "events" / "tip.json"
    tip.write_text(json.dumps({"event_id": "legacy-tip", "ledger_sha256": sha256_bytes(changed)}) + "\n")

    with pytest.raises(AuthorityError, match="unknown|extra",):
        plan_authority_migration(tmp_path)


def test_migration_refuses_v1_ledger_that_differs_from_history_tip(tmp_path: Path):
    ledger_path, _, _ = _campaign(tmp_path)
    ledger_path.write_bytes(ledger_path.read_bytes().replace(b"revision: 3", b"revision: 4"))

    with pytest.raises(AuthorityError, match="mutation-history tip"):
        plan_authority_migration(tmp_path)


def test_migration_refuses_pending_v1_transaction_until_compatible_recovery(tmp_path: Path):
    _campaign(tmp_path)
    target = tmp_path / "docs" / "pending.txt"
    target.write_bytes(b"before")
    journal = prepare_transaction(
        tmp_path,
        proposal_id="legacy",
        proposal_sha256="f" * 64,
        targets=[(target, b"before", b"after")],
    )
    path = tmp_path / "docs" / "authority" / "transactions" / f"{journal['id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("version")
    for item in payload["targets"]:
        item.pop("operation")
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(AuthorityError, match="authority recover"):
        plan_authority_migration(tmp_path)

    recover_transaction(tmp_path, journal["id"])
    assert plan_authority_migration(tmp_path)["from_version"] == 1


def test_completed_migration_retry_revalidates_live_ledger_and_tip(tmp_path: Path):
    ledger_path, _, _ = _campaign(tmp_path)
    plan = plan_authority_migration(tmp_path)
    apply_authority_migration(tmp_path, plan_sha256=plan["plan_sha256"])
    ledger_path.write_bytes(ledger_path.read_bytes().replace(b"revision: 4", b"revision: 5"))

    with pytest.raises(AuthorityError, match="mutation-history tip"):
        apply_authority_migration(tmp_path, plan_sha256=plan["plan_sha256"])


def _review_item(*, domain="duplicate_identity",
                 subject_id="10000000-0000-4000-8000-000000000001") -> ReviewItem:
    return ReviewItem(
        item_id="earthstone-pair",
        revision=1,
        campaign_id=UUID("11111111-1111-4111-8111-111111111111"),
        review_id="duplicate-review",
        domain=domain,
        subject_ref={
            "kind": "entity",
            "subject_id": UUID(subject_id),
            "registry_name": "Earthstone",
            "registry_type": "npc",
            "registry_snapshot_sha256": "a" * 64,
        },
        occurrence_id=UUID("20000000-0000-4000-8000-000000000001"),
        locator={
            "source_path": "docs/summaries/054.md",
            "anchor": "earthstone",
            "display_line": 1,
        },
        claim_text="The two Earthstone references may name one person.",
        evidence=({
            "source_id": "summary-54",
            "source_path": "docs/summaries/054.md",
            "anchor": "earthstone",
            "exact_excerpt": "Earthstone",
            "selected_span_sha256": "b" * 64,
            "citation_resolved": True,
        },),
        diagnostics=({
            "diagnostic_id": "duplicate-candidate",
            "legacy_code": "duplicate-candidate",
            "message": "Candidate identity pair needs a GM ruling",
            "blocking": False,
        },),
        categories={"unsupported_or_contradicted"},
        severity="needs_judgment",
        assignment_basis="gm_confirmed",
        rationale="The names and evidence require an identity ruling.",
        proposed_action={"action": "review_identity"},
        scope={"kind": "global"},
        rule_versions=({"rule_id": "identity-review", "version": "1"},),
        input_bindings=({
            "source_id": "summary-54",
            "path": "docs/summaries/054.md",
            "custody_sha256": "c" * 64,
            "semantic_sha256": "d" * 64,
        },),
    )


def _review_decision(*, disposition="distinct", proposal=None, receipt=None) -> ReviewDecisionRecord:
    return ReviewDecisionRecord.model_validate({
        "id": "review-earthstone-accepted",
        "kind": "review_decision",
        "revision": 1,
        "classification": "RULED",
        "subject": {"kind": "entity", "id": "10000000-0000-4000-8000-000000000001"},
        "claim_key": "earthstone.identity",
        "normalized_value": "Earthstone",
        "effective": {"horizon": "open"},
        "audience": {"grants": ["gm"]},
        "projections": ["planning", "world_state"],
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "status": "accepted",
        "campaign_id": "11111111-1111-4111-8111-111111111111",
        "review_id": "duplicate-review",
        "item_id": "earthstone-pair",
        "item_revision": 1,
        "event_id": "decision-event-one",
        "decision_revision": 1,
        "event_digest": "1" * 64,
        "review_digest": _review_item().review_digest,
        "domain": "duplicate_identity",
        "disposition": disposition,
        **({"proposal": proposal} if proposal is not None else {}),
        **({"receipt": receipt} if receipt is not None else {}),
    })


def _canonical_json(value: dict, *, exclude: str | None = None) -> bytes:
    payload = {key: item for key, item in value.items() if key != exclude}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_review_references(tmp_path: Path, review: ReviewDecisionRecord, *,
                             item_domain: str = "duplicate_identity",
                             subject_id: str = "10000000-0000-4000-8000-000000000001",
                             event_overrides: dict | None = None) -> ReviewDecisionRecord:
    review_root = tmp_path / "docs" / "reviews" / review.review_id
    (review_root / "items" / review.item_id).mkdir(parents=True, exist_ok=True)
    (review_root / "events").mkdir(exist_ok=True)
    (review_root / "manifest.json").write_bytes(_canonical_json({
        "campaign_id": str(review.campaign_id), "review_id": review.review_id,
    }))
    item = _review_item(domain=item_domain, subject_id=subject_id)
    (review_root / "items" / review.item_id / f"{review.item_revision}.json").write_bytes(
        canonical_bytes(item)
    )
    event = {
        "campaign_id": str(review.campaign_id), "review_id": review.review_id,
        "event_id": review.event_id, "item_id": review.item_id,
        "item_revision": review.item_revision, "review_digest": review.review_digest,
        "decision_revision": review.decision_revision, "verdict": "approve",
        "disposition": review.disposition, "reviewer": review.recorded_by,
        "recorded_at": "2026-10-09T00:00:00Z", "authority_record_id": review.id,
    }
    if review.proposal is not None:
        event.update({"proposal_id": review.proposal.id, "proposal_digest": review.proposal.digest})
    event.update(event_overrides or {})
    event_bytes = _canonical_json(event)
    (review_root / "events" / f"{review.event_id}.json").write_bytes(event_bytes)
    return review.model_copy(update={"event_digest": sha256_bytes(event_bytes)})


def test_review_decision_is_strict_audit_only_and_historical_identity_is_stable(tmp_path: Path):
    support = tmp_path / "notes" / "support.md"
    support.parent.mkdir(parents=True)
    support.write_bytes(b"planning evidence\n")
    note = NoteRecord.model_validate({
        "id": "planning-note",
        "kind": "note",
        "revision": 1,
        "classification": "PREP",
        "subject": {"kind": "topic", "id": "earthstone"},
        "effective": {"horizon": "future"},
        "audience": {"grants": ["gm"]},
        "projections": ["planning"],
        "recorded_at": "2026-10-09T00:00:00Z",
        "recorded_by": "GM",
        "status": "active",
        "source": {"path": "notes/support.md", "anchor": "__document__"},
        "content_digest": sha256_bytes(support.read_bytes()),
        "planning_date": "chapter-55",
        "selection_label": "Earthstone planning",
    })
    review = _write_review_references(tmp_path, _review_decision())
    write_ledger(tmp_path, AuthorityLedger(version=2, campaign="fixture", revision=4, records=[note, review]))

    loaded = load_ledger(tmp_path)
    assert isinstance(loaded.records[1], ReviewDecisionRecord)
    assert [record.id for record in resolve_anchored_records(loaded, audience="gm")] == [note.id]
    assert [record.id for record in resolve_planning_precedence(loaded.records)[0]] == [note.id]
    assert detect_conflicts(loaded) == []
    # The removed loser is validated through its immutable review/event
    # binding, not through the current entity registry.
    validate_record_identity(tmp_path, review)

    raw = review.model_dump(mode="json", exclude_none=True)
    raw["source"] = {"path": "docs/summaries/054.md", "anchor": "earthstone"}
    with pytest.raises(Exception, match="extra"):
        ReviewDecisionRecord.model_validate(raw)


def test_review_decision_cannot_be_used_as_a_conflict_fact():
    review = _review_decision()
    finding = ConflictFinding(
        id="audit-conflict",
        record_ids={review.id, "planning-note"},
        basis="human_identified",
        projections={"planning"},
    )
    note = NoteRecord.model_validate({
        "id": "planning-note", "kind": "note", "revision": 1, "classification": "PREP",
        "subject": {"kind": "topic", "id": "earthstone"}, "effective": {"horizon": "future"},
        "audience": {"grants": ["gm"]}, "projections": ["planning"], "status": "active",
        "recorded_at": "2026-10-09T00:00:00Z", "recorded_by": "GM",
        "source": {"path": "notes/support.md", "anchor": "__document__"},
        "content_digest": "3" * 64, "planning_date": "chapter-55", "selection_label": "Plan",
    })
    with pytest.raises(Exception, match="audit-only"):
        AuthorityLedger(version=2, campaign="fixture", revision=1, records=[review, note], conflicts=[finding])


@pytest.mark.parametrize(
    ("record_update", "message"),
    [
        ({"domain": "npc_finding"}, "domain"),
        ({"subject": {"kind": "entity", "id": "20000000-0000-4000-8000-000000000002"}}, "subject"),
    ],
)
def test_review_decision_refuses_unrelated_valid_item(tmp_path: Path, record_update, message):
    review = _write_review_references(tmp_path, _review_decision())
    if "subject" in record_update:
        record_update = {
            **record_update,
            "subject": review.subject.model_validate(record_update["subject"]),
        }
    review = review.model_copy(update=record_update)
    with pytest.raises(AuthorityError, match=message):
        validate_record_identity(tmp_path, review)


def test_review_decision_recomputes_immutable_item_semantic_digest(tmp_path: Path):
    review = _write_review_references(tmp_path, _review_decision())
    item_path = (
        tmp_path / "docs" / "reviews" / review.review_id / "items"
        / review.item_id / f"{review.item_revision}.json"
    )
    item = json.loads(item_path.read_bytes())
    item["rationale"] = "Edited after the GM decision."
    item_path.write_bytes(_canonical_json(item))

    with pytest.raises(AuthorityError, match="review_digest does not match the semantic payload"):
        validate_record_identity(tmp_path, review)


def test_review_decision_recomputes_proposal_digest_and_binds_event(tmp_path: Path):
    base = _review_decision(disposition="merge")
    proposal = {
        "proposal_id": "merge-proposal", "campaign_id": str(base.campaign_id),
        "review_id": base.review_id, "kind": "identity_merge",
        "decision_bindings": [{
            "event_id": base.event_id, "item_id": base.item_id,
            "item_revision": base.item_revision, "review_digest": base.review_digest,
            "decision_revision": base.decision_revision,
        }],
    }
    proposal["proposal_digest"] = sha256_bytes(_canonical_json(proposal))
    review = _review_decision(
        disposition="merge",
        proposal={"kind": "identity_merge", "id": proposal["proposal_id"], "digest": proposal["proposal_digest"]},
    )
    review = _write_review_references(tmp_path, review)
    proposal_path = tmp_path / "docs" / "reviews" / review.review_id / "proposals" / "merge-proposal.json"
    proposal_path.parent.mkdir()
    proposal_path.write_bytes(_canonical_json(proposal))
    validate_record_identity(tmp_path, review)

    proposal["tampered"] = True
    proposal_path.write_bytes(_canonical_json(proposal))
    with pytest.raises(AuthorityError, match="proposal digest"):
        validate_record_identity(tmp_path, review)


def test_review_decision_refuses_event_proposal_mismatch_and_symlinked_event(tmp_path: Path):
    base = _review_decision(disposition="merge")
    proposal_digest = "4" * 64
    review = _review_decision(
        disposition="merge",
        proposal={"kind": "identity_merge", "id": "merge-proposal", "digest": proposal_digest},
    )
    review = _write_review_references(
        tmp_path, review, event_overrides={"proposal_id": "another-proposal"},
    )
    with pytest.raises(AuthorityError, match="proposal_id"):
        validate_record_identity(tmp_path, review)

    review = _write_review_references(tmp_path, review)
    event_path = tmp_path / "docs" / "reviews" / review.review_id / "events" / f"{review.event_id}.json"
    event_bytes = event_path.read_bytes()
    outside = tmp_path / "outside-event.json"
    outside.write_bytes(event_bytes)
    event_path.unlink()
    event_path.symlink_to(outside)
    with pytest.raises(AuthorityError, match="symlink"):
        validate_record_identity(tmp_path, review)


def test_review_decision_receipt_recomputes_digest_and_binds_event_and_proposal(tmp_path: Path):
    base = _review_decision(disposition="merge")
    proposal = {
        "proposal_id": "merge-proposal", "campaign_id": str(base.campaign_id),
        "review_id": base.review_id, "kind": "identity_merge",
        "decision_bindings": [{
            "event_id": base.event_id, "item_id": base.item_id,
            "item_revision": base.item_revision, "review_digest": base.review_digest,
            "decision_revision": base.decision_revision,
        }],
    }
    proposal["proposal_digest"] = sha256_bytes(_canonical_json(proposal))
    receipt = {
        "receipt_id": "merge-receipt", "campaign_id": str(base.campaign_id),
        "review_id": base.review_id, "kind": "identity_merge",
        "proposal_id": proposal["proposal_id"], "proposal_digest": proposal["proposal_digest"],
        "decision_event_ids": [base.event_id], "authority_record_ids": [base.id],
    }
    receipt["receipt_digest"] = sha256_bytes(_canonical_json(receipt))
    review = _review_decision(
        disposition="merge",
        proposal={"kind": "identity_merge", "id": proposal["proposal_id"], "digest": proposal["proposal_digest"]},
        receipt={"kind": "identity_merge", "id": receipt["receipt_id"], "digest": receipt["receipt_digest"]},
    )
    review = _write_review_references(tmp_path, review)
    review_root = tmp_path / "docs" / "reviews" / review.review_id
    (review_root / "proposals").mkdir()
    (review_root / "receipts").mkdir()
    (review_root / "proposals" / "merge-proposal.json").write_bytes(_canonical_json(proposal))
    receipt_path = review_root / "receipts" / "merge-receipt.json"
    receipt_path.write_bytes(_canonical_json(receipt))
    validate_record_identity(tmp_path, review)

    receipt["decision_event_ids"] = ["different-event"]
    receipt["receipt_digest"] = sha256_bytes(_canonical_json(receipt, exclude="receipt_digest"))
    receipt_path.write_bytes(_canonical_json(receipt))
    changed = review.model_copy(update={
        "receipt": review.receipt.model_copy(update={"digest": receipt["receipt_digest"]}),
    })
    with pytest.raises(AuthorityError, match="does not bind"):
        validate_record_identity(tmp_path, changed)
