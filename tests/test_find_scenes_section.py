"""Tests for campaignlib.scenes.find_scenes_section (issue #262).

Before this function existed, four call sites each answered "does this
document have a ``## Scenes`` section" with their own heading-match rule and
gave three different verdicts on the same heading. This module tests the
unified rule directly, then re-runs each of the four call sites against a
shared trailing-text fixture to confirm none of them changed behaviour.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import campaignlib  # noqa: E402
import session_doc  # noqa: E402
from campaignlib.lineage import compose_summary_scenes  # noqa: E402
from campaignlib.scenes import find_scenes_section  # noqa: E402
from pipelines.ensemble import summary_map as sm  # noqa: E402


# ── heading recognition ──────────────────────────────────────────────────

def test_bare_scenes_heading():
    text = "## Scenes\n\nSome body text.\n"
    found = find_scenes_section(text)
    assert found is not None
    body, _ = found
    assert body.strip() == "Some body text."


def test_trailing_text_after_scenes_is_tolerated():
    text = "## Scenes (12)\n\nBody here.\n"
    found = find_scenes_section(text)
    assert found is not None
    assert "Body here." in found[0]


def test_lowercase_scenes_heading():
    text = "## scenes\n\nLower body.\n"
    found = find_scenes_section(text)
    assert found is not None
    assert "Lower body." in found[0]


def test_two_spaces_after_marker():
    text = "##  Scenes\n\nTwo-space body.\n"
    found = find_scenes_section(text)
    assert found is not None
    assert "Two-space body." in found[0]


def test_no_scenes_section_returns_none():
    text = "## Summary\n\nNothing about scenes here.\n"
    assert find_scenes_section(text) is None


# ── section boundary ─────────────────────────────────────────────────────

def test_section_terminated_by_next_h2():
    text = "## Scenes\n\nInside.\n\n## NPCs\n\nOutside.\n"
    found = find_scenes_section(text)
    assert found is not None
    body, (_start, end) = found
    assert "Inside." in body
    assert "Outside." not in body
    assert "NPCs" not in body
    assert text[end:].startswith("## NPCs")


def test_section_terminated_by_end_of_text():
    text = "## Scenes\n\nJust this.\n"
    found = find_scenes_section(text)
    assert found is not None
    body, (_start, end) = found
    assert end == len(text)
    assert body.strip() == "Just this."


def test_h3_inside_does_not_terminate_section():
    text = "## Scenes\n\n### Scene One\nSome content.\n\n### Scene Two\nMore.\n"
    found = find_scenes_section(text)
    assert found is not None
    body, _ = found
    assert "Scene One" in body and "Scene Two" in body
    assert "Some content." in body and "More." in body


def test_section_present_but_empty_is_not_none():
    text = "## Scenes\n## NPCs\nSomething.\n"
    found = find_scenes_section(text)
    assert found is not None
    body, (start, end) = found
    assert body == ""
    assert start == end


def test_start_offset_finds_a_later_section():
    text = (
        "## Scenes\n\nFirst body.\n\n"
        "## Other\n\nfiller\n\n"
        "## Scenes\n\nSecond body.\n"
    )
    first = find_scenes_section(text)
    assert first is not None
    body1, (_s1, e1) = first
    assert "First body." in body1

    second = find_scenes_section(text, start=e1)
    assert second is not None
    body2, _ = second
    assert "Second body." in body2
    assert "First body." not in body2


# ── the four call sites, on a shared trailing-text fixture ──────────────
#
# Each caller keeps its own scene-title rule and its own return shape;
# only the ## Scenes heading match and section boundary are shared now.
# This fixture exercises the one case none of the strict rules would have
# accepted: trailing text after "Scenes" on the heading line.

TRAILING_HEADING_TEXT = """\
# Session Recap

## Scenes (Reviewed)

### The Bridge Collapse
The party crossed as the bridge gave way.

### Quiet Aftermath
They regrouped and took stock.

## NPCs

