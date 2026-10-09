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

# ── Chunked, code-checked grounding documents (spec 033) ────────────────────

#: Section heading text -> citation target key (research R3). A section's own heading, in any
#: case, is accepted as its key; any other heading is an invalid citation target.
SECTION_TARGETS: dict[str, str] = {
    "Memorable Moments": "moment",
    "NPCs": "npcs",
    "Locations": "locations",
    "Items": "items",
    "Spells": "spells",
    "Abilities": "abilities",
    "Session-End State": "end",
}
#: Extra spellings of a section heading that map exactly to its key.
SECTION_TARGET_ALIASES: dict[str, str] = {"memorable moment": "moment", "moments": "moment"}
#: One bracket of a state-note citation: ``[ch NNN / target]`` parts joined by "; ". The target is
#: a scene id or a section key (before heading-text normalisation).
STATE_CITE_RE = re.compile(r"\[ch [^\[\]]*\]")
STATE_CITE_PART_RE = re.compile(
    r"ch (\d{3}) / (\d{3}\.\d{2}|moment|npcs|locations|items|spells|abilities|end)"
)

#: The note grammar an extract call writes.
THREAD_TAGS = ("OPENED", "ADVANCED", "RESOLVED", "ABANDONED")
WORLD_TAGS = ("FACTION", "NPC", "LOCATION", "ITEM", "THREAT")
STATUSES = ("Alive", "Dead", "Missing", "Imprisoned", "Departed", "Unknown")
#: The six ``##`` sections of an extract call, in order. (``MAP_SECTIONS`` above is the NPC
#: dossier map's; this one is the state notes'.)
STATE_MAP_SECTIONS = ("## Events", "## Concluded", "## Threads", "## NPC Status", "## World", "## Party")

DEFAULT_EXTRACT_PARALLEL = 6
DEFAULT_PROSE_BACKEND = "claude-code"
DEFAULT_PROSE_MODEL = "claude-sonnet-5-5"
DEFAULT_PROSE_EFFORT = "medium"
#: Word budgets for world_state's prose sections (research R8, round 3).
DEFAULT_WORLD_BUDGETS: dict[str, int] = {
    "Party": 700,
    "Factions and Powers": 450,
    "Key NPCs": 900,
    "Locations": 450,
    "Items and Artifacts": 450,
    "Active Threats and Open Pressures": 600,
}
DEFAULT_AUDIT_CANDIDATES = 3

# ── Chunked party and planning (spec 034) ───────────────────────────────────

