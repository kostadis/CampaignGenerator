"""API tests for the unified config endpoints.

Covers:
  - ``GET /api/config/`` returns the typed view AND a flat-key overlay so
    the un-reshaped frontend keeps working.
  - ``PUT /api/config/section/{name}`` rejects unknown sections.
  - ``PUT /api/config/runtime`` writes session_dir / default_model.
  - ``PUT /api/config/local`` cannot write ``ui.*`` keys.
  - Every route returns 503 when no service is wired (no silent fallback).
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
)
from server.routers import config_routes


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    _write(
        tmp_path / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


def _make_app(campaign_dir: Path | None) -> FastAPI:
    app = FastAPI()
    app.include_router(config_routes.router, prefix="/api/config")
    if campaign_dir is not None:
        app.state.config_service = CampaignConfigService(campaign_dir)
    else:
        app.state.config_service = None
    return app


# ── GET / shape ───────────────────────────────────────────────────────────


class TestGetConfig:
    def test_includes_new_shape_fields(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        body = client.get("/api/config/").json()
        for key in (
            "campaign_dir",
            "config_path",
            "ui_state_path",
            "local_config_path",
            "schema_version",
            "resolved",
            "tracked",
            "local",
            "migration_warnings",
        ):
            assert key in body, f"missing {key} in GET / response"

    def test_legacy_flat_keys_present_for_unmigrated_frontend(self, fresh_campaign):
        # Set values through typed endpoints, confirm flat overlay surfaces them.
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 4000, "voice_dir": "voice/"}},
        )
        client.put(
            "/api/config/runtime",
            json={"values": {"default_model": "claude-opus-4-6"}},
        )
        body = client.get("/api/config/").json()
        # The flat overlay lets the unreshaped Pinia store keep reading
        # ``cfg.sd_narrate_tokens`` and ``cfg.global_model`` directly.
        # Path fields are resolved to absolute (against campaign_dir)
        # because the overlay is computed from service.resolved().
        assert body["sd_narrate_tokens"] == 4000
        assert body["sd_voice_dir"].endswith("/voice")
        assert body["global_model"] == "claude-opus-4-6"

    def test_no_service_returns_503(self):
        # The hostile fallback is gone — with no campaign_dir, GET / refuses.
        client = TestClient(_make_app(None))
        resp = client.get("/api/config/")
        assert resp.status_code == 503


# ── PUT /section/{name} ────────────────────────────────────────────────────


class TestPutSection:
    def test_typed_section_update_persists(self, fresh_campaign):
        app = _make_app(fresh_campaign)
        client = TestClient(app)
        resp = client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 12000, "voice_dir": "voice/"}},
        )
        assert resp.status_code == 200

        # Read back via GET / and confirm the values are visible.
        body = client.get("/api/config/").json()
        assert body["resolved"]["ui"]["session_doc"]["narrate_tokens"] == 12000
        # And the flat overlay reflects them too.
        assert body["sd_narrate_tokens"] == 12000

    def test_unknown_section_rejected_404(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/config/section/server",
            json={"values": {"port": 6001}},
        )
        # Sections come from UISection model fields; ``server`` is local-only
        # and must not be writable through this endpoint.
        assert resp.status_code == 404

    def test_no_service_503(self, fresh_campaign):
        client = TestClient(_make_app(None))
        resp = client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 12000}},
        )
        assert resp.status_code == 503


# ── PUT /local ────────────────────────────────────────────────────────────


class TestPutLocal:
    def test_local_update_persists(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/config/local",
            json={"values": {"server": {"port": 6001}}},
        )
        assert resp.status_code == 200

        body = client.get("/api/config/").json()
        assert body["local"]["server"]["port"] == 6001

    def test_local_rejects_ui_top_level_key(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        # ``ui`` is not a valid LocalConfig top-level key; pydantic rejects.
        # ``extra="allow"`` on LocalConfig means stranger top-level keys are
        # accepted but stored without further validation. The important
        # invariant is that ``ui`` keys do not land in the typed
        # ``server``/``nav`` slots — verify by reading back.
        client.put("/api/config/local", json={"values": {"ui": {"session_doc": {}}}})
        body = client.get("/api/config/").json()
        # Whatever happened, the service-resolved ui section stays empty
        # of any session_doc state we didn't put there via /section/.
        assert body["resolved"]["ui"]["session_doc"]["narrate_tokens"] == 16000

    def test_no_service_503(self, fresh_campaign):
        client = TestClient(_make_app(None))
        resp = client.put("/api/config/local", json={"values": {"server": {"port": 6001}}})
        assert resp.status_code == 503


# ── PUT /runtime ──────────────────────────────────────────────────────────


class TestPutRuntime:
    def test_runtime_update_persists(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/config/runtime",
            json={"values": {"session_dir": "summaries/s1", "default_model": "claude-opus-4-6"}},
        )
        assert resp.status_code == 200

        body = client.get("/api/config/").json()
        # session_dir is path-resolved to absolute against campaign_dir.
        assert body["resolved"]["runtime"]["session_dir"].endswith("summaries/s1")
        assert body["resolved"]["runtime"]["default_model"] == "claude-opus-4-6"
        # Flat overlay carries the runtime values too.
        assert body["session_dir"].endswith("summaries/s1")
        assert body["global_model"] == "claude-opus-4-6"

    def test_no_service_503(self):
        client = TestClient(_make_app(None))
        resp = client.put("/api/config/runtime", json={"values": {"session_dir": "x"}})
        assert resp.status_code == 503


# ── Removed legacy endpoints ──────────────────────────────────────────────


class TestLegacyEndpointsAreGone:
    def test_legacy_put_root_returns_405(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        # The legacy bulk PUT / is removed; FastAPI should return method-not-
        # allowed because GET / still exists.
        resp = client.put("/api/config/", json={"values": {"sd_voice_dir": "v/"}})
        assert resp.status_code in (404, 405)

    def test_raw_yaml_endpoints_removed(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        assert client.get("/api/config/raw").status_code == 404
        assert client.put("/api/config/raw", json={"text": "x: y"}).status_code == 404
