"""Tests for campaignlib, prep.py, session_doc, and quote_ledger logic."""

import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
import prep
import session_doc
import quote_ledger


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


# ── campaignlib.save_log ────────────────────────────────────────────────────

def test_save_log_creates_file(tmp_path):
    log_file = campaignlib.save_log(
        str(tmp_path), [("Heading", "Content here.")], stem="test"
    )
    assert log_file.exists()
    assert log_file.name.endswith("_test.md")


def test_save_log_contains_sections(tmp_path):
    log_file = campaignlib.save_log(
        str(tmp_path),
        [("System Prompt", "You are a DM."), ("Response", "The encounter begins.")],
        stem="session",
    )
    text = log_file.read_text(encoding="utf-8")
    assert "## System Prompt" in text
    assert "You are a DM." in text
    assert "## Response" in text
    assert "The encounter begins." in text


def test_save_log_creates_directory(tmp_path):
    nested = tmp_path / "deep" / "logs"
    log_file = campaignlib.save_log(str(nested), [("A", "B")])
    assert log_file.exists()
    assert nested.exists()


# ── session_doc.extract_section_text ────────────────────────────────────────

RECAP_WITH_SECTIONS = """\
## Summary

The party climbed the mountain and fought giants.

## Memorable Moments

- Vukradin stared down a stone giant.
- Soma transformed into an eagle.

## Scenes

### The Stone Giants
Big fight here.

## NPCs

- Stone Giant Leader
"""


def test_extract_section_text_summary():
    text = session_doc.extract_section_text(RECAP_WITH_SECTIONS, "Summary")
    assert "climbed the mountain" in text
    assert "Memorable Moments" not in text


def test_extract_section_text_memorable_moments():
    text = session_doc.extract_section_text(RECAP_WITH_SECTIONS, "Memorable Moments")
    assert "Vukradin stared down" in text
    assert "Soma transformed" in text
    assert "climbed the mountain" not in text


def test_extract_section_text_case_insensitive():
    text = session_doc.extract_section_text(RECAP_WITH_SECTIONS, "summary")
    assert "climbed the mountain" in text


def test_extract_section_text_nonexistent():
    text = session_doc.extract_section_text(RECAP_WITH_SECTIONS, "Missing Section")
    assert text == ""


# ── session_doc.extract_character_roster ────────────────────────────────────

PARTY_TEXT = """\
## Soma
**Tortle Druid 5, Player: Wade**

Some backstory about Soma.

## Vukradin
**Goliath Barbarian 5, Player: Kostadis**

Some backstory about Vukradin.

## Valphine
**Elf Wizard 5**

No player listed.
"""


def test_extract_character_roster_basic():
    roster = session_doc.extract_character_roster(PARTY_TEXT)
    assert "Soma (Wade): Tortle Druid 5" in roster
    assert "Vukradin (Kostadis): Goliath Barbarian 5" in roster


def test_extract_character_roster_no_player():
    """Characters without Player: field but with valid class line are included."""
    text = "## Valphine\n**Elf Wizard 5, Bladesinger**\n"
    roster = session_doc.extract_character_roster(text)
    assert "Valphine: Elf Wizard 5, Bladesinger" in roster
    assert "Valphine (" not in roster


def test_extract_character_roster_empty():
    assert session_doc.extract_character_roster("") == ""


def test_extract_character_roster_multi_player():
    text = "## Soma\n**Tortle Druid 5, Player: Wade/Kostadis**\n"
    roster = session_doc.extract_character_roster(text)
    assert "Wade/Kostadis" in roster


# ── session_doc.load_voice_files ────────────────────────────────────────────

def test_load_voice_files(tmp_path):
    (tmp_path / "vukradin_voice.md").write_text("Gruff, terse.", encoding="utf-8")
    (tmp_path / "soma.md").write_text("Gentle, wise.", encoding="utf-8")
    voices = session_doc.load_voice_files(tmp_path)
    assert voices["vukradin"] == "Gruff, terse."
    assert voices["soma"] == "Gentle, wise."


