"""The checkout Settings route delegates to the one-shot CLI."""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from server.routers import config_routes
from server.main import app, limit_migration_mode


def test_default_target_comes_from_wiring_accessor(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MNEME_WIRING", raising=False)
    assert config_routes.get_wiring_default() == {
        "path": str(tmp_path / ".config" / "campaigngenerator" / "wiring.yaml")
    }
    selected = tmp_path / "shared" / "wiring.yaml"
    monkeypatch.setenv("MNEME_WIRING", str(selected))
    assert config_routes.get_wiring_default() == {"path": str(selected)}


def test_route_forwards_only_selected_cli_arguments(monkeypatch):
    seen = []

    async def fake_run(cmd):
        seen.append(cmd)
        return {"returncode": 0, "output": "Moved external wiring"}

    monkeypatch.setattr(config_routes, "run_command_capture", fake_run)
    result = asyncio.run(config_routes.migrate_wiring_route(
        config_routes.WiringMigrationRequest(
            source_checkout="/old/checkout", target="/new/wiring.yaml", force=True
        )
    ))
    assert result == {"returncode": 0, "output": "Moved external wiring"}
    assert seen == [[
        config_routes.python_exe(), "-m", "server.migrate_wiring",
        "--source-checkout", "/old/checkout", "--target", "/new/wiring.yaml", "--force",
    ]]


def test_route_refuses_empty_source(monkeypatch):
    async def forbidden(_cmd):
        pytest.fail("empty source reached subprocess")

    monkeypatch.setattr(config_routes, "run_command_capture", forbidden)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(config_routes.migrate_wiring_route(
            config_routes.WiringMigrationRequest(source_checkout=" ")
        ))
    assert exc.value.status_code == 400


def test_migration_only_server_exposes_form_api_but_no_campaign_api(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEME_WIRING", str(tmp_path / "selected.yaml"))
    app.state.migration_only = True

    async def next_handler(_request):
        return JSONResponse({"ok": True})

    def request(path, method="GET"):
        return Request({"type": "http", "method": method, "path": path,
                        "raw_path": path.encode(), "query_string": b"",
                        "headers": [], "scheme": "http", "server": ("localhost", 80)})

    try:
        assert config_routes.get_wiring_default() == {"path": str(tmp_path / "selected.yaml")}
        allowed = asyncio.run(limit_migration_mode(
            request("/api/config/wiring/default"), next_handler
        ))
        assert allowed.status_code == 200
        allowed_post = asyncio.run(limit_migration_mode(
            request("/api/config/wiring/migrate", "POST"), next_handler
        ))
        assert allowed_post.status_code == 200
        refused = asyncio.run(limit_migration_mode(request("/api/config/"), next_handler))
        assert refused.status_code == 503
        assert refused.body == b'{"detail":"migration-only mode"}'
    finally:
        app.state.migration_only = False
