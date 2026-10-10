"""Trusted local adapters for the campaign review CLI.

The dedicated capability server only reads prepared review data and records
decisions.  This router is the local administrative surface: every operation
is translated to one fixed CLI argv and executed through the bounded JSON
runner without a run log.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from campaignlib.review_config import ReviewConfig, load_campaign_review_config
from server.platform_config_service import require_platform
from server.subprocess_runner import BoundedJSONError, console_script, run_bounded_json, stream_subprocess


router = APIRouter()


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyRequest(StrictRequest):
    pass


class CreateRequest(StrictRequest):
    kind: Literal["npc_verification", "duplicate_identity", "grounding_documents"]
    selection: str = Field(min_length=1)


class DecisionMemberRequest(StrictRequest):
    item_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    item_revision: int = Field(ge=1)
    review_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_decision_revision: int = Field(ge=0)
    verdict: Literal["approve", "reject", "discuss"]
    disposition: Literal[
        "accept_no_change",
        "source_correction",
        "merge",
        "distinct",
        "reject_action",
        "defer",
        "document_signoff",
    ]
    note: str = ""
    proposal_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    proposal_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def proposal_pair(self):
        if (self.proposal_id is None) != (self.proposal_digest is None):
            raise ValueError("proposal_id and proposal_digest are required together")
        return self


class DecideRequest(StrictRequest):
    version: Literal[1] = 1
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    review_generation: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=256)
    decisions: list[DecisionMemberRequest] = Field(min_length=1)


class RetractRequest(StrictRequest):
    event: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    expected_decision_revision: int = Field(ge=1)
    reason: str = Field(min_length=1)


class FileSelectionRequest(StrictRequest):
    selection: str = Field(min_length=1)


class ImportRequest(StrictRequest):
    bundle: str = Field(min_length=1)
    expected_generation: int = Field(ge=1)


class MigrationRequest(StrictRequest):
    dry_run: bool = False
    plan_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exactly_one_mode(self):
        if self.dry_run == (self.plan_sha256 is not None):
            raise ValueError("choose dry_run or plan_sha256")
        return self


class RecoverRequest(StrictRequest):
    transaction: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")


class EndpointRequest(StrictRequest):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    origin: str = Field(min_length=1, max_length=2048)
    tls_cert: str | None = None
    tls_key: str | None = None

    @model_validator(mode="after")
    def tls_pair(self):
        if (self.tls_cert is None) != (self.tls_key is None):
            raise ValueError("tls_cert and tls_key are required together")
        return self


class GrantIssueRequest(StrictRequest):
    expires_in: int | None = Field(default=None, ge=60, le=31 * 86_400)


class GrantRevokeRequest(StrictRequest):
    grant: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")

class RefreshRequest(StrictRequest): expected_generation:int=Field(ge=1)
class RerunPreviewRequest(StrictRequest): selection:str=Field(min_length=1); mode:Literal["unresolved","selected"]
class RerunRunRequest(StrictRequest): selection_sha256:str=Field(pattern=r"^[0-9a-f]{64}$")
class CorrectionPrepareRequest(StrictRequest):
    item:str=Field(min_length=1); target_kind:Literal["source","draft"]; replacement:str=Field(min_length=1); expected_decision_revision:int=Field(ge=0); summaries_dir:str|None=None
class ProposalApplyRequest(StrictRequest): proposal:str=Field(min_length=1); proposal_sha256:str=Field(pattern=r"^[0-9a-f]{64}$"); summaries_dir:str|None=None
class IdentityRegenerateRequest(StrictRequest): receipt:str=Field(min_length=1); selection:str=Field(min_length=1); execute:bool=False
class GuardPrepareRequest(StrictRequest): proposal:str=Field(min_length=1); reviewer:str=Field(min_length=1); note:str=Field(min_length=1)
class GuardApplyRequest(StrictRequest): resolution:str=Field(min_length=1); resolution_sha256:str=Field(pattern=r"^[0-9a-f]{64}$")
class DocumentSignRequest(StrictRequest): item:str=Field(min_length=1); document_sha256:str=Field(pattern=r"^[0-9a-f]{64}$"); expected_decision_revision:int=Field(ge=0); reviewer:str=Field(min_length=1)
class NpcSignRequest(StrictRequest): item:str=Field(min_length=1); draft_sha256:str=Field(pattern=r"^[0-9a-f]{64}$"); expected_decision_revision:int=Field(ge=0); reviewer:str=Field(min_length=1)
class IdentityPrepareRequest(StrictRequest):
    item:str=Field(min_length=1); expected_decision_revision:int=Field(ge=0); scope_kind:Literal["global","chapter","scene","location","document","evidence"]; scope_value:str|None=None
    @model_validator(mode="after")
    def scope_pair(self):
        if (self.scope_kind=="global") != (self.scope_value is None): raise ValueError("scope_value is required exactly for local scope")
        return self


def _root(request: Request) -> Path:
    return Path(require_platform(request).campaign_dir).resolve()


def _contained_file(root: Path, value: str, field: str) -> str:
    raw = Path(value).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field} must stay inside the active campaign") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"{field} does not exist")
    return str(candidate)


def _command(root: Path, *arguments: str) -> list[str]:
    return [
        console_script("summary_native"),
        "review",
        *arguments,
        "--campaign-dir",
        str(root),
        "--json",
    ]


def _config(root: Path) -> ReviewConfig:
    return load_campaign_review_config(root)


def _error(exc: BoundedJSONError) -> JSONResponse:
    payload = exc.payload if isinstance(exc.payload, dict) else None
    supplied = payload.get("code") if payload else None
    known: dict[str, tuple[int, str]] = {
        "REVIEW_STALE_DECISION": (409, "Review state changed. Reload before trying again."),
        "REVIEW_STALE_GENERATION": (409, "Review state changed. Reload before trying again."),
        "REVIEW_STALE_CUSTODY": (409, "Review state changed. Reload before trying again."),
        "REVIEW_REQUEST_ID_CONFLICT": (409, "Review state changed. Reload before trying again."),
        "REVIEW_RECOVERY_REQUIRED": (423, "Review recovery is required before this operation."),
        "REVIEW_PENDING_TRANSACTION": (423, "Review recovery is required before this operation."),
        "REVIEW_PAGE_INVALID": (400, "Review page request is invalid."),
        "REVIEW_INVALID_BATCH": (400, "Decision request is invalid."),
        "REVIEW_UNKNOWN_ITEM": (404, "Review item was not found."),
        "REVIEW_UNKNOWN_REVIEW": (404, "Review was not found."),
    }
    if isinstance(supplied, str) and supplied in known:
        code = supplied
        status, message = known[code]
    else:
        code = "REVIEW_COMMAND_FAILED"
        status = 503
        message = "Review command failed safely."
    return JSONResponse({"ok": False, "code": code, "message": message}, status_code=status)


async def _run(root: Path, *arguments: str, stdin: bytes | None = None):
    config = _config(root)
    try:
        return await run_bounded_json(
            _command(root, *arguments),
            cwd=str(root),
            stdin_bytes=stdin,
            timeout_seconds=config.command_timeout_seconds,
            max_output_bytes=config.max_response_bytes,
            save_run_log=False,
        )
    except BoundedJSONError as exc:
        return _error(exc)


@router.post("/init")
async def initialize(request: Request, _payload: EmptyRequest):
    return await _run(_root(request), "init")


@router.post("/migrate")
async def migrate(request: Request, payload: MigrationRequest):
    arguments = ["migrate", "--dry-run"] if payload.dry_run else [
        "migrate", "--plan-sha256", str(payload.plan_sha256)
    ]
    return await _run(_root(request), *arguments)

@router.post("/dependencies/migrate")
async def dependency_migrate(request:Request,payload:MigrationRequest):
    arguments=["dependencies","migrate","--dry-run"] if payload.dry_run else ["dependencies","migrate","--plan-sha256",str(payload.plan_sha256)]
    return await _run(_root(request),*arguments)


@router.post("/recover")
async def recover(request: Request, payload: RecoverRequest):
    return await _run(_root(request), "recover", payload.transaction)


@router.post("/create")
async def create(request: Request, payload: CreateRequest):
    root = _root(request)
    selection = _contained_file(root, payload.selection, "selection")
    return await _run(root, "create", "--kind", payload.kind, "--selection", selection)


@router.get("")
async def listing(request: Request):
    return await _run(_root(request), "list")


@router.get("/{review_id}")
async def show(
    request: Request,
    review_id: str,
    item: str | None = None,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1),
):
    root = _root(request)
    if limit is not None and limit > _config(root).max_page_items:
        raise HTTPException(status_code=400, detail="limit exceeds the configured review page size")
    arguments = ["show", review_id]
    if item is not None:
        arguments += ["--item", item]
    if cursor is not None:
        arguments += ["--cursor", cursor]
    if limit is not None:
        arguments += ["--limit", str(limit)]
    return await _run(root, *arguments)


@router.get("/{review_id}/status")
async def status(request: Request, review_id: str):
    return await _run(_root(request), "status", review_id)


@router.post("/{review_id}/decisions")
async def decide(request: Request, review_id: str, payload: DecideRequest):
    root = _root(request)
    config = _config(root)
    if len(payload.decisions) > config.max_batch_decisions:
        raise HTTPException(status_code=400, detail="decision batch exceeds the configured limit")
    for decision in payload.decisions:
        if len(decision.note) > config.max_note_chars:
            raise HTTPException(status_code=400, detail="decision note exceeds the configured limit")
    encoded = json.dumps(
        payload.model_dump(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > config.max_request_bytes:
        raise HTTPException(status_code=413, detail="decision request exceeds the configured limit")
    return await _run(root, "decide", review_id, "--decisions", "-", stdin=encoded)


@router.get("/{review_id}/history")
async def decision_history(request: Request, review_id: str, item: str | None = None):
    arguments = ["history", review_id]
    if item is not None:
        arguments += ["--item", item]
    return await _run(_root(request), *arguments)


@router.post("/{review_id}/retract")
async def retract(request: Request, review_id: str, payload: RetractRequest):
    root = _root(request)
    if len(payload.reason) > _config(root).max_note_chars:
        raise HTTPException(status_code=400, detail="retraction reason exceeds the configured limit")
    return await _run(
        root,
        "retract", review_id,
        "--event", payload.event,
        "--expected-decision-revision", str(payload.expected_decision_revision),
        "--reason", payload.reason,
    )

@router.post("/{review_id}/refresh")
async def refresh(request:Request,review_id:str,payload:RefreshRequest):
    return await _run(_root(request),"refresh",review_id,"--expected-generation",str(payload.expected_generation))

@router.post("/{review_id}/findings")
async def finding_add(request:Request,review_id:str,payload:FileSelectionRequest,expected_generation:int=Query(ge=1)):
    root=_root(request); finding=_contained_file(root,payload.selection,"finding")
    return await _run(root,"finding","add",review_id,"--finding",finding,"--expected-generation",str(expected_generation))

@router.post("/{review_id}/rerun/preview")
async def rerun_preview(request:Request,review_id:str,payload:RerunPreviewRequest):
    root=_root(request); selection=_contained_file(root,payload.selection,"selection")
    return await _run(root,"rerun","preview",review_id,"--selection",selection,"--mode",payload.mode)

@router.post("/{review_id}/rerun/run")
async def rerun_run(request:Request,review_id:str,payload:RerunRunRequest):
    return await _run(_root(request),"rerun","run",review_id,"--selection-sha256",payload.selection_sha256)

@router.post("/{review_id}/correction/prepare")
async def correction_prepare(request:Request,review_id:str,payload:CorrectionPrepareRequest):
    arguments=["correction","prepare",review_id,"--item",payload.item,"--target-kind",payload.target_kind,"--replacement",payload.replacement,"--expected-decision-revision",str(payload.expected_decision_revision)]
    if payload.summaries_dir: arguments += ["--summaries-dir",payload.summaries_dir]
    return await _run(_root(request),*arguments)

@router.post("/{review_id}/correction/apply")
async def correction_apply(request:Request,review_id:str,payload:ProposalApplyRequest):
    arguments=["correction","apply",review_id,"--proposal",payload.proposal,"--proposal-sha256",payload.proposal_sha256]
    if payload.summaries_dir: arguments += ["--summaries-dir",payload.summaries_dir]
    return await _run(_root(request),*arguments)

@router.post("/{review_id}/document/sign")
async def document_sign(request:Request,review_id:str,payload:DocumentSignRequest):
    return await _run(_root(request),"document","sign",review_id,"--item",payload.item,"--document-sha256",payload.document_sha256,"--expected-decision-revision",str(payload.expected_decision_revision),"--reviewer",payload.reviewer)

@router.post("/{review_id}/npc/sign")
async def npc_sign(request:Request,review_id:str,payload:NpcSignRequest):
    return await _run(_root(request),"npc","sign",review_id,"--item",payload.item,"--draft-sha256",payload.draft_sha256,"--expected-decision-revision",str(payload.expected_decision_revision),"--reviewer",payload.reviewer)

@router.post("/{review_id}/document/prepare")
async def document_prepare(request:Request,review_id:str,payload:FileSelectionRequest):
    root=_root(request); value=_contained_file(root,payload.selection,"documents")
    return await _run(root,"document","prepare",review_id,"--documents",value)

@router.post("/{review_id}/document/promote")
async def document_promote(request:Request,review_id:str,payload:FileSelectionRequest):
    root=_root(request); value=_contained_file(root,payload.selection,"proposals")
    return await _run(root,"document","promote",review_id,"--proposals",value)

@router.post("/{review_id}/identity/prepare")
async def identity_prepare(request:Request,review_id:str,payload:IdentityPrepareRequest):
    arguments=["identity","prepare",review_id,"--item",payload.item,"--expected-decision-revision",str(payload.expected_decision_revision),"--scope-kind",payload.scope_kind]
    if payload.scope_value is not None: arguments += ["--scope-value",payload.scope_value]
    return await _run(_root(request),*arguments)

@router.get("/{review_id}/identity/{proposal_id}")
async def identity_detail(request:Request,review_id:str,proposal_id:str):
    return await _run(_root(request),"identity","detail",review_id,"--proposal",proposal_id)

@router.post("/{review_id}/identity/apply")
async def identity_apply(request:Request,review_id:str,payload:ProposalApplyRequest):
    return await _run(_root(request),"identity","apply",review_id,"--proposal",payload.proposal,"--proposal-sha256",payload.proposal_sha256)

@router.get("/{review_id}/identity/{proposal_id}/resolution")
async def identity_resolution(request:Request,review_id:str,proposal_id:str):
    return await _run(_root(request),"identity","resolution",review_id,"--proposal",proposal_id)

@router.post("/{review_id}/identity/regenerate")
async def identity_regenerate(request:Request,review_id:str,payload:IdentityRegenerateRequest):
    root=_root(request); selection=_contained_file(root,payload.selection,"regeneration selection")
    arguments=["identity","regenerate",review_id,"--receipt",payload.receipt,"--selection",selection]
    if not payload.execute:
        return await _run(root,*arguments)
    arguments.append("--execute")
    return StreamingResponse(
        stream_subprocess(_command(root,*arguments),cwd=str(root)),
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"},
    )

@router.post("/{review_id}/identity/guard/prepare")
async def identity_guard_prepare(request:Request,review_id:str,payload:GuardPrepareRequest):
    return await _run(_root(request),"identity","guard-prepare",review_id,"--proposal",payload.proposal,"--reviewer",payload.reviewer,"--note",payload.note)

@router.post("/{review_id}/identity/guard/apply")
async def identity_guard_apply(request:Request,review_id:str,payload:GuardApplyRequest):
    return await _run(_root(request),"identity","guard-apply",review_id,"--resolution",payload.resolution,"--resolution-sha256",payload.resolution_sha256)


@router.post("/{review_id}/export")
async def export(request: Request, review_id: str, payload: FileSelectionRequest):
    root = _root(request)
    selection = _contained_file(root, payload.selection, "selection")
    return await _run(root, "export", review_id, "--selection", selection)


@router.post("/import")
async def import_bundle(request: Request, payload: ImportRequest):
    root = _root(request)
    bundle = _contained_file(root, payload.bundle, "bundle")
    return await _run(
        root, "import", "--bundle", bundle,
        "--expected-generation", str(payload.expected_generation),
    )


@router.post("/{review_id}/service/start")
async def service_start(request: Request, review_id: str, payload: EndpointRequest):
    arguments = [
        "service", "start", review_id,
        "--host", payload.host,
        "--port", str(payload.port),
        "--origin", payload.origin,
    ]
    if payload.tls_cert is not None and payload.tls_key is not None:
        root = _root(request)
        arguments += [
            "--tls-cert", _contained_file(root, payload.tls_cert, "tls_cert"),
            "--tls-key", _contained_file(root, payload.tls_key, "tls_key"),
        ]
    return await _run(_root(request), *arguments)


@router.get("/{review_id}/service/status")
async def service_status(request: Request, review_id: str):
    return await _run(_root(request), "service", "status", review_id)


@router.post("/{review_id}/service/stop")
async def service_stop(request: Request, review_id: str, _payload: EmptyRequest):
    return await _run(_root(request), "service", "stop", review_id)


@router.post("/{review_id}/access/issue")
async def access_issue(request: Request, review_id: str, payload: GrantIssueRequest):
    arguments = ["access", "issue", review_id]
    if payload.expires_in is not None:
        arguments += ["--expires-in", str(payload.expires_in)]
    return await _run(_root(request), *arguments)


@router.post("/{review_id}/access/revoke")
async def access_revoke(request: Request, review_id: str, payload: GrantRevokeRequest):
    return await _run(_root(request), "access", "revoke", review_id, "--grant", payload.grant)
