#!/usr/bin/env python3
"""Synthesise world_state.md from a corpus of ensemble merged.json files.

This is ``distill.py``'s **synthesis pass**, with the local-LLM ensemble's
``merged.json`` corpus swapped in for the Claude ``distill_extractions/
extract_*.md`` corpus. Same synthesis prompt (``distill_synthesize``), same
output document — only the upstream extractor changed (Claude pass-1 →
local 5-lens ensemble). Keeping the prompt identical makes this a true
drop-in replacement and isolates the one variable under test: whether the
local facts synthesise as well as Claude's extracts.

Pipeline::

    session_NN.md
      → ensemble_extract.py            (5 local-LLM lenses, DGX)
    merged_NN.json                      (atomic facts, deterministic merge)
      → synthesise_world_state.py       (this script: render + Claude synth)
    world_state.md                      (cumulative campaign canon)

Per the LLM Pipeline Design Rule, the two LLM stages are separated by a
deterministic, human-reviewable checkpoint:

    local LLM extracts → deterministic merge (merged.json, reviewed)
        → deterministic render to structured input (no LLM)
        → Claude synthesises inside that structure → human reviews world_state

The render step is pure code: atomic facts are grouped by (type, subject)
into the same profile shape the ``extract_*.md`` files use. No model decides
scope, ordering, or attribution at that boundary. Claude only renders the
verified structure into cumulative canon. Each fact can carry its
``source_quote`` into synthesis (``--quotes``, default on) so a wrong fact
is more likely to sit beside the verbatim text that corrects it.

Grounding context fed alongside the corpus:
  --party        party.yaml — PC roster; anchors the Party section so the
                 canonical player characters always get a profile.
  --inventory    module proper-noun inventory; authoritative spellings and
                 identities (Velkenyvelve → Velkynvelve, etc.).
  --backstories  per-PC backstory docs; campaign-level background the
                 session facts never restate.

The existing world_state.md is NOT fed in (it is the OUTPUT of this
pipeline, regenerated from the corpus — feeding it back would anchor the
regen to stale content). --output is required and is never defaulted to
docs/world_state.md, so a partial corpus cannot silently overwrite the
full-campaign canon. Point it at a scratch file, diff, then promote.

Usage::

    python synthesise_world_state.py \\
        --corpus 'runs/*/merged.json' \\
        --party docs/party.yaml \\
        --inventory ~/campaigns/.../module_inventory.md \\
        --backstories 'docs/*_backstory.md' \\
        --output docs/world_state.generated.md \\
        --model claude-opus-4-7
"""

import argparse
import glob as globmod
import json
import re
import sys
import warnings
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import yaml

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    client_from_args,
    load_agent_prompt,
    load_party_names,  # re-exported for back-compat; canonical home is campaignlib.party
    load_registry,
    make_client,
    resolve_registry_arg,
    run_single_batch,
    split_frontmatter,
    stream_api,
)

# Same synthesis prompt distill.py uses — this script only swaps the input
# corpus, so the prompt must stay identical for the comparison to be honest.
SYNTHESIZE_SYSTEM = load_agent_prompt("distill_synthesize")

# Render order mirrors synthesise_facts.py / the extract_*.md profile shape.
TYPE_ORDER = ["npc", "monster", "faction", "location", "object", "date", "event", "thread"]
TYPE_HEADINGS = {
    "npc": "NPCs",
    "monster": "Monsters",
    "faction": "Factions",
    "location": "Locations",
    "object": "Objects",
    "date": "Dates & Temporal Anchors",
    "event": "World Events",
    "thread": "Threads & Mysteries",
}

INVENTORY_PREAMBLE = """The following is the canonical name and entity inventory for this campaign, compiled by the GM from the source module. Treat it as the authoritative reference for spellings, factions, identities, and backgrounds. When a fact uses a variant spelling that clearly matches an inventory entry (Velkenyvelve → Velkynvelve, Sloopdopblop → Sloobludop), use the canonical spelling in your output. Use inventory descriptions to enrich profiles where the facts are silent on faction, race, or role. Never let the inventory override what the session facts say happened.

---

CANONICAL INVENTORY:

"""

