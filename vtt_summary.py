#!/usr/bin/env python3
"""Generate a D&D session summary from a Zoom VTT transcript file.

Parses Zoom's WebVTT format, strips timestamps and cue numbers to produce
clean speaker dialogue, then runs a two-pass extract → synthesize pipeline
to generate a structured session summary.

Usage:
  python vtt_summary.py session.vtt --output docs/summaries/session_12.md
  python vtt_summary.py session.vtt -o session_12.md --date "2026-03-15"
  python vtt_summary.py session.vtt --synthesize-only --extract-dir vtt_extractions/ -o out.md

Output is a structured markdown session summary suitable for:
  - Appending to a session summaries file (fed to distill.py, campaign_state.py, etc.)
  - Direct review after the session

Options:
  --date DATE           Session date to include in the summary header (default: today)
  --session-name NAME   Session label (e.g. "Session 12 — Icespire Hold")
  --chunk-size CHARS    Characters per extract chunk (default: 50000)
  --extract-dir DIR     Where to save/load extract files (default: <output_dir>/vtt_extractions/)
  --synthesize-only     Skip extract, synthesize from existing files in --extract-dir
  --no-log              Skip saving a log file
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from campaignlib import make_client, stream_api, save_log


EXTRACT_SYSTEM_BASE = """\
You are reading a portion of a Zoom transcript from a D&D tabletop RPG session.
The speakers are the players (PCs) and the Game Master (GM/DM).
{context_section}{reference_section}
Extract a concise set of structured notes covering everything that happened in this portion:

## Events
Key story events, decisions, and plot developments. One bullet per event.
Be specific — include names, locations, outcomes.

## NPC Interactions
Every named NPC that was spoken to or about: what was said or decided, what was revealed.

## PC Actions & Decisions
Significant player character choices, skill checks, combat outcomes, discoveries.

## Out-of-Character Notes
Any meta decisions about the campaign (schedule, house rules, retcons) if present.

Rules:
- Do not invent anything not present in the transcript.
- Be exhaustive — it is better to over-extract than to miss something.
- Ignore crosstalk, laughter, and off-topic chatter unless it contains a game decision.
- Use the campaign context above to correctly identify NPC names and existing plot threads.
- Output only the structured notes. No preamble or commentary.
"""

ROLEPLAY_EXTRACT_SYSTEM_BASE = """\
You are reading a portion of a Zoom transcript from a D&D tabletop RPG session.
The speakers are the players (PCs) and the Game Master (GM/DM).
{context_section}
{reference_section}
Your job is to find the VERBATIM DIALOGUE for every significant moment in this transcript
portion.

{priority_block}

WHAT TO EXTRACT:
- In-character dialogue: a player speaking AS their character (not about them)
- NPC portrayals: the GM giving voice to an NPC — their tone, speech patterns, threats, pleas
- Dramatic exchanges: back-and-forth roleplay between a PC and an NPC or between PCs
- Character-defining moments: a decision, revelation, or action that reveals who the character is
- Emotional beats: fear, grief, triumph, betrayal, humour — moments with emotional weight
- Memorable lines: a turn of phrase, a threat, a promise, a punchline that stands out
- In-character jokes, item interactions, and moments that SOUND mechanical but have narrative
  weight (e.g. "This is not my necklace. I am holding it until we find its rightful owner.")

For each roleplay moment, record:
- WHO is speaking (player name / character name if known, or "GM as [NPC name]")
- The QUOTED TEXT or a close paraphrase if the exact wording is unclear
- A brief NOTE on the context (one sentence: what was happening)

Format each moment as:

**[Speaker as Character/NPC]** — *[context note]*
> [quoted or paraphrased dialogue]

Group related moments together if they form a single exchange.

Rules:
- Prefer exact quotes over paraphrasing. If you must paraphrase, mark it with (paraphrase).
- Ignore purely mechanical talk ONLY when it has no narrative or character weight.
  If a player discusses an item, a spell, or a rule in a way that reveals character
  (possessiveness, humour, fear, curiosity), capture it.
