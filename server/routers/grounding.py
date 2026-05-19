"""Grounding document API routes — campaign_state, distill, party, planning."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/


def _cmd_opt(cmd: list[str], flag: str, value: str | int | None) -> None:
    if value:
        cmd += [flag, str(value)]


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
    input: str = "",
    output: str = "",
    track_file: str = "",
    track: list[str] = Query(default=[]),
    extract_dir: str = "",
    chunk_size: int = 60000,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "campaign_state.py")]

    if not synthesize_only and input:
        cmd.append(input)

    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--track-file", track_file)
    _cmd_multi(cmd, "--track", track)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Distill World State ─────────────────────────────────────────────────────

@router.get("/run/distill")
async def run_distill(
    input: str = "",
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "distill.py")]

    if not synthesize_only and input:
        cmd.append(input)

    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Party Document ──────────────────────────────────────────────────────────

@router.get("/run/party")
async def run_party(
    party_config: str = "",
    character: list[str] = Query(default=[]),
    summaries: str = "",
    backstory: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "party.py")]

    if party_config:
        _cmd_opt(cmd, "--party-config", party_config)
    else:
        _cmd_multi(cmd, "--character", character)
        _cmd_multi(cmd, "--backstory", backstory)
        _cmd_multi(cmd, "--arc-scores", arc_scores)
    _cmd_opt(cmd, "--summaries", summaries)
    _cmd_multi(cmd, "--context", context)
    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Planning Document ───────────────────────────────────────────────────────

@router.get("/run/planning")
async def run_planning(
    planning_config: str = "",
    npc: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    summaries: str = "",
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    split_chapters: str = "",
    synthesize_only: bool = False,
    extract_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "planning.py")]

    if planning_config:
        _cmd_opt(cmd, "--planning-config", planning_config)
        # planning.py rejects --planning-config + --arc-scores; --npc extras
        # are allowed (pass-through dossiers for trackless NPCs).
        _cmd_multi(cmd, "--npc", npc)
    else:
        _cmd_multi(cmd, "--npc", npc)
        _cmd_multi(cmd, "--arc-scores", arc_scores)
    _cmd_opt(cmd, "--summaries", summaries)
    _cmd_multi(cmd, "--context", context)
    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


@router.get("/run/build-dossiers")
async def run_build_dossiers(
    summaries: str = "",
    dossier_dir: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    split_chapters: str = "",
    since: int = 0,
    extract_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "planning.py")]

    _cmd_opt(cmd, "--summaries", summaries)
    cmd.append("--build-dossiers")
    _cmd_opt(cmd, "--dossier-dir", dossier_dir)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if split_chapters:
        cmd += ["--split-chapters", split_chapters]
    elif chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    if since > 0:
        cmd += ["--since", str(since)]

    _cmd_flag(cmd, "--extract-only", extract_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

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
