"""Ensemble grounding-doc workflow API routes.

The UI mechanizes the ensemble pipeline (extract → bundle → synthesize → review);
this router shells out to the CLI scripts via subprocess_runner and exposes
disk-derived stage status. It contains NO pipeline logic and issues NO
retrieval/render calls — the CLI is the engine (Constitution Principle VI), files
on disk are the truth (Principle I), and OpenRouter is selected via env that the
single campaignlib seam honors (Principle V).
"""

import difflib
import glob
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from campaignlib.registry import find_registry
from server.backend_forwarding import backend_cli_args
from server.config import MODELS
from server.ensemble_config_service import EnsembleConfigService
from server.ensemble_config_shared import EnsembleConfig
from campaignlib.constants import config_path
from campaignlib.party_config import (
    PARTY_CONFIG_FILENAME,
    load_party_config,
    resolve_party_config,
)
from campaignlib.planning_config import (
    PLANNING_CONFIG_FILENAME,
    load_planning_config,
    resolve_entries,
)
from campaignlib.selection import ModelSelection
from server.platform_config_service import resolve_selection
from server.subprocess_runner import console_script, stream_subprocess, sse_error_stream

router = APIRouter()


def get_ensemble_service(request: Request) -> EnsembleConfigService:
    """Per-request DI for the ensemble config service (Planning's shipped
    shape — not an ``app.state`` singleton).

    Uses the platform's config dir when the server booted with a campaign, and
    otherwise falls back to ``<cwd>/config`` — the same convention
    ``_default_party_config``/``_default_planning_config`` below already use
    for this router's two sibling config files. Deliberately NOT
    ``require_platform``: that would make read-only routes like ``/chapters``
    and ``/status`` 503 without a platform, which they never did before, and
    the service needs a directory rather than a platform anyway (see
    ``server/ensemble_config_service.py``'s module docstring). In a booted
    server the two paths are identical — ``main`` chdirs to ``campaign_dir``.
    """
    platform = getattr(request.app.state, "platform", None)
    base = platform.config_path_base if platform is not None else Path.cwd() / "config"
    return EnsembleConfigService(base)

# The four grounding docs the workflow targets. live = promote target; draft =
# what synthesis writes. Nothing else may be promoted (FR-013).
GROUNDING_DOCS = {
    "world_state": ("docs/world_state.md", "docs/world_state_draft.md"),
    "campaign_state": ("docs/campaign_state.md", "docs/campaign_state_draft.md"),
    "party": ("docs/party.md", "docs/party_draft.md"),
    "planning": ("docs/planning.md", "docs/planning_draft.md"),
}

# Models considered capable enough for synthesis (FR-014 / R6). Anything else
# selected for the synthesize stage triggers a non-fatal warning.
#
# Derived from the registry, not snapshotted. The original literal froze the
# Claude ids of the day and went stale as soon as the registry moved: after
# platform-isolation Phase 5a refreshed ``MODELS`` this set still listed the
# retired ``claude-sonnet-4-20250514`` and knew nothing of Opus 5 / Sonnet 5 /
# Fable 5 — so picking the strongest model on offer earned a "may be too weak"
# warning. specs/001-ensemble-workflow-ui/research.md R6 always described the
# allow-list as "the Claude MODELS and a small set of frontier OpenRouter ids";
# this restores that, so it can no longer drift from the registry.
#
# The judgment that is genuinely ours — and the one a human should revisit — is
# the *exclusion*, not the inclusion. The stated bar is "at least as capable as
# Sonnet", which rules out the Haiku tier and nothing else currently in the
# registry. Matched as a substring so a future Haiku id is excluded on arrival
# rather than silently promoted.
_SUB_SONNET_TIER = "haiku"

# Frontier non-Anthropic ids. Not derivable — MODELS is the Anthropic registry
# — so these stay an explicit, hand-maintained set.
_THIRD_PARTY_SYNTHESIS_CAPABLE = {
    "anthropic/claude-sonnet-4", "anthropic/claude-opus-4",
    "openai/gpt-5", "google/gemini-2.5-pro",
}

SYNTHESIS_CAPABLE = {
    m for m in MODELS if _SUB_SONNET_TIER not in m
} | _THIRD_PARTY_SYNTHESIS_CAPABLE


# ── Command-building helpers (mirror grounding.py) ──────────────────────────

def _cmd_opt(cmd: list[str], flag: str, value) -> None:
    if value:
        cmd += [flag, str(value)]


def _cmd_multi(cmd: list[str], flag: str, values: list[str]) -> None:
    for v in values or []:
        if v and v.strip():
            cmd += [flag, v.strip()]


def _cmd_flag(cmd: list[str], flag: str, condition: bool) -> None:
    if condition:
        cmd.append(flag)


