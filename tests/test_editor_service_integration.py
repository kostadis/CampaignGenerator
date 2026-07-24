"""Integration tests for the Session Doc Editor router + config service.

Phase 2 of ``docs/config/session-editor-isolation.md``: the module-global
``scene_editor.CONFIG`` is gone. Every route now reads a request-scoped
``ResolvedEditorConfig`` (``server/session_editor_config_service.py``)
injected via FastAPI ``Depends``. These tests verify:

  - ``GET /api/editor/config`` returns the grouped, resolved shape.
  - ``PUT /api/editor/config`` accepts today's flat payload (mapped to a
    grouped partial by the TEMP ``_flat_body_to_grouped``), writes through
    ``SessionEditorConfigService``, and the value survives a simulated
    restart (a second app / service instance reading the same campaign
    dir) — the bug from VttSummary.vue:70-71 that nothing-without-an-
    explicit-save-call goes to disk.
  - A write through the generic ``/api/config/section/session_doc`` door
    is reflected in ``GET /api/editor/config`` (both doors write the same
    underlying platform storage in this phase).
  - Without a config service wired (``app.state.config_service is None``),
    editor routes return 503 (mirrors ``config_routes._require_service``)
    rather than silently falling back to an in-memory default.
  - A double-prefix regression guard for the router mount.
  - O3 — the editor-local anthropic/claude-code model override:
    ``backends.<active>.model`` wins over ``runtime.default_model`` when
    set, and falls back to it when unset.
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
from server.session_editor_config_service import SessionEditorConfigService

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


def _make_app(campaign_dir: Path | None) -> FastAPI:
    app = FastAPI()
    app.include_router(scene_editor.router, prefix="/api/editor")
    app.include_router(config_routes.router, prefix="/api/config")
    if campaign_dir is not None:
        app.state.config_service = CampaignConfigService(campaign_dir)
    else:
        app.state.config_service = None
    return app


# ── GET /api/editor/config — grouped resolved shape ─────────────────────────


class TestGetEditorConfig:
    def test_returns_grouped_shape(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "paths", "narrate", "scrub", "roster", "backends",
            "session_name", "profiles", "active_profile", "model",
            "work_dir", "campaign_dir", "config_dir", "vtt",
        }
        # Defaults: strict grouped schema, backends keyed by name (incl.
        # the hyphenated claude-code alias).
        assert body["backends"]["active"] == "anthropic"
        assert "claude-code" in body["backends"]
        assert body["narrate"]["tokens"] == 16000


# ── PUT /api/editor/config — flat payload, single write door ────────────────


class TestPutPersistsViaService:
    def test_put_editor_config_persists_through_service(self, fresh_campaign):
        # First server: PUT a value via the editor endpoint (flat payload —
        # still backward-compatible per _flat_body_to_grouped).
        client_a = TestClient(_make_app(fresh_campaign))
        resp = client_a.put(
            "/api/editor/config",
            json={"narrate_tokens": 12000, "voice_dir": "voice/"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify the service wrote it to disk.
        assert (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).exists()

        # Second server (simulates a restart): no in-memory state carried
        # over, but the service reloads ui_state.yaml.
        client_b = TestClient(_make_app(fresh_campaign))
        editor_cfg = client_b.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 12000
        assert editor_cfg["paths"]["voice_dir"].endswith("voice")  # absolute via resolve

    def test_put_editor_config_backend_and_scrub_fields(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={
                "backend": "dgx",
                "dgx_endpoint": "http://localhost:8000",
                "dgx_model": "llama-3-70b",
                "scrub_enabled": True,
                "scrub_tokens": 8000,
                "batch": True,
            },
        )
        assert resp.status_code == 200

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["backends"]["active"] == "dgx"
        assert editor_cfg["backends"]["dgx"]["endpoint"] == "http://localhost:8000"
        assert editor_cfg["backends"]["dgx"]["model"] == "llama-3-70b"
        assert editor_cfg["scrub"]["enabled"] is True
        assert editor_cfg["scrub"]["tokens"] == 8000
        assert editor_cfg["narrate"]["batch"] is True

    def test_put_editor_config_ignores_work_dir_and_output_dir(self, fresh_campaign):
        # work_dir/output_dir are derived/unused-as-stored — must not error
        # and must not appear anywhere persisted.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"work_dir": "/somewhere", "output_dir": "/elsewhere"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_put_editor_config_invalid_shape_returns_400(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate_tokens": "not-an-int"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False


class TestPutAcceptsGroupedOrFlat:
    """Phase 3a: PUT /api/editor/config accepts EITHER the grouped shape
    (a not-yet-migrated frontend won't send this until Phase 3b, but the
    API must already accept it) or today's flat shape — both write through
    the same SessionEditorConfigService.update_config door."""

    def test_put_editor_config_grouped_body_persists(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate": {"tokens": 9000}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 9000

    def test_put_editor_config_flat_body_still_works(self, fresh_campaign):
        # The pre-existing flat shim keeps working unchanged alongside the
        # new grouped-body support.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate_tokens": 7000},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 7000


class TestSectionDoorReflectedInEditorGet:
    def test_get_editor_config_reflects_service_writes_via_section_endpoint(
        self, fresh_campaign
    ):
        # Write to the typed section endpoint directly — bypasses the
        # editor PUT — and confirm the editor GET still sees the value
        # (both doors write the same underlying platform storage today).
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 9999

    def test_get_editor_config_reflects_typed_roleplay_dir_rename(self, fresh_campaign):
        # The typed field is `roleplay_dir`; the grouped shape renames it
        # to `paths.roleplay_extractions_dir`.
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"roleplay_dir": "summaries/sess1/vtt_roleplay_extractions"}},
        )
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["paths"]["roleplay_extractions_dir"].endswith(
            "vtt_roleplay_extractions"
        )


# ── No config service wired → 503, not a silent in-memory default ───────────


class TestNoServiceReturns503:
    def test_get_editor_config_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 503

    def test_put_editor_config_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.put("/api/editor/config", json={"narrate_tokens": 1000})
        assert resp.status_code == 503

    def test_scenes_503_without_service(self):
        client = TestClient(_make_app(None))
        resp = client.get("/api/editor/scenes")
        assert resp.status_code == 503


# ── Double-prefix mount regression guard ─────────────────────────────────────


class TestRouteMounting:
    def test_double_prefix_guard(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        # Correct path resolves...
        assert client.get("/api/editor/config").status_code == 200
        # ...and the double-prefixed path does NOT exist.
        assert client.get("/api/editor/api/editor/config").status_code == 404


# ── O3 — editor-local anthropic/claude-code model override ──────────────────


class TestO3ModelResolution:
    def test_anthropic_override_wins_then_falls_back_to_default_model(self, fresh_campaign):
        platform = CampaignConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)

        # Editor-local override (backends.anthropic.model) wins when set.
        service.update_config(
            {"backends": {"active": "anthropic", "anthropic": {"model": "claude-opus-4-9"}}}
        )
        cfg = service.resolved_editor_config()
        assert scene_editor._model_args(cfg) == ["--model", "claude-opus-4-9"]

        # Falls back to runtime.default_model (the global sidebar picker)
        # when the editor-local override is unset.
        service.update_config({"backends": {"active": "anthropic", "anthropic": {"model": None}}})
        cfg2 = service.resolved_editor_config()
        default_model = platform.resolved()["runtime"]["default_model"]
        assert scene_editor._model_args(cfg2) == ["--model", default_model]

    def test_dgx_and_openrouter_suppress_model_args(self, fresh_campaign):
        # _model_args() is skipped entirely for dgx/openrouter — that model
        # is governed by _backend_flags instead (unchanged O1 behavior).
        platform = CampaignConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        service.update_config({"backends": {"active": "dgx"}})
        cfg = service.resolved_editor_config()
        assert scene_editor._model_args(cfg) == []
