#!/usr/bin/env python3
"""Enhance an existing session recap with richer narrative, more memorable moments,
and a plot consistency check.

Takes a recap file (e.g. from gmassisstant.app) and runs two passes:

  1. Consistency check (silent) — compares the recap against campaign context documents
     (campaign_state.md, world_state.md, party.md) and produces a list of errors,
     contradictions, and questionable claims.

  2. Enhancement — rewrites the Summary with more narrative texture and quoted dialogue
     from the session extractions, expands Memorable Moments with anything significant
     that was missed, and appends a Consistency Notes section from pass 1.

The Scenes, NPCs, Locations, Items, and Spells sections are preserved unchanged.

Usage:
  python enhance_recap.py session-mar \\
      --roleplay-extract-dir vtt_roleplay_extractions/ \\
      --summary-extract-dir  vtt_extractions/ \\
      --context docs/campaign_state.md docs/world_state.md docs/party.md \\
      --output session-mar-enhanced.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, stream_api, save_log


CONSISTENCY_SYSTEM = """\
You are a continuity editor for a D&D campaign. You will be given a session recap and
one or more campaign context documents (campaign state, world state, party document).

Your job: identify every factual error, contradiction, or questionable claim in the recap.

Look for:
- Wrong NPC names, titles, or factions
- Events described as completed that haven't happened yet (per campaign state)
- Attributing actions or items to the wrong character
- Lore contradictions against world_state (places, factions, history)
- Character abilities or items that don't match their sheet
- Timeline issues (referencing events out of order)
- Ambiguous claims that might confuse future sessions

For each issue, output:
- **Location**: which section of the recap (Summary / Memorable Moments / Scenes / NPCs / etc.)
- **Issue**: what is wrong or uncertain
- **Evidence**: what the context documents say
- **Suggested fix**: a brief correction

If nothing is wrong, say so clearly.
Output only the consistency report. No preamble.
"""

ENHANCE_SYSTEM = """\
You are enhancing a D&D session recap. You will be given:
- The original recap
- Roleplay extractions — raw quoted dialogue and character moments from the session
- Session extractions — action detail, events, environmental context
- A consistency report flagging errors in the original
- (Optionally) a party document for character voice reference

Your job: produce an improved version of the recap that:

1. SUMMARY — Rewrite with more narrative texture. Weave in quoted dialogue from the
   extractions. Every significant thing a character said should appear as a direct quote,
   not a paraphrase. Keep the existing prose structure but make it come alive.
   Use the consistency report to correct any errors silently.

2. MEMORABLE MOMENTS — Keep all existing entries. Add new ones for any significant
   roleplay moment, memorable line, or dramatic beat in the extractions that isn't
   already captured. Format new entries consistently with the existing ones:
   bold description, italicised context note, blockquote for direct quotes.

3. CONSISTENCY NOTES — Append a new section at the end listing any issues from the
   consistency report that couldn't be silently fixed in the text (ambiguities,
   unresolved contradictions, things the GM should verify).

4. ALL OTHER SECTIONS (Scenes, NPCs, Locations, Items, Spells) — Preserve exactly
   as they are. Do not rewrite, reorder, or add to them.

