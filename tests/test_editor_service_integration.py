"""Integration test for step D — editor + ledger driven by the unified service.

Verifies:
  - ``PUT /api/editor/config`` writes through the service so values
    survive a server restart (the bug from VttSummary.vue:70-71 that
    nothing-without-an-explicit-save-call goes to disk).
  - The router-level ``_refresh_config_from_service`` dependency keeps
    the legacy ``CONFIG`` dict in sync with the service's resolved view
    on every request, including field-name translation
    (``roleplay_dir`` → ``roleplay_extract_dir``, etc.).
  - The legacy boot path (no service wired) still works unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_service import (
    CampaignConfigService,
    TRACKED_CONFIG_NAME,
    UI_STATE_NAME,
)
from server.routers import config_routes, scene_editor

# Service reads/writes its documents under <campaign>/<config_dir>/ (config_dir="config").
CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    _write(
        tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


@pytest.fixture(autouse=True)
def reset_editor_config_module_state():
    # The editor's CONFIG is a module-level dict shared across tests; reset
    # it before each test so leftovers from a previous test don't leak.
    scene_editor.CONFIG.clear()
    yield
    scene_editor.CONFIG.clear()


def _make_app(campaign_dir: Path | None) -> FastAPI:
    app = FastAPI()
    app.include_router(scene_editor.router, prefix="/api/editor")
    app.include_router(config_routes.router, prefix="/api/config")
    if campaign_dir is not None:
        app.state.config_service = CampaignConfigService(campaign_dir)
    else:
        app.state.config_service = None
    return app


class TestPutPersistsViaService:
    def test_put_editor_config_persists_through_service(self, fresh_campaign):
        # First server: PUT a value via the editor endpoint.
        client_a = TestClient(_make_app(fresh_campaign))
        resp = client_a.put(
            "/api/editor/config",
            json={"narrate_tokens": 12000, "voice_dir": "voice/"},
        )
        assert resp.status_code == 200

        # Verify the service wrote it to disk.
        assert (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).exists()

        # Second server (simulates a restart): no in-memory state carried
        # over, but the service reloads ui_state.yaml.
        scene_editor.CONFIG.clear()
        client_b = TestClient(_make_app(fresh_campaign))
        editor_cfg = client_b.get("/api/editor/config").json()
        assert editor_cfg["narrate_tokens"] == 12000
        assert editor_cfg["voice_dir"].endswith("voice")  # absolute via resolve

    def test_field_name_translation_into_legacy_keys(self, fresh_campaign):
        # The service stores ``roleplay_dir`` (typed) but the legacy CONFIG
        # dict and helpers expect ``roleplay_extract_dir``. The refresh
        # dependency translates.
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/editor/config",
            json={"roleplay_extract_dir": "summaries/sess1/vtt_roleplay_extractions"},
        )
        editor_cfg = client.get("/api/editor/config").json()
        # Read back via the editor endpoint — surfaces under the legacy key.
        assert "roleplay_extract_dir" in editor_cfg


class TestLegacyBootPathStillWorks:
    def test_no_service_uses_init_editor_config_seed(self):
        # Simulate the legacy boot path: no campaign_dir, no service.
        # init_editor_config seeds CONFIG; PUT updates it; GET reads it.
        scene_editor.init_editor_config({"narrate_tokens": 5000})

        client = TestClient(_make_app(None))
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate_tokens"] == 5000

        # PUT works without a service — just updates CONFIG locally.
        resp = client.put("/api/editor/config", json={"narrate_tokens": 7000})
        assert resp.status_code == 200
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate_tokens"] == 7000


class TestRefreshOverlaysServiceState:
    def test_get_editor_config_reflects_service_writes_via_section_endpoint(
        self, fresh_campaign
    ):
        # Write to the typed section endpoint directly — bypasses the
        # editor PUT — and confirm the editor GET still sees the value
        # via the refresh dependency.
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate_tokens"] == 9999
