"""Tests for campaignlib and prep.py logic."""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
import prep
import session_doc


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


# ── Fixtures for session_doc tests ───────────────────────────────────────────

RECAP_WITH_SCENES = """\
## Summary

The party climbed the mountain.

## Scenes

### The Stone Giants
The party encountered three stone giants blocking the pass.
Vukradin used intimidation to drive them back.

### The Whispering Glacier
Soma transformed into an eagle to scout ahead.
Ice cracked beneath Brewbarry's feet.

### Carving a Path
The party reached the summit. Soma reshaped the mountain.
Brewbarry held the rear as rocks fell.

## NPCs

- Stone Giant Leader
"""

EXTRACTIONS_CHUNK1 = [
    ("extract_001.md", 'Giant: "LEAVE OR DIE."\nVukradin: "We do not leave."'),
]
EXTRACTIONS_CHUNK2 = [
    ("extract_002.md", 'Soma: "Hold on — I can reshape this."\nBrewbarry: "Then do it now!"'),
]
ALL_EXTRACTIONS = EXTRACTIONS_CHUNK1 + EXTRACTIONS_CHUNK2


# ── session_doc.extract_scene_text ────────────────────────────────────────────

def test_extract_scene_text_returns_target_scene():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Stone Giants")
    assert "Vukradin used intimidation" in text
    assert "stone giants blocking the pass" in text


def test_extract_scene_text_excludes_adjacent_scenes():
    """Sending adjacent scene content is the 'too much data' bug (Bug 7)."""
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Stone Giants")
    assert "Soma transformed" not in text
    assert "Whispering Glacier" not in text
    assert "Carving a Path" not in text


def test_extract_scene_text_middle_scene_excludes_neighbours():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "The Whispering Glacier")
    assert "eagle to scout ahead" in text
    assert "Vukradin used intimidation" not in text  # from previous scene
    assert "Soma reshaped the mountain" not in text  # from next scene


def test_extract_scene_text_last_scene():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "Carving a Path")
    assert "Soma reshaped the mountain" in text
    assert "Ice cracked" not in text  # from Glacier


def test_extract_scene_text_unknown_scene_returns_empty():
    """Empty result means the extraction prompt will have no scope — hallucination risk."""
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "Nonexistent Scene")
    assert text == ""


def test_extract_scene_text_case_insensitive():
    text = session_doc.extract_scene_text(RECAP_WITH_SCENES, "the stone giants")
    assert "Vukradin used intimidation" in text


def test_extract_scene_text_no_scenes_section():
    recap_no_scenes = "## Summary\n\nThe party did things.\n\n## NPCs\n\n- Someone\n"
    text = session_doc.extract_scene_text(recap_no_scenes, "The Stone Giants")
    assert text == ""


# ── session_doc.build_char_extract_prompt ────────────────────────────────────

def _scene_section(scene_name, chunk_start=1, chunk_end=1):
    return {"narrator": "Vukradin", "chunk_start": chunk_start,
            "chunk_end": chunk_end, "scene": scene_name, "focus": "test"}

def _chunk_section(chunk_start=1, chunk_end=2):
    return {"narrator": "Vukradin", "chunk_start": chunk_start,
            "chunk_end": chunk_end, "focus": "test"}


def test_scene_mode_sends_scene_scope():
    """Scene mode must include the recap scene text so the model knows what belongs."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    assert "Scene scope" in prompt
    assert "stone giants blocking the pass" in prompt


def test_scene_mode_sends_roleplay_extractions():
    """Scene mode must include roleplay extractions so the model has verbatim dialogue."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    assert "Roleplay Extractions" in prompt
    assert "LEAVE OR DIE" in prompt