#: Word budgets for party's prose sections; ``Characters`` is per character (research R12).
DEFAULT_PARTY_BUDGETS: dict[str, int] = {"Party Overview": 300, "Characters": 500, "Party Dynamics": 300}
#: Word budgets for planning's prose sections (research R12).
DEFAULT_PLANNING_BUDGETS: dict[str, int] = {
    "NPC Dossiers": 1500, "Faction States": 600, "Active Plots": 1200, "DM Notes": 400,
}
#: Faction States writes at most this many factions; the rest are listed by name (research R9).
DEFAULT_MAX_FACTIONS = 20
#: ``thread-propose`` sends notes in batches no larger than this many characters (research R5).
DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS = 150000
#: The subject of a party-wide note: ``- **Party** — fact [cite]``.
PARTY_SUBJECT = "Party"
#: The tag of a level row: ``- [LEVEL] **Subject** — N [cite]``.
LEVEL_TAG = "LEVEL"
#: Active Plots, when no ratified thread has notes in the range.
NO_RATIFIED_THREADS = "_No ratified thread has notes in this range._"
#: Active Plots, when ratified threads have notes in the range but none of them is open.
NO_OPEN_THREADS = "_No ratified thread is open in this range._"
#: Faction States, when no faction is configured and none has notes in the range.
NO_FACTIONS = "_No faction is configured or has notes in this range._"
#: Where a party character's checked arc-score candidates go, inside that character's section. Code places
#: it; the model never writes it, and the annotators skip everything under it (spec 034 US4).
ARC_HEADING = "#### Candidate Arc Score Events"
#: The ``SECTION:`` line of an arc-score call's prompt, so a reader of a run directory can tell it apart.
ARC_CALL_SECTION = "## Candidate Arc Score Events"
DORMANT_HEADING = "### Dormant threads"
UNRATIFIED_HEADING = "### Unratified thread notes (not yet ruled on)"
#: Printed under DM Notes by code, so the section cannot be read as events.
DM_NOTES_LABEL = "_Suggestions for the GM, not events._"
#: Everything 033 writes lives under ``<range_dir>/state/``.
STATE_DIR = "state"
TIMELINE_FILE = "canon_events_timeline.md"
#: Beside the notes: the NPCs the latest world_state build found without a usable dossier (read by `GET /state`).
MISSING_DOSSIERS_FILE = "missing_dossiers.json"
#: planning's own file of the same shape, so one document's refusal is never shown as the other's.
MISSING_DOSSIERS_PLANNING_FILE = "missing_dossiers.planning.json"
#: Refusals shared by the CLI and the web routes (the routes answer 400 with the same words).
#: ``--parts`` on any document (spec 034, contracts/cli.md): every document is built one call per section.
PARTS_REFUSAL = "--parts is retired: every document is built one call per section from the checked notes"
#: Why ``--world-state`` / ``--campaign-state`` are gone (spec 034, contracts/cli.md).
UPSTREAM_REFUSAL = (
    "upstream drafts are no longer prompt context: party and planning build from the checked notes; "
    "review those documents on their own"
)
#: The retired ``synth`` options, by the name the CLI parser and the route's query string give them, and
#: the refusal each one gets (naming its replacement). A flag is refused when it is *present*, whatever its value.
RETIRED_SYNTH_FLAGS: dict[str, str] = {
    "parts": PARTS_REFUSAL,
    "world_state": f"--world-state is retired: {UPSTREAM_REFUSAL}",
    "campaign_state": f"--campaign-state is retired: {UPSTREAM_REFUSAL}",
}
#: ``--name`` / ``--recent-chapters`` / ``--recurring-min`` on party (spec 034, contracts/cli.md); the CLI prefixes the flag.
PARTY_SELECTION_REFUSAL = "party selects no NPCs; these apply to planning and world_state"
#: ``--fallback-npc-lines`` on party or campaign_state (spec 034, contracts/cli.md); the CLI prefixes the flag.
FALLBACK_NPC_LINES_REFUSAL = "applies to world_state and planning only"
STATE_AUDIT_REFUSAL ="--audit does not apply to campaign_state: the audit is its own step: summary_native audit"
#: Ends a Key NPCs line built by code for an NPC with no published dossier (``--fallback-npc-lines``).
KEY_NPC_FALLBACK_MARK = "(no published dossier — from checked notes)"
#: Shown in the Audit section until ``summary_native audit`` has run for the range.
AUDIT_NOT_RUN = "Audit not run for this range."


def missing_dossiers_file(doc: str) -> str:
    """The file (under ``state/``) holding the NPCs ``doc``'s latest build found without a usable dossier."""
    return MISSING_DOSSIERS_PLANNING_FILE if doc == "planning" else MISSING_DOSSIERS_FILE


def budget_report_file(doc: str) -> str:
    """The word-budget report beside ``doc``'s draft. world_state's keeps its name (``GET /state`` reads it);
    party and planning write their own, so one document's budgets never replace another's."""
    return f"budget_report.{doc}.json" if doc in ("party", "planning") else "budget_report.json"


def draft_dir(range_dir, doc: str):
    """Where ``doc``'s draft lives: ``state/drafts``, for every document (spec 034 retired the one-shot ``drafts/``)."""
    from pathlib import Path

    return Path(range_dir) / STATE_DIR / "drafts"

#: Annotation markers (research R10). Annotations are appended under a line; the line is never changed.
LATER = "⚠ later:"
SINCE = "ℹ since:"
UNVERIFIED = "⚠ unverified:"

# ── Documents ───────────────────────────────────────────────────────────────

#: Every document the pipeline will eventually draft (FR-018).
DOCS: tuple[str, ...] = ("world_state", "campaign_state", "party", "planning")
#: The documents `synth` can draft.
SYNTH_DOCS: tuple[str, ...] = DOCS
#: The documents built from the checked notes, one call per section (FR-029). Since spec 034, all four.
STATE_DOCS: tuple[str, ...] = DOCS


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
