"""Digest-bound whole-generation publication with one pointer commit point."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from campaignlib.grounding_bundle import open_grounding_snapshot
from pipelines.summary_native.authority_apply import (
    authority_lock,
    require_no_pending_transaction,
    validate_ledger_tip,
)
from pipelines.summary_native.promotion.aliases import install_aliases
from pipelines.summary_native.promotion.diff import reviewed_identities
from pipelines.summary_native.promotion.errors import (
    PromotionError,
    PromotionRecoveryRequired,
    PromotionStaleError,
    recover_command,
)
from pipelines.summary_native.promotion.history import current_activation, joined_receipt, write_activation
from pipelines.summary_native.promotion.models import (
    ActivationRecord,
    AttemptState,
    BaselineKind,
    BundleSelection,
    GenerationManifest,
    OperationIntent,
    OperationState,
    PromotionPreview,
    PublicationReceiptCandidate,
    ReceiptChange,
    ReceiptResolution,
    SignoffSet,
    OpaqueId,
)
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.staging import stage_generation
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest
from pydantic import TypeAdapter, ValidationError


FaultHook = Callable[[str], None]


def _write_sync(path: Path, data: bytes, *, exclusive: bool = False) -> None:
    """Durably write ``path`` so a crash leaves the old bytes or the new, never a tear.

    The bytes go to a temporary file in the same directory and are fsynced
    before they take the name: ``os.replace`` for a mutable record such as
    ``state.json`` or ``layout.json``, ``os.link`` (which refuses an existing
    name) for a create-once record. The directory is fsynced after.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    _sync_dir(path.parent)


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


UNRESOLVED_STATES = frozenset({
    AttemptState.PREPARED, AttemptState.STAGED, AttemptState.ACTIVATION_PENDING,
    AttemptState.COMMIT_UNKNOWN, AttemptState.INTERVENTION_REQUIRED,
})


@dataclass(frozen=True)
class OperationRecord:
    """One operation directory as found on disk; ``problem`` says why it is unreadable."""

    operation_id: str
    intent: OperationIntent | None
    state: OperationState | None
    problem: str | None

    @property
    def label(self) -> str:
        if self.problem is not None:
            return f"unreadable: {self.problem}"
        assert self.state is not None
        return self.state.state.value