Output the complete enhanced recap document. No preamble or commentary.
"""


def load_extractions(path_str: str) -> list[tuple[str, str]]:
    d = Path(path_str).expanduser()
    files = sorted(d.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


def format_extractions(extractions: list[tuple[str, str]], heading: str) -> str:
    parts = [f"### Chunk {i}\n\n{content}"
             for i, (_, content) in enumerate(extractions, 1)]
    return f"## {heading}\n\n" + "\n\n---\n\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhance a session recap with richer narrative, more memorable moments, "
                    "and a plot consistency check."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Existing session recap file to enhance")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the enhanced recap")
    parser.add_argument("--roleplay-extract-dir", metavar="DIR",
                        help="vtt_roleplay_extractions/ — quoted dialogue and character moments")
    parser.add_argument("--summary-extract-dir", metavar="DIR",
                        help="vtt_extractions/ — action detail and event context")
    parser.add_argument("--context", nargs="+", metavar="FILE",
                        help="Campaign context files for consistency check "
                             "(e.g. campaign_state.md world_state.md party.md)")
    parser.add_argument("--party", metavar="FILE",
                        help="Party document for character voice reference")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--model", default="claude-sonnet-4-20250514")
    args = parser.parse_args()

    # ── Load inputs ───────────────────────────────────────────────────────────
    recap_path = Path(args.recap).expanduser()
    if not recap_path.exists():
        print(f"Error: recap file not found: {recap_path}", file=sys.stderr)
        sys.exit(1)
    recap = recap_path.read_text(encoding="utf-8")
    print(f"  Recap: {recap_path.name} ({len(recap):,} chars)")

    roleplay_extractions: list[tuple[str, str]] = []
    if args.roleplay_extract_dir:
        roleplay_extractions = load_extractions(args.roleplay_extract_dir)
        print(f"  Roleplay extractions: {len(roleplay_extractions)} chunk(s)")

    summary_extractions: list[tuple[str, str]] = []
    if args.summary_extract_dir:
        summary_extractions = load_extractions(args.summary_extract_dir)
        print(f"  Session extractions:  {len(summary_extractions)} chunk(s)")

    context_parts: list[str] = []
    if args.context:
        for ctx in args.context:
            p = Path(ctx).expanduser()
            if p.exists():
                context_parts.append(f"## {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
            else:
                print(f"  Warning: context file not found: {p}", file=sys.stderr)
        if context_parts:
            print(f"  Context files: {len(context_parts)}")

    party_text: str | None = None
    if args.party:
        p = Path(args.party).expanduser()
        if p.exists():
            party_text = p.read_text(encoding="utf-8")
        else:
            print(f"  Warning: party file not found: {p}", file=sys.stderr)

    client = make_client()

    # ── Pass 1: Consistency check ─────────────────────────────────────────────
    consistency_report = ""
    if context_parts:
        print(f"\n[Pass 1: Consistency check | model: {args.model}]")
        print("=" * 60)
        consistency_prompt = (
            "## Session Recap\n\n" + recap.strip() +
            "\n\n---\n\n## Campaign Context\n\n" +
            "\n\n---\n\n".join(context_parts)
        )
        consistency_report = stream_api(client, CONSISTENCY_SYSTEM, consistency_prompt,
                                        args.model, silent=True)
        # Print a summary of issues found
        issue_count = consistency_report.count("**Location**")
        if issue_count:
            print(f"  Found {issue_count} potential issue(s):")
            for line in consistency_report.splitlines():
                if line.startswith("- **Issue**") or line.startswith("**Issue**"):
                    print(f"    {line.strip()}")
        else:
            print("  No issues found.")
        print("=" * 60)
    else:
        print("\n[Pass 1: Consistency check skipped — no --context files provided]")

    # ── Pass 2: Enhancement ───────────────────────────────────────────────────
    print(f"\n[Pass 2: Enhance | model: {args.model}]")
    print("=" * 60)

    enhance_parts = ["## Original Recap\n\n" + recap.strip()]

    if roleplay_extractions:
        enhance_parts.append(format_extractions(
            roleplay_extractions,
            "Roleplay Extractions (quoted dialogue and character moments — primary source)"
        ))
    if summary_extractions:
        enhance_parts.append(format_extractions(
            summary_extractions,
            "Session Extractions (action detail, events, environmental context)"
        ))
    if consistency_report.strip():
        enhance_parts.append("## Consistency Report\n\n" + consistency_report.strip())
    if party_text:
        enhance_parts.append("## Party Document (character voice reference)\n\n"
                             + party_text.strip())

    enhance_prompt = "\n\n---\n\n".join(enhance_parts)
    enhanced = stream_api(client, ENHANCE_SYSTEM, enhance_prompt, args.model)
    print("=" * 60)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(enhanced.strip() + "\n", encoding="utf-8")
    print(f"\nEnhanced recap saved to: {output}")

    if not args.no_log:
        log_sections = [("Consistency Report", consistency_report or "(skipped)"),
                        ("Enhanced Recap", enhanced)]
        log_file = save_log(str(output.parent / "logs"), log_sections, stem="enhance_recap")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