def test_load_voice_files_empty_dir(tmp_path):
    voices = session_doc.load_voice_files(tmp_path)
    assert voices == {}


# ── session_doc.get_voice_note ──────────────────────────────────────────────

def test_get_voice_note_found():
    voices = {"vukradin": "Gruff.", "soma": "Gentle."}
    assert session_doc.get_voice_note(voices, "Vukradin") == "Gruff."


def test_get_voice_note_first_name():
    voices = {"soma": "Gentle."}
    assert session_doc.get_voice_note(voices, "Soma the Tortle") == "Gentle."


def test_get_voice_note_missing():
    voices = {"vukradin": "Gruff."}
    assert session_doc.get_voice_note(voices, "Brewbarry") is None


# ── session_doc.load_extractions ────────────────────────────────────────────

def test_load_extractions_sorted(tmp_path):
    (tmp_path / "extract_002.md").write_text("Second", encoding="utf-8")
    (tmp_path / "extract_001.md").write_text("First", encoding="utf-8")
    (tmp_path / "notes.md").write_text("Ignored", encoding="utf-8")
    result = session_doc.load_extractions(tmp_path)
    assert len(result) == 2
    assert result[0] == ("extract_001.md", "First")
    assert result[1] == ("extract_002.md", "Second")


def test_load_extractions_empty_dir(tmp_path):
    assert session_doc.load_extractions(tmp_path) == []


# ── session_doc.format_extractions ──────────────────────────────────────────

def test_format_extractions_basic():
    exts = [("extract_001.md", "Dialogue here"), ("extract_002.md", "More dialogue")]
    result = session_doc.format_extractions(exts, "Roleplay Extractions")
    assert "## Roleplay Extractions" in result
    assert "### Chunk 1" in result
    assert "### Chunk 2" in result
    assert "Dialogue here" in result
    assert "---" in result


def test_format_extractions_single_chunk():
    exts = [("extract_001.md", "Only chunk")]
    result = session_doc.format_extractions(exts, "Test")
    assert "### Chunk 1" in result
    assert "---" not in result.split("## Test\n\n", 1)[1]  # no separator with single chunk


# ── session_doc.build_narrate_prompt ────────────────────────────────────────

def test_build_narrate_prompt_basic():
    result = session_doc.build_narrate_prompt(
        narrator="Vukradin",
        focus="Faces the stone giants",
        char_moments="**The Giants**\nVukradin: \"We do not leave.\"",
        party=None,
        handoff="",
    )
    assert "## Narrator: Vukradin" in result
    assert "Faces the stone giants" in result
    assert "We do not leave" in result


def test_build_narrate_prompt_includes_party():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party="## Soma\nTortle Druid", handoff=""
    )
    assert "## Party Document" in result
    assert "Tortle Druid" in result


def test_build_narrate_prompt_includes_voice_note():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="", voice_note="Gentle and wise."
    )
    assert "Voice Notes" in result
    assert "Gentle and wise." in result


def test_build_narrate_prompt_includes_handoff():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="The mountain loomed ahead."
    )
    assert "Handoff" in result
    assert "The mountain loomed ahead." in result


def test_build_narrate_prompt_no_handoff_when_empty():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff=""
    )
    assert "Handoff" not in result


def test_build_narrate_prompt_includes_roster():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="", roster="- Soma: Tortle Druid 5"
    )
    assert "Character Classes" in result
    assert "Tortle Druid 5" in result


def test_build_narrate_prompt_includes_roleplay_summary():
    result = session_doc.build_narrate_prompt(
        narrator="Soma", focus="focus", char_moments="moments",
        party=None, handoff="", roleplay_summary="Great roleplay here."
    )
    assert "Session Roleplay Summary" in result
    assert "Great roleplay here." in result


# ── session_doc.build_char_extract_prompt — recap context ───────────────────

def test_scene_mode_includes_recap_context():
    """Scene mode should include Summary and Memorable Moments from recap."""
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES
    )
    assert "Recap Context" in prompt
    assert "The party climbed the mountain" in prompt


