"""CLI adapter for whole-bundle preview and publication inspection."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from campaignlib.grounding_config import promotion_config_from_summary_native
from pipelines.summary_native.authority import AuthorityError
from pipelines.summary_native.promotion.errors import PromotionError, PromotionRecoveryRequired, recover_command
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.models import GateOutcome
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.publish import (
    UNRESOLVED_STATES,
    committed_replay,
    operation_records,
    publish_bundle,
    require_no_unresolved,
)
from pipelines.summary_native.promotion.history import joined_receipt
from pipelines.summary_native.promotion.recovery import recover_publication
from pipelines.summary_native.promotion.models import AttemptState, OperationIntent, OperationState, OpaqueId
from pipelines.summary_native.promotion.settings import load_settings, resolve_out_root
from pydantic import TypeAdapter, ValidationError
from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
from pipelines.summary_native.review.store import ReviewStoreError, load_campaign_identity


# The route caps a request id at this length; ids are never truncated, since two
# ids sharing a prefix would then name the same operation.
MAX_REQUEST_ID = 96

# contracts/cli-ui.md exit semantics. Codes not named here fall back by family.
_EXIT_INVALID = frozenset({
    "PROMOTION_PATH_CONFLICT", "PROMOTION_REQUEST_INVALID", "PROMOTION_OPERATION_CONFLICT",
    "PROMOTION_MIGRATION_REQUIRED", "PROMOTION_MIXED_RANGE", "PROMOTION_CONFIG_INVALID",
    "PROMOTION_WHOLE_BUNDLE_REQUIRED", "AUTH_LOCK_MISSING", "AUTH_UNSAFE_PATH",
    "AUTH_MIGRATION_REQUIRED", "AUTH_VALIDATION", "AUTH_TARGET_NOT_ALLOWED",
})
_EXIT_RECOVERY = frozenset({"AUTH_PENDING_TRANSACTION", "AUTH_RECOVERY"})


def exit_code(code: str) -> int:
    """Map one stable refusal code to the contract's exit status."""
    if code in _EXIT_INVALID:
        return 2
    if "STALE" in code:
        return 3
    if code in _EXIT_RECOVERY or "RECOVERY" in code or "UNKNOWN" in code:
        return 4
    if code.startswith("REVIEW_"):
        return 2
    return 5


def _preview_exit(refusal_codes: tuple[str, ...] | list[str]) -> int:
    """A blocked preview exits 5, or 2 when a refusal says the request itself is invalid.

    An unmigrated campaign, a mixed range or a path conflict cannot be fixed by
    review, so it is not reported as an ordinary blocking gate.
    """
    return 2 if any(exit_code(code) == 2 for code in refusal_codes) else 5


