"""Unit tests for SessionEditorConfigService — Phase 5 of
docs/config/session-editor-isolation.md.

Storage is a dedicated ``<config>/session_doc.yaml`` this service owns
exclusively — ``ui_state.yaml`` is never touched by an editor write. Most
tests exercise the service against a real ``PlatformConfigService`` (for
path resolution) and assert the value actually landed in
``session_doc.yaml`` on disk. The shared-module tests near the bottom
exercise ``save_/load_session_editor_config`` directly, without going
through the service at all.

Mirrors the structure of ``tests/test_planning_config_service.py``: no
conftest, a local ``_service(tmp_path)`` helper, the 404/409/400 contract
asserted via ``HTTPException.status_code``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.session_editor_config_shared import BackendProfile, ProfileEntry  # noqa: E402
from server.migrate_common import UI_STATE_NAME  # noqa: E402
from server.platform_config_service import PlatformConfigService  # noqa: E402
from server.session_editor_config_service import (  # noqa: E402
    SessionEditorConfigService,
)
from server.session_editor_config_shared import (  # noqa: E402
    Backends,
    EditorPaths,
    ExtractKnobs,
    NarrateKnobs,
    SessionEditorConfig,
    load_session_editor_config,
    save_session_editor_config,
)


def _service(tmp_path: Path) -> SessionEditorConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    platform = PlatformConfigService(str(tmp_path))
    return SessionEditorConfigService(platform)


# ── empty campaign → grouped defaults ───────────────────────────────────


def test_empty_campaign_returns_grouped_defaults(tmp_path):
    svc = _service(tmp_path)
    assert svc.get_config() == SessionEditorConfig()


def test_no_session_doc_yaml_written_for_empty_campaign(tmp_path):
    svc = _service(tmp_path)
    svc.get_config()
    assert not svc.session_doc_path.exists()


# ── update_config: merge + persist ──────────────────────────────────────


def test_update_config_round_trips_and_persists(tmp_path):
    svc = _service(tmp_path)
    updated = svc.update_config({"narrate": {"tokens": 8000}})

    assert updated.narrate.tokens == 8000
    # Untouched fields keep their defaults after a partial update.
    assert updated.narrate.prose_mode is False

    # Landed in the service's OWN file, not ui_state.yaml.
    assert svc.session_doc_path.exists()
    assert svc.session_doc_path.name == "session_doc.yaml"
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["narrate"]["tokens"] == 8000

    # ui_state.yaml is untouched by an editor write (Phase 5's whole point).
    ui_state_path = tmp_path / "config" / UI_STATE_NAME
    assert not ui_state_path.exists()

    # A fresh read through the service sees the persisted value.
    assert svc.get_config().narrate.tokens == 8000


def test_update_config_invalid_shape_raises_400(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_config({"narrate": {"tokens": "not-an-int"}})
    assert exc.value.status_code == 400


def test_update_config_unknown_field_raises_400(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_config({"bogus_top_level_field": True})
    assert exc.value.status_code == 400


def test_invalid_update_does_not_corrupt_stored_file(tmp_path):
    svc = _service(tmp_path)
    svc.update_config({"narrate": {"tokens": 8000}})
    with pytest.raises(HTTPException):
        svc.update_config({"narrate": {"tokens": "nope"}})
    # The bad partial never got written — prior value survives.
    assert svc.get_config().narrate.tokens == 8000


# ── extract knobs (011-extract-max-tokens) ──────────────────────────────


def test_extract_tokens_defaults_to_scene_extract_cli_default(tmp_path):
    # 8192 must match session_doc/scene_extract.py's own --max-tokens
    # default exactly, so an unset campaign's behavior is unchanged.
    svc = _service(tmp_path)
    assert svc.get_config().extract.tokens == 8192


def test_update_config_round_trips_and_persists_extract_tokens(tmp_path):
    svc = _service(tmp_path)
    updated = svc.update_config({"extract": {"tokens": 12000}})

    assert updated.extract.tokens == 12000

    assert svc.session_doc_path.exists()
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["extract"]["tokens"] == 12000

    # A fresh read through the service sees the persisted value.
    assert svc.get_config().extract.tokens == 12000


def test_update_config_unknown_extract_field_raises_400(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_config({"extract": {"bogus_field": True}})
    assert exc.value.status_code == 400


# ── batch knobs (013-batched-scene-extraction) ──────────────────────────


def test_batch_knobs_default_on_fresh_service(tmp_path):
    # batch_scenes defaults to None ("not pinned — follow the backend
    # default"); batch_tokens defaults to 32000, the batched ceiling.
    svc = _service(tmp_path)
    cfg = svc.get_config()
    assert cfg.extract.batch_scenes is None
    assert cfg.extract.batch_tokens == 32000


def test_update_config_round_trips_and_persists_batch_knobs(tmp_path):
    svc = _service(tmp_path)
    updated = svc.update_config(
        {"extract": {"batch_scenes": True, "batch_tokens": 40000}}
    )

    assert updated.extract.batch_scenes is True
    assert updated.extract.batch_tokens == 40000

    assert svc.session_doc_path.exists()
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["extract"]["batch_scenes"] is True
    assert on_disk["extract"]["batch_tokens"] == 40000

    # A fresh read through the service sees the persisted value.
    reread = svc.get_config()
    assert reread.extract.batch_scenes is True
    assert reread.extract.batch_tokens == 40000


def test_batch_tokens_and_tokens_are_independent(tmp_path):
    # DM-17: changing one never changes the other.
    svc = _service(tmp_path)

    svc.update_config({"extract": {"batch_tokens": 50000}})
    cfg = svc.get_config()
    assert cfg.extract.batch_tokens == 50000
    assert cfg.extract.tokens == 8192

    svc.update_config({"extract": {"tokens": 12000}})
    cfg = svc.get_config()
    assert cfg.extract.tokens == 12000
    assert cfg.extract.batch_tokens == 50000


def test_batch_scenes_tri_state_round_trips_all_three_values(tmp_path):
    # A persisted False must read back as False, not collapse to None —
    # that distinction is the entire reason batch_scenes is bool | None
    # rather than a plain bool.
    svc = _service(tmp_path)

    svc.update_config({"extract": {"batch_scenes": True}})
    assert svc.get_config().extract.batch_scenes is True
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["extract"]["batch_scenes"] is True

    svc.update_config({"extract": {"batch_scenes": False}})
    assert svc.get_config().extract.batch_scenes is False
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["extract"]["batch_scenes"] is False

    svc.update_config({"extract": {"batch_scenes": None}})
    assert svc.get_config().extract.batch_scenes is None
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["extract"]["batch_scenes"] is None


# ── per-backend model memory (O1) ───────────────────────────────────────


def test_per_backend_model_memory_survives_switching_active(tmp_path):
    svc = _service(tmp_path)
    svc.update_config(
        {"backends": {"active": "dgx", "dgx": {"model": "llama-3-70b"}}}
    )
    svc.update_config(
        {
            "backends": {
                "active": "openrouter",
                "openrouter": {"model": "anthropic/claude-3"},
            }
        }
    )

    cfg = svc.get_config()
    assert cfg.backends.active == "openrouter"
    # Switching active must not clobber the previously-set dgx model.
    assert cfg.backends.dgx.model == "llama-3-70b"
    assert cfg.backends.openrouter.model == "anthropic/claude-3"


# ── profile CRUD + 404/409 ──────────────────────────────────────────────


def test_create_list_get_profile(tmp_path):
    svc = _service(tmp_path)
    entry = ProfileEntry(name="Fast Draft", knobs={"narrate_tokens": 8000})
    created = svc.create_profile(entry)
    assert created.name == "Fast Draft"

    assert [p.name for p in svc.list_profiles()] == ["Fast Draft"]
    got = svc.get_profile("Fast Draft")
    assert got.knobs["narrate_tokens"] == 8000

    # Persisted to session_doc.yaml.
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["profiles"][0]["name"] == "Fast Draft"


def test_create_duplicate_profile_conflicts(tmp_path):
    svc = _service(tmp_path)
    svc.create_profile(ProfileEntry(name="Fast Draft"))
    with pytest.raises(HTTPException) as exc:
        svc.create_profile(ProfileEntry(name="Fast Draft"))
    assert exc.value.status_code == 409


def test_get_missing_profile_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.get_profile("Nobody")
    assert exc.value.status_code == 404


def test_delete_profile_then_missing(tmp_path):
    svc = _service(tmp_path)
    svc.create_profile(ProfileEntry(name="A"))
    svc.create_profile(ProfileEntry(name="B"))
    svc.delete_profile("A")
    assert [p.name for p in svc.list_profiles()] == ["B"]
    with pytest.raises(HTTPException) as exc:
        svc.get_profile("A")
    assert exc.value.status_code == 404


def test_delete_missing_profile_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.delete_profile("Nobody")
    assert exc.value.status_code == 404


def test_delete_last_profile_reads_back_empty(tmp_path):
    svc = _service(tmp_path)
    svc.create_profile(ProfileEntry(name="Onlyone"))
    svc.delete_profile("Onlyone")
    assert svc.list_profiles() == []


def test_upsert_profile_creates_then_replaces(tmp_path):
    svc = _service(tmp_path)
    svc.upsert_profile(ProfileEntry(name="A", knobs={"narrate_tokens": 4000}))
    svc.upsert_profile(ProfileEntry(name="A", knobs={"narrate_tokens": 6000}))
    assert [p.name for p in svc.list_profiles()] == ["A"]
    assert svc.get_profile("A").knobs["narrate_tokens"] == 6000


def test_update_profile_name_mismatch_400(tmp_path):
    svc = _service(tmp_path)
    svc.create_profile(ProfileEntry(name="A"))
    with pytest.raises(HTTPException) as exc:
        svc.update_profile("A", ProfileEntry(name="B"))
    assert exc.value.status_code == 400


def test_update_missing_profile_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_profile("Ghost", ProfileEntry(name="Ghost"))
    assert exc.value.status_code == 404


# ── activate_profile: server-side knob mirror (O2) ──────────────────────


def test_activate_profile_copies_knobs_into_narrate_and_backends(tmp_path):
    svc = _service(tmp_path)
    svc.create_profile(
        ProfileEntry(
            name="Fast",
            knobs={
                "narrate_tokens": 4000,
                "prose_mode": True,
                "reflections": True,
                "narration_genre_file": "voice/_genre.md",
                "backend": "dgx",
            },
        )
    )

    cfg = svc.activate_profile("Fast")
    assert cfg.narrate.tokens == 4000
    assert cfg.narrate.prose_mode is True
    assert cfg.narrate.reflections is True
    assert cfg.paths.genre_file == "voice/_genre.md"
    assert not hasattr(cfg.narrate, "genre")
    assert cfg.backends.active == "dgx"
    assert cfg.active_profile == "Fast"

    # Persisted — a fresh read agrees.
    reread = svc.get_config()
    assert reread.narrate.tokens == 4000
    assert reread.active_profile == "Fast"


def test_activate_missing_profile_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.activate_profile("Nope")
    assert exc.value.status_code == 404


# ── resolved_editor_config: path resolution + injected extras ──────────


def test_resolved_editor_config_resolves_session_and_campaign_paths(tmp_path):
    svc = _service(tmp_path)
    svc.platform.update_runtime({"session_dir": "sessions/2026-07-24"})
    svc.update_config(
        {"paths": {"session_recap": "recap.md", "party": "party.md"}}
    )

    resolved = svc.resolved_editor_config()

    expected_session_dir = (tmp_path / "sessions" / "2026-07-24").resolve()
    assert resolved.paths.session_recap == str(
        (expected_session_dir / "recap.md").resolve()
    )
    assert resolved.paths.party == str((tmp_path / "party.md").resolve())
    # Never-set path field: empty → None, not the string "None".
    assert resolved.paths.voice_dir is None

    # Injected platform extras, never persisted.
    assert resolved.model == svc.platform.resolved()["runtime"]["default_model"]
    assert resolved.campaign_dir == str(tmp_path.resolve())
    assert resolved.work_dir == str(tmp_path.resolve())
    assert resolved.config_dir == "config"
    assert resolved.vtt is None

    # resolved_editor_config never writes anything back: the stored
    # (relative) value is untouched by resolving a second time.
    before = svc.get_config().paths.session_recap
    svc.resolved_editor_config()
    assert svc.get_config().paths.session_recap == before == "recap.md"


def test_resolved_editor_config_absolute_path_passes_through(tmp_path, tmp_path_factory):
    svc = _service(tmp_path)
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "recap.md"
    svc.update_config({"paths": {"session_recap": str(elsewhere)}})

    resolved = svc.resolved_editor_config()
    assert resolved.paths.session_recap == str(elsewhere.resolve())


# ── relativize-on-write (Task 1b — parity with the old update_section) ──
#
# The frontend sends absolute paths (it calls resolvePath client-side).
# update_config must collapse an absolute-but-under-base session path back
# to relative storage before writing session_doc.yaml, so the value
# re-tracks a later runtime.session_dir change — mirrors
# UIStateService.update_section's write-time relativize_path choke
# point, now re-implemented here since the data no longer lives in
# ui_state.yaml.


class TestRelativizeOnWrite:
    def test_absolute_session_path_stored_relative(self, tmp_path):
        session_dir = tmp_path / "summaries" / "sess1"
        session_dir.mkdir(parents=True)
        svc = _service(tmp_path)
        svc.platform.update_runtime({"session_dir": str(session_dir)})

        svc.update_config(
            {"paths": {"scene_extractions_dir": str(session_dir / "scene_extractions")}}
        )

        # Raw stored value is relative, even though an absolute path was sent.
        on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
        assert on_disk["paths"]["scene_extractions_dir"] == "scene_extractions"
        assert svc.get_config().paths.scene_extractions_dir == "scene_extractions"

        # resolved_editor_config() still reports it absolute, anchored
        # under the session dir.
        resolved = svc.resolved_editor_config()
        assert resolved.paths.scene_extractions_dir == str(
            (session_dir / "scene_extractions").resolve()
        )

    def test_absolute_campaign_path_stored_relative(self, tmp_path):
        svc = _service(tmp_path)
        svc.update_config({"paths": {"voice_dir": str(tmp_path / "voice")}})

        on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
        assert on_disk["paths"]["voice_dir"] == "voice"

    def test_out_of_tree_absolute_path_stored_as_is(self, tmp_path):
        session_dir = tmp_path / "summaries" / "sess1"
        session_dir.mkdir(parents=True)
        svc = _service(tmp_path)
        svc.platform.update_runtime({"session_dir": str(session_dir)})

        svc.update_config({"paths": {"scene_extractions_dir": "/totally/other/place"}})

        on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
        assert on_disk["paths"]["scene_extractions_dir"] == "/totally/other/place"

    def test_session_path_retracks_after_session_dir_change(self, tmp_path):
        session_a = tmp_path / "summaries" / "sessA"
        session_b = tmp_path / "summaries" / "sessB"
        session_a.mkdir(parents=True)
        session_b.mkdir(parents=True)

        svc = _service(tmp_path)
        svc.update_config({"paths": {"scene_extractions_dir": "scene_extractions"}})
        svc.platform.update_runtime({"session_dir": str(session_a)})
        resolved_a = svc.resolved_editor_config()
        assert resolved_a.paths.scene_extractions_dir == str(
            (session_a / "scene_extractions").resolve()
        )

        # Switching session_dir alone must retrack the relative value.
        svc.platform.update_runtime({"session_dir": str(session_b)})
        resolved_b = svc.resolved_editor_config()
        assert resolved_b.paths.scene_extractions_dir == str(
            (session_b / "scene_extractions").resolve()
        )

    def test_relativize_does_not_use_boot_override_session_dir(self, tmp_path):
        # A --session-dir boot override must NOT be baked into on-disk
        # relative storage — mirrors UIStateService's
        # _normalize_stored_paths persisted-only rule. Only the PERSISTED
        # runtime.session_dir (set via update_runtime, i.e. what the UI
        # actually saved) is the relativization base.
        persisted_dir = tmp_path / "summaries" / "persisted"
        boot_dir = tmp_path / "summaries" / "boot"
        persisted_dir.mkdir(parents=True)
        boot_dir.mkdir(parents=True)

        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "config.yaml").write_text(
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
            encoding="utf-8",
        )
        platform = PlatformConfigService(
            str(tmp_path), boot_overrides={"runtime.session_dir": str(boot_dir)}
        )
        svc = SessionEditorConfigService(platform)
        # Persist the "real" session_dir (what's actually saved to disk).
        platform.update_runtime({"session_dir": str(persisted_dir)})

        svc.update_config(
            {"paths": {"scene_extractions_dir": str(boot_dir / "scene_extractions")}}
        )

        on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
        # Not relative to persisted_dir (out-of-tree relative to that base)
        # and not silently accepted as relative to boot_dir either — the
        # value stays absolute, since it isn't under the persisted base.
        assert on_disk["paths"]["scene_extractions_dir"] == str(
            (boot_dir / "scene_extractions").resolve()
        )


# ── shared-module load/save round trip (file-backed shape) ──────────────


def test_save_load_round_trip_grouped_shape(tmp_path):
    path = tmp_path / "session_doc.yaml"
    cfg = SessionEditorConfig(
        paths=EditorPaths(session_recap="recap.md", party="docs/party.md"),
        extract=ExtractKnobs(tokens=10000),
        narrate=NarrateKnobs(tokens=12000, genre="noir"),
        backends=Backends(
            active="dgx",
            dgx=BackendProfile(model="llama-3-70b", endpoint="http://localhost:8000"),
        ),
        profiles=[ProfileEntry(name="Fast", knobs={"narrate_tokens": 4000})],
        active_profile="Fast",
    )
    save_session_editor_config(path, cfg)

    text = path.read_text(encoding="utf-8")
    # Serialized via the field alias, not the Python attribute name.
    assert "claude-code" in text
    assert "claude_code" not in text

    reloaded = load_session_editor_config(path)
    assert reloaded == cfg
    assert reloaded.extract.tokens == 10000
    assert reloaded.backends.dgx.model == "llama-3-70b"
    assert reloaded.backends.active == "dgx"
    assert reloaded.profiles[0].knobs["narrate_tokens"] == 4000


def test_load_missing_file_returns_defaults(tmp_path):
    assert load_session_editor_config(tmp_path / "nope.yaml") == SessionEditorConfig()


def test_load_empty_file_returns_defaults(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert load_session_editor_config(path) == SessionEditorConfig()


def test_load_invalid_yaml_raises(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("paths: [this is not: a mapping", encoding="utf-8")
    with pytest.raises(ValueError):
        load_session_editor_config(path)
