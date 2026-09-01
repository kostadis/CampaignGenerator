"""Thin typed HTTP adapter for the narration-wiki CLI process boundary."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from server.subprocess_runner import (
    BoundedJSONError,
    console_script,
    run_bounded_json,
    sse_error_stream,
    stream_subprocess,
)
from session_doc.narration_wiki.models import canonical_json, require_stable_id
from session_doc.narration_wiki.paths import campaign_identity


router = APIRouter()


class ScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str = Field(min_length=1, max_length=256)
    session_relative: str = Field(min_length=1, max_length=1024)
    iteration_id: str = Field(min_length=1, max_length=64)

    @field_validator("campaign_id", "session_relative", "iteration_id")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("scope values must be non-empty")
        return value

    @field_validator("iteration_id")
    @classmethod
    def stable_iteration(cls, value: str) -> str:
        return require_stable_id(value, "iteration-id")

    @field_validator("session_relative")
    @classmethod
    def relative_session(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
            raise ValueError("session_relative must be a proper contained relative path")
        return path.as_posix()


class MeasureRequest(ScopeRequest):
    phase: Literal["before", "after"]
    proposal_id: str | None = None

    @model_validator(mode="after")
    def phase_proposal(self) -> "MeasureRequest":
        if (self.phase == "after") != bool(self.proposal_id):
            raise ValueError("proposal_id is required only for after measurement")
        return self


class ConflictRuleRequest(ScopeRequest):
    conflict_id: str = Field(min_length=1, max_length=64)
    resolution: str = Field(min_length=1, max_length=20_000)
    rationale: str = Field(min_length=1, max_length=20_000)


class PatternRuleRequest(ScopeRequest):
    pattern_slug: str = Field(min_length=1, max_length=256)
    decision: Literal["accept", "reject"]
    tier: Literal["campaign", "portable"] | None = None
    named_portable_override: bool = False
    rationale: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def decision_options(self) -> "PatternRuleRequest":
        if self.decision == "accept" and self.tier is None:
            raise ValueError("accepted patterns require a tier")
        if self.decision == "reject" and self.tier is not None:
            raise ValueError("rejected patterns cannot carry a tier")
        if self.named_portable_override and (
            self.decision != "accept" or self.tier != "portable" or not str(self.rationale or "").strip()
        ):
            raise ValueError("named portable override requires accepted portable placement and rationale")
        return self


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=1, max_length=1024)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    applies_to_kind: Literal["rule", "measurement_category"]
    applies_to_key: str = Field(min_length=1, max_length=64)

    @field_validator("source_ref")
    @classmethod
    def relative_source(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or path in {PurePosixPath("."), PurePosixPath("..")} or ".." in path.parts:
            raise ValueError("source_ref must identify a relative collected artifact")
        return value


class ProposalStageRequest(ScopeRequest):
    proposal_id: str = Field(min_length=1, max_length=64)
    draft_relative: str = Field(min_length=1, max_length=1024)
    evidence_bindings: list[EvidenceBinding] = Field(default_factory=list, max_length=100)
    override_rationale: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def reconsideration(self) -> "ProposalStageRequest":
        if self.evidence_bindings and str(self.override_rationale or "").strip():
            raise ValueError("evidence bindings and override rationale are mutually exclusive")
        return self

    @field_validator("draft_relative")
    @classmethod
    def contained_draft(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("draft_relative must stay inside the selected iteration")
        return path.as_posix()


class ProposalRequest(ScopeRequest):
    proposal_id: str = Field(min_length=1, max_length=64)


class ProposalRuleRequest(ProposalRequest):
    decision: Literal["accept", "reject"]


def _campaign_root(request: Request, scope: ScopeRequest) -> Path:
    platform = getattr(request.app.state, "platform", None)
    root = getattr(platform, "campaign_dir", None)
    if root is None:
        raise ValueError("campaign configuration is unavailable")
    campaign = Path(root).resolve(strict=True)
    if scope.campaign_id != campaign_identity(campaign):
        raise PermissionError("unknown campaign identity")
    session = campaign / scope.session_relative
    try:
        resolved = session.resolve(strict=True)
        relative = resolved.relative_to(campaign)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PermissionError("selected session is missing or outside the campaign") from exc
    if relative == Path(".") or not resolved.is_dir():
        raise PermissionError("selected session must be a proper campaign descendant")
    return campaign


def _base_command(scope: ScopeRequest) -> list[str]:
    return [
        console_script("narration_wiki"),
        "--campaign-dir", ".",
        "--session-dir", scope.session_relative,
        "--iteration-id", scope.iteration_id,
        "--json",
    ]


def build_command(scope: ScopeRequest, command: str) -> list[str]:
    """Return a fixed argument vector; callers append only typed fields."""
    if command not in {
        "status", "collect", "measure", "index-check", "conflict-rule",
        "pattern-rule", "proposal-stage", "proposal-apply", "proposal-rule",
    }:
        raise ValueError("unsupported narration-wiki command")
    base = _base_command(scope)
    return [base[0], command, *base[1:]]


def _stream(request: Request, scope: ScopeRequest, command: list[str]) -> StreamingResponse:
    try:
        campaign = _campaign_root(request, scope)
    except (ValueError, PermissionError) as exc:
        code = 2 if isinstance(exc, ValueError) else 3
        return StreamingResponse(
            sse_error_stream(str(exc), returncode=code),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return StreamingResponse(
        stream_subprocess(command, cwd=str(campaign), save_run_log=False),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _error_response(exc: BoundedJSONError) -> JSONResponse:
    if exc.category in {"timeout", "output_limit"}:
        status, code = 504, exc.category
    elif exc.returncode == 2:
        status, code = 400, "invalid_request"
    elif exc.returncode == 3:
        status, code = 403, "scope_refusal"
    elif exc.returncode == 4:
        status, code = (404, "iteration_not_found") if "missing" in str(exc).casefold() else (409, "state_conflict")
    elif exc.returncode == 5:
        status, code = 422, "invalid_artifact"
    else:
        status, code = 500, "process_failure"
    return JSONResponse({"detail": str(exc), "code": code}, status_code=status)


@router.get("/status")
async def status(
    request: Request,
    campaign_id: Annotated[str, Query(min_length=1)],
    session_relative: Annotated[str, Query(min_length=1)],
    iteration_id: Annotated[str, Query(min_length=1)],
):
    scope = ScopeRequest(
        campaign_id=campaign_id,
        session_relative=session_relative,
        iteration_id=iteration_id,
    )
    try:
        campaign = _campaign_root(request, scope)
        return await run_bounded_json(
            build_command(scope, "status"),
            cwd=str(campaign),
            timeout_seconds=10,
            max_output_bytes=262_144,
            save_run_log=False,
        )
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc), "code": "scope_refusal"}, status_code=403)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc), "code": "invalid_request"}, status_code=400)
    except BoundedJSONError as exc:
        return _error_response(exc)


@router.post("/collect")
async def collect(request: Request, body: ScopeRequest):
    return _stream(request, body, build_command(body, "collect"))


@router.post("/measure")
async def measure(request: Request, body: MeasureRequest):
    command = build_command(body, "measure") + ["--phase", body.phase]
    if body.proposal_id:
        command += ["--proposal-id", body.proposal_id]
    return _stream(request, body, command)


@router.post("/index-check")
async def index_check(request: Request, body: ScopeRequest):
    return _stream(request, body, build_command(body, "index-check"))


@router.post("/conflict-rule")
async def conflict_rule(request: Request, body: ConflictRuleRequest):
    command = build_command(body, "conflict-rule") + [
        "--conflict-id", body.conflict_id,
        "--resolution", body.resolution,
        "--rationale", body.rationale,
    ]
    return _stream(request, body, command)


@router.post("/pattern-rule")
async def pattern_rule(request: Request, body: PatternRuleRequest):
    command = build_command(body, "pattern-rule") + [
        "--pattern-slug", body.pattern_slug,
        "--decision", body.decision,
    ]
    if body.tier:
        command += ["--tier", body.tier]
    if body.named_portable_override:
        command.append("--named-portable-override")
    if body.rationale:
        command += ["--rationale", body.rationale]
    return _stream(request, body, command)


@router.post("/proposal-stage")
async def proposal_stage(request: Request, body: ProposalStageRequest):
    command = build_command(body, "proposal-stage") + [
        "--proposal-id", body.proposal_id,
        "--draft", body.draft_relative,
    ]
    for binding in body.evidence_bindings:
        command += ["--evidence-binding-json", canonical_json(binding.model_dump(), compact=True)]
    if body.override_rationale:
        command += ["--override-rationale", body.override_rationale]
    return _stream(request, body, command)


@router.post("/proposal-apply")
async def proposal_apply(request: Request, body: ProposalRequest):
    command = build_command(body, "proposal-apply") + ["--proposal-id", body.proposal_id]
    return _stream(request, body, command)


@router.post("/proposal-rule")
async def proposal_rule(request: Request, body: ProposalRuleRequest):
    command = build_command(body, "proposal-rule") + [
        "--proposal-id", body.proposal_id,
        "--decision", body.decision,
    ]
    return _stream(request, body, command)