def _envelope(*, ok: bool, code: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": ok, "code": code, "message": message, "artifacts": [], "data": data}


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _campaign_id(root: Path) -> str:
    return str(load_campaign_identity(root).campaign_id)


def _load_check_report(root: Path, value: str, bundle) -> tuple[str | None, str | None, bool, bool]:
    if value == "claims-unavailable":
        return None, None, False, False
    from pipelines.summary_native.claims.report import load_current_report

    report = load_current_report(root, value, bundle)
    return (
        report.analysis_digest,
        report.resolution_digest,
        report.outcome == "complete",
        report.outcome == "blocked" or any(
            finding.required_disposition and all(
                resolution.finding_id != finding.finding_id
                or resolution.disposition not in {"dismiss", "accept_uncertainty"}
                for resolution in report.resolutions
            )
            for finding in report.findings
        ),
    )


def _refusal(args: Any, code: str, message: str, data: dict[str, Any] | None = None) -> int:
    """Print one refusal envelope. A dry-run keeps its preview shape, without inventing a gate."""
    if args is not None and getattr(args, "dry_run", False) and data is None:
        data = {
            "selection": None,
            "preview": {"eligible": False, "refusal_codes": [code], "changes": [], "gates": []},
            "destination": {"edited_since_publication": False},
            "refusal": {"code": code, "message": message},
        }
        _print(_envelope(ok=False, code="PROMOTION_BLOCKED", message=message, data=data))
    else:
        _print(_envelope(ok=False, code=code, message=message, data=data or {}))
    return exit_code(code)


def _validate_request(args: Any) -> None:
    if args.dry_run and (args.preview_sha256 or args.request_id):
        raise PromotionError(
            "--dry-run cannot be combined with --preview-sha256 or --request-id; "
            "preview first, then commit the displayed digest",
            code="PROMOTION_REQUEST_INVALID",
        )
    if not args.dry_run and (not args.preview_sha256 or not args.request_id):
        raise PromotionError(
            "commit requires --preview-sha256 and --request-id (or --dry-run to preview)",
            code="PROMOTION_REQUEST_INVALID",
        )
    if args.request_id is not None:
        if len(args.request_id) > MAX_REQUEST_ID:
            raise PromotionError(
                f"--request-id is longer than {MAX_REQUEST_ID} characters",
                code="PROMOTION_REQUEST_INVALID",
            )
        try:
            TypeAdapter(OpaqueId).validate_python(args.request_id, strict=True)
        except ValidationError as exc:
            raise PromotionError("--request-id is not an opaque identifier", code="PROMOTION_REQUEST_INVALID") from exc


def run(args: Any) -> int:
    root: Path | None = None
    try:
        _validate_request(args)
        settings = load_settings(args.config)
        root = settings.root
        if not args.dry_run:
            historical = committed_replay(root, args.request_id)
            if historical is not None:
                intent, state = historical
                if args.preview_sha256 != intent.preview_sha256:
                    raise PromotionError(
                        "request id is already bound to a different preview; use a new --request-id",
                        code="PROMOTION_OPERATION_CONFLICT",
                    )
                assert state.activation_id is not None
                data = joined_receipt(root, state.activation_id)
                if "publication" in data and "receipt" not in data:
                    data = {"receipt": data["publication"], "activation": data["activation"]}
                _print(_envelope(ok=True, code="OK", message="promotion already committed", data=data))
                return 0
            require_no_unresolved(
                root, request_id=args.request_id, operation_id=f"operation-{args.request_id}",
            )
        promotion_settings = promotion_config_from_summary_native(settings.summary_native)
        bundle = build_bundle_selection(
            root,
            out_root=resolve_out_root(settings, args.out_root),
            since=args.since,
            until=args.until,
            campaign_id=_campaign_id(root),
            review_id=args.review,
            rule_versions=promotion_settings.rule_versions,
            config_path=settings.grounding_path,
        )
        try:
            analysis, resolution, claims_complete, claims_blocking = _load_check_report(
                root, args.check_report, bundle
            )
        except PromotionError as exc:
            # A named report that has not been produced yet is an ordinary
            # blocking gate. Preserve the complete read-only manifest/diff so
            # the operator can still review what would be published.
            if exc.code != "CLAIMS_INCOMPLETE":
                raise
            analysis = resolution = None
            claims_complete = claims_blocking = False
        signoffs = None
        signoff_failure = None
        try:
            signoffs = load_signoff_bindings(
                root, bundle, analysis_digest=analysis, resolution_digest=resolution,
            )
        except PromotionError as exc:
            signoff_failure = GateOutcome(
                gate="document-signoffs", state="blocked", code=exc.code, message=str(exc)
            )
        except AuthorityError as exc:
            # The lock or ledger is the problem, not a missing decision.
            signoff_failure = GateOutcome(
                gate="document-signoffs", state="blocked", code=exc.code, message=str(exc)
            )
        except (ReviewStoreError, OSError, ValueError) as exc:
            signoff_failure = GateOutcome(
                gate="document-signoffs",
                state="blocked",
                code="PROMOTION_SIGNOFF_REQUIRED",
                message=f"four current grounding-bundle-signoff/2 decisions are required ({exc})",
            )
        preview = preview_bundle(
            root,
            bundle,
            signoffs=signoffs,
            analysis_digest=analysis,
            resolution_digest=resolution,
            claims_complete=claims_complete,
            claims_blocking=claims_blocking,
            signoff_failure=signoff_failure,
        )
        destination = {
            "generation_id": preview.expected_generation_id,
            "live_digest": preview.live_digest,
            "edited_since_publication": preview.destination_edited_since_publication,
        }
        data = {
            "selection": bundle.model_dump(mode="json"),
            "preview": preview.model_dump(mode="json"),
            "destination": destination,
        }
        if not args.dry_run:
            if args.preview_sha256 != preview.preview_sha256:
                raise PromotionError(
                    "preview digest is stale; preview again and confirm the new digest",
                    code="PROMOTION_STALE_PREVIEW",
                )
            if signoffs is None or not preview.eligible:
                _print(_envelope(ok=False, code="PROMOTION_BLOCKED", message="promotion preview is blocked", data=data))
                return _preview_exit(preview.refusal_codes)
            result = publish_bundle(
                root, bundle, preview, signoffs=signoffs,
                analysis_digest=analysis or "", resolution_digest=resolution or "",
                request_id=args.request_id, operation_id=f"operation-{args.request_id}",
                generation_id=f"generation-{args.request_id}", actor="summary-native-cli",
                claims_blocking=claims_blocking, check_report=args.check_report,
            )
            _print(_envelope(ok=True, code="OK", message="promotion committed", data=result))
            return 0
        _print(_envelope(
            ok=preview.eligible,
            code="OK" if preview.eligible else "PROMOTION_BLOCKED",
            message="promotion preview is eligible" if preview.eligible else "promotion preview is blocked",
            data=data,
        ))
        return 0 if preview.eligible else _preview_exit(preview.refusal_codes)
    except PromotionRecoveryRequired as exc:
        data = {"operation_id": exc.operation_id} if exc.operation_id else None
        if data is not None:
            data["recover"] = recover_command(exc.operation_id)
        return _refusal(args, exc.code, str(exc), data)
    except (PromotionError, AuthorityError, ReviewStoreError) as exc:
        return _refusal(args, exc.code, str(exc))
    except (OSError, ValueError):
        operation_id = f"operation-{args.request_id}" if getattr(args, "request_id", None) else None
        state_value = None
        if operation_id and root is not None:
            try:
                _intent, state = _read_operation(root, operation_id)
                state_value = state.state.value
            except PromotionError:
                pass
        if state_value in {"activation_pending", "commit_unknown", "intervention_required"}:
            payload = _envelope(
                ok=False, code="PROMOTION_COMMIT_UNKNOWN",
                message="publication outcome requires explicit recovery",
                data={"operation_id": operation_id, "state": state_value,
                      "recover": recover_command(operation_id)},
            )
            _print(payload)
            return 4
        _print(_envelope(ok=False, code="PROMOTION_COMMAND_FAILED", message="promotion failed safely", data={}))
        return 70


def _read_operation(root: Path, operation_id: str) -> tuple[OperationIntent, OperationState]:
    try:
        TypeAdapter(OpaqueId).validate_python(operation_id, strict=True)
    except ValidationError as exc:
        raise PromotionError("publication operation id is invalid", code="PROMOTION_HISTORY_INVALID") from exc
    directory = root / "docs/grounding/operations" / operation_id
    try:
        intent_bytes = (directory / "intent.json").read_bytes()
        intent = OperationIntent.model_validate_json(intent_bytes)
        state = OperationState.model_validate_json((directory / "state.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise PromotionError(
            f"publication operation {operation_id} is missing or unreadable; "
            f"run `{recover_command(operation_id)}`",
            code="PROMOTION_HISTORY_INVALID",
        ) from exc
    if (intent.operation_id != operation_id or state.operation_id != operation_id
            or hashlib.sha256(intent_bytes).hexdigest() != state.intent_sha256):
        raise PromotionError("publication operation identity differs", code="PROMOTION_HISTORY_INVALID")
    if state.state is AttemptState.COMMITTED:
        if state.activation_id is None:
            raise PromotionError("committed operation has no activation", code="PROMOTION_HISTORY_INVALID")
        joined_receipt(root, state.activation_id)
    return intent, state


def _status_rows(root: Path) -> list[dict[str, Any]]:
    """Every operation, including one whose records cannot be read (never skipped)."""
    rows = []
    for record in operation_records(root):
        if record.problem is None:
            row = record.state.model_dump(mode="json")
            unresolved = record.state.state in UNRESOLVED_STATES
        else:
            row = {"operation_id": record.operation_id, "state": "unreadable", "detail": record.problem}
            unresolved = True
        if unresolved:
            row["recover"] = recover_command(record.operation_id)
        rows.append(row)
    return rows


def run_inspection(args: Any) -> int:
    try:
        root = load_settings(args.config).root
        if args.promotion_command == "recover":
            data = recover_publication(root, args.operation)
        elif args.promotion_command == "receipt":
            _intent, state = _read_operation(root, args.operation)
            if state.state is not AttemptState.COMMITTED or state.activation_id is None:
                raise PromotionError("operation has no completed receipt", code="PROMOTION_RECEIPT_UNAVAILABLE")
            data = joined_receipt(root, state.activation_id)
        elif args.operation:
            try:
                intent, state = _read_operation(root, args.operation)
            except PromotionError:
                # Inspection reports an unreadable operation; it does not fail on it.
                rows = [row for row in _status_rows(root) if row["operation_id"] == args.operation]
                if not rows or rows[0]["state"] != "unreadable":
                    raise
                data = {"intent": None, "state": rows[0]}
            else:
                data = {"intent": intent.model_dump(mode="json"), "state": state.model_dump(mode="json")}
        else:
            data = {"operations": _status_rows(root)}
        _print(_envelope(ok=True, code="OK", message="promotion inspection complete", data=data))
        return 0
    except (PromotionError, AuthorityError, ReviewStoreError) as exc:
        _print(_envelope(ok=False, code=exc.code, message=str(exc), data={}))
        return exit_code(exc.code)
