"""Integration tests for the Session Doc Editor router + config service.

Phase 5 of ``docs/config/session-editor-isolation.md``: storage is a
dedicated ``<config>/session_doc.yaml`` the service owns exclusively — an
editor write never touches ``ui_state.yaml``. Phase 3b's single write door
(the flat-body compat shim is gone; the router just forwards the request
body to ``SessionEditorConfigService.update_config``) and Phase 2's
module-global ``scene_editor.CONFIG`` removal still hold: every route reads
a request-scoped ``ResolvedEditorConfig``
(``server/session_editor_config_service.py``) injected via FastAPI
``Depends``. These tests verify:

  - ``GET /api/editor/config`` returns the grouped, resolved shape.
  - ``PUT /api/editor/config`` accepts a grouped partial, writes through
    ``SessionEditorConfigService`` to ``session_doc.yaml`` (NOT
    ``ui_state.yaml``), and the value survives a simulated restart (a
    second app / service instance reading the same campaign dir) — the bug
    from VttSummary.vue:70-71 that nothing-without-an-explicit-save-call
    goes to disk.
  - ``session_doc`` is no longer a valid section on the generic
    ``/api/config/section/{name}`` door (404 — Task 3).
  - Without a config service wired (``app.state.platform is None``),
    editor routes return 503 (mirrors ``config_routes._require_service``)
    rather than silently falling back to an in-memory default.
  - A double-prefix regression guard for the router mount.
  - O3 — the editor-local anthropic/claude-code model override:
    ``backends.<active>.model`` wins over ``runtime.default_model`` when
    set, and falls back to it when unset.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.migrate_common import UI_STATE_NAME
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.routers import config_routes, scene_editor
from server.session_editor_config_service import SessionEditorConfigService
from server.session_editor_config_shared import (
    EditorPaths,
    SessionEditorConfig,
    save_session_editor_config,
)

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
        app.state.platform = PlatformConfigService(campaign_dir)
    else:
        app.state.platform = None
    return app


# ── GET /api/editor/config — grouped resolved shape ─────────────────────────


class TestGetEditorConfig:
    def test_returns_grouped_shape(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.get("/api/editor/config")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "paths", "extract", "narrate", "scrub", "backends",
            "session_name", "profiles", "active_profile", "model",
            "work_dir", "campaign_dir", "config_dir", "vtt", "session_dir",
            "genre",
        }
        # Defaults: strict grouped schema, backends keyed by name (incl.
        # the hyphenated claude-code alias).
        assert body["backends"]["active"] == "anthropic"
        assert "claude-code" in body["backends"]
        assert body["extract"]["tokens"] == 8192
        assert body["narrate"]["tokens"] == 16000
        # The genre rulebook is a file (#276 fix 2): no path configured yet, so
        # the injected read-only summary says "nothing resolved" rather than
        # carrying a pasted default.
        assert body["genre"] == {
            "path": None, "exists": False, "lines": 0, "chars": 0,
            "preview": "", "sha256": "", "error": None,
        }
        assert "genre" not in body["narrate"]


# ── PUT /api/editor/config — flat payload, single write door ────────────────


class TestPutPersistsViaService:
    def test_put_editor_config_persists_through_service(self, fresh_campaign):
        # First server: PUT a grouped partial via the editor endpoint — the
        # single write door (the flat-body compat shim was retired in
        # Phase 3b, now that the frontend sends the grouped shape).
        client_a = TestClient(_make_app(fresh_campaign))
        resp = client_a.put(
            "/api/editor/config",
            json={"narrate": {"tokens": 12000}, "paths": {"voice_dir": "voice/"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        # Verify the service wrote it to its OWN file, not ui_state.yaml.
        assert (fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml").exists()
        assert not (fresh_campaign / CONFIG_SUBDIR / UI_STATE_NAME).exists()

        # Second server (simulates a restart): no in-memory state carried
        # over, but the service reloads session_doc.yaml.
        client_b = TestClient(_make_app(fresh_campaign))
        editor_cfg = client_b.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 12000
        assert editor_cfg["paths"]["voice_dir"].endswith("voice")  # absolute via resolve

    def test_put_editor_config_backend_and_scrub_fields(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={
                "backends": {
                    "active": "dgx",
                    "dgx": {"endpoint": "http://localhost:8000", "model": "llama-3-70b"},
                },
                "scrub": {"enabled": True, "tokens": 8000},
            },
        )
        assert resp.status_code == 200

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["backends"]["active"] == "dgx"
        assert editor_cfg["backends"]["dgx"]["endpoint"] == "http://localhost:8000"
        assert editor_cfg["backends"]["dgx"]["model"] == "llama-3-70b"
        assert editor_cfg["scrub"]["enabled"] is True
        assert editor_cfg["scrub"]["tokens"] == 8000

    def test_put_editor_config_narrate_batch_is_retired(self, fresh_campaign):
        """005-ui-batch-selection T029: `narrate.batch` was the bespoke
        checkbox's own store, superseded by `backends.<name>.batch`
        (test_ui_batch_service_selection.py's editor coverage). A stray
        `narrate.batch` key — e.g. from a pre-T029 session_doc.yaml, or a
        stale client still sending the old shape — is stripped before
        `extra="forbid"` sees it (NarrateKnobs._drop_retired_fields),
        mirroring EditorPaths' RETIRED_PATH_FIELDS precedent: the PUT still
        succeeds, but the field is simply absent afterward rather than
        persisted."""
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put("/api/editor/config", json={"narrate": {"batch": True}})
        assert resp.status_code == 200, resp.text

        editor_cfg = client.get("/api/editor/config").json()
        assert "batch" not in editor_cfg["narrate"]

    def test_put_editor_config_rejects_extraneous_top_level_keys(self, fresh_campaign):
        # The flat compat shim (_flat_body_to_grouped / _IGNORED_FLAT_KEYS)
        # used to silently drop CONFIG-only keys like work_dir/output_dir.
        # Now that the router forwards the body straight to
        # SessionEditorConfig's strict (extra="forbid") schema, unknown
        # top-level keys are a validation error instead.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"work_dir": "/somewhere", "output_dir": "/elsewhere"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False

    def test_put_editor_config_invalid_shape_returns_400(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={"narrate": {"tokens": "not-an-int"}},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["ok"] is False


class TestPutGroupedBody:
    """Phase 3b: the flat-body compat shim (_flat_body_to_grouped) is gone —
    PUT /api/editor/config only accepts a grouped SessionEditorConfig
    partial, written through SessionEditorConfigService.update_config."""

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

    def test_put_editor_config_grouped_body_merges_multiple_groups(self, fresh_campaign):
        # A partial touching two different top-level groups in one PUT
        # merges into both without clobbering the rest of the config.
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/editor/config",
            json={
                "scrub": {"enabled": True},
                "narrate": {"tokens": 12345},
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["scrub"]["enabled"] is True
        assert editor_cfg["narrate"]["tokens"] == 12345


class TestSectionDoorNoLongerHandlesSessionDoc:
    """Phase 5: session_doc left ui_state.yaml entirely, so the generic
    `/api/config/section/{name}` door no longer recognizes it — the editor
    is reachable ONLY through GET/PUT /api/editor/config now (single write
    door, single read door)."""

    def test_section_session_doc_is_404(self, fresh_campaign):
        client = TestClient(_make_app(fresh_campaign))
        resp = client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        assert resp.status_code == 404

    def test_section_door_write_does_not_reach_editor_config(self, fresh_campaign):
        # Even though the section door 404s, confirm the editor config is
        # untouched (defense in depth — no silent partial write).
        client = TestClient(_make_app(fresh_campaign))
        client.put(
            "/api/config/section/session_doc",
            json={"values": {"narrate_tokens": 9999}},
        )
        editor_cfg = client.get("/api/editor/config").json()
        assert editor_cfg["narrate"]["tokens"] == 16000


# ── Phase 4 — boot unification: --session-dir populates the editor ──────────
# server/main.py no longer builds a second, main.py-local derivation of
# session paths (the old `config` dict + `init_editor_config` seed). The
# only boot-time input is `runtime.session_dir` (via boot_overrides), and
# SessionEditorConfigService.resolved_editor_config() is responsible for
# threading it through its own path resolution — see the docstring on
# resolved_editor_config() for why that must be explicit rather than
# relying on PlatformConfigService's persisted-value fallback.


class TestSessionDirBootOverride:
    def test_relative_scene_extractions_dir_resolves_under_boot_session_dir(
        self, fresh_campaign
    ):
        session_dir = fresh_campaign / "summaries" / "session1"
        session_dir.mkdir(parents=True)
        save_session_editor_config(
            fresh_campaign / CONFIG_SUBDIR / "session_doc.yaml",
            SessionEditorConfig(
                paths=EditorPaths(scene_extractions_dir="scene_extractions")
            ),
        )

        platform = PlatformConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(session_dir)},
        )
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()

        expected_session_dir = str(session_dir.resolve())
        assert cfg.session_dir == expected_session_dir
        assert cfg.paths.scene_extractions_dir == str(
            (session_dir / "scene_extractions").resolve()
        )


class TestSessionDirFallback:
    """``scene_editor._session_dir`` fallback order: ``session_recap``'s
    parent, then ``cfg.session_dir`` (populated at boot from
    ``runtime.session_dir`` even before any recap has been saved), then
    ``cfg.work_dir`` (the campaign root) as a last resort."""

    def test_falls_back_to_cfg_session_dir_when_no_recap(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()
        assert cfg.paths.session_recap is None

        cfg = dataclasses.replace(cfg, session_dir="/some/session/dir")
        assert scene_editor._session_dir(cfg) == Path("/some/session/dir")

    def test_prefers_session_recap_parent_over_session_dir(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        cfg = service.resolved_editor_config()
        cfg = dataclasses.replace(
            cfg,
            paths=cfg.paths.model_copy(
                update={"session_recap": "/recap/dir/gm-assist.md"}
            ),
            session_dir="/some/other/dir",
        )
        assert scene_editor._session_dir(cfg) == Path("/recap/dir")


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
    """O3's editor-local model override, preserved through feature 003.

    003 replaced ``_model_args`` + ``_backend_flags`` with a single
    ``_selection_args`` call into the one resolution seam. The *reach* of the
    editor's override is unchanged — its own backend profile still wins over
    the platform's pick — so these assertions are the same guarantee against
    the new helper.
    """

    def test_anthropic_override_wins_then_falls_back_to_default_model(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)

        # Editor-local override (backends.anthropic.model) wins when set.
        service.update_config(
            {"backends": {"active": "anthropic", "anthropic": {"model": "claude-opus-4-9"}}}
        )
        cfg = service.resolved_editor_config()
        assert scene_editor._selection_args(None, cfg) == ["--model", "claude-opus-4-9"]

        # Falls back to runtime.default_model (the global sidebar picker)
        # when the editor-local override is unset.
        service.update_config({"backends": {"active": "anthropic", "anthropic": {"model": None}}})
        cfg2 = service.resolved_editor_config()
        default_model = platform.resolved()["runtime"]["default_model"]
        assert scene_editor._selection_args(None, cfg2) == ["--model", default_model]

    def test_dgx_selection_forwards_backend_and_no_claude_model(self, fresh_campaign):
        """Pre-003 this asserted ``_model_args(cfg) == []`` — the anthropic
        model was suppressed for dgx because ``_backend_flags`` supplied its
        own. One helper now emits both halves, so the assertion moves from
        "no model args" to what actually matters: the dgx backend is
        forwarded, and no Claude id rides along with it (the pairing rule —
        a tier that picks a different backend does not inherit the platform's
        model).
        """
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        service.update_config({"backends": {"active": "dgx"}})
        cfg = service.resolved_editor_config()
        args = scene_editor._selection_args(None, cfg)
        assert "--backend" in args and args[args.index("--backend") + 1] == "dgx"
        assert not any(a.startswith("claude-") for a in args)

    def test_plan_routes_still_suppress_the_dgx_adapter(self, fresh_campaign):
        """``allow_openai_compat=False`` is preserved verbatim: the plan
        routes fall back to the script's own default rather than being
        retargeted at DGX, whose OpenAI-compat shape cannot serve routes that
        may use tool-use.
        """
        platform = PlatformConfigService(fresh_campaign)
        service = SessionEditorConfigService(platform)
        service.update_config({"backends": {"active": "dgx"}})
        cfg = service.resolved_editor_config()
        assert scene_editor._selection_args(None, cfg, allow_openai_compat=False) == []
