"""``/api/summary-native/delta`` — thin routes over ``summary_native delta`` (feature 039).

Principle VI: this module builds argv from ``console_script("summary_native")`` and shells out through
``server/subprocess_runner.py``. It imports nothing from ``pipelines`` and holds no pipeline logic.
Principle XII: it declares no default for a backend, model or path; those resolve from the owning
config model (``server.grounding_config_shared.SummaryNativeRun`` through ``resolve_selection``)
at the route edge, and a route takes sentinels (``None``).

Every operation route calls ``build_delta_argv`` and then ``_run_json`` (bounded JSON, always
``--json``) or ``_stream`` (SSE, the CLI's human output). Every CLI verb has a face here (Principle XI).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from server.platform_config_service import resolve_selection, selection_cli_args
from server.routers.grounding import _service, _sse_response
from server.routers.summary_native import _authority_campaign_dir, per_run_service
from server.subprocess_runner import BoundedJSONError, console_script, run_bounded_json

router = APIRouter()

_SERVICE_NAME = "summary_native.delta"

#: Flag emission order. Deterministic argv is part of the contract (Principle XI).
_FLAG_ORDER: tuple[str, ...] = (
    "campaign_dir", "config", "plan", "product", "stop", "source", "member", "resolve",
    "decision", "reason", "publication", "preview_sha", "review", "claims_report", "request_id",
    "canonical", "reviewer", "backend", "model", "json", "force",
)
_BOOL_FLAGS = frozenset({"json", "force"})
_LIST_FLAGS = frozenset({"source", "product", "member", "resolve"})


def build_delta_argv(command: list[str], **flags: Any) -> list[str]:
    """``[console_script, "delta", *command, *flags]`` with flags in ``_FLAG_ORDER``.

    ``None`` and ``False`` flags are omitted; list flags repeat. An empty ``source`` list is kept out
    of argv so the CLI refuses with its own text (exit 2) rather than the router guessing a default.
    """
    unknown = set(flags) - set(_FLAG_ORDER)
    if unknown:
        raise ValueError(f"unknown delta flag(s): {', '.join(sorted(unknown))}")
    argv = [console_script("summary_native"), "delta", *command]
    for name in _FLAG_ORDER:
        value = flags.get(name)
        if value is None or value is False:
            continue
        flag = "--" + name.replace("_", "-")
        if name in _BOOL_FLAGS:
            argv.append(flag)
        elif name in _LIST_FLAGS:
            for item in value:
                argv += [flag, str(item)]
        else:
            argv += [flag, str(value)]
    return argv


def _status_for(returncode: int) -> int:
    """contracts/http.md: 3 stale -> 409, 4 partial -> 207, 5 recovery -> 409, 2 usage -> 400, 1 refusal -> 422."""
    return {1: 422, 2: 400, 3: 409, 4: 207, 5: 409}.get(returncode, 500)


async def _run_json(argv: list[str], *, cwd: str | None = None, timeout_seconds: float = 30.0):
    """Run one delta command and return its JSON object, mapping CLI exit codes to HTTP status."""
    try:
        return await run_bounded_json(argv, cwd=cwd, timeout_seconds=timeout_seconds)
    except BoundedJSONError as exc:
        body = dict(exc.payload) if isinstance(exc.payload, dict) else {}
        body.setdefault("message", str(exc))
        body["exit_code"] = exc.returncode
        return JSONResponse(status_code=_status_for(exc.returncode), content=body)


def _stream(argv: list[str]):
    """Stream a long stage as SSE (``event: line`` / ``event: exit``) via the shared helper."""
    return _sse_response(argv)


def _require_sources(sources: list[str] | None) -> list[str]:
    if not sources:
        raise HTTPException(
            status_code=400,
            detail="no sources selected; the delta does not default to all chapters.",
        )
    return list(sources)


def _resolve_models(request: Request, request_backend: str | None, request_model: str | None) -> list[str]:
    """``--backend``/``--model`` argv for a run, resolved from the owning config model; no literals here."""
    stored = _service(request).resolved().summary_native.prose
    service, backend = per_run_service(stored, request_backend)
    resolved = resolve_selection(
        request, request_model=request_model, request_backend=backend, service=service,
        service_name=_SERVICE_NAME,
    )
    return selection_cli_args(resolved)


# ── operation routes ───────────────────────────────────────────────────────

_JSON_TIMEOUT = 120.0


class _Body(BaseModel):
    """Superset of the request bodies; each route reads only the fields its CLI verb takes."""

    sources: list[str] | None = None
    product: list[str] | None = None
    stop: str | None = None
    backend: str | None = None
    model: str | None = None
    plan: str | None = None
    decision: str | None = None
    reason: str | None = None
    reviewer: str | None = None
    publication: str | None = None
    preview_sha: str | None = None
    members: list[str] | None = None
    resolve: list[str] | None = None
    review: str | None = None
    claims_report: str | None = None
    request_id: str | None = None
    canonical: str | None = None


def _root(request: Request) -> str:
    return str(_authority_campaign_dir(request))


def _model_args(request: Request, body: _Body | None) -> list[str]:
    return _resolve_models(request, body.backend if body else None, body.model if body else None)


async def _json(request: Request, command: list[str], *, models: _Body | None = None, use_models: bool = False,
                **flags: Any):
    root = _root(request)
    argv = build_delta_argv(command, campaign_dir=root, json=True, **flags)
    if use_models:
        argv += _model_args(request, models)
    return await _run_json(argv, cwd=root, timeout_seconds=_JSON_TIMEOUT)


def _sse(request: Request, command: list[str], *, models: _Body | None = None, use_models: bool = False,
         **flags: Any):
    argv = build_delta_argv(command, campaign_dir=_root(request), **flags)
    if use_models:
        argv += _model_args(request, models)
    return _stream(argv)


@router.post("/plans")
async def create_plan(request: Request, body: _Body):
    sources = _require_sources(body.sources)
    return await _json(request, ["plan"], models=body, use_models=True, source=sources,
                       product=body.product or None, stop=body.stop)


@router.post("/plans/{plan_id}/sources")
async def plan_sources(request: Request, plan_id: str):
    return await _json(request, ["sources"], plan=plan_id)


@router.get("/plans/{plan_id}/baseline")
async def baseline_status(request: Request, plan_id: str):
    return await _json(request, ["baseline", "status"], plan=plan_id)


@router.post("/plans/{plan_id}/baseline/adopt")
async def baseline_adopt(request: Request, plan_id: str, body: _Body | None = None):
    return await _json(request, ["baseline", "adopt"], plan=plan_id,
                       resolve=(body.resolve if body else None) or None)


@router.post("/plans/{plan_id}/census")
async def census(request: Request, plan_id: str):
    return _sse(request, ["census"], plan=plan_id)


@router.post("/plans/{plan_id}/associations/propose")
async def associations_propose(request: Request, plan_id: str, body: _Body | None = None):
    return _sse(request, ["associate", "propose"], models=body, use_models=True, plan=plan_id)


@router.post("/associations/{assoc_id}/decision")
async def associations_decide(request: Request, assoc_id: str, body: _Body):
    if not body.plan:
        raise HTTPException(status_code=400, detail="--plan ID is required: send `plan` with the decision.")
    return await _json(request, ["associate", "decide", assoc_id], plan=body.plan, decision=body.decision,
                       reason=body.reason, reviewer=body.reviewer)


@router.post("/plans/{plan_id}/npc/draft")
async def npc_draft(request: Request, plan_id: str, body: _Body | None = None):
    return _sse(request, ["npc", "draft"], models=body, use_models=True, plan=plan_id)


@router.post("/plans/{plan_id}/npc/verify")
async def npc_verify(request: Request, plan_id: str):
    return _sse(request, ["npc", "verify"], plan=plan_id)


@router.post("/plans/{plan_id}/npc/{subject}/attest")
async def npc_attest(request: Request, plan_id: str, subject: str, body: _Body):
    return await _json(request, ["npc", "attest", subject], plan=plan_id, reason=body.reason,
                       publication=body.publication)


@router.post("/plans/{plan_id}/npc/publish/preview")
async def npc_publish_preview(request: Request, plan_id: str, body: _Body):
    """The CLI's own preview: ``npc publish --member ... --json`` with no ``--preview-sha`` writes nothing
    and returns the digest (``preview_sha256``) the GM confirms before the publishing call."""
    if not body.members:
        raise HTTPException(status_code=400, detail="no members selected; npc publish needs an explicit member list.")
    return await _json(request, ["npc", "publish"], plan=plan_id, member=body.members)


@router.post("/plans/{plan_id}/npc/publish")
async def npc_publish(request: Request, plan_id: str, body: _Body):
    if not body.members:
        raise HTTPException(status_code=400, detail="no members selected; npc publish needs an explicit member list.")
    if not body.preview_sha:
        raise HTTPException(status_code=400, detail="preview_sha is required; POST .../npc/publish/preview first "
                            "and confirm the digest it returns.")
    return _sse(request, ["npc", "publish"], plan=plan_id, member=body.members, preview_sha=body.preview_sha)


@router.post("/plans/{plan_id}/grounding/propose")
async def grounding_propose(request: Request, plan_id: str, body: _Body | None = None):
    return _sse(request, ["grounding", "propose"], models=body, use_models=True, plan=plan_id)


@router.post("/grounding/proposals/{proposal_id}/decision")
async def grounding_decide(request: Request, proposal_id: str, body: _Body):
    return await _json(request, ["grounding", "decide", proposal_id], plan=body.plan, decision=body.decision,
                       reason=body.reason, reviewer=body.reviewer)


@router.post("/plans/{plan_id}/grounding/check")
async def grounding_check(request: Request, plan_id: str, body: _Body | None = None):
    return _sse(request, ["grounding", "check"], models=body, use_models=True, plan=plan_id)


@router.post("/plans/{plan_id}/grounding/preview")
async def grounding_preview(request: Request, plan_id: str, body: _Body | None = None):
    b = body or _Body()
    return await _json(request, ["grounding", "preview"], plan=plan_id, review=b.review,
                       claims_report=b.claims_report, request_id=b.request_id)


@router.post("/plans/{plan_id}/grounding/apply")
async def grounding_apply(request: Request, plan_id: str, body: _Body | None = None):
    return _sse(request, ["grounding", "apply"], plan=plan_id, preview_sha=body.preview_sha if body else None)


@router.get("/plans/{plan_id}/status")
async def run_status(request: Request, plan_id: str):
    return await _json(request, ["run", "status"], plan=plan_id)


@router.post("/plans/{plan_id}/resume")
async def run_resume(request: Request, plan_id: str):
    return _sse(request, ["run", "resume"], plan=plan_id)


@router.get("/plans/{plan_id}/receipt")
async def receipt(request: Request, plan_id: str):
    return await _json(request, ["receipt"], plan=plan_id)


@router.get("/plans/{plan_id}/review")
async def review_show(request: Request, plan_id: str):
    return await _json(request, ["review", "show"], plan=plan_id)


@router.post("/plans/{plan_id}/review/handoff")
async def review_handoff(request: Request, plan_id: str):
    return await _json(request, ["review", "handoff"], plan=plan_id)


@router.post("/transfer/verify")
async def transfer_verify(request: Request, body: _Body):
    return await _json(request, ["transfer", "verify"], plan=body.plan, canonical=body.canonical)


@router.post("/transfer/bind")
async def transfer_bind(request: Request, body: _Body):
    return await _json(request, ["transfer", "bind"], plan=body.plan, canonical=body.canonical)
