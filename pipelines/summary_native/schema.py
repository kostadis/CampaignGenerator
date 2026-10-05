"""Shared vocabulary for the summary_native pipeline.

One home for the things every module must agree on: which H2 names are
recognised, how a category maps to a registry type, the finding codes (and
which of them block a run), the heading regexes, and the default values.
The defaults are declared HERE ONCE; the config model and the CLI import them
rather than re-spelling them (Principle XII).
"""

from __future__ import annotations

import re

# ── Sections ────────────────────────────────────────────────────────────────

SCENES = "Scenes"
MEMORABLE_MOMENTS = "Memorable Moments"
SESSION_END_STATE = "Session-End State"

RECOGNISED_SECTIONS: tuple[str, ...] = (
    "Scenes",
    "NPCs",
    "Locations",
    "Items",
    "Spells",
    "Abilities",
    "Memorable Moments",
    "Session-End State",
)

#: H2 name -> category key.
ENTITY_CATEGORIES: dict[str, str] = {
    "NPCs": "npc",
    "Locations": "location",
    "Items": "item",
    "Spells": "spell",
    "Abilities": "ability",
}

#: Category -> registry type allowed to supply exact aliases. Spells and
#: abilities are absent on purpose: the registry does not carry them, so those
#: categories group by identical heading text only (research R7).
CATEGORY_REGISTRY_TYPE: dict[str, str] = {
    "npc": "npc",
    "location": "location",
    "item": "item",
}

# ── Finding codes (research R2) ─────────────────────────────────────────────

NO_NUMERIC_PREFIX = "no-numeric-prefix"
DUPLICATE_CHAPTER = "duplicate-chapter"
MISSING_TITLE = "missing-title"
TITLE_CHAPTER_MISMATCH = "title-chapter-mismatch"
MISSING_SCENES = "missing-scenes"
EMPTY_SCENES = "empty-scenes"
BAD_SCENE_ID = "bad-scene-id"
SCENE_CHAPTER_MISMATCH = "scene-chapter-mismatch"
DUPLICATE_SCENE_ID = "duplicate-scene-id"
UNKNOWN_SECTION = "unknown-section"
POSSIBLE_DUPLICATE = "possible-duplicate"
STALE_RULING = "stale-ruling"
RANGE_GAP = "range-gap"
UNREADABLE_FILE = "unreadable-file"

#: Codes that stop `build` / `synth`. Everything else is advisory.
BLOCKING_CODES: frozenset[str] = frozenset(
    {
        NO_NUMERIC_PREFIX,
        DUPLICATE_CHAPTER,
        MISSING_TITLE,
        TITLE_CHAPTER_MISMATCH,
        MISSING_SCENES,
        EMPTY_SCENES,
        BAD_SCENE_ID,
        SCENE_CHAPTER_MISMATCH,
        DUPLICATE_SCENE_ID,
        UNREADABLE_FILE,
    }
)
NON_BLOCKING_CODES: frozenset[str] = frozenset(
    {UNKNOWN_SECTION, POSSIBLE_DUPLICATE, STALE_RULING, RANGE_GAP}
)
ALL_CODES: frozenset[str] = BLOCKING_CODES | NON_BLOCKING_CODES


def is_blocking(code: str) -> bool:
    return code in BLOCKING_CODES


# ── Regexes ─────────────────────────────────────────────────────────────────
# Heading regexes use a negative lookahead so `###` never matches the H2
# pattern and so on; a plain `^##` would match the first two hashes of `###`.

PREFIX_RE = re.compile(r"^(\d+)[-_.]")
TITLE_RE = re.compile(r"(?mi)^#\s+Chapter\s+(\d+)\b")
H2_RE = re.compile(r"^##(?!#)\s+(.+?)\s*$")
H3_RE = re.compile(r"^###(?!#)\s+(.+?)\s*$")
H4_RE = re.compile(r"^####(?!#)\s+(.+?)\s*$")
SCENE_ID_RE = re.compile(r"^(\d{3})\.(\d{2})\s+(.+)$")
DATE_RE = re.compile(r"^Date:\s*(.*?)\s*$")

# ── Defaults (declared once) ────────────────────────────────────────────────

DEFAULT_OUT_ROOT = "docs/summary_native"
DEFAULT_RECENT_CHAPTERS = 4
DEFAULT_RECURRING_MIN = 10
DEFAULT_DUP_THRESHOLD = 0.88
DEFAULT_PARTS = 0
DEFAULT_MAX_TOKENS = 16000

# ── Documents ───────────────────────────────────────────────────────────────

#: Every document the pipeline will eventually draft (FR-018).
DOCS: tuple[str, ...] = ("world_state", "campaign_state", "party", "planning")
#: The documents `synth` can draft today; US4 adds the others.
SYNTH_DOCS: tuple[str, ...] = ("world_state", "campaign_state")


def resolve_under(root, value):
    """Resolve a configured path: ``~`` expanded, relative ones against ``root``.

    The one resolver shared by the CLI and the web routes, so both read the
    same file for the same configured value.
    """
    from pathlib import Path

    p = Path(value).expanduser()
    return p if p.is_absolute() else Path(root) / p


def display_path(path, root):
    """``path`` relative to ``root`` when inside it, else absolute. Never raises."""
    from pathlib import Path

    p = Path(path)
    try:
        return str(p.relative_to(Path(root)))
    except ValueError:
        return str(p)
