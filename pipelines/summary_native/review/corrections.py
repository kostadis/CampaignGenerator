"""Explicit source versus authored-draft correction previews.

Source corrections are review-local bindings around the existing #546 ruling
workflow. This module never writes a maintained summary itself: it stages and
applies the native authority proposal, then records the typed review receipt.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    ReviewArtifactRef,
    ReviewDecisionRecord,
    RulingRecord,
    ledger_bytes,
    ledger_digest,
    ledger_path,
    load_ledger,
    sha256_bytes,
)
from pipelines.summary_native.authority_apply import (
    TransactionTarget,
    _json_bytes,
    _prepare_transaction_locked,
    _tip_bytes,
    apply_proposal,
    authority_dir,
    authority_lock,
    create_proposal,
    ledger_tip_path,
    recover_transaction,
    require_no_pending_transaction,
    validate_ledger_tip,
)
from pipelines.summary_native.authority_sources import allowed_summary_path, exact_replace
from pipelines.summary_native.review.models import (
    DecisionBinding,
    ProposalTarget,
    SourceCorrectionProposal,
    SourceCorrectionReceipt,
    SourceCustodyRef,
    canonical_bytes,
    model_from_json,
    parse_json_strict,
)
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    _reject_symlinks,
    _review_dir,
    history,
    read_snapshot,
)


class CorrectionReviewError(ReviewStoreError):
    pass


def _proposal_target(relative: str, before: bytes, after: bytes) -> ProposalTarget:
    return ProposalTarget(
        path=relative,
        operation="replace",
        before_exists=True,
        before_sha256=sha256_bytes(before),
        before_bytes_b64=base64.b64encode(before).decode("ascii"),
        after_exists=True,
        after_sha256=sha256_bytes(after),
        after_bytes_b64=base64.b64encode(after).decode("ascii"),
    )


def _latest_decision_revision(root: Path, review_id: str, item_id: str) -> int:
    return max(
        (int(event.get("decision_revision", 0)) for event in history(root, review_id, item_id=item_id)),
        default=0,
    )


def _ruling_for_item(
    ledger: AuthorityLedger,
    details: dict,
    *,
    binding_path: str,
    replacement_text: str,
) -> RulingRecord:
    ruling_id = details.get("authority_ruling_id")
    if not isinstance(ruling_id, str) or not ruling_id:
        raise CorrectionReviewError(
            "REVIEW_AUTHORITY_RULING_REQUIRED: source correction needs an existing #546 ruling"
        )
    record = next((candidate for candidate in ledger.records if candidate.id == ruling_id), None)
    if not isinstance(record, RulingRecord):
        raise CorrectionReviewError(
            "REVIEW_AUTHORITY_RULING_REQUIRED: source correction ruling is missing"
        )
    if record.status not in {"draft", "proposed"}:
        raise CorrectionReviewError(
            f"REVIEW_AUTHORITY_RULING_STATE: ruling {ruling_id} is {record.status}"
        )
    if record.source.path != binding_path:
        raise CorrectionReviewError(
            "REVIEW_AUTHORITY_RULING_MISMATCH: ruling and reviewed source paths differ"
        )
    anchor = details.get("anchor")
    if anchor and record.source.anchor != anchor:
        raise CorrectionReviewError(
            "REVIEW_AUTHORITY_RULING_MISMATCH: ruling and reviewed source anchors differ"
        )
    rejected = details.get("rejected_claim")
    if record.rejected_claim != rejected or record.replacement_fact != replacement_text:
        raise CorrectionReviewError(
            "REVIEW_AUTHORITY_RULING_MISMATCH: ruling does not contain the reviewed replacement"
        )
    return record


def _decode_target(target: ProposalTarget, side: str) -> bytes:
    encoded = getattr(target, f"{side}_bytes_b64")
    if encoded is None:
        raise CorrectionReviewError("REVIEW_INVALID_PROPOSAL: correction target bytes are missing")
    return base64.b64decode(encoded, validate=True)


def _only_review_decisions_since(root: Path, before_sha256: str, after_sha256: str, *, ruling_id: str) -> bool:
    """Allow the approval audit transition without weakening native ledger binding."""
    if before_sha256 == after_sha256:
        return True
    events: dict[str, list[dict]] = {}
    for path in (authority_dir(root) / "events").glob("*.json"):
        if path.name == "tip.json" or path.is_symlink():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if isinstance(payload, dict) and isinstance(payload.get("after_sha256"), str):
            events.setdefault(payload["after_sha256"], []).append(payload)
    cursor = after_sha256
    visited: set[str] = set()
    while cursor != before_sha256:
        if cursor in visited:
            return False
        visited.add(cursor)
        candidates = events.get(cursor, [])
        if len(candidates) != 1:
            return False
        event=candidates[0]
        if event.get("reason")!="review-decision" and not (
            event.get("reason")=="proposal-stage" and event.get("ruling_id")==ruling_id
        ):
            return False
        previous = event.get("before_sha256")
        if not isinstance(previous, str):
            return False
        cursor = previous
    return True


def prepare_correction(
    campaign_dir: Path,
    review_id: str,
    item_id: str,
    *,
    target_kind: str,
    replacement_text: str,
    expected_decision_revision: int,
    summaries_dir: Path | None = None,
):
    root = Path(campaign_dir).resolve()
    summaries = Path(summaries_dir or root / "docs" / "summaries")
    manifest, custody, items = read_snapshot(root, review_id)
    item = next((candidate for candidate in items if candidate.item_id == item_id), None)
    if item is None:
        raise CorrectionReviewError("REVIEW_UNKNOWN_ITEM: correction item missing")
    details = item.proposed_action.details
    expected = details.get("expected_target")
    if target_kind != expected:
        code = (
            "REVIEW_SOURCE_CORRECTION_REQUIRED"
            if expected == "source"
            else "REVIEW_DRAFT_CORRECTION_REQUIRED"
        )
        raise CorrectionReviewError(code)
    relative = details.get(f"{target_kind}_path")
    binding = next((candidate for candidate in item.input_bindings if candidate.path == relative), None)
    if binding is None:
        raise CorrectionReviewError("REVIEW_INVALID_CORRECTION: reviewed input binding is missing")
    if _latest_decision_revision(root, review_id, item_id) != expected_decision_revision:
        raise CorrectionReviewError(
            "REVIEW_STALE_DECISION: decision revision changed", "REVIEW_STALE_DECISION"
        )

    if target_kind == "draft":
        path = _reject_symlinks(root, root / binding.path)
        before = path.read_bytes()
        if sha256_bytes(before) != binding.custody_sha256:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
        try:
            after = exact_replace(
                path,
                str(details["rejected_claim"]).encode("utf-8"),
                replacement_text.encode("utf-8"),
                expected_file_sha256=binding.custody_sha256,
            )
        except AuthorityError as exc:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT") from exc
        return {
            "version": 2,
            "kind": "draft_correction",
            "proposal_id": f"draft-correction-{item_id}",
            "campaign_id": str(manifest.campaign_id),
            "review_id": review_id,
            "target_kind": "draft",
            "affected_paths": [binding.path],
            "before_sha256": sha256_bytes(before),
            "after_sha256": sha256_bytes(after),
            "replacement_text": replacement_text,
        }

    proposal_id = f"source-correction-{item_id}-r{item.revision}"
    proposal_path = _review_dir(root, review_id) / "proposals" / f"{proposal_id}.json"
    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        validate_ledger_tip(root)
        ledger = load_ledger(root)
        ruling = _ruling_for_item(
            ledger, details, binding_path=binding.path, replacement_text=replacement_text
        )
        source = allowed_summary_path(root, summaries, ruling.source)
        before = source.read_bytes()
        if sha256_bytes(before) != binding.custody_sha256:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")

        if proposal_path.exists():
            existing = model_from_json(SourceCorrectionProposal, proposal_path.read_bytes())
            target = existing.targets[0]
            decision = existing.decision_bindings[0]
            if (
                existing.authority_ruling_id != ruling.id
                or existing.proposal_id != proposal_id
                or decision.item_id != item.item_id
                or decision.item_revision != item.revision
                or decision.review_digest != item.review_digest
                or decision.decision_revision != expected_decision_revision
                or target.path != binding.path
                or target.before_sha256 != sha256_bytes(before)
            ):
                raise CorrectionReviewError("REVIEW_PROPOSAL_CONFLICT: proposal id exists")
            return existing

        native = create_proposal(root, ruling.id, summaries_dir=summaries)
        native_before = native["before_bytes"].encode("utf-8")
        native_after = native["after_bytes"].encode("utf-8")
        if native_before != before:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
        proposal = SourceCorrectionProposal(
            proposal_id=proposal_id,
            campaign_id=manifest.campaign_id,
            review_id=review_id,
            custody=SourceCustodyRef(
                campaign_id=manifest.campaign_id,
                review_id=review_id,
                generation=custody.generation,
                digest=custody.custody_digest,
            ),
            decision_bindings=(DecisionBinding(
                event_id=None,
                item_id=item.item_id,
                item_revision=item.revision,
                review_digest=item.review_digest,
                decision_revision=expected_decision_revision,
            ),),
            applicable=True,
            targets=(_proposal_target(binding.path, native_before, native_after),),
            affected_paths=(binding.path,),
            inspected_paths=tuple(candidate.path for candidate in item.input_bindings),
            ledger_sha256=native["ledger_sha256"],
            created_at=datetime.now(timezone.utc),
            authority_ruling_id=ruling.id,
        )
        journal = _prepare_transaction_locked(
            root,
            proposal_id=proposal.proposal_id,
            proposal_sha256=proposal.proposal_digest,
            targets=[TransactionTarget.create(proposal_path, canonical_bytes(proposal))],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return proposal


def _approved_record(
    ledger: AuthorityLedger, review_id: str, proposal: SourceCorrectionProposal
) -> ReviewDecisionRecord:
    binding = proposal.decision_bindings[0]
    matches = [
        record
        for record in ledger.records
        if isinstance(record, ReviewDecisionRecord)
        and record.review_id == review_id
        and record.item_id == binding.item_id
        and record.status == "accepted"
        and record.disposition == "source_correction"
        and record.proposal is not None
        and record.proposal.id == proposal.proposal_id
        and record.proposal.digest == proposal.proposal_digest
    ]
    if not matches:
        raise CorrectionReviewError("REVIEW_CORRECTION_APPROVAL_REQUIRED")
    record = matches[-1]
    if (
        record.item_revision != binding.item_revision
        or record.review_digest != binding.review_digest
        or record.decision_revision != binding.decision_revision + 1
    ):
        raise CorrectionReviewError("REVIEW_STALE_CORRECTION_APPROVAL")
    return record


def _load_native_receipt(root: Path, ruling: RulingRecord) -> dict:
    if ruling.applied_receipt is None:
        raise CorrectionReviewError("REVIEW_CORRECTION_RECEIPT_MISSING")
    path = authority_dir(root) / "receipts" / f"{ruling.applied_receipt}.json"
    try:
        payload = parse_json_strict(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CorrectionReviewError("REVIEW_CORRECTION_RECEIPT_MISSING") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("id") != ruling.applied_receipt
        or payload.get("ruling_id") != ruling.id
    ):
        raise CorrectionReviewError("REVIEW_CORRECTION_RECEIPT_INVALID")
    return payload


def apply_correction(
    campaign_dir: Path,
    review_id: str,
    *,
    proposal_id: str,
    proposal_sha256: str,
    summaries_dir: Path | None = None,
) -> SourceCorrectionReceipt:
    root = Path(campaign_dir).resolve()
    summaries = Path(summaries_dir or root / "docs" / "summaries")
    proposal_path = _reject_symlinks(
        root, _review_dir(root, review_id) / "proposals" / f"{proposal_id}.json"
    )
    if not proposal_path.is_file():
        raise CorrectionReviewError("REVIEW_INVALID_PROPOSAL: proposal missing")
    proposal = model_from_json(SourceCorrectionProposal, proposal_path.read_bytes())
    if proposal.proposal_digest != proposal_sha256:
        raise CorrectionReviewError("REVIEW_INVALID_PROPOSAL: digest mismatch")
    target = proposal.targets[0]
    before = _decode_target(target, "before")
    after = _decode_target(target, "after")
    receipt_id = f"receipt-{proposal_id}"
    receipt_path = _review_dir(root, review_id) / "receipts" / f"{receipt_id}.json"

    with authority_lock(root, exclusive=True):
        require_no_pending_transaction(root)
        validate_ledger_tip(root)
        if receipt_path.exists():
            ledger=load_ledger(root); review_record=_approved_record(ledger,review_id,proposal)
            ruling=next((record for record in ledger.records if record.id==proposal.authority_ruling_id),None)
            receipt=model_from_json(SourceCorrectionReceipt,receipt_path.read_bytes())
            if not isinstance(ruling,RulingRecord) or ruling.status!="applied" or receipt.proposal_digest!=proposal_sha256 or review_record.receipt is None or review_record.receipt.id!=receipt.receipt_id or review_record.receipt.digest!=receipt.receipt_digest:
                raise CorrectionReviewError("REVIEW_RECEIPT_CONFLICT")
            return receipt
        manifest,custody,items=read_snapshot(root,review_id,_already_locked=True)
        if manifest.campaign_id!=proposal.campaign_id or custody.generation!=proposal.custody.generation or custody.custody_digest!=proposal.custody.digest:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
        binding=proposal.decision_bindings[0]
        current_item=next((item for item in items if item.item_id==binding.item_id),None)
        if current_item is None or current_item.revision!=binding.item_revision or current_item.review_digest!=binding.review_digest:
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
        sources={source.path:source for source in custody.sources}
        for inspected in proposal.inspected_paths:
            source=sources.get(inspected); inspected_path=_reject_symlinks(root,root/inspected)
            if source is None or not inspected_path.is_file() or sha256_bytes(inspected_path.read_bytes())!=source.sha256:
                raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
        ledger = load_ledger(root)
        review_record = _approved_record(ledger, review_id, proposal)
        ruling = next(
            (record for record in ledger.records if record.id == proposal.authority_ruling_id),
            None,
        )
        if not isinstance(ruling, RulingRecord):
            raise CorrectionReviewError("REVIEW_AUTHORITY_RULING_REQUIRED")
        if ruling.source.path != target.path or ruling.rejected_claim.encode("utf-8") not in before:
            raise CorrectionReviewError("REVIEW_AUTHORITY_RULING_MISMATCH")

        if receipt_path.exists():
            receipt = model_from_json(SourceCorrectionReceipt, receipt_path.read_bytes())
            if (
                receipt.proposal_id != proposal_id
                or receipt.proposal_digest != proposal_sha256
                or review_record.receipt is None
                or review_record.receipt.id != receipt.receipt_id
                or review_record.receipt.digest != receipt.receipt_digest
                or ruling.status != "applied"
            ):
                raise CorrectionReviewError("REVIEW_RECEIPT_CONFLICT")
            return receipt

        current_ledger_sha = ledger_digest(root)
        if ruling.status != "applied" and not _only_review_decisions_since(
            root, proposal.ledger_sha256, current_ledger_sha, ruling_id=ruling.id
        ):
            raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")

        if ruling.status == "applied":
            source = allowed_summary_path(root, summaries, ruling.source)
            if sha256_bytes(source.read_bytes()) != target.after_sha256:
                raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT")
            native_receipt = _load_native_receipt(root, ruling)
        else:
            if ruling.status not in {"draft", "proposed"}:
                raise CorrectionReviewError(
                    f"REVIEW_AUTHORITY_RULING_STATE: ruling {ruling.id} is {ruling.status}"
                )
            source = allowed_summary_path(root, summaries, ruling.source)
            try:
                computed_after = exact_replace(
                    source,
                    ruling.rejected_claim.encode("utf-8"),
                    ruling.replacement_fact.encode("utf-8"),
                    expected_file_sha256=target.before_sha256,
                )
            except AuthorityError as exc:
                raise CorrectionReviewError("REVIEW_STALE_CORRECTION_INPUT") from exc
            if computed_after != after:
                raise CorrectionReviewError("REVIEW_AUTHORITY_RULING_MISMATCH")
            native = create_proposal(root, ruling.id, summaries_dir=summaries)
            if (
                native["before_bytes"].encode("utf-8") != before
                or native["after_bytes"].encode("utf-8") != after
            ):
                raise CorrectionReviewError("REVIEW_AUTHORITY_RULING_MISMATCH")
            native_receipt = apply_proposal(
                root,
                ruling.id,
                proposal_sha256=native["proposal_sha256"],
                actor=review_record.recorded_by,
            )

        if (
            native_receipt.get("before_source_sha256") != target.before_sha256
            or native_receipt.get("after_source_sha256") != target.after_sha256
        ):
            raise CorrectionReviewError("REVIEW_CORRECTION_RECEIPT_INVALID")

        ledger = load_ledger(root)
        validate_ledger_tip(root)
        review_record = _approved_record(ledger, review_id, proposal)
        ruling = next(
            (record for record in ledger.records if record.id == proposal.authority_ruling_id),
            None,
        )
        if not isinstance(ruling, RulingRecord) or ruling.status != "applied":
            raise CorrectionReviewError("REVIEW_CORRECTION_APPLY_INCOMPLETE")
        receipt = SourceCorrectionReceipt(
            receipt_id=receipt_id,
            campaign_id=proposal.campaign_id,
            review_id=review_id,
            proposal_id=proposal_id,
            proposal_digest=proposal_sha256,
            decision_event_ids=(review_record.event_id,),
            changed_paths=(target.path,),
            before_hashes={target.path: target.before_sha256},
            after_hashes={target.path: target.after_sha256},
            authority_record_ids=(review_record.id, ruling.id),
            ledger_sha256=ledger_digest(root),
            committed_at=native_receipt.get("committed_at") or datetime.now(timezone.utc),
            authority_ruling_id=ruling.id,
        )
        updated = [
            record.model_copy(update={
                "revision": record.revision + 1,
                "receipt": ReviewArtifactRef(
                    kind="source_correction",
                    id=receipt_id,
                    digest=receipt.receipt_digest,
                ),
            }) if record.id == review_record.id else record
            for record in ledger.records
        ]
        after_ledger = AuthorityLedger(
            version=ledger.version,
            campaign=ledger.campaign,
            revision=ledger.revision + 1,
            records=updated,
            conflicts=ledger.conflicts,
        )
        ledger_before = ledger_path(root).read_bytes()
        ledger_after = ledger_bytes(after_ledger)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        audit_id = f"event-{receipt_id}"
        audit = {
            "id": audit_id,
            "reason": "source-correction",
            "actor": review_record.recorded_by,
            "recorded_at": now,
            "before_sha256": sha256_bytes(ledger_before),
            "after_sha256": sha256_bytes(ledger_after),
            "record_id": ruling.id,
            "ruling_id": ruling.id,
        }
        journal = _prepare_transaction_locked(
            root,
            proposal_id=proposal_id,
            proposal_sha256=proposal_sha256,
            targets=[
                TransactionTarget.create(receipt_path, canonical_bytes(receipt)),
                TransactionTarget.replace(ledger_path(root), ledger_before, ledger_after),
                TransactionTarget.create(
                    authority_dir(root) / "events" / f"{audit_id}.json", _json_bytes(audit)
                ),
                TransactionTarget.replace(
                    ledger_tip_path(root),
                    ledger_tip_path(root).read_bytes(),
                    _tip_bytes(audit_id, ledger_after),
                ),
            ],
        )
        recover_transaction(root, journal["id"], _already_locked=True)
        return receipt
