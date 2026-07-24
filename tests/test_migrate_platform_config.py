"""Tests for the one-shot ``server/migrate_platform_config`` CLI — Phase 3 of
docs/config/platform-isolation.md (O3).

Moves the ``runtime`` key out of ``ui_state.yaml`` into the dedicated
``platform.yaml`` ``PlatformConfigService`` now owns exclusively.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.migrate_platform_config import build_platform_document, main  # noqa: E402
from server.platform_config_service import PLATFORM_CONFIG_NAME  # noqa: E402
from server.platform_config_shared import load_platform_config  # noqa: E402

CONFIG_SUBDIR = "config"

OLD_UI_STATE = """\
version: 2
ui:
  vtt_summary:
    input: x.vtt
runtime:
  default_model: claude-opus-4-6
  session_dir: summaries/session1
"""


def _write_old_ui_state(campaign_dir: Path, body: str = OLD_UI_STATE) -> Path:
    path = campaign_dir / CONFIG_SUBDIR / "ui_state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ── build_platform_document: the pure mapping function ──────────────────


class TestBuildPlatformDocument:
    def test_maps_runtime_to_platform_document(self):
        raw = yaml.safe_load(OLD_UI_STATE)
        doc = build_platform_document(raw)
        assert doc is not None
        assert doc.runtime.default_model == "claude-opus-4-6"
        assert doc.runtime.session_dir == "summaries/session1"

    def test_no_runtime_key_returns_none(self):
        assert build_platform_document({}) is None
        assert build_platform_document({"version": 2}) is None
        assert build_platform_document({"version": 2, "ui": {}}) is None

    def test_empty_runtime_dict_returns_none(self):
        raw = {"version": 2, "runtime": {}}
        assert build_platform_document(raw) is None

    def test_only_unknown_runtime_keys_returns_none(self):
        # A pre-Phase-3 runtime block was extra="allow" — nothing in this
        # codebase ever wrote an unrecognized key there, but the migrator
        # must not choke on (or silently invent state from) one either.
        raw = {"version": 2, "runtime": {"bogus_field": "x"}}
        assert build_platform_document(raw) is None

    def test_session_dir_only_still_migrates(self):
        raw = {"version": 2, "runtime": {"session_dir": "summaries/s1"}}
        doc = build_platform_document(raw)
        assert doc is not None
        assert doc.runtime.session_dir == "summaries/s1"
        # default_model falls back to PlatformRuntime's own default_factory.
        assert doc.runtime.default_model

    def test_default_model_only_still_migrates(self):
        raw = {"version": 2, "runtime": {"default_model": "claude-opus-4-6"}}
        doc = build_platform_document(raw)
        assert doc is not None
        assert doc.runtime.default_model == "claude-opus-4-6"
        assert doc.runtime.session_dir is None

    def test_unknown_keys_alongside_known_ones_are_dropped_not_preserved(self):
        raw = {
            "version": 2,
            "runtime": {
                "default_model": "claude-opus-4-6",
                "session_dir": "summaries/s1",
                "bogus_field": "x",
            },
        }
        doc = build_platform_document(raw)
        assert doc is not None
        assert doc.runtime.default_model == "claude-opus-4-6"
        assert doc.runtime.session_dir == "summaries/s1"
        assert not hasattr(doc.runtime, "bogus_field")


# ── CLI end-to-end ────────────────────────────────────────────────────────


class TestMigrateCli:
    def test_migrates_old_ui_state_to_platform_yaml(self, tmp_path, capsys):
        _write_old_ui_state(tmp_path)

        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0

        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        assert dest.exists()
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"
        assert on_disk["runtime"]["session_dir"] == "summaries/session1"

        out = capsys.readouterr().out
        assert "migrated platform config" in out
        assert str(dest) in out

    def test_migrated_session_dir_copied_as_is_not_re_resolved(self, tmp_path):
        # The old ui_state stored session_dir relative already — the CLI
        # must NOT re-resolve it to absolute.
        _write_old_ui_state(tmp_path)
        main(["--campaign-dir", str(tmp_path)])
        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["runtime"]["session_dir"] == "summaries/session1"

    def test_missing_ui_state_reports_nothing_to_migrate(self, tmp_path, capsys):
        (tmp_path / CONFIG_SUBDIR).mkdir(parents=True, exist_ok=True)
        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        assert not (tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).exists()

    def test_ui_state_without_runtime_reports_nothing_to_migrate(self, tmp_path, capsys):
        _write_old_ui_state(
            tmp_path,
            "version: 2\nui:\n  vtt_summary:\n    input: x.vtt\n",
        )
        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        assert not (tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).exists()

    def test_campaign_that_never_had_runtime_state(self, tmp_path, capsys):
        # No ui_state.yaml at all — a brand-new campaign that has never
        # touched the sidebar model picker or session_dir.
        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        assert not (tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME).exists()

    def test_idempotent_second_run_reports_nothing_to_migrate(self, tmp_path, capsys):
        # Running the CLI twice against an unchanged source (ui_state.yaml
        # is never modified by this migration — see module docstring) must
        # NOT refuse-to-overwrite on the second run. The destination
        # already reflects the source's runtime data, so there is nothing
        # left to do.
        _write_old_ui_state(tmp_path)

        rc1 = main(["--campaign-dir", str(tmp_path)])
        assert rc1 == 0
        capsys.readouterr()  # drain first run's output

        rc2 = main(["--campaign-dir", str(tmp_path)])
        assert rc2 == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out

        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"
        assert on_disk["runtime"]["session_dir"] == "summaries/session1"

    def test_refuses_to_overwrite_genuinely_different_existing_file(
        self, tmp_path, capsys
    ):
        _write_old_ui_state(tmp_path)
        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            "runtime:\n  default_model: claude-sonnet-4-6\n  session_dir: summaries/other\n",
            encoding="utf-8",
        )

        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 1
        # Untouched.
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["runtime"]["session_dir"] == "summaries/other"
        err = capsys.readouterr().err
        assert "refusing to overwrite" in err

    def test_force_overwrites_genuinely_different_existing_file(self, tmp_path):
        _write_old_ui_state(tmp_path)
        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            "runtime:\n  default_model: claude-sonnet-4-6\n  session_dir: summaries/other\n",
            encoding="utf-8",
        )

        rc = main(["--campaign-dir", str(tmp_path), "--force"])
        assert rc == 0
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["runtime"]["default_model"] == "claude-opus-4-6"
        assert on_disk["runtime"]["session_dir"] == "summaries/session1"

    def test_custom_config_dir(self, tmp_path, capsys):
        _write_old_ui_state_at(tmp_path / "myconfig")
        rc = main(["--campaign-dir", str(tmp_path), "--config-dir", "myconfig"])
        assert rc == 0
        assert (tmp_path / "myconfig" / PLATFORM_CONFIG_NAME).exists()

    def test_migrated_file_loads_cleanly_through_load_platform_config(self, tmp_path):
        # The migrated file must be readable by the same loader
        # PlatformConfigService uses at boot, not just parseable YAML.
        _write_old_ui_state(tmp_path)
        main(["--campaign-dir", str(tmp_path)])
        dest = tmp_path / CONFIG_SUBDIR / PLATFORM_CONFIG_NAME
        cfg = load_platform_config(dest)
        assert cfg.runtime.default_model == "claude-opus-4-6"
        assert cfg.runtime.session_dir == "summaries/session1"


def _write_old_ui_state_at(config_dir: Path, body: str = OLD_UI_STATE) -> Path:
    path = config_dir / "ui_state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
