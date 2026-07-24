"""Unit tests for EnsembleConfigService and the GET/PUT /api/ensemble/config
routes — Phase 2 of docs/config/ensemble-isolation.md.

The load-bearing test in this file is TestIsolationInvariant: an ensemble
write must be physically incapable of touching ui_state.yaml or platform.yaml.
That is the whole reason the service exists, and it mirrors
``test_ui_section_write_cannot_touch_platform_yaml`` from
tests/test_platform_config_service.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.ensemble_config_service import EnsembleConfigService
from server.ensemble_config_shared import ENSEMBLE_CONFIG_FILENAME, EnsembleConfig
from server.platform_config_service import PlatformConfigService
from server.routers import ensemble

CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    """A campaign dir with only ``config.yaml`` (mirrors the platform tests)."""
    _write(
        tmp_path / CONFIG_SUBDIR / "config.yaml",
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


@pytest.fixture
def service(fresh_campaign):
    return EnsembleConfigService(fresh_campaign / CONFIG_SUBDIR)


@pytest.fixture
def client(fresh_campaign):
    app = FastAPI()
    app.include_router(ensemble.router, prefix="/api/ensemble")
    app.state.platform = PlatformConfigService(fresh_campaign)
    return TestClient(app)


# ── Storage location + laziness ────────────────────────────────────────────

class TestStorage:
    def test_path_is_under_the_platform_config_dir(self, service, fresh_campaign):
        assert service.ensemble_config_path == (
            fresh_campaign / CONFIG_SUBDIR / ENSEMBLE_CONFIG_FILENAME
        )

    def test_no_file_until_first_write(self, service):
        assert not service.ensemble_config_path.exists()
        service.get_config()
        assert not service.ensemble_config_path.exists(), "a read created the file"

    def test_read_before_any_write_is_all_defaults(self, service):
        assert service.get_config() == EnsembleConfig()

    def test_first_write_creates_the_file(self, service):
        service.update_config({"known_names": ["docs/names.md"]})
        assert service.ensemble_config_path.exists()

    def test_resolved_matches_get_config(self, service):
        service.update_config({"tuning": {"chapter_parallel": 9}})
        assert service.resolved() == service.get_config()


# ── Merge semantics ────────────────────────────────────────────────────────

class TestUpdate:
    def test_nested_partial_updates_one_field_not_the_group(self, service):
        service.update_config({"tuning": {"chapter_parallel": 6}})
        t = service.get_config().tuning
        assert t.chapter_parallel == 6
        assert t.chunk_parallel == 4, "sibling field in the same group was clobbered"

    def test_untouched_groups_survive(self, service):
        service.update_config({"extract": {"backend": "dgx"}})
        service.update_config({"tuning": {"chunk_parallel": 8}})
        cfg = service.get_config()
        assert cfg.extract.backend == "dgx"
        assert cfg.tuning.chunk_parallel == 8

    def test_lists_are_replaced_not_appended(self, service):
        """chapters_selected is a selection — appending would make
        deselection impossible."""
        service.update_config({"chapters_selected": ["a.md", "b.md"]})
        service.update_config({"chapters_selected": ["a.md"]})
        assert service.get_config().chapters_selected == ["a.md"]

    def test_empty_selection_round_trips(self, service):
        """Principle X — no silent 'all'. An empty list must persist as empty
        and must not be treated as 'unset, use a default'."""
        service.update_config({"chapters_selected": ["a.md"]})
        service.update_config({"chapters_selected": []})
        assert service.get_config().chapters_selected == []

    def test_unknown_key_is_a_400(self, service):
        with pytest.raises(HTTPException) as exc:
            service.update_config({"planning_depth": "full"})
        assert exc.value.status_code == 400

    def test_bad_value_is_a_400(self, service):
        with pytest.raises(HTTPException) as exc:
            service.update_config({"planning": {"depth": "deep"}})
        assert exc.value.status_code == 400

    def test_rejected_write_leaves_the_stored_config_untouched(self, service):
        service.update_config({"tuning": {"chapter_parallel": 6}})
        before = service.ensemble_config_path.read_bytes()
        with pytest.raises(HTTPException):
            service.update_config({"nope": 1})
        assert service.ensemble_config_path.read_bytes() == before

    def test_malformed_stored_yaml_is_a_400_not_a_crash(self, service):
        service.ensemble_config_path.parent.mkdir(parents=True, exist_ok=True)
        service.ensemble_config_path.write_text("paths: [unclosed\n", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            service.get_config()
        assert exc.value.status_code == 400


# ── The invariant this service exists for ──────────────────────────────────

class TestIsolationInvariant:
    def test_ensemble_write_cannot_touch_ui_state_or_platform_yaml(
        self, fresh_campaign
    ):
        platform = PlatformConfigService(fresh_campaign)
        platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        platform.uis.update_section("vtt_summary", {"session_name": "Session 12"})

        # BOTH live under <campaign>/config/ — ui_state.yaml is NOT at the
        # campaign root. Getting this wrong made an earlier cut of this test
        # silently guard only platform.yaml while claiming to cover both.
        platform_yaml = fresh_campaign / CONFIG_SUBDIR / "platform.yaml"
        ui_state_yaml = fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml"
        assert platform_yaml.exists() and ui_state_yaml.exists(), (
            "fixture did not create both files — the guard below would be vacuous"
        )
        before = {p: p.read_bytes() for p in (platform_yaml, ui_state_yaml)}

        EnsembleConfigService(platform.config_path_base).update_config(
            {"extract": {"backend": "dgx", "endpoints": ["http://spark:8001/v1"]},
             "tuning": {"chapter_parallel": 6}}
        )

        for path, blob in before.items():
            assert path.read_bytes() == blob, (
                f"an ensemble write touched {path.name} — the isolation "
                "invariant this service exists to guarantee is broken"
            )

    def test_ensemble_write_cannot_touch_ui_state_or_platform_yaml_via_route(
        self, fresh_campaign
    ):
        app = FastAPI()
        app.include_router(ensemble.router, prefix="/api/ensemble")
        app.state.platform = PlatformConfigService(fresh_campaign)
        app.state.platform.update_runtime({"default_model": "claude-opus-4-6"})
        app.state.platform.uis.update_section("distill", {"some_field": "value"})
        client = TestClient(app)

        # BOTH live under <campaign>/config/ — ui_state.yaml is NOT at the
        # campaign root. Getting this wrong made an earlier cut of this test
        # silently guard only platform.yaml while claiming to cover both.
        platform_yaml = fresh_campaign / CONFIG_SUBDIR / "platform.yaml"
        ui_state_yaml = fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml"
        assert platform_yaml.exists() and ui_state_yaml.exists(), (
            "fixture did not create both files — the guard below would be vacuous"
        )
        before = {p: p.read_bytes() for p in (platform_yaml, ui_state_yaml)}
        resp = client.put("/api/ensemble/config", json={"known_names": ["x.md"]})
        assert resp.status_code == 200

        for path, blob in before.items():
            assert path.read_bytes() == blob


# ── HTTP contract ──────────────────────────────────────────────────────────

class TestRoutes:
    def test_get_before_any_write_returns_defaults(self, client):
        resp = client.get("/api/ensemble/config")
        assert resp.status_code == 200
        assert resp.json()["paths"]["chapters_glob"] == "docs/chapters/chapter_*.md"

    def test_put_returns_the_merged_config(self, client):
        resp = client.put(
            "/api/ensemble/config", json={"tuning": {"chapter_parallel": 6}}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tuning"]["chapter_parallel"] == 6
        assert body["tuning"]["chunk_parallel"] == 4

    def test_put_then_get_persists(self, client):
        client.put("/api/ensemble/config", json={"aliases_path": "docs/a.json"})
        assert client.get("/api/ensemble/config").json()["aliases_path"] == "docs/a.json"

    def test_put_unknown_key_is_400(self, client):
        resp = client.put("/api/ensemble/config", json={"planning_npc": "x"})
        assert resp.status_code == 400

    def test_put_non_object_body_is_400(self, client):
        resp = client.put("/api/ensemble/config", json=["not", "an", "object"])
        assert resp.status_code == 400

    def test_body_is_the_partial_itself_not_a_values_envelope(self, client):
        """The {"values": …} envelope belongs to the generic
        PUT /api/config/section/{name} this endpoint replaces."""
        resp = client.put(
            "/api/ensemble/config", json={"values": {"known_names": ["x.md"]}}
        )
        assert resp.status_code == 400

    def test_routes_are_not_double_prefixed(self, client):
        """The bug planning-isolation.md shipped: prefix= set on the APIRouter
        *and* added by main.py, mounting everything at /api/x/api/x/*."""
        assert client.get("/api/ensemble/api/ensemble/config").status_code == 404

    def test_written_file_is_hand_editable_yaml(self, client, fresh_campaign):
        client.put("/api/ensemble/config", json={"known_names": ["docs/names.md"]})
        raw = (fresh_campaign / CONFIG_SUBDIR / ENSEMBLE_CONFIG_FILENAME).read_text()
        assert yaml.safe_load(raw)["known_names"] == ["docs/names.md"]


# ── Phase 5: the ui.ensemble section is retired ────────────────────────────

class TestSectionRetired:
    def test_put_section_ensemble_404s(self, fresh_campaign):
        """`ensemble` is no longer a UISection field, so the generic section
        route must reject it — the same contract Phase 5 of the session-editor
        isolation set for `PUT /section/session_doc`."""
        from server.routers import config_routes

        app = FastAPI()
        app.include_router(config_routes.router, prefix="/api/config")
        app.state.platform = PlatformConfigService(fresh_campaign)
        c = TestClient(app)

        assert c.put("/api/config/section/ensemble",
                     json={"values": {"known_names": ["x.md"]}}).status_code == 404
        # A surviving loose section still works — this isn't a blanket break.
        assert c.put("/api/config/section/distill",
                     json={"values": {"x": 1}}).status_code == 200

    def test_ensemble_is_not_a_ui_section_name(self):
        from server.config_models import UI_SECTION_NAMES

        assert "ensemble" not in UI_SECTION_NAMES

    def test_a_pre_migration_ui_state_still_loads(self, fresh_campaign):
        """UIState stays extra="allow", so a leftover ui.ensemble block from a
        campaign that hasn't run the migration CLI loads harmlessly and is
        ignored rather than failing the server's boot."""
        import yaml as _yaml

        ui_state = fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml"
        ui_state.parent.mkdir(parents=True, exist_ok=True)
        ui_state.write_text(_yaml.safe_dump({
            "version": 3,
            "ui": {"ensemble": {"chapters_glob": "old/*.md", "campaign_dir": "/old"},
                   "distill": {"x": 1}},
        }), encoding="utf-8")

        platform = PlatformConfigService(fresh_campaign)
        resolved = platform.resolved()
        assert resolved["ui"]["distill"]["x"] == 1
        assert "ensemble" not in resolved["ui"]

    def test_schema_version_bumped(self):
        from server.config_models import SCHEMA_VERSION

        assert SCHEMA_VERSION == 4
