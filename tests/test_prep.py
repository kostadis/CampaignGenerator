"""Tests for campaignlib and prep.py logic."""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
import prep


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_workspace(tmp_path):
    """Minimal workspace with absolute paths in config."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "world_state.md").write_text("# World\nSome lore.", encoding="utf-8")
    (docs / "mechanics.md").write_text("# Mechanics\nSome rules.", encoding="utf-8")
    (tmp_path / "system_prompt.md").write_text("You are a DM assistant.", encoding="utf-8")

    (tmp_path / "config.yaml").write_text(f"""\
system_prompt: {tmp_path}/system_prompt.md
log_dir: {tmp_path}/logs
agents:
  lore_oracle: {tmp_path}/agents/lore_oracle.md
  encounter_architect: {tmp_path}/agents/encounter_architect.md
  voice_keeper: {tmp_path}/agents/voice_keeper.md
documents:
  - label: world_state
    path: {docs}/world_state.md
  - label: mechanics
    path: {docs}/mechanics.md
""", encoding="utf-8")
    return tmp_path


@pytest.fixture
def tmp_workspace_relative(tmp_path):
    """Workspace where doc paths are relative to the config file."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "world_state.md").write_text("# World\nRelative lore.", encoding="utf-8")
    (tmp_path / "system_prompt.md").write_text("System prompt.", encoding="utf-8")

    (tmp_path / "config.yaml").write_text("""\
system_prompt: system_prompt.md
log_dir: logs
agents:
  lore_oracle: agents/lore_oracle.md
  encounter_architect: agents/encounter_architect.md
  voice_keeper: agents/voice_keeper.md
documents:
  - label: world_state
    path: docs/world_state.md
""", encoding="utf-8")
    return tmp_path


# ── campaignlib.load_config ───────────────────────────────────────────────────

def test_load_config_returns_dict_and_path(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    assert isinstance(config, dict)
    assert base_dir == tmp_workspace


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        campaignlib.load_config("/nonexistent/path/config.yaml")


# ── campaignlib.load_file ─────────────────────────────────────────────────────

def test_load_file_absolute(tmp_workspace):
    content = campaignlib.load_file(str(tmp_workspace / "docs" / "world_state.md"))
    assert "Some lore" in content


def test_load_file_relative_resolved_against_base(tmp_workspace):
    content = campaignlib.load_file("docs/world_state.md", base_dir=tmp_workspace)
    assert "Some lore" in content


def test_load_file_missing_exits():
    with pytest.raises(SystemExit):
        campaignlib.load_file("/nonexistent/file.md")


def test_load_file_relative_missing_exits(tmp_workspace):
    with pytest.raises(SystemExit):
        campaignlib.load_file("docs/missing.md", base_dir=tmp_workspace)


# ── campaignlib.assemble_docs ─────────────────────────────────────────────────

def test_assemble_docs_includes_content(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = campaignlib.assemble_docs(config, ["world_state", "mechanics"], base_dir)
    assert "## world_state" in result
    assert "Some lore" in result
    assert "## mechanics" in result
    assert "Some rules" in result


def test_assemble_docs_skips_doc_with_no_path(tmp_path):
    (tmp_path / "world_state.md").write_text("Lore.", encoding="utf-8")
    config = {
        "documents": [
            {"label": "world_state", "path": str(tmp_path / "world_state.md")},
            {"label": "mechanics"},
        ]
    }
    result = campaignlib.assemble_docs(config, ["world_state", "mechanics"])
    assert "## world_state" in result
    assert "## mechanics" not in result


def test_assemble_docs_unknown_label_exits(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    with pytest.raises(SystemExit):
        campaignlib.assemble_docs(config, ["nonexistent"], base_dir)


def test_assemble_docs_relative_paths(tmp_workspace_relative):
    config, base_dir = campaignlib.load_config(str(tmp_workspace_relative / "config.yaml"))
    result = campaignlib.assemble_docs(config, ["world_state"], base_dir)
    assert "Relative lore" in result


# ── campaignlib.find_default_config ──────────────────────────────────────────

def test_find_default_config_prefers_cwd(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = campaignlib.find_default_config("/some/script.py")
    assert result == str(tmp_path / "config.yaml")


def test_find_default_config_falls_back_to_script_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no config.yaml here
    script = "/home/user/CampaignGenerator/npc_table.py"
    result = campaignlib.find_default_config(script)
    assert result == "/home/user/CampaignGenerator/config/config.yaml"


# ── prep.assemble_user_prompt ─────────────────────────────────────────────────

def test_assemble_user_prompt_includes_beat(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = prep.assemble_user_prompt(config, "The party enters the dungeon", base_dir)
    assert "The party enters the dungeon" in result
    assert "## Session Beat" in result


def test_assemble_user_prompt_includes_docs(tmp_workspace):
    config, base_dir = campaignlib.load_config(str(tmp_workspace / "config.yaml"))
    result = prep.assemble_user_prompt(config, "A beat", base_dir)
    assert "## world_state" in result
    assert "Some lore" in result


# ── prep.parse_session_beats ──────────────────────────────────────────────────

def test_parse_beats_period():
    beats = prep.parse_session_beats("1. Travel\n2. Confront\n3. Reveal")
    assert beats == ["Travel", "Confront", "Reveal"]


def test_parse_beats_paren():
    assert prep.parse_session_beats("1) First\n2) Second") == ["First", "Second"]


def test_parse_beats_colon():
    assert prep.parse_session_beats("1: First\n2: Second") == ["First", "Second"]


def test_parse_beats_multiline():
    beats = prep.parse_session_beats("1. First beat\n   continued here\n2. Second beat")
    assert len(beats) == 2
    assert "continued here" in beats[0]


def test_parse_beats_empty_returns_empty():
    assert prep.parse_session_beats("") == []


def test_parse_beats_single():
    assert prep.parse_session_beats("1. Only one beat") == ["Only one beat"]