def test_scene_mode_includes_session_summary():
    prompt = session_doc.build_char_extract_prompt(
        _scene_section("The Stone Giants"),
        ALL_EXTRACTIONS, None, recap=RECAP_WITH_SCENES,
        session_summary="Session events log here."
    )
    assert "Session Events" in prompt
    assert "Session events log here." in prompt


def test_chunk_mode_includes_summary_extractions():
    summary_exts = [("extract_001.md", "Action details chunk 1"),
                    ("extract_002.md", "Action details chunk 2")]
    prompt = session_doc.build_char_extract_prompt(
        _chunk_section(1, 1), ALL_EXTRACTIONS, summary_exts
    )
    assert "Session Extractions" in prompt
    assert "Action details chunk 1" in prompt


def test_build_char_extract_prompt_includes_roster():
    prompt = session_doc.build_char_extract_prompt(
        _chunk_section(1, 2), ALL_EXTRACTIONS, None,
        roster="- Vukradin: Goliath Barbarian 5"
    )
    assert "Character Classes" in prompt
    assert "Goliath Barbarian 5" in prompt


# ── quote_ledger.parse_roleplay_quotes ──────────────────────────────────────

ROLEPLAY_TEXT = """\
**kostadis1 as Vukradin** — *confronting the giant*
> "We do not leave."
> "This mountain is ours."

**GM as Brewbarry** — *reaction*
> "Then I guess we fight."
"""


def test_parse_roleplay_quotes_basic():
    quotes = quote_ledger.parse_roleplay_quotes(ROLEPLAY_TEXT, "extract_001.md")
    assert len(quotes) == 2
    assert quotes[0]["speaker"] == "kostadis1 as Vukradin"
    assert quotes[0]["character"] == "Vukradin"
    assert quotes[0]["context"] == "confronting the giant"
    assert "We do not leave" in quotes[0]["quote_text"]
    assert "This mountain is ours" in quotes[0]["quote_text"]
    assert quotes[0]["source_file"] == "extract_001.md"
    assert quotes[0]["block_index"] == 0


def test_parse_roleplay_quotes_gm_character():
    quotes = quote_ledger.parse_roleplay_quotes(ROLEPLAY_TEXT, "test.md")
    assert quotes[1]["character"] == "Brewbarry"


def test_parse_roleplay_quotes_empty():
    assert quote_ledger.parse_roleplay_quotes("No quotes here.", "f.md") == []


def test_parse_roleplay_quotes_no_as_in_speaker():
    text = '**David** — *talking*\n> "Hello there."\n'
    quotes = quote_ledger.parse_roleplay_quotes(text, "f.md")
    assert len(quotes) == 1
    assert quotes[0]["character"] == "David"  # fallback to speaker


# ── quote_ledger.parse_scene_dialogue ───────────────────────────────────────

def test_parse_scene_dialogue_basic():
    text = 'Vukradin: "We do not leave."\nSoma: "Hold on."'
    result = quote_ledger.parse_scene_dialogue(text)
    assert len(result) == 2
    assert result[0] == ("Vukradin", "We do not leave.")
    assert result[1] == ("Soma", "Hold on.")


def test_parse_scene_dialogue_no_dialogue():
    assert quote_ledger.parse_scene_dialogue("Just action beats.") == []


def test_parse_scene_dialogue_requires_capital():
    text = 'someone: "lowercase speaker"'
    assert quote_ledger.parse_scene_dialogue(text) == []


# ── quote_ledger.normalize_quote ────────────────────────────────────────────

def test_normalize_quote_lowercase():
    assert "hello world" in quote_ledger.normalize_quote("HELLO WORLD")


def test_normalize_quote_strips_punctuation():
    result = quote_ledger.normalize_quote('"Hello," said the giant—"Leave!"')
    assert '"' not in result
    assert ',' not in result
    assert '—' not in result
    assert '!' not in result


