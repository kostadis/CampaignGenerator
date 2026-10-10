"""summary_native routes — grounding-doc drafts built from reviewed summaries.

Every run route shells out to ``console_script("summary_native")`` and streams
it through the grounding router's SSE helper (feature 031, Principle VI: the UI
invokes the CLI and never reimplements it). Defaults resolve from
``<config>/grounding.yaml``'s ``summary_native`` group at the route edge; a
route takes sentinels (``""`` / ``None``), never a default literal, and the
declared defaults live in ``pipelines/summary_native/schema.py`` (Principle XII).

``--registry``, ``--canon`` and ``--out-root`` are deliberately never passed:
they are campaign-layout paths with no per-run UI control (GM ruling). The CLI
reads ``grounding.yaml``'s ``summary_native`` group itself (``out_root``,
``canon_file``, ``registry``), so the config file is where they change
(contracts/http.md, "Deliberately CLI-only").

The read-only routes (``/chapters``, ``/report``, ``/drafts``) only list files
and read a JSON the CLI wrote. None of them parses summary content or calls a
model.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from campaignlib.constants import config_path
from campaignlib.grounding_config import DEFAULT_MAX_REPORT_BYTES
from campaignlib.players_config import PLAYERS_CONFIG_FILENAME
from campaignlib.projection_config import PROJECTION_CONFIG_FILENAME, load_projection_config
from pipelines.summary_native import annotate, audit_select, freshness, notes, resolve, schema, thread_attach
from server.grounding_config_shared import SummaryNativeRun
from server.platform_config_service import resolve_selection, selection_cli_args
from server.routers.grounding import (
    _pick,
    _service,
    _sse_response,
)
from server.subprocess_runner import BoundedJSONError, console_script, run_bounded_json
from server.scheduler_status import project_latest

_ENDPOINT_BACKENDS = frozenset({"dgx"})  # the only backend that takes --endpoints
AUTHORITY_JSON_TIMEOUT_SECONDS = 10
PROMOTION_PREVIEW_TIMEOUT_SECONDS = 30
PROMOTION_COMMAND_TIMEOUT_SECONDS = 60

router = APIRouter()

#: ``resolve_selection``'s ``service_name`` and the owner of the override.
_SERVICE_NAME = "summary_native"


class PromotionPreviewRequest(BaseModel):
    """Explicit selection forwarded unchanged to ``summary_native promote``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    since: int = Field(ge=0)
    until: int = Field(ge=0)
    review: str
    check_report: str
    out_root: str | None = None

    @field_validator("review", "check_report")
    @classmethod
    def nonempty_selection(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be non-empty")
        return value

    @field_validator("out_root")
    @classmethod
    def nonempty_optional_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must be non-empty when supplied")
        return value

    @model_validator(mode="after")
    def ordered_range(self) -> "PromotionPreviewRequest":
        if self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self


class PromotionCommitRequest(PromotionPreviewRequest):
    preview_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PromotionOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class MigrationApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClaimsSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    since: int = Field(ge=0); until: int = Field(ge=0)
    out_root: str | None = None; sources: str | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.until < self.since: raise ValueError("until must follow since")
        return self


class ClaimsSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selection: str = Field(min_length=1)


class ClaimsSelectionSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selection: str | dict[str, Any]
    reviewer: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def object_requires_reviewer(self):
        if isinstance(self.selection, dict) and self.reviewer is None:
            raise ValueError("selection object requires reviewer")
        return self


class ClaimsChunkSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    selection: dict[str, Any]
    source_ids: list[str]


class ClaimsImportRequest(ClaimsSelectionRequest):
    candidates: str = Field(min_length=1)


class ClaimsExtractRequest(ClaimsSelectionRequest):
    backend: str | None = Field(default=None, min_length=1); model: str | None = Field(default=None, min_length=1)
    max_tokens: int | None = Field(default=None, gt=0); chunk_chars: int | None = Field(default=None, gt=0)
    force: bool = False


class ClaimsReviewRequest(ClaimsSelectionRequest):
    review: str = Field(min_length=1); candidates: str | None = None


class ClaimsCheckRequest(ClaimsSelectionRequest):
    review: str = Field(min_length=1)


class ClaimsShowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    report: str = Field(min_length=1)


class ClaimsDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review: str = Field(min_length=1); item: str = Field(min_length=1)
    expected_decision_revision: int = Field(ge=0)
    disposition: str = Field(pattern=r"^(dismiss|accept_uncertainty)$")
    rationale: str = Field(min_length=1)


# ── Resolution helpers ──────────────────────────────────────────────────────

def _run_config(request: Request) -> SummaryNativeRun:
    return _service(request).resolved().summary_native


def _pick_num(explicit: int | float | None, stored: int | float | None):
    """Explicit request value wins; ``None`` (not ``0``) means "not supplied".

    ``recent_chapters=0`` ("every chapter") is a meaningful value, so unlike
    ``grounding._pick`` a zero is an answer.
    """
    return explicit if explicit is not None else stored


def _require_doc(doc: str) -> str:
    if doc not in schema.DOCS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown doc {doc!r}; choose one of: {', '.join(schema.DOCS)}",
        )
    return doc


def _require_dir(run: SummaryNativeRun, explicit: str) -> str:
    value = _pick((explicit or "").strip(), run.summaries_dir)
    if not value or not str(value).strip():
        raise HTTPException(
            status_code=400,
            detail=(
                "no summaries directory: pass ?summaries_dir= or set "
                "grounding.yaml summary_native.summaries_dir"
            ),
        )
    return str(value).strip()


def _require_range(run: SummaryNativeRun, since: int | None, until: int | None) -> tuple[int, int]:
    lo = _pick_num(since, run.range_since)
    hi = _pick_num(until, run.range_until)
    if lo is None or hi is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "choose a chapter range: pass ?since= and ?until=, or set "
                "grounding.yaml summary_native.range_since and range_until "
                "(the UI never assumes all chapters)"
            ),
        )
    return lo, hi