ROSTER_PREAMBLE = """These are the campaign's player characters. Every one of them MUST receive a profile in the world_state document, anchored as the party section, even if the supplied facts touch them only lightly:

"""

GROUNDING_NOTE = """\
Two kinds of source material follow.

1. SESSION FACT EXTRACTS — atomic facts pulled from each session, grouped by
   type and subject. These are the authoritative record of WHAT HAPPENED.
   The sessions appear in CHRONOLOGICAL ORDER, earliest first; each block is
   headed with its session number and in-world date(s). When sessions disagree
   about the CURRENT state of a person, place, or thing, the LATER session
   always wins — a fact from an earlier session describes a past moment, not
   the present. The FINAL session reflects the current state of the world; do
   not report a stale earlier situation (a wound since healed, a captivity
   since escaped, a location since left) as if it were still true. Where a
   fact is followed by an indented "> quote", that is verbatim source text
   supporting it; rely on it to disambiguate, and do not assert beyond what
   the facts and their quotes support.
2. PLAYER CHARACTER BACKSTORIES — campaign-level background the session facts
   do not restate. Use these to enrich the party profiles, not to invent
   session events.
"""

DOSSIER_GROUNDING = """\
The source material below is already distilled. Synthesise it into the
world_state document.

1. ENTITY DOSSIERS — one per NPC, faction, location, object, or monster. Each
   is a CURRENT-STATE summary already reconciled across the whole campaign
   (later chapters override earlier), with a "## Uncertainty" block listing what
   could not be confirmed. Treat the dossier body as current; fold the
   Uncertainty items into open threads or omit them — do NOT assert an uncertain
   claim as settled fact. A dossier's roster of "current companions" may be
   stale (it was written from that one entity's facts); reconcile party
   membership across dossiers and the player-character roster, not from any
   single dossier's companion list.

   They arrive in two segments, and the split is chronological, not editorial:

   * RECENT ENTITIES — everyone touched in the most recent chapters. This is
     the PRESENT. Whatever the document says about where the party is, who is
     alive, and what is unresolved must be consistent with this segment, and an
     entity here belongs in the document even if it appears only briefly — a
     newly introduced character has few facts precisely BECAUSE it is new, not
     because it is unimportant.
   * BACKGROUND ENTITIES — established material last seen in earlier chapters,
     included for continuity. Where background contradicts recent, RECENT WINS:
     background describes a past moment, not the present.
2. OPEN THREADS & MYSTERIES — recurring unresolved thread facts in chapter
   order. Cluster related ones and surface them as the document's open
   questions / mysteries section.
3. NARRATIVE ACCOUNTS (if present) — approved, human-reviewed plain-prose
   accounts of what happened. Prefer these for attribution and event order.
4. PLAYER CHARACTER BACKSTORIES — campaign background to enrich party profiles,
   not to invent events.
"""

# --narratives grounding (issue #202): the whole point of a narrative pass is
# that it states attribution the atomic facts fragment away (issue #195,
# Moziqodo). It is still LLM output, though a human-reviewed one — so it gets
# a stronger claim on attribution/order than the raw fact fragments, not an
# unconditional one; a verbatim quote still wins a direct contradiction.
NARRATIVE_GROUNDING = """\
# NARRATIVE ACCOUNTS (approved, chronological)

The following are per-scene plain-prose accounts of what happened, produced
by a narration pass and reviewed/approved by the GM before being included
here (unapproved narratives are never included). Each states, in order, who
did what, who was present, and — critically — who died and by whose action.
Prefer these over the atomic fact extracts above when the two disagree about
attribution or event order: atomic facts are extracted independently per
sentence and can lose the sentence structure that carried who-did-what-to-
whom, which these accounts were written specifically to preserve. A
narrative account is still LLM output, though a reviewed one — if it
contradicts a fact's verbatim source_quote, prefer the quote.
"""