### Watchman
Saw everything.
"""


def test_extract_scene_text_handles_trailing_heading_text():
    text = session_doc.extract_scene_text(TRAILING_HEADING_TEXT, "The Bridge Collapse")
    assert "crossed as the bridge gave way" in text
    assert "regrouped and took stock" not in text
    assert "Watchman" not in text


def test_parse_gmassist_scenes_handles_trailing_heading_text():
    scenes = campaignlib.parse_gmassist_scenes(TRAILING_HEADING_TEXT)
    assert [s["name"] for s in scenes] == ["The Bridge Collapse", "Quiet Aftermath"]
    assert "crossed as the bridge gave way" in scenes[0]["body"]
    assert "regrouped and took stock" in scenes[1]["body"]
    for s in scenes:
        assert "Watchman" not in s["body"]


def test_parse_summary_scenes_handles_trailing_heading_text():
    assert sm.parse_summary_scenes(TRAILING_HEADING_TEXT) == [
        "The Bridge Collapse", "Quiet Aftermath"]


def test_compose_summary_scenes_handles_trailing_heading_text(tmp_path):
    src = tmp_path / "session-summary.md"
    src.write_text(TRAILING_HEADING_TEXT)
    out = compose_summary_scenes(src, tmp_path / "sliced.md")
    assert out is not None
    text = out.read_text()
    assert text.startswith("# Session Recap")
    assert "### The Bridge Collapse" in text
    assert "### Quiet Aftermath" in text
    assert "## NPCs" not in text
    assert "Watchman" not in text


# ── multi-section behaviour: two accidents, kept deliberately ────────────────
#
# Before #262 the two callers below disagreed about a document with more than
# one ``## Scenes`` heading, in opposite directions, and neither behaviour was
# designed — each fell out of the order of statements in a line loop.
#
#   extract_scene_text     tested ``line.strip() == "## Scenes"`` BEFORE its
#                          break-on-next-``##`` and had no "already inside"
#                          guard, so an adjacent second section was swallowed
#                          by the entry test and scanned as a continuation —
#                          but any other ``##`` still stopped it dead.
#   parse_gmassist_scenes  left on any ``##`` and let the entry test fire
#                          again later, so it accumulated across sections
#                          separated by ``## NPCs`` — yet dropped an adjacent
#                          one, having consumed it as the terminator.
#
# The GM ruling on #262 was to keep each caller wherever it is cheapest to
# state rather than reproduce either accident: first-section-only here,
# all-sections there. Across the 16,896-file corpus that changes output on one
# chapter-bible file that no caller reads as input. These tests pin both, so a
# later "tidy-up" that harmonises them has to argue with a failing test.

ADJACENT_SECTIONS = """\
# Chapter 31

## Scenes

### Tunnel Collapse
The passage gave way.

# Chapter 32

## Scenes

### The Dragon Slayer Sword
Resting on the skull.
"""

SPLIT_BY_ANOTHER_H2 = """\
## Scenes

### Tunnel Collapse
The passage gave way.

## NPCs

### Sister Kaella
A warning.

## Scenes

### The Dragon Slayer Sword
Resting on the skull.
"""


def test_extract_scene_text_reads_the_first_section_only():
    """A scene in a later section is not reachable — see the docstring on
    extract_scene_text for why that narrowing is acceptable."""
    assert "gave way" in session_doc.extract_scene_text(
        ADJACENT_SECTIONS, "Tunnel Collapse")
    assert session_doc.extract_scene_text(
        ADJACENT_SECTIONS, "The Dragon Slayer Sword") == ""
    assert session_doc.extract_scene_text(
        SPLIT_BY_ANOTHER_H2, "The Dragon Slayer Sword") == ""


def test_parse_gmassist_scenes_accumulates_every_section():
    """Both shapes, including the adjacent one the old loop silently dropped."""
    assert [s["name"] for s in campaignlib.parse_gmassist_scenes(ADJACENT_SECTIONS)] == [
        "Tunnel Collapse", "The Dragon Slayer Sword"]
    assert [s["name"] for s in campaignlib.parse_gmassist_scenes(SPLIT_BY_ANOTHER_H2)] == [
        "Tunnel Collapse", "The Dragon Slayer Sword"]


def test_an_intervening_h1_lands_in_the_preceding_scene_body():
    """A known wart, pinned rather than fixed — it is NOT part of #262.

    No scanner has ever treated ``#`` as a section boundary; only ``##`` ends
    a section. So a ``# Chapter 32`` sitting between two ``## Scenes``
    sections falls inside the body of the last scene of the first one. That
    was true before this refactor and is true after, in all four call sites.

    Fixing it means making H1 a boundary, which changes what every scene body
    contains — a behaviour change well outside "make four heading rules into
    one". Asserted here so the wart is visible and so a later fix has to
    update a test that says out loud what it is doing.
    """
    scenes = campaignlib.parse_gmassist_scenes(ADJACENT_SECTIONS)
    assert scenes[0]["body"] == "The passage gave way.\n\n# Chapter 32"
    assert scenes[1]["body"] == "Resting on the skull."


def test_parse_gmassist_scenes_skips_a_non_scenes_section_entirely():
    """Sister Kaella sits under ``## NPCs`` and is not a scene."""
    names = [s["name"] for s in campaignlib.parse_gmassist_scenes(SPLIT_BY_ANOTHER_H2)]
    assert "Sister Kaella" not in names
