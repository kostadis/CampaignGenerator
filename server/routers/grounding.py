"""Grounding document API routes — campaign_state, distill, party, planning.

Run endpoints build their commands from ``<config>/grounding.yaml`` via
``GroundingConfigService`` (Phase 8 of ``docs/config/grounding-isolation.md``).
An explicit request parameter still wins over the stored value; what changed is
that omitting one now falls back to per-campaign config instead of a literal
baked into the route signature.
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.grounding_config_service import GroundingConfigService
from server.grounding_config_shared import DEFAULT_CHUNK_SIZE, GroundingConfig
from server.platform_config_service import resolve_selection, selection_cli_args
from server.subprocess_runner import console_script, stream_subprocess

router = APIRouter()


# ── Config (own document, own service) ──────────────────────────────────────

def _service(request: Request) -> GroundingConfigService:
    """Resolve the service for this request.

    Prefers the live platform's config dir; falls back to ``cwd/config`` like
    the ensemble router, so read-only routes work in contexts without a booted
    platform (see ``GroundingConfigService``'s module docstring).
    """
    platform = getattr(request.app.state, "platform", None)
    base = platform.config_path_base if platform else Path.cwd() / "config"
    return GroundingConfigService(base)


@router.get("/config")
def get_grounding_config(request: Request) -> GroundingConfig:
    return _service(request).get_config()


@router.put("/config")
async def put_grounding_config(request: Request) -> GroundingConfig:
    """Merge a grouped partial into ``grounding.yaml``.

    The body IS the partial (no ``{"values": …}`` envelope), matching
    ``PUT /api/ensemble/config``. An unknown key is a 400 — the schema is
    strict.
    """
    partial: Any = await request.json()
    if not isinstance(partial, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return _service(request).update_config(partial)


# ── LLM backend selection → subprocess CLI flags ────────────────────────────
# `_backend_flags` lived here until feature 003. It constructed a
# SessionEditorConfigService and read that service's `backends.active` — so
# Grounding runs took their backend from the Session Doc Editor's own config
# while taking their model from the platform tier. Two owners, one command:
# `cmd += ["--model", <platform>]` followed by `cmd += _backend_flags(...)`,
# which appended a SECOND `--model` from session_doc.yaml whenever the editor
# had one stored. argparse last-wins made that work by accident, and when the
# editor had none stored a claude-* id went to a DGX endpoint, where the
# adapter silently substituted its own default.
#
# Both halves now come from `resolve_selection` — one tier, one `--model`,
# and no reading of another service's document (contract guarantees C1/C4).
# Grounding's own override lands in grounding.yaml/party.yaml/planning.yaml
# in Phase 4; until then these endpoints inherit the platform selection,
# which is correct behaviour rather than a gap.

def _cmd_opt(cmd: list[str], flag: str, value: str | int | None) -> None:
    if value:
        cmd += [flag, str(value)]


def _pick(explicit: str | int | None, stored: str | int | None) -> Any:
    """Explicit request value wins; otherwise the stored config value.

    An empty string / 0 from a query param means "not supplied" — FastAPI
    gives those defaults when the caller omits the parameter entirely, so they
    cannot be distinguished from a deliberate blank. Treating them as "unset"
    is what makes the stored config reachable at all.
    """
    if explicit not in (None, "", 0):
        return explicit
    return stored


def _pick_list(explicit: list[str], stored: list[str]) -> list[str]:
    return explicit if explicit else list(stored)


def _chunking(cmd: list[str], split_chapters: str, chunk_size: int) -> None:
    """``--split-chapters`` and ``--chunk-size`` are mutually exclusive at the
    CLI; splitting wins when both are set. This was four copies of the same
    ``if/elif`` across the run endpoints."""
    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != DEFAULT_CHUNK_SIZE:
        cmd += ["--chunk-size", str(chunk_size)]


def _require_input(cfg: GroundingConfig, doc: str, explicit: str) -> str:
    """The run's input document: explicit → the doc's stored ``input`` → the
    shared ``summaries``.

    Refuses rather than guessing when none is set — the "no silent all"
    invariant ``ensemble.yaml``'s ``chapters_selected`` established.
    """
    value = (explicit or "").strip() or cfg.input_for(doc)
    if not value:
        raise HTTPException(
            status_code=400,
            detail=(
                f"no input for {doc}: pass ?input=, or set grounding.yaml's "
                f"{doc}.input or the shared summaries pointer"
            ),
        )
    return value


def _cmd_multi(cmd: list[str], flag: str, values: list[str]) -> None:
    for v in values:
        if v.strip():
            cmd += [flag, v.strip()]


def _cmd_flag(cmd: list[str], flag: str, condition: bool) -> None:
    if condition:
        cmd.append(flag)


def _sse_response(cmd: list[str]) -> StreamingResponse:
    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Campaign State ──────────────────────────────────────────────────────────

@router.get("/run/campaign-state")
async def run_campaign_state(
    request: Request,
    input: str = "",
    output: str = "",
    track_file: str = "",
    track_file_extra: list[str] = Query(default=[]),
    track: list[str] = Query(default=[]),
    extract_dir: str = "",
    chunk_size: int = 0,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str | None = None,
):
    cfg = _service(request).resolved()
    run = cfg.campaign_state
    cmd = [console_script("campaign_state")]

    if not synthesize_only:
        cmd.append(_require_input(cfg, "campaign_state", input))

    _cmd_opt(cmd, "--output", _pick(output, run.output))
    # track_file (singular) + track_file_extra (list) are one list in the
    # config; the CLI has always taken --track-file as action="append".
    _cmd_multi(
        cmd, "--track-file",
        _pick_list([t for t in [track_file, *track_file_extra] if t], run.track_files),
    )
    _cmd_multi(cmd, "--track", _pick_list(track, run.track_items))
    _cmd_opt(cmd, "--extract-dir", _pick(extract_dir, run.extract_dir))
    _chunking(cmd, _pick(split_chapters, run.split_chapters),
              _pick(chunk_size, run.chunk_size))

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log or run.no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── Distill World State ─────────────────────────────────────────────────────

@router.get("/run/distill")
async def run_distill(
    request: Request,
    input: str = "",
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 0,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str | None = None,
):
    cfg = _service(request).resolved()
    run = cfg.distill
    cmd = [console_script("distill")]

    if not synthesize_only:
        cmd.append(_require_input(cfg, "distill", input))

    _cmd_opt(cmd, "--output", _pick(output, run.output))
    _cmd_opt(cmd, "--extract-dir", _pick(extract_dir, run.extract_dir))
    _chunking(cmd, _pick(split_chapters, run.split_chapters),
              _pick(chunk_size, run.chunk_size))

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log or run.no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── Party Document ──────────────────────────────────────────────────────────

@router.get("/run/party")
async def run_party(
    request: Request,
    party_config: str = "",
    character: list[str] = Query(default=[]),
    summaries: str = "",
    backstory: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 0,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str | None = None,
):
    cfg = _service(request).resolved()
    run = cfg.party
    cmd = [console_script("party")]

    # config mode reads the roster from party.yaml (PartyConfigService's
    # document); flat mode passes per-file lists. The stored mode decides only
    # when the request supplies neither shape.
    cfg_path = _pick(party_config, run.config_path)
    use_config = bool(party_config) or (
        not character and run.mode == "config" and cfg_path
    )
    if use_config:
        _cmd_opt(cmd, "--party-config", cfg_path)
    else:
        _cmd_multi(cmd, "--character", _pick_list(character, run.characters))
        _cmd_multi(cmd, "--backstory", _pick_list(backstory, run.backstory))
        _cmd_multi(cmd, "--arc-scores", _pick_list(arc_scores, run.arc_scores))

    # --summaries is optional for party (characters-only mode is legitimate),
    # so unlike the other three this one does not go through _require_input.
    _cmd_opt(cmd, "--summaries",
             (summaries or "").strip() or cfg.input_for("party") or "")
    _cmd_multi(cmd, "--context", _pick_list(context, run.context))
    _cmd_opt(cmd, "--output", _pick(output, run.output))
    _cmd_opt(cmd, "--extract-dir", _pick(extract_dir, run.extract_dir))
    _chunking(cmd, _pick(split_chapters, run.split_chapters),
              _pick(chunk_size, run.chunk_size))

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log or run.no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── Planning Document ───────────────────────────────────────────────────────

@router.get("/run/planning")
async def run_planning(
    request: Request,
    planning_config: str = "",
    npc: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    summaries: str = "",
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 0,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str | None = None,
):
    cfg = _service(request).resolved()
    run = cfg.planning
    cmd = [console_script("planning")]

    cfg_path = _pick(planning_config, run.config_path)
    use_config = bool(planning_config) or (
        not npc and run.synth_mode == "config" and cfg_path
    )
    if use_config:
        _cmd_opt(cmd, "--planning-config", cfg_path)
        # planning.py rejects --planning-config + --arc-scores; --npc extras
        # are allowed (pass-through dossiers for trackless NPCs).
        _cmd_multi(cmd, "--npc", _pick_list(npc, run.npc))
    else:
        _cmd_multi(cmd, "--npc", _pick_list(npc, run.npc))
        _cmd_multi(cmd, "--arc-scores", _pick_list(arc_scores, run.arc_scores))

    _cmd_opt(cmd, "--summaries",
             (summaries or "").strip() or cfg.input_for("planning") or "")
    _cmd_multi(cmd, "--context", _pick_list(context, run.context))
    _cmd_opt(cmd, "--output", _pick(output, run.output))
    _cmd_opt(cmd, "--extract-dir", _pick(extract_dir, run.extract_dir))
    _chunking(cmd, _pick(split_chapters, run.split_chapters),
              _pick(chunk_size, run.chunk_size))

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log or run.no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


@router.get("/run/build-dossiers")
async def run_build_dossiers(
    request: Request,
    summaries: str = "",
    dossier_dir: str = "",
    extract_dir: str = "",
    chunk_size: int = 0,
    split_chapters: str = "",
    since: int = 0,
    extract_only: bool = False,
    no_log: bool = False,
    model: str | None = None,
):
    cfg = _service(request).resolved()
    build = cfg.planning.dossiers
    cmd = [console_script("planning")]

    _cmd_opt(cmd, "--summaries",
             (summaries or "").strip() or build.summaries
             or (cfg.summaries or "").strip() or "")
    cmd.append("--build-dossiers")
    _cmd_opt(cmd, "--dossier-dir", _pick(dossier_dir, build.dossier_dir))
    _cmd_opt(cmd, "--extract-dir", _pick(extract_dir, build.extract_dir))
    _chunking(cmd, _pick(split_chapters, build.split_chapters),
              _pick(chunk_size, cfg.planning.chunk_size))

    effective_since = _pick(since, build.since) or 0
    if effective_since > 0:
        cmd += ["--since", str(effective_since)]

    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log or cfg.planning.no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── Extraction file review (two-phase checkpoint) ───────────────────────────
# Used by the UI between the extract and synthesize passes: list the cached
# extracts, read one for preview/edit, write an edited version back. The CLI
# already writes these files — these endpoints just expose them to the browser
# so the human review loop can happen without dropping to a terminal.

def _resolve_extract_dir(extract_dir: str) -> Path:
    if not extract_dir:
        raise HTTPException(status_code=400, detail="extract_dir is required")
    p = Path(extract_dir).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return p


@router.get("/extracts")
def list_extracts(extract_dir: str):
    """List cached extract_*.md / dossier_extract_*.md files in a dir."""
    d = _resolve_extract_dir(extract_dir)
    if not d.exists():
        return {"extract_dir": str(d), "exists": False, "files": []}
    files = sorted(
        f.name for f in d.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name.startswith(("extract_", "dossier_extract_"))
    )
    return {
        "extract_dir": str(d),
        "exists": True,
        "files": [
            {"name": name, "size": (d / name).stat().st_size}
            for name in files
        ],
    }


@router.get("/extracts/{filename}")
def read_extract(filename: str, extract_dir: str):
    d = _resolve_extract_dir(extract_dir)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")
    path = d / filename
    if not path.exists() or not path.is_file():
        return JSONResponse({"exists": False, "content": ""}, status_code=404)
    return {"exists": True, "content": path.read_text(encoding="utf-8")}


@router.put("/extracts/{filename}")
async def write_extract(filename: str, extract_dir: str, request: Request):
    d = _resolve_extract_dir(extract_dir)
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not d.exists():
        raise HTTPException(status_code=404, detail="extract_dir does not exist")
    path = d / filename
    data = await request.json()
    path.write_text(data.get("content", ""), encoding="utf-8")
    return {"ok": True, "size": path.stat().st_size}
