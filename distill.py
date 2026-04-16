#!/usr/bin/env python3
"""Convert session summaries into a structured world_state lore document.

Runs in two passes:
  1. Extract — splits the input into chunks, asks Claude to pull canon facts,
     NPC states, faction states, and key events from each chunk.
  2. Synthesize — feeds all extracted notes into a final call that produces
     a coherent world_state.md.

Intermediate extractions are saved so you can re-run --synthesize-only if
the final pass fails without repeating the expensive extract pass.

Usage:
  python distill.py summaries.md --output world_state.md
  python distill.py summaries.md --output world_state.md --chunk-size 50000
  python distill.py --synthesize-only extractions/ --output world_state.md

  # Consume the shared per-chapter extracts produced by chapter_extract.py
  # (skips the extract pass entirely; uses a schema-aware synthesize prompt)
  python distill.py --chapter-extracts chapter_extracts/ --output world_state.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import prepare_chunks, make_client, stream_api

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

SYNTHESIZE_FROM_CHAPTERS_SYSTEM = """\
You are a lore archivist for a D&D campaign. You will be given a set of \
per-chapter structured extraction notes, each covering one chapter of the \
campaign's session summaries. Each extract uses this shared schema:

  ## NPCs                (named NPCs: identity, faction, actions, state changes, last location)
  ## Factions            (visible actions, alliances, resources, members)
  ## Party               (PC actions, decisions, acquisitions, arc beats)
  ## Quests & Threads    (one bullet per thread with explicit OPENED / PROGRESSED / RESOLVED)
  ## Locations           (named places and their current state)
  ## Events              (significant events, chronological)
  ## Arc Score Events    (moments that trigger tracked threat arcs)
  ## Revealed Information (secrets, plans, intel the party uncovered)
  ## Tracked Items       (optional; only present when a tracking list was used)

Your output is a living **world_state** canon document. Focus on these sections \
when building it:

- ## NPCs → unified NPC entries with current state and known motivations
- ## Factions → goals, alliances, recent actions, key members
- ## Locations → what each place is and its current state
- ## Events → a concise Canon Events timeline in chronological order
- ## Quests & Threads → Threads & Mysteries (treat OPENED/PROGRESSED as open; list
  RESOLVED threads only when their lasting consequence matters for canon)
- ## Revealed Information → fold secrets/intel into the relevant NPC or faction entries

The ## Party and ## Arc Score Events sections contain context you can reference \
(who did what, which arcs moved) but they are not the focus of this document — \
a companion document (campaign_state) covers party acquisitions and arc mechanics.

The document should:
- Merge duplicate entries across chapters; later chapters override earlier ones on conflicts
- Be organised into clear sections a GM can scan quickly during prep
- Capture the *current* state of the world, not a blow-by-blow history
- End with a brief Canon Events timeline for chronological reference

Use whatever section structure best fits the material. Write clearly and concisely. \
Do not invent anything not present in the source extracts.

Output only the world_state document. No preamble or commentary.
"""



def run_extract(client, text: str, chunk_size: int, model: str, extract_dir: Path,
                split_chapters: str | None = None) -> list[Path]:
    chunks, label = prepare_chunks(text, chunk_size, split_chapters, split_label="chapter")
    total = len(chunks)

    extract_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"extract_{i:03d}.md"
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting {label} ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, EXTRACT_SYSTEM, chunk, model)
        print("  " + "─" * 56)

        out_file.write_text(result, encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize(client, extract_files: list[Path], model: str) -> str:
    combined = [
        f"<!-- Source: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in sorted(extract_files)
    ]
    user_prompt = "\n\n---\n\n".join(combined)
    print(f"  Synthesizing {len(extract_files)} extraction(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, SYNTHESIZE_SYSTEM, user_prompt, model)
    print("  " + "─" * 56)
    return result


def run_synthesize_from_chapters(client, chapter_files: list[Path], model: str) -> str:
    combined = [
        f"<!-- Chapter extract: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in sorted(chapter_files)
    ]
    user_prompt = "\n\n---\n\n".join(combined)
    print(f"  Synthesizing {len(chapter_files)} chapter extract(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, SYNTHESIZE_FROM_CHAPTERS_SYSTEM, user_prompt, model)
    print("  " + "─" * 56)
    return result


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
    parser.add_argument("--chapter-extracts", metavar="DIR", default=None,
                        help="Synthesize from shared per-chapter extracts produced by "
                             "chapter_extract.py. Skips the extract pass and uses a "
                             "schema-aware synthesize prompt. Additive: existing --extract-dir "
                             "/ --synthesize-only paths are unaffected.")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.synthesize_only and not args.extract_dir:
        print("Error: --synthesize-only requires --extract-dir", file=sys.stderr)
        sys.exit(1)
    if not args.synthesize_only and not args.chapter_extracts and not args.input:
        print("Error: input file required unless --synthesize-only or --chapter-extracts",
              file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "distill_extractions"
    )

    client = make_client()

    if args.chapter_extracts:
        chapter_dir = Path(args.chapter_extracts).expanduser().resolve()
        if not chapter_dir.is_dir():
            print(f"Error: --chapter-extracts directory not found: {chapter_dir}",
                  file=sys.stderr)
            sys.exit(1)
        chapter_files = sorted(chapter_dir.glob("extract_*.md"))
        if not chapter_files:
            print(f"Error: no extract_*.md files found in {chapter_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Chapter-extracts mode | {len(chapter_files)} extract(s) from {chapter_dir}]")
        print(f"\n[Pass 2: Synthesize from chapter extracts | model: {args.model}]")
        print("=" * 60)
        world_state = run_synthesize_from_chapters(client, chapter_files, args.model)
        print("=" * 60)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(world_state.strip() + "\n", encoding="utf-8")
        print(f"\nWorld state saved to: {output}")
        print(f"Source chapter extracts: {chapter_dir}\n")
        return

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        if not text.strip():
            print(f"Error: input file is empty: {args.input}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Pass 1: Extract | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract(client, text, args.chunk_size, args.model, extract_dir,
                                    split_chapters=args.split_chapters)
        if not extract_files:
            print("Error: no chunks were extracted — input may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only mode | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize | model: {args.model}]")
    print("=" * 60)
    world_state = run_synthesize(client, extract_files, args.model)
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(world_state.strip() + "\n", encoding="utf-8")
    print(f"\nWorld state saved to: {output}")
    print(f"Intermediate extractions kept in: {extract_dir}")
    print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
