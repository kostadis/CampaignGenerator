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

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from campaignlib.registry import find_registry
from server.subprocess_runner import python_exe, stream_subprocess, sse_error_stream

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/

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
SYNTHESIS_CAPABLE = {
    "claude-sonnet-4-6", "claude-sonnet-4-20250514",
    "claude-opus-4-8", "claude-opus-4-6", "claude-opus-4-7",
    "anthropic/claude-sonnet-4", "anthropic/claude-opus-4",
    "openai/gpt-5", "google/gemini-2.5-pro",
}


# ── Command-building helpers (mirror grounding.py) ──────────────────────────

def _cmd_opt(cmd: list[str], flag: str, value) -> None:
    if value:
        cmd += [flag, str(value)]


def _cmd_multi(cmd: list[str], flag: str, values: list[str]) -> None:
    for v in values or []:
        if v and v.strip():
            cmd += [flag, v.strip()]


def _cmd_nargs(cmd: list[str], flag: str, values: list[str]) -> None:
    """Emit ONE `flag v1 v2 ...` occurrence for an argparse nargs="+" flag
    (e.g. --endpoints). Unlike _cmd_multi (which repeats the flag once per
    value — correct for action="append" flags), nargs="+" keeps only the
    LAST occurrence's values if the flag is repeated, so every value must go
    into a single occurrence."""
    vs = [v.strip() for v in (values or []) if v and v.strip()]
    if vs:
        cmd += [flag, *vs]


def _cmd_flag(cmd: list[str], flag: str, condition: bool) -> None:
    if condition:
        cmd.append(flag)


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
    """Conventional party.yaml location (mirrors server/config.py's
    derive_campaign_paths) — used when the caller doesn't specify one."""
    cwd = Path.cwd()
    for rel in ("config/party.yaml", "party.yaml"):
        p = cwd / rel
        if p.exists():
            return p
    return None


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


# ── LLM backend selection → subprocess env (Principle V) ────────────────────

def _llm_env(backend: str, endpoints: list[str], model: str) -> dict[str, str]:
    """Translate a per-stage backend choice into env that campaignlib.make_client
    honors. The API key itself is inherited from the server env, never injected
    from a query param.
    """
    if backend == "openrouter":
        env = {"CG_BACKEND": "openrouter"}
        if model:
            env["OPENROUTER_MODEL"] = model
        return env
    if backend == "dgx":
        # DGX_ENDPOINT is only a fallback for when --endpoints isn't passed
        # on the CLI at all; the explicit flag (built below) always wins.
        env = {"DGX_ENDPOINT": (endpoints[0] if endpoints else "") or "http://localhost:8000"}
        if model:
            env["DGX_MODEL"] = model
        return env
    if backend == "claude-code":
        env = {"CG_BACKEND": "claude-code"}
        if model:
            env["CG_CLAUDE_CODE_MODEL"] = model
        return env
    return {}  # anthropic: default path, no overrides


# ── Per-stage in-flight lock (M4) ───────────────────────────────────────────
# Single-operator, local-first: an in-process guard is enough to stop a
# double-click or a second tab from launching two writers on the same workdir
# (the orphaned-worker cache-corruption trap in ensemble_workflow.md).

_RUNNING: set[str] = set()


def _lock_key(stage: str) -> str:
    return f"{Path.cwd().resolve()}::{stage}"