def _base_cmd(command: str, doc: str | None, summaries_dir: str, since: int, until: int) -> list[str]:
    cmd = [console_script("summary_native"), command]
    if doc:
        cmd.append(doc)
    return cmd + [
        "--summaries-dir", summaries_dir,
        "--since", str(since),
        "--until", str(until),
    ]


def _range_dir(run: SummaryNativeRun, since: int, until: int) -> Path:
    return schema.resolve_under(Path.cwd(), run.out_root) / f"ch{since:03d}-{until:03d}"


# ── Authority command boundary ─────────────────────────────────────────────

def _authority_campaign_dir(request: Request, requested: str | None = None) -> Path:
    """Return the campaign already selected by the local server.

    Authority commands are campaign-local.  The page may repeat the selected
    campaign directory for ``init`` but cannot retarget the server at another
    directory.  The authority CLI remains the owner of all policy checks.
    """
    platform = getattr(request.app.state, "platform", None)
    configured = getattr(platform, "campaign_dir", None)
    root = Path(configured or Path.cwd()).expanduser().resolve()
    if requested and requested.strip():
        candidate = Path(requested).expanduser().resolve()
        if candidate != root:
            raise HTTPException(status_code=400, detail="campaign_dir must match the active campaign")
    return root


def _authority_path(root: Path, value: object, field: str) -> str:
    """Accept a non-empty campaign-contained path without interpreting it."""
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{field} is required")
    raw = Path(value.strip()).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} must stay inside the active campaign") from exc
    # SSE commands run from the server process' current working directory,
    # which is not guaranteed to be the configured platform campaign in tests
    # or embedded deployments.  Pass the validated resolved path to the CLI.
    return str(candidate)


def _authority_value(payload: dict, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return value.strip()


def _authority_command(root: Path, *args: str) -> list[str]:
    return [console_script("summary_native"), "authority", *args, "--campaign-dir", str(root), "--json"]


def _authority_error(exc: BoundedJSONError):
    """Keep the CLI's stable exit classes visible at the HTTP boundary."""
    payload = exc.payload if isinstance(exc.payload, dict) else None
    if payload is not None:
        code = str(payload.get("code") or "")
        status = {
            "AUTH_VALIDATION": 422,
            "AUTH_STALE": 409,
            "AUTH_RECOVERY": 423,
            "AUTH_CONFLICT": 409,
        }.get(code.split("_", 2)[0] + "_" + code.split("_", 2)[1] if code.startswith("AUTH_") and code.count("_") >= 1 else code)
        # Authority codes may be refined (for example AUTH_STALE_PROPOSAL),
        # while their documented class remains the first two components.
        if status is None:
            if code.startswith("AUTH_VALIDATION"):
                status = 422
            elif code.startswith("AUTH_STALE"):
                status = 409
            elif code.startswith("AUTH_RECOVERY"):
                status = 423
            elif code.startswith("AUTH_CONFLICT"):
                status = 409
            else:
                status = 500
        return JSONResponse(payload, status_code=status)
    status = 504 if exc.category in {"timeout", "output_limit"} else 500
    return JSONResponse({"detail": str(exc), "code": exc.category}, status_code=status)


async def _authority_json(request: Request, *args: str):
    root = _authority_campaign_dir(request)
    try:
        return await run_bounded_json(
            _authority_command(root, *args),
            cwd=str(root),
            timeout_seconds=AUTHORITY_JSON_TIMEOUT_SECONDS,
            max_output_bytes=1_048_576,
            save_run_log=False,
        )
    except BoundedJSONError as exc:
        return _authority_error(exc)


def _authority_stream(request: Request, *args: str):
    root = _authority_campaign_dir(request)
    # `_sse_response` is the established Summary Native command runner.  The
    # command itself emits the JSON envelope, so its full digest/receipt data
    # remains visible to the caller rather than being reconstructed by a route.
    return _sse_response(_authority_command(root, *args))


# ── Whole-bundle promotion preview (typed CLI adapter) ─────────────────────

def _promotion_preview_command(root: Path, payload: PromotionPreviewRequest) -> list[str]:
    command = [
        console_script("summary_native"),
        "promote",
        "--config", str(config_path(root, "grounding.yaml")),
        "--since", str(payload.since),
        "--until", str(payload.until),
        "--review", payload.review,
        "--check-report", payload.check_report,
        "--dry-run",
        "--json",
    ]
    if payload.out_root is not None:
        command.extend(("--out-root", payload.out_root))
    return command


def _promotion_preview_error(exc: BoundedJSONError) -> JSONResponse:
    # A valid preview may be blocked and therefore use the CLI's documented
    # nonzero exit while still returning the complete manifest and differences.
    # Preserve that domain envelope byte-for-byte at the HTTP boundary.
    if isinstance(exc.payload, dict):
        return JSONResponse(exc.payload, status_code=200)
    status = 504 if exc.category in {"timeout", "output_limit"} else 503
    return JSONResponse(
        {"ok": False, "code": "PROMOTION_COMMAND_FAILED", "message": "Promotion preview failed safely."},
        status_code=status,
    )


@router.post("/promotion/preview")
async def promotion_preview(request: Request, payload: PromotionPreviewRequest):
    """Return the installed CLI's complete dry-run envelope without mutation."""
    root = _authority_campaign_dir(request)
    try:
        return await run_bounded_json(
            _promotion_preview_command(root, payload),
            cwd=str(root),
            timeout_seconds=PROMOTION_PREVIEW_TIMEOUT_SECONDS,
            max_output_bytes=DEFAULT_MAX_REPORT_BYTES,
            save_run_log=False,
        )
    except BoundedJSONError as exc:
        return _promotion_preview_error(exc)


def _promotion_commit_command(root: Path, payload: PromotionCommitRequest) -> list[str]:
    command = _promotion_preview_command(root, payload)
    command.remove("--dry-run")
    command.extend(("--preview-sha256", payload.preview_sha256, "--request-id", payload.request_id))
    return command


def _promotion_inspection_command(root: Path, action: str, operation: str | None = None) -> list[str]:
    command = [console_script("summary_native"), "promotion", action,
               "--config", str(config_path(root, "grounding.yaml"))]
    if operation is not None:
        command.extend(("--operation", operation))
    command.append("--json")
    return command


def _migration_command(root: Path, mode: str, value: str | None = None) -> list[str]:
    command = [console_script("migrate_grounding_bundle"), "--campaign-dir", str(root)]
    if mode == "apply":
        command.extend(("--plan-sha256", value or ""))
    else:
        command.append(f"--{mode}")
    if mode == "recover":
        command.extend(("--operation", value or ""))
    command.append("--json")
    return command


async def _promotion_command_json(
    request: Request, command: list[str], *, mutation: bool = False,
    operation: str | None = None, request_id: str | None = None,
):
    root = _authority_campaign_dir(request)
    try:
        return await run_bounded_json(
            command, cwd=str(root), timeout_seconds=PROMOTION_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=DEFAULT_MAX_REPORT_BYTES, save_run_log=False,
        )
    except BoundedJSONError as exc:
        if isinstance(exc.payload, dict):
            return JSONResponse(exc.payload, status_code=200)
        if mutation:
            return JSONResponse({
                "ok": False,
                "code": "PROMOTION_COMMIT_UNKNOWN",
                "message": "The command response was lost. Inspect status and recover explicitly; do not retry automatically.",
                "artifacts": [],
                "data": {"operation_id": operation, "request_id": request_id},
            }, status_code=504 if exc.category in {"timeout", "output_limit"} else 503)
        return _promotion_preview_error(exc)


@router.post("/promotion/commit")
async def promotion_commit(request: Request, payload: PromotionCommitRequest):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(
        request, _promotion_commit_command(root, payload), mutation=True,
        request_id=payload.request_id, operation=f"operation-{payload.request_id[:96]}",
    )


@router.get("/promotion/status")
async def promotion_status(request: Request, operation: str | None = None):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _promotion_inspection_command(root, "status", operation))


