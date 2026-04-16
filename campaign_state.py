#!/usr/bin/env python3
"""Generate a campaign_state.md from session summaries — a grounding document for all planning.

campaign_state.md is the "what's been completed and where things stand now" reference.
Its purpose is to prevent LLM hallucination about current state: it explicitly marks
completed encounters and quests so they aren't re-suggested, tracks current NPC dispositions,
and lists only genuinely active threads.

Distinct from world_state.md (which is lore/history/facts) and planning.md (which is
forward-looking). campaign_state.md answers: "What has the party finished, and what
is actually on the table right now?"

Runs in two passes:
  1. Extract — chunks the summaries, pulls completion events, NPC state changes,
     and thread resolution from each chunk
  2. Synthesize — merges all extractions into a clean campaign_state.md

Usage:
  python campaign_state.py summaries.md --output docs/campaign_state.md

  # With a tracking list to ensure specific events are never missed
  python campaign_state.py summaries.md \\
      --track-file tracking.txt \\
      --output docs/campaign_state.md

  # Re-synthesize without re-extracting (tracking list still applies)
  python campaign_state.py --synthesize-only \\
      --track-file tracking.txt \\
      --extract-dir docs/state_extractions \\
      --output docs/campaign_state.md

  # Synthesize from the shared per-chapter extracts produced by chapter_extract.py
  # (skips the extract pass entirely; uses a schema-aware synthesize prompt)
  python campaign_state.py \\
      --chapter-extracts docs/chapter_extracts \\
      --track-file tracking.txt \\
      --output docs/campaign_state.md

Tracking file format (tracking.txt):
  One item per line. Blank lines and lines starting with # are ignored.
  Items can be short phrases or full sentences describing events to track.

  Example:
    # Locations
    Whispering Woods resolution
    Gnomengarde dungeon

    # NPCs
    Cryovain encounter and outcome
    Grundar alliance status

    # Factions
    Kraken Society first contact
    Lord Neverember's involvement

Integration:
  Add to config.yaml to have prep.py include it in every session prep call:
    documents:
      - label: campaign_state
        path: docs/campaign_state.md

  Pass to planning.py or party.py:
    python planning.py --npc grundar.md --context docs/campaign_state.md --output planning.md
    python party.py --character soma.md --context docs/campaign_state.md --output party.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import prepare_chunks, make_client, stream_api

EXTRACT_SYSTEM_BASE = """\
You are extracting campaign completion and status information from D&D session summary notes.

Focus on facts that establish WHAT HAS BEEN COMPLETED and WHAT IS CURRENTLY TRUE. Extract:

## Completed Encounters & Quests
Any quest, mission, encounter, dungeon, or objective that was fully resolved. For each:
- Name or description of the content
- Session or approximate time it occurred
- Outcome (success, failure, partial, abandoned)
- Consequences for the world or party

## Resolved Plot Threads
Story threads that are definitively closed — mysteries solved, conflicts ended, \
factions defeated or allied. Enough detail to know they are finished.

## NPC State Changes
Changes to named NPCs that define their current status:
- Deaths, incapacitations, or captures
- Alliance shifts (enemy → ally, neutral → hostile, etc.)
- Location changes (where they went after an event)
- Revealed true identities or changed roles

## Party Accomplishments & Acquisitions
Significant things the party has earned, learned, or achieved that carry forward:
- Items, titles, reputations, or secrets gained
- Abilities, oaths, or obligations taken on
- Enemies made or allies secured

## Party Current Situation
The most recent snapshot of where the party is and what they are facing:
- Current location
- Immediate unresolved situation (if any)
{tracked_section}
Rules:
- Only extract things that are clearly completed or definitively established.
- Do not extract things that are still in progress or uncertain.
- Be specific: name the encounter/NPC/thread.
- If a section has nothing relevant in this chunk, omit it.
- Output only the structured notes. No preamble.
"""

EXTRACT_TRACKED_SECTION = """\

## Tracked Items
The following specific events MUST be extracted if they appear anywhere in this chunk, \
even if they would otherwise be omitted. For each one that appears, note exactly what \
happened and the outcome:
{items}
"""

SYNTHESIZE_SYSTEM_BASE = """\
You are creating a campaign state reference document for a D&D GM.

You will receive extraction notes from multiple session summaries. Synthesize them into a \
single authoritative campaign_state.md. This document serves as grounding context for \
future planning: it tells the LLM what is DONE and what is CURRENT so it does not \
hallucinate completed content as still active, or suggest revisiting finished encounters.

Produce campaign_state.md with these sections:

## Completed Encounters & Quests
A definitive list of content that is DONE and should NOT be replayed or re-suggested.
For each entry: name, brief outcome, and any lasting consequence.
Format as a list, most recent last.

## Resolved Plot Threads
Threads that are closed. One bullet per thread: what it was and how it ended.

## NPC Current States
A table of all named NPCs with their current status:
| NPC | Status | Last Known Location | Disposition toward Party |
(Status: Alive / Dead / Missing / Imprisoned / Unknown)

