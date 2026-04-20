#!/usr/bin/env python3
"""Generate a party.md document from character sheets, session summaries, and backstories.

Combines three sources:
  - Character sheets (.md files, one per character) — definitive stats and abilities
  - Session summaries (large file) — arc score progression, relationships, decisions
  - Backstory documents (optional, one per character) — origin context

Runs in two passes for the session summaries (same as distill.py):
  1. Extract — chunks the summaries, pulls party-relevant info from each chunk
  2. Synthesize — combines character sheets + extractions + backstories into party.md

Usage:
  python party.py \\
      --character soma.md --character vukradin.md --character valphine.md \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --output docs/party.md

  python party.py \\
      --character soma.md \\
      --summaries summaries.md \\
      --backstory soma_backstory.md \\
      --output docs/party.md

  # Preferred: per-character config so the synthesizer can't confuse which
  # arc score belongs to which PC, and characters without a formal track
  # are first-class citizens (see config/party.example.yaml).
  python party.py \\
      --party-config config/party.yaml \\
      --summaries summaries.md \\
      --output docs/party.md

  # Skip extraction if already done
  python party.py \\
      --character soma.md vukradin.md \\
      --synthesize-only \\
      --extract-dir docs/party_extractions \\
      --output docs/party.md
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib import make_client, run_extract_pipeline, run_synthesize_pipeline, stream_api


@dataclass
class PartyCharacter:
    name: str
    sheet: Path
    backstory: Path | None = None
    arc_score: Path | None = None
    trackless: bool = False  # True when arc_score is explicitly null in config


@dataclass
class PartyConfig:
    characters: list[PartyCharacter] = field(default_factory=list)


def load_party_config(path: Path) -> PartyConfig:
    """Read a party config YAML file, validate every referenced file, and
    return a PartyConfig.

    The YAML shape is:

        characters:
          - name: Brewbarry
            sheet: docs/party/brewbarry.md
            backstory: docs/Backstory - Brewbarry.md   # optional
            arc_score: docs/tracking/brewbarry-score.md # optional
          - name: Vukradin
            sheet: docs/party/Vukradin.md
            arc_score: null   # intentionally trackless — first-class state

    Distinction: `arc_score: null` (trackless by design) vs the key being
    absent (unspecified — treated the same as omitted for now, but the
    config author can audit it later).

    Paths resolve against the config file's parent directory. Every
    referenced file must exist — raises SystemExit on a missing file.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML in {path}: {e}", file=sys.stderr)
        sys.exit(1)

    base = path.parent
    chars_raw = raw.get("characters") or []
    if not isinstance(chars_raw, list) or not chars_raw:
        print(f"Error: {path} must define a non-empty 'characters' list", file=sys.stderr)
        sys.exit(1)

    def _resolve(rel: str, field_name: str, char_name: str) -> Path:
        p = (base / rel).expanduser().resolve()
        if not p.exists():
            print(f"Error: party config references missing file for {char_name}.{field_name}: {p}",
                  file=sys.stderr)
            sys.exit(1)
        return p

    characters: list[PartyCharacter] = []
    for entry in chars_raw:
        if not isinstance(entry, dict):
            print(f"Error: each character entry in {path} must be a mapping", file=sys.stderr)
            sys.exit(1)
        name = entry.get("name")
        sheet_rel = entry.get("sheet")
        if not name or not sheet_rel:
            print(f"Error: character entry in {path} missing 'name' or 'sheet': {entry}",
                  file=sys.stderr)
            sys.exit(1)
        sheet = _resolve(sheet_rel, "sheet", name)
        backstory = _resolve(entry["backstory"], "backstory", name) if entry.get("backstory") else None

        # arc_score distinguishes three cases:
        #   key absent → arc_score=None, trackless=False
        #   key present, value null → arc_score=None, trackless=True
        #   key present, value path → arc_score=Path, trackless=False
        if "arc_score" in entry:
            if entry["arc_score"] is None:
                arc_score = None
                trackless = True
            else:
                arc_score = _resolve(entry["arc_score"], "arc_score", name)
                trackless = False
        else:
            arc_score = None
            trackless = False

        characters.append(PartyCharacter(
            name=str(name), sheet=sheet, backstory=backstory,
            arc_score=arc_score, trackless=trackless,
        ))

    return PartyConfig(characters=characters)


