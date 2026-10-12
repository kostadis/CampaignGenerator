"""Explicit reconciliation for interrupted whole-bundle publication."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from pydantic import TypeAdapter, ValidationError

from pipelines.summary_native.authority_apply import authority_lock
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.history import (
    activation_path, current_activation, joined_receipt, verify_generation_evidence, write_activation,
)
from pipelines.summary_native.promotion.models import (
    ActivationRecord, AttemptState, BaselineKind, GenerationManifest,
    OperationIntent, OperationState, PublicationReceiptCandidate,
    OpaqueId,
)
from pipelines.summary_native.promotion.aliases import install_aliases
from pipelines.summary_native.promotion.publish import _write_sync, write_active_layout
from pipelines.summary_native.review.models import canonical_bytes


def recover_publication(campaign_dir: Path, operation_id: str) -> dict:
    """Reconcile only the named durable intent against the exact current pointer."""
    root = Path(campaign_dir).resolve()
    try:
        TypeAdapter(OpaqueId).validate_python(operation_id, strict=True)
    except ValidationError as exc:
        raise PromotionError("publication operation id is invalid", code="PROMOTION_RECOVERY_INVALID") from exc
    operation = root / "docs/grounding/operations" / operation_id
    with authority_lock(root, exclusive=True, create=False):
        try:
            intent_bytes = (operation / "intent.json").read_bytes()
            intent = OperationIntent.model_validate_json(intent_bytes)
        except (OSError, ValueError) as exc:
            raise PromotionError("publication intent is missing or invalid", code="PROMOTION_RECOVERY_INVALID") from exc
        intent_sha = hashlib.sha256(intent_bytes).hexdigest()
        try:
            state: OperationState | None = OperationState.model_validate_json((operation / "state.json").read_bytes())
        except (OSError, ValueError):
            # A missing or torn state record says nothing about activation; the
            # durable intent plus the observed pointer decide, as below.
            state = None
        if intent.operation_id != operation_id or (state is not None and state.operation_id != operation_id):
            raise PromotionError("publication operation identity differs", code="PROMOTION_RECOVERY_INVALID")
        if state is not None and intent_sha != state.intent_sha256:
            raise PromotionError("publication intent digest differs", code="PROMOTION_RECOVERY_INVALID")
        if state is not None and state.state is AttemptState.COMMITTED:
            if state.activation_id is None:
                raise PromotionError("committed operation has no activation", code="PROMOTION_HISTORY_INVALID")
            return {"state": "committed", **joined_receipt(root, state.activation_id)}
        if state is not None and state.state is AttemptState.ABORTED:
            return {"state": "aborted", "operation_id": operation_id}

        def abort(detail: str) -> dict:
            aborted = OperationState(
                operation_id=operation_id, state=AttemptState.ABORTED, intent_sha256=intent_sha,
                generation_manifest_sha256=state.generation_manifest_sha256 if state else None,
                receipt_candidate_sha256=state.receipt_candidate_sha256 if state else None,
                detail=detail,
            )
            _write_sync(operation / "state.json", canonical_bytes(aborted))
            return {"state": "aborted", "operation_id": operation_id}

        grounding = root / "docs/grounding"
        current = grounding / "current"
        if not current.is_symlink() and intent.expected_generation_id is None and not current.exists():
            return abort("activation did not occur")
        if not current.is_symlink():
            raise PromotionError("current pointer is not reconcilable", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED")
        observed = os.readlink(current)
        old_target = f"generations/{intent.expected_generation_id}/live" if intent.expected_generation_id else None
        new_target = f"generations/{intent.generation_id}/live"
        if observed == old_target:
            return abort("activation did not occur")
        if observed != new_target:
            if state is not None and state.state in {AttemptState.PREPARED, AttemptState.STAGED}:
                # The pointer swap is only attempted after ACTIVATION_PENDING is
                # durable, so this generation never became current.
                return abort(f"activation was never attempted; current names {observed}")
            raise PromotionError(
                f"current pointer names neither operation endpoint (observed {observed}, "
                f"expected {old_target} or {new_target})",
                code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED",
            )

        generation = grounding / "generations" / intent.generation_id
        try:
            manifest_bytes = (generation / "manifest.json").read_bytes()
            manifest = GenerationManifest.model_validate_json(manifest_bytes)
            receipt_bytes = (generation / "publication-receipt.json").read_bytes()
            receipt = PublicationReceiptCandidate.model_validate_json(receipt_bytes)
        except (OSError, ValueError) as exc:
            raise PromotionError("activated generation evidence is invalid", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED") from exc
        if (manifest.generation_id != intent.generation_id or receipt.operation_id != operation_id
                or receipt.generation_id != intent.generation_id or receipt.preview_sha256 != intent.preview_sha256):
            raise PromotionError("activated generation evidence identity differs", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED")
        try:
            verify_generation_evidence(root, manifest, manifest_bytes, receipt)
            receipt_file_sha = hashlib.sha256(receipt_bytes).hexdigest()
            if (state is not None and state.generation_manifest_sha256 is not None
                    and state.generation_manifest_sha256 != manifest.manifest_sha256):
                raise PromotionError("operation manifest binding differs", code="PROMOTION_HISTORY_INVALID")
            if (state is not None and state.receipt_candidate_sha256 is not None
                    and state.receipt_candidate_sha256 != receipt_file_sha):
                raise PromotionError("operation receipt binding differs", code="PROMOTION_HISTORY_INVALID")
            previous_bytes = (operation / "previous-manifest.json").read_bytes()
            if hashlib.sha256(previous_bytes).hexdigest() != receipt.previous_snapshot_sha256:
                raise PromotionError("previous snapshot binding differs", code="PROMOTION_HISTORY_INVALID")
            previous_manifest = json.loads(previous_bytes)
            expected_previous = {
                item["path"]: (item["sha256"], item["size"])
                for item in previous_manifest.get("members", [])
            }
            previous_dir = operation / "previous"
            actual_previous = {
                item.relative_to(previous_dir).as_posix(): (
                    hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_size
                )
                for item in previous_dir.rglob("*") if item.is_file() and not item.is_symlink()
            } if previous_dir.is_dir() else {}
            if actual_previous != expected_previous:
                raise PromotionError("previous snapshot members differ", code="PROMOTION_HISTORY_INVALID")
        except (OSError, PromotionError) as exc:
            raise PromotionError("sealed publication evidence differs", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED") from exc
        parent = None
        parent_sha = None
        if intent.expected_activation_id is not None:
            parent, parent_sha = current_activation(root, intent.expected_generation_id or "")
            if parent.activation_id != intent.expected_activation_id:
                raise PromotionError("activation parent differs", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED")
        elif intent.expected_generation_id is not None:
            raise PromotionError("activation parent is absent", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED")

        if intent.expected_generation_id is None:
            try:
                install_aliases(root)
            except PromotionError as exc:
                raise PromotionError(str(exc), code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED") from exc

        activation_id = f"activation-{operation_id}"
        record_path = activation_path(root, activation_id)
        if record_path.exists():
            try:
                activation = ActivationRecord.model_validate_json(record_path.read_bytes())
            except ValueError as exc:
                raise PromotionError("activation record is invalid", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED") from exc
            if (activation.activation_id != activation_id or activation.operation_id != operation_id
                    or activation.generation_id != intent.generation_id
                    or activation.receipt_candidate_sha256 != receipt_file_sha
                    or activation.parent_activation_id != (parent.activation_id if parent else None)
                    or activation.parent_activation_sha256 != parent_sha):
                raise PromotionError("existing activation identity differs", code="PROMOTION_RECOVERY_INTERVENTION_REQUIRED")
        else:
            observed_at = datetime.now(timezone.utc)
            activation = ActivationRecord(
                activation_id=activation_id, operation_id=operation_id, generation_id=intent.generation_id,
                manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                receipt_candidate_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                parent_activation_id=parent.activation_id if parent else None, parent_activation_sha256=parent_sha,
                baseline_kind=BaselineKind.ACTIVATION, previous_snapshot_sha256=receipt.previous_snapshot_sha256,
                actor="promotion-recovery", completed_at=observed_at, recovered_at=observed_at,
            )
            write_activation(root, activation)
        write_active_layout(root, intent.generation_id, activation.activation_id)
        committed = OperationState(
            operation_id=operation_id, state=AttemptState.COMMITTED, intent_sha256=intent_sha,
            generation_manifest_sha256=manifest.manifest_sha256,
            receipt_candidate_sha256=receipt_file_sha,
            activation_id=activation.activation_id,
        )
        _write_sync(operation / "state.json", canonical_bytes(committed))
        return {"state": "committed", **joined_receipt(root, activation.activation_id)}
