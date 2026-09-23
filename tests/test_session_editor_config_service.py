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


# ── narration bundle ceiling (022-bundle-narration) ─────────────────────


def test_narrate_batch_tokens_defaults_to_bundle_cli_default(tmp_path):
    svc = _service(tmp_path)
    assert svc.get_config().narrate.batch_tokens == 32000


def test_update_config_round_trips_narrate_batch_tokens(tmp_path):
    svc = _service(tmp_path)

    updated = svc.update_config({"narrate": {"batch_tokens": 48000}})

    assert updated.narrate.tokens == 16000
    assert updated.narrate.batch_tokens == 48000
    on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
    assert on_disk["narrate"]["batch_tokens"] == 48000
    assert svc.get_config().narrate.batch_tokens == 48000


def test_legacy_narrate_config_without_batch_tokens_gets_default(tmp_path):
    path = tmp_path / "session_doc.yaml"
    path.write_text("narrate:\n  tokens: 9000\n", encoding="utf-8")

    loaded = load_session_editor_config(path)

    assert loaded.narrate.tokens == 9000
    assert loaded.narrate.batch_tokens == 32000


def test_narrate_batch_tokens_must_be_positive(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.update_config({"narrate": {"batch_tokens": 0}})
    assert exc.value.status_code == 400


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


def test_old_four_profile_document_loads_and_gains_codex_profile(tmp_path):
    """A pre-Codex editor document remains readable after the schema grows.

    The four named profiles are the on-disk shape used before feature 016.
    Loading it must preserve each remembered model while supplying the new
    subscription profile as an empty, opt-in choice.
    """
    svc = _service(tmp_path)
    svc.session_doc_path.write_text(
        yaml.safe_dump(
            {
                "backends": {
                    "active": "openrouter",
                    "anthropic": {"model": "claude-sonnet-4"},
                    "dgx": {
                        "endpoint": "http://dgx.local:8000",
                        "model": "Qwen/Qwen3-32B",
                    },
                    "openrouter": {"model": "anthropic/claude-3.7-sonnet"},
                    "claude-code": {"model": "claude-opus-4-1"},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cfg = svc.get_config()
    assert cfg.backends.active == "openrouter"
    assert cfg.backends.anthropic.model == "claude-sonnet-4"
    assert cfg.backends.dgx.model == "Qwen/Qwen3-32B"
    assert cfg.backends.dgx.endpoint == "http://dgx.local:8000"
    assert cfg.backends.openrouter.model == "anthropic/claude-3.7-sonnet"
    assert cfg.backends.claude_code.model == "claude-opus-4-1"
    assert cfg.backends.codex_cli.model is None


def test_default_codex_profile_is_canonical_and_empty(tmp_path):
    cfg = _service(tmp_path).get_config()
    codex = cfg.backends.codex_cli
    assert codex.model is None
    assert codex.endpoint is None
    assert codex.batch is None


def test_codex_cli_yaml_alias_loads_and_serializes(tmp_path):
    path = tmp_path / "session_doc.yaml"
    path.write_text(
        "backends:\n"
        "  active: codex-cli\n"
        "  codex-cli:\n"
        "    model: gpt-5-codex\n",
        encoding="utf-8",
    )

    cfg = load_session_editor_config(path)
    assert cfg.backends.active == "codex-cli"
    assert cfg.backends.codex_cli.model == "gpt-5-codex"

    save_session_editor_config(path, cfg)
    on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert on_disk["backends"]["codex-cli"]["model"] == "gpt-5-codex"
    assert "codex_cli" not in on_disk["backends"]


def test_codex_model_memory_is_isolated_from_existing_backends(tmp_path):
    svc = _service(tmp_path)
    svc.update_config(
        {
            "backends": {
                "active": "anthropic",
                "anthropic": {"model": "claude-sonnet-4"},
            }
        }
    )
    svc.update_config(
        {
            "backends": {
                "active": "codex-cli",
                "codex-cli": {"model": "gpt-5-codex"},
            }
        }
    )

    cfg = svc.get_config()
    assert cfg.backends.active == "codex-cli"
    assert cfg.backends.codex_cli.model == "gpt-5-codex"
    assert cfg.backends.anthropic.model == "claude-sonnet-4"

    # Switching the active selector is not allowed to leak a model from one
    # provider profile into another.
    svc.update_config({"backends": {"active": "anthropic"}})
    assert svc.get_config().backends.anthropic.model == "claude-sonnet-4"
    svc.update_config({"backends": {"active": "codex-cli"}})
    assert svc.get_config().backends.codex_cli.model == "gpt-5-codex"


# ── profile CRUD + 404/409 ──────────────────────────────────────────────


def test_create_list_get_profile(tmp_path):
    svc = _service(tmp_path)
    entry = ProfileEntry(
        name="Fast Draft",
        knobs={"narrate_tokens": 8000, "narrate_batch_tokens": 36000},
    )
    created = svc.create_profile(entry)
    assert created.name == "Fast Draft"

    assert [p.name for p in svc.list_profiles()] == ["Fast Draft"]
    got = svc.get_profile("Fast Draft")
    assert got.knobs["narrate_tokens"] == 8000
    assert got.knobs["narrate_batch_tokens"] == 36000

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
                "narrate_batch_tokens": 48000,
                "prose_mode": True,
                "reflections": True,
                "narration_genre_file": "voice/_genre.md",
                "backend": "dgx",
            },
        )
    )

    cfg = svc.activate_profile("Fast")
    assert cfg.narrate.tokens == 4000
    assert cfg.narrate.batch_tokens == 48000
    assert cfg.narrate.prose_mode is True
    assert cfg.narrate.reflections is True
    assert cfg.paths.genre_file == "voice/_genre.md"
    assert not hasattr(cfg.narrate, "genre")
    assert cfg.backends.active == "dgx"
    assert cfg.active_profile == "Fast"

    # Persisted — a fresh read agrees.
    reread = svc.get_config()
    assert reread.narrate.tokens == 4000
    assert reread.narrate.batch_tokens == 48000
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
    # Serialized via the field alias, not the Python attribute name. Matched as
    # a YAML *key* (`claude_code:`) rather than a bare substring: feature 021
    # added a `claude_code_effort` field, whose name legitimately contains
    # "claude_code" without saying anything about how the profile is keyed.
    assert "claude-code" in text
    assert "claude_code:" not in text

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


# ── 017: paths_stored / warnings — the read-side classification ─────────
#
# Feature 017 (specs/017-session-dir-repoint). The editor used to bind the
# RESOLVED (absolute) paths and PUT them back; relativize_path cannot
# collapse a path that is not under the current session_dir, so it stored
# it verbatim as a "genuine out-of-tree override" and the field stopped
# tracking session_dir forever. resolved_editor_config() now also exposes
# `paths_stored` — the healed, as-stored form the UI binds and echoes back
# — plus `warnings`. See specs/017-session-dir-repoint/data-model.md for
# the four-state table.
#
# This class covers the three BENIGN states only. The stale-pin state has
# its own class further down (TestStalePinHealing).


class TestPathsStoredBenignStates:
    def _with_session(self, tmp_path, name="sess1"):
        session_dir = tmp_path / "summaries" / name
        session_dir.mkdir(parents=True)
        svc = _service(tmp_path)
        svc.platform.update_runtime({"session_dir": str(session_dir)})
        return svc, session_dir

    def test_relative_session_path_passes_through_unchanged(self, tmp_path):
        svc, session_dir = self._with_session(tmp_path)
        svc.update_config({"paths": {"scene_extractions_dir": "scene_extractions"}})

        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.scene_extractions_dir == "scene_extractions"
        assert resolved.paths.scene_extractions_dir == str(
            (session_dir / "scene_extractions").resolve()
        )
        assert resolved.warnings == []

    def test_in_session_absolute_is_collapsed_in_paths_stored(self, tmp_path):
        svc, session_dir = self._with_session(tmp_path)
        # Write the raw document directly so the write-time choke point does
        # not collapse it first — this is the "hand-authored absolute" case.
        save_session_editor_config(
            svc.session_doc_path,
            SessionEditorConfig(
                paths=EditorPaths(
                    narration_dir=str(session_dir / "narration")
                )
            ),
        )
        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.narration_dir == "narration"
        assert resolved.paths.narration_dir == str((session_dir / "narration").resolve())
        assert resolved.warnings == []

    def test_out_of_tree_absolute_is_preserved_and_unreported(self, tmp_path):
        svc, _ = self._with_session(tmp_path)
        svc.update_config({"paths": {"narration_dir": "/totally/other/place"}})

        resolved = svc.resolved_editor_config()
        # A genuine override has no relative form that preserves its meaning.
        assert resolved.paths_stored.narration_dir == "/totally/other/place"
        assert resolved.paths.narration_dir == "/totally/other/place"
        assert resolved.warnings == []

    def test_resolve_invariant_holds_for_every_field(self, tmp_path):
        """data-model.md invariant: paths[k] == resolve(paths_stored[k])."""
        svc, session_dir = self._with_session(tmp_path)
        svc.update_config(
            {
                "paths": {
                    "session_recap": "gm-assist.md",
                    "session_summary": "session-summary.md",
                    "scene_extractions_dir": "scene_extractions",
                    "narration_dir": "/totally/other/place",
                    "party": "docs/party.md",
                    "voice_dir": "voice",
                    "examples_dir": "examples",
                    "genre_file": "voice/_genre.md",
                }
            }
        )
        resolved = svc.resolved_editor_config()
        session_fields = (
            "session_recap", "session_summary",
            "scene_extractions_dir", "narration_dir", "output_dir",
        )
        campaign_fields = ("party", "voice_dir", "examples_dir", "genre_file")
        for field in session_fields + campaign_fields:
            stored = getattr(resolved.paths_stored, field)
            base = "session" if field in session_fields else "campaign"
            expected = svc.platform.resolve_path(
                stored, base=base, session_dir=str(session_dir)
            )
            assert getattr(resolved.paths, field) == expected, field

    def test_campaign_fields_unaffected_by_session_switch(self, tmp_path):
        """FR-013: a session switch must not move a campaign-scoped path."""
        session_b = tmp_path / "summaries" / "sessB"
        session_b.mkdir(parents=True)
        svc, _ = self._with_session(tmp_path)
        svc.update_config({"paths": {"voice_dir": "voice", "party": "docs/party.md"}})

        before = svc.resolved_editor_config()
        svc.platform.update_runtime({"session_dir": str(session_b)})
        after = svc.resolved_editor_config()

        assert before.paths.voice_dir == after.paths.voice_dir
        assert before.paths.party == after.paths.party
        assert after.paths_stored.voice_dir == "voice"
        assert after.paths_stored.party == "docs/party.md"

    def test_no_session_dir_leaves_session_paths_untouched(self, tmp_path):
        """Preserves the existing defensive rule: with no session_dir there
        is no base to interpret a session-scoped value against, so nothing
        is classified and nothing is healed."""
        svc = _service(tmp_path)  # note: no update_runtime — session_dir unset
        save_session_editor_config(
            svc.session_doc_path,
            SessionEditorConfig(
                paths=EditorPaths(scene_extractions_dir="/somewhere/else/scenes")
            ),
        )
        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.scene_extractions_dir == "/somewhere/else/scenes"
        assert resolved.warnings == []

    def test_none_fields_stay_none(self, tmp_path):
        svc, _ = self._with_session(tmp_path)
        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.output_dir is None
        assert resolved.paths.output_dir is None


class TestStalePinHealing:
    """017 US3 (FR-004..FR-008, FR-012) — the stale-pin state.

    A stored session path that resolves under the PARENT of the current
    session directory, but not under the session directory itself, is a
    sibling-session pin. That is never a meaningful thing to intend, and it
    is exactly what the pre-017 editor produced. It is re-pointed on read
    and announced. Anything absolute outside that tree is a deliberate
    override and is left alone.
    """

    def _campaign(self, tmp_path):
        old = tmp_path / "summaries" / "20260811"
        cur = tmp_path / "summaries" / "20260825"
        old.mkdir(parents=True)
        cur.mkdir(parents=True)
        svc = _service(tmp_path)
        svc.platform.update_runtime({"session_dir": str(cur)})
        return svc, old, cur

    def _store_raw(self, svc, **paths):
        """Write the document directly, bypassing the write-time choke point
        — this is how a damaged config actually looks on disk."""
        save_session_editor_config(
            svc.session_doc_path,
            SessionEditorConfig(paths=EditorPaths(**paths)),
        )

    def test_sibling_session_pin_is_repointed(self, tmp_path):
        svc, old, cur = self._campaign(tmp_path)
        self._store_raw(svc, scene_extractions_dir=str(old / "scene_extractions"))

        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.scene_extractions_dir == "scene_extractions"
        assert resolved.paths.scene_extractions_dir == str(
            (cur / "scene_extractions").resolve()
        )

    def test_repoint_preserves_a_nested_name(self, tmp_path):
        """FR-008 — the value's path WITHIN its own session dir survives,
        not merely its basename."""
        svc, old, cur = self._campaign(tmp_path)
        self._store_raw(svc, narration_dir=str(old / "narration" / "pass5"))

        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.narration_dir == "narration/pass5"
        assert resolved.paths.narration_dir == str(
            (cur / "narration" / "pass5").resolve()
        )

    def test_out_of_tree_override_survives_and_is_not_reported(self, tmp_path):
        """FR-005 — outside the session-directory tree is a real override."""
        svc, _, _ = self._campaign(tmp_path)
        self._store_raw(svc, narration_dir="/tmp/shared-narration")

        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.narration_dir == "/tmp/shared-narration"
        assert resolved.paths.narration_dir == "/tmp/shared-narration"
        assert resolved.warnings == []

    def test_warning_names_the_field_and_both_values(self, tmp_path):
        """FR-006 — a correction to stored config is never silent."""
        svc, old, cur = self._campaign(tmp_path)
        stale = str(old / "scene_extractions")
        self._store_raw(svc, scene_extractions_dir=stale)

        resolved = svc.resolved_editor_config()
        assert len(resolved.warnings) == 1
        message = resolved.warnings[0]
        assert "scene_extractions_dir" in message
        assert stale in message
        assert str((cur / "scene_extractions").resolve()) in message

    def test_one_warning_per_stale_field(self, tmp_path):
        svc, old, _ = self._campaign(tmp_path)
        self._store_raw(
            svc,
            scene_extractions_dir=str(old / "scene_extractions"),
            narration_dir=str(old / "narration"),
            session_recap=str(old / "gm-assist.md"),
        )
        assert len(svc.resolved_editor_config().warnings) == 3

    def test_read_never_writes(self, tmp_path):
        """FR-007 / Principle XIII — the whole constitutional argument for
        healing on read rests on this test. A read must not mutate the
        workspace; the healed value reaches disk only on a later write the
        GM triggered for their own reasons."""
        svc, old, _ = self._campaign(tmp_path)
        self._store_raw(svc, scene_extractions_dir=str(old / "scene_extractions"))
        before_bytes = svc.session_doc_path.read_bytes()
        before_mtime = svc.session_doc_path.stat().st_mtime_ns

        svc.resolved_editor_config()
        svc.resolved_editor_config()

        assert svc.session_doc_path.read_bytes() == before_bytes
        assert svc.session_doc_path.stat().st_mtime_ns == before_mtime
        # And the raw stored view is untouched — get_config() is not healed.
        assert svc.get_config().paths.scene_extractions_dir == str(
            old / "scene_extractions"
        )

    def test_healing_is_idempotent(self, tmp_path):
        """FR-012 — a second read produces the same result, and a config
        that is already healthy produces no warning at all."""
        svc, old, _ = self._campaign(tmp_path)
        self._store_raw(svc, scene_extractions_dir=str(old / "scene_extractions"))

        first = svc.resolved_editor_config()
        second = svc.resolved_editor_config()
        assert first.paths_stored == second.paths_stored
        assert first.paths == second.paths

        # Now let the healed value land through the normal write door...
        svc.update_config({"paths": {"scene_extractions_dir": "scene_extractions"}})
        third = svc.resolved_editor_config()
        assert third.paths_stored.scene_extractions_dir == "scene_extractions"
        assert third.warnings == []  # nothing left to correct

    def test_healed_value_lands_on_the_next_write(self, tmp_path):
        """FR-004 final scenario — after any write, the field tracks
        session_dir from then on."""
        svc, old, cur = self._campaign(tmp_path)
        self._store_raw(svc, scene_extractions_dir=str(old / "scene_extractions"))

        stored = svc.resolved_editor_config().paths_stored
        # This is what the editor does: echo back what it was given.
        svc.update_config({"paths": stored.model_dump(mode="json")})

        on_disk = yaml.safe_load(svc.session_doc_path.read_text(encoding="utf-8"))
        assert on_disk["paths"]["scene_extractions_dir"] == "scene_extractions"
        assert "20260811" not in svc.session_doc_path.read_text(encoding="utf-8")

    def test_current_session_subdirectory_is_not_stale(self, tmp_path):
        """Guard against over-eager healing: a path under the CURRENT
        session directory is in-session, not a sibling pin."""
        svc, _, cur = self._campaign(tmp_path)
        self._store_raw(svc, narration_dir=str(cur / "narration"))

        resolved = svc.resolved_editor_config()
        assert resolved.paths_stored.narration_dir == "narration"
        assert resolved.warnings == []


def test_healthy_campaign_is_byte_identical_through_load_modify_save(tmp_path):
    """017 / plan.md Principle XIII, ground 1 — nothing changes shape.

    The constitutional argument for healing on read rests on this: a
    campaign whose stored paths are already relative — which is every
    campaign in the workspace that has not hit the bug — must come through
    a full load-modify-save cycle byte-identical apart from the field the
    GM actually changed. If this ever fails, 017 IS a state-shape change and
    the one-shot migrator fallback in plan.md is required instead.
    """
    session_dir = tmp_path / "summaries" / "20260825"
    session_dir.mkdir(parents=True)
    svc = _service(tmp_path)
    svc.platform.update_runtime({"session_dir": str(session_dir)})
    svc.update_config(
        {
            "paths": {
                "session_recap": "gm-assist.md",
                "session_summary": "session-summary.md",
                "scene_extractions_dir": "scene_extractions",
                "narration_dir": "narration",
                "party": "docs/party.md",
                "voice_dir": "voice",
                "examples_dir": "examples",
                "genre_file": "voice/_genre.md",
            }
        }
    )
    before = svc.session_doc_path.read_text(encoding="utf-8")

    # A read does not touch it...
    resolved = svc.resolved_editor_config()
    assert resolved.warnings == []
    assert svc.session_doc_path.read_text(encoding="utf-8") == before

    # ...and echoing back exactly what the editor was handed is a no-op.
    svc.update_config({"paths": resolved.paths_stored.model_dump(mode="json")})
    assert svc.session_doc_path.read_text(encoding="utf-8") == before


class TestBootOverrideSessionDir:
    """017 FR-011 — `--session-dir` for one run gets the same behaviour, and
    persists nothing.

    The boot override reaches this service through platform.resolved(), so
    re-pointing and healing apply to the resolved view for free. What must
    NOT happen is any of it reaching disk: the override is
    process-lifetime-only, and _relativized_paths is keyed off the
    PERSISTED runtime.session_dir for exactly that reason.
    """

    def _svc(self, tmp_path, boot_dir):
        (tmp_path / "config").mkdir(exist_ok=True)
        (tmp_path / "config" / "config.yaml").write_text(
            "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
            encoding="utf-8",
        )
        platform = PlatformConfigService(
            str(tmp_path), boot_overrides={"runtime.session_dir": str(boot_dir)}
        )
        return SessionEditorConfigService(platform)

    def test_paths_resolve_against_the_boot_override(self, tmp_path):
        persisted = tmp_path / "summaries" / "persisted"
        boot = tmp_path / "summaries" / "boot"
        persisted.mkdir(parents=True)
        boot.mkdir(parents=True)
        svc = self._svc(tmp_path, boot)
        svc.platform.update_runtime({"session_dir": str(persisted)})
        svc.update_config({"paths": {"scene_extractions_dir": "scene_extractions"}})

        resolved = svc.resolved_editor_config()
        assert resolved.paths.scene_extractions_dir == str(
            (boot / "scene_extractions").resolve()
        )
        assert resolved.paths_stored.scene_extractions_dir == "scene_extractions"

    def test_healing_under_a_boot_override_persists_nothing(self, tmp_path):
        persisted = tmp_path / "summaries" / "persisted"
        boot = tmp_path / "summaries" / "boot"
        stale = tmp_path / "summaries" / "20260811"
        for d in (persisted, boot, stale):
            d.mkdir(parents=True)
        svc = self._svc(tmp_path, boot)
        svc.platform.update_runtime({"session_dir": str(persisted)})
        save_session_editor_config(
            svc.session_doc_path,
            SessionEditorConfig(
                paths=EditorPaths(scene_extractions_dir=str(stale / "scene_extractions"))
            ),
        )
        before = svc.session_doc_path.read_bytes()

        resolved = svc.resolved_editor_config()
        # Healed against the OVERRIDE, in the resolved view only...
        assert resolved.paths_stored.scene_extractions_dir == "scene_extractions"
        assert resolved.paths.scene_extractions_dir == str(
            (boot / "scene_extractions").resolve()
        )
        assert len(resolved.warnings) == 1
        # ...and nothing reached disk.
        assert svc.session_doc_path.read_bytes() == before
