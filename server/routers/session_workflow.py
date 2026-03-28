"""Session workflow API routes — VTT summary and scene extraction subprocess streaming."""

import sys
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from server.config import load_ui_config
from server.subprocess_runner import python_exe, stream_subprocess

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent  # CampaignGenerator/


def _resolve_session_path(path_str: str, session_dir: str) -> str:
    """Resolve a relative path against session_dir if set."""
    if not path_str.strip():
        return path_str
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return path_str
    if session_dir.strip():
        return str(Path(session_dir).expanduser() / p)
    return path_str


def _cmd_opt(cmd: list[str], flag: str, value: str | int | None) -> None:
    if value:
        cmd += [flag, str(value)]


def _cmd_multi(cmd: list[str], flag: str, values: list[str]) -> None:
    if values:
        for v in values:
            if v.strip():
                cmd += [flag, v.strip()]


def _cmd_flag(cmd: list[str], flag: str, condition: bool) -> None:
    if condition:
        cmd.append(flag)


# ── VTT Summary ─────────────────────────────────────────────────────────────

@router.get("/run/vtt-summary")
async def run_vtt_summary(
    session_dir: str = "",
    vtt_input: str = "",
    output: str = "",
    roleplay_output: str = "",
    date: str = "",
    session_name: str = "",
    context: list[str] = Query(default=[]),
    reference_summaries: list[str] = Query(default=[]),
    extract_dir: str = "",
    chunk_size: int = 50000,
    synthesize_only: bool = False,
    no_log: bool = False,
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "vtt_summary.py")]

    if not synthesize_only and vtt_input:
        cmd.append(vtt_input)

    _cmd_opt(cmd, "--output", _resolve_session_path(output, session_dir))
    _cmd_opt(cmd, "--date", date.strip())
    _cmd_opt(cmd, "--session-name", session_name.strip())
    _cmd_opt(cmd, "--roleplay-output", _resolve_session_path(roleplay_output, session_dir))

    for ctx in context:
        if ctx.strip():
            cmd += ["--context", ctx.strip()]

    for ref in reference_summaries:
        if ref.strip():
            cmd += ["--reference-summaries", ref.strip()]

    resolved_extract_dir = _resolve_session_path(extract_dir, session_dir)
    _cmd_opt(cmd, "--extract-dir", resolved_extract_dir)

    if chunk_size and chunk_size != 50000:
        cmd += ["--chunk-size", str(chunk_size)]

    _cmd_flag(cmd, "--synthesize-only", synthesize_only)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += ["--model", model]

    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Scene Extraction ─────────────────────────────────────────────────────────

@router.get("/run/scene-extraction")
async def run_scene_extraction(
    session: str = "",
    roleplay_dir: str = "",
    extract_dir: str = "",
    summary_dir: str = "",
    session_summary: str = "",
    roleplay_summary: str = "",
    characters: str = "",
    party: str = "",
    voice_dir: str = "",
    examples_dir: str = "",
    campaign_state: str = "",
    world_state: str = "",
    context: list[str] = Query(default=[]),
    session_name: str = "",
    model: str = "claude-sonnet-4-6",
):
    cmd = [
        python_exe(), str(SCRIPT_DIR / "session_doc.py"),
        session,
        "--roleplay-extract-dir", roleplay_dir,
        "--by-scene",
        "--extract-dir", extract_dir,
        "--extract-only",
        "--output", "/dev/null",
        "--model", model,
    ]

    _cmd_opt(cmd, "--summary-extract-dir", summary_dir)
    _cmd_opt(cmd, "--session-summary", session_summary)
    _cmd_opt(cmd, "--roleplay-summary", roleplay_summary)
    _cmd_opt(cmd, "--characters", characters.strip())
    _cmd_opt(cmd, "--party", party)
    _cmd_opt(cmd, "--voice-dir", voice_dir)
    _cmd_opt(cmd, "--examples", examples_dir)

    # Context files: campaign_state + world_state + extras
    for ctx in [campaign_state, world_state] + list(context):
        if ctx and ctx.strip():
            cmd += ["--context", ctx.strip()]

    _cmd_opt(cmd, "--session-name", session_name.strip())

    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