def _backend_args(backend: str, model: str, request: Request, *,
                  endpoint: str | None = None,
                  endpoints: list[str] | None = None) -> list[str]:
    """Resolve this stage's selection and render it as CLI flags.

    Feature 003 replaced this function's body with a call to the one seam,
    ``server.platform_config_service.resolve_selection``. Callers already
    fold the per-stage ``ensemble.yaml`` value into ``backend``/``model``
    before calling (``backend = backend or cfg.extract.backend``), so what
    arrives here is "request-or-service" already collapsed; the seam sees it
    as the explicit tier and falls back to the platform when it is empty.

    Resolution order, unchanged in effect:

    1. an explicit ``model``/``backend`` on the request
    2. ``ensemble.yaml``'s per-stage value (folded in by the caller)
    3. ``platform.runtime.default_model`` / ``default_backend``
    4. ``campaignlib.constants.DEFAULT_MODEL``

    **What changed: the stale-model guard no longer substitutes.** This used
    to read

        anthropic_model = model if (model or "").startswith("claude-") else None
        args += ["--model", resolve_default_model(anthropic_model, request)]

    — i.e. a model id that could not belong to the Anthropic backend was
    silently discarded and the platform's model swapped in. The Setup page
    keeps a per-stage model across a backend switch, so selecting dgx, typing
    a Qwen id, then switching back to Anthropic left a foreign id in
    ``model``; the old code quietly ran something the operator had not
    chosen. Under 003 that pair raises ``IncompatibleSelection`` (HTTP 409)
    and the operator clears or corrects it. The *rule* survives in
    ``platform_config_shared.compatible``; only the substitution is gone.

    ``endpoint``/``endpoints`` still come from the caller — extract fans out
    across several DGX hosts (plural), synthesize targets one (singular).
    """
    # Passed as the SERVICE tier, not the request tier. The callers fold the
    # per-stage ensemble.yaml value into these arguments, and that value's
    # schema default for `backend` is the literal "anthropic" — so treating it
    # as an explicit request would pin every unconfigured stage to Anthropic
    # and the platform's backend would never reach the ensemble at all
    # (FR-008). As a service tier, resolve_selection's "backend is the schema
    # default and no model is set" rule recognises it as deferring, while a
    # stage that genuinely names dgx/openrouter still wins.
    resolved = resolve_selection(
        request,
        service=ModelSelection(backend=backend or None, model=model or None),
        service_name="ensemble",
    )
    args = backend_cli_args(resolved.backend, endpoint=endpoint, endpoints=endpoints)
    return args + (["--model", resolved.model] if resolved.model else [])


def _resolve_ensemble_path(path: str) -> Path:
    """Resolve a path and confine it to the campaign workspace (CWD).

    Rejects traversal outside the workspace — the UI must not read/write
    arbitrary disk locations.
    """
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    cwd = Path.cwd().resolve()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (cwd / p)
    p = p.resolve()
    if cwd != p and cwd not in p.parents:
        raise HTTPException(status_code=400, detail="path escapes the campaign workspace")
    return p


def _is_live_doc(path: Path) -> bool:
    cwd = Path.cwd().resolve()
    live = {(cwd / live_rel).resolve() for live_rel, _ in GROUNDING_DOCS.values()}
    return path.resolve() in live


def _default_party_config() -> Path | None:
    """The campaign's ``config/party.yaml``, or None if it doesn't exist.

    Used when the caller doesn't specify one. This used to probe ``config/``
    then the campaign root; there is one declared location now (Track 0 of
    docs/config/grounding-isolation.md) — ``./migrate_config.sh`` moves a
    stray copy into it.
    """
    p = config_path(Path.cwd(), PARTY_CONFIG_FILENAME)
    return p if p.exists() else None


def _default_planning_config() -> Path | None:
    """The campaign's ``config/planning.yaml``, or None (mirrors
    :func:`_default_party_config`)."""
    p = config_path(Path.cwd(), PLANNING_CONFIG_FILENAME)
    return p if p.exists() else None


def _default_threads_file(threads_out: str) -> Path | None:
    """The ensemble threads track's output location (see the /run/threads
    route) — used when the caller doesn't specify --threads explicitly, for
    both world_state and planning synthesis.

    ``threads_out`` comes from ``EnsemblePaths.threads_out`` so this and the
    /run/threads route that writes the file cannot disagree about where it is.
    """
    p = Path.cwd() / threads_out
    return p if p.exists() else None