## Active Quests & Open Threads
What is genuinely still in play. For each: what it is, current stakes, and last known state.
Keep this section short — if it's here, it's unfinished.

## Party Current Situation
- Current location
- Active obligations and outstanding debts
- Key resources and assets held
- Recent developments shaping the next session
{tracked_section}
Rules:
- Merge duplicate entries; later events override earlier ones.
- The "Completed" sections are the most important — be thorough and explicit there.
- The "Active" section should only contain genuinely unresolved threads.
- Be concise. This document is scanned quickly before each session.
- Do not invent anything not present in the source notes.
- Output only the campaign_state document. No preamble or commentary.
"""

SYNTHESIZE_TRACKED_SECTION = """\

## Tracked Items Status
The following events were explicitly requested for tracking. For EACH item below, \
include a subsection with its status and what was found in the session notes. \
If an item was not found at all, write "NOT FOUND IN SUMMARIES" so the GM knows \
to verify it manually.
{items}
"""

SYNTHESIZE_FROM_CHAPTERS_SYSTEM_BASE = """\
You are creating a campaign state reference document for a D&D GM.

You will receive a set of per-chapter structured extraction notes. Each extract \
uses this shared schema:

  ## NPCs                (identity, faction, actions, state changes, last location)
  ## Factions            (visible actions, alliances, resources, members)
  ## Party               (PC decisions, acquisitions, arc beats, relationships)
  ## Quests & Threads    (one bullet per thread with explicit OPENED / PROGRESSED / RESOLVED)
  ## Locations           (named places and their current state)
  ## Events              (significant events, chronological)
  ## Arc Score Events    (moments that trigger tracked threat arcs)
  ## Revealed Information (secrets and intel the party uncovered)
  ## Tracked Items       (optional; only present when a tracking list was used)

Your output is a **campaign_state** grounding document: what has been COMPLETED \
and what is CURRENTLY TRUE. It prevents downstream planning from hallucinating \
finished content as still active. Focus on these sections when building it:

- ## Quests & Threads with status "RESOLVED" → feed the Completed Encounters & Quests
  and Resolved Plot Threads sections
- ## Quests & Threads with status "OPENED" or "PROGRESSED" → feed Active Quests & Open Threads
- ## NPCs, specifically state-change lines (died, incapacitated, captured,
  allied/hostile shift, location change, revealed identity) → NPC Current States table
- ## Party → Party Accomplishments & Acquisitions and Party Current Situation
- ## Tracked Items (if present) → the Tracked Items Status section

