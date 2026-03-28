"""Grounding document API routes — campaign_state, distill, party, planning."""

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

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
    synthesize_only: bool = False,
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

    if chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
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
    synthesize_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "distill.py")]

    if not synthesize_only and input:
        cmd.append(input)

    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Party Document ──────────────────────────────────────────────────────────

@router.get("/run/party")
async def run_party(
    character: list[str] = Query(default=[]),
    summaries: str = "",
    backstory: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    synthesize_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "party.py")]

    _cmd_multi(cmd, "--character", character)
    _cmd_opt(cmd, "--summaries", summaries)
    _cmd_multi(cmd, "--backstory", backstory)
    _cmd_multi(cmd, "--arc-scores", arc_scores)
    _cmd_multi(cmd, "--context", context)
    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Planning Document ───────────────────────────────────────────────────────

@router.get("/run/planning")
async def run_planning(
    npc: list[str] = Query(default=[]),
    arc_scores: list[str] = Query(default=[]),
    summaries: str = "",
    context: list[str] = Query(default=[]),
    output: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    synthesize_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "planning.py")]

    _cmd_multi(cmd, "--npc", npc)
    _cmd_multi(cmd, "--arc-scores", arc_scores)
    _cmd_opt(cmd, "--summaries", summaries)
    _cmd_multi(cmd, "--context", context)
    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


@router.get("/run/build-dossiers")
async def run_build_dossiers(
    summaries: str = "",
    dossier_dir: str = "",
    extract_dir: str = "",
    chunk_size: int = 60000,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "planning.py")]

    _cmd_opt(cmd, "--summaries", summaries)
    cmd.append("--build-dossiers")
    _cmd_opt(cmd, "--dossier-dir", dossier_dir)
    _cmd_opt(cmd, "--extract-dir", extract_dir)

    if chunk_size and chunk_size != 60000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)
