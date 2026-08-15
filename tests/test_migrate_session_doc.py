"""Tests for the one-shot ``server/migrate_session_doc`` CLI — Phase 5 of
docs/config/session-editor-isolation.md.

Moves a pre-Phase-5 ``ui.session_doc`` + ``ui.profiles`` fragment out of
``ui_state.yaml`` into the dedicated ``session_doc.yaml``
``SessionEditorConfigService`` now owns exclusively.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.migrate_session_doc import build_grouped_config, main  # noqa: E402
from server.session_editor_config_service import SESSION_DOC_FILENAME  # noqa: E402

CONFIG_SUBDIR = "config"

OLD_UI_STATE = """\
version: 2
ui:
  session_doc:
    session: gm-assist.md
    session_summary: session-summary.md
    scene_extractions_dir: scene_extractions
    roleplay_dir: vtt_roleplay_extractions
    party: ../party.md
    voice_dir: ../voice
    characters: "Zalthir, Grygum"
    gm_player: Kostadis
    narrate_tokens: 12000
    prose_mode: true
    narration_genre: noir
    backend: dgx
    dgx_endpoint: http://box:8001
    dgx_model: Qwen-X
    scrub_enabled: true
  profiles:
    profiles:
      - name: Fast Draft
        knobs:
          narrate_tokens: 4000
    active: Fast Draft