def _render_party_block(party_config: PartyConfig) -> str:
    """Render the PARTY source group as `# PARTY` with one `## {name}`
    subsection per PC, nesting sheet / backstory / arc_score files with
    source-comment labels.

    Trackless characters get an explicit marker so the LLM doesn't
    invent an arc track or suggest creating one.
    """
    char_blocks: list[str] = []
    for pc in party_config.characters:
        parts = [f"## {pc.name}"]
        parts.append(f"<!-- Character sheet: {pc.sheet.name} -->\n\n{pc.sheet.read_text(encoding='utf-8').strip()}")
        if pc.backstory is not None:
            parts.append(f"<!-- Backstory: {pc.backstory.name} -->\n\n{pc.backstory.read_text(encoding='utf-8').strip()}")
        if pc.arc_score is not None:
            parts.append(f"<!-- Arc score mechanic: {pc.arc_score.name} -->\n\n{pc.arc_score.read_text(encoding='utf-8').strip()}")
        elif pc.trackless:
            parts.append(
                "<!-- Arc score: INTENTIONALLY TRACKLESS -->\n\n"
                f"{pc.name} has no formal arc score mechanic. This is a deliberate design "
                "choice — do not invent an arc score for this character and do not suggest "
                "creating one."
            )
        char_blocks.append("\n\n".join(parts))
    return "# PARTY\n\n" + "\n\n---\n\n".join(char_blocks)


def _render_source_group(heading: str, files: list[Path], label: str) -> str:
    """Match run_synthesize_pipeline's rendering so the party-config path
    produces an equivalent user prompt for non-party groups."""
    if not files:
        return ""
    blocks = [
        f"<!-- {label}: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in files
    ]
    body = "\n\n---\n\n".join(blocks)
    return f"# {heading}\n\n{body}" if heading else body

EXTRACT_SYSTEM = """\
You are extracting party-relevant information from D&D session summary notes.

Focus ONLY on information about the player characters. Extract:

## Character Progression
For each PC: level changes, new abilities learned, items gained or lost.

## Arc Score Events
Specific moments that triggered arc score changes for each character. \
Include the character name, what happened, and whether it was positive or negative.

## Relationships & Decisions
Key decisions each PC made, relationships formed or damaged, oaths taken, \
debts incurred, enemies made.

## Party State Updates
Changes to the party's collective situation: location, resources, reputation, \
active obligations.

Rules:
- Only include information about player characters, not NPCs.
- Be specific: name the character and the session event.
- Ignore combat mechanics and spell details unless they reveal character development.
- Output only the structured notes under the headings above.
- If a section has nothing relevant, omit it entirely.
"""

