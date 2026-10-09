from pathlib import Path

import pytest

from campaignlib.planning_config import PlanningConfig, PlanningNoteSelector, load_planning_config, save_planning_config


def test_notes_absent_is_legacy_summary_only(tmp_path: Path):
    path = tmp_path / "planning.yaml"
    path.write_text("npcs: []\n")
    assert load_planning_config(path).notes is None


@pytest.mark.parametrize("text", ["notes: []\n", "notes: missing.md\n"])
def test_configured_notes_must_be_nonempty_list(tmp_path: Path, text: str):
    path = tmp_path / "planning.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="notes must be a non-empty list"):
        load_planning_config(path)


def test_note_selector_round_trips(tmp_path: Path):
    path = tmp_path / "planning.yaml"
    cfg = PlanningConfig(notes=[PlanningNoteSelector(id="current-plan", path="notes/*.md", record_ids={"plan-a"})])
    save_planning_config(path, cfg)
    assert load_planning_config(path).notes == cfg.notes


@pytest.mark.parametrize(
    "text, match",
    [
        ("notes:\n  - id: bad selector\n    path: notes/a.md\n", "stable lowercase slug"),
        ("notes:\n  - id: note-a\n    path: ''\n", "path is required"),
        ("notes:\n  - id: note-a\n    path: notes/a.md\n    record_ids: []\n", "record_ids must be non-empty"),
    ],
)
def test_configured_note_selectors_are_strict(tmp_path: Path, text: str, match: str):
    path = tmp_path / "planning.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match=match):
        load_planning_config(path)
