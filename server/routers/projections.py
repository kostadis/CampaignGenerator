"""State Projection API routes — config, staleness, and per-section rebuild.

Phase 6 of ``specs/006-state-projection-service`` (User Story 4): "See what
is stale and rebuild just that, from the UI." Release scope was deliberately
narrow (spec Q2) — staleness and per-section rebuild only.

**Reversed 2026-08-26 for thread triage, on a GM ruling (014 / #337,
research D13).** This docstring used to say there was no route for thread
triage because "adding a write route for proposals would move a judgment
checkpoint into the interface". That reasoning was wrong about *where* the
checkpoint lives. The checkpoint is the GM reading the evidence and deciding;
it is not the keyboard they type on. Meanwhile the absence had a cost the
original scope call did not anticipate: ``threads`` is a required section of
the ``planning`` doc spec, so ``assemble()`` refuses to write ANY planning
draft while ``docs/thread_registry.yaml`` is missing — and nothing in
``server/`` or ``frontend/`` mentioned the file, so every ``--sections`` build
dead-ended in a raw subprocess error naming a YAML file the UI gave the GM no
way to create (#337).

The checkpoint is preserved by *constraints*, not by absence:

- one candidate per ruling — no route accepts a list of ``norm`` values, and
  ``thread_registry rule`` takes exactly one ``--norm`` (FR-007, SC-004);
- every field that will be written is shown before it is written — ``ratify``
  requires an explicit ``--plan``; there is no "accept as proposed" (FR-008);
- nothing here decides thread identity, merges by similarity, or ratifies
  anything on its own (FR-022, FR-031).

Summary-map approval, the lineage report and promotion remain CLI/skill
driven; this reversal is scoped to thread triage alone.

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


# ── Thread registry seam (014) ────────────────────────────────────────────
#
# Every threads route below goes through here. The router builds argv and
# nothing else: no registry logic, no YAML parsing, no write of its own
# (Constitution VI, FR-018/FR-019 — guarded by
# tests/test_thread_registry_routes.py).


def _thread_registry(*args: str) -> dict:
    """Run one ``thread_registry`` verb and return its JSON payload.

    A non-zero exit becomes a 400 carrying the CLI's own message verbatim, so
    the GM reads the engine's wording rather than a paraphrase invented here
    (FR-021, SC-008). ``check`` is the one caller that must NOT treat exit 1
    as failure — a failing consistency check is data to render — so it passes
    ``allow_nonzero`` and reads the payload anyway.
    """
    return _thread_registry_run(args, allow_nonzero=False)


def _thread_registry_run(args: tuple[str, ...], *, allow_nonzero: bool) -> dict:
    cmd = [console_script("thread_registry"), *args]
    result = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True)
    if result.returncode != 0 and not allow_nonzero:
        raise HTTPException(
            status_code=400,
            detail=(result.stderr or result.stdout).strip()
            or f"thread_registry {args[0] if args else ''} failed",
        )
    if not result.stdout.strip():
        return {}
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise HTTPException(
            status_code=500, detail=f"malformed thread_registry payload: {exc}"
        ) from exc


def _thread_registry_write(*args: str) -> dict:
    """A write verb: no JSON comes back, only success or the CLI's refusal."""
    cmd = [console_script("thread_registry"), *args]
    result = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=(result.stderr or result.stdout).strip()
            or "thread_registry write failed",
        )
    return {"ok": True, "output": (result.stdout or "").strip()}


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


# ── Thread registry: reads (014 US1) ──────────────────────────────────────


@router.get("/threads/registry")
def threads_registry() -> dict:
    """The ratified registry, machine-readable. Read-only."""
    return _thread_registry("list", "--json")


@router.get("/threads/proposals")
def threads_proposals() -> dict:
    """The FULL candidate queue — every proposal, whatever its ruling.

    Deliberately takes **no** query, filter or paging parameter (FR-028,
    research D16). The 986-candidate OOTA harvest serialises to 484 KB, which
    a localhost single-user server sends without noticing, and the page
    searches in the browser. A server-side query here would put "which
    candidates matter" in the server — a scope decision that belongs to the
    GM.
    """
    return _thread_registry("proposals", "--json")


@router.get("/threads/check")
def threads_check() -> dict:
    """Registry invariants. **200 even when problems exist.**

    The CLI exits 1 so shell users and CI keep the behaviour they have, but a
    failing consistency check is a *state to render*, not a transport error —
    turning it into a 4xx would make the page show "request failed" where the
    GM needs to read which thread is broken.
    """
    return _thread_registry_run(("check", "--json"), allow_nonzero=True)


@router.get("/threads/corpus")
def threads_corpus(pattern: list[str] = Query(default=[])) -> dict:
    """Resolve explicit corpus patterns to the file list a harvest would read.

    Files only — **no chapter numbers** (GM ruling, research D20). Deriving a
    chapter here would mean importing ``chapter_of`` or wrapping it in a new
    verb, i.e. a second seam onto the engine for a preview. The chapterless
    warning lives on the candidate card instead, where the GM acts on it.

    No config fallback: reading ``ensemble.yaml`` for a default corpus would
    be a cross-service config read (research D5), and an implicit corpus is
    exactly the silent "all" Constitution X forbids.
    """
    picked = [p.strip() for p in pattern if p and p.strip()]
    if not picked:
        raise HTTPException(
            status_code=400,
            detail="pattern is required — give at least one corpus glob "
                   "before resolving; there is no implicit \"all\".",
        )
    cwd = Path.cwd().resolve()
    files: dict[str, int] = {}
    for pat in picked:
        for hit in cwd.glob(pat):
            r = hit.resolve()
            if cwd not in r.parents:
                continue  # confine to the workspace, as list_chapters does
            if r.is_file():
                files[str(r.relative_to(cwd))] = r.stat().st_size
    return {"files": [{"path": p, "size": files[p]} for p in sorted(files)],
            "count": len(files)}