@router.post("/promotion/receipt")
async def promotion_receipt(request: Request, payload: PromotionOperationRequest):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _promotion_inspection_command(root, "receipt", payload.operation))


@router.post("/promotion/recover")
async def promotion_recover(request: Request, payload: PromotionOperationRequest):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _promotion_inspection_command(root, "recover", payload.operation), mutation=True, operation=payload.operation)


@router.post("/promotion/migration/preview")
async def migration_preview(request: Request):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _migration_command(root, "dry-run"))


@router.post("/promotion/migration/apply")
async def migration_apply(request: Request, payload: MigrationApplyRequest):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _migration_command(root, "apply", payload.plan_sha256), mutation=True)


@router.get("/promotion/migration/status")
async def migration_status(request: Request):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _migration_command(root, "status"))


@router.post("/promotion/migration/verify")
async def migration_verify(request: Request):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _migration_command(root, "verify"))


@router.post("/promotion/migration/recover")
async def migration_recover(request: Request, payload: PromotionOperationRequest):
    root = _authority_campaign_dir(request)
    return await _promotion_command_json(request, _migration_command(root, "recover", payload.operation), mutation=True, operation=payload.operation)


# ── Private claims workflow (installed CLI adapters) ──────────────────────

def _claims_command(root: Path, *args: str) -> list[str]:
    return [console_script("summary_native"), "claims", *args,
            "--config", str(config_path(root, "grounding.yaml")), "--json"]


async def _claims_json(request: Request, command: list[str], *, mutation: bool = False, stdin_bytes: bytes | None = None):
    root = _authority_campaign_dir(request)
    try:
        return await run_bounded_json(
            command, cwd=str(root), timeout_seconds=PROMOTION_COMMAND_TIMEOUT_SECONDS,
            max_output_bytes=DEFAULT_MAX_REPORT_BYTES, save_run_log=False, stdin_bytes=stdin_bytes,
        )
    except BoundedJSONError as exc:
        if isinstance(exc.payload, dict):
            return JSONResponse(exc.payload, status_code=200)
        if mutation:
            return JSONResponse({
                "ok": False, "code": "CLAIMS_COMMAND_UNKNOWN",
                "message": "The command response was lost. Inspect current claims state before retrying.",
                "artifacts": [], "data": {},
            }, status_code=504 if exc.category in {"timeout", "output_limit"} else 503)
        return JSONResponse({"ok": False, "code": "CLAIMS_COMMAND_FAILED",
                             "message": "Claims command failed safely.", "artifacts": [], "data": {}}, status_code=503)


@router.post("/claims/select")
async def claims_select(request: Request, payload: ClaimsSelectRequest):
    root = _authority_campaign_dir(request); args = ["select", "--since", str(payload.since), "--until", str(payload.until)]
    if payload.out_root: args += ["--out-root", payload.out_root]
    if payload.sources: args += ["--sources", _authority_path(root, payload.sources, "sources")]
    return await _claims_json(request, _claims_command(root, *args))


