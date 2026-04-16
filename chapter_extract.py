#!/usr/bin/env python3
"""Unified per-chapter extractor.

Produces a single structured intermediate per chapter that can be consumed by
distill.py, campaign_state.py, and planning.py synthesizers — replacing three
independent scans of the same summaries file with one rich extract.

Usage:
  python chapter_extract.py summaries.md --output-dir chapter_extracts/

  # Chapter-aligned splitting (recommended)
  python chapter_extract.py summaries.md \\
      --output-dir chapter_extracts/ \\
      --split-chapters "## "

  # POC / validation mode — only process specific chunk indices
  python chapter_extract.py summaries.md \\
      --output-dir chapter_extracts/ \\
      --split-chapters "## " \\
      --only 10 15 25

  # With optional tracking list (same format as campaign_state.py)
  python chapter_extract.py summaries.md \\
      --output-dir chapter_extracts/ \\
      --split-chapters "## " \\
      --track-file tracking.txt
"""

import argparse
import sys
from pathlib import Path

from campaignlib import prepare_chunks, make_client, stream_api, DEFAULT_MODEL

EXTRACT_SYSTEM_BASE = """\
You are extracting information from a D&D session summary for downstream use
by multiple planning tools (lore canon, completion/state tracking, and NPC
planning). Work through the following sections IN ORDER, filling each with
specific facts drawn from the text. Omit a section entirely if nothing in
this chunk belongs in it.

## NPCs
For each named NPC (not a player character) who appears or is referenced:
- Identity, faction, role
- Actions they took or words they spoke
- State changes (died, incapacitated, allied, fled, revealed true identity)
- Last known location
- Motivations, secrets, or plans that were revealed

## Factions
For each faction or organization:
- Visible actions or operations
- Alliances formed, shifted, or broken
- Resources gained or lost
- Members mentioned

## Party
Player-character actions and moments:
- Decisions made, positions taken
- Acquisitions (items, titles, intel, reputation, obligations)
- Arc score moments or character-growth beats
- Significant relationship beats (PC-to-PC or PC-to-NPC)

## Quests & Threads
One bullet per thread with explicit status:
- OPENED: what started, who offered it, stakes
- PROGRESSED: what advanced, current state
- RESOLVED: how it ended, outcome, lasting consequence

## Locations
Named locations that appeared:
- What the location is, what happened there this chunk
- Any changes to the location's state or control

## Events
Chronological bullets of significant events — tactical, social,
environmental. Be concrete. Name the participants and the outcome.

## Arc Score Events
Specific moments that would trigger an arc score change for any tracked
threat (e.g. Brundar's Echo, Kraken Society Echoes, Planar Distortion).
Name the arc and describe the trigger precisely.

## Revealed Information
Secrets, plans, intel, or foreshadowing the party uncovered that matter
for future sessions.
{tracked_section}
Rules:
- Use each ## heading exactly as written above, in the order above.
- Player characters go under "Party", never under "NPCs".
- Be specific — name the NPC, faction, location, or event. Avoid generic
  summaries like "the party fought some enemies."
- Do not invent anything. If it isn't in the text, don't include it.
- If a section has no content in this chunk, OMIT the heading entirely.
  Do not write "None" or "N/A".
- Output only the structured notes. No preamble or commentary.
"""

EXTRACT_TRACKED_SECTION = """\

## Tracked Items
The following specific events MUST be addressed if they appear anywhere in
this chunk, even if they would otherwise be omitted. For each, note exactly
what happened and the outcome. If an item does NOT appear in this chunk,
omit it (do not write "not present").
{items}
"""


def build_system(track_file: Path | None) -> str:
    if not track_file:
        return EXTRACT_SYSTEM_BASE.format(tracked_section="")
    items_text = track_file.read_text(encoding="utf-8").strip()
    tracked = EXTRACT_TRACKED_SECTION.format(items=items_text)
    return EXTRACT_SYSTEM_BASE.format(tracked_section=tracked)


def run_extract(
    client,
    text: str,
    chunk_size: int,
    model: str,
    extract_dir: Path,
    system: str,
    split_chapters: str | None = None,
    only: set[int] | None = None,
    max_tokens: int = 8096,
) -> list[Path]:
    chunks, label = prepare_chunks(text, chunk_size, split_chapters, split_label="chapter")
    total = len(chunks)
    extract_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"extract_{i:03d}.md"
        if only is not None and i not in only:
            continue
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting {label} ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, system, chunk, model, max_tokens=max_tokens)
        print("  " + "─" * 56)

        out_file.write_text(result, encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract unified per-chapter intermediates from session summaries."
    )
    parser.add_argument("input", help="Session summaries file")
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write extract_NNN.md files into")
    parser.add_argument("--split-chapters", default=None,
                        help="Heading prefix to split on (e.g. '## '). "
                             "If omitted, uses character-count chunking.")
    parser.add_argument("--chunk-size", type=int, default=60000,
                        help="Character-count chunk size when --split-chapters is not used")
    parser.add_argument("--track-file", default=None,
                        help="Optional tracking list (one item per line, # for comments)")
    parser.add_argument("--only", nargs="+", type=int, default=None,
                        help="Only process chunks at these 1-based indices "
                             "(useful for POC / validation)")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=8096,
                        help="Max output tokens per chunk (default 8096)")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    text = input_path.read_text(encoding="utf-8")

    track_file = Path(args.track_file).expanduser() if args.track_file else None
    if track_file and not track_file.exists():
        print(f"Error: track file not found: {track_file}", file=sys.stderr)
        sys.exit(1)

    system = build_system(track_file)
    client = make_client()
    extract_dir = Path(args.output_dir).expanduser()
    only = set(args.only) if args.only else None

    print(f"Source: {input_path}")
    print(f"Output: {extract_dir}")
    if only:
        print(f"Only running chunks: {sorted(only)}")
    print()

    saved = run_extract(
        client, text, args.chunk_size, args.model,
        extract_dir, system, args.split_chapters, only,
        max_tokens=args.max_tokens,
    )
    print(f"\nDone. {len(saved)} extract file(s) in {extract_dir}")


if __name__ == "__main__":
    main()
