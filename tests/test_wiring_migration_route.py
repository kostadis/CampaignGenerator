"""The checkout Settings route delegates to the one-shot CLI."""

import asyncio

import pytest
from fastapi import HTTPException

from server.routers import config_routes


def test_default_target_comes_from_wiring_accessor(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config_routes.get_wiring_default() == {
        "path": str(tmp_path / ".config" / "campaigngenerator" / "wiring.yaml")
    }


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
