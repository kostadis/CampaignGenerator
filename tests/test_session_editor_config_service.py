"""Unit tests for SessionEditorConfigService — Phase 1 of
docs/config/session-editor-isolation.md.

In this phase storage is still the platform's ``ui.session_doc`` +
``ui.profiles`` (via the internal ``_from_platform``/``_persist_partial``
adapter, marked TEMP — deleted in Phase 5), so most tests exercise the
service against a real ``CampaignConfigService`` and assert both the
grouped view AND that the value actually landed in platform storage.
The shared-module tests near the bottom exercise ``save_/load_
session_editor_config`` directly (the file-backed round trip Phase 5 will
rely on) without going through the service or the platform adapter at all.

Mirrors the structure of ``tests/test_planning_config_service.py``: no
conftest, a local ``_service(tmp_path)`` helper, the 404/409/400 contract
asserted via ``HTTPException.status_code``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_models import BackendProfile, ProfileEntry  # noqa: E402
from server.config_service import CampaignConfigService  # noqa: E402
from server.session_editor_config_service import (  # noqa: E402
    SessionEditorConfigService,
)
from server.session_editor_config_shared import (  # noqa: E402
    Backends,
    EditorPaths,
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
    platform = CampaignConfigService(str(tmp_path))
    return SessionEditorConfigService(platform)


# ── empty campaign → grouped defaults ───────────────────────────────────


def test_empty_campaign_returns_grouped_defaults(tmp_path):
    svc = _service(tmp_path)
    assert svc.get_config() == SessionEditorConfig()


# ── update_config: merge + persist ──────────────────────────────────────


def test_update_config_round_trips_and_persists(tmp_path):
    svc = _service(tmp_path)
    updated = svc.update_config({"narrate": {"tokens": 8000}})

    assert updated.narrate.tokens == 8000
    # Untouched fields keep their defaults after a partial update.
    assert updated.narrate.prose_mode is False

    # Landed in the platform's typed session_doc section under its
    # (temporary) flat name.
    assert svc.platform.ui_state.ui.session_doc.narrate_tokens == 8000

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
                "narration_genre": "noir",
                "backend": "dgx",
            },
        )
    )

    cfg = svc.activate_profile("Fast")
    assert cfg.narrate.tokens == 4000
    assert cfg.narrate.prose_mode is True
    assert cfg.narrate.reflections is True
    assert cfg.narrate.genre == "noir"
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
    before = svc.platform.ui_state.ui.session_doc.session
    svc.resolved_editor_config()
    assert svc.platform.ui_state.ui.session_doc.session == before == "recap.md"


def test_resolved_editor_config_absolute_path_passes_through(tmp_path, tmp_path_factory):
    svc = _service(tmp_path)
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "recap.md"
    svc.update_config({"paths": {"session_recap": str(elsewhere)}})

    resolved = svc.resolved_editor_config()
    assert resolved.paths.session_recap == str(elsewhere.resolve())


# ── shared-module load/save round trip (file-backed shape, for Phase 5) ─


def test_save_load_round_trip_grouped_shape(tmp_path):
    path = tmp_path / "session_doc.yaml"
    cfg = SessionEditorConfig(
        paths=EditorPaths(session_recap="recap.md", party="docs/party.md"),
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
