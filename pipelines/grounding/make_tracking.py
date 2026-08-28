#!/usr/bin/env python3
"""Extract a campaign_state tracking list from an adventure module or campaign document.

Reads a markdown adventure file and produces a tracking.txt suitable for passing
to campaign_state --track-file. The tracking file lists every named quest,
encounter, dungeon, key location, and plot point in the adventure so that
campaign_state will explicitly hunt for and report on each one.

Usage:
  make_tracking adventure.md --output tracking.txt
  make_tracking "Dragon of Icespire Peak.md" -o docs/tracking.txt

  # Then use with campaign_state:
  campaign_state summaries.md \\
      --track-file docs/tracking.txt \\
      --output docs/campaign_state.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    add_backend_args,
    client_from_args,
    run_single_batch,
    stream_api,
    DEFAULT_MODEL,
)
from campaignlib.api.client import resolve_cli_model

SYSTEM_PROMPT = """\
You are reading a D&D adventure module or campaign document and extracting a tracking list.

Your output will be used as a checklist for a campaign state tracker. It tells the tracker \
which specific events to look for in session summaries to determine whether they have happened yet.

Extract every:
- Named quest or mission (main and side quests)
- Named encounter location (dungeons, ruins, lairs, strongholds)
- Key NPC events (first contact, alliance, betrayal, death of named NPCs)
- Major plot beats (reveals, faction events, arc milestones)
- Any other discrete completable event that a GM would want to confirm happened

CRITICAL — phrasing rules:
- Each item must describe the SUBJECT and EVENT TYPE only, not the outcome.
- Do NOT phrase items as already completed (e.g. NOT "Dragon defeated", NOT "Orcs displaced").
- DO phrase items neutrally so the tracker can find them whether done or not.
  Good: "Cryovain encounter — Icespire Hold"
  Good: "Gnomengarde dungeon — mystery monster"
  Good: "Stone-Cold Reavers — treasure hunt encounter"
  Good: "Wererats at Tresendar Manor"
  Bad: "Dragon Cryovain driven from territory" (asserts outcome)
  Bad: "Orcs displaced by dragon threat" (asserts outcome)

Format:
- One item per line
- Group related items under a # comment header (e.g. # Main Quests, # Side Quests, # Locations, # NPCs)
- Do not number the items
- Do not include GM prep content (read-aloud text, stat blocks, encounter tables)
  — only events the party can complete or witness

Output only the tracking list. No preamble or commentary.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract a tracking list from an adventure module for use with campaign_state.py."
    )
    parser.add_argument("input", metavar="FILE",
                        help="Adventure module or campaign markdown file")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the tracking list (e.g. tracking.txt)")
    parser.add_argument("--model", default=None,
                        help="Claude model to use")
    add_backend_args(parser)
    args = parser.parse_args()
    args.model = resolve_cli_model(
        args, legacy_default=DEFAULT_MODEL
    ).effective_model

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    text = input_path.read_text(encoding="utf-8")
    print(f"\n[Extracting tracking list | {len(text):,} chars | model: {args.model}]")
    print("=" * 60)

    client = client_from_args(args)
    if args.batch:
        try:
            result = run_single_batch(client, system=SYSTEM_PROMPT, user=text,
                                      model=args.model, max_tokens=8096)
        except RuntimeError as e:
            print(f"Error: batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        result = stream_api(client, SYSTEM_PROMPT, text, args.model)
    print("=" * 60)

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.strip() + "\n", encoding="utf-8")
    print(f"\nTracking list saved to: {output}")

    # Count items for a quick summary
    items = [l for l in result.splitlines() if l.strip() and not l.strip().startswith("#")]
    print(f"{len(items)} trackable item(s) extracted.")
    print(f"\nNext step:")
    print(f"  campaign_state summaries.md --track-file {output} --output campaign_state.md")


if __name__ == "__main__":
    main()