@router.get("/threads/run/propose")
async def run_threads_propose(corpus: list[str] = Query(default=[])):
    """Harvest thread candidates (SSE).

    **Deterministic — zero tokens.** No ``resolve_selection``, no
    ``--model``/``--backend``/``--endpoint``: this pass reads JSON off disk
    and groups it. That is why the page gives it a dedicated run control
    rather than the shared ``RunPanel`` (research D19), and why no credential
    is involved at any point.
    """
    picked = [c.strip() for c in corpus if c and c.strip()]
    if not picked:
        raise HTTPException(
            status_code=400,
            detail="corpus is required — pass at least one --corpus glob.",
        )
    cmd = [console_script("thread_registry"), "propose"]
    for c in picked:
        cmd += ["--corpus", c]
    return _sse_response(cmd)


# ── Thread registry: rulings (014 US2) ────────────────────────────────────


@router.post("/threads/rule")
async def threads_rule(request: Request) -> dict:
    """Record ONE ruling on ONE candidate: ratified / rejected / deferred.

    There is deliberately no bulk variant — no endpoint in this router
    accepts a list of ``norm`` values (SC-004, asserted by
    tests/test_thread_registry_routes.py).
    """
    body: Any = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    norm = (body.get("norm") or "").strip()
    status = (body.get("status") or "").strip()
    if not norm:
        raise HTTPException(status_code=400, detail="norm is required")
    if not status:
        raise HTTPException(status_code=400, detail="status is required")
    args = ["rule", "--norm", norm, "--status", status]
    if body.get("note"):
        args += ["--note", str(body["note"])]
    if body.get("thread"):
        args += ["--thread", str(body["thread"])]
    return _thread_registry_write(*args)


@router.post("/threads/ratify")
async def threads_ratify(request: Request) -> dict:
    """Turn one candidate into canon — **one** subprocess call.

    The body IS the plan (id/title/status/opened/tracker/notes/log[]),
    forwarded verbatim on stdin to ``thread_registry ratify --plan -``. There
    is no 207, no per-step report and no partial-apply state for the page to
    model: that is exactly what the atomic verb bought (research D18).
    """
    body: Any = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    norm = (body.get("norm") or "").strip()
    if not norm:
        raise HTTPException(status_code=400, detail="norm is required")

    # Route-edge validation BEFORE the subprocess (research D4): a chapterless
    # accept is a *form* problem, and the GM should be told which field is
    # missing rather than handed check_registry's wording about log rows.
    plan = {k: v for k, v in body.items() if k != "norm"}
    rows = plan.get("log")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(
            status_code=400,
            detail="log is required — a ratified thread records at least the "
                   "chapter it opened in.")
    for i, row in enumerate(rows, 1):
        ch = row.get("chapter") if isinstance(row, dict) else None
        if not isinstance(ch, int) or isinstance(ch, bool) or ch < 1:
            raise HTTPException(
                status_code=400,
                detail=f"log row {i}: chapter is required and must be a "
                       f"chapter number — this candidate has no chapter "
                       f"recorded, so you must supply one.")
    if not plan.get("matches") and not str(plan.get("title") or "").strip():
        raise HTTPException(status_code=400, detail="title is required")

    cmd = [console_script("thread_registry"), "ratify", "--norm", norm,
           "--plan", "-"]
    result = subprocess.run(cmd, cwd=str(Path.cwd()), capture_output=True,
                            text=True, input=json.dumps(plan))
    if result.returncode != 0:
        raise HTTPException(
            status_code=400,
            detail=(result.stderr or result.stdout).strip() or "ratify failed")
    return {"ok": True, "output": (result.stdout or "").strip()}


# ── Thread registry: maintenance (014 US3) ────────────────────────────────


@router.post("/threads/log")
async def threads_log(request: Request) -> dict:
    """Append one per-chapter transition to a ratified thread."""
    body: Any = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    for field in ("id", "chapter", "change", "summary"):
        if body.get(field) in (None, ""):
            raise HTTPException(status_code=400, detail=f"{field} is required")
    args = ["log", "--id", str(body["id"]), "--chapter", str(body["chapter"]),
            "--change", str(body["change"]), "--summary", str(body["summary"])]
    if body.get("quote"):
        args += ["--quote", str(body["quote"])]
    return _thread_registry_write(*args)


@router.post("/threads/status")
async def threads_status(request: Request) -> dict:
    """Change a thread's lifecycle status.

    A closing chapter is required for ``resolved``/``abandoned`` — enforced
    here so the form can say so, AND by the CLI, which is the authority.
    """
    body: Any = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    for field in ("id", "status"):
        if body.get(field) in (None, ""):
            raise HTTPException(status_code=400, detail=f"{field} is required")
    args = ["set-status", "--id", str(body["id"]), "--status", str(body["status"])]
    if body.get("chapter"):
        args += ["--chapter", str(body["chapter"])]
    return _thread_registry_write(*args)


@router.post("/threads/alias")
async def threads_alias(request: Request) -> dict:
    """Record a title variant as the same thread.

    Aliasing is an *identity assertion the GM makes*, never something derived
    from string similarity — the engine matches on exact normalised titles for
    the same reason (FR-022, FR-031).
    """
    body: Any = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    for field in ("id", "alias"):
        if body.get(field) in (None, ""):
            raise HTTPException(status_code=400, detail=f"{field} is required")
    return _thread_registry_write("alias", "--id", str(body["id"]),
                                  "--alias", str(body["alias"]))