def test_normalize_quote_collapses_whitespace():
    result = quote_ledger.normalize_quote("  too   many   spaces  ")
    assert "  " not in result
    assert result == "too many spaces"


def test_normalize_quote_strips_smart_quotes():
    result = quote_ledger.normalize_quote("\u201cHello\u201d \u2018world\u2019")
    assert "\u201c" not in result
    assert "\u201d" not in result


# ── quote_ledger.match_quote ────────────────────────────────────────────────

def test_match_quote_identical():
    assert quote_ledger.match_quote("we do not leave", "we do not leave") == 1.0


def test_match_quote_different():
    ratio = quote_ledger.match_quote("we do not leave", "completely different text here")
    assert ratio < 0.5


def test_match_quote_similar():
    ratio = quote_ledger.match_quote("we do not leave this place",
                                      "we do not leave this place ever")
    assert ratio > 0.8


# ── quote_ledger.first_n_words ──────────────────────────────────────────────

def test_first_n_words_default():
    text = "one two three four five six seven eight nine ten"
    assert quote_ledger.first_n_words(text) == "one two three four five six seven eight"


def test_first_n_words_short():
    assert quote_ledger.first_n_words("hello") == "hello"


def test_first_n_words_custom_n():
    assert quote_ledger.first_n_words("a b c d e", n=3) == "a b c"


# ── quote_ledger.QuoteLedger ───────────────────────────────────────────────

def test_quote_ledger_create_and_close(tmp_path):
    db = tmp_path / "test.db"
    ledger = quote_ledger.QuoteLedger(db)
    assert db.exists()
    ledger.close()


def test_quote_ledger_sync_and_query(tmp_path):
    """Full round-trip: ingest roleplay files, match to scenes, query results."""
    # Set up roleplay extraction dir
    rp_dir = tmp_path / "roleplay"
    rp_dir.mkdir()
    (rp_dir / "extract_001.md").write_text(ROLEPLAY_TEXT, encoding="utf-8")

    # Set up scene extraction dir with matching dialogue
    ext_dir = tmp_path / "extractions"
    ext_dir.mkdir()
    scene_file = session_doc.extraction_filename(1, "Vukradin", "The Stone Giants")
    (ext_dir / scene_file).write_text(
        'Vukradin: "We do not leave."\nVukradin: "This mountain is ours."',
        encoding="utf-8"
    )

    scenes = [{"index": 1, "narrator": "Vukradin", "scene": "The Stone Giants"}]

    db = tmp_path / "test.db"
    ledger = quote_ledger.QuoteLedger(db)
    result = ledger.sync(rp_dir, ext_dir, scenes)
    assert result["total"] == 2
    assert result["matched"] >= 1  # at least Vukradin's quote should match

    grouped = ledger.get_quotes_grouped(scenes)
    assert len(grouped["scenes"]) == 1
    ledger.close()


def test_quote_ledger_assign(tmp_path):
    """Manual assignment pins a quote to a scene."""
    rp_dir = tmp_path / "roleplay"
    rp_dir.mkdir()
    (rp_dir / "extract_001.md").write_text(ROLEPLAY_TEXT, encoding="utf-8")

    ext_dir = tmp_path / "extractions"
    ext_dir.mkdir()

    scenes = [{"index": 1, "narrator": "Vukradin", "scene": "The Stone Giants"}]

    db = tmp_path / "test.db"
    ledger = quote_ledger.QuoteLedger(db)
    ledger.sync(rp_dir, ext_dir, scenes)

    # Get an unassigned quote and assign it
    grouped = ledger.get_quotes_grouped(scenes)
    unassigned = grouped["unassigned"]
    if unassigned:
        qid = unassigned[0]["id"]
        assert ledger.assign(qid, 1) is True
        # Verify it moved
        grouped2 = ledger.get_quotes_grouped(scenes)
        scene_qids = [q["id"] for q in grouped2["scenes"][0]["quotes"]]
        assert qid in scene_qids

    ledger.close()


