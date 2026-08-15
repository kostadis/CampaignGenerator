"""Tests for campaignlib/sheet_identity.py — reading a character's level off
a sheet that is about to be archived (feature 008).

The parser cases here are drawn from real files, not invented: ``Druid 5`` and
``Druid 6`` are what Phandalin's hand-archived ``old/level/5/Soma.md`` and its
live ``soma.md`` actually say, and ``Human Fighter 9 / Bard 2`` is a real
Hillsfar value. None of the campaign's existing sheets have frontmatter, which
is why the ``## Identity`` fallback is load-bearing rather than defensive.
"""

import sys
import textwrap
from pathlib import Path

import pytest

# D12 — see tests/test_sheet_naming.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from campaignlib.sheet_identity import (  # noqa: E402
    AmbiguousLevelError,
    parse_level,
    read_class_level,
    sheet_name,
)

NO_FRONTMATTER = textwrap.dedent("""\
    # Soma

    ## Identity
    - **Class & Level:** Druid 6
    - **Species:** Firbolg
    - **Player:** Wade

    ## Combat
    - **HP:** 44
    """)

WITH_FRONTMATTER = textwrap.dedent("""\
    ---
    name: Soma
    player: Wade
    species: Firbolg
    class_level: Druid 7
    subclass: ""
    ---
    """) + NO_FRONTMATTER


# ── parse_level ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase,level", [
    ("Monk 8", 8),
    ("Druid 5", 5),
    ("Warrior of the Elements Monk 12", 12),
    ("  Druid 6  ", 6),
])
def test_single_class_and_level_parses(phrase, level):
    assert parse_level(phrase) == level


@pytest.mark.parametrize("phrase", [
    "Fighter 9 / Bard 2",
    "Human Fighter 9 / Bard 2",
    "Fighter 9, Bard 2",
    "Fighter 9 and Bard 2",
])
def test_multiclass_refuses(phrase):
    """Not a sum, not a first-wins. Picking 11, 9 or 2 out of this invents
    precision the source lacks — the same reason class_level is kept as one
    undecomposed string."""
    with pytest.raises(AmbiguousLevelError):
        parse_level(phrase)


@pytest.mark.parametrize("phrase", [None, "", "   ", "Druid", "Level Five"])
def test_no_readable_level_refuses(phrase):
    with pytest.raises(AmbiguousLevelError):
        parse_level(phrase)


# ── read_class_level ───────────────────────────────────────────────────────

def test_reads_from_the_identity_block_when_there_is_no_frontmatter():
    """Every sheet in every campaign is currently shaped like this."""
    assert read_class_level(NO_FRONTMATTER) == "Druid 6"
    assert parse_level(read_class_level(NO_FRONTMATTER)) == 6


def test_frontmatter_wins_when_present():
    """The machine channel is preferred — #293 landed it on 19 sheets."""
    assert read_class_level(WITH_FRONTMATTER) == "Druid 7"


def test_empty_frontmatter_value_falls_through_to_the_identity_block():
    text = WITH_FRONTMATTER.replace("class_level: Druid 7", 'class_level: ""')
    assert read_class_level(text) == "Druid 6"


def test_a_sheet_stating_no_level_anywhere_reads_as_none():
    text = NO_FRONTMATTER.replace("- **Class & Level:** Druid 6\n", "")
    assert read_class_level(text) is None
    with pytest.raises(AmbiguousLevelError):
        parse_level(read_class_level(text))


def test_a_file_with_no_identity_block_reads_as_none():
    assert read_class_level("# Soma\n\nJust prose.\n") is None


# ── sheet_name (moved from sheet_frontmatter, D3) ──────────────────────────

def test_sheet_name_is_the_first_h1():
    assert sheet_name(NO_FRONTMATTER) == "Soma"
    assert sheet_name(WITH_FRONTMATTER) == "Soma"


def test_sheet_name_is_none_without_an_h1():
    assert sheet_name("## Identity\n- **Player:** Wade\n") is None