def _run_locked(stage: str, cmd: list[str], env_extra: dict[str, str] | None = None,
                prelude: str = "") -> StreamingResponse:
    key = _lock_key(stage)
    if key in _RUNNING:
        return StreamingResponse(
            sse_error_stream(f"stage '{stage}' is already running for this campaign — "
                             f"wait for it to finish (avoids corrupting the workdir)."),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
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


# ── Status (disk-derived, FR-002) ───────────────────────────────────────────

@router.get("/status")
def status(chapters: str = "docs/chapters/chapter_*.md"):
    """Pipeline state computed entirely from artifacts on disk — no caching."""
    cwd = Path.cwd()
    per_chapter = sorted(glob.glob(str(cwd / "docs/ensemble/per_chapter/*/merged.json")))
    dossiers = sorted(glob.glob(str(cwd / "docs/ensemble/state_dossiers/*.md")))
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
    glob: list[str] = Query(default=["docs/chapters/chapter_*.md"]),
    per_chapter_dir: str = "docs/ensemble/per_chapter",
):
    """Resolve one or more chapter globs/paths to the concrete file list the
    extraction stage would run over (FR: chapter selection). Each entry is
    flagged `extracted` when its per-chapter merged.json already exists on disk
    (Principle I — the picker reflects truth, not a cached selection)."""
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
    chapters: list[str] = Query(default=[]),
    per_chapter_dir: str = "docs/ensemble/per_chapter",
    out: str = "docs/ensemble/merged.json",
    plan: str = "",
    endpoints: list[str] = Query(default=[]),
    model: str = "",
    backend: str = "anthropic",
    chapter_parallel: int = 3,
    chunk_parallel: int = 4,
    no_speculative: bool = False,
):
    # Principle X: no silent "all". An empty selection is refused, never
    # expanded to the full glob — "Select all" must be an explicit choice the
    # caller makes (the UI sends every resolved path; a CLI user types a glob).
    picked = [c.strip() for c in (chapters or []) if c and c.strip()]
    if not picked:
        return StreamingResponse(
            sse_error_stream("No chapters selected — pick chapters (or click "
                             "'Select all') before running extraction."),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    cmd = [python_exe(), str(SCRIPT_DIR / "ensemble_batch.py"),
           "--chapters", *picked,
           "--per-chapter-dir", per_chapter_dir,
           "--out", out]
    _cmd_opt(cmd, "--plan", plan)
    if backend != "anthropic":
        _cmd_nargs(cmd, "--endpoints", endpoints)
        _cmd_opt(cmd, "--model", model)
    _cmd_opt(cmd, "--chapter-parallel", chapter_parallel)
    _cmd_opt(cmd, "--chunk-parallel", chunk_parallel)
    _cmd_flag(cmd, "--no-speculative", no_speculative)
    return _run_locked("extract", cmd, env_extra=_llm_env(backend, endpoints, model))


@router.get("/run/bundle")
def run_bundle(
    corpus: str = "docs/ensemble/per_chapter/*/merged.json",
    aliases: str = "",
    known_names: list[str] = Query(default=[]),
    min_facts: int = 3,
    known_only: bool = False,
    out_dir: str = "docs/ensemble/state_dossiers",
    list: bool = False,
    endpoints: list[str] = Query(default=[]),
    model: str = "",
    backend: str = "anthropic",
    entity_parallel: int = 0,
):
    cmd = [python_exe(), str(SCRIPT_DIR / "facts_to_state.py"), "--corpus", corpus]
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
        if backend != "anthropic":
            _cmd_nargs(cmd, "--endpoints", endpoints)
            _cmd_opt(cmd, "--model", model)
        _cmd_opt(cmd, "--entity-parallel", entity_parallel)
    # --list does no model work, so it never needs the lock or backend env.
    if list:
        return _run_locked("bundle-list", cmd)
    return _run_locked("bundle", cmd, env_extra=_llm_env(backend, endpoints, model))


@router.get("/run/recent-events")
def run_recent_events(
    corpus: str = "docs/ensemble/per_chapter/*/merged.json",
    output: str = "docs/recent_events.md",
    window: int = 0,
):
    cmd = [python_exe(), str(SCRIPT_DIR / "build_recent_events.py"),
           "--corpus", corpus, "--output", output, "--window", str(window)]
    return _run_locked("recent-events", cmd)


@router.get("/run/threads")
def run_threads(
    corpus: str = "docs/ensemble/per_chapter/*/merged.json",
    aliases: str = "",
    output: str = "docs/ensemble/threads.md",
    min_facts: int = 2,
):
    """(M1) Deterministic threads-track render — the chronological-spine input
    fed to synthesis. No model call."""
    cmd = [python_exe(), str(SCRIPT_DIR / "facts_to_state.py"),
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
    doc: str,
    output: str = "",
    backend: str = "anthropic",
    endpoint: str = "",
    model: str = "",
    # world_state
    dossiers: str = "docs/ensemble/merged_dossiers/*.md",
    dossier_min_facts: int = 10,
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
    npc: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
):
    if doc not in GROUNDING_DOCS:
        raise HTTPException(status_code=400, detail=f"unknown doc '{doc}'")
    out = output or GROUNDING_DOCS[doc][1]  # default to the draft path
    # FR-013: never let synthesis target a live grounding doc.
    if _is_live_doc(_resolve_ensemble_path(out)):
        raise HTTPException(status_code=400,
                            detail="synthesis output must be a draft, not a live doc")

    if doc == "world_state":
        cmd = [python_exe(), str(SCRIPT_DIR / "synthesise_world_state.py"),
               "--dossiers", dossiers, "--dossier-min-facts", str(dossier_min_facts),
               "--output", out]
        _cmd_opt(cmd, "--party", party)
        _cmd_opt(cmd, "--threads", threads)
        _cmd_multi(cmd, "--backstories", backstories)
    elif doc == "campaign_state":
        cmd = [python_exe(), str(SCRIPT_DIR / "campaign_state.py"), "--output", out]
        _cmd_flag(cmd, "--synthesize-only", synthesize_only)
        _cmd_opt(cmd, "--extract-dir", extract_dir)
    elif doc == "party":
        cmd = [python_exe(), str(SCRIPT_DIR / "party.py"), "--output", out]
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
        cmd = [python_exe(), str(SCRIPT_DIR / "planning.py"), "--output", out]
        _cmd_multi(cmd, "--npc", npc)
        _cmd_multi(cmd, "--arc-scores", arc_scores)
        _cmd_multi(cmd, "--context", context)

    if backend != "anthropic":
        cmd += ["--backend", backend]
        _cmd_opt(cmd, "--endpoint", endpoint)
        _cmd_opt(cmd, "--model", model)

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
    # FR-014 / R6: warn (don't block) on a sub-Sonnet synthesis model.
    if backend != "anthropic" and model and model not in SYNTHESIS_CAPABLE:
        prelude_parts.append(
            f"⚠️  '{model}' is not on the synthesis-capable list — synthesis "
            f"assumes a model at least as capable as Sonnet; output quality may "
            f"degrade. Proceeding anyway.\n\n")
    prelude = "".join(prelude_parts)
    return _run_locked(f"synthesize-{doc}", cmd,
                       env_extra=_llm_env(backend, [endpoint] if endpoint else [], model),
                       prelude=prelude)