def load_aliases(path: Path | None) -> dict[str, str]:
    """Load aliases.json -> flat {variant: canonical} (canonicals self-map)."""
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    flat: dict[str, str] = {}
    for canonical, variants in data.items():
        flat[canonical] = canonical
        for v in variants:
            flat[v] = canonical
    return flat


_NFACTS_RE = re.compile(r"^n_facts:\s*(\d+)", re.M)
_CHAPTERS_RE = re.compile(r"^chapters:\s*(\d+)\s*-\s*(\d+)", re.M)


class Dossier(NamedTuple):
    """One per-entity dossier, plus the two frontmatter fields that decide its fate.

    ``last_chapter`` is the ``hi`` of ``facts_to_state.py``'s ``chapters: lo-hi``
    line — the chapter this entity was most recently touched in. 0 when the line
    is missing or unparseable.
    """

    stem: str
    text: str
    n_facts: int
    last_chapter: int


def read_dossiers(paths: list[Path]) -> tuple[list[Dossier], int]:
    """Parse per-entity dossier .md files (facts_to_state.py output).

    Returns ``(dossiers, n_missing_chapters)`` — the second value is how many
    files carried no parseable ``chapters:`` line, so the caller can say so out
    loud instead of silently treating them as chapter 0.
    """
    out: list[Dossier] = []
    n_missing = 0
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _NFACTS_RE.search(text)
        n = int(m.group(1)) if m else 0
        c = _CHAPTERS_RE.search(text)
        if c is None:
            n_missing += 1
        last = int(c.group(2)) if c else 0
        out.append(Dossier(p.stem, text, n, last))
    return out, n_missing


def split_dossiers(
    dossiers: list[Dossier], background_min_facts: int, recent_window: int
) -> tuple[list[Dossier], list[Dossier], int | None]:
    """Split dossiers into ``(recent, background, cutoff)`` by *when*, not how often.

    The significance floor used to apply to every dossier, which made it delete
    the present: an entity introduced in the newest chapter necessarily has the
    fewest facts, so *any* frequency floor preferentially discards exactly the
    material a "current state" document exists to report (issue #194). Frequency
    of reference is not sequence of events — and the sequence is already in the
    frontmatter, parsed and then thrown away.

    So recency scopes the floor instead of competing with it:

    * **recent** — ``last_chapter >= cutoff``, kept regardless of fact count.
      This is the present; it is not a popularity contest.
    * **background** — everything else, and only if ``n_facts >=
      background_min_facts``. The floor keeps doing its real job, filtering
      one-scene noise out of the deep past.

    ``cutoff = latest - recent_window + 1``, where ``latest`` is the highest
    chapter any dossier declares. ``recent_window == 0`` returns ``cutoff=None``
    and treats everything as recent (no floor) — matching
    ``build_recent_events.py --window 0 = all chapters``, whose docstring frames
    the same trade: a wide window wants a high threshold, a narrow one wants
    ~none.

    Both degenerate cases fail toward keeping too much rather than deleting. If
    no dossier declares a chapter at all, ``latest`` is 0 and everything lands in
    recent: the pipeline must not delete on a signal it could not read.

    Recent sorts newest-touched first (the present leads); background stays
    densest-first, as before.
    """
    latest = max((d.last_chapter for d in dossiers), default=0)
    cutoff = latest - recent_window + 1 if recent_window > 0 else None

    recent = [d for d in dossiers if cutoff is None or d.last_chapter >= cutoff]
    background = [
        d
        for d in dossiers
        if cutoff is not None
        and d.last_chapter < cutoff
        and d.n_facts >= background_min_facts
    ]
    recent.sort(key=lambda d: (-d.last_chapter, -d.n_facts, d.stem))
    background.sort(key=lambda d: (-d.n_facts, d.stem))
    return recent, background, cutoff