- Ignore out-of-character scheduling and rules lookups.
- Do not invent dialogue. Only record what is in the transcript.
- Output only the roleplay moments. No preamble or commentary.
"""

# When a reference summary (GMassistant) is available, the extraction is anchored
# on it — find dialogue for its scenes first, then catch anything it missed.
_ROLEPLAY_PRIORITY_WITH_REF = """\
PRIORITY ORDER:
1. ANCHOR on the reference summary above. For every scene and character moment it describes,
   find the corresponding verbatim dialogue in this transcript chunk. The reference summary
   was generated from this same transcript, so if it mentions something, the dialogue IS here.
   Look carefully — it may appear as casual or mechanical-sounding talk.
2. BONUS: after covering all referenced moments, scan for any significant exchanges the
   reference summary missed — side conversations that turned into character moments,
   throwaway jokes with narrative weight, quiet interactions between PCs."""

_ROLEPLAY_PRIORITY_NO_REF = """\
Scan the transcript for every moment worth narrating. Cast a wide net — it is better to
over-extract than to miss a quiet character moment or an in-character joke buried in
mechanical discussion."""

ROLEPLAY_SYNTHESIZE_SYSTEM_BASE = """\
You are a D&D session archivist. You will receive roleplay moment extractions from a single
session's Zoom transcript. Your job is to synthesize them into a Roleplay Highlights document.
{context_section}
The document has two purposes:
1. A record of memorable roleplay for the players and GM to look back on
2. A Voice Keeper reference — character voice examples and speech patterns useful for future
   session prep (feeding to the Voice Keeper agent or directly to encounter design)

Format:
# Roleplay Highlights — {session_name}

## Character Voices
One subsection per PC and significant NPC. For each: 2–3 bullet points describing their voice
and personality as expressed this session, followed by 1–3 of their most representative quotes.

### [Character/NPC Name]
- Voice notes (speech patterns, register, emotional tone)
> "memorable quote"

## Memorable Exchanges
The best back-and-forth roleplay moments — dramatic, funny, or emotionally significant dialogues.
For each: a one-line scene-setter, then the exchange as a short script.

## Standout Moments
Individual character moments that defined the session — a decision, a revelation, a speech.
One bullet per moment, with the quote or paraphrase.

## Voice Keeper Notes
A concise section for future session prep use:
- Key NPC speech patterns the GM should maintain
- PC emotional states and relationships that should inform NPC dialogue toward them
- Any promises, threats, or vows made in character that future encounters should reference

Write with clarity. Quotes should feel alive on the page.
Output only the Roleplay Highlights document. No preamble or commentary.
"""

SYNTHESIZE_SYSTEM_BASE = """\
You are a D&D session chronicler. You will receive structured extraction notes compiled
from a single session's Zoom transcript. Your job is to synthesize them into a clean,
readable session summary that a GM can use for future session prep.
{context_section}
The summary should:
- Open with a one-paragraph narrative overview of what happened
- Cover all major story beats, NPC interactions, and PC decisions
- Note what changed relative to existing campaign context (new revelations, status changes, etc.)
- Note any unresolved threads or open questions
- Capture any retcons, rule clarifications, or out-of-character decisions
- End with a "Next Session Setup" section: the immediate situation the party is in

Format:
# {session_name}

## Overview
(one paragraph narrative)

## Session Events
(bullet list of key events in chronological order)

## NPC Interactions
(named NPCs with what happened)

## Open Threads
(unresolved plot threads and open questions)

## Out-of-Character
(any meta decisions — skip section if none)

## Next Session Setup
(one short paragraph: where are the PCs, what is immediately at stake)