"""


def _write_old_ui_state(campaign_dir: Path, body: str = OLD_UI_STATE) -> Path:
    path = campaign_dir / CONFIG_SUBDIR / "ui_state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ── build_grouped_config: the pure mapping function ─────────────────────


class TestBuildGroupedConfig:
    def test_maps_flat_to_grouped_shape(self):
        raw = yaml.safe_load(OLD_UI_STATE)
        cfg = build_grouped_config(raw)
        assert cfg is not None
        assert cfg.paths.session_recap == "gm-assist.md"
        assert cfg.paths.scene_extractions_dir == "scene_extractions"
        # `roleplay_dir` is still in OLD_UI_STATE above (real campaigns have
        # it) but was dropped from TYPED_SESSION_DOC_TO_GROUPED when the
        # vtt_summary chain retired: it has no grouped target any more, so
        # the migration must leave it behind rather than write it into a
        # field EditorPaths no longer declares.
        assert not hasattr(cfg.paths, "roleplay_extractions_dir")
        assert "roleplay" not in cfg.model_dump_json()
        # `characters` and `gm_player` are still in OLD_UI_STATE above but were
        # dropped from TYPED_SESSION_DOC_TO_GROUPED by feature 009: the whole
        # `roster` group is gone. The narrating cast is derived from party.yaml
        # and who plays what lives in players.yaml, so this migration has no
        # destination to write them to. Same treatment as `roleplay_dir` and
        # `narration_genre` — reported as unrecognised and left behind, rather
        # than written into a field that no longer exists.
        # `server/migrate_players_config.py` is what harvests them.
        assert not hasattr(cfg, "roster")
        assert "Grygum" not in cfg.model_dump_json()
        assert cfg.narrate.tokens == 12000
        assert cfg.narrate.prose_mode is True
        # `narration_genre` is still in OLD_UI_STATE above but was dropped from
        # TYPED_SESSION_DOC_TO_GROUPED by #276 fix 2: the genre rulebook is a
        # file at `paths.genre_file`, and this migration cannot relocate a
        # pasted string into a file on disk — choosing that file's contents is a
        # GM decision. Same treatment as `roleplay_dir` above: left behind in
        # ui_state.yaml, visible, rather than written into a field that is gone.
        assert not hasattr(cfg.narrate, "genre")
        assert "noir" not in cfg.model_dump_json()
        assert cfg.paths.genre_file is None
        assert cfg.backends.active == "dgx"
        assert cfg.backends.dgx.endpoint == "http://box:8001"
        assert cfg.backends.dgx.model == "Qwen-X"
        assert cfg.scrub.enabled is True
        assert cfg.profiles[0].name == "Fast Draft"
        assert cfg.profiles[0].knobs["narrate_tokens"] == 4000
        assert cfg.active_profile == "Fast Draft"

    def test_no_ui_key_returns_none(self):
        assert build_grouped_config({}) is None
        assert build_grouped_config({"version": 2}) is None

    def test_empty_session_doc_and_profiles_returns_none(self):
        raw = {"version": 2, "ui": {"session_doc": {}, "profiles": {}}}
        assert build_grouped_config(raw) is None

    def test_session_doc_only_still_migrates(self):
        raw = {"version": 2, "ui": {"session_doc": {"narrate_tokens": 8000}}}
        cfg = build_grouped_config(raw)
        assert cfg is not None
        assert cfg.narrate.tokens == 8000
        assert cfg.profiles == []
        assert cfg.active_profile is None

    def test_profiles_only_still_migrates(self):
        raw = {
            "version": 2,
            "ui": {"profiles": {"profiles": [{"name": "A"}], "active": "A"}},
        }
        cfg = build_grouped_config(raw)
        assert cfg is not None
        assert cfg.profiles[0].name == "A"
        assert cfg.active_profile == "A"
        # No session_doc data → path/narrate/etc. stay at defaults.
        assert cfg.paths.session_recap is None


# ── CLI end-to-end ────────────────────────────────────────────────────────


class TestMigrateCli:
    def test_migrates_old_ui_state_to_session_doc_yaml(self, tmp_path, capsys):
        _write_old_ui_state(tmp_path)

        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0

        dest = tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME
        assert dest.exists()
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["backends"]["dgx"]["model"] == "Qwen-X"
        assert on_disk["backends"]["active"] == "dgx"
        assert on_disk["narrate"]["tokens"] == 12000
        assert on_disk["profiles"][0]["name"] == "Fast Draft"
        assert on_disk["active_profile"] == "Fast Draft"

        out = capsys.readouterr().out
        assert "migrated session-editor config" in out
        assert str(dest) in out

    def test_migrated_paths_copied_as_is_not_re_resolved(self, tmp_path):
        # The old ui_state stored session-scoped paths relative already —
        # the CLI must NOT re-resolve them to absolute.
        _write_old_ui_state(tmp_path)
        main(["--campaign-dir", str(tmp_path)])
        dest = tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["paths"]["scene_extractions_dir"] == "scene_extractions"
        assert on_disk["paths"]["party"] == "../party.md"

    def test_refuses_to_overwrite_existing_without_force(self, tmp_path, capsys):
        _write_old_ui_state(tmp_path)
        dest = tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("narrate:\n  tokens: 1\n", encoding="utf-8")

        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 1
        # Untouched.
        assert dest.read_text(encoding="utf-8") == "narrate:\n  tokens: 1\n"
        err = capsys.readouterr().err
        assert "refusing to overwrite" in err

    def test_force_overwrites_existing(self, tmp_path):
        _write_old_ui_state(tmp_path)
        dest = tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("narrate:\n  tokens: 1\n", encoding="utf-8")

        rc = main(["--campaign-dir", str(tmp_path), "--force"])
        assert rc == 0
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["narrate"]["tokens"] == 12000

    def test_missing_ui_state_reports_nothing_to_migrate(self, tmp_path, capsys):
        (tmp_path / CONFIG_SUBDIR).mkdir(parents=True, exist_ok=True)
        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        assert not (tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME).exists()

    def test_ui_state_without_session_doc_reports_nothing_to_migrate(self, tmp_path, capsys):
        _write_old_ui_state(
            tmp_path,
            "version: 2\nui:\n  vtt_summary:\n    input: x.vtt\n",
        )
        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        assert not (tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME).exists()

    def test_nothing_to_migrate_does_not_refuse_even_if_dest_exists(self, tmp_path, capsys):
        # An empty/absent source must report "nothing to migrate" rather
        # than a refuse-to-overwrite error, even if a session_doc.yaml
        # already happens to exist (e.g. the editor was already used).
        _write_old_ui_state(tmp_path, "version: 2\nui:\n  vtt_summary: {}\n")
        dest = tmp_path / CONFIG_SUBDIR / SESSION_DOC_FILENAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("narrate:\n  tokens: 9999\n", encoding="utf-8")

        rc = main(["--campaign-dir", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "nothing to migrate" in out
        # Existing file left untouched.
        on_disk = yaml.safe_load(dest.read_text(encoding="utf-8"))
        assert on_disk["narrate"]["tokens"] == 9999

    def test_custom_config_dir(self, tmp_path, capsys):
        _write_old_ui_state_at(tmp_path / "myconfig")
        rc = main(["--campaign-dir", str(tmp_path), "--config-dir", "myconfig"])
        assert rc == 0
        assert (tmp_path / "myconfig" / SESSION_DOC_FILENAME).exists()


def _write_old_ui_state_at(config_dir: Path, body: str = OLD_UI_STATE) -> Path:
    path = config_dir / "ui_state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
