#!/usr/bin/env python3
"""Convert session summaries into a structured world_state lore document.

Runs in two passes:
  1. Extract — splits the input into chunks, asks Claude to pull canon facts,
     NPC states, faction states, and key events from each chunk.
  2. Synthesize — feeds all extracted notes into a final call that produces
     a coherent world_state.md.

Intermediate extractions are saved so you can re-run --synthesize-only if
the final pass fails without repeating the expensive extract pass.

Use --extract-only to stop after the extract pass so you can review and edit
the intermediate files before synthesis (recommended for large corpora).

Usage:
  python distill.py summaries.md --output world_state.md
  python distill.py summaries.md --output world_state.md --chunk-size 50000
  python distill.py summaries.md --output world_state.md --extract-only
  python distill.py --synthesize-only --extract-dir extractions/ --output world_state.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_alias_normalizer,
    client_from_args,
    CitationIdAssigner,
    find_citation_refs,
    find_uncited_bullets,
    find_unreferenced_claims,
    format_npc_roster,
    load_agent_prompt,
    find_alias_registry,
    load_alias_map,
    prepare_chunks,
    render_report,
    render_sources_section,
    render_synthesis_report,
    run_extract_pipeline,
    run_synthesize_pipeline,
    verify_citations,
    verify_id_citations,
)

# Per-bullet [cite: "..."] tags roughly double a bullet's length over the
# original 8096-token extraction default (a holdover from before distill.py
# required citations). Match the synthesis pass's ceiling instead: on the
# claude-code (subscription) backend a too-low ceiling is a hard error with
# no partial text, not a graceful truncation.
EXTRACT_MAX_TOKENS = 32000

EXTRACT_SYSTEM = load_agent_prompt("distill_extract")

SYNTHESIZE_SYSTEM = load_agent_prompt("distill_synthesize")


def check_citations(text: str, normalize, extract_files: list[Path],
                     chunk_size: int, split_chapters: str | None, extract_dir: Path) -> None:
    """Verify every `[cite: "..."]` tag in each extract file against its source
    chunk; print a summary and, if anything is flagged, write citation_report.md.

    Deterministic — no model call. Re-derives the same chunks
    run_extract_pipeline produced (same normalizer + chunk args) so each
    extract file lines up with the exact text it was extracted from.
    """
    normalized_text = normalize(text) if normalize else text
    chunks, _ = prepare_chunks(normalized_text, chunk_size, split_chapters, split_label="chapter")
    if len(chunks) != len(extract_files):
        print(f"  [citation check skipped — {len(chunks)} chunk(s) vs "
              f"{len(extract_files)} extract file(s); likely a resumed run "
              f"with mismatched chunking]")
        return

    results_by_file = {}
    total_cited = total_verified = total_uncited = 0
    for chunk, extract_file in zip(chunks, extract_files):
        extract_text = extract_file.read_text(encoding="utf-8")
        citations = verify_citations(extract_text, chunk)
        uncited = find_uncited_bullets(extract_text)
        results_by_file[extract_file.name] = (citations, uncited)
        total_cited += len(citations)
        total_verified += sum(1 for c in citations if c.verified)
        total_uncited += len(uncited)

    flagged = (total_cited - total_verified) + total_uncited
    missing_note = f", {total_uncited} bullet(s) missing a citation" if total_uncited else ""
    print(f"  Citation check: {total_verified}/{total_cited} cited claims verified{missing_note}.")
    if flagged:
        report_path = extract_dir / "citation_report.md"
        report_path.write_text(render_report(results_by_file), encoding="utf-8")
        print(f"  {flagged} flagged claim(s) for review — see {report_path}")


def check_synthesis_citations(world_state: str, known_ids: dict[int, str], extract_dir: Path) -> str:
    """Verify every citation ID in the synthesized doc against the IDs
    CitationIdAssigner actually showed the model during synthesis; print a
    summary and, if anything is flagged, write synthesis_citation_report.md.
    Returns `world_state` with a mechanically-rendered `## Sources` section
    appended for the IDs actually used — the model never spends output
    tokens reproducing quote text, so this is the only place the quotes
    re-appear in the final document.

    Deterministic — no model call, no fuzzy text matching. Synthesis can
    only ever cite an ID it was shown, never invent a new one, so this is
    exact ID lookup.
    """
    results = verify_id_citations(world_state, known_ids)
    unreferenced = find_unreferenced_claims(world_state)

    verified = sum(1 for r in results if r.verified)
    flagged = (len(results) - verified) + len(unreferenced)
    print(f"  Synthesis citation check: {verified}/{len(results)} citation IDs verified, "
          f"{len(unreferenced)} claim(s) missing a citation.")
    if flagged:
        report_path = extract_dir / "synthesis_citation_report.md"
        report_path.write_text(render_synthesis_report(results, unreferenced), encoding="utf-8")
        print(f"  {flagged} flagged item(s) for review — see {report_path}")

    used_ids = {n for _, nums in find_citation_refs(world_state) for n in nums}
    return world_state.rstrip() + "\n\n" + render_sources_section(used_ids, known_ids)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Distill the canonical timeline (master narrative bible) into a world_state lore document."
    )
    parser.add_argument("input", nargs="?",
                        help="Canonical timeline — the master narrative bible (not needed with --synthesize-only)")
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
                        help="Claude model to use")
    add_backend_args(parser)
    args = parser.parse_args()

    if args.synthesize_only and args.extract_only:
        print("Error: --synthesize-only and --extract-only are mutually exclusive",
              file=sys.stderr)
        sys.exit(1)
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

    alias_map = load_alias_map(args.dossier_dir, registry_path=find_alias_registry(Path.cwd()))
    normalize, _ = build_alias_normalizer(alias_map)
    roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    client = client_from_args(args)

    if not args.synthesize_only:
        text = Path(args.input).expanduser().read_text(encoding="utf-8")
        if not text.strip():
            print(f"Error: input file is empty: {args.input}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Pass 1: Extract | {len(text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract_pipeline(
            client, text,
            extract_system=EXTRACT_SYSTEM,
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="chapter",
            input_normalizer=normalize,
            system_suffix=roster,
            max_tokens=EXTRACT_MAX_TOKENS,
        )
        if not extract_files:
            print("Error: no chunks were extracted — input may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")
        check_citations(text, normalize, extract_files, args.chunk_size, args.split_chapters, extract_dir)

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, run:")
            print(f"  python distill.py --synthesize-only "
                  f"--extract-dir {extract_dir} --output {Path(args.output)}")
            return
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only mode | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize | model: {args.model}]")
    print("=" * 60)
    id_assigner = CitationIdAssigner()
    world_state = run_synthesize_pipeline(
        client,
        source_groups=[("", extract_files)],
        synthesize_system=SYNTHESIZE_SYSTEM,
        model=args.model,
        input_normalizer=lambda body: id_assigner(normalize(body)),
        system_suffix=roster,
    )
    print("=" * 60)
    world_state = check_synthesis_citations(world_state, id_assigner.id_to_quote, extract_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(world_state.strip() + "\n", encoding="utf-8")
    print(f"\nWorld state saved to: {output}")
    print(f"Intermediate extractions kept in: {extract_dir}")
    print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