Write clearly and concisely. This document will be used as a session record and
fed to other AI tools as campaign context. Precision matters.
Output only the session summary document. No preamble or commentary.
"""


def parse_vtt(text: str) -> str:
    """Strip VTT headers, cue numbers, and timestamps. Return clean speaker dialogue."""
    lines = text.splitlines()
    dialogue: list[str] = []
    # Patterns to skip
    header_re = re.compile(r"^WEBVTT", re.IGNORECASE)
    timestamp_re = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}")
    cue_re = re.compile(r"^\d+\s*$")
    note_re = re.compile(r"^NOTE\b", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if header_re.match(stripped):
            continue
        if timestamp_re.match(stripped):
            continue
        if cue_re.match(stripped):
            continue
        if note_re.match(stripped):
            continue
        dialogue.append(stripped)

    return "\n".join(dialogue)


def chunk_text(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks at newline boundaries near chunk_size chars."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        # Try to break at a newline
        boundary = text.rfind("\n", start, end)
        if boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return [c.strip() for c in chunks if c.strip()]


def build_context_section(context_text: str) -> str:
    """Return a formatted context block for injection into system prompts."""
    if not context_text.strip():
        return "\n"
    return (
        "\n\n# CAMPAIGN CONTEXT\n"
        "The following documents describe the existing campaign state. "
        "Use them to correctly identify NPC names, completed events, and ongoing plot threads.\n\n"
        f"{context_text.strip()}\n\n"
        "# END CAMPAIGN CONTEXT\n\n"
    )


def build_reference_section(reference_text: str) -> str:
    """Return a formatted reference summary block for injection into system prompts."""
    if not reference_text.strip():
        return ""
    return (
        "\n\n# SESSION REFERENCE (authoritative — generated from this same transcript)\n"
        "This is the definitive account of what happened in this session. Every scene and "
        "character moment described below occurred in the transcript you are reading. "
        "Your primary job is to find the verbatim dialogue for these moments.\n\n"
        f"{reference_text.strip()}\n\n"
        "# END SESSION REFERENCE\n\n"
    )


def run_extract(client, text: str, chunk_size: int, model: str,
                extract_dir: Path, context_text: str = "",
                system_base: str = None,
                reference_text: str = "") -> list[Path]:
    chunks = chunk_text(text, chunk_size)
    total = len(chunks)
    print(f"  {total} chunk(s) to process (chunk size: {chunk_size:,} chars)\n")

    extract_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    base = system_base if system_base is not None else EXTRACT_SYSTEM_BASE
    system = base.replace("{context_section}", build_context_section(context_text))
    # Roleplay prompt has {reference_section} and {priority_block} placeholders;
    # summary prompt doesn't — the replacements are no-ops for it.
    has_ref = bool(reference_text.strip())
    system = system.replace("{reference_section}", build_reference_section(reference_text))
    system = system.replace("{priority_block}",
                            _ROLEPLAY_PRIORITY_WITH_REF if has_ref
                            else _ROLEPLAY_PRIORITY_NO_REF)

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"extract_{i:03d}.md"
        if out_file.exists():
            print(f"  [{i}/{total}] Skipping (already exists): {out_file.name}")
            saved.append(out_file)
            continue

        print(f"  [{i}/{total}] Extracting chunk ({len(chunk):,} chars)...")
        print("  " + "─" * 56)
        result = stream_api(client, system, chunk, model)
        print("  " + "─" * 56)

        out_file.write_text(result, encoding="utf-8")
        saved.append(out_file)
        print(f"  Saved: {out_file.name}\n")

    return saved


def run_synthesize(client, extract_files: list[Path], model: str,
                   session_name: str, context_text: str = "",
                   system_base: str = None, reference_text: str = "") -> str:
    combined = [
        f"<!-- Source: {f.name} -->\n\n{f.read_text(encoding='utf-8').strip()}"
        for f in sorted(extract_files)
    ]
    user_prompt = "\n\n---\n\n".join(combined)
    if reference_text.strip():
        user_prompt += (
            "\n\n---\n\n"
            "## Reference Summaries\n\n"
            "The following summaries were produced by other tools (GMassistant, Saga20, etc.) "
            "for the same session. Cross-reference them against the extraction notes above. "
            "Incorporate any events, NPC interactions, or decisions that appear here but are "
            "absent from the extractions. Note any significant discrepancies.\n\n"
            + reference_text.strip()
        )
    base = system_base if system_base is not None else SYNTHESIZE_SYSTEM_BASE
    system = (base
              .replace("{session_name}", session_name)
              .replace("{context_section}", build_context_section(context_text)))
    print(f"  Synthesizing {len(extract_files)} extraction(s) ({len(user_prompt):,} chars total)...")
    print("  " + "─" * 56)
    result = stream_api(client, system, user_prompt, model, max_tokens=8096)
    print("  " + "─" * 56)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a D&D session summary from a Zoom VTT transcript."
    )
    parser.add_argument("input", nargs="?", metavar="FILE",
                        help="Zoom .vtt transcript file (not needed with --synthesize-only)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the session summary")
    parser.add_argument("--date", default=str(date.today()), metavar="DATE",
                        help="Session date, e.g. 2026-03-15 (default: today)")
    parser.add_argument("--session-name", default="", metavar="NAME",
                        help='Session label, e.g. "Session 12 — Icespire Hold"')
    parser.add_argument("--chunk-size", type=int, default=50000, metavar="CHARS",
                        help="Max characters per extract chunk (default: 50000)")
    parser.add_argument("--roleplay-output", metavar="FILE",
                        help="Also generate a Roleplay Highlights document (character voices, "
                             "memorable exchanges, Voice Keeper notes). "
                             "e.g. docs/summaries/session_12_roleplay.md")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save/load intermediate extractions "
                             "(default: <output_dir>/vtt_extractions/)")
    parser.add_argument("--roleplay-extract-dir", metavar="DIR", default=None,
                        help="Where to save/load roleplay extractions "
                             "(default: <output_dir>/vtt_roleplay_extractions/)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip extraction, synthesize from existing files in --extract-dir "
                             "(applies to both summary and roleplay passes)")
    parser.add_argument("--context", nargs="+", metavar="FILE",
                        help="Campaign context files to include (e.g. campaign_state.md "
                             "world_state.md party.md). Helps identify NPCs and track changes.")
    parser.add_argument("--reference-summaries", nargs="+", metavar="FILE",
                        help="Pre-existing summaries (GMassistant recap, Saga20 summary, etc.) "
                             "to cross-reference during synthesis. The model will incorporate "
                             "anything present in these that is missing from the VTT extractions.")
    parser.add_argument("--no-log", action="store_true",
                        help="Skip saving a log file")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    if args.synthesize_only and not args.extract_dir:
        print("Error: --synthesize-only requires --extract-dir", file=sys.stderr)
        sys.exit(1)
    if not args.synthesize_only and not args.input:
        print("Error: input .vtt file required unless --synthesize-only", file=sys.stderr)
        sys.exit(1)

    output = Path(args.output).expanduser().resolve()
    if output.is_dir():
        print(f"Error: --output must be a file path, not a directory: {output}", file=sys.stderr)
        print(f"  Try: --output {output / 'session_summary.md'}", file=sys.stderr)
        sys.exit(1)
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "vtt_extractions"
    )
    roleplay_extract_dir = (
        Path(args.roleplay_extract_dir).expanduser().resolve()
        if args.roleplay_extract_dir
        else output.parent / "vtt_roleplay_extractions"
    )
    session_name = args.session_name or f"Session — {args.date}"

    # Load optional context files
    context_text = ""
    if args.context:
        parts = []
        for ctx_path in args.context:
            p = Path(ctx_path).expanduser()
            if not p.exists():
                print(f"Warning: context file not found, skipping: {p}", file=sys.stderr)
                continue
            parts.append(f"## {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
        if parts:
            context_text = "\n\n---\n\n".join(parts)
            print(f"[Context: {len(args.context)} file(s), {len(context_text):,} chars]")

    # Load optional reference summaries (GMassistant recap, Saga20, etc.)
    reference_text = ""
    if args.reference_summaries:
        parts = []
        for ref_path in args.reference_summaries:
            p = Path(ref_path).expanduser()
            if not p.exists():
                print(f"Warning: reference summary not found, skipping: {p}", file=sys.stderr)
                continue
            parts.append(f"### {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
        if parts:
            reference_text = "\n\n---\n\n".join(parts)
            print(f"[Reference summaries: {len(parts)} file(s), {len(reference_text):,} chars]")

    client = make_client()

    if not args.synthesize_only:
        vtt_path = Path(args.input).expanduser()
        if not vtt_path.exists():
            print(f"Error: file not found: {vtt_path}", file=sys.stderr)
            sys.exit(1)

        raw = vtt_path.read_text(encoding="utf-8")
        print(f"\n[Parsing VTT | {len(raw):,} raw chars | {vtt_path.name}]")
        dialogue = parse_vtt(raw)
        print(f"  → {len(dialogue):,} chars of clean dialogue\n")
        if not dialogue.strip():
            print(f"Error: no dialogue found in VTT file: {vtt_path.name}", file=sys.stderr)
            sys.exit(1)

        print(f"[Pass 1: Extract (summary) | model: {args.model}]")
        print("=" * 60)
        extract_files = run_extract(client, dialogue, args.chunk_size, args.model,
                                    extract_dir, context_text,
                                    reference_text=reference_text)
        if not extract_files:
            print("Error: no chunks were extracted — dialogue may be too short.", file=sys.stderr)
            sys.exit(1)
        print(f"Extractions saved to: {extract_dir}")
    else:
        extract_files = sorted(extract_dir.glob("extract_*.md"))
        if not extract_files:
            print(f"Error: no extract_*.md files found in {extract_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"\n[Synthesize-only mode | {len(extract_files)} extraction(s) from {extract_dir}]")

    print(f"\n[Pass 2: Synthesize (summary) | model: {args.model}]")
    print("=" * 60)
    summary = run_synthesize(client, extract_files, args.model, session_name, context_text,
                             reference_text=reference_text)
    print("=" * 60)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(summary.strip() + "\n", encoding="utf-8")
    print(f"\nSession summary saved to: {output}")

    # ── Roleplay pass ─────────────────────────────────────────────────────────
    log_sections = [("Session Summary", summary)]

    if args.roleplay_output:
        roleplay_output = Path(args.roleplay_output).expanduser().resolve()

        if not args.synthesize_only:
            print(f"\n[Pass 3: Extract (roleplay) | model: {args.model}]")
            print("=" * 60)
            roleplay_extract_files = run_extract(
                client, dialogue, args.chunk_size, args.model,
                roleplay_extract_dir, context_text,
                system_base=ROLEPLAY_EXTRACT_SYSTEM_BASE,
                reference_text=reference_text,
            )
            print(f"Roleplay extractions saved to: {roleplay_extract_dir}")
        else:
            roleplay_extract_files = sorted(roleplay_extract_dir.glob("extract_*.md"))
            if not roleplay_extract_files:
                print(f"Warning: no roleplay extractions found in {roleplay_extract_dir} "
                      f"— skipping roleplay pass.", file=sys.stderr)
                roleplay_extract_files = []

        if roleplay_extract_files:
            print(f"\n[Pass 4: Synthesize (roleplay) | model: {args.model}]")
            print("=" * 60)
            roleplay_doc = run_synthesize(
                client, roleplay_extract_files, args.model, session_name, context_text,
                system_base=ROLEPLAY_SYNTHESIZE_SYSTEM_BASE,
            )
            print("=" * 60)

            roleplay_output.parent.mkdir(parents=True, exist_ok=True)
            roleplay_output.write_text(roleplay_doc.strip() + "\n", encoding="utf-8")
            print(f"\nRoleplay highlights saved to: {roleplay_output}")
            log_sections.append(("Roleplay Highlights", roleplay_doc))

    if not args.no_log:
        log_dir = output.parent / "logs"
        log_file = save_log(str(log_dir), log_sections, stem="vtt_summary")
        print(f"Log saved to: {log_file}")

    print(f"\nNext steps:")
    print(f"  Append to your summaries file, then run:")
    print(f"  python campaign_state.py summaries.md --output docs/campaign_state.md")


if __name__ == "__main__":
    main()
