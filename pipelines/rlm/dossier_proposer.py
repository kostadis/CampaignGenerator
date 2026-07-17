"""
dossier_proposer.py — slot retrieval hits into a human-reviewable proposal.

Phase 3 of the RLM integration plan enforces:

    "Render pipelines refuse to run without an approved proposal file."

This module is the producer of that file. Given a free-text query (a
session beat, a character name, a faction, whatever) it runs the Phase 2
``rpg_retriever.retrieve`` and organizes the three-state result into
typed slots — NPC candidates, locations, encounters, stat blocks, lore,
conversion suggestions — then writes the result as markdown to
``docs/dossier_proposal.md``.

Crucially this module **never** calls Claude. The slotting is
deterministic keyword matching. An LLM reads the file and picks what it
wants; a human edits it in place; only then do render pipelines
(``prep.py``, ``session_doc.py``, ``planning.py``) consume it as
grounding.

Rationale (CLAUDE.md global rule): LLMs render, humans impose scope.

Usage (library):

    from pipelines.rlm.dossier_proposer import propose

    md = propose(
        "party arrives at Icespire Hold",
        campaign_dir="/home/.../icespire",
        palace="/mnt/data/mempalace/palaces/chat",
        limit=20,
    )
    Path("docs/dossier_proposal.md").write_text(md)

Usage (CLI):

    dossier_proposer "party arrives at Icespire Hold"
    dossier_proposer "Strahd" --output docs/dossier_proposal.md
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .rpg_retriever import retrieve

logger = logging.getLogger(__name__)


_DEFAULT_OUTPUT = Path("docs/dossier_proposal.md")


# ── Keyword classifiers (deterministic; no LLM) ──────────────────────────


_LOCATION_WORDS = (
    "hold", "keep", "tower", "temple", "shrine", "citadel", "fortress",
    "castle", "manor", "hall", "gate", "bridge", "river", "forest",
    "wood", "mountain", "valley", "cavern", "cave", "dungeon", "ruins",
    "crypt", "tomb", "island", "village", "town", "city", "harbor",
    "port", "camp", "outpost", "lair", "sanctum", "grove", "marsh",
    "swamp", "desert", "wastes", "plateau", "peak", "pass", "vault",
    "arena", "inn", "tavern", "market", "palace", "garden", "bazaar",
)

_ENCOUNTER_WORDS = (
    "attack", "attacks", "ambush", "ambushes", "fight", "fights", "combat",
    "battle", "battles", "clash", "confront", "confronts", "engage",
    "engages", "skirmish", "assault", "siege", "duel", "raid",
    "stalk", "hunt", "charge", "strike", "strikes", "pursuit",
    "chase", "trap", "traps", "encounter", "encounters",
)

_NPC_HINT_WORDS = (
    "priest", "priestess", "captain", "sergeant", "commander",
    "lord", "lady", "king", "queen", "duke", "duchess", "baron",
    "baroness", "prince", "princess", "earl", "chief", "chieftain",
    "warlock", "wizard", "sorcerer", "druid", "cleric", "paladin",
    "ranger", "fighter", "rogue", "bard", "monk", "barbarian",
    "smith", "innkeeper", "townmaster", "merchant", "scholar",
    "sage", "oracle", "warden", "mayor", "elder", "shopkeeper",
    "guard", "mercenary", "advisor", "emissary", "envoy",
)


def _word_boundary_re(words: tuple[str, ...]) -> re.Pattern:
    """Compile a case-insensitive \\b(word1|word2|…)\\b regex.

    Word-boundary matching prevents "town" in `townmaster` from firing
    the location heuristic — a common cause of NPC hits being misfiled
    as locations.
    """
    pattern = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_LOCATION_RE = _word_boundary_re(_LOCATION_WORDS)
_ENCOUNTER_RE = _word_boundary_re(_ENCOUNTER_WORDS)
_NPC_HINT_RE = _word_boundary_re(_NPC_HINT_WORDS)

# A proper noun is "a single capitalized word ≥ 3 chars, not sentence-start
# (heuristic: preceded by whitespace or punctuation not at string start)."
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z][a-zA-Z'’\-]{1,})\b")

# Very rough first-letter-capital sequences that look like a person name
# ("Grundar Quartzvein", "Harbin Wester"). Two or more capitalized tokens
# in a row.
_NAMED_ENTITY_RE = re.compile(
    r"\b([A-Z][a-zA-Z’'\-]{1,}(?:\s+[A-Z][a-zA-Z’'\-]{1,}){1,3})\b"
)


# ── Slot types ───────────────────────────────────────────────────────────


@dataclass
class Candidate:
    """One proposal entry — a hit classified into a slot."""

    slot: str
    label: str
    excerpt: str
    drawer_id: str | None = None
    kind: str = "drawer"
    book_id: int | None = None
    book_title: str | None = None
    section_path: str | None = None
    page: int | None = None
    source: str | None = None
    similarity: float | None = None
    entities: list[str] = field(default_factory=list)
    conversion_hint: dict | None = None


@dataclass
class Proposal:
    query: str
    campaign_dir: str
    palace: str | None
    rpglib_db: str | None
    generated_at: str
    slots: dict[str, list[Candidate]]
    raw_hit_count: int
    fallback: bool
    fallback_reason: str | None
    notes: list[str] = field(default_factory=list)


# ── Slotting ─────────────────────────────────────────────────────────────


def _excerpt(text: str | None, limit: int = 280) -> str:
    if not isinstance(text, str):
        return ""
    stripped = " ".join(text.split())
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _extract_named_entities(text: str | None, max_results: int = 5) -> list[str]:
    """Pull proper-noun clusters out of free text, deduped and ordered by
    first appearance. Pure heuristic — no POS tagging, no LLM. Skips
    common sentence-starters handled by the same stoplist MemPalace uses.
    """
    if not text:
        return []
    stopwords = {
        "The", "This", "That", "These", "Those", "When", "Where", "What",
        "Why", "Who", "Which", "How", "After", "Before", "Then", "Now",
        "Here", "There", "And", "But", "Or",
    }
    seen: dict[str, None] = {}
    for match in _NAMED_ENTITY_RE.finditer(text):
        name = match.group(1).strip()
        first = name.split()[0]
        if first in stopwords:
            continue
        if name not in seen:
            seen[name] = None
        if len(seen) >= max_results:
            break
    # Intentionally no single-proper-noun fallback: a lone capitalized word
    # is indistinguishable from a sentence-start (e.g. "Generic lore…"). The
    # NPC classifier relies on multi-token named clusters only, which is
    # strict enough to avoid misfiling bare sentences.
    return list(seen.keys())


def _looks_like_encounter(hit: dict) -> bool:
    return bool(_ENCOUNTER_RE.search(hit.get("drawer_text") or ""))


def _looks_like_npc(hit: dict) -> bool:
    text = hit.get("drawer_text") or ""
    if _NPC_HINT_RE.search(text):
        return True
    # Named-entity heuristic: a drawer that mentions 1+ proper-noun
    # clusters but has no location/encounter signal → probably an NPC.
    # The caller has already ruled those signals out by classify order.
    named = _extract_named_entities(text)
    return len(named) >= 1


def _looks_like_location(hit: dict) -> bool:
    entry_type = (hit.get("entry_type") or "").lower()
    section_path = hit.get("section_path") or ""
    text = hit.get("drawer_text") or ""
    if entry_type in ("section", "inset", "entries") and _LOCATION_RE.search(text):
        return True
    # A section-path tail like "Icespire Hold" or "the forest" is a
    # strong location signal even when the body prose is thin.
    if section_path:
        tail = section_path.split("/")[-1]
        if _LOCATION_RE.search(tail):
            return True
    return False


def classify(hit: dict) -> str:
    """Return the slot name for one hit. Deterministic keyword match.

    Classifier order (strongest signal wins):
      1. kind=="candidate" + cost=="cheap"      → ingest_cheap
      2. kind=="candidate" + cost=="expensive"  → ingest_expensive
      3. kind=="statblock"                      → statblock
      4. encounter verbs                        → encounter
      5. NPC hint / named                       → npc
      6. location keywords                      → location
      7. otherwise                              → lore

    Encounters and NPCs are pulled up above locations so a drawer like
    "bandits ambush the party at the narrow pass" doesn't get misfiled
    as a location just because the word "pass" appears.
    """
    kind = hit.get("kind")
    if kind == "candidate":
        cost = hit.get("cost")
        if cost == "cheap":
            return "ingest_cheap"
        if cost == "expensive":
            return "ingest_expensive"
        return "ingest_expensive"  # legacy fall-through
    if kind == "statblock":
        return "statblock"
    if _looks_like_encounter(hit):
        return "encounter"
    if _looks_like_npc(hit):
        return "npc"
    if _looks_like_location(hit):
        return "location"
    return "lore"


def _slot_label(hit: dict, slot: str) -> str:
    """Best-effort human-readable label for a candidate."""
    for key in ("statblock_name", "name", "title", "section_path"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().split("/")[-1].strip()
    named = _extract_named_entities(hit.get("drawer_text"))
    if named:
        return named[0]
    text = (hit.get("drawer_text") or "").splitlines()[0]
    return text.strip() or f"unnamed {slot}"


def build_candidate(hit: dict) -> Candidate:
    slot = classify(hit)
    label = _slot_label(hit, slot)
    excerpt = _excerpt(hit.get("drawer_text"))
    entities = _extract_named_entities(hit.get("drawer_text"))

    conversion_hint = None
    if hit.get("kind") == "candidate":
        cost = hit.get("cost", "expensive")
        if cost == "cheap":
            conversion_hint = {
                "cost": "cheap",
                "ingest_command": hit.get("ingest_command", []),
                "command": hit.get("command"),
                "file_path": hit.get("file_path"),
                "entity_type": hit.get("entity_type"),
                "name": hit.get("name"),
                "source": hit.get("source"),
                "chapter_ordinal": hit.get("chapter_ordinal"),
                "page": hit.get("page"),
                "notes": [],
            }
        else:
            conversion_hint = {
                "cost": "expensive",
                "convert_command": hit.get("convert_command", []),
                "ingest_command": hit.get("ingest_command", []),
                "command": hit.get("command"),
                "filepath": hit.get("filepath"),
                "relative_path": hit.get("relative_path"),
                "product_id": hit.get("product_id"),
                "estimated_cost_tokens": hit.get("estimated_cost_tokens"),
                "estimated_cost_usd_min": hit.get("estimated_cost_usd_min"),
                "estimated_cost_usd_max": hit.get("estimated_cost_usd_max"),
                "notes": hit.get("notes", []),
            }

    return Candidate(
        slot=slot,
        label=label,
        excerpt=excerpt,
        drawer_id=hit.get("drawer_id"),
        kind=hit.get("kind", "drawer"),
        book_id=hit.get("book_id"),
        book_title=hit.get("title"),
        section_path=hit.get("section_path"),
        page=hit.get("page") if isinstance(hit.get("page"), int) else None,
        source=hit.get("source"),
        similarity=hit.get("similarity"),
        entities=entities,
        conversion_hint=conversion_hint,
    )


def group_candidates(hits: list[dict]) -> dict[str, list[Candidate]]:
    """Slot every hit. Returns a dict keyed by slot name with stable ordering."""
    slots: dict[str, list[Candidate]] = {
        "npc": [],
        "location": [],
        "encounter": [],
        "statblock": [],
        "lore": [],
        "ingest_cheap": [],
        "ingest_expensive": [],
    }
    for hit in hits:
        cand = build_candidate(hit)
        slots[cand.slot].append(cand)
    return slots


# ── Markdown rendering (pure string work, no I/O) ────────────────────────


_SLOT_HEADERS = [
    ("npc", "NPC Candidates"),
    ("location", "Locations"),
    ("encounter", "Encounters"),
    ("statblock", "Stat Blocks"),
    ("lore", "Lore & Background"),
    ("ingest_cheap", "Cheap Ingest Candidates (5etools-canonical JSON on disk)"),
    ("ingest_expensive", "Expensive Ingest Candidates (rpg-library PDFs needing conversion)"),
]


def _render_candidate(c: Candidate, index: int) -> str:
    lines: list[str] = [f"### {index}. {c.label}"]
    bits = []
    if c.book_title:
        bits.append(f"**book**: {c.book_title}")
    if c.section_path:
        bits.append(f"**section**: `{c.section_path}`")
    if c.page and c.page > 0:
        bits.append(f"**page**: {c.page}")
    if c.similarity is not None:
        bits.append(f"**similarity**: {c.similarity:.2f}")
    if c.drawer_id:
        bits.append(f"**drawer**: `{c.drawer_id}`")
    elif c.book_id is not None:
        bits.append(f"**book_id**: {c.book_id}")
    if bits:
        lines.append("  ".join(bits))
    if c.entities:
        lines.append(f"**named**: {', '.join(c.entities)}")
    if c.excerpt:
        lines.append("")
        lines.append("> " + c.excerpt)
    if c.conversion_hint:
        hint = c.conversion_hint
        cost = hint.get("cost", "expensive")
        cmd_convert = " ".join(hint.get("convert_command") or [])
        cmd_ingest = " ".join(hint.get("ingest_command") or [])
        lines.append("")
        if cost == "cheap":
            lines.append(
                "**cheap ingest** "
                f"(5etools JSON on disk: `{hint.get('file_path', '?')}`)"
            )
            if cmd_ingest:
                lines.append(f"```\n{cmd_ingest}\n```")
        else:
            lines.append("**expensive ingest** (PDF → JSON via pdf-translators v2)")
            if cmd_convert:
                lines.append("**convert:**")
                lines.append(f"```\n{cmd_convert}\n```")
            if cmd_ingest:
                lines.append("**then ingest:**")
                lines.append(f"```\n{cmd_ingest}\n```")
            tokens = hint.get("estimated_cost_tokens")
            cost_lo = hint.get("estimated_cost_usd_min")
            cost_hi = hint.get("estimated_cost_usd_max")
            if tokens:
                lines.append(
                    f"estimated: ~{tokens:,} tokens  (~${cost_lo:.2f}–${cost_hi:.2f})"
                )
        for note in hint.get("notes") or []:
            lines.append(f"- note: {note}")
    return "\n".join(lines)


def render(proposal: Proposal) -> str:
    """Pure function: turn a Proposal into the dossier_proposal.md text."""
    out: list[str] = []
    out.append(f"# Dossier Proposal — {proposal.query}")
    out.append("")
    out.append(
        "> **Status:** candidates only. Review, delete, reorder, and "
        "edit before any render pipeline (prep / session_doc / planning) "
        "consumes this file."
    )
    out.append("")
    out.append("## Metadata")
    out.append(f"- generated_at: {proposal.generated_at}")
    out.append(f"- campaign_dir: `{proposal.campaign_dir}`")
    if proposal.palace:
        out.append(f"- palace: `{proposal.palace}`")
    if proposal.rpglib_db:
        out.append(f"- rpglib_db: `{proposal.rpglib_db}`")
    out.append(f"- raw_hit_count: {proposal.raw_hit_count}")
    if proposal.fallback:
        reason = proposal.fallback_reason or "(reason not provided)"
        out.append(f"- **fallback active**: {reason}")
    for note in proposal.notes:
        out.append(f"- note: {note}")
    out.append("")

    for slot_key, header in _SLOT_HEADERS:
        items = proposal.slots.get(slot_key, [])
        if not items:
            continue
        out.append(f"## {header}")
        out.append("")
        for idx, c in enumerate(items, start=1):
            out.append(_render_candidate(c, idx))
            out.append("")
        out.append("")

    empty_slots = [h for k, h in _SLOT_HEADERS if not proposal.slots.get(k)]
    if empty_slots:
        out.append("---")
        out.append("")
        out.append(
            "_Empty slots: " + ", ".join(empty_slots) + "._"
        )

    out.append("")
    out.append("## Approval")
    out.append("")
    out.append(
        "Rendering pipelines should refuse to run unless this file is "
        "present and the header line above is edited from the default "
        "`> **Status:** candidates only.` to e.g. "
        "`> **Status:** approved by <name> on <date>.`"
    )
    out.append("")
    return "\n".join(out)


# ── Pure approval marker ─────────────────────────────────────────────────


_STATUS_LINE_RE = re.compile(r"^>\s*\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)


def is_approved(markdown: str) -> bool:
    """Return True when the proposal file's status line has been edited
    away from the default ``candidates only`` banner.
    """
    if not isinstance(markdown, str):
        return False
    match = _STATUS_LINE_RE.search(markdown)
    if match is None:
        return False
    status = match.group(1).strip().lower()
    return not status.startswith("candidates only")


# ── Orchestrator ─────────────────────────────────────────────────────────


def propose(
    query: str,
    *,
    campaign_dir: str | os.PathLike | None = None,
    palace: str | None = None,
    rpg_library_url: str | None = None,
    fivetools_data_root: str | os.PathLike | None = None,
    limit: int = 20,
    k_cheap: int = 10,
    k_expensive: int = 5,
    include_cheap: bool = True,
    include_expensive: bool = True,
    retriever=retrieve,
    **retriever_kwargs: Any,
) -> Proposal:
    """Run retrieval and slot the hits. Does not call Claude."""
    campaign_dir_str = str(Path(campaign_dir).expanduser().resolve()) if campaign_dir else str(
        Path.cwd().resolve()
    )
    retriever_kwargs.setdefault("limit", limit)
    if rpg_library_url:
        retriever_kwargs["rpg_library_url"] = rpg_library_url
    if fivetools_data_root:
        retriever_kwargs["fivetools_data_root"] = (
            Path(fivetools_data_root).expanduser()
        )
    retriever_result = retriever(
        query,
        palace=palace,
        k_cheap=k_cheap,
        k_expensive=k_expensive,
        include_cheap=include_cheap,
        include_expensive=include_expensive,
        **retriever_kwargs,
    )
    hits = retriever_result.get("hits", [])
    slots = group_candidates(hits)

    return Proposal(
        query=query,
        campaign_dir=campaign_dir_str,
        palace=palace,
        rpglib_db=rpg_library_url,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        slots=slots,
        raw_hit_count=len(hits),
        fallback=bool(retriever_result.get("fallback")),
        fallback_reason=retriever_result.get("fallback_reason"),
        notes=[],
    )


def write_proposal(
    markdown: str,
    output_path: Path,
    *,
    overwrite: bool = True,
) -> Path:
    """Write the rendered markdown to ``output_path``. Creates parents."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists (pass --force to overwrite)")
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("query", help="Free-text query to build a proposal for.")
    parser.add_argument(
        "--campaign-dir",
        type=Path,
        default=None,
        help="Campaign workspace directory (default: $CAMPAIGN_DIR or CWD).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output path (default <campaign-dir>/{_DEFAULT_OUTPUT}).",
    )
    parser.add_argument("--palace", default=None)
    parser.add_argument("--rpg-library-url", default=None)
    parser.add_argument("--fivetools-data-root", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--k-cheap", type=int, default=10)
    parser.add_argument("--k-expensive", type=int, default=5)
    parser.add_argument(
        "--no-cheap", dest="include_cheap", action="store_false", default=True,
    )
    parser.add_argument(
        "--no-expensive", dest="include_expensive", action="store_false", default=True,
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print rendered markdown to stdout instead of writing to disk.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def _resolve_campaign_dir(arg: Path | None) -> Path:
    if arg is not None:
        return arg.expanduser().resolve()
    env = os.environ.get("CAMPAIGN_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    campaign_dir = _resolve_campaign_dir(args.campaign_dir)
    proposal = propose(
        args.query,
        campaign_dir=campaign_dir,
        palace=args.palace,
        rpg_library_url=args.rpg_library_url,
        fivetools_data_root=args.fivetools_data_root,
        limit=args.limit,
        k_cheap=args.k_cheap,
        k_expensive=args.k_expensive,
        include_cheap=args.include_cheap,
        include_expensive=args.include_expensive,
    )
    markdown = render(proposal)
    if args.print:
        print(markdown)
        return 0
    output = args.output or (campaign_dir / _DEFAULT_OUTPUT)
    write_proposal(markdown, output, overwrite=args.force or not output.exists())
    print(f"dossier_proposer: wrote {output} ({proposal.raw_hit_count} hits)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
