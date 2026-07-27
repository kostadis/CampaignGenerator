"""Tests for server/migrate_ensemble_config.py — Phase 5 of
docs/config/ensemble-isolation.md.

The CLI has to rescue data from a section the current UISection model no
longer declares, so the tests build pre-migration ui_state.yaml files by hand
rather than through UIState (which would drop ui.ensemble on load — exactly
the failure the CLI's raw yaml.safe_load exists to avoid).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.ensemble_config_shared import EnsembleConfig, load_ensemble_config
from server.migrate_ensemble_config import build_ensemble_config, main

CONFIG_SUBDIR = "config"


def _ui_state(campaign: Path, ensemble_section: dict) -> Path:
    p = campaign / CONFIG_SUBDIR / "ui_state.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump({"version": 3, "ui": {"ensemble": ensemble_section}}),
        encoding="utf-8",
    )
    return p


# ── build_ensemble_config: the pure mapping function ───────────────────────

class TestBuildEnsembleConfig:
    def test_no_ui_key_is_nothing_to_migrate(self):
        assert build_ensemble_config({}) == (None, [])

    def test_absent_or_empty_section_is_nothing_to_migrate(self):
        assert build_ensemble_config({"ui": {}}) == (None, [])
        assert build_ensemble_config({"ui": {"ensemble": {}}}) == (None, [])

    def test_chapters_glob_moves_under_paths(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {"chapters_glob": "book/ch_*.md"}}})
        assert cfg.paths.chapters_glob == "book/ch_*.md"

    def test_scalars_carry_over(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "chapters_selected": ["a.md", "b.md"],
        }}})
        assert cfg.chapters_selected == ["a.md", "b.md"]

    def test_known_names_and_aliases_path_are_dropped_silently(self):
        """Retired in favor of the entity registry (docs/entity_registry.yaml)
        — an intended drop, so they must NOT show up in the 'unrecognised
        keys' warning the operator is asked to review, and must not survive
        onto the built config."""
        cfg, skipped = build_ensemble_config({"ui": {"ensemble": {
            "chapters_selected": ["a.md"],
            "known_names": ["docs/inv.md"],
            "aliases_path": "docs/ensemble/aliases.json",
        }}})
        assert "known_names" not in skipped
        assert "aliases_path" not in skipped
        assert not hasattr(cfg, "known_names")
        assert not hasattr(cfg, "aliases_path")

    def test_empty_chapter_selection_is_preserved_not_dropped(self):
        """Principle X: an empty selection means 'nothing selected', which is
        a real state, not 'unset'."""
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "chapters_selected": [],
        }}})
        assert cfg.chapters_selected == []

    def test_campaign_dir_is_dropped_silently(self):
        """Platform-tier (Phase 0) — an intended drop, so it must NOT show up
        in the 'unrecognised keys' warning the operator is asked to review."""
        cfg, skipped = build_ensemble_config({"ui": {"ensemble": {
            "campaign_dir": "/home/x/campaign", "chapters_selected": ["a.md"],
        }}})
        assert "campaign_dir" not in skipped
        assert not hasattr(cfg, "campaign_dir")

    def test_unrecognised_keys_are_reported_not_discarded_quietly(self):
        _, skipped = build_ensemble_config({"ui": {"ensemble": {
            "chapters_selected": ["a.md"], "some_stale_key": 1, "another": 2,
        }}})
        assert sorted(skipped) == ["another", "some_stale_key"]

    def test_only_unrecognised_keys_means_nothing_to_migrate(self):
        cfg, skipped = build_ensemble_config({"ui": {"ensemble": {"junk": 1}}})
        assert cfg is None
        assert skipped == ["junk"]

    # ── backends ──

    def test_singular_endpoint_is_lifted_to_a_list(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "extract": {"backend": "dgx", "endpoint": "http://spark:8001/v1"},
        }}})
        assert cfg.extract.endpoints == ["http://spark:8001/v1"]

    def test_plural_endpoints_win_over_singular(self):
        """The plural is what the shipped frontend and both run routes use."""
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "extract": {"backend": "dgx",
                        "endpoint": "http://old:8001/v1",
                        "endpoints": ["http://spark:8001/v1", "http://spark2:8001/v1"]},
        }}})
        assert cfg.extract.endpoints == ["http://spark:8001/v1", "http://spark2:8001/v1"]

    def test_both_stages_migrate_independently(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "extract": {"backend": "dgx", "endpoints": ["http://spark:8001/v1"]},
            "synthesize": {"backend": "anthropic", "model": "claude-opus-5"},
        }}})
        assert cfg.extract.backend == "dgx"
        assert cfg.synthesize.backend == "anthropic"
        assert cfg.synthesize.model == "claude-opus-5"
        assert cfg.synthesize.endpoints == []

    # ── the six planning_* keys ──

    def test_planning_string_blobs_become_lists(self):
        """They were bound to <textarea>s, so they were stored newline-joined."""
        cfg, skipped = build_ensemble_config({"ui": {"ensemble": {
            "planning_npc": "docs/npcs/a.md\ndocs/npcs/b.md",
            "planning_arc_scores": "docs/tracking/a.md",
            "planning_context": " docs/world_state.md \n\n docs/party.md ",
            "planning_force_include": "",
        }}})
        assert skipped == []
        assert cfg.planning.npc == ["docs/npcs/a.md", "docs/npcs/b.md"]
        assert cfg.planning.arc_scores == ["docs/tracking/a.md"]
        assert cfg.planning.context == ["docs/world_state.md", "docs/party.md"]
        assert cfg.planning.force_include == []

    def test_planning_literals_carry_over(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "planning_synth_mode": "flat", "planning_depth": "full",
        }}})
        assert cfg.planning.synth_mode == "flat"
        assert cfg.planning.depth == "full"

    def test_an_already_list_planning_value_is_accepted(self):
        cfg, _ = build_ensemble_config({"ui": {"ensemble": {
            "planning_npc": ["docs/npcs/a.md"],
        }}})
        assert cfg.planning.npc == ["docs/npcs/a.md"]

    def test_a_bad_planning_literal_still_fails_validation(self):
        """The migration must not smuggle a value past the strict schema."""
        with pytest.raises(Exception):
            build_ensemble_config({"ui": {"ensemble": {"planning_depth": "deep"}}})

    def test_a_full_pre_migration_section_round_trips(self):
        """known_names/aliases_path are included here too, to prove a section
        that still carries the retired legacy keys migrates cleanly rather
        than tripping the 'unrecognised keys' warning."""
        cfg, skipped = build_ensemble_config({"ui": {"ensemble": {
            "campaign_dir": "/home/x/c",
            "chapters_glob": "docs/chapters/chapter_*.md",
            "chapters_selected": ["docs/chapters/chapter_01.md"],
            "known_names": ["docs/background/inv.md"],
            "aliases_path": "docs/ensemble/aliases.json",
            "extract": {"backend": "dgx", "endpoint": "http://spark:8001/v1",
                        "model": "qwen3-next"},
            "synthesize": {"backend": "anthropic", "model": "claude-opus-5"},
            "planning_synth_mode": "flat",
            "planning_npc": "docs/npcs/a.md\ndocs/npcs/b.md",
            "planning_depth": "full",
        }}})
        assert skipped == []
        assert isinstance(cfg, EnsembleConfig)
        assert cfg.extract.endpoints == ["http://spark:8001/v1"]
        assert cfg.planning.npc == ["docs/npcs/a.md", "docs/npcs/b.md"]
        assert not hasattr(cfg, "known_names")
        assert not hasattr(cfg, "aliases_path")


# ── The CLI itself ─────────────────────────────────────────────────────────

class TestCli:
    def test_writes_ensemble_yaml(self, tmp_path, capsys):
        _ui_state(tmp_path, {"chapters_selected": ["a.md"], "chapters_glob": "b/*.md"})
        assert main(["--campaign-dir", str(tmp_path)]) == 0

        dest = tmp_path / CONFIG_SUBDIR / "ensemble.yaml"
        assert dest.exists()
        cfg = load_ensemble_config(dest)
        assert cfg.chapters_selected == ["a.md"]
        assert cfg.paths.chapters_glob == "b/*.md"
        assert "migrated ensemble config" in capsys.readouterr().out

    def test_missing_ui_state_is_a_clean_noop(self, tmp_path, capsys):
        assert main(["--campaign-dir", str(tmp_path)]) == 0
        assert "nothing to migrate" in capsys.readouterr().out
        assert not (tmp_path / CONFIG_SUBDIR / "ensemble.yaml").exists()

    def test_refuses_to_clobber_without_force(self, tmp_path, capsys):
        _ui_state(tmp_path, {"chapters_selected": ["a.md"]})
        dest = tmp_path / CONFIG_SUBDIR / "ensemble.yaml"
        dest.write_text("chapters_selected: [existing.md]\n", encoding="utf-8")

        assert main(["--campaign-dir", str(tmp_path)]) == 1
        assert "refusing to overwrite" in capsys.readouterr().err
        assert load_ensemble_config(dest).chapters_selected == ["existing.md"]

    def test_force_overwrites(self, tmp_path):
        _ui_state(tmp_path, {"chapters_selected": ["a.md"]})
        dest = tmp_path / CONFIG_SUBDIR / "ensemble.yaml"
        dest.write_text("chapters_selected: [existing.md]\n", encoding="utf-8")

        assert main(["--campaign-dir", str(tmp_path), "--force"]) == 0
        assert load_ensemble_config(dest).chapters_selected == ["a.md"]

    def test_skipped_keys_are_surfaced_to_the_operator(self, tmp_path, capsys):
        _ui_state(tmp_path, {"chapters_selected": ["a.md"], "mystery_key": 1})
        assert main(["--campaign-dir", str(tmp_path)]) == 0
        assert "mystery_key" in capsys.readouterr().out

    def test_honours_a_custom_config_dir(self, tmp_path):
        p = tmp_path / "cfgdir" / "ui_state.yaml"
        p.parent.mkdir(parents=True)
        p.write_text(
            yaml.safe_dump({"ui": {"ensemble": {"chapters_selected": ["x.md"]}}}),
            encoding="utf-8",
        )
        assert main(["--campaign-dir", str(tmp_path), "--config-dir", "cfgdir"]) == 0
        assert (tmp_path / "cfgdir" / "ensemble.yaml").exists()

    def test_the_migrated_file_is_what_the_service_reads(self, tmp_path):
        """End-to-end: the CLI's output is loadable by the running service,
        not just by the loader it happens to call."""
        from server.ensemble_config_service import EnsembleConfigService

        _ui_state(tmp_path, {
            "extract": {"backend": "dgx", "endpoint": "http://spark:8001/v1"},
            "planning_npc": "docs/npcs/a.md",
        })
        assert main(["--campaign-dir", str(tmp_path)]) == 0

        cfg = EnsembleConfigService(tmp_path / CONFIG_SUBDIR).resolved()
        assert cfg.extract.endpoints == ["http://spark:8001/v1"]
        assert cfg.planning.npc == ["docs/npcs/a.md"]
