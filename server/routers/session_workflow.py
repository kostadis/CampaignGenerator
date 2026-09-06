"""Thin session workflow adapter: all behavior runs in the CLI subprocess."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from server.subprocess_runner import BoundedJSONError, console_script, run_bounded_json, stream_subprocess
from session_doc.workflow.cli import OPERATIONS

router = APIRouter()


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    session_dir: str = Field(min_length=1)
    config: str | None = None
    expected_revision: int | None = None
    payload: dict = Field(default_factory=dict)


def _build_workflow_cmd(body: WorkflowRequest) -> list[str]:
    if body.operation not in OPERATIONS:
        raise ValueError("unsupported session workflow operation")
    command = [console_script("session_workflow"), body.operation, "--campaign-dir", ".", "--session-dir", body.session_dir, "--json", "--request-json", json.dumps(body.payload)]
    if body.config is not None:
        command += ["--config", body.config]
    if body.expected_revision is not None:
        command += ["--expected-revision", str(body.expected_revision)]
    return command


@router.post("/command")
async def command(request: Request, body: WorkflowRequest):
    service = getattr(request.app.state, "platform", None)
    if service is None:
        raise HTTPException(400, "campaign configuration is unavailable")
    campaign = Path(service.campaign_dir).resolve(strict=True)
    try:
        session = (campaign / body.session_dir).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(400, "selected session directory does not exist") from exc
    if session == campaign or not session.is_relative_to(campaign) or not session.is_dir():
        raise HTTPException(403, "session must be a directory within the selected campaign")
    if body.config and not (campaign / body.config).resolve().is_relative_to(campaign):
        raise HTTPException(403, "configuration must belong to this campaign")
    if body.operation == "execute":
        return StreamingResponse(stream_subprocess(_build_workflow_cmd(body), cwd=str(campaign), save_run_log=False), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        return await run_bounded_json(_build_workflow_cmd(body), cwd=str(campaign), timeout_seconds=30, max_output_bytes=8 * 1024 * 1024)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except BoundedJSONError as exc:
        raise HTTPException(409 if exc.returncode == 2 else 500, str(exc)) from exc
