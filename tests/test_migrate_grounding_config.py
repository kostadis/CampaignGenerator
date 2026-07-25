"""Tests for the one-shot ui.<grounding sections> -> grounding.yaml migration.

Phase 10 of ``docs/config/grounding-isolation.md``. Mirrors
``test_migrate_ensemble_config.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.grounding_config_shared import load_grounding_config  # noqa: E402
from server.migrate_grounding_config import (  # noqa: E402
    build_grounding_config,
    main,
)


def _write_ui_state(tmp_path: Path, ui: dict) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    p = cfg / "ui_state.yaml"
    p.write_text(yaml.safe_dump({"version": 4, "ui": ui}), encoding="utf-8")
    return p


# ── build_grounding_config ─────────────────────────────────────────────────

def test_no_ui_state_is_nothing_to_migrate():
    cfg, skipped, _ = build_grounding_config({})
    assert cfg is None and not skipped


def test_empty_sections_are_nothing_to_migrate():
    cfg, _, _ = build_grounding_config({"ui": {"campaign_state": {}, "distill": {}}})
    assert cfg is None


def test_grounding_summaries_becomes_the_root_pointer():
    cfg, _, _ = build_grounding_config(
        {"ui": {"grounding": {"summaries": "docs/summaries.md"}}}
    )
    assert cfg is not None and cfg.summaries == "docs/summaries.md"


def test_per_section_summaries_becomes_that_docs_input():
    cfg, _, _ = build_grounding_config(
        {"ui": {"distill": {"summaries": "docs/other.md", "output": "docs/ws.md"}}}
    )
    assert cfg.distill.input == "docs/other.md"
    assert cfg.distill.output == "docs/ws.md"


def test_track_fields_merge_into_one_list():
    """track_file (singular) + track_files_extra (textarea) -> track_files."""
    cfg, _, _ = build_grounding_config({"ui": {"campaign_state": {
        "track_file": "notes/module.txt",
        "track_files_extra": "notes/arc_a.txt\nnotes/arc_b.txt",
        "track": "Freed the sovereign\nBurned the bridge",
    }}})
    assert cfg.campaign_state.track_files == [
        "notes/module.txt", "notes/arc_a.txt", "notes/arc_b.txt",
    ]
    assert cfg.campaign_state.track_items == [
        "Freed the sovereign", "Burned the bridge",
    ]


def test_newline_textareas_become_lists():
    cfg, _, _ = build_grounding_config({"ui": {"party": {
        "chars": "docs/a.md\ndocs/b.md",
        "context": "docs/ws.md",
    }}})
    assert cfg.party.characters == ["docs/a.md", "docs/b.md"]
    assert cfg.party.context == ["docs/ws.md"]


def test_planning_build_keys_move_into_dossiers_group():
    cfg, _, _ = build_grounding_config({"ui": {"planning": {
        "build_summaries": "docs/s.md",
        "dossier_dir": "docs/npcs/",
        "build_extract_dir": "docs/px",
        "build_split_chapters": "# Session",
    }}})
    d = cfg.planning.dossiers
    assert d.summaries == "docs/s.md"
    assert d.dossier_dir == "docs/npcs/"
    assert d.extract_dir == "docs/px"
    assert d.split_chapters == "# Session"


def test_mode_and_config_path_survive():
    cfg, _, _ = build_grounding_config({"ui": {
        "party": {"mode": "flat", "config_path": "config/party.yaml"},
        "planning": {"synth_mode": "config", "config_path": "config/planning.yaml"},
    }})
    assert cfg.party.mode == "flat"
    assert cfg.party.config_path == "config/party.yaml"
    assert cfg.planning.synth_mode == "config"


def test_unknown_keys_are_reported_not_dropped_silently():
    """The failure mode this whole effort exists to remove."""
    cfg, skipped, _ = build_grounding_config({"ui": {
        "grounding": {"summaries": "docs/s.md", "stale_key": "x"},
        "distill": {"output": "docs/ws.md", "ancient_field": 1},
    }})
    assert cfg is not None
    assert "ui.grounding.stale_key" in skipped
    assert "ui.distill.ancient_field" in skipped


def test_empty_values_are_ignored():
    cfg, _, _ = build_grounding_config({"ui": {
        "distill": {"output": "docs/ws.md", "extract_dir": "", "input": None},
    }})
    assert cfg.distill.output == "docs/ws.md"
    assert cfg.distill.extract_dir is None


# ── CLI ────────────────────────────────────────────────────────────────────

def test_cli_writes_grounding_yaml(tmp_path, capsys):
    _write_ui_state(tmp_path, {
        "grounding": {"summaries": "docs/summaries.md"},
        "party": {"mode": "config", "config_path": "config/party.yaml"},
    })
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    dest = tmp_path / "config" / "grounding.yaml"
    assert dest.exists()
    cfg = load_grounding_config(dest)
    assert cfg.summaries == "docs/summaries.md"
    assert cfg.party.config_path == "config/party.yaml"


def test_cli_nothing_to_migrate_exits_zero(tmp_path, capsys):
    """Expected for most campaigns — two of the five sections were
    write-never, so there is genuinely nothing stored to move."""
    _write_ui_state(tmp_path, {"query": {"input": "x"}})
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "nothing to migrate" in out
    # Says WHY, so an empty result doesn't read as a failure.
    assert "write-never" in out or "never written" in out


def test_cli_refuses_to_overwrite_without_force(tmp_path, capsys):
    _write_ui_state(tmp_path, {"grounding": {"summaries": "docs/s.md"}})
    (tmp_path / "config" / "grounding.yaml").write_text(
        "summaries: docs/existing.md\n", encoding="utf-8"
    )
    assert main(["--campaign-dir", str(tmp_path)]) == 1
    assert load_grounding_config(
        tmp_path / "config" / "grounding.yaml"
    ).summaries == "docs/existing.md"


def test_cli_force_overwrites(tmp_path):
    _write_ui_state(tmp_path, {"grounding": {"summaries": "docs/new.md"}})
    (tmp_path / "config" / "grounding.yaml").write_text(
        "summaries: docs/existing.md\n", encoding="utf-8"
    )
    assert main(["--campaign-dir", str(tmp_path), "--force"]) == 0
    assert load_grounding_config(
        tmp_path / "config" / "grounding.yaml"
    ).summaries == "docs/new.md"


def test_cli_reports_skipped_keys(tmp_path, capsys):
    _write_ui_state(tmp_path, {
        "grounding": {"summaries": "docs/s.md", "mystery": "keep me"},
    })
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_cli_is_idempotent_with_force(tmp_path):
    _write_ui_state(tmp_path, {"grounding": {"summaries": "docs/s.md"}})
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    first = (tmp_path / "config" / "grounding.yaml").read_text(encoding="utf-8")
    assert main(["--campaign-dir", str(tmp_path), "--force"]) == 0
    assert (tmp_path / "config" / "grounding.yaml").read_text(encoding="utf-8") == first


def test_cli_reads_ui_state_raw_not_through_uistate_model(tmp_path):
    """UISection no longer declares these fields, so a typed load would drop
    exactly the data this CLI exists to rescue."""
    _write_ui_state(tmp_path, {"campaign_state": {"output": "docs/cs.md"}})
    assert main(["--campaign-dir", str(tmp_path)]) == 0
    cfg = load_grounding_config(tmp_path / "config" / "grounding.yaml")
    assert cfg.campaign_state.output == "docs/cs.md"