def test_scene_mode_excludes_full_chunk_blob():
    """The old bug: sending all chunks as one blob caused over-narration (Bug 7)."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    # Chunk 2 dialogue must NOT appear — it's from a different scene
    assert "Soma reshaped the mountain" not in prompt
    assert 'Hold on — I can reshape this' not in prompt


def test_scene_mode_unknown_scene_falls_back_to_full_chunk():
    """When scene text is not found, fall back gracefully (don't silently send nothing)."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("Nonexistent Scene"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    # Should fall back to the full-chunk path and still have the extractions
    assert "Roleplay Extractions" in prompt
    assert "LEAVE OR DIE" in prompt


def test_scene_mode_missing_recap_falls_back_to_full_chunk():
    """No recap provided → fall back to full chunk, not an empty prompt."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=""
    )
    assert "Roleplay Extractions" in prompt
    assert "LEAVE OR DIE" in prompt


def test_chunk_mode_does_not_include_scene_scope():
    """Chunk mode should not inject scene scope — that's scene mode only."""
    prompt = session_doc.build_char_extract_prompt(
        _chunk_section(1, 2), ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    assert "Scene scope" not in prompt


def test_chunk_mode_respects_chunk_boundaries():
    """Chunk mode: only the assigned chunks are included, not the whole session."""
    prompt = session_doc.build_char_extract_prompt(
        _chunk_section(1, 1), ALL_EXTRACTIONS, None
    )
    assert "LEAVE OR DIE" in prompt        # chunk 1 — included
    assert "reshape this" not in prompt    # chunk 2 — excluded


# ── session_doc.parse_plan ────────────────────────────────────────────────────

PLAN_SECTION_FORMAT = """\
## Section 1
narrator: Vukradin
chunks: 1
focus: Faces the giants.

## Section 2
narrator: Soma
chunks: 2
focus: Reshapes the mountain.
"""

PLAN_SCENE_FORMAT = """\
## Scene 1
narrator: Vukradin
chunks: 1
scene: The Stone Giants
focus: Faces the giants.

## Scene 2
narrator: Soma
chunks: 2
scene: Carving a Path
focus: Reshapes the mountain.
"""


def test_parse_plan_section_format():
    sections = session_doc.parse_plan(PLAN_SECTION_FORMAT, total_chunks=2)
    assert len(sections) == 2
    assert sections[0]["narrator"] == "Vukradin"
    assert sections[1]["narrator"] == "Soma"


def test_parse_plan_scene_format():
    """Bug 2 regression: parse_plan must handle ## Scene N headings."""
    sections = session_doc.parse_plan(PLAN_SCENE_FORMAT, total_chunks=2)
    assert len(sections) == 2
    assert sections[0]["scene"] == "The Stone Giants"
    assert sections[1]["scene"] == "Carving a Path"


def test_parse_plan_chunk_range():
    plan = "## Section 1\nnarrator: A\nchunks: 1-2\nfocus: x\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert sections[0]["chunk_start"] == 1
    assert sections[0]["chunk_end"] == 2


def test_parse_plan_chunk_clamped_to_total():
    plan = "## Section 1\nnarrator: A\nchunks: 5\nfocus: x\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert sections[0]["chunk_start"] == 2
    assert sections[0]["chunk_end"] == 2


def test_parse_plan_skips_blocks_with_no_narrator():
    plan = "## Scene 1\nchunks: 1\nfocus: x\n\n## Scene 2\nnarrator: B\nchunks: 2\nfocus: y\n"
    sections = session_doc.parse_plan(plan, total_chunks=2)
    assert len(sections) == 1
    assert sections[0]["narrator"] == "B"


# ── session_doc.build_narrate_system — dialogue handling ─────────────────────

def test_chunk_mode_mandates_dialogue():
    """Chunk mode: strong dialogue mandate (full sessions usually have dialogue)."""
    system = session_doc.build_narrate_system(None, scene=None)
    assert "THE DIALOGUE IS THE STORY" in system
    assert "DO NOT invent" not in system


def test_scene_mode_dialogue_is_conditional():
    """Scene mode: dialogue is conditional — don't mandate it when it may not exist."""
    system = session_doc.build_narrate_system(None, scene="The Whispering Glacier")
    assert "THE DIALOGUE IS THE STORY" not in system
    assert "USE DIALOGUE IF PRESENT" in system
    assert "DO NOT invent" in system


def test_scene_mode_no_dialogue_instruction_allows_action_only():
    """Scene mode prompt must explicitly allow action-beat-only narration."""
    system = session_doc.build_narrate_system(None, scene="The Glacier Crossing")
    assert "action beats" in system.lower() or "action beat" in system.lower()
    assert "no dialogue" in system.lower() or "no verbatim" in system.lower() or "no dialogue" in system.lower()


def test_char_extract_system_does_not_mandate_dialogue():
    """Extraction prompt must not demand dialogue — it may not exist for the scene."""
    assert "Do not invent" in session_doc.CHAR_EXTRACT_SYSTEM
    assert "valid output" in session_doc.CHAR_EXTRACT_SYSTEM


# ── session_doc.extraction_filename ──────────────────────────────────────────

def test_extraction_filename_with_scene():
    name = session_doc.extraction_filename(3, "Soma", "The Whispering Glacier")
    assert name == "03_soma_the_whispering_glacier.md"


def test_extraction_filename_without_scene():
    name = session_doc.extraction_filename(1, "Vukradin", "")
    assert name == "01_vukradin.md"


def test_extraction_filename_sortable():
    """Index padding must keep files in order up to 99 scenes."""
    n1 = session_doc.extraction_filename(1, "A", "Scene")
    n9 = session_doc.extraction_filename(9, "A", "Scene")
    n10 = session_doc.extraction_filename(10, "A", "Scene")
    assert sorted([n10, n1, n9]) == [n1, n9, n10]


def test_extraction_filename_slugifies_special_chars():
    name = session_doc.extraction_filename(2, "Brewbarry", "Giants & Ice!")
    assert " " not in name
    assert "&" not in name
    assert "!" not in name


# ── extract-dir / from-extractions round-trip ─────────────────────────────────

# ── scene index filtering (the --scene flag logic) ───────────────────────────

def _make_sections():
    return [
        {"narrator": "Vukradin", "chunk_start": 1, "chunk_end": 1,
         "scene": "The Stone Giants", "focus": "a"},
        {"narrator": "Soma",     "chunk_start": 1, "chunk_end": 1,
         "scene": "The Glacier",    "focus": "b"},
        {"narrator": "Brewbarry","chunk_start": 2, "chunk_end": 2,
         "scene": "Carving a Path", "focus": "c"},
    ]

def test_scene_filter_selects_correct_sections():
    sections = _make_sections()
    wanted = [3, 1]
    result = [(n, sections[n - 1]) for n in wanted]
    narrators = [s["narrator"] for _, s in result]
    assert narrators == ["Brewbarry", "Vukradin"]

def test_scene_filter_preserves_original_index():
    """The original 1-based index must be preserved so filenames stay consistent."""
    sections = _make_sections()
    result = [(n, sections[n - 1]) for n in [2]]
    i, s = result[0]
    assert i == 2
    fname = session_doc.extraction_filename(i, s["narrator"], s.get("scene", ""))
    assert fname == "02_soma_the_glacier.md"

def test_scene_filter_single():
    sections = _make_sections()
    result = [(n, sections[n - 1]) for n in [3]]
    assert len(result) == 1
    assert result[0][1]["narrator"] == "Brewbarry"


# ── session_doc.parse_extraction_file ────────────────────────────────────────

# ── session_doc.estimate_narration_tokens ────────────────────────────────────

def test_estimate_uses_higher_expansion_for_dialogue():
    with_dialogue    = '**Scene**\nVukradin: "We do not leave."\nHe stood firm.' * 10
    without_dialogue = '**Scene**\nThe glacier stretched ahead. Cold wind. Silence.' * 10
    assert session_doc.estimate_narration_tokens(with_dialogue) > \
           session_doc.estimate_narration_tokens(without_dialogue)

def test_estimate_rounds_to_nearest_250():
    result = session_doc.estimate_narration_tokens("x" * 400)
    assert result % 250 == 0

def test_estimate_minimum_500():
    assert session_doc.estimate_narration_tokens("short") == 500

def test_estimate_grows_with_content_length():
    short = "**Beat**\nSomething happened. The party moved on carefully.\n" * 5
    long  = "**Beat**\nSomething happened. The party moved on carefully.\n" * 50
    assert session_doc.estimate_narration_tokens(long) > \
           session_doc.estimate_narration_tokens(short)


def test_parse_extraction_file_no_header():
    text = "**The Giants**\nVukradin: \"We do not leave.\""
    content, tokens = session_doc.parse_extraction_file(text)
    assert content == text
    assert tokens is None

def test_parse_extraction_file_with_tokens_header():
    text = "tokens: 3000\n\n**The Giants**\nVukradin: \"We do not leave.\""
    content, tokens = session_doc.parse_extraction_file(text)
    assert tokens == 3000
    assert "tokens:" not in content
    assert "We do not leave" in content

def test_parse_extraction_file_header_stripped_from_content():
    text = "tokens: 2500\n\nSome extracted moments."
    content, tokens = session_doc.parse_extraction_file(text)
    assert content.strip() == "Some extracted moments."

def test_parse_extraction_file_non_token_first_line():
    text = "**Scene label**\ntokens: 3000\nmore content"
    content, tokens = session_doc.parse_extraction_file(text)
    assert tokens is None
    assert content == text


def test_extraction_files_can_be_reloaded(tmp_path):
    """Files written by extraction_filename can be read back by matching the same name."""
    sections = [
        {"narrator": "Vukradin", "chunk_start": 1, "chunk_end": 1,
         "scene": "The Stone Giants", "focus": "x"},
        {"narrator": "Soma", "chunk_start": 2, "chunk_end": 2,
         "scene": "Carving a Path", "focus": "y"},
    ]
    contents = ["Vukradin's extracted moments here.", "Soma's extracted moments here."]

    # Simulate saving
    for i, (section, text) in enumerate(zip(sections, contents), 1):
        fname = session_doc.extraction_filename(i, section["narrator"], section.get("scene", ""))
        (tmp_path / fname).write_text(text, encoding="utf-8")

    # Simulate loading
    for i, (section, expected) in enumerate(zip(sections, contents), 1):
        fname = session_doc.extraction_filename(i, section["narrator"], section.get("scene", ""))
        loaded = (tmp_path / fname).read_text(encoding="utf-8")
        assert loaded == expected