def test_quote_ledger_assign_nonexistent(tmp_path):
    db = tmp_path / "test.db"
    ledger = quote_ledger.QuoteLedger(db)
    assert ledger.assign(99999, 1) is False
    ledger.close()


# ── Helper: create a ledger with quotes ───────────────────────────────────

def _make_ledger_with_quotes(tmp_path):
    """Create a ledger with 3 quotes (2 Vukradin, 1 Brewbarry), all unassigned."""
    rp_dir = tmp_path / "roleplay"
    rp_dir.mkdir()
    (rp_dir / "extract_001.md").write_text(ROLEPLAY_TEXT, encoding="utf-8")
    ext_dir = tmp_path / "extractions"
    ext_dir.mkdir()

    db = tmp_path / "test.db"
    ledger = quote_ledger.QuoteLedger(db)
    # Ingest only (no scene matching since no extraction files)
    ledger.sync(rp_dir, ext_dir, [])
    return ledger


# ── quote_ledger.QuoteLedger.bulk_assign ──────────────────────────────────

def test_bulk_assign_basic(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    ids = [q["id"] for q in all_q]
    count = ledger.bulk_assign(ids[:2], scene_index=1)
    assert count == 2
    scene_q = ledger.get_scene_quotes(1)
    assert len(scene_q) == 2
    assert all(q["pinned"] == 1 for q in scene_q)
    ledger.close()


def test_bulk_assign_empty_list(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    assert ledger.bulk_assign([], scene_index=1) == 0
    ledger.close()


# ── quote_ledger.QuoteLedger.bulk_unassign ────────────────────────────────

def test_bulk_unassign_basic(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    ids = [q["id"] for q in all_q]
    ledger.bulk_assign(ids, scene_index=1)
    count = ledger.bulk_unassign(ids[:1])
    assert count == 1
    scene_q = ledger.get_scene_quotes(1)
    assert len(scene_q) == len(ids) - 1
    ledger.close()


def test_bulk_unassign_empty_list(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    assert ledger.bulk_unassign([]) == 0
    ledger.close()


# ── quote_ledger.QuoteLedger.make_exclusive ───────────────────────────────

def test_make_exclusive_reassigns_from_other_scene(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    ids = [q["id"] for q in all_q]

    # Assign first quote to scene 2
    ledger.bulk_assign(ids[:1], scene_index=2)
    # Make it exclusive to scene 1
    ledger.make_exclusive(ids[:1], scene_index=1)

    assert ledger.get_scene_quotes(2) == []
    assert len(ledger.get_scene_quotes(1)) == 1
    ledger.close()


def test_make_exclusive_empty_list(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    assert ledger.make_exclusive([], scene_index=1) == 0
    ledger.close()


# ── quote_ledger.QuoteLedger.get_scene_quotes ─────────────────────────────

def test_get_scene_quotes_empty(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    assert ledger.get_scene_quotes(99) == []
    ledger.close()


def test_get_scene_quotes_returns_correct_fields(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    ledger.bulk_assign([all_q[0]["id"]], scene_index=3)
    scene_q = ledger.get_scene_quotes(3)
    assert len(scene_q) == 1
    q = scene_q[0]
    assert "id" in q
    assert "speaker" in q
    assert "character" in q
    assert "quote_text" in q
    assert q["scene_index"] == 3
    ledger.close()


# ── quote_ledger.QuoteLedger.get_all_quotes ───────────────────────────────

def test_get_all_quotes_returns_all(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    assert len(all_q) == 2  # ROLEPLAY_TEXT has 2 quote blocks
    ledger.close()


def test_get_all_quotes_includes_source_file(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    assert all("source_file" in q for q in all_q)
    assert all("block_index" in q for q in all_q)
    ledger.close()


def test_get_all_quotes_chronological_order(tmp_path):
    ledger = _make_ledger_with_quotes(tmp_path)
    all_q = ledger.get_all_quotes()
    indices = [(q["source_file"], q["block_index"]) for q in all_q]
    assert indices == sorted(indices)
    ledger.close()
