"""Unit tests for EnsembleConfigService and the GET/PUT /api/ensemble/config
routes — Phase 2 of docs/config/ensemble-isolation.md.

The load-bearing test in this file is TestIsolationInvariant: an ensemble
write must be physically incapable of touching a sibling service's document.
That is the whole reason the service exists, and it mirrors
``test_another_services_write_cannot_touch_platform_yaml`` from
tests/test_platform_config_service.py. (Both guards named ``ui_state.yaml``
as one of the documents at risk until docs/config/ui-state-retirement.md
removed it; see TestIsolationInvariant's own docstring.)
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
    """An ensemble write must not re-serialize another service's document.

    The guarded pair used to be ``platform.yaml`` + ``ui_state.yaml``, the two
    documents an ensemble save could plausibly have clobbered back when
    ``ui.ensemble`` lived in the shared file. ``ui_state.yaml`` is not written
    by anything any more (docs/config/ui-state-retirement.md), so guarding it
    would be vacuous — exactly the failure the assertions below were added to
    prevent. The probe moves to ``grounding.yaml``, a live sibling document
    under the same ``config/`` directory.
    """

    @staticmethod
    def _seed_siblings(platform, fresh_campaign):
        """Materialize both guarded documents and return their paths + bytes."""
        from server.grounding_config_service import GroundingConfigService

        platform.update_runtime(
            {"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"}
        )
        GroundingConfigService(platform.config_path_base).update_config(
            {"summaries": "docs/summaries.md"}
        )
        platform_yaml = fresh_campaign / CONFIG_SUBDIR / "platform.yaml"
        grounding_yaml = fresh_campaign / CONFIG_SUBDIR / "grounding.yaml"
        assert platform_yaml.exists() and grounding_yaml.exists(), (
            "fixture did not create both files — the guard below would be vacuous"
        )
        return {p: p.read_bytes() for p in (platform_yaml, grounding_yaml)}

    @staticmethod
    def _assert_untouched(before):
        for path, blob in before.items():
            assert path.read_bytes() == blob, (
                f"an ensemble write touched {path.name} — the isolation "
                "invariant this service exists to guarantee is broken"
            )

    def test_ensemble_write_cannot_touch_sibling_documents(self, fresh_campaign):
        platform = PlatformConfigService(fresh_campaign)
        before = self._seed_siblings(platform, fresh_campaign)

        EnsembleConfigService(platform.config_path_base).update_config(
            {"extract": {"backend": "dgx", "endpoints": ["http://spark:8001/v1"]},
             "tuning": {"chapter_parallel": 6}}
        )

        self._assert_untouched(before)

    def test_ensemble_write_cannot_touch_sibling_documents_via_route(
        self, fresh_campaign
    ):
        app = FastAPI()
        app.include_router(ensemble.router, prefix="/api/ensemble")
        app.state.platform = PlatformConfigService(fresh_campaign)
        before = self._seed_siblings(app.state.platform, fresh_campaign)
        client = TestClient(app)

        resp = client.put(
            "/api/ensemble/config", json={"tuning": {"chapter_parallel": 6}}
        )
        assert resp.status_code == 200

        self._assert_untouched(before)


# ── Phase 5: the ui.ensemble section is retired ────────────────────────────

class TestSectionRetired:
    """Ensemble's config left ``ui_state.yaml`` in Phase 5 of
    ``docs/config/ensemble-isolation.md``. These tests originally pinned that
    against a still-live generic section route — ``PUT /section/ensemble``
    404s while a surviving loose section still 200s. That second half is gone:
    ``docs/config/ui-state-retirement.md`` deleted the route, the six
    remaining sections, ``UI_SECTION_NAMES`` and ``SCHEMA_VERSION`` outright,
    so what these now pin is the stronger claim — nothing reaches
    ``ui_state.yaml``, from any direction, ever.
    """

    def test_put_section_ensemble_404s(self, fresh_campaign):
        from server.routers import config_routes

        app = FastAPI()
        app.include_router(config_routes.router, prefix="/api/config")
        app.state.platform = PlatformConfigService(fresh_campaign)
        c = TestClient(app)

        assert c.put("/api/config/section/ensemble",
                     json={"values": {"known_names": ["x.md"]}}).status_code == 404

    def test_a_pre_migration_ui_state_is_ignored_entirely(self, fresh_campaign):
        """A campaign that never ran the migration CLI still boots. The file
        used to load through ``UIState`` (``extra="allow"``, so a stale
        ``ui.ensemble`` block was parsed then ignored); now it is not read at
        all, which is the same outcome by a shorter route — and the reason
        ``server/migrate_ensemble_config.py`` still reads it raw."""
        import yaml as _yaml

        ui_state = fresh_campaign / CONFIG_SUBDIR / "ui_state.yaml"
        ui_state.parent.mkdir(parents=True, exist_ok=True)
        ui_state.write_text(_yaml.safe_dump({
            "version": 3,
            "ui": {"ensemble": {"chapters_glob": "old/*.md", "campaign_dir": "/old"},
                   "query": {"x": 1}},
        }), encoding="utf-8")

        platform = PlatformConfigService(fresh_campaign)
        resolved = platform.resolved()
        assert "ui" not in resolved
        # The stale file is left exactly as found — this service does not
        # write it, and the migration CLIs are what rescue its contents.
        assert _yaml.safe_load(ui_state.read_text())["ui"]["ensemble"][
            "chapters_glob"
        ] == "old/*.md"
