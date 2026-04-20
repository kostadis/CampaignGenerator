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

  # Skip extraction if already done
  python party.py \\
      --character soma.md vukradin.md \\
      --synthesize-only \\
      --extract-dir docs/party_extractions \\
      --output docs/party.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, run_extract_pipeline, run_synthesize_pipeline

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

You will receive:
- Character sheets (definitive source for stats, abilities, and current arc score values)
- Arc score mechanic documents (full definition of each score: triggers, thresholds, unlocked abilities)
- Extracted session notes (arc score events, decisions, relationships from play)
- Backstory documents (optional origin context)

Produce a single authoritative party.md with these sections:

## Party Overview
Current location, active quests, collective resources, and group reputation.

## Characters
One subsection per PC with:
- Name, class, level, player
- Key personality traits and motivations (2-3 sentences)
- Current arc score tracks: name, current value, what triggers changes
- Notable relationships (allies, enemies, obligations)
- Items of significance

## Arc Score Summary
A compact table of all arc scores across all characters for quick reference, including
current value, next threshold, and what ability unlocks at that threshold.

## Party Dynamics
How the characters relate to each other, current tensions, shared goals.

Rules:
- Character sheets take precedence over session notes for stats and arc score values.
- Session notes take precedence for current emotional state and recent decisions.
- Be concise. This document is read quickly during session prep.
- Do not invent anything not present in the source material.
- Output only the party document. No preamble or commentary.
"""




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a party.md from character sheets, session summaries, and backstories."
    )
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
    if not args.character and not args.summaries and not args.synthesize_only:
        print("Error: provide at least --character or --summaries", file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir and not args.character:
        print("Error: --synthesize-only requires --extract-dir or --character", file=sys.stderr)
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
