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

Use --extract-only to stop after the extract pass so you can review and edit
the intermediate files before synthesis (recommended for large corpora).

Usage:
  campaign_state summaries.md --output docs/campaign_state.md

  # With a tracking list to ensure specific events are never missed
  campaign_state summaries.md \\
      --track-file tracking.txt \\
      --output docs/campaign_state.md

  # Re-synthesize without re-extracting (tracking list still applies)
  campaign_state --synthesize-only \\
      --track-file tracking.txt \\
      --extract-dir docs/state_extractions \\
      --output docs/campaign_state.md

  # Ensemble workflow: --extract-dir omitted auto-stages
  # docs/ensemble/drafts/world_state_draft.md + docs/ensemble/threads.md as extracts
  campaign_state --synthesize-only --output docs/campaign_state_draft.md

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
  Add to config.yaml to have prep include it in every session prep call:
    documents:
      - label: campaign_state
        path: docs/campaign_state.md

  Pass to planning or party:
    planning --npc grundar.md --context docs/campaign_state.md --output planning.md
    party --character soma.md --context docs/campaign_state.md --output party.md
"""

import argparse
import shutil
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_alias_normalizer,
    client_from_args,
    format_npc_roster,
    load_agent_prompt,
    find_alias_registry,
    load_alias_map,
    make_client,
    resolve_extract_output,
    run_extract_pipeline,
    run_synthesize_pipeline,
)

EXTRACT_SYSTEM_BASE = load_agent_prompt("campaign_state_extract")

EXTRACT_TRACKED_SECTION = load_agent_prompt("campaign_state_extract_tracked")

SYNTHESIZE_SYSTEM_BASE = load_agent_prompt("campaign_state_synthesize")

SYNTHESIZE_TRACKED_SECTION = load_agent_prompt("campaign_state_synthesize_tracked")


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


def auto_stage_synthesize_only_extracts(output_dir: Path) -> Path:
    """Auto-stage world_state_draft.md + docs/ensemble/threads.md as extract_*.md
    so --synthesize-only works without the manual mkdir+cp 'staging trick'
    (docs/cli/ensemble_workflow.md §3c). Always re-copies from source so a
    staged extract can't go stale relative to what it was copied from.

    The world-state source lives under Dossier Synthesis's own draft
    directory (docs/ensemble/drafts/, not the pre-move docs/ shared path) —
    this cross-service dependency follows that service to its new location
    rather than reading whichever rendering service wrote the shared
    filename last (006-state-projection-service FR-007a). A plain literal on
    purpose, not a projections.yaml/ensemble.yaml read: a cross-service
    config read is the defect _backend_flags was deleted for (FR-003).
    """
    cwd = Path.cwd()
    sources = [
        (cwd / "docs" / "ensemble" / "drafts" / "world_state_draft.md",
         "extract_001_world_state.md"),
        (cwd / "docs" / "ensemble" / "threads.md", "extract_002_threads.md"),
    ]
    missing = [str(src) for src, _ in sources if not src.exists()]
    if missing:
        print("Error: --synthesize-only auto-staging needs these files first:",
              file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print("Run world_state synthesis (and the threads stage) before "
              "campaign_state, or pass --extract-dir to point at your own "
              "pre-staged extracts instead.", file=sys.stderr)
        sys.exit(1)
    staging_dir = output_dir / "state_staging" / "campaign_state"
    staging_dir.mkdir(parents=True, exist_ok=True)
    for src, name in sources:
        shutil.copyfile(src, staging_dir / name)
    return staging_dir


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a campaign_state.md (completed content + current NPC states) "
                    "from the canonical timeline."
    )
    parser.add_argument("input", nargs="?",
                        help="Canonical timeline — the master narrative bible (not needed with --synthesize-only)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the campaign state document")
    parser.add_argument("--track-file", metavar="FILE", action="append",
                        help="Text file listing events/locations/NPCs to explicitly track "
                             "(one item per line, # for comments). Items appear as a dedicated "
                             "'Tracked Items Status' section in the output. May be repeated to "
                             "load multiple tracking files (e.g. a module baseline plus per-arc "
                             "homebrew tracking).")
    parser.add_argument("--track", nargs="+", action="extend", metavar="ITEM",
                        help="One or more tracking items as inline arguments "
                             "(alternative to --track-file)")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX", default=None,
                        help="Split input at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Session'). Each session becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load intermediate extractions "
                             "(default: <output_dir>/state_extractions/, or an "
                             "auto-staged dir — see --synthesize-only)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir "
                             "(tracking list still applies to synthesize prompt). If "
                             "--extract-dir is omitted, auto-stages "
                             "docs/ensemble/drafts/world_state_draft.md "
                             "+ docs/ensemble/threads.md as extracts (run those first)")
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
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Model id (Claude id, or an OpenRouter id for --backend openrouter)")
    add_backend_args(parser)
    parser.add_argument("--dump-input", default=None, metavar="FILE",
                        help="Write the synthesis prompt to FILE (and FILE.system.md) "
                             "without making an API call — for use with `claude -p`.")
    parser.add_argument("--dump-only", action="store_true",
                        help="With --dump-input: stop after writing the dump, making no API call.")
    args = parser.parse_args()

    if args.synthesize_only and args.extract_only:
        print("Error: --synthesize-only and --extract-only are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
    if not args.synthesize_only and not args.input:
        print("Error: input file required unless --synthesize-only", file=sys.stderr)
        sys.exit(1)

    # Load tracking items
    tracked_items: list[str] = []
    if args.track_file:
        for track_file in args.track_file:
            track_path = Path(track_file).expanduser()
            if not track_path.exists():
                print(f"Error: track file not found: {track_path}", file=sys.stderr)
                sys.exit(1)
            tracked_items.extend(load_tracking_items(track_path))
    if args.track:
        tracked_items = tracked_items + args.track

    output = Path(args.output).expanduser().resolve()
    if args.extract_dir:
        extract_dir = Path(args.extract_dir).expanduser().resolve()
    elif args.synthesize_only:
        extract_dir = auto_stage_synthesize_only_extracts(output.parent)
        print(f"[Auto-staged synthesize-only inputs into {extract_dir}]")
    else:
        extract_dir = output.parent / "state_extractions"

    alias_map = load_alias_map(args.dossier_dir, registry_path=find_alias_registry(Path.cwd()))
    normalize, _ = build_alias_normalizer(alias_map)
    roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    client = client_from_args(args)

    if tracked_items:
        print(f"\n  Tracking {len(tracked_items)} item(s):")
        for item in tracked_items:
            print(f"    • {item}")

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        if not text.strip():
            print(f"Error: input file is empty: {args.input}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Pass 1: Extract campaign state | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_result = run_extract_pipeline(
            client, text,
            extract_system=build_extract_system(tracked_items),
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="session",
            input_normalizer=normalize,
            system_suffix=roster,
            batch=args.batch,
        )
        extract_files = resolve_extract_output(
            extract_result, batch=args.batch, extract_dir=extract_dir)
        if not extract_files:
            print("Error: no chunks were extracted — input may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, run:")
            print(f"  campaign_state --synthesize-only "
                  f"--extract-dir {extract_dir} --output {Path(args.output)}")
            return
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize | model: {args.model}]")
    print("=" * 60)
    try:
        state_doc = run_synthesize_pipeline(
            client,
            source_groups=[("", extract_files)],
            synthesize_system=build_synthesize_system(tracked_items),
            model=args.model,
            input_normalizer=normalize,
            system_suffix=roster,
            dump_input=args.dump_input,
            dump_only=args.dump_only,
            batch=args.batch,
        )
    except RuntimeError as e:
        print(f"Error: synthesis batch item failed: {e}", file=sys.stderr)
        sys.exit(1)
    print("=" * 60)

    if args.dump_only:
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(state_doc.strip() + "\n", encoding="utf-8")
    print(f"\nCampaign state saved to: {output}")
    print(f"Extractions kept in: {extract_dir}")
    if tracked_items:
        print(f"\nCheck the 'Tracked Items Status' section in {output.name} for any NOT FOUND items.")
    print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
