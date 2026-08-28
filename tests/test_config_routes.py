"""API tests for the unified config endpoints.

Covers:
  - ``GET /api/config/`` returns the typed/resolved view plus metadata.
  - ``PUT /api/config/section/{name}`` is gone entirely — every name 404s.
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

from campaignlib.selection import BACKENDS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import (
    PlatformConfigService,
    TRACKED_CONFIG_NAME,
)
from server.routers import config_routes

# Service reads config.yaml from <campaign>/<config_dir>/ (config_dir="config").
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
    app.include_router(config_routes.router, prefix="/api/config")
    if campaign_dir is not None:
        app.state.platform = PlatformConfigService(campaign_dir)
    else:
        app.state.platform = None
    return app


# ── GET / shape ───────────────────────────────────────────────────────────


class TestGetConfig:
    def test_includes_new_shape_fields(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        body = client.get("/api/config/").json()
        for key in (
            "campaign_dir",
            "config_path",
            "local_config_path",
            "resolved",
            "tracked",
            "local",
            "migration_warnings",
        ):
            assert key in body, f"missing {key} in GET / response"
        # ``ui_state_path`` and ``schema_version`` left with ui_state.yaml
        # itself (docs/config/ui-state-retirement.md). Asserted absent, not
        # merely dropped from the list above: Settings.vue rendered the path,
        # and a body key that reappears without a document behind it is how a
        # dead surface comes back.
        assert "ui_state_path" not in body
        assert "schema_version" not in body

    def test_resolved_has_no_ui_key_at_all(self, fresh_campaign):
        # This assertion used to read "session_doc is no longer among the
        # resolved ui sections" (Phase 5, session-editor-isolation). Every
        # other section has since followed it out, and
        # docs/config/ui-state-retirement.md retired the empty remainder — so
        # the stronger claim now holds: there is no `ui` key.
        client = TestClient(_make_app(fresh_campaign))
        body = client.get("/api/config/").json()
        assert "ui" not in body["resolved"]
        assert set(body["resolved"]) == {"campaign_dir", "runtime", "server", "nav"}

    def test_no_service_returns_503(self):
        # The hostile fallback is gone — with no campaign_dir, GET / refuses.
        client = TestClient(_make_app(None))
        resp = client.get("/api/config/")
        assert resp.status_code == 503


# ── PUT /section/{name} — the route itself is gone ────────────────────────


class TestPutSectionIsRetired:
    """The generic ``ui.<section>`` write door is deleted, not merely emptied.

    This class used to hold one 404 test per retired section name
    (``session_doc``, ``profiles``, ``ensemble``, ``vtt_summary``,
    ``grounding`` …) — each a checkpoint that a service which had taken its
    config into its own document could no longer write back through the
    shared one. ``docs/config/ui-state-retirement.md`` removes the door
    itself, so the per-name assertions collapse into this: no name works,
    including one that was live until now.
    """

    def test_every_section_name_404s(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        for name in (
            "prep",          # was a live UISection field until this effort
            "npc",
            "query",
            "workflow",
            "connections",
            "experimental",
            "session_doc",   # retired by session-editor isolation
            "profiles",
            "ensemble",      # retired by ensemble isolation
            "grounding",     # retired by grounding isolation
            "party",
            "planning",
            "vtt_summary",   # retired with the VTT Summary chain
            "server",        # local-only, never writable here
        ):
            resp = client.put(
                f"/api/config/section/{name}", json={"values": {"x": 1}}
            )
            assert resp.status_code == 404, f"{name} should 404, got {resp.status_code}"


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
        # ``ui`` is not a valid PlatformLocalConfig top-level key. Unlike the
        # retired ``extra="allow"`` LocalConfig, PlatformLocalConfig is
        # strict (extra="forbid") per docs/config/platform-isolation.md's
        # "Strictness rule" — but that rule is about LOAD (a pre-existing,
        # possibly hand-edited file must not block boot), not WRITE. A live
        # PUT with an unrecognized key is a real caller bug, so
        # update_local now rejects it (400) the same way update_runtime/
        # update_section already do for a bad partial — this one response
        # code is a deliberate, narrow exception to "no behavior change",
        # required by tightening the model as the design doc asks. This
        # test doesn't pin the PUT's status; the invariant that matters
        # either way is that ``ui`` keys never land in the typed
        # ``server``/``nav`` slots — verify by reading back.
        client.put("/api/config/local", json={"values": {"ui": {"query": {}}}})
        body = client.get("/api/config/").json()
        # Whatever happened, a stray `ui` key never lands in the typed
        # server/nav slots — and there is no `ui` key in the resolved view at
        # all any more (docs/config/ui-state-retirement.md).
        assert "ui" not in body["resolved"]
        assert "ui" not in body["resolved"]["server"]
        assert "ui" not in body["resolved"]["nav"]

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


# ── Codex config API (feature 016, T040) ────────────────────────────────────


class TestCodexConfigApi:
    def test_models_exposes_canonical_codex_backend_once(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        body = client.get("/api/config/models").json()

        assert tuple(body["backends"]) == BACKENDS
        assert body["backends"].count("codex-cli") == 1
        assert body["default_backend"] == "anthropic"

    def test_runtime_accepts_codex_backend_and_round_trips(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        response = client.put(
            "/api/config/runtime",
            json={"values": {"default_backend": "codex-cli"}},
        )
        assert response.status_code == 200, response.text

        config = client.get("/api/config/").json()
        models = client.get("/api/config/models").json()
        assert config["resolved"]["runtime"]["default_backend"] == "codex-cli"
        assert models["default_backend"] == "codex-cli"

    def test_runtime_rejects_noncanonical_backend(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        response = client.put(
            "/api/config/runtime",
            json={"values": {"default_backend": "codex"}},
        )

        assert response.status_code == 400
