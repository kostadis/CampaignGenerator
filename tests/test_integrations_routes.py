"""Contract tests for the Scabard integration HTTP face (feature 016).

The integration is deliberately tested without Scabard credentials or a live
network.  The route must receive the key in JSON, pass it only as a child
environment override, and stream the normal subprocess output/artifact path.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent
SECRET = "scabard-super-secret-016"


def _integrations_module():
    try:
        return importlib.import_module("server.routers.integrations")
    except ModuleNotFoundError as exc:
        pytest.fail(
            "Scabard integration router is not implemented: "
            "server/routers/integrations.py is required"
        )
        raise AssertionError from exc


def _scabard_route(module):
    routes = [
        route
        for route in module.router.routes
        if "scabard" in route.path.lower()
        and "POST" in (route.methods or set())
    ]
    if not routes:
        pytest.fail("integration router must mount a POST Scabard route")
    return routes[0]


def _payload(tmp_path: Path) -> dict[str, object]:
    return {
        "campaign_id": 121,
        "username": "kostadis",
        "access_key": SECRET,
        "world_state": str(tmp_path / "world_state.md"),
        "campaign_state": str(tmp_path / "campaign_state.md"),
        "party": str(tmp_path / "party.md"),
        "extract_only": True,
        "extract_file": str(tmp_path / "exports" / "entities.json"),
        "backend": "codex-cli",
        "model": "gpt-5-codex",
    }


def test_scabard_router_is_mounted_in_application():
    source = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
    assert "integrations" in source
    assert "/api/integrations" in source
    module = _integrations_module()
    assert _scabard_route(module)


def test_route_contract_reads_body_key_and_uses_child_only_environment():
    module = _integrations_module()
    source = (REPO_ROOT / "server" / "routers" / "integrations.py").read_text(
        encoding="utf-8"
    )
    assert "request.json" in source
    assert "SCABARD_ACCESS_KEY" in source
    assert "env_extra" in source
    # Manual CLI use retains --access-key, but the server route must never
    # place the request-body secret in its child argv.
    assert '"--access-key"' not in source
    assert _scabard_route(module)


def test_scabard_route_forwards_output_and_redacts_key_from_argv(
    monkeypatch, tmp_path
):
    module = _integrations_module()
    captured: dict[str, object] = {}

    async def fake_stream(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        yield "event: command\ndata: \\\"scabard_sync\\\"\n\n"
        yield 'event: done\ndata: {"returncode": 0}\n\n'

    monkeypatch.setattr(module, "stream_subprocess", fake_stream)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/integrations")
    route_path = _scabard_route(module).path

    world_state = tmp_path / "world_state.md"
    world_state.write_text("A quiet campaign.", encoding="utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/api/integrations" + route_path,
            json=_payload(tmp_path),
        )

    assert response.status_code == 200, response.text
    assert SECRET not in json.dumps(captured.get("cmd", []))
    assert captured["kwargs"]["env_extra"] == {
        "SCABARD_ACCESS_KEY": SECRET
    }
    cmd = captured["cmd"]
    assert "--extract-file" in cmd
    assert str(tmp_path / "exports" / "entities.json") in cmd
    assert "--backend" in cmd
    assert "codex-cli" in cmd
    assert "--model" in cmd
    assert "gpt-5-codex" in cmd


class _DirectRequest:
    def __init__(self, body: dict[str, object], backend: str, model: str):
        self._body = body
        self.app = SimpleNamespace(
            state=SimpleNamespace(
                platform=SimpleNamespace(
                    runtime=SimpleNamespace(
                        default_backend=backend,
                        default_model=model,
                        default_batch=False,
                    )
                )
            )
        )

    async def json(self):
        return self._body


def test_route_omits_inherited_claude_model_for_codex(monkeypatch):
    module = _integrations_module()
    captured: dict[str, object] = {}

    async def fake_stream(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        yield "event: done\ndata: {\"returncode\": 0}\n\n"

    monkeypatch.setattr(module, "stream_subprocess", fake_stream)
    request = _DirectRequest(
        {"campaign_id": 121, "username": "u", "access_key": SECRET},
        "codex-cli",
        "claude-sonnet-4-6",
    )
    response = asyncio.run(module.run_scabard(request))
    asyncio.run(_collect(response.body_iterator))

    command = captured["cmd"]
    assert "--backend" in command and "codex-cli" in command
    assert "--model" not in command
    assert captured["kwargs"]["env_extra"] == {"SCABARD_ACCESS_KEY": SECRET}


def test_route_refuses_explicit_claude_model_for_codex():
    module = _integrations_module()
    request = _DirectRequest(
        {
            "campaign_id": 121,
            "username": "u",
            "access_key": SECRET,
            "backend": "codex-cli",
            "model": "claude-sonnet-4-6",
        },
        "anthropic",
        "claude-sonnet-4-6",
    )
    with pytest.raises(Exception, match="valid model"):
        asyncio.run(module.run_scabard(request))


async def _collect(generator):
    return [chunk async for chunk in generator]


@pytest.mark.parametrize("returncode", [0, 1])
def test_subprocess_diagnostics_redact_scabard_override(
    tmp_path, returncode
):
    """Command events, child output, and persisted logs never expose the key."""
    from server.subprocess_runner import stream_subprocess

    code = (
        "import os, sys; "
        "print(os.environ.get('SCABARD_ACCESS_KEY', ''), file=sys.stderr); "
        f"sys.exit({returncode})"
    )
    events = asyncio.run(
        _collect(
            stream_subprocess(
                ["python", "-c", code],
                cwd=str(tmp_path),
                env_extra={"SCABARD_ACCESS_KEY": SECRET},
            )
        )
    )
    rendered = "".join(events)
    assert SECRET not in rendered
    logs = list((tmp_path / "logs").glob("*.md"))
    assert logs
    assert SECRET not in logs[0].read_text(encoding="utf-8")
