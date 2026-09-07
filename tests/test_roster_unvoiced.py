"""The roster block distinguishes "in the party" from "voiced this session".

Filters A and B stop an unvoiced character *narrating*. They say nothing about
how the character is *rendered*, and the roster block is the anchor Pass 5 is
told never to contradict — so before this it told the renderer that Brewbarry
was simply in the party, with nothing about who spoke for him.

The trap this feature had to avoid is the opposite of the original bug. His
player was absent; *he was in the tavern*, because the GM put him there and
narrated him walking in. A marker reading "not at this session" would make the
never-contradict block assert something the extraction flatly contradicts. So
these tests assert the marker's WORDING, not merely its presence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.party_config import (  # noqa: E402
    ResolvedCharacter,
    ResolvedPartyConfig,
)
from session_doc.roster import UNVOICED_MARKER, roster_from_config  # noqa: E402

SHEET = """---
name: {name}
player: SHEET VALUE — must not be read
species: {species}
class_level: {cls}
subclass: ''
---

# {name}
"""

CAST = [
    ("Vukradin", "Human", "Bard 6"),
    ("Soma", "Tabaxi", "Druid 6"),
    ("Brewbarry", "Halfling", "Rogue 6"),
]


def _party(tmp_path):
    """Built from ResolvedCharacter directly, as tests/test_roster.py does."""
    characters = []
    for name, species, cls in CAST:
        sheet = tmp_path / f"{name.lower()}.md"
        sheet.write_text(
            SHEET.format(name=name, species=species, cls=cls), encoding="utf-8"
        )
        characters.append(ResolvedCharacter(name=name, sheet=sheet))
    return ResolvedPartyConfig(characters=characters)


# ── T032: inert without attendance ──────────────────────────────────────────

def test_no_attendance_argument_renders_exactly_as_before(tmp_path):
    cfg = _party(tmp_path)
    assert roster_from_config(cfg) == roster_from_config(cfg, None)


def test_no_attendance_argument_marks_nobody(tmp_path):
    out = roster_from_config(_party(tmp_path))
    assert UNVOICED_MARKER not in out


def test_an_empty_unvoiced_set_marks_nobody(tmp_path):
    out = roster_from_config(_party(tmp_path), set())
    assert UNVOICED_MARKER not in out


# ── T031: the marker ────────────────────────────────────────────────────────

def test_unvoiced_character_is_marked(tmp_path):
    out = roster_from_config(_party(tmp_path), {"Brewbarry"})
    line = next(ln for ln in out.splitlines() if ln.startswith("- Brewbarry"))
    assert UNVOICED_MARKER.strip() in line


def test_voiced_characters_are_not_marked(tmp_path):
    out = roster_from_config(_party(tmp_path), {"Brewbarry"})
    for name in ("Vukradin", "Soma"):
        line = next(ln for ln in out.splitlines() if ln.startswith(f"- {name}"))
        assert UNVOICED_MARKER.strip() not in line


def test_grounding_survives_the_marker(tmp_path):
    """FR-024: an unvoiced character keeps species and class through the
    marker. Omitting them would leave Pass 5 narrating the GM's placement of
    a character it holds no facts about.

    #398 rewrite: FR-024 originally covered ``player`` too, and this test
    asserted the player's name survived alongside them. #398 deletes the
    person's name from the roster block entirely, so the assertion is now the
    opposite — the marker must not smuggle a name in either.
    """
    out = roster_from_config(_party(tmp_path), {"Brewbarry"})
    line = next(ln for ln in out.splitlines() if ln.startswith("- Brewbarry"))
    assert "Halfling" in line and "Rogue 6" in line
    assert "(" not in line  # no subclass here, so any "(" would be a name leak


# ── D7: the wording is the risk ─────────────────────────────────────────────

def test_marker_speaks_about_voicing_not_about_presence():
    """The marker must not assert the character was absent from the fiction."""
    lowered = UNVOICED_MARKER.lower()
    assert "voiced" in lowered
    for forbidden in ("not present", "was not in", "absent from the scene",
                      "not at this session", "did not attend"):
        assert forbidden not in lowered, (
            f"{forbidden!r} would contradict a GM who placed the character in a "
            "scene — the fabrication risk pointed the other way"
        )


def test_marker_tells_the_renderer_what_to_do_about_it():
    lowered = UNVOICED_MARKER.lower()
    assert "invent no dialogue" in lowered
    assert "gm may still have placed them" in lowered


def test_marker_is_a_suffix_not_a_replacement(tmp_path):
    """It extends the existing line shape rather than restructuring the block,
    so every prompt that reads the roster sees the same format."""
    cfg = _party(tmp_path)
    plain = roster_from_config(cfg)
    marked = roster_from_config(cfg, {"Brewbarry"})
    assert len(plain.splitlines()) == len(marked.splitlines())
    assert marked.startswith(plain.split("\n")[0])
