"""Setup API routes — D&D sheet conversion, make tracking list.

An *inheriting* service (feature 003): Setup owns no config document — there
is no ``SetupConfigService`` and no ``setup.yaml`` — so it always runs on the
platform selection and has no override of its own. This is deliberate; the
scope decision in ``specs/003-model-selection-resolution/spec.md`` keeps
config away from services that were purposely left stateless (D1).

Like ``prep.py`` and ``connections.py``, these two emitted no ``--backend``
before 003 and so ignored the sidebar toggle entirely.
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


def _sse_response(cmd: list[str]) -> StreamingResponse:
    return StreamingResponse(
        stream_subprocess(cmd, cwd=str(Path.cwd())),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── D&D Sheet → Markdown ───────────────────────────────────────────────────

@router.get("/run/dnd-sheet")
async def run_dnd_sheet(
    request: Request,
    pdfs: list[str] = Query(default=[]),
    output: str = "",
    output_dir: str = "",
    model: str | None = None,
):
    # Same defect class as the twelve request-body defaults Phase 5a fixed,
    # just wearing a constant instead of a bareword literal — so a
    # "claude-sonnet-4-6" grep never surfaced it. Defaulting to
    # DEFAULT_MODEL here meant an omitted `model` silently took the module
    # constant rather than the operator's persisted runtime.default_model.
    selection = resolve_selection(request, request_model=model)
    cmd = [console_script("dnd_sheet")]

    for pdf in pdfs:
        if pdf.strip():
            cmd.append(pdf.strip())

    # --output for single PDF, --output-dir for multiple
    if len(pdfs) == 1 and output.strip():
        cmd += ["--output", output.strip()]
    elif output_dir.strip():
        cmd += ["--output-dir", output_dir.strip()]

    cmd += selection_cli_args(selection)

    return _sse_response(cmd)


# ── Make Tracking List ──────────────────────────────────────────────────────

@router.get("/run/make-tracking")
async def run_make_tracking(
    request: Request,
    input: str = "",
    output: str = "",
    model: str | None = None,
):
    # See run_dnd_sheet above — same constant-shaped instance of the
    # omitted-model defect.
    selection = resolve_selection(request, request_model=model)
    cmd = [console_script("make_tracking")]

    if input.strip():
        cmd.append(input.strip())

    _cmd_opt(cmd, "--output", output)
    cmd += selection_cli_args(selection)

    return _sse_response(cmd)