def _all_planning_npc_files(npc_glob: str, exclude: set[Path] = frozenset()) -> list[str]:
    """Every merged NPC dossier — the "flat" planning mode's auto-detect
    fallback when no explicit --npc list is given and no planning.yaml is in
    play (no config to bind against, unlike _planning_npc_passthrough, so
    `exclude` — PC dossiers, see _party_pc_dossier_files — is the only
    filter)."""
    cwd = Path.cwd()
    return [str(p) for p in sorted(cwd.glob(npc_glob))
            if p.resolve() not in exclude]


def _planning_npc_passthrough(
    config_path: Path, npc_glob: str, exclude: set[Path] = frozenset()
) -> list[str]:
    """Merged NPC dossiers not already bound in planning.yaml and not in
    `exclude` (PC dossiers, see _party_pc_dossier_files).

    planning.py's own docstring frames --planning-config entries as the
    arc-scored minority and --npc pass-through dossiers as "the majority" —
    without this, every NPC not manually added to planning.yaml is silently
    absent from planning.md. Dossiers already bound in the config are
    excluded so planning.py's own overlap guard (each NPC in exactly one
    place) doesn't trip."""
    cwd = Path.cwd()
    npc_files = sorted(cwd.glob(npc_glob))
    if not npc_files:
        return []
    config = load_planning_config(config_path)
    # Resolve against the campaign root (this router is cwd-rooted throughout —
    # see _resolve_ensemble_path and _default_planning_config), NOT against
    # planning.yaml's own directory. Track A′ of docs/config/
    # grounding-isolation.md; issues #145/#146.
    npcs = resolve_entries(config.npcs, cwd)
    bound = {e.dossier.resolve() for e in npcs if e.dossier is not None}
    return [str(p) for p in npc_files if p.resolve() not in bound and p.resolve() not in exclude]


def _party_pc_dossier_files(party_config_path: Path | None) -> tuple[set[Path], str | None]:
    """Resolved dossier paths explicitly bound to a PC in party.yaml, so
    planning's NPC auto-detect can exclude them — ensemble extraction
    doesn't distinguish PCs from NPCs, so a PC gets a merged npc_*.md
    dossier just like anyone else.

    Only dossiers with an explicit `dossier:` entry in party.yaml are
    excluded (see load_party_config's docstring: attribution is always an
    explicit, human-authored mapping, never inferred by name-matching) — a
    PC with no such binding still shows up in the NPC list, same as before
    this existed.

    Returns (exclude_set, warning). party.yaml is optional here (it's a
    filter, not a required input), so a load failure doesn't block
    planning — but it's surfaced as a warning instead of silently doing
    nothing."""
    if party_config_path is None:
        return set(), None
    try:
        config = resolve_party_config(
            load_party_config(party_config_path), Path.cwd()
        )
    except ValueError as e:
        return set(), f"could not read {party_config_path} for PC exclusion: {e}"
    return {pc.dossier.resolve() for pc in config.characters if pc.dossier is not None}, None


def _default_party_context() -> list[str]:
    """Auto-include world_state/campaign_state as --context for party
    synthesis — otherwise party.py's characters-only path has no source for
    current location/active quests/reputation and correctly reports them as
    absent. Prefers each doc's draft (this workflow's own freshest output)
    over its live counterpart when both exist."""
    cwd = Path.cwd()
    found = []
    for key in ("world_state", "campaign_state"):
        live_rel, draft_rel = GROUNDING_DOCS[key]
        draft, live = cwd / draft_rel, cwd / live_rel
        if draft.exists():
            found.append(str(draft))
        elif live.exists():
            found.append(str(live))
    return found


# ── Per-stage in-flight lock (M4) ───────────────────────────────────────────
# Single-operator, local-first: an in-process guard is enough to stop a
# double-click or a second tab from launching two writers on the same workdir
# (the orphaned-worker cache-corruption trap in ensemble_workflow.md).

_RUNNING: set[str] = set()


def _lock_key(stage: str) -> str:
    return f"{Path.cwd().resolve()}::{stage}"