def operation_records(campaign_dir: Path) -> list[OperationRecord]:
    """Every operation with a durable intent or state, including unreadable ones."""
    operations = Path(campaign_dir) / "docs/grounding/operations"
    if operations.is_symlink() or not operations.is_dir():
        return []
    records: list[OperationRecord] = []
    for directory in sorted(operations.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            continue
        intent_path = directory / "intent.json"
        state_path = directory / "state.json"
        if not os.path.lexists(intent_path) and not os.path.lexists(state_path):
            continue  # nothing durable was written for this attempt
        intent = state = None
        problem = None
        try:
            intent_bytes = intent_path.read_bytes()
            intent = OperationIntent.model_validate_json(intent_bytes)
        except (OSError, ValueError):
            problem = "intent.json is missing or invalid"
        try:
            state = OperationState.model_validate_json(state_path.read_bytes())
        except FileNotFoundError:
            problem = problem or "state.json was never written"
        except (OSError, ValueError):
            problem = problem or "state.json is unreadable"
        if problem is None and (
            intent.operation_id != directory.name or state.operation_id != directory.name
            or hashlib.sha256(intent_bytes).hexdigest() != state.intent_sha256
        ):
            problem = "intent and state identities differ"
        records.append(OperationRecord(directory.name, intent, state, problem))
    return records


def committed_replay(campaign_dir: Path, request_id: str) -> tuple[OperationIntent, OperationState] | None:
    """The one committed operation bound to ``request_id``, if any."""
    matched = None
    for record in operation_records(campaign_dir):
        if record.problem is not None or record.intent.request_id != request_id:
            continue
        if record.state.state is not AttemptState.COMMITTED:
            continue
        if matched is not None:
            raise PromotionError("request id has conflicting operation history", code="PROMOTION_HISTORY_INVALID")
        if record.state.activation_id is None:
            raise PromotionError("committed request has no activation", code="PROMOTION_HISTORY_INVALID")
        matched = (record.intent, record.state)
    return matched


def require_no_unresolved(campaign_dir: Path, *, request_id: str, operation_id: str) -> None:
    """Refuse while any earlier attempt is unresolved, or this request was already tried.

    A committed identical request is answered by ``committed_replay`` first, so
    reaching a committed or aborted record for this request/operation here means
    it cannot be reused.
    """
    for record in operation_records(campaign_dir):
        same = record.operation_id == operation_id or (
            record.intent is not None and record.intent.request_id == request_id
        )
        state = record.state.state if record.problem is None else None
        if state in {AttemptState.COMMITTED, AttemptState.ABORTED}:
            if same:
                outcome = "published a different intent" if state is AttemptState.COMMITTED else "did not publish"
                raise PromotionError(
                    f"request id {request_id} was already used by operation {record.operation_id}, "
                    f"which {outcome}; use a new --request-id",
                    code="PROMOTION_OPERATION_CONFLICT",
                )
            continue
        raise PromotionRecoveryRequired(
            f"promotion operation {record.operation_id} is unresolved ({record.label}); "
            f"run `{recover_command(record.operation_id)}` before publishing again",
            operation_id=record.operation_id,
        )


def _refuse_ineligible(preview: PromotionPreview) -> None:
    for code in ("PROMOTION_PATH_CONFLICT", "PROMOTION_MIGRATION_REQUIRED"):
        if code in preview.refusal_codes:
            break
    else:
        code = "PROMOTION_BLOCKED"
    reasons = "; ".join(gate.message for gate in preview.gates if gate.state != "passed")
    raise PromotionError(f"promotion is blocked: {reasons}", code=code)


def _verify_staged_generation(generation: Path, manifest: GenerationManifest, bundle: BundleSelection) -> None:
    """Every staged member must be byte-for-byte what the reviewer signed."""
    expected = reviewed_identities(bundle)
    if {item.path: (item.sha256, item.size) for item in manifest.members} != expected:
        raise PromotionStaleError("staged generation manifest differs from the reviewed bundle")
    for tree in ("published", "live"):
        base = generation / tree
        actual: dict[str, tuple[str, int]] = {}
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise PromotionStaleError(f"staged {tree}/ contains an unsafe member")
            if path.is_file():
                data = path.read_bytes()
                actual[path.relative_to(base).as_posix()] = (hashlib.sha256(data).hexdigest(), len(data))
        if actual != expected:
            differing = sorted(
                path for path in set(actual) | set(expected) if actual.get(path) != expected.get(path)
            )
            raise PromotionStaleError(
                f"staged {tree}/ differs from the reviewed bundle: {', '.join(differing)}"
            )


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
    replay = committed_replay(root, request_id)
    if replay is not None:
        saved_intent, saved_state = replay
        if (saved_intent.preview_sha256 != expected_preview.preview_sha256
                or saved_intent.bundle_digest != bundle.digest):
            raise PromotionError(
                "request id is already bound to a different publication intent; use a new --request-id",
                code="PROMOTION_OPERATION_CONFLICT",
            )
        joined = joined_receipt(root, saved_state.activation_id)
        return {"receipt": joined["publication"], "activation": joined["activation"]}
    require_no_unresolved(root, request_id=request_id, operation_id=operation_id)
    parent = None
    parent_sha = None
    if expected_preview.expected_activation_id is not None:
        parent, parent_sha = current_activation(root, expected_preview.expected_generation_id or "")
        if parent.activation_id != expected_preview.expected_activation_id:
            raise PromotionStaleError("preview activation parent is stale")
    elif expected_preview.expected_generation_id is not None:
        raise PromotionError("publication requires a reconciled active baseline", code="PROMOTION_HISTORY_INVALID")
    stage, manifest = stage_generation(
        root, bundle, operation_id=operation_id, generation_id=generation_id,
        parent_activation_id=parent.activation_id if parent else None, created_at=now(),
        analysis_digest=analysis_digest or None,
    )
    grounding = root / "docs/grounding"
    operation = _operation_dir(root, operation_id)
    final_generation = grounding / "generations" / generation_id
    activated = False
    intent_sha: str | None = None
    receipt_file_sha: str | None = None
    try:
        with authority_lock(root, exclusive=True):
            require_no_pending_transaction(root)
            validate_ledger_tip(root)
            require_no_unresolved(root, request_id=request_id, operation_id=operation_id)
            current_signoffs = signoffs
            report = None
            if check_report is not None:
                from pipelines.summary_native.claims.report import load_current_report
                from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
                report = load_current_report(
                    root, check_report, bundle, _already_locked=True,
                )
                if (report.outcome != "complete" or report.analysis_digest != analysis_digest
                        or report.resolution_digest != resolution_digest):
                    raise PromotionStaleError("claims report changed after preview")
                current_signoffs = load_signoff_bindings(
                    root, bundle, analysis_digest=analysis_digest, resolution_digest=resolution_digest,
                    _already_locked=True,
                )
                if current_signoffs.digest != signoffs.digest:
                    raise PromotionStaleError("document sign-offs changed after preview")
            current = preview_bundle(
                root,
                bundle,
                signoffs=current_signoffs,
                analysis_digest=analysis_digest,
                resolution_digest=resolution_digest,
                claims_complete=True,
                claims_blocking=claims_blocking,
            )
            if current.preview_sha256 != expected_preview.preview_sha256:
                raise PromotionStaleError("preview is stale; preview again and confirm the new digest")
            if not current.eligible:
                _refuse_ineligible(current)
            if parent is not None:
                locked_parent, locked_parent_sha = current_activation(root, current.expected_generation_id or "")
                if locked_parent.activation_id != parent.activation_id or locked_parent_sha != parent_sha:
                    raise PromotionStaleError("activation parent changed after preview")
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
            try:
                _write_sync(operation / "intent.json", intent_bytes, exclusive=True)
            except FileExistsError as exc:
                raise PromotionError(
                    f"operation {operation_id} already exists; use a new --request-id",
                    code="PROMOTION_OPERATION_CONFLICT",
                ) from exc
            intent_sha = hashlib.sha256(intent_bytes).hexdigest()
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
            receipt = PublicationReceiptCandidate.sealed(
                receipt_id=f"receipt-{operation_id}", operation_id=operation_id, request_id=request_id,
                campaign_id=bundle.campaign_id, generation_id=generation_id,
                generation_manifest_sha256=manifest.manifest_sha256,
                preview_sha256=current.preview_sha256, bundle_digest=bundle.digest,
                previous_snapshot_sha256=previous_sha, review_event_ids=review_events,
                gates=current.gates, prepared_at=now(),
                selected_range=bundle.selected_range,
                changes=tuple(
                    ReceiptChange(
                        path=change.path, kind=change.kind,
                        before_sha256=change.before_sha256, after_sha256=change.after_sha256,
                    )
                    for change in current.changes
                ),
                previous_generation_id=current.expected_generation_id,
                previous_activation_id=current.expected_activation_id,
                claims_report_id=report.report_id if report is not None else None,
                analysis_digest=analysis_digest or None,
                resolution_digest=resolution_digest or None,
                finding_resolutions=tuple(
                    ReceiptResolution(
                        finding_id=item.finding_id, disposition=item.disposition,
                        rationale=item.rationale, event_id=item.event_id,
                        decision_revision=item.decision_revision,
                    )
                    for item in (report.resolutions if report is not None else ())
                ),
                coverage_limitations=tuple(report.coverage_limitations) if report is not None else (),
            )
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
                    raise PromotionStaleError("claims report changed before activation")
                current_signoffs = load_signoff_bindings(
                    root, bundle, analysis_digest=analysis_digest, resolution_digest=resolution_digest,
                    _already_locked=True,
                )
            final_check = preview_bundle(
                root, bundle, signoffs=current_signoffs, analysis_digest=analysis_digest,
                resolution_digest=resolution_digest, claims_complete=True,
                claims_blocking=claims_blocking,
            )
            if final_check.preview_sha256 != current.preview_sha256:
                raise PromotionStaleError("source, review, or live state changed before activation")
            if not final_check.eligible:
                _refuse_ineligible(final_check)
            # The bytes about to go live are the bytes that were signed, not
            # whatever a fresh read of the drafts happens to return now.
            _verify_staged_generation(final_generation, manifest, bundle)
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
            if current.expected_generation_id is None:
                # First publication: the compatibility aliases join the bundle
                # here, under the same lock (recovery finishes them after a crash).
                install_aliases(root)
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
            write_active_layout(root, generation_id, activation.activation_id)
            _write_sync(
                operation / "state.json",
                canonical_bytes(_state(operation_id, AttemptState.COMMITTED, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha,
                    activation_id=activation.activation_id)),
            )
            fault("completed")
            return {"receipt": receipt.model_dump(mode="json"), "activation": activation.model_dump(mode="json")}
    except Exception as exc:
        if activated:
            try:
                intent_sha = hashlib.sha256((operation / "intent.json").read_bytes()).hexdigest()
                _write_sync(operation / "state.json", canonical_bytes(_state(
                    operation_id, AttemptState.COMMIT_UNKNOWN, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha,
                    detail="activation may have completed; run explicit recovery",
                )))
            except Exception:
                pass
        elif intent_sha is not None and isinstance(exc, PromotionError):
            # A deliberate refusal under the lock, before the pointer moved:
            # nothing was published, so the attempt is resolved here rather
            # than left blocking every later publication until recovery.
            try:
                _write_sync(operation / "state.json", canonical_bytes(_state(
                    operation_id, AttemptState.ABORTED, intent_sha,
                    generation_manifest_sha256=manifest.manifest_sha256,
                    receipt_candidate_sha256=receipt_file_sha,
                    detail=f"refused before activation: {exc.code}: {exc}",
                )))
            except Exception:
                pass
        raise
    finally:
        staging_parent = grounding / ".staging" / operation_id
        if staging_parent.exists() and not activated:
            shutil.rmtree(staging_parent)


def write_active_layout(campaign_dir: Path, generation_id: str, activation_id: str) -> None:
    """Record the reconciled active generation, keeping the migration's operation id."""
    grounding = Path(campaign_dir) / "docs/grounding"
    try:
        prior_layout = json.loads((grounding / "layout.json").read_text(encoding="utf-8"))
        migration_operation_id = prior_layout.get("migration_operation_id")
    except (OSError, ValueError, AttributeError):
        migration_operation_id = None
    layout_value = {
        "version": 1, "state": "active", "generation_id": generation_id,
        "activation_id": activation_id,
    }
    if migration_operation_id:
        layout_value["migration_operation_id"] = migration_operation_id
    _write_sync(grounding / "layout.json", canonical_bytes(layout_value))


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
