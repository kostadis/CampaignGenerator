#!/usr/bin/env python3
"""Stage 1 — enhance a gm-assist recap with VTT detail.

Single LLM call. The full VTT transcript goes into a cached system prefix;
the gm-assist body goes into the user message with the enrichment prompt.
The model returns one enriched markdown document that preserves the
gm-assist's section structure (Summary, Memorable Moments, Scenes, NPCs,
Locations, Items, Spells, etc.) but fills in details and verbatim moments
the recap missed.

Output is human-reviewable. It is the input to Stage 2 (scene_extract.py).

Usage:
  python enhance_summary.py session.vtt \\
      --gmassist gm-assist.md \\
      --output session-summary.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, save_log, stream_api
from vtt_summary import parse_vtt


ENHANCE_SYSTEM_PREFIX = """\
You are reading a Zoom transcript from a D&D session, anchored to a
gm-assist recap that gives the canonical structure of the session.

Your job: produce an ENRICHED version of the gm-assist by filling in
details and verbatim moments from the transcript that the recap missed.
The recap's section structure is the contract — preserve every section
header it uses (Summary, Memorable Moments, Scenes, NPCs, Locations,
Items, Spells, etc.) and produce a richer version of each.

GROUND RULES:
- Use the recap as the structural spec. Do not invent new top-level
  sections, do not drop existing ones, do not reorder scenes.
- Within each section, ENRICH from the transcript: add bullets for
  details the recap missed, expand thin scenes with what actually
  happened, lift verbatim quotes for Memorable Moments.
- Do NOT invent anything. Every added detail must be supportable from
  the transcript. If a recap claim has no transcript evidence, leave
  the recap claim alone — do not contradict it, do not delete it.
- Quote dialogue VERBATIM when promoting a line to Memorable Moments
  or a scene bullet. If a line is cut off in the transcript, copy what
  is there and mark it (truncated). Mark (paraphrase) only when no
  direct quote exists at all.
- Speaker label normalisation: Zoom labels are unreliable. Use the
  recap's attributions as ground truth. Map by voice context — players
  to their characters, DM lines stay attributed to the DM or the NPC
  being voiced. Strip parentheticals like "(Player)" or "(GM)".

OUTPUT:
- One complete markdown document. No preamble, no commentary about
  your process — just the enriched recap.
"""


ENHANCE_USER_TEMPLATE = """\
The full VTT transcript is in the cached system prefix above.

Here is the gm-assist recap. Produce an enriched version following
the rules in the system prompt — same section structure, richer
content drawn from the transcript.

---

{gmassist_body}
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 1 — enrich a gm-assist recap with VTT detail (single cached call)."
    )
    parser.add_argument("input", metavar="FILE", help="Zoom .vtt transcript file")
    parser.add_argument("--gmassist", "-g", required=True, metavar="FILE",
                        help="gm-assist recap (the structural spec)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to write the enriched session-summary.md "
                             "(typically alongside the gm-assist)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster)")
    parser.add_argument("--max-tokens", type=int, default=16384,
                        help="Max output tokens (default: 16384 — enriched recaps "
                             "can be large)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable prompt caching of the VTT prefix")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--verbose", action="store_true",
                        help="Print system + user prompts before the API call")
    args = parser.parse_args()

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"
        print("  [fast mode: claude-haiku-4-5-20251001]")

    vtt_path = Path(args.input).expanduser()
    if not vtt_path.exists():
        print(f"Error: VTT file not found: {vtt_path}", file=sys.stderr)
        sys.exit(1)
    raw = vtt_path.read_text(encoding="utf-8")
    print(f"\n[Parsing VTT | {len(raw):,} raw chars | {vtt_path.name}]")
    dialogue = parse_vtt(raw)
    if not dialogue.strip():
        print(f"Error: no dialogue found in VTT file: {vtt_path.name}", file=sys.stderr)
        sys.exit(1)
    print(f"  → {len(dialogue):,} chars of dialogue")

    gm_path = Path(args.gmassist).expanduser()
    if not gm_path.exists():
        print(f"Error: gm-assist file not found: {gm_path}", file=sys.stderr)
        sys.exit(1)
    gmassist_body = gm_path.read_text(encoding="utf-8")
    print(f"\n[gm-assist | {gm_path.name} | {len(gmassist_body):,} chars]")

    out_path = Path(args.output).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    system = ENHANCE_SYSTEM_PREFIX + "\n---\n\nFULL VTT TRANSCRIPT:\n\n" + dialogue
    user = ENHANCE_USER_TEMPLATE.format(gmassist_body=gmassist_body)

    client = make_client()
    print(f"\n[Enhancing summary | model: {args.model} | "
          f"system: {len(system):,} chars | user: {len(user):,} chars]")
    print("=" * 60)
    enriched = stream_api(
        client,
        system=system,
        user=user,
        model=args.model,
        max_tokens=args.max_tokens,
        cache_system=not args.no_cache,
        verbose=args.verbose,
    )
    print("=" * 60)

    out_path.write_text(enriched.rstrip() + "\n", encoding="utf-8")
    print(f"\nWrote enriched summary to {out_path} ({len(enriched):,} chars)")

    if not args.no_log:
        log_dir = out_path.parent / "logs"
        log_sections = [
            ("VTT", f"{vtt_path.name} — {len(dialogue):,} chars dialogue"),
            ("gm-assist", gmassist_body),
            ("Enriched summary", enriched),
        ]
        log_file = save_log(str(log_dir), log_sections, stem="enhance_summary")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
