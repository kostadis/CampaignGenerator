#!/usr/bin/env python3
"""Convert session summaries into a structured world_state lore document.

Runs in two passes:
  1. Extract — splits the input into chunks, asks Claude to pull canon facts,
     NPC states, faction states, and key events from each chunk.
  2. Synthesize — feeds all extracted notes into a final call that produces
     a coherent world_state.md.

Intermediate extractions are saved so you can re-run --synthesize-only if
the final pass fails without repeating the expensive extract pass.

Use --extract-only to stop after the extract pass so you can review and edit
the intermediate files before synthesis (recommended for large corpora).

Usage:
  python distill.py summaries.md --output world_state.md
  python distill.py summaries.md --output world_state.md --chunk-size 50000
  python distill.py summaries.md --output world_state.md --extract-only
  python distill.py --synthesize-only --extract-dir extractions/ --output world_state.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    build_alias_normalizer,
    format_npc_roster,
    load_alias_map,
    make_client,
    run_extract_pipeline,
    run_synthesize_pipeline,
)

EXTRACT_SYSTEM = """\
You are a lore archivist for a D&D campaign. You will be given a portion of \
session summary notes. Your job is to extract every piece of canon information \
into structured notes under these headings:

## NPCs
For each named NPC: current location, current state, recent actions, faction, \
and any revealed motivations or secrets.

## Factions
For each faction or organisation: current goals, recent actions, relationships \
to other factions, and key members.

## World Events
Significant events that occurred, in rough chronological order. One bullet per event. \
Be specific and concrete.

## Locations
Named locations that appeared: what they are, what happened there, current state.

## Threads & Mysteries
Unresolved plot threads, open questions, and foreshadowed events.

Rules:
- Be exhaustive. Include every named person, place, and faction you encounter.
- Do not invent anything not present in the text.
- Do not summarise the narrative. Extract facts only.
- Use the headings above exactly. Output only the structured notes.
"""

SYNTHESIZE_SYSTEM = """\
You are a lore archivist for a D&D campaign. You will be given a set of \
structured extraction notes compiled from multiple session summaries. Your job \
is to synthesise them into a single authoritative world_state document that \
will serve as the living canon reference for future session prep.

The document should:
- Merge duplicate entries and resolve any contradictions (later events take precedence)
- Be organised into clear sections that a GM can scan quickly during prep
- Capture the *current* state of the world (not a chronological history)
- Include a brief Canon Events timeline at the end for chronological reference

Use whatever section structure best fits the material. Write clearly and concisely. \
This document will be read by an AI assistant, so precision matters more than prose.

Output only the world_state document. No preamble or commentary.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Distill session summaries into a world_state lore document."
    )
    parser.add_argument("input", nargs="?",
                        help="Session summaries file (not needed with --synthesize-only)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the final world_state document")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX",
                        help="Split input at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Chapter'). Each chapter becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load intermediate extractions "
                             "(default: <output_dir>/distill_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction and synthesize from existing files in --extract-dir")
    parser.add_argument("--extract-only", action="store_true",
                        help="Run the extract pass only, then stop so you can review "
                             "extractions before synthesis. Re-run with --synthesize-only "
                             "against the same --extract-dir to produce the final document.")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Directory of per-NPC dossier files (built by "
                             "planning.py --build-dossiers). If given, every "
                             "alias in dossier frontmatter is rewritten to its "
                             "canonical name before extract/synth, and a "
                             "'Known NPCs' roster seeds the system prompts.")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.synthesize_only and args.extract_only:
        print("Error: --synthesize-only and --extract-only are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir:
        print("Error: --synthesize-only requires --extract-dir", file=sys.stderr)
        sys.exit(1)
    if not args.synthesize_only and not args.input:
        print("Error: input file required unless --synthesize-only", file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "distill_extractions"
    )

    alias_map = load_alias_map(args.dossier_dir)
    normalize, _ = build_alias_normalizer(alias_map)
    roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    client = make_client()

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        if not text.strip():
            print(f"Error: input file is empty: {args.input}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Pass 1: Extract | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract_pipeline(
            client, text,
            extract_system=EXTRACT_SYSTEM,
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="chapter",
            input_normalizer=normalize,
            system_suffix=roster,
        )
        if not extract_files:
            print("Error: no chunks were extracted — input may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, run:")
            print(f"  python distill.py --synthesize-only "
                  f"--extract-dir {extract_dir} --output {Path(args.output)}")
            return
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only mode | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize | model: {args.model}]")
    print("=" * 60)
    world_state = run_synthesize_pipeline(
        client,
        source_groups=[("", extract_files)],
        synthesize_system=SYNTHESIZE_SYSTEM,
        model=args.model,
        input_normalizer=normalize,
        system_suffix=roster,
    )
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(world_state.strip() + "\n", encoding="utf-8")
    print(f"\nWorld state saved to: {output}")
    print(f"Intermediate extractions kept in: {extract_dir}")
    print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