Sections that exist but are not primary: ## Factions, ## Locations, ## Events, \
## Arc Score Events, ## Revealed Information. Use them for incidental context \
(e.g. filling in an NPC's last known location) but they are not the focus — a \
companion document (world_state) covers lore, and another (planning) covers \
forward-looking threat tracking.

Produce campaign_state.md with these sections:

## Completed Encounters & Quests
A definitive list of content that is DONE and should NOT be replayed or re-suggested. \
For each entry: name, brief outcome, and any lasting consequence. Most recent last.

## Resolved Plot Threads
Threads that are closed. One bullet per thread: what it was and how it ended.

## NPC Current States
A table of all named NPCs with their current status:
| NPC | Status | Last Known Location | Disposition toward Party |
(Status: Alive / Dead / Missing / Imprisoned / Unknown)

## Active Quests & Open Threads
What is genuinely still in play. For each: what it is, current stakes, last known state. \
Keep this section short — if it's here, it's unfinished.

## Party Current Situation
- Current location
- Active obligations and outstanding debts
- Key resources and assets held
- Recent developments shaping the next session
{tracked_section}
Rules:
- Merge duplicate entries across chapters; later chapters override earlier ones on conflicts.
- The "Completed" sections are the most important — be thorough and explicit there.
- The "Active" section should only contain genuinely unresolved threads.
- Be concise. This document is scanned quickly before each session.
- Do not invent anything not present in the source extracts.
- Output only the campaign_state document. No preamble or commentary.
"""


def load_tracking_items(path: Path) -> list[str]:
    """Load tracking items from a file. One item per line; # comments and blank lines ignored."""
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            items.append(stripped)
    return items


def build_extract_system(tracked_items: list[str]) -> str:
    if not tracked_items:
        return EXTRACT_SYSTEM_BASE.format(tracked_section="")
    item_list = "\n".join(f"- {item}" for item in tracked_items)
    tracked_section = EXTRACT_TRACKED_SECTION.format(items=item_list)
    return EXTRACT_SYSTEM_BASE.format(tracked_section=tracked_section)


def build_synthesize_system(tracked_items: list[str]) -> str:
    if not tracked_items:
        return SYNTHESIZE_SYSTEM_BASE.format(tracked_section="")
    item_list = "\n".join(f"- {item}" for item in tracked_items)
    tracked_section = SYNTHESIZE_TRACKED_SECTION.format(items=item_list)
    return SYNTHESIZE_SYSTEM_BASE.format(tracked_section=tracked_section)


def build_synthesize_from_chapters_system(tracked_items: list[str]) -> str:
    if not tracked_items:
        return SYNTHESIZE_FROM_CHAPTERS_SYSTEM_BASE.format(tracked_section="")
    item_list = "\n".join(f"- {item}" for item in tracked_items)
    tracked_section = SYNTHESIZE_TRACKED_SECTION.format(items=item_list)
    return SYNTHESIZE_FROM_CHAPTERS_SYSTEM_BASE.format(tracked_section=tracked_section)



def run_extract(
    client, text: str, chunk_size: int, model: str, extract_dir: Path,
    tracked_items: list[str], split_chapters: str | None = None,
) -> list[Path]:
    chunks, label = prepare_chunks(text, chunk_size, split_chapters, split_label="session")
    total = len(chunks)
    extract_dir.mkdir(parents=True, exist_ok=True)
    system = build_extract_system(tracked_items)
    saved = []

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"extract_{i:03d}.md"
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting {label} ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, system, chunk, model)
        print("  " + "─" * 56)

        out_file.write_text(result, encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize(
    client, extract_files: list[Path], model: str, tracked_items: list[str],
) -> str:
    combined = [
        f"<!-- Source: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in sorted(extract_files)
    ]
    user_prompt = "\n\n---\n\n".join(combined)
    system = build_synthesize_system(tracked_items)
    print(f"  Synthesizing {len(extract_files)} extraction(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, system, user_prompt, model)
    print("  " + "─" * 56)
    return result


def run_synthesize_from_chapters(
    client, chapter_files: list[Path], model: str, tracked_items: list[str],
) -> str:
    combined = [
        f"<!-- Chapter extract: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in sorted(chapter_files)
    ]
    user_prompt = "\n\n---\n\n".join(combined)
    system = build_synthesize_from_chapters_system(tracked_items)
    print(f"  Synthesizing {len(chapter_files)} chapter extract(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, system, user_prompt, model)
    print("  " + "─" * 56)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a campaign_state.md (completed content + current NPC states) "
                    "from session summaries."
    )
    parser.add_argument("input", nargs="?",
                        help="Session summaries file (not needed with --synthesize-only)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the campaign state document")
    parser.add_argument("--track-file", metavar="FILE",
                        help="Text file listing events/locations/NPCs to explicitly track "
                             "(one item per line, # for comments). Items appear as a dedicated "
                             "'Tracked Items Status' section in the output.")
    parser.add_argument("--track", nargs="+", metavar="ITEM",
                        help="One or more tracking items as inline arguments "
                             "(alternative to --track-file)")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX", default=None,
                        help="Split input at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Session'). Each session becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load intermediate extractions "
                             "(default: <output_dir>/state_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir "
                             "(tracking list still applies to synthesize prompt)")
    parser.add_argument("--chapter-extracts", metavar="DIR", default=None,
                        help="Synthesize from shared per-chapter extracts produced by "
                             "chapter_extract.py. Skips the extract pass and uses a "
                             "schema-aware synthesize prompt. Additive: existing --extract-dir "
                             "/ --synthesize-only paths are unaffected. --track-file still "
                             "applies to the synthesize-time Tracked Items Status section.")
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

    # Load tracking items
    tracked_items: list[str] = []
    if args.track_file:
        track_path = Path(args.track_file).expanduser()
        if not track_path.exists():
            print(f"Error: track file not found: {track_path}", file=sys.stderr)
            sys.exit(1)
        tracked_items = load_tracking_items(track_path)
    if args.track:
        tracked_items = tracked_items + args.track

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "state_extractions"
    )

    client = make_client()

    if tracked_items:
        print(f"\n  Tracking {len(tracked_items)} item(s):")
        for item in tracked_items:
            print(f"    • {item}")

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
        state_doc = run_synthesize_from_chapters(client, chapter_files, args.model, tracked_items)
        print("=" * 60)

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(state_doc.strip() + "\n", encoding="utf-8")
        print(f"\nCampaign state saved to: {output}")
        print(f"Source chapter extracts: {chapter_dir}")
        if tracked_items:
            print(f"\nCheck the 'Tracked Items Status' section in {output.name} for any NOT FOUND items.")
        print()
        return

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        if not text.strip():
            print(f"Error: input file is empty: {args.input}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Pass 1: Extract campaign state | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract(client, text, args.chunk_size, args.model, extract_dir,
                                    tracked_items, split_chapters=args.split_chapters)
        if not extract_files:
            print("Error: no chunks were extracted — input may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize | model: {args.model}]")
    print("=" * 60)
    state_doc = run_synthesize(client, extract_files, args.model, tracked_items)
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(state_doc.strip() + "\n", encoding="utf-8")
    print(f"\nCampaign state saved to: {output}")
    print(f"Extractions kept in: {extract_dir}")
    if tracked_items:
        print(f"\nCheck the 'Tracked Items Status' section in {output.name} for any NOT FOUND items.")
    print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
