"""State Projection API routes — config, staleness, and per-section rebuild.

Phase 6 of ``specs/006-state-projection-service`` (User Story 4): "See what
is stale and rebuild just that, from the UI." Release scope is deliberately
narrow (spec Q2) — staleness and per-section rebuild only. There is no route
for thread triage, summary-map approval, the lineage report, or promotion;
those stay CLI/skill driven, and adding a write route for proposals would
move a judgment checkpoint into the interface (the LLM-pipeline design rule:
scope/attribution decisions need a human checkpoint, not a button).

This router contains NO generation logic — argv construction and streaming
only (FR-023, Constitution VI). Every path the ``run/*`` routes need comes
from ``ProjectionConfigService.resolved()`` at the route edge; no location
literal survives anywhere in this file (guarded by
``tests/test_projection_routes.py::test_no_literals_in_router``, mirroring
``tests/test_ensemble_config_defaults.py``'s no-drift guard one layer up).

``GET /sections`` shells out to ``grounding_sections list --json`` (T037)
rather than parsing the human-readable table — screen-scraping CLI output
would put parsing logic in the server, which Constitution VI and FR-023
forbid.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from campaignlib.projection_config import ProjectionConfig
from campaignlib.selection import ModelSelection
from server.backend_forwarding import backend_cli_args
from server.platform_config_service import resolve_selection, selection_cli_args
from server.projection_config_service import ProjectionConfigService
from server.subprocess_runner import console_script, stream_subprocess

router = APIRouter()


# ── Config (own document, own service) ──────────────────────────────────────

def _service(request: Request) -> ProjectionConfigService:
    """Resolve the service for this request.

    Prefers the live platform's config dir; falls back to ``cwd/config``
    like the grounding and ensemble routers, so read-only routes work in
    contexts without a booted platform (see ``ProjectionConfigService``'s
    module docstring).
    """
    platform = getattr(request.app.state, "platform", None)
    base = platform.config_path_base if platform is not None else Path.cwd() / "config"
    return ProjectionConfigService(base)


@router.get("/config")
def get_projection_config(request: Request) -> ProjectionConfig:
    return _service(request).get_config()


@router.put("/config")
async def put_projection_config(request: Request) -> ProjectionConfig:
    """Merge a grouped partial into ``projections.yaml``.

    The body IS the partial (no ``{"values": …}`` envelope), matching
    ``PUT /api/grounding/config`` / ``PUT /api/ensemble/config``. An unknown
    key, or an ``output.draft`` missing the ``{doc}`` placeholder, is a 400 —
    the schema is strict.
    """
    partial: Any = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return _service(request).update_config(partial)


# ── Command-building helpers (mirror grounding.py / ensemble.py) ───────────

def _cmd_opt(cmd: list[str], flag: str, value: str | int | None) -> None:
    if value:
        cmd += [flag, str(value)]


def _cmd_flag(cmd: list[str], flag: str, condition: bool) -> None:
    if condition:
        cmd.append(flag)


def _sse_response(cmd: list[str]) -> StreamingResponse:
    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _selection_args(
    request: Request, *, model: str | None, backend: str | None,
    endpoint: str | None, selection: ModelSelection | None,
) -> list[str]:
    """Resolve this run's model/backend/endpoint and render the CLI flags.

    Same split ``server/routers/ensemble.py::_backend_args`` uses: the
    resolved backend/endpoint go through ``backend_cli_args`` directly (an
    explicit ``endpoint`` query param wins over whatever the dgx-wiring
    fallback inside ``resolve_selection`` would have supplied), and a
    throwaway copy of the resolution with ``backend`` forced to
    ``"anthropic"`` goes through ``selection_cli_args`` so that call
    contributes only ``--model`` — never a duplicate or wrongly-shaped
    ``--backend``/``--endpoint`` (Constitution V: ``selection_cli_args`` is
    the only place the model flag and the batch flag are built).

    The batch flag never reaches ``grounding_sections build`` — it has no
    such flag at all — so an incompatible batch selection raises here, via
    ``resolve_selection``'s own refusal machinery
    (``BATCH_CAPABILITY["projections"] == "incompatible"``), before any argv
    is built.
    """
    resolved = resolve_selection(
        request, request_model=model, request_backend=backend,
        service=selection, service_name="projections",
    )
    args = backend_cli_args(resolved.backend, endpoint=endpoint or resolved.endpoint)
    args += selection_cli_args(replace(resolved, backend="anthropic"))
    return args


# ── Staleness (read-only, T037/T041) ────────────────────────────────────────

@router.get("/sections")
def get_sections(doc: str):
    """One row per section for ``doc`` — shells out to ``grounding_sections
    list --json`` and returns the parsed payload verbatim, ``provenance``
    included (FR-024a). Read-only; no route in this file writes it."""
    cmd = [console_script("grounding_sections"), "list", "--doc", doc, "--json"]
    result = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=(result.stderr or result.stdout).strip()
            or f"grounding_sections list --doc {doc} failed",
        )
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"malformed sections payload: {exc}"
        ) from exc


# ── Build (SSE) ──────────────────────────────────────────────────────────

@router.get("/run/build")
async def run_build(
    request: Request,
    doc: str,
    sections: list[str] = Query(default=[]),
    force: bool = False,
    model: str | None = None,
    backend: str | None = None,
    endpoint: str | None = None,
    max_tokens: int | None = None,
):
    """Rebuild exactly the named sections of ``doc``.

    ``sections`` is declared OPTIONAL here and rejected explicitly when
    empty — Constitution X, mirroring the "no silent all" precedent
    ``server/routers/ensemble.py::run_extract`` established. A missing or
    empty selection is a 400 naming the problem, never FastAPI's generic 422
    for an absent required param, and never "every section" standing in for
    an omitted choice. Selecting every section is still possible — the page
    just has to send them all explicitly, which is the point.
    """
    picked = [s.strip() for s in sections if s and s.strip()]
    if not picked:
        raise HTTPException(
            status_code=400,
            detail="sections is required — pick at least one section (or "
                   "every section) before building; there is no implicit "
                   "\"all\".",
        )

    svc = _service(request)
    sel = svc.get_selection()

    cmd = [console_script("grounding_sections"), "build",
           "--doc", doc, "--sections", ",".join(picked)]
    _cmd_flag(cmd, "--force", force)
    cmd += _selection_args(
        request, model=model, backend=backend, endpoint=endpoint,
        selection=sel if not sel.is_empty() else None,
    )
    _cmd_opt(cmd, "--max-tokens", max_tokens)

    return _sse_response(cmd)


# ── Recent events (SSE, moved from /api/ensemble/run/recent-events) ────────

@router.get("/run/recent-events")
async def run_recent_events(
    request: Request,
    corpus: list[str] = Query(default=[]),
    output: str = "",
    window: int | None = None,
    store: str = "",
):
    """Wraps ``build_recent_events`` (research D15). Deterministic — no
    model call, so no selection resolution applies. ``corpus`` is required
    and repeated (Constitution X: no config default exists or may be added
    for it); ``output``/``window``/``store`` are sentinels resolved from
    ``output.recent_events``, ``output.recent_events_window`` and
    ``stores.events``.
    """
    picked = [c.strip() for c in corpus if c and c.strip()]
    if not picked:
        raise HTTPException(
            status_code=400,
            detail="corpus is required — pass at least one --corpus glob.",
        )

    cfg = _service(request).resolved()
    cmd = [console_script("build_recent_events"), "--corpus", *picked]
    _cmd_opt(cmd, "--output", output or cfg.output.recent_events)
    win = window if window is not None else cfg.output.recent_events_window
    cmd += ["--window", str(win)]
    _cmd_opt(cmd, "--store", store or cfg.stores.events)

    return _sse_response(cmd)


# ── Model/backend selection (feature 003) ──────────────────────────────────

@router.get("/selection")
def get_projection_selection(request: Request):
    return _service(request).get_selection().model_dump()


@router.put("/selection")
async def put_projection_selection(request: Request):
    partial = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    try:
        selection = ModelSelection.model_validate(partial)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _service(request).set_selection(selection).model_dump()


@router.delete("/selection")
def delete_projection_selection(request: Request):
    """Clear the override — this service returns to the platform selection
    with no further operator action (FR-013)."""
    return _service(request).set_selection(ModelSelection()).model_dump()


@router.get("/selection/resolved")
def get_projection_resolved_selection(request: Request):
    """What a ``/run/build`` would actually use, and where each half came
    from — the pre-run preview ``SelectionPanel.vue`` renders."""
    sel = _service(request).get_selection()
    return resolve_selection(
        request, service=sel if sel and not sel.is_empty() else None,
        service_name="projections", raise_on_incompatible=False,
    ).as_dict()
