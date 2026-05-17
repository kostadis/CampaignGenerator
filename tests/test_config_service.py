"""Tests for server/config_service.py — the single-authority service.

The hard invariants this file freezes:

  - ``config.yaml`` is never opened for write.
  - Path resolution is uniform: relative → absolute against campaign_dir;
    absolute and ``~`` paths pass through.
  - Boot overrides are in-memory only; a second instance does not see them.
  - Atomic writes: a crash between ``tmp.write`` and ``os.replace`` leaves
    the original file untouched.
  - Concurrent updates serialize on the section lock.
  - A `--session-dir` boot override rebases stale absolute paths persisted
    under the prior session dir.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.config_service import (
    CampaignConfigService,
    ConfigError,
    LOCAL_CONFIG_NAME,
    TRACKED_CONFIG_NAME,
    UI_STATE_NAME,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    """A campaign dir with only ``config.yaml``."""
    cfg = tmp_path / TRACKED_CONFIG_NAME
    _write(
        cfg,
        "# hand-written, do not touch\ndocuments:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


# ── Construction ──────────────────────────────────────────────────────────


class TestConstruction:
    def test_missing_campaign_dir_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="does not exist"):
            CampaignConfigService(tmp_path / "nope")

    def test_missing_config_yaml_raises(self, tmp_path):
        # Empty dir, no config.yaml.
        with pytest.raises(ConfigError, match="no config.yaml"):
            CampaignConfigService(tmp_path)

    def test_invalid_config_yaml_raises(self, tmp_path):
        _write(tmp_path / TRACKED_CONFIG_NAME, "key: : :")
        with pytest.raises(ConfigError, match="not valid YAML"):
            CampaignConfigService(tmp_path)

    def test_invalid_ui_state_yaml_raises(self, tmp_path):
        _write(tmp_path / TRACKED_CONFIG_NAME, "documents: []\n")
        _write(tmp_path / UI_STATE_NAME, "version: 2\nui: : :")
        with pytest.raises(ConfigError, match="ui_state.yaml is not valid YAML"):
            CampaignConfigService(tmp_path)

    def test_local_yaml_syntax_error_does_not_block_startup(self, fresh_campaign):
        _write(fresh_campaign / LOCAL_CONFIG_NAME, "server: : :")
        # Hostile to refuse boot over a bad nav.last_page entry.
        svc = CampaignConfigService(fresh_campaign)
        assert any("could not be parsed" in w for w in svc.load_warnings)


# ── config.yaml read-only invariant ──────────────────────────────────────


class TestConfigYamlNeverWritten:
    def test_config_yaml_unchanged_after_updates(self, fresh_campaign):
        original = (fresh_campaign / TRACKED_CONFIG_NAME).read_bytes()
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"narrate_tokens": 12000})
        svc.update_local({"server": {"port": 6001}})
        assert (fresh_campaign / TRACKED_CONFIG_NAME).read_bytes() == original

    def test_service_module_has_no_config_yaml_writer(self):
        """Source-level guard: no function in config_service.py opens
        config.yaml for writing. The strongest enforcement of the
        'human-only' contract."""
        src = Path(__file__).resolve().parent.parent / "server" / "config_service.py"
        text = src.read_text(encoding="utf-8")
        # Writers go through _atomic_write or _persist_*. Make sure none
        # target the tracked config path.
        assert "config_path" not in text.split("_atomic_write")[1].split("def ")[0] if "_atomic_write" in text else True
        # The structural guarantee: only ui_state and local are persisted.
        assert "_persist_ui_state" in text
        assert "_persist_local" in text
        # And there should be no ``self.config_path.write`` style mutation.
        assert ".config_path.write" not in text


# ── Path resolution ──────────────────────────────────────────────────────


class TestPathResolution:
    def test_relative_resolves_against_campaign_dir(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        resolved = svc.resolve_path("docs/world_state.md")
        assert resolved == str((fresh_campaign / "docs" / "world_state.md").resolve())

    def test_absolute_passes_through(self, fresh_campaign, tmp_path):
        svc = CampaignConfigService(fresh_campaign)
        resolved = svc.resolve_path(str(tmp_path / "elsewhere"))
        assert resolved == str((tmp_path / "elsewhere").resolve())

    def test_tilde_expands(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        resolved = svc.resolve_path("~/file.md")
        assert resolved == str(Path.home() / "file.md")

    def test_empty_becomes_none(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        assert svc.resolve_path("") is None
        assert svc.resolve_path("   ") is None
        assert svc.resolve_path(None) is None


# ── Boot overrides ───────────────────────────────────────────────────────


class TestBootOverrides:
    def test_boot_override_visible_in_resolved(self, fresh_campaign):
        svc = CampaignConfigService(
            fresh_campaign,
            boot_overrides={"session_doc.narrate_tokens": 8000},
        )
        resolved = svc.resolved()
        assert resolved["ui"]["session_doc"]["narrate_tokens"] == 8000

    def test_boot_override_does_not_persist(self, fresh_campaign):
        # First instance with override.
        CampaignConfigService(
            fresh_campaign,
            boot_overrides={"session_doc.narrate_tokens": 8000},
        )
        # Second instance with no override sees the file's value (default).
        second = CampaignConfigService(fresh_campaign)
        resolved = second.resolved()
        # narrate_tokens default is 16000 from SessionDocSection.
        assert resolved["ui"]["session_doc"]["narrate_tokens"] == 16000

    def test_runtime_dotted_override_lands_in_runtime(self, fresh_campaign):
        svc = CampaignConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "/tmp/x"},
        )
        resolved = svc.resolved()
        assert resolved["runtime"]["session_dir"] == "/tmp/x"


# ── Fresh-campaign defaults ──────────────────────────────────────────────


class TestFreshCampaign:
    def test_no_ui_state_starts_with_defaults(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        assert svc.load_warnings == []
        # Defaults applied from the schema.
        assert svc.ui_state.ui.session_doc.narrate_tokens == 16000
        # Bool defaults survive a YAML round-trip even when persisted as null.
        assert svc.ui_state.ui.session_doc.prose_mode is False

    def test_null_bool_in_persisted_file_does_not_block_load(self, fresh_campaign):
        # The exact failure mode that triggered the --session-dir bug: a
        # ui_state.yaml with `prose_mode: null` from a prior write.
        (fresh_campaign / UI_STATE_NAME).write_text(
            "version: 2\nui:\n  session_doc:\n    prose_mode: null\n"
            "    reflections: null\n    use_enhanced_sections: null\n"
            "    batch: null\n    scrub_enabled: null\n",
            encoding="utf-8",
        )
        svc = CampaignConfigService(fresh_campaign)
        sd = svc.ui_state.ui.session_doc
        assert sd.prose_mode is False
        assert sd.reflections is False
        assert sd.use_enhanced_sections is False
        assert sd.batch is False
        assert sd.scrub_enabled is False


# ── update_section / update_local ─────────────────────────────────────────


class TestUpdateSection:
    def test_update_section_persists(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"narrate_tokens": 12000})

        # Re-read from disk.
        on_disk = yaml.safe_load((fresh_campaign / UI_STATE_NAME).read_text())
        assert on_disk["ui"]["session_doc"]["narrate_tokens"] == 12000

    def test_update_section_merges_not_replaces(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"narrate_tokens": 12000})
        svc.update_section("session_doc", {"voice_dir": "voice/"})
        # Both fields present after the second call.
        assert svc.ui_state.ui.session_doc.narrate_tokens == 12000
        assert svc.ui_state.ui.session_doc.voice_dir == "voice/"

    def test_unknown_section_rejected(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        with pytest.raises(ValueError, match="unknown UI section"):
            svc.update_section("server", {"port": 6001})

    def test_update_local(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_local({"server": {"port": 6001}})
        on_disk = yaml.safe_load((fresh_campaign / LOCAL_CONFIG_NAME).read_text())
        assert on_disk["server"]["port"] == 6001


# ── Atomic writes & concurrency ──────────────────────────────────────────


class TestAtomicWrites:
    def test_replace_failure_leaves_existing_file_intact(
        self, fresh_campaign, monkeypatch
    ):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"narrate_tokens": 11111})
        before = (fresh_campaign / UI_STATE_NAME).read_bytes()

        original_replace = os.replace

        def boom(*args, **kwargs):
            raise OSError("simulated mid-write crash")

        monkeypatch.setattr(os, "replace", boom)

        with pytest.raises(OSError, match="simulated"):
            svc.update_section("session_doc", {"narrate_tokens": 22222})

        # Original file unchanged.
        assert (fresh_campaign / UI_STATE_NAME).read_bytes() == before

        # Restore so cleanup works.
        monkeypatch.setattr(os, "replace", original_replace)

    def test_concurrent_writes_to_same_section_no_torn_file(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        errors: list[BaseException] = []

        def writer(value: int) -> None:
            try:
                svc.update_section("session_doc", {"narrate_tokens": value})
            except BaseException as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(v,)) for v in range(100, 200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        # File is parseable (no torn YAML) — that's the actual invariant.
        on_disk = yaml.safe_load((fresh_campaign / UI_STATE_NAME).read_text())
        assert isinstance(on_disk, dict)
        # Whatever the last writer was, it's a valid value from our range.
        assert 100 <= on_disk["ui"]["session_doc"]["narrate_tokens"] < 200


# ── Resolved view ────────────────────────────────────────────────────────


class TestResolvedView:
    def test_campaign_relative_path_resolves_against_campaign_dir(
        self, fresh_campaign
    ):
        # voice_dir is campaign-scoped (lives at <campaign>/voice/).
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"voice_dir": "voice/"})
        resolved = svc.resolved()
        voice = resolved["ui"]["session_doc"]["voice_dir"]
        assert Path(voice).is_absolute()
        assert voice == str((fresh_campaign / "voice").resolve())

    def test_session_relative_path_resolves_against_session_dir(
        self, fresh_campaign
    ):
        # The user-reported bug: a relative `session_summary` was landing
        # in the campaign root instead of the session dir.
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"session_summary": "session-summary.md"})
        svc.update_section("grounding", {"summaries": "summaries.md"})
        # Without a session_dir set, the legacy fallback to campaign_dir
        # still applies.
        no_sd = svc.resolved()
        assert no_sd["ui"]["session_doc"]["session_summary"] == \
            str((fresh_campaign / "session-summary.md").resolve())

        # With session_dir set, session-scoped paths resolve there.
        svc2 = CampaignConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": "summaries/sess1"},
        )
        svc2.update_section(
            "session_doc", {"session_summary": "session-summary.md"}
        )
        svc2.update_section("grounding", {"summaries": "summaries.md"})
        with_sd = svc2.resolved()
        # session-scoped → resolves against session_dir
        assert with_sd["ui"]["session_doc"]["session_summary"] == str(
            (fresh_campaign / "summaries" / "sess1" / "session-summary.md").resolve()
        )
        # campaign-scoped → still campaign root, even with session_dir set
        assert with_sd["ui"]["grounding"]["summaries"] == str(
            (fresh_campaign / "summaries.md").resolve()
        )

    def test_absolute_path_overrides_base(self, fresh_campaign, tmp_path):
        # Absolute paths pass through regardless of base hint.
        elsewhere = tmp_path / "elsewhere" / "file.md"
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"session_summary": str(elsewhere)})
        resolved = svc.resolved()
        assert resolved["ui"]["session_doc"]["session_summary"] == \
            str(elsewhere.resolve())

    def test_non_path_fields_pass_through(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_section("session_doc", {"narrate_tokens": 12000, "narration_genre": "lyric"})
        resolved = svc.resolved()
        assert resolved["ui"]["session_doc"]["narrate_tokens"] == 12000
        assert resolved["ui"]["session_doc"]["narration_genre"] == "lyric"

    def test_resolved_includes_campaign_dir(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        resolved = svc.resolved()
        assert resolved["campaign_dir"] == str(fresh_campaign.resolve())

    def test_boot_session_dir_rebases_stale_absolute_paths(self, fresh_campaign):
        """The user-reported bug: ``ui_state.yaml`` had session-scoped fields
        persisted as absolute paths under the previous session dir. Booting
        with ``--session-dir`` overrode ``runtime.session_dir`` but the
        absolute paths in ``ui.session_doc.*`` passed through unchanged. The
        rebase pass in ``resolved()`` is the fix."""
        old_sd = fresh_campaign / "summaries" / "20260505"
        new_sd = fresh_campaign / "summaries" / "20260512"
        for d in (old_sd, new_sd):
            d.mkdir(parents=True)

        # Persist the stale state — these are what the previous session left
        # behind in ui_state.yaml.
        svc_init = CampaignConfigService(fresh_campaign)
        svc_init.update_section(
            "session_doc",
            {
                "scene_extractions_dir": str(old_sd / "scene_extractions_new"),
                "narration_dir": str(old_sd / "narration"),
                "session_summary": str(old_sd / "session-summary.md"),
                "voice_dir": str(fresh_campaign / "voice"),  # campaign-scoped — must NOT rebase
            },
        )
        svc_init.update_runtime({"session_dir": str(old_sd)})

        # New launch with --session-dir 20260512.
        svc = CampaignConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(new_sd)},
        )
        r = svc.resolved()

        assert r["runtime"]["session_dir"] == str(new_sd.resolve())
        assert r["ui"]["session_doc"]["scene_extractions_dir"] == str(
            (new_sd / "scene_extractions_new").resolve()
        )
        assert r["ui"]["session_doc"]["narration_dir"] == str(
            (new_sd / "narration").resolve()
        )
        assert r["ui"]["session_doc"]["session_summary"] == str(
            (new_sd / "session-summary.md").resolve()
        )
        # Campaign-scoped path stays put.
        assert r["ui"]["session_doc"]["voice_dir"] == str(
            (fresh_campaign / "voice").resolve()
        )

    def test_rebase_handles_persisted_paths_under_unrelated_session(
        self, fresh_campaign
    ):
        """The Phandalin failure mode: persisted runtime.session_dir was
        ``summaries/20260429`` but session_doc fields were under
        ``summaries/20260505`` (different historical save). The rebase pass
        must key off the path PATTERN, not the persisted runtime value."""
        for d in (
            fresh_campaign / "summaries" / "20260429",
            fresh_campaign / "summaries" / "20260505",
            fresh_campaign / "summaries" / "20260512",
        ):
            d.mkdir(parents=True)
        wrong_sd = fresh_campaign / "summaries" / "20260505"
        stale_runtime_sd = fresh_campaign / "summaries" / "20260429"
        new_sd = fresh_campaign / "summaries" / "20260512"

        svc_init = CampaignConfigService(fresh_campaign)
        svc_init.update_section(
            "session_doc",
            {"narration_dir": str(wrong_sd / "narration")},
        )
        svc_init.update_runtime({"session_dir": str(stale_runtime_sd)})

        svc = CampaignConfigService(
            fresh_campaign,
            boot_overrides={"runtime.session_dir": str(new_sd)},
        )
        r = svc.resolved()
        assert r["ui"]["session_doc"]["narration_dir"] == str(
            (new_sd / "narration").resolve()
        )

    def test_rebase_only_runs_when_boot_overrides_session_dir(
        self, fresh_campaign
    ):
        """Without a --session-dir CLI flag, persisted absolute paths must pass
        through unchanged — even if ``runtime.session_dir`` happens to point
        somewhere else. The rebase is a fix-the-stale-data behavior gated on
        an explicit boot override."""
        old_sd = fresh_campaign / "summaries" / "20260505"
        runtime_sd = fresh_campaign / "summaries" / "20260512"
        for d in (old_sd, runtime_sd):
            d.mkdir(parents=True)

        svc_init = CampaignConfigService(fresh_campaign)
        svc_init.update_section(
            "session_doc", {"narration_dir": str(old_sd / "narration")}
        )
        svc_init.update_runtime({"session_dir": str(runtime_sd)})

        # No boot override.
        svc = CampaignConfigService(fresh_campaign)
        r = svc.resolved()
        assert r["ui"]["session_doc"]["narration_dir"] == str(
            (old_sd / "narration").resolve()
        )

    def test_explicit_boot_override_wins_over_rebase(self, fresh_campaign):
        """If the CLI passes both --session-dir AND an explicit override for a
        session-scoped field, the explicit one must win."""
        old_sd = fresh_campaign / "summaries" / "old"
        new_sd = fresh_campaign / "summaries" / "new"
        custom = fresh_campaign / "custom" / "narration"
        for d in (old_sd, new_sd, custom):
            d.mkdir(parents=True)

        svc_init = CampaignConfigService(fresh_campaign)
        svc_init.update_section(
            "session_doc", {"narration_dir": str(old_sd / "narration")}
        )
        svc_init.update_runtime({"session_dir": str(old_sd)})

        svc = CampaignConfigService(
            fresh_campaign,
            boot_overrides={
                "runtime.session_dir": str(new_sd),
                "session_doc.narration_dir": str(custom),
            },
        )
        r = svc.resolved()
        assert r["ui"]["session_doc"]["narration_dir"] == str(custom.resolve())


# ── update_runtime ────────────────────────────────────────────────────────


class TestUpdateRuntime:
    def test_update_runtime_persists(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_runtime({"session_dir": "summaries/sess1", "default_model": "claude-opus-4-6"})
        on_disk = yaml.safe_load((fresh_campaign / UI_STATE_NAME).read_text())
        assert on_disk["runtime"]["session_dir"] == "summaries/sess1"
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"

    def test_update_runtime_merges(self, fresh_campaign):
        svc = CampaignConfigService(fresh_campaign)
        svc.update_runtime({"session_dir": "summaries/sess1"})
        svc.update_runtime({"default_model": "claude-opus-4-6"})
        assert svc.ui_state.runtime.session_dir == "summaries/sess1"
        assert svc.ui_state.runtime.default_model == "claude-opus-4-6"
