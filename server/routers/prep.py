"""Prep API routes — session prep, NPC table, query summaries.

These three are *inheriting* services (feature 003): they own no config
document, so they always run on the platform selection and have no override
of their own. Until 003 they also emitted no ``--backend`` at all — picking
DGX or OpenRouter in the sidebar left every one of them billing the metered
Anthropic API, silently. ``selection_cli_args`` now emits both halves.
"""

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from server.platform_config_service import resolve_selection, selection_cli_args
from server.subprocess_runner import console_script, stream_subprocess

router = APIRouter()


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


# ── Session Prep ────────────────────────────────────────────────────────────

@router.get("/run/session-prep")
async def run_session_prep(
    request: Request,
    input_mode: str = "beat",
    beat: str = "",
    session_file: str = "",
    session_text: str = "",
    prep_mode: str = "single",
    config: str = "",
    output: str = "",
    no_log: bool = False,
    model: str | None = None,
):
    cmd = [console_script("prep")]
    cmd += ["--mode", prep_mode]

    if input_mode == "beat" and beat.strip():
        cmd += ["--beat", beat.strip()]
    elif input_mode == "session_file" and session_file.strip():
        cmd += ["--session", session_file.strip()]
    elif input_mode == "session_text" and session_text.strip():
        cmd += ["--session-text", session_text.strip()]

    _cmd_opt(cmd, "--config", config)
    _cmd_opt(cmd, "--output", output)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── NPC Table ───────────────────────────────────────────────────────────────

@router.get("/run/npc-table")
async def run_npc_table(
    request: Request,
    docs: list[str] = Query(default=["world_state"]),
    config: str = "",
    output: str = "",
    no_log: bool = False,
    model: str | None = None,
):
    cmd = [console_script("npc_table")]

    doc_list = [d.strip() for d in docs if d.strip()]
    if doc_list:
        cmd += ["--docs"] + doc_list

    _cmd_opt(cmd, "--config", config)
    _cmd_opt(cmd, "--output", output)
    _cmd_flag(cmd, "--no-log", no_log)
    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)


# ── Query Summaries ─────────────────────────────────────────────────────────

@router.get("/run/query")
async def run_query(
    request: Request,
    input: str = "",
    query: str = "",
    hits_only: bool = False,
    verbose: bool = False,
    output: str = "",
    chunk_size: int = 40000,
    model: str | None = None,
):
    cmd = [console_script("query")]

    if input.strip():
        cmd.append(input.strip())
    if query.strip():
        cmd.append(query.strip())

    _cmd_flag(cmd, "--hits-only", hits_only)
    _cmd_flag(cmd, "--verbose", verbose)
    _cmd_opt(cmd, "--output", output)

    if chunk_size and chunk_size != 40000:
        cmd += ["--chunk-size", str(chunk_size)]

    cmd += selection_cli_args(resolve_selection(request, request_model=model))

    return _sse_response(cmd)
