"""Setup API routes — D&D sheet conversion, make tracking list."""

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from server.subprocess_runner import python_exe, stream_subprocess

router = APIRouter()

SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent


def _cmd_opt(cmd: list[str], flag: str, value: str | int | None) -> None:
    if value:
        cmd += [flag, str(value)]


def _sse_response(cmd: list[str]) -> StreamingResponse:
    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── D&D Sheet → Markdown ───────────────────────────────────────────────────

@router.get("/run/dnd-sheet")
async def run_dnd_sheet(
    pdfs: list[str] = Query(default=[]),
    output: str = "",
    output_dir: str = "",
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "dnd_sheet.py")]

    for pdf in pdfs:
        if pdf.strip():
            cmd.append(pdf.strip())

    # --output for single PDF, --output-dir for multiple
    if len(pdfs) == 1 and output.strip():
        cmd += ["--output", output.strip()]
    elif output_dir.strip():
        cmd += ["--output-dir", output_dir.strip()]

    cmd += ["--model", model]

    return _sse_response(cmd)


# ── Make Tracking List ──────────────────────────────────────────────────────

@router.get("/run/make-tracking")
async def run_make_tracking(
    input: str = "",
    output: str = "",
    model: str = "claude-sonnet-4-6",
):
    cmd = [python_exe(), str(SCRIPT_DIR / "make_tracking.py")]

    if input.strip():
        cmd.append(input.strip())

    _cmd_opt(cmd, "--output", output)
    cmd += ["--model", model]

    return _sse_response(cmd)
