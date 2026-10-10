"""Digest-bound whole-generation publication with one pointer commit point."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from campaignlib.grounding_bundle import open_grounding_snapshot
from pipelines.summary_native.authority_apply import (
    authority_lock,
    require_no_pending_transaction,
    validate_ledger_tip,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.history import current_activation, joined_receipt, write_activation
from pipelines.summary_native.promotion.models import (
    ActivationRecord,
    AttemptState,
    BaselineKind,
    BundleSelection,
    OperationIntent,
    OperationState,
    PromotionPreview,
    PublicationReceiptCandidate,
    SignoffSet,
    OpaqueId,
)
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.staging import stage_generation
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest
from pydantic import TypeAdapter, ValidationError


FaultHook = Callable[[str], None]


def _write_sync(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_EXCL if exclusive else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_tree_directories(path: Path) -> None:
    for directory in sorted((item for item in path.rglob("*") if item.is_dir()), reverse=True):
        _sync_dir(directory)
    _sync_dir(path)


def _operation_dir(root: Path, operation_id: str) -> Path:
    return root / "docs/grounding/operations" / operation_id


def _state(operation_id: str, state: AttemptState, intent_sha: str, **values) -> OperationState:
    return OperationState(operation_id=operation_id, state=state, intent_sha256=intent_sha, **values)


def _publish_bundle_impl(
    campaign_dir: Path,
    bundle: BundleSelection,
    expected_preview: PromotionPreview,
    *,
    signoffs: SignoffSet,
    analysis_digest: str,
    resolution_digest: str,
    request_id: str,
    operation_id: str,
    generation_id: str,
    actor: str,
    claims_blocking: bool = False,
    check_report: str | None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    fault: FaultHook | None = None,
) -> dict:
    """Publish only the exact eligible preview; never refresh consent silently."""
    root = Path(campaign_dir).resolve()
    fault = fault or (lambda _stage: None)
    try:
        for value in (request_id, operation_id, generation_id):
            TypeAdapter(OpaqueId).validate_python(value, strict=True)
    except ValidationError as exc:
        raise PromotionError("publication identifiers are invalid", code="PROMOTION_REQUEST_INVALID") from exc
    operations = root / "docs/grounding/operations"
    if operations.is_dir():
        for state_path in sorted(operations.glob("*/state.json")):
            try:
                saved_state = OperationState.model_validate_json(state_path.read_bytes())
                saved_intent = OperationIntent.model_validate_json((state_path.parent / "intent.json").read_bytes())
            except (OSError, ValueError):
                continue
            if saved_intent.request_id == request_id and saved_state.state is AttemptState.COMMITTED:
                if (saved_intent.preview_sha256 != expected_preview.preview_sha256
                        or saved_intent.bundle_digest != bundle.digest):
                    raise PromotionError(
                        "request id is already bound to a different publication intent",
                        code="PROMOTION_OPERATION_CONFLICT",
                    )
                if saved_state.activation_id is None:
                    raise PromotionError("committed request has no activation", code="PROMOTION_HISTORY_INVALID")
                joined = joined_receipt(root, saved_state.activation_id)
                return {"receipt": joined["publication"], "activation": joined["activation"]}
    parent = None
    parent_sha = None
    if expected_preview.expected_activation_id is not None:
        parent, parent_sha = current_activation(root, expected_preview.expected_generation_id or "")
        if parent.activation_id != expected_preview.expected_activation_id:
            raise PromotionError("preview activation parent is stale", code="PROMOTION_PREVIEW_STALE")
    elif expected_preview.expected_generation_id is not None:
        raise PromotionError("publication requires a reconciled active baseline", code="PROMOTION_HISTORY_INVALID")
    stage, manifest = stage_generation(
        root, bundle, operation_id=operation_id, generation_id=generation_id,
        parent_activation_id=parent.activation_id if parent else None, created_at=now()
    )
    grounding = root / "docs/grounding"
    operation = _operation_dir(root, operation_id)
    final_generation = grounding / "generations" / generation_id
    activated = False
    try:
        with authority_lock(root, exclusive=True):
            require_no_pending_transaction(root)
            validate_ledger_tip(root)
            current_signoffs = signoffs
            if check_report is not None:
                from pipelines.summary_native.claims.report import load_current_report
                from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
                report = load_current_report(
                    root, check_report, bundle, _already_locked=True,
                )
                if (report.outcome != "complete" or report.analysis_digest != analysis_digest
                        or report.resolution_digest != resolution_digest):
                    raise PromotionError("claims report changed after preview", code="PROMOTION_PREVIEW_STALE")
                current_signoffs = load_signoff_bindings(
                    root, bundle, analysis_digest=analysis_digest, resolution_digest=resolution_digest,
                    _already_locked=True,
                )
                if current_signoffs.digest != signoffs.digest:
                    raise PromotionError("document sign-offs changed after preview", code="PROMOTION_PREVIEW_STALE")
            current = preview_bundle(
                root,
                bundle,
                signoffs=current_signoffs,
                analysis_digest=analysis_digest,
                resolution_digest=resolution_digest,
                claims_complete=True,
                claims_blocking=claims_blocking,
            )
            if not current.eligible or current.preview_sha256 != expected_preview.preview_sha256:
                raise PromotionError("preview is stale or no longer eligible", code="PROMOTION_PREVIEW_STALE")
            if parent is not None:
                locked_parent, locked_parent_sha = current_activation(root, current.expected_generation_id or "")
                if locked_parent.activation_id != parent.activation_id or locked_parent_sha != parent_sha:
                    raise PromotionError("activation parent changed after preview", code="PROMOTION_PREVIEW_STALE")
            intent_values = dict(
                operation_id=operation_id,
                request_id=request_id,
                campaign_id=bundle.campaign_id,
                preview_sha256=current.preview_sha256,
                bundle_digest=bundle.digest,
                expected_generation_id=current.expected_generation_id,
                expected_activation_id=current.expected_activation_id,
                expected_live_digest=current.live_digest,
                generation_id=generation_id,
                created_at=now(),
            )
            intent = OperationIntent.model_validate(intent_values)
            intent_bytes = canonical_bytes(intent)
            intent_sha = hashlib.sha256(intent_bytes).hexdigest()
            _write_sync(operation / "intent.json", intent_bytes, exclusive=True)
            fault("intent")
            if current.expected_generation_id is None:
                if (grounding / "current").exists() or (grounding / "current").is_symlink():
                    raise PromotionError("absent baseline changed after preview", code="PROMOTION_DESTINATION_STALE")
                previous = {}
            else:
                with open_grounding_snapshot(root) as snapshot:
                    if snapshot.generation_id != current.expected_generation_id or snapshot.live_digest != current.live_digest:
                        raise PromotionError("live generation changed after preview", code="PROMOTION_DESTINATION_STALE")
                    previous = dict(snapshot.members)
            previous_dir = operation / "previous"
            for relative, data in previous.items():
                _write_sync(previous_dir / relative, data, exclusive=True)
            previous_manifest = {
                "version": 1,
                "generation_id": current.expected_generation_id,
                "members": [
                    {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                    for path, data in sorted(previous.items())
                ],
            }
            previous_bytes = canonical_bytes(previous_manifest)
            _write_sync(operation / "previous-manifest.json", previous_bytes, exclusive=True)
            previous_sha = hashlib.sha256(previous_bytes).hexdigest()
            _write_sync(operation / "state.json", canonical_bytes(_state(operation_id, AttemptState.PREPARED, intent_sha)))
            fault("prepared")
            final_generation.parent.mkdir(parents=True, exist_ok=True)
            if final_generation.exists():
                raise PromotionError("generation id already exists", code="PROMOTION_OPERATION_CONFLICT")
            os.replace(stage, final_generation)
            _sync_dir(final_generation.parent)
            fault("generation_renamed")
            review_events = tuple(binding.decision_event_id for binding in current_signoffs.bindings)
            receipt_values = dict(
                receipt_id=f"receipt-{operation_id}", operation_id=operation_id, request_id=request_id,
                campaign_id=bundle.campaign_id, generation_id=generation_id,
                generation_manifest_sha256=manifest.manifest_sha256,
                preview_sha256=current.preview_sha256, bundle_digest=bundle.digest,
                previous_snapshot_sha256=previous_sha, review_event_ids=review_events,
                gates=current.gates, prepared_at=now(), receipt_sha256="0" * 64,
            )
            provisional = PublicationReceiptCandidate.model_construct(**receipt_values)
            receipt_values["receipt_sha256"] = canonical_digest(
                provisional, exclude_fields=frozenset({"receipt_sha256"})
            )
            receipt = PublicationReceiptCandidate.model_validate(receipt_values)
            receipt_path = final_generation / "publication-receipt.json"
            receipt_bytes = canonical_bytes(receipt)
            _write_sync(receipt_path, receipt_bytes, exclusive=True)
            receipt_file_sha = hashlib.sha256(receipt_bytes).hexdigest()
            _write_sync(
                operation / "state.json",
                canonical_bytes(_state(operation_id, AttemptState.STAGED, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha)),
            )
            _sync_tree_directories(operation)
            _sync_tree_directories(final_generation)
            fault("receipt")
            if check_report is not None:
                report = load_current_report(
                    root, check_report, bundle, _already_locked=True,
                )
                if (
                    report.outcome != "complete"
                    or report.analysis_digest != analysis_digest
                    or report.resolution_digest != resolution_digest
                ):
                    raise PromotionError("claims report changed before activation", code="PROMOTION_PREVIEW_STALE")
                current_signoffs = load_signoff_bindings(
                    root, bundle, analysis_digest=analysis_digest, resolution_digest=resolution_digest,
                    _already_locked=True,
                )
            final_check = preview_bundle(
                root, bundle, signoffs=current_signoffs, analysis_digest=analysis_digest,
                resolution_digest=resolution_digest, claims_complete=True,
                claims_blocking=claims_blocking,
            )
            if not final_check.eligible or final_check.preview_sha256 != current.preview_sha256:
                raise PromotionError("source, review, or live state changed before activation", code="PROMOTION_PREVIEW_STALE")
            _write_sync(
                operation / "state.json",
                canonical_bytes(_state(operation_id, AttemptState.ACTIVATION_PENDING, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha)),
            )
            _sync_tree_directories(operation)
            temporary_link = grounding / f".current-{operation_id}"
            os.symlink(f"generations/{generation_id}/live", temporary_link)
            os.replace(temporary_link, grounding / "current")
            activated = True
            _sync_dir(grounding)
            fault("activated")
            activation = ActivationRecord(
                activation_id=f"activation-{operation_id}", operation_id=operation_id,
                generation_id=generation_id,
                manifest_sha256=hashlib.sha256((final_generation / "manifest.json").read_bytes()).hexdigest(),
                receipt_candidate_sha256=receipt_file_sha,
                parent_activation_id=parent.activation_id if parent else None, parent_activation_sha256=parent_sha,
                baseline_kind=BaselineKind.ACTIVATION, previous_snapshot_sha256=previous_sha,
                actor=actor, completed_at=now(),
            )
            write_activation(root, activation)
            try:
                prior_layout = json.loads((grounding / "layout.json").read_text(encoding="utf-8"))
                migration_operation_id = prior_layout.get("migration_operation_id")
            except (OSError, ValueError):
                migration_operation_id = None
            layout_value = {
                "version": 1, "state": "active", "generation_id": generation_id,
                "activation_id": activation.activation_id,
            }
            if migration_operation_id:
                layout_value["migration_operation_id"] = migration_operation_id
            _write_sync(
                grounding / "layout.json",
                canonical_bytes(layout_value),
            )
            _sync_dir(grounding)
            _write_sync(
                operation / "state.json",
                canonical_bytes(_state(operation_id, AttemptState.COMMITTED, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha,
                    activation_id=activation.activation_id)),
            )
            fault("completed")
            return {"receipt": receipt.model_dump(mode="json"), "activation": activation.model_dump(mode="json")}
    except Exception:
        if activated:
            try:
                intent_sha = hashlib.sha256((operation / "intent.json").read_bytes()).hexdigest()
                _write_sync(operation / "state.json", canonical_bytes(_state(
                    operation_id, AttemptState.COMMIT_UNKNOWN, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    detail="activation may have completed; run explicit recovery",
                )))
            except Exception:
                pass
        raise
    finally:
        staging_parent = grounding / ".staging" / operation_id
        if staging_parent.exists() and not activated:
            shutil.rmtree(staging_parent)


def publish_bundle(
    campaign_dir: Path,
    bundle: BundleSelection,
    expected_preview: PromotionPreview,
    *,
    signoffs: SignoffSet,
    analysis_digest: str,
    resolution_digest: str,
    request_id: str,
    operation_id: str,
    generation_id: str,
    actor: str,
    check_report: str,
    claims_blocking: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    fault: FaultHook | None = None,
) -> dict:
    """Publish only with an exact persisted report that can be recomputed now."""
    if not check_report or check_report == "claims-unavailable":
        raise PromotionError(
            "publication requires an exact current claims report",
            code="CLAIMS_REPORT_REQUIRED",
        )
    return _publish_bundle_impl(
        campaign_dir, bundle, expected_preview, signoffs=signoffs,
        analysis_digest=analysis_digest, resolution_digest=resolution_digest,
        request_id=request_id, operation_id=operation_id, generation_id=generation_id,
        actor=actor, claims_blocking=claims_blocking, check_report=check_report,
        now=now, fault=fault,
    )


def _publish_bundle_for_recovery_test(
    campaign_dir: Path,
    bundle: BundleSelection,
    expected_preview: PromotionPreview,
    **kwargs,
) -> dict:
    """Exercise publication durability before the claims layer in fault tests only."""
    return _publish_bundle_impl(
        campaign_dir, bundle, expected_preview, check_report=None, **kwargs,
    )
