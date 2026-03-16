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
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, stream_api

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


def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks at paragraph boundaries near chunk_size chars."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        boundary = text.rfind("\n\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = text.rfind("\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return [c.strip() for c in chunks if c.strip()]


def run_extract(client, text: str, chunk_size: int, model: str, extract_dir: Path) -> list[Path]:
    chunks = chunk_text(text, chunk_size)
    total = len(chunks)
    print(f"  {total} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")

    extract_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"extract_{i:03d}.md"
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting chunk ({len(chunk):,} chars)...")
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
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load intermediate extractions "
                             "(default: <output_dir>/distill_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction and synthesize from existing files in --extract-dir")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

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

    client = make_client()

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        print(f"\n[Pass 1: Extract | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract(client, text, args.chunk_size, args.model, extract_dir)
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
