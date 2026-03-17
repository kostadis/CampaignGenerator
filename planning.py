#!/usr/bin/env python3
"""Generate a planning.md document from NPC dossiers, threat arc scores, and session summaries.

Combines:
  - NPC dossier files — definitive source for each NPC's identity, motivation, and abilities
  - Threat arc score documents — mechanics tracking NPC/faction progress through the campaign
  - Session summaries (large file) — what has actually happened with each NPC/faction at the table
  - World context files (optional) — faction documents, location notes, etc.

Runs in two passes for the session summaries:
  1. Extract — chunks the summaries, pulls NPC/faction-relevant info from each chunk
  2. Synthesize — combines dossiers + arc scores + extractions into planning.md

Usage:
  python planning.py \\
      --npc grundar.md xalvosh.md jena_roscoe.md \\
      --arc-scores brundar_echo.md kraken_echoes.md kp_planar_distortion.md \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --output docs/planning.md

  # With optional world context
  python planning.py \\
      --npc grundar.md \\
      --arc-scores brundar_echo.md \\
      --summaries summaries.md \\
      --context factions.md locations.md \\
      --output docs/planning.md

  # Re-synthesize without re-extracting
  python planning.py \\
      --npc grundar.md xalvosh.md \\
      --arc-scores brundar_echo.md \\
      --synthesize-only \\
      --extract-dir docs/planning_extractions \\
      --output docs/planning.md

  # Build per-NPC dossier files from session summaries (run once, then edit)
  python planning.py \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --build-dossiers \\
      --dossier-dir docs/npcs/
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib import make_client, stream_api

EXTRACT_SYSTEM = """\
You are extracting NPC and faction-relevant information from D&D session summary notes.

Focus ONLY on named NPCs, factions, and threat actors (not player characters). Extract:

## NPC Activity
For each named NPC: what they did, where they appeared, what they revealed, \
how they interacted with the party or other NPCs.

## Faction Movements
For each faction: actions taken, resources gained or lost, alliances shifted, \
plans advanced or disrupted.