def _sse_error_response(message: str) -> StreamingResponse:
    """Wrap a precondition failure as a real SSE stream (see sse_error_stream's
    docstring) — a plain error response is invisible to the browser's
    EventSource and reads as a dropped connection, not a reported error."""
    return StreamingResponse(
        sse_error_stream(message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_locked(stage: str, cmd: list[str], env_extra: dict[str, str] | None = None,
                prelude: str = "") -> StreamingResponse:
    key = _lock_key(stage)
    if key in _RUNNING:
        return _sse_error_response(
            f"stage '{stage}' is already running for this campaign — "
            f"wait for it to finish (avoids corrupting the workdir).")
    _RUNNING.add(key)

    def _release(_rc):
        # T023: stream_subprocess calls on_complete from its finally block on
        # every exit path (normal, explicit abort, or disconnect). The lock is
        # therefore always released — no run can get stuck "running" after abort.
        _RUNNING.discard(key)

    async def _gen():
        if prelude:
            import json
            yield f"data: {json.dumps(prelude)}\n\n"
        async for chunk in stream_subprocess(cmd, cwd=str(Path.cwd()),
                                             env_extra=env_extra or None,
                                             on_complete=_release):
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Config (owned document, docs/config/ensemble-isolation.md) ──────────────
#
# Ensemble config is one grouped document, not a collection, so this takes the
# Session Doc Editor's document shape (GET/PUT of the whole thing) rather than
# Planning's per-resource CRUD.
#
# NOTE: the "/api/ensemble" prefix is supplied by main.py's include_router,
# matching every sibling router. Do not set prefix= on the APIRouter above or
# these mount at /api/ensemble/api/ensemble/* — the bug planning-isolation.md
# shipped and had to fix.

@router.get("/config", response_model=EnsembleConfig)
def get_ensemble_config(
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    """The stored ensemble.yaml, all-defaults if the file does not exist yet."""
    return service.get_config()


@router.put("/config", response_model=EnsembleConfig)
async def put_ensemble_config(
    request: Request,
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    """Merge a partial into ensemble.yaml and return the validated result.

    Body is the grouped partial itself (e.g. ``{"tuning": {"chapter_parallel":
    6}}``), not a ``{"values": …}`` envelope — the envelope belongs to the
    generic ``PUT /api/config/section/{name}`` this endpoint replaces.
    400 on validation failure, including an unknown key (the schema is strict).
    """
    partial = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return service.update_config(partial)


# ── Status (disk-derived, FR-002) ───────────────────────────────────────────

@router.get("/status")
def status(service: EnsembleConfigService = Depends(get_ensemble_service)):
    """Pipeline state computed entirely from artifacts on disk — no caching.

    Phase 3 dropped a dead ``chapters`` query parameter: it carried its own
    copy of the chapter glob and the body never referenced it. The frontend
    (``EnsembleWorkflow.vue``) has always called this with no params.
    """
    cfg = service.resolved()
    cwd = Path.cwd()
    per_chapter = sorted(glob.glob(str(cwd / cfg.paths.corpus_glob)))
    dossiers = sorted(glob.glob(str(cwd / cfg.paths.state_dossiers_dir / "*.md")))
    drafts = [name for name, (_, draft_rel) in GROUNDING_DOCS.items()
              if (cwd / draft_rel).exists()]
    promoted = [name for name, (live_rel, draft_rel) in GROUNDING_DOCS.items()
                if (cwd / live_rel).exists() and (cwd / draft_rel).exists()
                and (cwd / live_rel).stat().st_mtime >= (cwd / draft_rel).stat().st_mtime]

    def st(done: bool) -> str:
        return "complete" if done else "not_started"

    stages = [
        {"id": "extract", "status": st(bool(per_chapter)), "artifacts": len(per_chapter)},
        {"id": "bundle", "status": st(bool(dossiers)), "artifacts": len(dossiers)},
        {"id": "synthesize", "status": st(bool(drafts)), "drafts": drafts},
        {"id": "review", "status": st(bool(promoted)), "promoted": promoted},
    ]
    current = next((s["id"] for s in stages if s["status"] != "complete"), "review")
    return {"campaign_dir": str(cwd.resolve()), "stages": stages, "current_stage": current}


# ── File listing / read / write (FR-004, FR-012, FR-017) ────────────────────

@router.get("/files")
def list_files(dir: str, pattern: str = "*.md"):
    d = _resolve_ensemble_path(dir)
    if not d.exists():
        return {"dir": str(d), "exists": False, "files": []}
    files = sorted(f.name for f in d.glob(pattern) if f.is_file())
    return {"dir": str(d), "exists": True,
            "files": [{"name": n, "size": (d / n).stat().st_size} for n in files]}


@router.get("/chapters")
def list_chapters(
    glob: list[str] = Query(default=[]),
    per_chapter_dir: str = "",
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    """Resolve one or more chapter globs/paths to the concrete file list the
    extraction stage would run over (FR: chapter selection). Each entry is
    flagged `extracted` when its per-chapter merged.json already exists on disk
    (Principle I — the picker reflects truth, not a cached selection).

    Omitted parameters fall back to ``ensemble.yaml`` rather than to literals
    declared here — see docs/config/ensemble-isolation.md Phase 3.
    """
    cfg = service.resolved()
    glob = glob or [cfg.paths.chapters_glob]
    per_chapter_dir = per_chapter_dir or cfg.paths.per_chapter_dir
    cwd = Path.cwd().resolve()
    pc_dir = (cwd / per_chapter_dir).resolve()
    matched: dict[str, Path] = {}
    for pattern in glob or []:
        if not pattern or not pattern.strip():
            continue
        for hit in cwd.glob(pattern.strip()):
            r = hit.resolve()
            if cwd not in r.parents:
                continue  # confine to the workspace (escaping hits stay silently empty)
            if r.is_dir():
                rel = r.relative_to(cwd)
                raise HTTPException(
                    status_code=400,
                    detail=f"'{pattern.strip()}' matched a directory ({rel}), not chapter files. Did you mean '{rel}/*.md'?",
                )
            if not r.is_file():
                continue
            matched[str(r.relative_to(cwd))] = r
    out = []
    for rel in sorted(matched):
        p = matched[rel]
        merged = pc_dir / p.stem / "merged.json"
        out.append({"path": rel, "stem": p.stem, "size": p.stat().st_size,
                    "extracted": merged.exists()})
    return {"chapters": out, "count": len(out)}


@router.get("/file")
def read_file(path: str):
    p = _resolve_ensemble_path(path)
    if not p.exists() or not p.is_file():
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    return {"exists": True, "content": p.read_text(encoding="utf-8")}


@router.put("/file")
async def write_file(path: str, request: Request):
    """Write an interchange file (e.g. aliases.json). Live grounding docs are
    rejected — promotion is the only path to a live doc (FR-013)."""
    p = _resolve_ensemble_path(path)
    if _is_live_doc(p):
        raise HTTPException(status_code=403,
                            detail="refusing to write a live grounding doc; use /promote")
    p.parent.mkdir(parents=True, exist_ok=True)
    data = await request.json()
    p.write_text(data.get("content", ""), encoding="utf-8")
    return {"ok": True, "size": p.stat().st_size}


# ── Diff + promote (US3 gate, FR-013, SC-005) ───────────────────────────────

@router.get("/diff")
def diff(draft: str, live: str):
    """Unified diff draft vs live for the diff-before-promote gate. Read-only."""
    dp = _resolve_ensemble_path(draft)
    lp = _resolve_ensemble_path(live)
    draft_text = dp.read_text(encoding="utf-8").splitlines(keepends=True) if dp.exists() else []
    live_text = lp.read_text(encoding="utf-8").splitlines(keepends=True) if lp.exists() else []
    ud = "".join(difflib.unified_diff(live_text, draft_text,
                                      fromfile=str(lp), tofile=str(dp)))
    return {"draft": str(dp), "live": str(lp), "diff": ud,
            "draft_exists": dp.exists(), "live_exists": lp.exists()}


@router.post("/promote")
async def promote(request: Request):
    """Copy a reviewed draft over its live grounding doc — the single explicit
    live-doc writer (FR-013). Restricted to the four known grounding docs."""
    body = await request.json()
    draft = _resolve_ensemble_path(body.get("draft", ""))
    live = _resolve_ensemble_path(body.get("live", ""))
    if not _is_live_doc(live):
        raise HTTPException(status_code=400,
                            detail="promote target must be one of the four grounding docs")
    if not draft.exists():
        raise HTTPException(status_code=404, detail="draft does not exist")
    shutil.copyfile(draft, live)
    return {"ok": True, "live": str(live), "size": live.stat().st_size}


# ── Stage runners (SSE) ─────────────────────────────────────────────────────

@router.get("/run/extract")
def run_extract(
    request: Request,
    chapters: list[str] = Query(default=[]),
    per_chapter_dir: str = "",
    out: str = "",
    plan: str = "",
    endpoints: list[str] = Query(default=[]),
    model: str = "",
    backend: str = "",
    chapter_parallel: int | None = None,
    chunk_parallel: int | None = None,
    no_speculative: bool = False,
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    cfg = service.resolved()
    per_chapter_dir = per_chapter_dir or cfg.paths.per_chapter_dir
    out = out or cfg.paths.merged_out
    backend = backend or cfg.extract.backend
    model = model or cfg.extract.model or ""
    endpoints = endpoints or cfg.extract.endpoints
    # `is None`, not `or`: 0 is a legitimate value for these, so a falsy-test
    # would silently substitute the config value for an explicit 0.
    if chapter_parallel is None:
        chapter_parallel = cfg.tuning.chapter_parallel
    if chunk_parallel is None:
        chunk_parallel = cfg.tuning.chunk_parallel

    # Principle X: no silent "all". An empty selection is refused, never
    # expanded to the full glob — "Select all" must be an explicit choice the
    # caller makes (the UI sends every resolved path; a CLI user types a glob).
    # Deliberately NOT defaulted from cfg.chapters_selected: the request is the
    # authority on what this run covers, and a persisted selection quietly
    # standing in for an omitted one is exactly the silent "all" this forbids.
    picked = [c.strip() for c in (chapters or []) if c and c.strip()]
    if not picked:
        return StreamingResponse(
            sse_error_stream("No chapters selected — pick chapters (or click "
                             "'Select all') before running extraction."),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    cmd = [console_script("ensemble_batch"),
           "--chapters", *picked,
           "--per-chapter-dir", per_chapter_dir,
           "--out", out]
    _cmd_opt(cmd, "--plan", plan)
    cmd += _backend_args(backend, model, request, endpoints=endpoints)
    _cmd_opt(cmd, "--chapter-parallel", chapter_parallel)
    _cmd_opt(cmd, "--chunk-parallel", chunk_parallel)
    _cmd_flag(cmd, "--no-speculative", no_speculative)
    return _run_locked("extract", cmd)


@router.get("/run/bundle")
def run_bundle(
    request: Request,
    corpus: str = "",
    aliases: str = "",
    known_names: list[str] = Query(default=[]),
    min_facts: int | None = None,
    known_only: bool = False,
    out_dir: str = "",
    list: bool = False,
    endpoints: list[str] = Query(default=[]),
    model: str = "",
    backend: str = "",
    entity_parallel: int | None = None,
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    cfg = service.resolved()
    corpus = corpus or cfg.paths.corpus_glob
    out_dir = out_dir or cfg.paths.state_dossiers_dir
    aliases = aliases or cfg.aliases_path or ""
    known_names = known_names or cfg.known_names
    backend = backend or cfg.extract.backend
    model = model or cfg.extract.model or ""
    endpoints = endpoints or cfg.extract.endpoints
    if min_facts is None:
        min_facts = cfg.tuning.bundle_min_facts
    if entity_parallel is None:
        entity_parallel = cfg.tuning.entity_parallel

    cmd = [console_script("facts_to_state"), "--corpus", corpus]
    # A campaign that has migrated to docs/entity_registry.yaml supersedes the
    # UI's persisted legacy aliases/known-names fields (Principle: single
    # source of truth for aliases). Passing both trips facts_to_state.py's
    # deprecation guard and permanently disables its own auto-discovery.
    registry_path = find_registry(Path.cwd())
    if registry_path is not None:
        _cmd_opt(cmd, "--registry", str(registry_path))
    else:
        _cmd_opt(cmd, "--aliases", aliases)
        _cmd_multi(cmd, "--known-names", known_names)
    _cmd_opt(cmd, "--min-facts", min_facts)
    if list:
        cmd.append("--list")
    else:
        _cmd_opt(cmd, "--out-dir", out_dir)
        _cmd_flag(cmd, "--known-only", known_only)
        cmd += _backend_args(backend, model, request, endpoints=endpoints)
        _cmd_opt(cmd, "--entity-parallel", entity_parallel)
    # --list does no model work, so it never needs the lock or backend env.
    if list:
        return _run_locked("bundle-list", cmd)
    return _run_locked("bundle", cmd)


@router.get("/run/recent-events")
def run_recent_events(
    corpus: str = "",
    output: str = "",
    window: int | None = None,
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    cfg = service.resolved()
    corpus = corpus or cfg.paths.corpus_glob
    output = output or cfg.paths.recent_events_out
    if window is None:
        window = cfg.tuning.recent_events_window
    cmd = [console_script("build_recent_events"),
           "--corpus", corpus, "--output", output, "--window", str(window)]
    return _run_locked("recent-events", cmd)


@router.get("/run/threads")
def run_threads(
    corpus: str = "",
    aliases: str = "",
    output: str = "",
    min_facts: int | None = None,
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    """(M1) Deterministic threads-track render — the chronological-spine input
    fed to synthesis. No model call."""
    cfg = service.resolved()
    corpus = corpus or cfg.paths.corpus_glob
    output = output or cfg.paths.threads_out
    aliases = aliases or cfg.aliases_path or ""
    if min_facts is None:
        min_facts = cfg.tuning.threads_min_facts
    cmd = [console_script("facts_to_state"),
           "--corpus", corpus, "--types", "thread",
           "--min-facts", str(min_facts), "--render-only", output]
    registry_path = find_registry(Path.cwd())
    if registry_path is not None:
        _cmd_opt(cmd, "--registry", str(registry_path))
    else:
        _cmd_opt(cmd, "--aliases", aliases)
    return _run_locked("threads", cmd)


@router.get("/run/synthesize")
def run_synthesize(
    request: Request,
    doc: str,
    output: str = "",
    backend: str = "",
    endpoint: str = "",
    model: str = "",
    # world_state
    dossiers: str = "",
    dossier_min_facts: int | None = None,
    # party.yaml — anchors the Party section for world_state, and is the
    # preferred (human-authored) source for the party doc's own synthesis.
    # Falls back to the conventional config/party.yaml / party.yaml path
    # when left blank.
    party: str = "",
    threads: str = "",
    backstories: list[str] = Query(default=[]),
    # campaign_state / party (staging)
    extract_dir: str = "",
    synthesize_only: bool = True,
    # planning
    planning_config: str = "",
    planning_mode: str = "",
    npc: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
    depth: str = "",
    force_include: list[str] = Query(default=[]),
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    if doc not in GROUNDING_DOCS:
        raise HTTPException(status_code=400, detail=f"unknown doc '{doc}'")

    cfg = service.resolved()
    dossiers = dossiers or cfg.paths.dossiers_glob
    backend = backend or cfg.synthesize.backend
    model = model or cfg.synthesize.model or ""
    endpoint = endpoint or (cfg.synthesize.endpoints[0] if cfg.synthesize.endpoints else "")
    if dossier_min_facts is None:
        dossier_min_facts = cfg.tuning.dossier_min_facts
    planning_mode = planning_mode or cfg.planning.synth_mode
    depth = depth or cfg.planning.depth
    npc = npc or cfg.planning.npc
    arc_scores = arc_scores or cfg.planning.arc_scores
    context = context or cfg.planning.context
    force_include = force_include or cfg.planning.force_include
    out = output or GROUNDING_DOCS[doc][1]  # default to the draft path
    # FR-013: never let synthesis target a live grounding doc.
    if _is_live_doc(_resolve_ensemble_path(out)):
        raise HTTPException(status_code=400,
                            detail="synthesis output must be a draft, not a live doc")

    if doc == "world_state":
        cmd = [console_script("synthesise_world_state"),
               "--dossiers", dossiers, "--dossier-min-facts", str(dossier_min_facts),
               "--output", out]
        _cmd_opt(cmd, "--party", party)
        # Auto-detect the threads track the same way planning_config /
        # party_config auto-detect — an explicit --threads override still wins.
        threads_path = _resolve_ensemble_path(threads) if threads else _default_threads_file(cfg.paths.threads_out)
        _cmd_opt(cmd, "--threads", threads_path)
        _cmd_multi(cmd, "--backstories", backstories)
    elif doc == "campaign_state":
        cmd = [console_script("campaign_state"), "--output", out]
        _cmd_flag(cmd, "--synthesize-only", synthesize_only)
        _cmd_opt(cmd, "--extract-dir", extract_dir)
    elif doc == "party":
        cmd = [console_script("party"), "--output", out]
        # Which dossiers/sheets belong to which PC is campaign-specific and
        # already a human decision once party.yaml exists — reuse it instead
        # of guessing. party.py's own "characters-only" path (no --summaries,
        # no --synthesize-only) then needs neither --extract-dir nor staged
        # extract_*.md files.
        party_config_path = (
            _resolve_ensemble_path(party) if party else _default_party_config()
        )
        if party_config_path:
            _cmd_opt(cmd, "--party-config", str(party_config_path))
            # Characters-only mode has no session extracts, so without context
            # docs it correctly reports current location/quests/reputation as
            # absent — feed it world_state/campaign_state so it doesn't have to.
            party_context = context or _default_party_context()
            _cmd_multi(cmd, "--context", party_context)
        else:
            _cmd_flag(cmd, "--synthesize-only", synthesize_only)
            _cmd_opt(cmd, "--extract-dir", extract_dir)
    else:  # planning
        cmd = [console_script("planning"), "--output", out]
        # The tracked (arc-scored) NPC/faction subset is a human-curated
        # decision (docs/cli/ensemble_workflow.md §3e) — reuse the
        # already-curated planning.yaml the same way the party branch reuses
        # party.yaml, instead of guessing at it. "flat" is an explicit UI
        # override ("Explicit dossier list") to skip planning.yaml outright —
        # e.g. no config exists yet, or the one on disk is a stale/unfilled
        # template (empty npcs:/factions: raises in load_planning_config).
        # Honor that choice rather than auto-detecting underneath it.
        planning_config_path = (
            None if planning_mode == "flat" else
            _resolve_ensemble_path(planning_config) if planning_config
            else _default_planning_config()
        )
        # Ensemble extraction captures every named entity, PCs included, so
        # the merged_dossiers/ glob below has an npc_<pc>.md right next to
        # every real NPC. Excluding those is opt-in and explicit — only
        # dossiers bound via party.yaml's `dossier:` field are excluded, and
        # only when the caller didn't pass an explicit --npc list of their
        # own (see _party_pc_dossier_files).
        party_config_path = (
            _resolve_ensemble_path(party) if party else _default_party_config()
        )
        pc_dossiers, pc_warning = _party_pc_dossier_files(party_config_path)
        if planning_config_path:
            _cmd_opt(cmd, "--planning-config", str(planning_config_path))
            # planning.py rejects --planning-config + --arc-scores; --npc
            # extras are allowed (pass-through dossiers for trackless NPCs).
            # planning.yaml's own npcs: list is only the arc-scored minority
            # (planning.py's docstring calls --npc pass-through "the
            # majority") — without this, every NPC not in planning.yaml is
            # silently absent from planning.md.
            try:
                npc_passthrough = npc or _planning_npc_passthrough(planning_config_path, cfg.paths.npc_dossiers_glob, exclude=pc_dossiers)
            except ValueError as e:
                # load_planning_config raises on a missing/invalid dossier
                # reference — surface it as a real SSE error (below) instead
                # of an unhandled 500, which the frontend's EventSource can't
                # distinguish from a dropped connection.
                return _sse_error_response(f"planning config error: {e}")
            _cmd_multi(cmd, "--npc", npc_passthrough)
        else:
            _cmd_multi(cmd, "--npc", npc or _all_planning_npc_files(cfg.paths.npc_dossiers_glob, exclude=pc_dossiers))
            _cmd_multi(cmd, "--arc-scores", arc_scores)
        _cmd_multi(cmd, "--context", context)
        # Same auto-detect as the world_state branch: without this, Active
        # Plots has nothing but scattered NPC-dossier snapshots to infer
        # threads from, and the model has to guess chapter ordering.
        threads_path = _resolve_ensemble_path(threads) if threads else _default_threads_file(cfg.paths.threads_out)
        _cmd_opt(cmd, "--threads", threads_path)
        # "scene" is planning.py --depth's own default — only pass it through
        # when overridden so the reproducible command stays minimal.
        if depth and depth != "scene":
            _cmd_opt(cmd, "--depth", depth)
        _cmd_multi(cmd, "--force-include", force_include)

    cmd += _backend_args(backend, model, request, endpoint=endpoint)

    prelude_parts = []
    # Surface auto-detected party.yaml / context so picking them up isn't
    # silent — the caller didn't ask for them explicitly.
    if doc == "party" and party_config_path:
        detected = []
        if not party:
            detected.append(f"party config: {party_config_path}")
        if not context and party_context:
            detected.append(f"context: {', '.join(party_context)}")
        if detected:
            prelude_parts.append(f"Auto-detected — {'; '.join(detected)}\n\n")
    if doc == "planning" and planning_config_path:
        detected = []
        if not planning_config:
            detected.append(f"planning config: {planning_config_path}")
        if not npc and npc_passthrough:
            detected.append(f"{len(npc_passthrough)} pass-through NPC dossier(s)")
        if detected:
            prelude_parts.append(f"Auto-detected — {'; '.join(detected)}\n\n")
    if doc == "planning" and not npc and pc_dossiers:
        prelude_parts.append(
            f"Auto-detected — {len(pc_dossiers)} PC dossier(s) excluded "
            f"(bound in {party_config_path.name})\n\n")
    if doc == "planning" and pc_warning:
        prelude_parts.append(f"⚠️  {pc_warning}\n\n")
    if doc in ("world_state", "planning") and not threads and threads_path:
        prelude_parts.append(f"Auto-detected — threads track: {threads_path}\n\n")
    # FR-014 / R6: warn (don't block) on a sub-Sonnet synthesis model.
    if backend != "anthropic" and model and model not in SYNTHESIS_CAPABLE:
        prelude_parts.append(
            f"⚠️  '{model}' is not on the synthesis-capable list — synthesis "
            f"assumes a model at least as capable as Sonnet; output quality may "
            f"degrade. Proceeding anyway.\n\n")
    prelude = "".join(prelude_parts)
    return _run_locked(f"synthesize-{doc}", cmd, prelude=prelude)


# ── Resolved-selection preview (feature 003, FR-012) ───────────────────────


@router.get("/selection/resolved")
def get_ensemble_resolved_selection(
    request: Request,
    stage: str = "extract",
    service: EnsembleConfigService = Depends(get_ensemble_service),
):
    """What a run of ``stage`` would use, and where each half came from.

    Per-stage because ensemble's selection is: the canonical workflow runs
    extract on DGX and synthesize on Anthropic within one campaign, so a
    single answer for "the ensemble" would be wrong for one of them.
    """
    cfg = service.resolved()
    stage_cfg = getattr(cfg, stage, None) or cfg.extract
    return resolve_selection(
        request,
        service=ModelSelection(backend=stage_cfg.backend or None,
                               model=stage_cfg.model or None),
        service_name="ensemble",
        raise_on_incompatible=False,
    ).as_dict()
