"""Experimental API routes — enhance recap, session narrative."""

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent


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


# ── Enhance Recap ───────────────────────────────────────────────────────────

@router.get("/run/enhance-recap")
async def run_enhance_recap(
    recap: str = "",
    output: str = "",
    roleplay_extract_dir: str = "",
    summary_extract_dir: str = "",
    context: list[str] = Query(default=[]),
    party: str = "",
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "enhance_recap.py")]

    if recap.strip():
        cmd.append(recap.strip())

    _cmd_opt(cmd, "--output", output)
    _cmd_opt(cmd, "--roleplay-extract-dir", roleplay_extract_dir)
    _cmd_opt(cmd, "--summary-extract-dir", summary_extract_dir)
    _cmd_multi(cmd, "--context", context)
    _cmd_opt(cmd, "--party", party)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Session Narrative ───────────────────────────────────────────────────────

@router.get("/run/narrative")
async def run_narrative(
    roleplay_extract_dir: str = "",
    summary_extract_dir: str = "",
    examples: list[str] = Query(default=[]),
    roleplay: str = "",
    summary: str = "",
    party: str = "",
    characters: str = "",
    session_name: str = "",
    voice_dir: str = "",
    output: str = "",
    plan_only: bool = False,
    fast: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "narrative.py")]

    _cmd_opt(cmd, "--roleplay-extract-dir", roleplay_extract_dir)
    _cmd_opt(cmd, "--summary-extract-dir", summary_extract_dir)
    _cmd_multi(cmd, "--examples", examples)
    _cmd_opt(cmd, "--roleplay", roleplay)
    _cmd_opt(cmd, "--summary", summary)
    _cmd_opt(cmd, "--party", party)
    _cmd_opt(cmd, "--characters", characters.strip())
    _cmd_opt(cmd, "--session-name", session_name.strip())
    _cmd_opt(cmd, "--voice-dir", voice_dir)
    _cmd_opt(cmd, "--output", output)
    _cmd_flag(cmd, "--plan-only", plan_only)
    _cmd_flag(cmd, "--fast", fast)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return _sse_response(cmd)