def read_narrative(path: Path) -> tuple[dict, str] | None:
    """Parse one narrate_chapter.py narrative.md into (frontmatter, body).

    Returns ``None`` only when the file can't be read at all. A file that
    reads fine but has no/malformed frontmatter still returns
    ``({}, whole_text)`` via ``split_frontmatter`` — the caller's approval
    check (``frontmatter.get("approved") is True``) then treats it the same
    as an explicit ``approved: false``: the gate defaults CLOSED, never open.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return split_frontmatter(text)


def expand_globs(patterns: list[str]) -> list[Path]:
    """Expand and de-dup glob patterns, preserving order.

    Matches within a single pattern are sorted (deterministic); patterns are
    kept in the order given, so ``--preserve-order`` can rely on arg order.
    """
    seen: dict[str, Path] = {}
    for pat in patterns:
        for hit in sorted(globmod.glob(str(Path(pat).expanduser()), recursive=True)):
            p = Path(hit).resolve()
            seen.setdefault(str(p), p)
    return list(seen.values())


def session_label(path: Path) -> str:
    """A human-readable label for a merged.json — prefer its parent dir name."""
    if path.name in ("merged.json", "merged_embed.json", "facts.json",
                     "narrative.md") and path.parent.name:
        return path.parent.name
    return path.stem


_INT_RE = re.compile(r"\d+")


def session_index(path: Path) -> tuple:
    """Chronological sort key from the session label's integers (chapter_03 → 3).

    Labels containing a number sort first, by those numbers in order (so
    chapter_2 < chapter_10, unlike a string sort); numberless labels sort last,
    alphabetically. This ordering is what "current state" depends on, so the
    resolved order is printed for the human to verify — session sequencing is
    a GM decision, not one the model (or a silent sort) should quietly own.
    """
    label = session_label(path)
    nums = [int(n) for n in _INT_RE.findall(label)]
    return (0, nums, label.lower()) if nums else (1, [], label.lower())


def session_dates(facts: list[dict]) -> list[str]:
    """In-world date strings from a session's `date`-type facts, de-duped.

    Generic placeholder subjects ("session date") are dropped; real anchors
    ("4th day of the 2nd Tenday of Taraskh 1493") are kept in first-seen order
    to label the session block with its narrative time.
    """
    out: list[str] = []
    for f in facts:
        if f.get("type") != "date":
            continue
        d = (f.get("subject") or "").strip()
        if not d or d.lower() in {"session date", "date", "unknown"}:
            continue
        if d not in out:
            out.append(d)
    return out


def render_facts(facts: list[dict], aliases: dict[str, str], with_quotes: bool) -> str:
    """Group atomic facts into the extract_*.md profile shape (no LLM).

    Mirrors the ## Type / **Subject** / bulleted-fact layout the Claude
    distill extracts use, so the synthesis prompt sees a familiar structure.
    """
    by_type: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        t = f.get("type", "unknown")
        subject = f.get("subject", "")
        canonical = aliases.get(subject, subject)
        by_type[t][canonical].append(f)

    lines: list[str] = []
    ordered_types = TYPE_ORDER + [t for t in sorted(by_type) if t not in TYPE_ORDER]
    for t in ordered_types:
        if t not in by_type:
            continue
        lines.append(f"## {TYPE_HEADINGS.get(t, t.title())}")
        lines.append("")
        for subject in sorted(by_type[t], key=str.lower):
            lines.append(f"**{subject}**")
            for f in by_type[t][subject]:
                fact_text = f.get("fact", "").strip()
                if not fact_text:
                    continue
                lines.append(f"- {fact_text}")
                quote = (f.get("source_quote") or "").strip()
                if with_quotes and quote:
                    quote = " ".join(quote.split())  # collapse newlines/runs
                    lines.append(f'  > "{quote}"')
            lines.append("")
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Synthesise world_state.md from a corpus of ensemble merged.json "
            "files, using distill.py's synthesis prompt. The local-LLM "
            "ensemble replaces Claude's distill_extractions as the input."
        )
    )
    parser.add_argument("--corpus", nargs="+", metavar="GLOB",
                        help="One or more globs matching merged.json files "
                             "(e.g. 'runs/*/merged.json'). Quote them so the "
                             "shell does not expand them first. Renders ALL facts; "
                             "for large corpora prefer --dossiers + --threads.")
    parser.add_argument("--dossiers", nargs="+", metavar="GLOB",
                        help="Glob(s) for per-entity current-state dossiers from "
                             "facts_to_state.py (the aggregation layer). Included "
                             "verbatim — already compressed + human-reviewable. "
                             "Use instead of --corpus when the raw fact corpus is "
                             "too large for one synthesis call.")
    parser.add_argument("--background-min-facts", type=int, default=0, metavar="N",
                        help="Significance floor for entities OUTSIDE the recency "
                             "window: include a background dossier only if its "
                             "frontmatter n_facts >= N (e.g. 10 -> the recurring "
                             "entities). Entities inside --recent-window are always "
                             "included regardless of fact count. Renamed from "
                             "--dossier-min-facts, which applied to every dossier and "
                             "so deleted newly-introduced entities — the newest "
                             "chapter always has the fewest facts (issue #194).")
    parser.add_argument("--recent-window", type=int, default=0, metavar="N",
                        help="Treat the last N chapters as the current window: every "
                             "entity touched in them is included whatever its fact "
                             "count, because recency is what 'current state' means. "
                             "0 = every chapter counts as recent, so no floor applies "
                             "(same sense as build_recent_events.py --window 0).")
    parser.add_argument("--threads", metavar="FILE", default=None,
                        help="Pre-rendered threads/mysteries markdown (from "
                             "facts_to_state.py --types thread --render-only). The "
                             "cross-cutting material that doesn't aggregate per-entity.")
    parser.add_argument("--narratives", nargs="+", metavar="GLOB",
                        help="Glob(s) matching narrate_chapter.py narrative.md files "
                             "(issue #202). Only files whose frontmatter says "
                             "'approved: true' are included as grounding; unapproved "
                             "narratives are SKIPPED and reported by name (never "
                             "silently) — narrative.md is still LLM output and needs "
                             "the human checkpoint before it can ground synthesis. "
                             "Approved narratives are preferred over the atomic fact "
                             "extracts for attribution and event order.")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to write world_state markdown. Required and "
                             "never defaulted — point at a scratch file and diff "
                             "before promoting over docs/world_state.md.")
    parser.add_argument("--party", default=None, metavar="FILE",
                        help="party.yaml — PC roster; anchors the party section.")
    parser.add_argument("--inventory", default=None, metavar="FILE",
                        help="Module proper-noun inventory (markdown). "
                             "Authoritative spellings/identities.")
    parser.add_argument("--backstories", default=None, nargs="+", action="extend", metavar="GLOB",
                        help="Glob(s) for per-PC backstory docs "
                             "(e.g. 'docs/*_backstory.md').")
    parser.add_argument("--aliases", default=None, metavar="FILE",
                        help="Optional aliases.json {canonical: [variants]} to "
                             "collapse spelling variants before synthesis. "
                             "Deprecated: prefer --registry.")
    parser.add_argument("--registry", default=None, metavar="PATH",
                        help="Entity registry (docs/entity_registry.yaml) as the "
                             "single source for aliases, superseding --aliases. "
                             "A campaign dir resolves to its docs/entity_registry.yaml; "
                             "omit to auto-discover one from the CWD. Does NOT feed "
                             "--inventory (that is separate module-canon grounding).")
    parser.add_argument("--preserve-order", action="store_true",
                        help="Feed sessions in the order the corpus globs/args "
                             "were given, instead of sorting by the session "
                             "number parsed from each file's label. Use when "
                             "your filenames carry no chronological index.")
    parser.add_argument("--quotes", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Include each fact's source_quote in the synthesis "
                             "input for grounding (default: on). --no-quotes for "
                             "a clean baseline comparison against the extracts.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Model id (default: {DEFAULT_MODEL}). "
                             f"Use claude-opus-4-7 for highest-quality synthesis; "
                             f"an OpenRouter id (e.g. anthropic/claude-sonnet-4) for --backend openrouter.")
    add_backend_args(parser)
    parser.add_argument("--max-tokens", type=int, default=16000,
                        help="max_tokens for the synthesis call (default: 16000).")
    parser.add_argument("--dump-input", default=None, metavar="FILE",
                        help="Also write the rendered user prompt sent to Claude "
                             "(plus FILE.system.md with the system prompt), "
                             "for prompt debugging without spending tokens.")
    parser.add_argument("--dump-only", action="store_true",
                        help="With --dump-input: stop after writing the dump, "
                             "making no API call (e.g. to run the synthesis "
                             "through `claude -p` instead).")
    args = parser.parse_args()

    corpus_paths = expand_globs(args.corpus) if args.corpus else []
    dossier_paths = expand_globs(args.dossiers) if args.dossiers else []
    if not corpus_paths and not dossier_paths:
        print("Error: provide --corpus and/or --dossiers (nothing matched).",
              file=sys.stderr)
        sys.exit(1)

    registry_path, _campaign_dir, explicit_registry = resolve_registry_arg(
        args.registry, bool(args.aliases), parser)
    if registry_path is not None:
        if explicit_registry and args.aliases:
            parser.error("--registry is the single source; do not combine it with --aliases")
        aliases = load_registry(registry_path).alias_to_canonical()
        note = "Entity registry" if explicit_registry else "Auto-discovered entity registry"
        print(f"{note}: {registry_path} (aliases only; --inventory stays separate)",
              file=sys.stderr)
    else:
        if args.aliases:
            warnings.warn("--aliases is deprecated; migrate to --registry "
                          "(docs/entity_registry.yaml).", DeprecationWarning)
        aliases = load_aliases(
            Path(args.aliases).expanduser().resolve() if args.aliases else None
        )
    party_names = load_party_names(
        Path(args.party).expanduser().resolve() if args.party else None
    )
    inventory_path = Path(args.inventory).expanduser().resolve() if args.inventory else None
    inventory_text = (
        inventory_path.read_text(encoding="utf-8").strip()
        if inventory_path and inventory_path.exists() else ""
    )
    backstory_paths = expand_globs(args.backstories) if args.backstories else []

    dossier_mode = bool(dossier_paths)
    blocks: list[str] = [DOSSIER_GROUNDING if dossier_mode else GROUNDING_NOTE]
    sessions: list[tuple] = []
    total_facts = 0
    n_dossiers = 0
    n_narratives_approved = 0
    n_narratives_skipped = 0

    # ── Dossier track: pre-aggregated, current-state-per-entity (no LLM here) ──
    if dossier_paths:
        all_dossiers, n_missing_chapters = read_dossiers(dossier_paths)
        recent, background, cutoff = split_dossiers(
            all_dossiers, args.background_min_facts, args.recent_window)
        if not recent and not background:
            print(f"Error: no dossiers survived "
                  f"--recent-window {args.recent_window} / "
                  f"--background-min-facts {args.background_min_facts}.",
                  file=sys.stderr)
            sys.exit(1)
        n_dossiers = len(recent) + len(background)
        latest = max((d.last_chapter for d in all_dossiers), default=0)

        # What got dropped is a scope decision, so say it out loud — the corpus
        # track below prints its resolved session order for exactly this reason
        # (see session_index). A filter that silently deletes the newest chapter
        # is how #194 shipped a Chapter-61 document stamped Chapter 62.
        dropped = len(all_dossiers) - n_dossiers
        print(f"Entity dossiers: {len(all_dossiers)} read -> {len(recent)} recent, "
              f"{len(background)} background "
              f"(n_facts >= {args.background_min_facts}), {dropped} dropped.")
        if cutoff is None:
            window_note = ("Recent window: all chapters (--recent-window 0), "
                           "so the background floor applies to nothing.")
        else:
            window_note = (f"Recent window: last {args.recent_window} chapter(s) "
                           f"= chapters {cutoff}-{latest} (latest chapter = {latest}).")
        print(window_note)
        if n_missing_chapters:
            print(f"Warning: {n_missing_chapters} dossier(s) carry no parseable "
                  f"'chapters:' line; treated as chapter 0.", file=sys.stderr)
        if recent:
            print("Recent entities (newest first):")
            for d in recent:
                print(f"  ch{d.last_chapter:02d}  {d.stem} "
                      f"({d.n_facts} fact{'' if d.n_facts == 1 else 's'})")

        if recent:
            span = ("all chapters" if cutoff is None
                    else f"chapters {cutoff}-{latest}")
            blocks.append(f"# RECENT ENTITIES ({span} — the current window)")
            for d in recent:
                blocks.append(f"<!-- {d.stem} -->\n\n{d.text.strip()}")
        if background:
            blocks.append(f"# BACKGROUND ENTITIES (last seen before chapter "
                          f"{cutoff}; n_facts >= {args.background_min_facts})")
            for d in background:
                blocks.append(f"<!-- {d.stem} -->\n\n{d.text.strip()}")

    # ── Threads / mysteries track (cross-cutting; does not aggregate per-entity) ──
    if args.threads:
        tpath = Path(args.threads).expanduser().resolve()
        if tpath.exists():
            print(f"Threads track: {tpath.name}")
            blocks.append("# OPEN THREADS & MYSTERIES (recurring, chronological)")
            blocks.append(tpath.read_text(encoding="utf-8").strip())

    # ── Narrative track (issue #202): approved, human-reviewed plain-prose ──
    # accounts of what happened. Unapproved narratives are skipped and named
    # OUT LOUD — narrative.md is still LLM output; silently including an
    # unreviewed one (or silently dropping one without saying so) would both
    # be the same "computed a signal, then ignored it" failure #194/#197/#200
    # already shipped fixes for.
    if args.narratives:
        narrative_paths = expand_globs(args.narratives)
        approved_narratives: list[tuple[Path, dict, str]] = []
        skipped_narratives: list[str] = []
        for npath in narrative_paths:
            parsed = read_narrative(npath)
            if parsed is None:
                skipped_narratives.append(f"{npath.name} (unreadable)")
                continue
            n_fm, n_body = parsed
            if n_fm.get("approved") is True:
                approved_narratives.append((npath, n_fm, n_body))
            else:
                skipped_narratives.append(session_label(npath))
        approved_narratives.sort(key=lambda t: session_index(t[0]))
        n_narratives_approved = len(approved_narratives)
        n_narratives_skipped = len(skipped_narratives)

        print(f"Narrative accounts: {len(narrative_paths)} found -> "
              f"{len(approved_narratives)} approved, "
              f"{len(skipped_narratives)} skipped (unapproved).")
        if skipped_narratives:
            print(f"  Skipped (unapproved): {', '.join(skipped_narratives)}")
        if approved_narratives:
            print("  Approved (chronological):")
            for npath, n_fm, _n_body in approved_narratives:
                print(f"    {n_fm.get('chapter') or session_label(npath)}")
            blocks.append(NARRATIVE_GROUNDING)
            for npath, n_fm, n_body in approved_narratives:
                n_label = n_fm.get("chapter") or session_label(npath)
                blocks.append(f"<!-- {n_label} -->\n\n{n_body.strip()}")

    # ── Corpus track: raw facts rendered per session (the original path) ──
    if corpus_paths:
        for path in corpus_paths:
            try:
                facts = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"Warning: skipping {path}: {exc}", file=sys.stderr)
                continue
            sessions.append((path, facts))
        if not args.preserve_order:
            sessions.sort(key=lambda pf: session_index(pf[0]))
        # Ordering is a precision decision — show it so the human can veto a
        # mis-sort before it silently becomes "current state".
        print("Session order (earliest → latest; the LAST session is current):")
        for i, (path, facts) in enumerate(sessions, 1):
            ds = session_dates(facts)
            print(f"  {i}. {session_label(path)}"
                  + (f"  [{'; '.join(ds)}]" if ds else "  [no in-world date]"))
        blocks.append("# SESSION FACT EXTRACTS (chronological)")
        for i, (path, facts) in enumerate(sessions, 1):
            total_facts += len(facts)
            ds = session_dates(facts)
            date_note = f" | in-world date: {'; '.join(ds)}" if ds else ""
            rendered = render_facts(facts, aliases, args.quotes)
            blocks.append(
                f"<!-- Session {i}: {session_label(path)}{date_note} -->\n\n{rendered}"
            )
    print("=" * 60)

    if backstory_paths:
        blocks.append("# PLAYER CHARACTER BACKSTORIES")
        for path in backstory_paths:
            body = path.read_text(encoding="utf-8").strip()
            blocks.append(f"<!-- Backstory: {path.stem} -->\n\n{body}")

    user_prompt = "\n\n---\n\n".join(blocks)

    # ── Grounding goes into the system prompt as authoritative context ──
    system_prompt = SYNTHESIZE_SYSTEM
    if party_names:
        roster = "\n".join(f"- {n}" for n in party_names)
        system_prompt += "\n\n" + ROSTER_PREAMBLE + roster
    if inventory_text:
        system_prompt += "\n\n" + INVENTORY_PREAMBLE + inventory_text

    if args.dump_input:
        dump_path = Path(args.dump_input).expanduser().resolve()
        dump_path.write_text(user_prompt, encoding="utf-8")
        # System prompt alongside, so external runners (`claude -p
        # --system-prompt ...`) can reproduce the exact call.
        system_path = dump_path.with_suffix(dump_path.suffix + ".system.md")
        system_path.write_text(system_prompt, encoding="utf-8")
        print(f"Dumped synthesis input: {dump_path}")
        print(f"Dumped system prompt:   {system_path}")
        if args.dump_only:
            print("[--dump-only: stopping before the API call]")
            return

    inv_note = f" | inventory: {inventory_path.name}" if inventory_text else ""
    pc_note = f" | party: {len(party_names)} PCs" if party_names else ""
    bs_note = f" | backstories: {len(backstory_paths)}" if backstory_paths else ""
    srcs = []
    if n_dossiers:
        srcs.append(f"{n_dossiers} dossiers")
    if sessions:
        srcs.append(f"{len(sessions)} sessions/{total_facts} facts")
    if args.threads:
        srcs.append("threads")
    if args.narratives:
        srcs.append(f"{n_narratives_approved} narratives "
                    f"({n_narratives_skipped} skipped unapproved)")
    print(f"[Synthesise world_state | {', '.join(srcs) or 'no source'} | "
          f"quotes: {'on' if args.quotes else 'off'} | "
          f"model: {args.model}{pc_note}{inv_note}{bs_note}]")
    print(f"[Input: {len(user_prompt):,} chars]")
    print("=" * 60)

    client = client_from_args(args)
    if args.batch:
        try:
            world_state = run_single_batch(
                client, system=system_prompt, user=user_prompt,
                model=args.model, max_tokens=args.max_tokens,
            )
        except RuntimeError as e:
            print(f"Error: batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        world_state = stream_api(
            client,
            system_prompt,
            user_prompt,
            args.model,
            max_tokens=args.max_tokens,
        )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(world_state.strip() + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Wrote world_state: {output_path}")
    narr_note = (f" + {n_narratives_approved} narrative(s)"
                if args.narratives else "")
    print(f"Synthesised from {n_dossiers} dossier(s) + {len(sessions)} "
          f"session(s){narr_note}.")
    if party_names:
        print(f"Party anchored: {', '.join(party_names)}")


if __name__ == "__main__":
    main()
