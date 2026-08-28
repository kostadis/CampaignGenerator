"""HTTP integrations that stream external synchronization jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from server.platform_config_service import resolve_selection, selection_cli_args
from server.subprocess_runner import console_script, sse_error_stream, stream_subprocess

router = APIRouter()


def _text(body: dict[str, Any], key: str) -> str:
    """Return a trimmed request value, treating non-strings as omitted."""
    value = body.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _option(command: list[str], flag: str, value: Any) -> None:
    if isinstance(value, str):
        value = value.strip()
    if value:
        command.extend([flag, str(value)])


def _response(stream) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/scabard")
async def run_scabard(request: Request):
    """Run Scabard synchronization with its key confined to child env."""
    body = await request.json()
    access_key = _text(body, "access_key")
    if not access_key:
        return _response(
            sse_error_stream("Scabard access key is required in the request body.")
        )

    campaign_id = body.get("campaign_id")
    username = _text(body, "username")
    if campaign_id is None or not username:
        return _response(
            sse_error_stream("Scabard campaign_id and username are required.")
        )

    command = [
        console_script("scabard_sync"),
        "--campaign-id",
        str(campaign_id),
        "--username",
        username,
    ]
    selection = resolve_selection(
        request,
        request_backend=_text(body, "backend") or None,
        request_model=_text(body, "model") or None,
        service_name="scabard",
    )
    command.extend(selection_cli_args(selection))
    for key, flag in (
        ("world_state", "--world-state"),
        ("campaign_state", "--campaign-state"),
        ("party", "--party"),
        ("extract_file", "--extract-file"),
        ("from_extract", "--from-extract"),
        ("manifest", "--manifest"),
    ):
        _option(command, flag, body.get(key))
    for key, flag in (("extract_only", "--extract-only"), ("dry_run", "--dry-run")):
        if body.get(key):
            command.append(flag)

    # The key is intentionally absent from command, output, and diagnostics.
    # subprocess_runner redacts the value before it reaches SSE or disk logs.
    return _response(
        stream_subprocess(
            command,
            cwd=str(Path.cwd()),
            env_extra={"SCABARD_ACCESS_KEY": access_key},
        )
    )
