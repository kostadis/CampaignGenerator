"""Shared vocabulary for the summary_native pipeline.

One home for the things every module must agree on: which H2 names are
recognised, how a category maps to a registry type, the finding codes (and
which of them block a run), the heading regexes, and the default values.
The defaults are declared HERE ONCE; the config model and the CLI import them
rather than re-spelling them (Principle XII).
"""

from __future__ import annotations

import re

# Declared in campaignlib (which must not import from pipelines/) and re-exported
# here so there is one spelling of the header prefix (spec 032 T001, Principle XII).
from campaignlib.npc import PUBLISH_HEADER_PREFIX  # noqa: F401

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

# Link findings (spec 032). All non-blocking: they describe what npc-link withheld
# or noticed, never a reason to stop the run.
AMBIGUOUS_FORM = "ambiguous-form"
GENERIC_FORM = "generic-form"
STALE_LINK_RULING = "stale-link-ruling"
LINK_RULING_UNNEEDED = "link-ruling-unneeded"
MENTION_WITHOUT_HEADING = "mention-without-heading"
PLAYER_CHARACTER_UNRESOLVED = "player-character-unresolved"

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
    {
        UNKNOWN_SECTION,
        POSSIBLE_DUPLICATE,
        STALE_RULING,
        RANGE_GAP,
        AMBIGUOUS_FORM,
        GENERIC_FORM,
        STALE_LINK_RULING,
        LINK_RULING_UNNEEDED,
        MENTION_WITHOUT_HEADING,
        PLAYER_CHARACTER_UNRESOLVED,
    }
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

# Citation grammar (contracts/files.md). One bracket holds one or more
# ``ch NNN / target`` parts separated by "; "; a scene id's chapter part must
# equal the CHAPTER (checked by npc_verify, not expressible in a regex).
_CITE_PART = r"ch \d{3} / (?:\d{3}\.\d{2}|entry|moment)"
CITATION_RE = re.compile(rf"\[{_CITE_PART}(?:; {_CITE_PART})*\]")
#: One part inside a matched bracket: (chapter, target).
CITATION_PART_RE = re.compile(r"ch (\d{3}) / (\d{3}\.\d{2}|entry|moment)")
#: ``[manual N]`` — N is the 1-based position in the authored ``manual`` list.
MANUAL_CITATION_RE = re.compile(r"\[manual (\d+)\]")

# ── Defaults (declared once) ────────────────────────────────────────────────

DEFAULT_OUT_ROOT = "docs/summary_native"
DEFAULT_RECENT_CHAPTERS = 4
DEFAULT_RECURRING_MIN = 10
DEFAULT_DUP_THRESHOLD = 0.88
DEFAULT_PARTS = 0
DEFAULT_MAX_TOKENS = 16000

# ── NPC dossiers (spec 032) ─────────────────────────────────────────────────

DEFAULT_NPC_ROOT = "docs/npcs/summary_native"
NPCS_DIR = "docs/npcs"
AUTHORED_DIR = "docs/npcs/authored"
DISTILLED_DIR = "docs/npcs/distilled"
#: Where ``planning --build-dossiers`` keeps its per-chunk extracts when --extract-dir is
#: not given. Outside docs/npcs/, which may hold only published dossiers and its subdirectories.
PLANNING_EXTRACTIONS_DIR = "docs/planning_extractions"
NPC_OUTLINE = "npc_dossier"
EXIT_VERIFY_FAILED = 5

# Drafting defaults (spec 032 T059, GM rulings 2026-10-06). The dgx endpoint is deliberately
# NOT declared here: it resolves through campaignlib's chain (--endpoint, DGX_ENDPOINT, wiring).
DEFAULT_DRAFT_BACKEND = "dgx"
DEFAULT_DRAFT_MODEL = "qwen3.8-flash-next"
DEFAULT_DRAFT_MODE = "chunked"
DRAFT_MODES = ("chunked", "one-shot")
DEFAULT_CHUNK_CHARS = 60000
#: The ``draft:`` keys ``npc_dossiers.yaml`` may carry; any other key refuses.
DRAFT_CONFIG_KEYS = ("backend", "model", "mode", "chunk_chars")
#: Outline sections a chunked map call writes (code-verified, stitched); the reduce call
#: writes the remaining outline sections.
MAP_SECTIONS = ("## History with the Party", "## Notable Quotes", "## Arc-Score Candidates")
#: Attributions that are placeholders, not a speaker (advisory ``placeholder-speaker``).
PLACEHOLDER_SPEAKERS = ("speaker", "unknown", "unnamed", "narrator", "someone", "n/a")
#: Written by code in place of a map section whose every item failed the map check.
NONE_VERIFIED = "_(none verified)_"

# ── Documents ───────────────────────────────────────────────────────────────

#: Every document the pipeline will eventually draft (FR-018).
DOCS: tuple[str, ...] = ("world_state", "campaign_state", "party", "planning")
#: The documents `synth` can draft.
SYNTH_DOCS: tuple[str, ...] = DOCS


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