## Threat Arc Events
Specific moments that would trigger arc score increases for any tracked threat \
(e.g. Brundar's Echo, Kraken Society Echoes, Planar Distortion). \
Name the score and describe the triggering event.

## Revealed Information
Secrets, plans, or intel about NPCs/factions that the party has uncovered.

## Current Whereabouts
Last known location or status of any named NPC or faction operative.

Rules:
- Only include information about NPCs and factions, not player characters.
- Be specific: name the NPC/faction and the session event.
- If a section has nothing relevant, omit it entirely.
- Output only the structured notes under the headings above.
"""

SYNTHESIZE_SYSTEM = """\
You are creating a GM planning reference document for a D&D campaign.

You will receive:
- NPC dossier files (definitive source for each NPC's identity, motivation, abilities, and secrets)
- Threat arc score documents (full mechanics: triggers, thresholds, and narrative consequences)
- Extracted session notes (what has actually happened at the table with each NPC/faction)
- World context files (optional faction overviews, location notes)

Produce a single authoritative planning.md with these sections:

## Threat Tracker
A compact table of all active threat arc scores:
| Score Name | NPC/Faction | Current Value | Next Threshold | What Triggers Next |

## NPC Dossiers
One subsection per NPC with:
- Current location and status
- Active plans and immediate goals
- What the party knows vs. what is hidden
- Key relationships and leverage points
- Current arc score value (if applicable) and what unlocks next

## Faction States
One subsection per faction with:
- Current goals and active operations
- Key members and their roles
- Relationship to the party and other factions
- Resources and vulnerabilities

## Active Plots
Threads currently in motion, ordered by urgency. For each:
- What is happening
- Timeline or trigger conditions
- How it intersects with the party

## DM Notes
Foreshadowing opportunities, convergence points between plot threads, \
and NPCs whose paths are about to cross.

Rules:
- NPC dossiers take precedence over session notes for definitive facts.
- Session notes take precedence for current emotional state and recent actions.
- Arc score documents define the mechanics; session notes track the current value.
- Be concise. This is a quick-reference document used during live play.
- Do not invent anything not present in the source material.
- Output only the planning document. No preamble or commentary.
"""


BUILD_EXTRACT_SYSTEM = """\
You are extracting information about named NPCs from D&D session summary notes.

For each named NPC that appears in this text, create a section using their full name as the heading. Include everything relevant:
- What they did, said, or ordered
- Where they appeared and under what circumstances
- Motivations, plans, or secrets revealed
- Their relationships with the party and other characters
- Any arc score events (e.g. Brundar's Echo increasing, Kraken Society Echoes)
- Current status or last known whereabouts

Rules:
- Use ## Full NPC Name as the heading for each NPC (one ## per NPC, no sub-headings)
- Only include named NPCs — not player characters, not generic "bandits" or "guards"
- Be specific: name the session event, not a generic description
- If an NPC doesn't appear in this chunk at all, omit them entirely
- Output only the NPC sections. No preamble, no summary.
"""

BUILD_SYNTHESIZE_SYSTEM = """\
You are writing an NPC dossier for a D&D campaign GM.

You will receive raw session notes about a single NPC, extracted from multiple sessions. \
Synthesize these into a clean, organized dossier for use during session prep.

Structure:

# [NPC Full Name]

## Identity
- Role / title / faction affiliation
- First appearance and how the party met them

## Personality & Motivations
- Core goals and drives
- Personality traits demonstrated through play (2–4 sentences)

## History with the Party
Chronological summary of significant interactions and events at the table.

## Current Status
- Last known location and what they were doing
- Active plans or operations in progress
- What the party knows vs. what remains hidden

## Relationships
Key relationships with other NPCs, factions, and the party members individually.

## Arc Score Events
If applicable: events that triggered arc score changes, and the direction (increase/decrease).

Rules:
- Only include information present in the source notes — do not invent anything.
- Be concise. This document is read quickly during live play.
- Output only the dossier. No preamble or commentary.
"""


def chunk_text(text: str, chunk_size: int) -> list[str]:
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


def run_extract(client, summaries_text: str, chunk_size: int, model: str, extract_dir: Path) -> list[Path]:
    chunks = chunk_text(summaries_text, chunk_size)
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


def run_build_dossiers(
    client, summaries_text: str, chunk_size: int, model: str, extract_dir: Path, dossier_dir: Path
) -> list[Path]:
    """Two-phase dossier builder: extract per-chunk → aggregate by NPC → synthesize each dossier."""

    # ── Phase 1: extract NPC mentions from each chunk ─────────────────────────
    chunks = chunk_text(summaries_text, chunk_size)
    total = len(chunks)
    print(f"  {total} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")

    extract_dir.mkdir(parents=True, exist_ok=True)

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"dossier_extract_{i:03d}.md"
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            continue
        print(f"  [{i}/{total}] Extracting NPC mentions ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, BUILD_EXTRACT_SYSTEM, chunk, model)
        print("  " + "─" * 56)
        out_file.write_text(result, encoding="utf-8")
        print(f"  Saved: {out_file.name}\n")

    # ── Phase 2: aggregate sections by NPC name ───────────────────────────────
    npc_excerpts: dict[str, list[str]] = {}
    for extract_file in sorted(extract_dir.glob("dossier_extract_*.md")):
        content = extract_file.read_text(encoding="utf-8")
        # split on lines that start with "## "
        sections = re.split(r"(?m)^## ", content)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            lines = section.splitlines()
            npc_name = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            if npc_name and body:
                npc_excerpts.setdefault(npc_name, []).append(body)

    if not npc_excerpts:
        print("  No NPC sections found in extractions.", file=sys.stderr)
        return []

    print(f"\n  Found {len(npc_excerpts)} NPC(s): {', '.join(sorted(npc_excerpts))}\n")

    # ── Phase 3: synthesize each NPC into a dossier file ─────────────────────
    dossier_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    for npc_name in sorted(npc_excerpts):
        slug = re.sub(r"[^a-z0-9]+", "_", npc_name.lower()).strip("_")
        out_file = dossier_dir / f"{slug}.md"
        if out_file.exists():
            print(f"  Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        excerpts = npc_excerpts[npc_name]
        raw_notes = (
            f"# Raw session notes: {npc_name}\n\n"
            + "\n\n---\n\n".join(excerpts)
        )
        print(f"  Synthesizing: {npc_name} ({len(excerpts)} excerpt(s), {len(raw_notes):,} chars)...")
        print("  " + "─" * 56)
        dossier = stream_api(client, BUILD_SYNTHESIZE_SYSTEM, raw_notes, model)
        print("  " + "─" * 56)
        out_file.write_text(dossier.strip() + "\n", encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize(
    client,
    npc_files: list[Path],
    arc_score_files: list[Path],
    extract_files: list[Path],
    context_files: list[Path],
    model: str,
) -> str:
    parts = []

    if npc_files:
        dossiers = "\n\n---\n\n".join(
            f"<!-- NPC dossier: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
            for f in npc_files
        )
        parts.append(f"# NPC DOSSIERS\n\n{dossiers}")

    if arc_score_files:
        arc_scores = "\n\n---\n\n".join(
            f"<!-- Threat arc score: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
            for f in arc_score_files
        )
        parts.append(f"# THREAT ARC SCORE MECHANICS\n\n{arc_scores}")

    if extract_files:
        extractions = "\n\n---\n\n".join(
            f"<!-- Session extract: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
            for f in sorted(extract_files)
        )
        parts.append(f"# SESSION EXTRACTIONS\n\n{extractions}")

    if context_files:
        context = "\n\n---\n\n".join(
            f"<!-- World context: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
            for f in context_files
        )
        parts.append(f"# WORLD CONTEXT\n\n{context}")

    user_prompt = "\n\n===\n\n".join(parts)
    print(f"  Synthesizing ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, SYNTHESIZE_SYSTEM, user_prompt, model)
    print("  " + "─" * 56)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a planning.md from NPC dossiers, threat arc scores, and session summaries."
    )
    parser.add_argument("--npc", "-n", nargs="+", metavar="FILE", default=[],
                        help="NPC dossier file(s)")
    parser.add_argument("--arc-scores", "-a", nargs="+", metavar="FILE", default=[],
                        help="Threat arc score document(s) (e.g. brundar_echo.md, kraken_echoes.md)")
    parser.add_argument("--summaries", "-s", metavar="FILE",
                        help="Session summaries file (large, will be chunked)")
    parser.add_argument("--context", "-c", nargs="+", metavar="FILE", default=[],
                        help="Optional world context files (factions, locations, etc.)")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Where to save the planning document (required unless --build-dossiers)")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load session extractions "
                             "(default: <output_dir>/planning_extractions/ or ./planning_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir")
    parser.add_argument("--build-dossiers", action="store_true",
                        help="Build individual per-NPC dossier files from --summaries instead of "
                             "producing planning.md (save to --dossier-dir, review/edit, then run "
                             "the normal synthesize pass with --npc)")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Where to save per-NPC dossier files when using --build-dossiers "
                             "(default: ./npcs/ relative to CWD)")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.build_dossiers and not args.summaries:
        print("Error: --build-dossiers requires --summaries", file=sys.stderr)
        sys.exit(1)
    if not args.build_dossiers and not args.output:
        print("Error: --output is required (unless using --build-dossiers)", file=sys.stderr)
        sys.exit(1)
    if not args.build_dossiers and not args.npc and not args.summaries and not args.synthesize_only:
        print("Error: provide at least --npc or --summaries", file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir and not args.npc:
        print("Error: --synthesize-only requires --extract-dir or --npc", file=sys.stderr)
        sys.exit(1)

    npc_files = [Path(f).expanduser().resolve() for f in args.npc]
    arc_score_files = [Path(f).expanduser().resolve() for f in args.arc_scores]
    context_files = [Path(f).expanduser().resolve() for f in args.context]

    for f in npc_files + arc_score_files + context_files:
        if not f.exists():
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    client = make_client()

    # ── Build-dossiers mode ───────────────────────────────────────────────────
    if args.build_dossiers:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        base = Path(args.output).expanduser().resolve().parent if args.output else Path.cwd()
        extract_dir = (
            Path(args.extract_dir).expanduser().resolve()
            if args.extract_dir
            else base / "planning_extractions"
        )
        dossier_dir = (
            Path(args.dossier_dir).expanduser().resolve()
            if args.dossier_dir
            else Path.cwd() / "npcs"
        )
        print(f"\n[Build dossiers | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        saved = run_build_dossiers(client, summaries_text, args.chunk_size, args.model, extract_dir, dossier_dir)
        print("=" * 60)
        print(f"\n{len(saved)} dossier file(s) saved to: {dossier_dir}")
        print("\nNext steps:")
        print("  1. Review and edit the dossier files")
        print(f"  2. Run the planning synthesize pass:")
        npc_args = " ".join(f"--npc {f.name}" for f in saved[:3])
        if len(saved) > 3:
            npc_args += " ..."
        print(f"     python planning.py {npc_args} --output planning.md")
        return

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "planning_extractions"
    )

    # ── Extract pass ──────────────────────────────────────────────────────────
    if args.summaries and not args.synthesize_only:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        print(f"\n[Pass 1: Extract NPC/faction info | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract(client, summaries_text, args.chunk_size, args.model, extract_dir)
        print(f"Extractions saved to: {extract_dir}")
    elif args.synthesize_only:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only | {len(extract_files)} extraction(s) from {extract_dir}]")
    else:
        extract_files = []

    # ── Synthesize pass ───────────────────────────────────────────────────────
    sources = []
    if npc_files:
        sources.append(f"{len(npc_files)} NPC dossier(s)")
    if arc_score_files:
        sources.append(f"{len(arc_score_files)} arc score doc(s)")
    if extract_files:
        sources.append(f"{len(extract_files)} session extraction(s)")
    if context_files:
        sources.append(f"{len(context_files)} context file(s)")

    print(f"\n[Pass 2: Synthesize | {', '.join(sources)} | model: {args.model}]")
    print("=" * 60)
    planning_doc = run_synthesize(client, npc_files, arc_score_files, extract_files, context_files, args.model)
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(planning_doc.strip() + "\n", encoding="utf-8")
    print(f"\nPlanning document saved to: {output}")
    if extract_files and not args.synthesize_only:
        print(f"Extractions kept in: {extract_dir}")
        print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
