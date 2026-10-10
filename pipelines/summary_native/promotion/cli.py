"""CLI adapter for whole-bundle preview and publication inspection."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from campaignlib.config import campaign_root_for_config
from campaignlib.grounding_config import promotion_config_from_summary_native
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.models import GateOutcome
from pipelines.summary_native.promotion.preview import preview_bundle
from pipelines.summary_native.promotion.publish import publish_bundle
from pipelines.summary_native.promotion.history import joined_receipt
from pipelines.summary_native.promotion.recovery import recover_publication
from pipelines.summary_native.promotion.models import AttemptState, OperationIntent, OperationState, OpaqueId
from pydantic import TypeAdapter, ValidationError
from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
from pipelines.summary_native.review.store import ReviewStoreError, load_campaign_identity


def _envelope(*, ok: bool, code: str, message: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": ok, "code": code, "message": message, "artifacts": [], "data": data}


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


def _out_root(root: Path, config_path: Path, raw_summary: object, explicit: str | None) -> str:
    if explicit:
        candidate = root / explicit
    else:
        configured = raw_summary.get("out_root") if isinstance(raw_summary, dict) else None
        candidate = config_path.parent / configured if isinstance(configured, str) else root / "docs/summary_native"
    resolved = candidate.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise PromotionError("summary_native out_root escapes campaign", code="PROMOTION_PATH_CONFLICT") from exc


def run(args: Any) -> int:
    config_path = Path(args.config).expanduser().resolve()
    root = campaign_root_for_config(config_path)
    try:
        if not args.dry_run and args.request_id:
            historical = _historical_request(root, args.request_id)
            if historical is not None:
                intent, state = historical
                if args.preview_sha256 != intent.preview_sha256:
                    raise PromotionError(
                        "request id is already bound to a different preview",
                        code="PROMOTION_OPERATION_CONFLICT",
                    )
                assert state.activation_id is not None
                data = joined_receipt(root, state.activation_id)
                if "publication" in data and "receipt" not in data:
                    data = {"receipt": data["publication"], "activation": data["activation"]}
                print(json.dumps(_envelope(ok=True, code="OK", message="promotion already committed", data=data), sort_keys=True))
                return 0
        import yaml

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        summary = raw.get("summary_native") if isinstance(raw, dict) else None
        settings = promotion_config_from_summary_native(summary)
        bundle = build_bundle_selection(
            root,
            out_root=_out_root(root, config_path, summary, args.out_root),
            since=args.since,
            until=args.until,
            campaign_id=_campaign_id(root),
            review_id=args.review,
            rule_versions=settings.rule_versions,
            config_path=config_path,
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
        except (ReviewStoreError, OSError, ValueError):
            signoff_failure = GateOutcome(
                gate="document-signoffs",
                state="blocked",
                code="PROMOTION_SIGNOFF_REQUIRED",
                message="four current grounding-bundle-signoff/2 decisions are required",
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
            if not args.preview_sha256 or not args.request_id:
                raise PromotionError(
                    "commit requires --preview-sha256 and --request-id",
                    code="PROMOTION_REQUEST_INVALID",
                )
            if args.preview_sha256 != preview.preview_sha256:
                raise PromotionError("preview digest is stale", code="PROMOTION_PREVIEW_STALE")
            if signoffs is None or not preview.eligible:
                payload = _envelope(ok=False, code="PROMOTION_BLOCKED", message="promotion preview is blocked", data=data)
                print(json.dumps(payload, sort_keys=True))
                return 5
            suffix = args.request_id[:96]
            result = publish_bundle(
                root, bundle, preview, signoffs=signoffs,
                analysis_digest=analysis or "", resolution_digest=resolution or "",
                request_id=args.request_id, operation_id=f"operation-{suffix}",
                generation_id=f"generation-{suffix}", actor="summary-native-cli",
                claims_blocking=claims_blocking, check_report=args.check_report,
            )
            print(json.dumps(_envelope(ok=True, code="OK", message="promotion committed", data=result), sort_keys=True))
            return 0
        payload = _envelope(
            ok=preview.eligible,
            code="OK" if preview.eligible else "PROMOTION_BLOCKED",
            message="promotion preview is eligible" if preview.eligible else "promotion preview is blocked",
            data=data,
        )
        print(json.dumps(payload, sort_keys=True))
        return 0 if preview.eligible else 5
    except PromotionError as exc:
        # Even a malformed candidate returns the stable preview-shaped refusal
        # envelope when enough explicit range context exists to identify it.
        data = {
            "selection": None,
            "preview": {
                "eligible": False,
                "refusal_codes": [exc.code],
                "changes": [],
                "gates": [{"gate": "paths", "state": "blocked", "code": exc.code, "message": str(exc)}],
            },
            "destination": {"edited_since_publication": False},
        }
        code = "PROMOTION_BLOCKED" if args.dry_run else exc.code
        print(json.dumps(_envelope(ok=False, code=code, message=str(exc), data=data), sort_keys=True))
        if exc.code in {"PROMOTION_PATH_CONFLICT", "PROMOTION_REQUEST_INVALID", "PROMOTION_OPERATION_CONFLICT"}:
            return 2
        if "STALE" in exc.code:
            return 3
        if "RECOVERY" in exc.code or "UNKNOWN" in exc.code:
            return 4
        return 5
    except (OSError, ValueError) as exc:
        operation_id = f"operation-{args.request_id[:96]}" if getattr(args, "request_id", None) else None
        state_value = None
        if operation_id:
            try:
                _intent, state = _read_operation(root, operation_id)
                state_value = state.state.value
            except PromotionError:
                pass
        if state_value in {"activation_pending", "commit_unknown", "intervention_required"}:
            payload = _envelope(
                ok=False, code="PROMOTION_COMMIT_UNKNOWN",
                message="publication outcome requires explicit recovery",
                data={"operation_id": operation_id, "state": state_value},
            )
            print(json.dumps(payload, sort_keys=True))
            return 4
        payload = _envelope(ok=False, code="PROMOTION_COMMAND_FAILED", message="promotion failed safely", data={})
        print(json.dumps(payload, sort_keys=True))
        return 2


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
        raise PromotionError("publication operation is missing or invalid", code="PROMOTION_HISTORY_INVALID") from exc
    if (intent.operation_id != operation_id or state.operation_id != operation_id
            or hashlib.sha256(intent_bytes).hexdigest() != state.intent_sha256):
        raise PromotionError("publication operation identity differs", code="PROMOTION_HISTORY_INVALID")
    if state.state is AttemptState.COMMITTED:
        if state.activation_id is None:
            raise PromotionError("committed operation has no activation", code="PROMOTION_HISTORY_INVALID")
        joined_receipt(root, state.activation_id)
    return intent, state


def _historical_request(root: Path, request_id: str) -> tuple[OperationIntent, OperationState] | None:
    operations = root / "docs/grounding/operations"
    if not operations.is_dir():
        return None
    matched = None
    for state_path in sorted(operations.glob("*/state.json")):
        intent, state = _read_operation(root, state_path.parent.name)
        if intent.request_id != request_id:
            continue
        if matched is not None:
            raise PromotionError("request id has conflicting operation history", code="PROMOTION_HISTORY_INVALID")
        if state.state is AttemptState.COMMITTED:
            matched = (intent, state)
    return matched


def run_inspection(args: Any) -> int:
    config_path = Path(args.config).expanduser().resolve()
    root = campaign_root_for_config(config_path)
    try:
        if args.promotion_command == "recover":
            data = recover_publication(root, args.operation)
        elif args.promotion_command == "receipt":
            _intent, state = _read_operation(root, args.operation)
            if state.state is not AttemptState.COMMITTED or state.activation_id is None:
                raise PromotionError("operation has no completed receipt", code="PROMOTION_RECEIPT_UNAVAILABLE")
            data = joined_receipt(root, state.activation_id)
        elif args.operation:
            intent, state = _read_operation(root, args.operation)
            data = {"intent": intent.model_dump(mode="json"), "state": state.model_dump(mode="json")}
        else:
            operations = root / "docs/grounding/operations"
            values = []
            for state_path in sorted(operations.glob("*/state.json")) if operations.is_dir() else ():
                try:
                    state = OperationState.model_validate_json(state_path.read_bytes())
                except ValueError:
                    continue
                values.append(state.model_dump(mode="json"))
            data = {"operations": values}
        print(json.dumps(_envelope(ok=True, code="OK", message="promotion inspection complete", data=data), sort_keys=True))
        return 0
    except PromotionError as exc:
        print(json.dumps(_envelope(ok=False, code=exc.code, message=str(exc), data={}), sort_keys=True))
        return 4 if "RECOVERY" in exc.code else 5