@router.post("/claims/selection/save")
async def claims_selection_save(request: Request, payload: ClaimsSelectionSaveRequest):
    root = _authority_campaign_dir(request)
    if isinstance(payload.selection, str):
        return await _claims_json(request, _claims_command(root, "selection", "save", "--input", _authority_path(root, payload.selection, "selection")), mutation=True)
    raw = json.dumps(payload.selection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return await _claims_json(request, _claims_command(root, "selection", "save", "--input", "-", "--reviewer", payload.reviewer), mutation=True, stdin_bytes=raw)


@router.post("/claims/selection/chunks")
async def claims_selection_chunks(request: Request, payload: ClaimsChunkSelectionRequest):
    root = _authority_campaign_dir(request)
    args = ["selection", "chunks", "--input", "-"]
    for source_id in payload.source_ids: args += ["--source", source_id]
    raw = json.dumps(payload.selection, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return await _claims_json(request, _claims_command(root, *args), stdin_bytes=raw)


@router.post("/claims/extract")
async def claims_extract(request: Request, payload: ClaimsExtractRequest):
    root = _authority_campaign_dir(request); args = ["extract", "--selection", _authority_path(root, payload.selection, "selection")]
    if payload.backend is not None: args += ["--backend", payload.backend]
    if payload.model is not None: args += ["--model", payload.model]
    if payload.max_tokens is not None: args += ["--max-tokens", str(payload.max_tokens)]
    if payload.chunk_chars is not None: args += ["--chunk-chars", str(payload.chunk_chars)]
    if payload.force: args.append("--force")
    return await _claims_json(request, _claims_command(root, *args), mutation=True)


@router.post("/claims/import")
async def claims_import(request: Request, payload: ClaimsImportRequest):
    root = _authority_campaign_dir(request)
    return await _claims_json(request, _claims_command(root, "import", "--selection", _authority_path(root, payload.selection, "selection"), "--candidates", _authority_path(root, payload.candidates, "candidates")), mutation=True)


@router.post("/claims/review")
async def claims_review(request: Request, payload: ClaimsReviewRequest):
    root = _authority_campaign_dir(request); args = ["review", "--selection", _authority_path(root, payload.selection, "selection"), "--review", payload.review]
    if payload.candidates: args += ["--candidates", _authority_path(root, payload.candidates, "candidates")]
    return await _claims_json(request, _claims_command(root, *args), mutation=True)


@router.post("/claims/check")
async def claims_check(request: Request, payload: ClaimsCheckRequest):
    root = _authority_campaign_dir(request)
    return await _claims_json(request, _claims_command(root, "check", "--selection", _authority_path(root, payload.selection, "selection"), "--review", payload.review), mutation=True)


@router.post("/claims/show")
async def claims_show(request: Request, payload: ClaimsShowRequest):
    root = _authority_campaign_dir(request)
    return await _claims_json(request, _claims_command(root, "show", "--report", _authority_path(root, payload.report, "report")))


@router.post("/claims/disposition")
async def claims_disposition(request: Request, payload: ClaimsDispositionRequest):
    root = _authority_campaign_dir(request)
    return await _claims_json(request, _claims_command(
        root, "prepare-disposition", "--review", payload.review, "--item", payload.item,
        "--expected-decision-revision", str(payload.expected_decision_revision),
        "--disposition", payload.disposition, "--rationale", payload.rationale,
    ), mutation=True)


# ── Authority ledger (CLI-backed JSON / SSE) ───────────────────────────────

@router.get("/authority/status")
async def authority_status(request: Request):
    return await _authority_json(request, "status")


@router.get("/authority/records")
async def authority_records(request: Request, status: str | None = None):
    args = ["list"]
    if status and status.strip():
        args += ["--status", status.strip()]
    return await _authority_json(request, *args)


@router.get("/authority/records/{record_id}")
async def authority_record(request: Request, record_id: str):
    return await _authority_json(request, "show", record_id)


@router.get("/authority/records/{record_id}/history")
async def authority_record_history(request: Request, record_id: str):
    return await _authority_json(request, "history", record_id)


@router.get("/authority/conflicts")
async def authority_conflicts(request: Request, status: str | None = None):
    args = ["conflicts"]
    if status and status.strip():
        args += ["--status", status.strip()]
    return await _authority_json(request, *args)


@router.get("/authority/conflicts/{conflict_id}/history")
async def authority_conflict_history(request: Request, conflict_id: str):
    return await _authority_json(request, "conflict", "history", conflict_id)


@router.post("/authority/validate")
async def authority_validate(request: Request):
    return await _authority_json(request, "validate")


@router.post("/authority/notes/preview")
async def authority_notes_preview(request: Request, payload: dict):
    """Materialize the exact planning-note set through the authority CLI.

    Selectors are persisted by the planning owner.  The browser supplies only
    the audience target, so the preview and subsequent synthesis resolve the
    same campaign configuration and the CLI remains the policy owner for
    external locations and membership drift.
    """
    audience = payload.get("audience", "gm")
    if not isinstance(audience, str) or not audience.strip():
        raise HTTPException(status_code=400, detail="audience is required")
    args = ["notes", "preview", "--audience", audience.strip()]
    planning_config = payload.get("planning_config")
    if planning_config is not None:
        root = _authority_campaign_dir(request)
        args += ["--planning-config", _authority_path(root, planning_config, "planning_config")]
    return await _authority_json(request, *args)


@router.post("/authority/init")
async def authority_init(request: Request, payload: dict):
    root = _authority_campaign_dir(request, payload.get("campaign_dir"))
    args = ["init"]
    campaign = payload.get("campaign")
    if campaign is not None:
        if not isinstance(campaign, str) or not campaign.strip():
            raise HTTPException(status_code=400, detail="campaign must be a non-empty string")
        args += ["--campaign", campaign.strip()]
    return _sse_response(_authority_command(root, *args))


@router.post("/authority/records/stage")
async def authority_record_stage(request: Request, payload: dict):
    root = _authority_campaign_dir(request)
    record_file = _authority_path(root, payload.get("record_file"), "record_file")
    return _authority_stream(request, "record", "stage", record_file)


@router.post("/authority/records/stages/{stage_id}/apply")
async def authority_record_apply(request: Request, stage_id: str, payload: dict):
    return _authority_stream(
        request, "record", "apply", stage_id,
        "--stage-sha256", _authority_value(payload, "stage_sha256"),
        "--expected-ledger-sha256", _authority_value(payload, "expected_ledger_sha256"),
    )


@router.post("/authority/records/{record_id}/retire")
async def authority_record_retire(request: Request, record_id: str, payload: dict):
    expected_revision = payload.get("expected_revision")
    if not isinstance(expected_revision, int) or expected_revision < 1:
        raise HTTPException(status_code=400, detail="expected_revision must be a positive integer")
    return _authority_stream(
        request, "record", "retire", record_id,
        "--reason", _authority_value(payload, "reason"),
        "--expected-revision", str(expected_revision),
        "--expected-ledger-sha256", _authority_value(payload, "expected_ledger_sha256"),
    )


@router.post("/authority/records/{record_id}/propose")
async def authority_propose(request: Request, record_id: str, payload: dict):
    root = _authority_campaign_dir(request)
    configured = _require_dir(_run_config(request), str(payload.get("summaries_dir") or ""))
    summaries_dir = _authority_path(root, configured, "summaries_dir")
    return _authority_stream(request, "propose", record_id, "--summaries-dir", summaries_dir)


@router.post("/authority/records/{record_id}/apply")
async def authority_apply(request: Request, record_id: str, payload: dict):
    return _authority_stream(
        request, "apply", record_id,
        "--proposal-sha256", _authority_value(payload, "proposal_sha256"),
    )


@router.post("/authority/records/{record_id}/withdraw")
async def authority_withdraw(request: Request, record_id: str, payload: dict):
    return _authority_stream(request, "withdraw", record_id, "--reason", _authority_value(payload, "reason"))


@router.post("/authority/conflicts/{conflict_id}/resolve")
async def authority_conflict_resolve(request: Request, conflict_id: str, payload: dict):
    root = _authority_campaign_dir(request)
    return _authority_stream(
        request, "conflict", "resolve", conflict_id,
        "--resolution-record", _authority_path(root, payload.get("resolution_record_file"), "resolution_record_file"),
        "--expected-ledger-sha256", _authority_value(payload, "expected_ledger_sha256"),
    )


@router.post("/authority/conflicts/{conflict_id}/dismiss")
async def authority_conflict_dismiss(request: Request, conflict_id: str, payload: dict):
    return _authority_stream(
        request, "conflict", "dismiss", conflict_id,
        "--reason", _authority_value(payload, "reason"),
        "--expected-ledger-sha256", _authority_value(payload, "expected_ledger_sha256"),
    )


@router.post("/authority/conflicts/identify")
async def authority_conflict_identify(request: Request, payload: dict):
    identifier = _authority_value(payload, "id")
    record_ids = payload.get("record_ids")
    if not isinstance(record_ids, list) or len(record_ids) < 2 or not all(isinstance(item, str) and item.strip() for item in record_ids):
        raise HTTPException(status_code=400, detail="record_ids must contain at least two non-empty identifiers")
    basis = payload.get("basis", "human_identified")
    if basis not in {"human_identified", "prose_candidate"}:
        raise HTTPException(status_code=400, detail="basis must be human_identified or prose_candidate")
    args = ["conflict", "identify", identifier, "--basis", basis,
            "--reason", _authority_value(payload, "reason"),
            "--expected-ledger-sha256", _authority_value(payload, "expected_ledger_sha256")]
    for record_id in record_ids:
        args += ["--record", record_id.strip()]
    return _authority_stream(request, *args)


@router.post("/authority/transactions/{transaction_id}/recover")
async def authority_recover(request: Request, transaction_id: str, payload: dict):
    # The empty body is intentional: recovery resumes only the immutable
    # transaction already named by its id; the route supplies no new bytes.
    return _authority_stream(request, "recover", transaction_id)


# ── Read-only ───────────────────────────────────────────────────────────────

def chapter_listing(directory: Path) -> dict:
    """The chapter numbers present in ``directory``, from filename prefixes only.

    Mirrors the CLI's own listing (top-level ``*.md``, ``PREFIX_RE``) so the
    range picker offers exactly the values ``--since``/``--until`` accept. The
    content of a file is never opened here. Shared with the NPC dossiers router.
    """
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"{directory}: not a directory")
    by_chapter: dict[int, list[str]] = {}
    for p in sorted(directory.iterdir()):
        if not (p.is_file() and p.suffix == ".md"):
            continue
        m = schema.PREFIX_RE.match(p.name)
        if m:
            by_chapter.setdefault(int(m.group(1)), []).append(p.name)
    return {
        "present": sorted(by_chapter),
        "files": [
            {"chapter": ch, "path": name}
            for ch in sorted(by_chapter)
            for name in by_chapter[ch]
        ],
        "duplicate_chapters": [ch for ch in sorted(by_chapter) if len(by_chapter[ch]) > 1],
    }


@router.get("/chapters")
def get_chapters(request: Request, summaries_dir: str = ""):
    """The chapter numbers present (see :func:`chapter_listing`)."""
    return chapter_listing(
        schema.resolve_under(Path.cwd(), _require_dir(_run_config(request), summaries_dir))
    )


@router.get("/report")
def get_report(request: Request, since: int | None = None, until: int | None = None):
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    path = _range_dir(run, lo, hi) / "validation_report.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="no validation report yet: run Validate")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"{path}: unreadable report: {exc}") from exc


@router.get("/drafts")
def get_drafts(request: Request, since: int | None = None, until: int | None = None):
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    range_dir = _range_dir(run, lo, hi)
    if not range_dir.is_dir():
        raise HTTPException(status_code=404, detail="no output for this range yet: run Build")
    out = []
    for doc in schema.DOCS:
        for status, suffix in (("draft", "draft"), ("incomplete", "incomplete")):
            p = schema.draft_dir(range_dir, doc) / f"{doc}.{suffix}.md"
            if p.is_file():
                out.append({
                    "doc": doc,
                    "path": schema.display_path(p, Path.cwd()),
                    "status": status,
                    "bytes": p.stat().st_size,
                })
    # Reports the chunked build writes beside its notes and drafts (spec 033).
    state_drafts = schema.draft_dir(range_dir, "world_state")
    reports = [
        ("drops", freshness.notes_dir(range_dir) / "drops.md"),
        ("npc_status_report", state_drafts / "npc_status_report.md"),
        ("key_npcs_report", state_drafts / "key_npcs_report.md"),
        ("annotations", state_drafts / annotate.REPORT_FILE),
        ("canon_events_timeline", state_drafts / schema.TIMELINE_FILE),
        ("budget_report", state_drafts / schema.budget_report_file("world_state")),
        ("audit", freshness.audit_dir(range_dir) / "audit.md"),
        # party and planning (spec 034)
        ("party_report", state_drafts / "party_report.md"),
        ("planning_npcs_report", state_drafts / "planning_npcs_report.md"),
        ("threads_report", state_drafts / "threads_report.md"),
        ("campaign_threads_report", state_drafts / schema.CAMPAIGN_THREADS_REPORT_FILE),
        ("arc_report", state_drafts / "arc_report.md"),
        ("budget_report_party", state_drafts / schema.budget_report_file("party")),
        ("budget_report_planning", state_drafts / schema.budget_report_file("planning")),
    ]
    reports += [(f"reference/{p.stem}", p) for p in sorted((state_drafts / "reference").glob("*.md"))]
    for name, p in reports:
        if p.is_file():
            out.append({"doc": name, "path": schema.display_path(p, Path.cwd()), "status": "report", "bytes": p.stat().st_size})
    return out


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _extract_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The checked notes' state, read from ``state/notes/`` only: no model, no CLI, no summary parsing."""
    root = Path.cwd()
    range_dir = _range_dir(run, lo, hi)
    mp = freshness.notes_dir(range_dir) / freshness.NOTES_MANIFEST
    m = _read_json(mp)
    block: dict = {"present": False, "complete": False, "stale": False, "stale_reason": None,
                   "chunks": [], "totals": {"chunks": 0, "checked": 0, "kept": 0, "dropped": 0},
                   "outliers": [], "drops_file": None}
    if not (isinstance(m, dict) and m.get("kind") == "state_notes"):
        return block
    chunks = [c for c in m.get("chunks", []) if isinstance(c, dict)]
    outliers = notes.outliers_of([(c["chapters"], int(c.get("dropped", 0))) for c in chunks])
    block.update({
        "present": True,
        "complete": bool(m.get("complete")),
        "backend": m.get("backend"),
        "model": m.get("model"),
        "chunk_chars": m.get("chunk_chars"),
        "absent_chapters": m.get("absent_chapters", []),
        "chunks": [
            {"index": c["index"], "chapters": c["chapters"], "status": c.get("status"),
             "kept": int(c.get("kept", 0)), "dropped": int(c.get("dropped", 0)),
             "outlier": c["chapters"] in outliers}
            for c in chunks
        ],
        "totals": {
            "chunks": len(chunks),
            "checked": sum(1 for c in chunks if c.get("status") == "checked"),
            "kept": sum(int(c.get("kept", 0)) for c in chunks),
            "dropped": sum(int(c.get("dropped", 0)) for c in chunks),
        },
        "outliers": outliers,
    })
    drops = freshness.notes_dir(range_dir) / "drops.md"
    if drops.is_file():
        block["drops_file"] = schema.display_path(drops, root)
    # Freshness is the CLI's own check (corpus manifest, registry, players.yaml).
    try:
        registry = resolve.resolve_registry_path(root, None, run.model_dump(mode="json"))
    except resolve.PathRefusal as e:
        block.update(stale=True, stale_reason=str(e))
        return block
    players = _service(request).config_path_base / PLAYERS_CONFIG_FILENAME
    reason = freshness.check_notes_fresh(range_dir, registry, players)
    block.update(stale=reason is not None, stale_reason=reason)
    return block


def _audit_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The tracking audit's state, read from ``state/audit/`` only: counts from ``audit.json``, and
    freshness from the CLI's own check against the track files the audit was run with."""
    root = Path.cwd()
    range_dir = _range_dir(run, lo, hi)
    defaults = _default_track_files(request)
    block: dict = {"present": False, "complete": False, "stale": False, "stale_reason": None,
                   "counts": None, "audit_file": None, "track_files": defaults}
    if not freshness.audit_exists(range_dir):
        return block
    ad = freshness.audit_dir(range_dir)
    data = _read_json(ad / "audit.json")
    items = _read_json(ad / "items.json")
    if not (isinstance(data, dict) and data.get("kind") == "audit"):
        return block
    counts = data.get("counts") or audit_select.counts_of(data.get("verdicts") or [])
    block.update({
        "present": True,
        "complete": not counts.get("not_judged"),
        "counts": counts,
        "summary": audit_select.summary_line(counts),
        "backend": items.get("backend") if isinstance(items, dict) else None,
        "model": items.get("model") if isinstance(items, dict) else None,
        "candidates": items.get("candidates") if isinstance(items, dict) else None,
        "audit_file": schema.display_path(ad / "audit.md", root) if (ad / "audit.md").is_file() else None,
        # the files the audit was run with (names), which campaign_state's freshness check compares
        "track_files_run": [n for n, _ in (items.get("track_files_sha256") or [])] if isinstance(items, dict) else [],
    })
    # Stale against the configured track files, the same comparison `synth campaign_state` makes.
    reason = freshness.check_audit_fresh(range_dir, [root / t for t in defaults])
    block.update(stale=reason is not None, stale_reason=reason)
    return block


def _threads_block(request: Request, run: SummaryNativeRun, lo: int, hi: int) -> dict:
    """The ratified-thread counts of the last build that read the thread registry (planning or campaign_state), from
    ``state/threads/attach.json`` and the proposals file only: no model, no CLI, no summary parsing. ``present`` is false
    before such a build."""
    range_dir = _range_dir(run, lo, hi)
    block: dict = {"present": False, "ratified_in_range": None, "open": None, "dormant": None,
                   "unattached": None, "ambiguous": None, "pending_groups": None}
    data = _read_json(thread_attach.threads_dir(range_dir) / thread_attach.ATTACH_FILE)
    if isinstance(data, dict) and data.get("kind") == "thread_attach":
        threads = data.get("threads") or {}
        counts = data.get("counts") or {}
        block.update(
            present=True,
            ratified_in_range=len(threads),
            open=sum(1 for t in threads.values() if t.get("open")),
            dormant=sum(1 for t in threads.values() if t.get("dormant")),
            unattached=int(counts.get("unattached", 0)),
            ambiguous=len(data.get("ambiguous") or {}),
        )
    # Group proposals the GM has not ruled on yet (the file is not range-scoped, as the Threads page shows it).
    try:
        stores = load_projection_config(_service(request).config_path_base / PROJECTION_CONFIG_FILENAME).stores
        proposals = (_read_yaml(schema.resolve_under(Path.cwd(), stores.thread_proposals)) or {}).get("proposals") or []
        block["pending_groups"] = sum(
            1 for p in proposals if isinstance(p, dict) and p.get("key") and p.get("status", "pending") == "pending")
    except (ValueError, OSError, AttributeError, TypeError):
        pass
    return block


def _read_yaml(path: Path):
    """A YAML file as data, or ``None`` when it is absent."""
    import yaml

    if not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@router.get("/state")
def get_state(request: Request, since: int | None = None, until: int | None = None):
    """What is on disk for the range, per step (read-only; files only)."""
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    range_dir = _range_dir(run, lo, hi)
    drafts = schema.draft_dir(range_dir, "world_state")
    budgets = {doc: _read_json(drafts / schema.budget_report_file(doc)) for doc in schema.BUDGET_DOCS}
    missing = _read_json(range_dir / schema.STATE_DIR / schema.missing_dossiers_file("world_state"))
    planning_missing = _read_json(range_dir / schema.STATE_DIR / schema.missing_dossiers_file("planning"))
    return {
        "range": f"{lo}-{hi}",
        "extract": _extract_block(request, run, lo, hi),
        "audit": _audit_block(request, run, lo, hi),
        # {doc: {section: {budget, words, over}} | null}: each document's last build, null before one
        "budgets": {doc: b if isinstance(b, dict) else None for doc, b in budgets.items()},
        # {doc: {later, since, unverified, removed, lines}} from each document's last annotate step
        "annotations": annotate.read_counts(drafts),
        # [{name, state}]: the selected NPCs the latest world_state build found without a usable dossier
        # ([] when none, null before any build); `missing_dossiers_refused` says whether that build stopped
        "missing_dossiers": missing.get("npcs") if isinstance(missing, dict) else None,
        "missing_dossiers_refused": bool(missing.get("refused")) if isinstance(missing, dict) else False,
        # the same for planning's NPC Dossiers (its own file: one document's refusal is not the other's)
        "planning_missing_dossiers": planning_missing.get("npcs") if isinstance(planning_missing, dict) else None,
        "planning_missing_dossiers_refused": bool(planning_missing.get("refused")) if isinstance(planning_missing, dict) else False,
        # {present, ratified_in_range, open, dormant, unattached, ambiguous, pending_groups} from the last build that read the thread registry
        "threads": _threads_block(request, run, lo, hi),
    }


# ── Runs (SSE) ──────────────────────────────────────────────────────────────

@router.get("/run/validate")
async def run_validate(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dup_threshold: float | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("validate", None, directory, lo, hi)
    cmd += ["--dup-threshold", str(_pick_num(dup_threshold, run.dup_threshold))]
    return _sse_response(cmd)


@router.get("/run/build")
async def run_build(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dup_threshold: float | None = None,
    force: bool = False,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("build", None, directory, lo, hi)
    cmd += ["--dup-threshold", str(_pick_num(dup_threshold, run.dup_threshold))]
    if force:
        cmd.append("--force")
    return _sse_response(cmd)


@router.get("/run/synth/{doc}")
async def run_synth(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    party_config: str = "",
    planning_config: str = "",
    audit: list[str] | None = Query(default=None),
    name: list[str] | None = Query(default=None),
    recent_chapters: int | None = None,
    recurring_min: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    claude_code_effort: str | None = None,
    fallback_npc_lines: bool = False,
    authority_selection: list[str] | None = Query(default=None),
    audience: str | None = None,
):
    _require_doc(doc)
    # The retired parameters are not declared (FastAPI would ignore an undeclared one), so a request carrying
    # any of them is refused here, with the CLI's words naming the replacement (spec 034 FR-024).
    for retired, refusal in schema.RETIRED_SYNTH_FLAGS.items():
        if retired in request.query_params:
            raise HTTPException(status_code=400, detail=refusal)
    run = _run_config(request)
    if fallback_npc_lines and doc not in ("world_state", "planning"):
        raise HTTPException(
            status_code=400, detail=f"--fallback-npc-lines {schema.FALLBACK_NPC_LINES_REFUSAL}, not {doc}")
    if doc == "party":
        # party selects no NPCs, so the flags that choose them are refused here with the CLI's words
        # (a party run carries neither a stored nor a schema-default value of them either).
        for flag, given in (
            ("--name", any(n.strip() for n in (name or []))),
            ("--recent-chapters", recent_chapters is not None),
            ("--recurring-min", recurring_min is not None),
        ):
            if given:
                raise HTTPException(
                    status_code=400, detail=f"{flag} does not apply to party: {schema.PARTY_SELECTION_REFUSAL}")
    # Every document is built one call per section from the checked notes; the CLI refuses these flags and
    # so does the route, with the CLI's words.
    if any(a.strip() for a in (audit or [])):
        raise HTTPException(
            status_code=400,
            detail=schema.STATE_AUDIT_REFUSAL if doc == "campaign_state"
            else f"--audit applies to campaign_state only, not {doc}",
        )
    if doc == "campaign_state" and any(n.strip() for n in (name or [])):
        raise HTTPException(
            status_code=400, detail="--name does not apply to campaign_state: it has no Key NPCs section")
    selections = [selection.strip() for selection in (authority_selection or []) if selection.strip()]
    if doc != "planning" and (selections or (audience or "").strip()):
        raise HTTPException(status_code=400, detail="authority_selection and audience apply to planning only")
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("synth", doc, directory, lo, hi)

    # --party-config / --planning-config default to <config>/party.yaml and
    # <config>/planning.yaml inside the CLI; passed only when the request names one.
    if party_config.strip():
        cmd += ["--party-config", party_config.strip()]
    if planning_config.strip():
        cmd += ["--planning-config", planning_config.strip()]
    if selections:
        for selection in selections:
            cmd += ["--authority-selection", selection]
    if audience and audience.strip():
        cmd += ["--audience", audience.strip()]
    # --audit defaults to campaign_state.track_files inside the CLI; the route
    # passes it only when the request names files.
    files = [a.strip() for a in (audit or []) if a.strip()]
    if files:
        cmd += ["--audit", *files]
    subjects = [n.strip() for n in (name or []) if n.strip()]
    if subjects:
        cmd += ["--name", *subjects]

    # campaign_state has no Key NPCs section and party selects no NPCs, so the CLI refuses the selection flags for them
    if doc not in ("campaign_state", "party"):
        cmd += ["--recent-chapters", str(_pick_num(recent_chapters, run.recent_chapters))]
        cmd += ["--recurring-min", str(_pick_num(recurring_min, run.recurring_min))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    if fallback_npc_lines:  # per run, never from config
        cmd.append("--fallback-npc-lines")

    # The prose step has its own backend/model block (grounding.yaml summary_native.prose).
    cmd += selection_cli_args(resolve_selection(
        request, request_model=model, service=run.prose, service_name=f"{_SERVICE_NAME}.prose",
        request_claude_code_effort=(claude_code_effort or "").strip() or None,
    ))
    return _sse_response(cmd)


@router.get("/run/extract")
async def run_extract(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    chunk_chars: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    endpoints: list[str] | None = Query(default=None),
    parallel: int | None = None,
    resume: str | None = None,
):
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    urls = [e.strip() for e in (endpoints or []) if e.strip()]
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail=f"parallel must be at least 1, got {parallel}")
    if resume is not None and (force or dump_only):
        raise HTTPException(status_code=400, detail="--resume cannot be combined with --force or --dump-only")
    cmd = _base_cmd("extract", None, directory, lo, hi)
    cmd += ["--chunk-chars", str(_pick_num(chunk_chars, run.extract.chunk_chars))]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    # Endpoints are machine wiring, never stored in grounding.yaml: a request value rides on top of
    # the stored backend/model and reaches the command as `--endpoints A B` (the CLI's own spelling).
    service = run.extract
    if urls:
        service = SimpleNamespace(backend=run.extract.backend, model=run.extract.model, endpoints=tuple(urls))
    resolved = resolve_selection(
        request, request_model=model, service=service, service_name=f"{_SERVICE_NAME}.extract",
    )
    if urls and resolved.backend not in _ENDPOINT_BACKENDS:
        raise HTTPException(status_code=400, detail=f"--endpoints applies to --backend dgx only, not {resolved.backend}")
    cmd += selection_cli_args(resolved)
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    if resume is not None:
        cmd += ["--resume", resume] if resume else ["--resume"]
    return _sse_response(cmd)


@router.get("/run/audit")
async def run_audit(
    request: Request,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    track_file: list[str] | None = Query(default=None),
    candidates: int | None = None,
    max_tokens: int | None = None,
    dump_only: bool = False,
    force: bool = False,
    model: str | None = None,
    endpoints: list[str] | None = Query(default=None),
    parallel: int | None = None,
    resume: str | None = None,
):
    """The tracking audit. Its judge uses the extraction backend family (``summary_native.extract``) and
    the same endpoint wiring as ``/run/extract``; ``track_file`` repeats ``--track-file`` and, when
    absent, the CLI reads ``grounding.yaml campaign_state.track_files`` itself."""
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    urls = [e.strip() for e in (endpoints or []) if e.strip()]
    files = [t.strip() for t in (track_file or []) if t.strip()]
    if parallel is not None and parallel < 1:
        raise HTTPException(status_code=400, detail=f"parallel must be at least 1, got {parallel}")
    if resume is not None and (force or dump_only):
        raise HTTPException(status_code=400, detail="--resume cannot be combined with --force or --dump-only")
    if candidates is not None and candidates < 1:
        raise HTTPException(status_code=400, detail=f"candidates must be at least 1, got {candidates}")
    if not files and not _default_track_files(request):
        raise HTTPException(
            status_code=400,
            detail="no track files: pass ?track_file= or set grounding.yaml campaign_state.track_files",
        )
    cmd = _base_cmd("audit", None, directory, lo, hi)
    for f in files:
        cmd += ["--track-file", f]
    if candidates is not None:
        cmd += ["--candidates", str(candidates)]
    if max_tokens is not None:
        cmd += ["--max-tokens", str(max_tokens)]
    if dump_only:
        cmd.append("--dump-only")
    if force:
        cmd.append("--force")
    service = run.extract
    if urls:
        service = SimpleNamespace(backend=run.extract.backend, model=run.extract.model, endpoints=tuple(urls))
    resolved = resolve_selection(
        request, request_model=model, service=service, service_name=f"{_SERVICE_NAME}.extract",
    )
    if urls and resolved.backend not in _ENDPOINT_BACKENDS:
        raise HTTPException(status_code=400, detail=f"--endpoints applies to --backend dgx only, not {resolved.backend}")
    cmd += selection_cli_args(resolved)
    if parallel is not None:
        cmd += ["--parallel", str(parallel)]
    if resume is not None:
        cmd += ["--resume", resume] if resume else ["--resume"]
    return _sse_response(cmd)


@router.get("/status/{operation}")
def get_scheduler_status(request: Request, operation: str, since: int | None = None, until: int | None = None):
    """Project the latest extract/audit journal from disk without scheduler policy."""
    if operation not in {"extract", "audit"}:
        raise HTTPException(status_code=400, detail="operation must be extract or audit")
    run = _run_config(request)
    lo, hi = _require_range(run, since, until)
    range_dir = _range_dir(run, lo, hi)
    runs = (freshness.audience_state_dir(range_dir) / "runs" if operation == "extract"
            else Path(range_dir) / schema.STATE_DIR / "runs")
    return project_latest(runs, operation)


def _default_track_files(request: Request) -> list[str]:
    """``grounding.yaml campaign_state.track_files``: the audit's default."""
    return list(_service(request).resolved().campaign_state.track_files)


@router.get("/run/annotate/{doc}")
async def run_annotate(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
    dry_run: bool = False,
):
    _require_doc(doc)
    if doc not in schema.STATE_DOCS:
        raise HTTPException(
            status_code=400,
            detail=f"annotate applies to {' and '.join(schema.STATE_DOCS)} only, not {doc}",
        )
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("annotate", doc, directory, lo, hi)
    if dry_run:
        cmd.append("--dry-run")
    return _sse_response(cmd)


@router.get("/run/compare/{doc}")
async def run_compare(
    request: Request,
    doc: str,
    summaries_dir: str = "",
    since: int | None = None,
    until: int | None = None,
):
    _require_doc(doc)
    run = _run_config(request)
    directory = _require_dir(run, summaries_dir)
    lo, hi = _require_range(run, since, until)
    cmd = _base_cmd("compare", doc, directory, lo, hi)
    cmd += ["--live", f"docs/{doc}.md"]
    return _sse_response(cmd)
