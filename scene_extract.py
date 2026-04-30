#!/usr/bin/env python3
"""Stage 2 — scene-anchored VTT extraction.

Takes a Zoom .vtt transcript and an enriched session summary (Stage 1 output
from enhance_summary.py, post-human-review) and produces one rich
extraction file per scene named in the summary. The summary is the
human-verified scene structure — feeding it into extraction directly avoids
re-deriving structure from arbitrary chunk windows.

Each per-scene call sends the full VTT in the system prompt (cached as a
prefix) and a short user message naming one scene + its bullets. The model
returns the verbatim transcript moments belonging to that scene.

Usage:
  python scene_extract.py session.vtt \\
      --summary session-summary.md \\
      --output-dir scene_extractions/ \\
      [--dossier-dir docs/npcs/]

Output:
  scene_extractions/01_<scene_slug>.md  ... 09_<scene_slug>.md
  Each file contains the scene summary verbatim + a verbatim-moments
  section sourced from the VTT.
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    build_alias_normalizer,
    format_npc_roster,
    load_alias_map,
    make_client,
    parse_gmassist_scenes,
    run_scene_extraction,
    save_log,
)
from vtt_summary import parse_vtt


SCENE_EXTRACT_SYSTEM_PREFIX = """\
You are reading a Zoom transcript from a D&D session, anchored to an
enriched session summary that has already structured the session into
named scenes.

The user will name one scene at a time and quote the summary's bullets
for it. Your job: find every moment in the transcript that belongs to
that scene and surface it as a rich, verbatim extraction.

GROUND RULES:
- Use the summary bullets as scope: only extract moments that fit the scene.
- Quote dialogue VERBATIM. Do not paraphrase. If a line is cut off in the
  transcript, copy what is there and mark it (truncated). Only mark
  (paraphrase) when no direct quote exists at all.
- Do NOT invent anything. If the transcript contains nothing that matches
  a summary bullet, omit it — silence is correct, fabrication is not.
- The summary is the structural spec but may still miss detail. Capture
  verbatim exchanges, OOC banter that reveals character, dice rolls
  reified as narrative beats, and environmental texture the summary
  glosses.

OUTPUT FORMAT — flat markdown, no preamble:

**[Speaker]** — *brief context*
> "verbatim quote"
> "verbatim quote from the other side of the exchange"

For action beats / environment use:
**[scene tag — e.g. The Drow Spy Spotted]**
- what happened, in chronological order
- one sentence per beat

SPEAKER LABEL NORMALISATION:
- "GM (Name)" / "DM (Name)" / "Name (GM)" / "Name (DM)" → write as "GM"
- "Character (Player)" → strip the parenthetical; keep the character name
- Unnamed NPCs ("Warrior", "Voice") → keep as-is
"""


SCENE_EXTRACT_USER_TEMPLATE = """\
## Scene to extract

**{name}**

Summary bullets (use as scope — only extract transcript moments that fit):

{body}

---

Find every moment in the transcript that belongs to this scene. Output the
verbatim moments in chronological order, following the format described in
the system prompt. No preamble, no commentary.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scene-anchored VTT extraction (replaces blind chunked extraction)."
    )
    parser.add_argument("input", metavar="FILE", help="Zoom .vtt transcript file")
    parser.add_argument("--summary", "-s", required=True, metavar="FILE",
                        dest="summary",
                        help="Enriched session summary from Stage 1 / "
                             "enhance_summary.py (must contain a ## Scenes section)")
    parser.add_argument("--output-dir", "-o", required=True, metavar="DIR",
                        help="Where to write per-scene extraction files")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Directory of per-NPC dossier files (built by "
                             "planning.py --build-dossiers). Aliases are "
                             "rewritten to canonical names in the VTT before "
                             "extraction; the canonical NPC roster is appended "
                             "to the system prompt.")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster)")
    parser.add_argument("--max-tokens", type=int, default=8192,
                        help="Max output tokens per scene (default: 8192)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Disable prompt caching of the VTT prefix")
    parser.add_argument("--no-log", action="store_true")
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

    summary_path = Path(args.summary).expanduser()
    if not summary_path.exists():
        print(f"Error: summary file not found: {summary_path}", file=sys.stderr)
        sys.exit(1)
    summary_text = summary_path.read_text(encoding="utf-8")

    scenes = parse_gmassist_scenes(summary_text)
    if not scenes:
        print(f"Error: no '## Scenes' section (with ### scene headings) found in {summary_path}.\n"
              f"Scene-anchored extraction requires human-verified scene structure. "
              f"Use vtt_summary.py for unstructured chunk extraction instead.",
              file=sys.stderr)
        sys.exit(1)
    print(f"\n[summary | {summary_path.name}: {len(scenes)} scene(s)]")
    for i, s in enumerate(scenes, 1):
        print(f"  {i}. {s['name']}")

    alias_map = load_alias_map(args.dossier_dir)
    normalize, _ = build_alias_normalizer(alias_map)
    npc_roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"  Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    out_dir = Path(args.output_dir).expanduser()

    client = make_client()
    print(f"\n[Scene extraction | {len(scenes)} scene(s) | model: {args.model}]")
    print("=" * 60)
    saved = run_scene_extraction(
        client,
        vtt_text=dialogue,
        scenes=scenes,
        extract_dir=out_dir,
        model=args.model,
        extraction_instruction=SCENE_EXTRACT_USER_TEMPLATE,
        system_prefix=SCENE_EXTRACT_SYSTEM_PREFIX,
        system_suffix=npc_roster,
        input_normalizer=normalize if alias_map else None,
        cache_vtt=not args.no_cache,
        max_tokens=args.max_tokens,
    )
    print("=" * 60)
    print(f"\nWrote {len(saved)} scene file(s) to {out_dir}")

    if not args.no_log:
        log_sections = [
            ("VTT", f"{vtt_path.name} — {len(dialogue):,} chars"),
            ("Summary", summary_text),
            ("Scenes", "\n".join(f"{i}. {s['name']}" for i, s in enumerate(scenes, 1))),
            ("Output files", "\n".join(str(p) for p in saved)),
        ]
        log_file = save_log(str(out_dir / "logs"), log_sections, stem="scene_extract")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
