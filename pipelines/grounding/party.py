#!/usr/bin/env python3
"""Generate a party.md document from character sheets, session summaries, and backstories.

Combines three sources:
  - Character sheets (.md files, one per character) — definitive stats and abilities
  - Session summaries (large file) — arc score progression, relationships, decisions
  - Backstory documents (optional, one per character) — origin context

Runs in two passes for the session summaries (same as distill.py):
  1. Extract — chunks the summaries, pulls party-relevant info from each chunk
  2. Synthesize — combines character sheets + extractions + backstories into party.md

Output behavior:
  party.md is now hand-edited downstream (session summaries and the GM
  add content the LLM does not see), so this script does NOT overwrite an
  existing --output file by default. When --output already exists it writes
  a sibling `<stem>.candidate<ext>` (e.g. `party.candidate.md`) and prints
  a diff command so the GM can manually merge the regenerated draft into
  the live document. Pass --overwrite to restore the old clobbering
  behavior (intended only when bootstrapping a fresh party.md).

Usage:
  party \\
      --character soma.md --character vukradin.md --character valphine.md \\
      --summaries "Neverwinter Expansionism and the North.md" \\
      --output docs/party.md

  party \\
      --character soma.md \\
      --summaries summaries.md \\
      --backstory soma_backstory.md \\
      --output docs/party.md

  # Preferred: per-character config so the synthesizer can't confuse which
  # arc score belongs to which PC, and characters without a formal track
  # are first-class citizens (see config/party.example.yaml).
  party \\
      --party-config config/party.yaml \\
      --summaries summaries.md \\
      --output docs/party.md

  # Skip extraction if already done
  party \\
      --character soma.md vukradin.md \\
      --synthesize-only \\
      --extract-dir docs/party_extractions \\
      --output docs/party.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    build_alias_normalizer,
    check_citations,
    check_synthesis_citations,
    CITATION_RULES_EXTRACT,
    CITATION_RULES_SYNTHESIZE,
    CITED_EXTRACT_MAX_TOKENS,
    CitationIdAssigner,
    client_from_args,
    format_npc_roster,
    load_agent_prompt,
    find_alias_registry,
    load_alias_map,
    make_client,
    run_extract_pipeline,
    run_synthesize_pipeline,
    stream_api,
)

# Import shared party config logic
from server.party_config_shared import (
    PartyCharacter,
    PartyConfig,
    load_party_config as _shared_load_party_config,
)


def load_party_config(path: Path) -> PartyConfig:
    """CLI wrapper around server.party_config_shared.load_party_config that
    prints to stderr and exits instead of raising, matching this script's
    other error-handling. See the shared function's docstring for the YAML
    shape and field semantics.
    """
    try:
        return _shared_load_party_config(path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _render_party_block(party_config: PartyConfig, input_normalizer=None) -> str:
    """Render the PARTY source group as `# PARTY` with one `## {name}`
    subsection per PC, nesting sheet / backstory / dossier / arc_score files
    with source-comment labels.

    Trackless characters get an explicit marker so the LLM doesn't
    invent an arc track or suggest creating one.
    """
    def _read(p: Path) -> str:
        body = p.read_text(encoding="utf-8").strip()
        return input_normalizer(body) if input_normalizer else body

    char_blocks: list[str] = []
    for pc in party_config.characters:
        parts = [f"## {pc.name}"]
        parts.append(f"<!-- Character sheet: {pc.sheet.name} -->\n\n{_read(pc.sheet)}")
        if pc.backstory is not None:
            parts.append(f"<!-- Backstory: {pc.backstory.name} -->\n\n{_read(pc.backstory)}")
        if pc.dossier is not None:
            parts.append(f"<!-- Ensemble dossier: {pc.dossier.name} -->\n\n{_read(pc.dossier)}")
        if pc.arc_score is not None:
            parts.append(f"<!-- Arc score mechanic: {pc.arc_score.name} -->\n\n{_read(pc.arc_score)}")
        elif pc.trackless:
            parts.append(
                "<!-- Arc score: INTENTIONALLY TRACKLESS -->\n\n"
                f"{pc.name} has no formal arc score mechanic. This is a deliberate design "
                "choice — do not invent an arc score for this character and do not suggest "
                "creating one."
            )
        char_blocks.append("\n\n".join(parts))
    return "# PARTY\n\n" + "\n\n---\n\n".join(char_blocks)


def _render_source_group(heading: str, files: list[Path], label: str,
                         input_normalizer=None) -> str:
    """Match run_synthesize_pipeline's rendering so the party-config path
    produces an equivalent user prompt for non-party groups."""
    if not files:
        return ""
    blocks = []
    for f in files:
        body = f.read_text(encoding="utf-8").strip()
        if input_normalizer:
            body = input_normalizer(body)
        blocks.append(f"<!-- {label}: {f.name} -->\n\n{body}")
    body = "\n\n---\n\n".join(blocks)
    return f"# {heading}\n\n{body}" if heading else body

EXTRACT_SYSTEM_BASE = load_agent_prompt("party_extract")

SYNTHESIZE_SYSTEM_BASE = load_agent_prompt("party_synthesize")

EXTRACT_SYSTEM = EXTRACT_SYSTEM_BASE + "\n\n" + CITATION_RULES_EXTRACT

SYNTHESIZE_SYSTEM = SYNTHESIZE_SYSTEM_BASE + "\n\n" + CITATION_RULES_SYNTHESIZE




def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a party.md from character sheets, the canonical timeline, and backstories."
    )
    parser.add_argument("--party-config", metavar="FILE", default=None,
                        help="Party config YAML mapping each PC to sheet/backstory/arc_score. "
                             "When set, --character/--backstory/--arc-scores are rejected.")
    parser.add_argument("--character", "-c", nargs="+", action="extend", metavar="FILE", default=[],
                        help="Character sheet file(s)")
    parser.add_argument("--summaries", "-s", metavar="FILE",
                        help="Canonical timeline — the master narrative bible (large, will be chunked)")
    parser.add_argument("--backstory", "-b", nargs="+", action="extend", metavar="FILE", default=[],
                        help="Backstory document(s) (optional)")
    parser.add_argument("--arc-scores", "-a", nargs="+", action="extend", metavar="FILE", default=[],
                        help="Arc score mechanic document(s), one per character (optional)")
    parser.add_argument("--context", nargs="+", action="extend", metavar="FILE", default=[],
                        help="Additional context files (e.g. campaign_state.md)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the party document. If this file already "
                             "exists, the regenerated draft is written to "
                             "<stem>.candidate<ext> next to it (so hand edits are not "
                             "clobbered) — see --overwrite.")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite --output even if it exists, instead of writing "
                             "to a sibling .candidate.md file. Use only when "
                             "bootstrapping a fresh party.md.")
    parser.add_argument("--chunk-size", type=int, default=60000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 60000)")
    parser.add_argument("--split-chapters", metavar="PREFIX", default=None,
                        help="Split summaries at lines beginning with PREFIX instead of by character "
                             "count (e.g. '# Session'). Each session becomes one extract chunk.")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load session extractions "
                             "(default: <output_dir>/party_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir")
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
    if args.party_config and (args.character or args.backstory or args.arc_scores):
        print("Error: --party-config is mutually exclusive with "
              "--character / --backstory / --arc-scores (use one or the other)",
              file=sys.stderr)
        sys.exit(1)
    if not args.party_config and not args.character and not args.summaries and not args.synthesize_only:
        print("Error: provide at least --party-config, --character, or --summaries",
              file=sys.stderr)
        sys.exit(1)
    if args.synthesize_only and not args.extract_dir and not args.character and not args.party_config:
        print("Error: --synthesize-only requires --extract-dir, --character, or --party-config",
              file=sys.stderr)
        sys.exit(1)
    if args.extract_only and not args.summaries:
        print("Error: --extract-only requires --summaries (no summaries = nothing to extract)",
              file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "party_extractions"
    )

    party_config: PartyConfig | None = None
    if args.party_config:
        party_config = load_party_config(Path(args.party_config).expanduser().resolve())

    character_files = [Path(f).expanduser().resolve() for f in args.character]
    backstory_files = [Path(f).expanduser().resolve() for f in args.backstory]
    arc_score_files = [Path(f).expanduser().resolve() for f in args.arc_scores]
    context_files = [Path(f).expanduser().resolve() for f in args.context]

    for f in character_files + backstory_files + arc_score_files + context_files:
        if not f.exists():
            print(f"Error: file not found: {f}", file=sys.stderr)
            sys.exit(1)

    alias_map = load_alias_map(args.dossier_dir, registry_path=find_alias_registry(Path.cwd()))
    normalize, _ = build_alias_normalizer(alias_map)
    roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")

    client = client_from_args(args)

    # ── Extract pass ──────────────────────────────────────────────────────────
    if args.summaries and not args.synthesize_only:
        summaries_text = Path(args.summaries).expanduser().read_text(encoding="utf-8")
        print(f"\n[Pass 1: Extract party info | {len(summaries_text):,} chars | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract_pipeline(
            client, summaries_text,
            extract_system=EXTRACT_SYSTEM,
            model=args.model,
            extract_dir=extract_dir,
            chunk_size=args.chunk_size,
            split_chapters=args.split_chapters,
            split_label="session",
            input_normalizer=normalize,
            system_suffix=roster,
            max_tokens=CITED_EXTRACT_MAX_TOKENS,
        )
        print(f"Extractions saved to: {extract_dir}")
        check_citations(summaries_text, normalize, extract_files, args.chunk_size,
                         args.split_chapters, extract_dir, tool_name="party.py")

        if args.extract_only:
            print(f"\n[Extract-only mode — stopping before synthesis]")
            print(f"Review files in: {extract_dir}")
            print(f"When ready, re-run with --synthesize-only --extract-dir {extract_dir} "
                  f"plus the same --character/--backstory/--arc-scores/--context args.")
            return
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
    if party_config:
        trackless = [pc.name for pc in party_config.characters if pc.trackless]
        with_arc = [pc.name for pc in party_config.characters if pc.arc_score]
        sources.append(f"{len(party_config.characters)} PC(s) from party config "
                       f"({len(with_arc)} with arc, {len(trackless)} trackless)")
    if character_files:
        sources.append(f"{len(character_files)} character sheet(s)")
    if extract_files:
        sources.append(f"{len(extract_files)} session extraction(s)")
    if backstory_files:
        sources.append(f"{len(backstory_files)} backstory doc(s)")
    if arc_score_files:
        sources.append(f"{len(arc_score_files)} arc score doc(s)")
    if context_files:
        sources.append(f"{len(context_files)} context file(s)")

    print(f"\n[Pass 2: Synthesize | {', '.join(sources)} | model: {args.model}]")
    print("=" * 60)
    id_assigner = CitationIdAssigner()
    cited_normalize = lambda body: id_assigner(normalize(body))
    if party_config:
        party_block = _render_party_block(party_config, input_normalizer=cited_normalize)
        extracts_block = _render_source_group("SESSION EXTRACTIONS", extract_files,
                                              "Session extract", input_normalizer=cited_normalize)
        context_block = _render_source_group("ADDITIONAL CONTEXT", context_files,
                                             "Context", input_normalizer=cited_normalize)
        parts = [p for p in (party_block, extracts_block, context_block) if p]
        if not parts:
            print("Error: no source material to synthesize.", file=sys.stderr)
            sys.exit(1)
        user_prompt = "\n\n===\n\n".join(parts)
        system_prompt = SYNTHESIZE_SYSTEM + ("\n\n" + roster if roster else "")
        if args.dump_input:
            dump_path = Path(args.dump_input).expanduser().resolve()
            dump_path.write_text(user_prompt, encoding="utf-8")
            system_path = dump_path.with_suffix(dump_path.suffix + ".system.md")
            system_path.write_text(system_prompt, encoding="utf-8")
            print(f"Dumped synthesis input: {dump_path}")
            print(f"Dumped system prompt:   {system_path}")
            if args.dump_only:
                print("[--dump-only: stopping before the API call]")
                party_doc = ""
            else:
                print(f"  Synthesizing per-character party block ({len(user_prompt):,} chars)...")
                print("  " + "─" * 56)
                party_doc = stream_api(client, system_prompt, user_prompt, args.model)
                print("  " + "─" * 56)
        else:
            print(f"  Synthesizing per-character party block ({len(user_prompt):,} chars)...")
            print("  " + "─" * 56)
            party_doc = stream_api(client, system_prompt, user_prompt, args.model)
            print("  " + "─" * 56)
    else:
        party_doc = run_synthesize_pipeline(
            client,
            source_groups=[
                ("CHARACTER SHEETS", character_files, "Character sheet"),
                ("SESSION EXTRACTIONS", extract_files, "Session extract"),
                ("BACKSTORY DOCUMENTS", backstory_files, "Backstory"),
                ("ARC SCORE MECHANICS", arc_score_files, "Arc score mechanic"),
                ("ADDITIONAL CONTEXT", context_files, "Context"),
            ],
            synthesize_system=SYNTHESIZE_SYSTEM,
            model=args.model,
            input_normalizer=cited_normalize,
            system_suffix=roster,
            dump_input=args.dump_input,
            dump_only=args.dump_only,
        )
    print("=" * 60)

    if args.dump_only:
        return

    extract_dir.mkdir(parents=True, exist_ok=True)
    party_doc = check_synthesis_citations(
        party_doc, id_assigner.id_to_quote, extract_dir,
        tool_name="party.py", flag_unreferenced=False,
    )

    # party.md is hand-edited downstream — write to a sibling candidate file
    # when the target already exists, so a regenerated draft can be merged
    # manually instead of clobbering edits the LLM never saw.
    if output.exists() and not args.overwrite:
        write_path = output.with_name(output.stem + ".candidate" + output.suffix)
        is_candidate = True
    else:
        write_path = output
        is_candidate = False

    write_path.parent.mkdir(parents=True, exist_ok=True)
    write_path.write_text(party_doc.strip() + "\n", encoding="utf-8")

    if is_candidate:
        print(f"\nCandidate party document saved to: {write_path}")
        print(f"  ({output.name} already exists — wrote to candidate to preserve hand edits)")
        print(f"  Review and merge:")
        print(f"    diff -u {output} {write_path}")
        print(f"    # or open both in your editor and merge by hand")
        print(f"  Pass --overwrite to replace {output.name} directly (bootstrap only).")
    else:
        print(f"\nParty document saved to: {write_path}")
    if extract_files:
        print(f"Extractions kept in: {extract_dir}")
        print("(Re-run with --synthesize-only to re-synthesize without re-extracting)\n")


if __name__ == "__main__":
    main()