SYNTHESIZE_SYSTEM = """\
You are creating a party reference document for a D&D campaign GM.

You may receive two input shapes:

**A. Per-character PARTY block** (preferred, when a party config is supplied):
A `# PARTY` section with one `## {Name}` subsection per player character.
Each subsection nests that character's own sheet, backstory (optional),
and arc score mechanic (optional). A character marked
`<!-- Arc score: INTENTIONALLY TRACKLESS -->` has no formal arc score
mechanic by design — do not invent one and do not suggest creating one.

**B. Flat groups** (legacy CLI flags):
Separate `# CHARACTER SHEETS`, `# BACKSTORY DOCUMENTS`, and
`# ARC SCORE MECHANICS` groups with no explicit PC mapping. Infer
which files belong to which character by name match.

In both shapes you will also receive:
- `# SESSION EXTRACTIONS` — arc score events, decisions, relationships from play
- `# ADDITIONAL CONTEXT` — campaign state, etc. (optional)

Produce a single authoritative party.md with these sections:

## Party Overview
Current location, active quests, collective resources, and group reputation.

## Characters
One subsection per PC with:
- Name, class, level, player
- Key personality traits and motivations (2-3 sentences)
- Current arc score tracks: name, current value, what triggers changes.
  If the PC is intentionally trackless, state that plainly ("no formal arc
  score mechanic — tracked narratively") and move on. Do not fabricate a
  track or flag the absence as an issue.
- Notable relationships (allies, enemies, obligations)
- Items of significance

## Arc Score Summary
A compact table of arc scores for the characters who have formal tracks,
showing current value, next threshold, and what unlocks at that threshold.
Omit trackless characters from this table entirely — do not list them with
"N/A" rows.

## Party Dynamics
How the characters relate to each other, current tensions, shared goals.

Rules:
- Character sheets take precedence over session notes for stats and arc score values.
- Session notes take precedence for current emotional state and recent decisions.
- A character marked intentionally trackless has no arc score — full stop.
  Do not invent one. Do not suggest adopting the arc system of another PC.
- Be concise. This document is read quickly during session prep.
- Do not invent anything not present in the source material.
- Output only the party document. No preamble or commentary.
"""




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a party.md from character sheets, session summaries, and backstories."
    )
    parser.add_argument("--party-config", metavar="FILE", default=None,
                        help="Party config YAML mapping each PC to sheet/backstory/arc_score. "
                             "When set, --character/--backstory/--arc-scores are rejected.")
    parser.add_argument("--character", "-c", nargs="+", metavar="FILE", default=[],
                        help="Character sheet file(s)")
    parser.add_argument("--summaries", "-s", metavar="FILE",
                        help="Session summaries file (large, will be chunked)")
    parser.add_argument("--backstory", "-b", nargs="+", metavar="FILE", default=[],
                        help="Backstory document(s) (optional)")
    parser.add_argument("--arc-scores", "-a", nargs="+", metavar="FILE", default=[],
                        help="Arc score mechanic document(s), one per character (optional)")
    parser.add_argument("--context", nargs="+", metavar="FILE", default=[],
                        help="Additional context files (e.g. campaign_state.md)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the party document")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX", default=None,
                        help="Split summaries at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Session'). Each session becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load session extractions "
                             "(default: <output_dir>/party_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir")
    parser.add_argument("--extract-only", action="store_true",
                        help="Run the extract pass only, then stop so you can review "
                             "extractions before synthesis. Re-run with --synthesize-only "
                             "against the same --extract-dir to produce the final document.")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.synthesize_only and args.extract_only:
        print("Error: --synthesize-only and --extract-only are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
    if args.party_config and (args.character or args.backstory or args.arc_scores):
        print("Error: --party-config is mutually exclusive with "
              "--character / --backstory / --arc-scores (use one or the other)",
              file=sys.stderr)
        sys.exit(1)
    if not args.party_config and not args.character and not args.summaries and not args.synthesize_only:
        print("Error: provide at least --party-config, --character, or --summaries",
              file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir and not args.character and not args.party_config:
        print("Error: --synthesize-only requires --extract-dir, --character, or --party-config",
              file=sys.stderr)
        sys.exit(1)
    if args.extract_only and not args.summaries:
        print("Error: --extract-only requires --summaries (no summaries = nothing to extract)",
              file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "party_extractions"
    )

    party_config: PartyConfig | None = None
    if args.party_config:
        party_config = load_party_config(Path(args.party_config).expanduser().resolve())

    character_files = [Path(f).expanduser().resolve() for f in args.character]
    backstory_files = [Path(f).expanduser().resolve() for f in args.backstory]
    arc_score_files = [Path(f).expanduser().resolve() for f in args.arc_scores]
    context_files = [Path(f).expanduser().resolve() for f in args.context]

    for f in character_files + backstory_files + arc_score_files + context_files:
        if not f.exists():
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    client = make_client()

    # ── Extract pass ──────────────────────────────────────────────────────────
    if args.summaries and not args.synthesize_only:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        print(f"\n[Pass 1: Extract party info | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract_pipeline(
            client, summaries_text,
            extract_system=EXTRACT_SYSTEM,
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="session",
        )
        print(f"Extractions saved to: {extract_dir}")

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, re-run with --synthesize-only --extract-dir {extract_dir} "
                  f"plus the same --character/--backstory/--arc-scores/--context args.")
            return
    elif args.synthesize_only:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only | {len(extract_files)} extraction(s) from {extract_dir}]")
    else:
        extract_files = []

    # ── Synthesize pass ───────────────────────────────────────────────────────
    sources = []
    if party_config:
        trackless = [pc.name for pc in party_config.characters if pc.trackless]
        with_arc = [pc.name for pc in party_config.characters if pc.arc_score]
        sources.append(f"{len(party_config.characters)} PC(s) from party config "
                       f"({len(with_arc)} with arc, {len(trackless)} trackless)")
    if character_files:
        sources.append(f"{len(character_files)} character sheet(s)")
    if extract_files:
        sources.append(f"{len(extract_files)} session extraction(s)")
    if backstory_files:
        sources.append(f"{len(backstory_files)} backstory doc(s)")
    if arc_score_files:
        sources.append(f"{len(arc_score_files)} arc score doc(s)")
    if context_files:
        sources.append(f"{len(context_files)} context file(s)")

    print(f"\n[Pass 2: Synthesize | {', '.join(sources)} | model: {args.model}]")
    print("=" * 60)
    if party_config:
        party_block = _render_party_block(party_config)
        extracts_block = _render_source_group("SESSION EXTRACTIONS", extract_files, "Session extract")
        context_block = _render_source_group("ADDITIONAL CONTEXT", context_files, "Context")
        parts = [p for p in (party_block, extracts_block, context_block) if p]
        if not parts:
            print("Error: no source material to synthesize.", file=sys.stderr)
            sys.exit(1)
        user_prompt = "\n\n===\n\n".join(parts)
        print(f"  Synthesizing per-character party block ({len(user_prompt):,} chars)...")
        print("  " + "─" * 56)
        party_doc = stream_api(client, SYNTHESIZE_SYSTEM, user_prompt, args.model)
        print("  " + "─" * 56)
    else:
        party_doc = run_synthesize_pipeline(
            client,
            source_groups=[
                ("CHARACTER SHEETS", character_files, "Character sheet"),
                ("SESSION EXTRACTIONS", extract_files, "Session extract"),
                ("BACKSTORY DOCUMENTS", backstory_files, "Backstory"),
                ("ARC SCORE MECHANICS", arc_score_files, "Arc score mechanic"),
                ("ADDITIONAL CONTEXT", context_files, "Context"),
            ],
            synthesize_system=SYNTHESIZE_SYSTEM,
            model=args.model,
        )
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(party_doc.strip() + "\n", encoding="utf-8")
    print(f"\nParty document saved to: {output}")
    if extract_files:
        print(f"Extractions kept in: {extract_dir}")
        print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
