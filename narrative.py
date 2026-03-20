#!/usr/bin/env python3
"""Generate a first-person narrative of a D&D session driven by roleplay moments.

Runs in three passes:
  1. Plan   — reads all roleplay extractions and returns a section outline: narrator,
              chunk range, and one-sentence focus. Multiple sections can share the same
              chunks because each character only sees their own moments (pass 2).
  2. Extract — for each section, silently pulls ONLY that character's moments from the
              assigned chunks (their dialogue, reactions, emotional beats). This is what
              prevents bleed while allowing full coverage across all characters.
  3. Narrate — each section is generated in isolation from its character-specific notes
              plus the party doc and a one-line handoff from the previous narrator.

Usage:
  python narrative.py \\
      --roleplay-extract-dir vtt_roleplay_extractions/ \\
      --party docs/party.md \\
      --output docs/narratives/session_12.md

  python narrative.py \\
      --roleplay-extract-dir vtt_roleplay_extractions/ \\
      --summary session_12.md \\
      --party docs/party.md \\
      --characters "Brewbarry, Soma, Valphine, Vukradin" \\
      --session-name "Session 12 — Icespire Hold" \\
      --output docs/narratives/session_12.md \\
      --plan-only
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib import make_client, stream_api, save_log


# ── Pass 1: Planning ───────────────────────────────────────────────────────────

PLAN_SYSTEM = """\
You are planning a first-person narrative of a D&D session.

You will be given numbered roleplay extractions (Chunk 1, Chunk 2, …).
Each chunk covers a chronological slice of the session.

Your job: create one section per character so every character gets a voice.

CRITICAL: If an "Available narrators" list is provided, EVERY character on that list
must appear as the narrator of exactly one section. Do not skip anyone.

For each section:
- Assign one character from the roster as narrator
- Specify which chunks contain their moments, e.g. "chunks: 1-2"
  Chunks may overlap — multiple characters can draw from the same chunk
- Write a one-sentence FOCUS: the emotional or dramatic core of this character's experience

Rules:
- The number of sections equals the number of characters in the roster
- Order sections so the narrative flows chronologically through the session
- If a character appears throughout, assign all chunks — the extraction pass will isolate
  their specific moments from the full set
- If no roster is provided, infer the main characters from the extractions

Output ONLY the plan in this exact format — no preamble, no commentary:

## Section 1
narrator: [name]
chunks: 1-2
focus: [one sentence — the emotional/dramatic core of this character's experience]

## Section 2
narrator: [name]
chunks: 1-2
focus: [one sentence]

(one section per character — every character in the roster must appear)
"""

# ── Pass 2: Per-section character extraction ───────────────────────────────────

CHAR_EXTRACT_SYSTEM = """\
You are extracting roleplay moments for a specific character from D&D session notes.

Character: {narrator}

Your job: pull out every moment worth narrating from {narrator}'s perspective — dialogue,
action, and environment alike.

THREE TYPES OF MOMENTS — capture all of them:

1. DIALOGUE EXCHANGES
   A conversation has two sides. When {narrator} says something, include what the other
   person said — before and after — so the full exchange is present. Attribute every line.
   Quote verbatim when possible; mark reconstructions as (paraphrase).

2. ACTION BEATS
   Combat, physical challenges, feats of strength or skill — anything {narrator} did with
   their body. What happened, how it felt, what was at stake. Even if no words were spoken,
   these moments deserve narration: the swing of a weapon, a creature lunging, a desperate
   scramble over rocks, a near miss.

3. ENVIRONMENTAL & TRAVEL MOMENTS
   Crossing a glacier, descending into a dark place, feeling the cold or the wind or the
   silence. The world pressing in on a character is worth narrating — it sets the scene
   for everything else and grounds the reader in the physical reality of the moment.

For each moment, format as:

**[brief scene label — e.g. "The Drake Attack", "Crossing the Glacier"]**
[for dialogue: Speaker A: "words" / Speaker B: "words" / etc.]
[for action/environment: describe what happened and what {narrator} experienced]
[one sentence: what this moment felt like or cost]

Keep everything in chronological order. Do not skip quiet or wordless moments — they are
the texture between the dramatic exchanges. Output only the extracted moments. No preamble.
"""

# ── Pass 3: Per-section narration ─────────────────────────────────────────────

NARRATE_SYSTEM = """\
You are writing one section of a first-person D&D session narrative.

You will be given:
- The narrator's name and a one-sentence focus
- A handoff line from the previous narrator (if any)
- This character's extracted moments — their exact dialogue, reactions, and emotional beats
- A party document with backstory, personality, and relationships

Write 3–5 paragraphs of first-person narration.

THE DIALOGUE IS THE STORY. The moments list contains full exchanges — both sides of each
conversation. Write them as scenes. Every line from the exchange should appear in the text.

Good:
  Kaella leaned in close, voice dropping to almost nothing. "You know nothing, my friend.
  The true dangers ahead would make your blood run cold."
  I met her eyes. "Then tell me. All of it."
  She laughed — a short, hollow sound. "And if I do? What does that buy me?"

Bad:
  Kaella warned me about dangers I didn't understand, and I pressed her for information.

A reader should feel like they were in the room. Give them the words, both voices,
the silence between lines. Build prose around the exchanges, not in place of them.

FOCUS ON:
- Every line of dialogue from the moments list — include as many as fit naturally
- The emotional weight behind each line: why did they say that, what did it cost them
- What this character personally felt, feared, hoped for, or noticed in this moment
- How their backstory and relationships colour what they said and why

AVOID:
- Summarizing or paraphrasing lines that are already quoted — use the actual words
- Dry event recaps ("then we went to X and fought Y")
- Mechanical detail (rolls, HP, spell slots)

VOICE:
- First person, emotionally honest, distinct to this character
- The prose connecting the quoted lines should sound like this character reflecting —
  use their vocabulary, their rhythm, their way of seeing things

CONTINUITY:
- If a handoff is provided, pick up naturally from that line
- End at a natural emotional pause that another voice could follow

Output only the narration. No heading, no name prefix, no commentary.
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_file_safe(path_str: str, label: str) -> str | None:
    p = Path(path_str).expanduser()
    if not p.exists():
        print(f"Warning: {label} not found, skipping: {p}", file=sys.stderr)
        return None
    return p.read_text(encoding="utf-8")


def load_extractions(extract_dir: Path) -> list[tuple[str, str]]:
    """Return [(filename, content), …] sorted by filename."""
    files = sorted(extract_dir.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


def build_plan_prompt(extractions: list[tuple[str, str]], characters: list[str],
                      summary: str | None, party: str | None,
                      session_name: str,
                      summary_extractions: list[tuple[str, str]] | None = None) -> str:
    parts = []
    if session_name:
        parts.append(f"# Session: {session_name}")
    if characters:
        parts.append("## Available narrators\n" + "\n".join(f"- {c}" for c in characters))
    chunk_parts = [f"### Chunk {i}\n\n{content}"
                   for i, (_, content) in enumerate(extractions, 1)]
    parts.append("## Roleplay Extractions\n"
                 "(dialogue, character voice, emotional beats)\n\n"
                 + "\n\n---\n\n".join(chunk_parts))

    if summary_extractions:
        s_parts = [f"### Chunk {i}\n\n{content}"
                   for i, (_, content) in enumerate(summary_extractions, 1)]
        parts.append("## Session Extractions\n"
                     "(action detail, events, environmental context)\n\n"
                     + "\n\n---\n\n".join(s_parts))
    if summary:
        parts.append(f"## Session Summary (event context only)\n\n{summary.strip()}")
    if party:
        parts.append(f"## Party Document\n\n{party.strip()}")
    return "\n\n---\n\n".join(parts)


def parse_plan(plan_text: str, total_chunks: int) -> list[dict]:
    sections = []
    for block in re.split(r"(?m)^## Section \d+", plan_text):
        block = block.strip()
        if not block:
            continue
        section: dict = {}
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("narrator:"):
                section["narrator"] = line.split(":", 1)[1].strip()
            elif line.startswith("chunks:"):
                raw = line.split(":", 1)[1].strip()
                m = re.match(r"(\d+)\s*[-–]\s*(\d+)", raw)
                if m:
                    section["chunk_start"] = int(m.group(1))
                    section["chunk_end"]   = int(m.group(2))
                else:
                    single = re.match(r"(\d+)", raw)
                    if single:
                        n = int(single.group(1))
                        section["chunk_start"] = n
                        section["chunk_end"]   = n
            elif line.startswith("focus:"):
                section["focus"] = line.split(":", 1)[1].strip()
        if "narrator" in section and "chunk_start" in section:
            # Clamp to valid range
            section["chunk_start"] = max(1, min(section["chunk_start"], total_chunks))
            section["chunk_end"]   = max(section["chunk_start"],
                                         min(section["chunk_end"], total_chunks))
            sections.append(section)
    return sections


def build_char_extract_prompt(section: dict,
                               extractions: list[tuple[str, str]],
                               summary_extractions: list[tuple[str, str]] | None = None) -> str:
    start = section["chunk_start"] - 1
    end   = section["chunk_end"]

    parts = []

    roleplay_chunks = [f"### Chunk {start + i + 1}\n\n{content}"
                       for i, (_, content) in enumerate(extractions[start:end])]
    parts.append("## Roleplay Extractions\n"
                 "(dialogue, character voice, emotional beats — primary source)\n\n"
                 + "\n\n---\n\n".join(roleplay_chunks))

    if summary_extractions:
        summary_chunks = [f"### Chunk {start + i + 1}\n\n{content}"
                          for i, (_, content) in enumerate(summary_extractions[start:end])]
        if summary_chunks:
            parts.append("## Session Extractions\n"
                         "(action detail, events, environmental context — use for texture)\n\n"
                         + "\n\n---\n\n".join(summary_chunks))

    return "\n\n---\n\n".join(parts)


def build_narrate_prompt(narrator: str, focus: str, char_moments: str,
                          party: str | None, handoff: str) -> str:
    parts = [f"## Narrator: {narrator}\n## Focus: {focus}"]
    if handoff:
        parts.append(f"## Handoff from previous narrator\n\"{handoff}\"")
    parts.append(f"## {narrator}'s Roleplay Moments\n\n{char_moments.strip()}")
    if party:
        parts.append(f"## Party Document (voice and backstory reference)\n\n{party.strip()}")
    return "\n\n---\n\n".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a first-person D&D narrative in rotating character voices."
    )
    parser.add_argument("--roleplay-extract-dir", metavar="DIR",
                        help="vtt_roleplay_extractions/ folder — dialogue, character voice, "
                             "emotional beats.")
    parser.add_argument("--summary-extract-dir", metavar="DIR",
                        help="vtt_extractions/ folder — action detail, events, environmental "
                             "context. Combined with roleplay extractions for richer narration.")
    parser.add_argument("--roleplay", metavar="FILE",
                        help="Synthesized Roleplay Highlights (fallback if no extract dir).")
    parser.add_argument("--summary", metavar="FILE",
                        help="Session summary — event context for the planning pass only.")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — backstory, personality, relationships.")
    parser.add_argument("--characters", metavar="NAMES",
                        help='Comma-separated roster, e.g. "Brewbarry, Soma, Valphine, Vukradin".')
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the narrative.")
    parser.add_argument("--session-name", default="", metavar="NAME",
                        help='e.g. "Session 12 — Icespire Hold".')
    parser.add_argument("--plan-only", action="store_true",
                        help="Run the planning pass only and print the section outline.")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--model", default="claude-sonnet-4-20250514")
    args = parser.parse_args()

    # ── Load inputs ───────────────────────────────────────────────────────────
    extractions: list[tuple[str, str]] = []

    if args.roleplay_extract_dir:
        extract_dir = Path(args.roleplay_extract_dir).expanduser()
        extractions = load_extractions(extract_dir)
        if not extractions:
            print(f"Warning: no extract_*.md files in {extract_dir}", file=sys.stderr)
        else:
            total_chars = sum(len(c) for _, c in extractions)
            print(f"  Loaded {len(extractions)} extraction(s) ({total_chars:,} chars)")

    if not extractions and args.roleplay:
        content = load_file_safe(args.roleplay, "roleplay highlights")
        if content:
            extractions = [("roleplay_highlights.md", content)]

    if not extractions:
        print("Error: provide --roleplay-extract-dir or --roleplay", file=sys.stderr)
        sys.exit(1)

    summary_extractions: list[tuple[str, str]] = []
    if args.summary_extract_dir:
        sdir = Path(args.summary_extract_dir).expanduser()
        summary_extractions = load_extractions(sdir)
        if not summary_extractions:
            print(f"Warning: no extract_*.md files in {sdir}", file=sys.stderr)
        else:
            total_chars = sum(len(c) for _, c in summary_extractions)
            print(f"  Loaded {len(summary_extractions)} summary extraction(s) "
                  f"({total_chars:,} chars)")

    summary = load_file_safe(args.summary, "summary") if args.summary else None
    party   = load_file_safe(args.party,   "party")   if args.party   else None

    characters = (
        [c.strip() for c in args.characters.replace(",", " ").split() if c.strip()]
        if args.characters else []
    )

    client = make_client()

    # ── Pass 1: Plan ──────────────────────────────────────────────────────────
    print(f"\n[Pass 1: Plan | {len(extractions)} chunk(s) | model: {args.model}]")
    print("=" * 60)
    plan_prompt = build_plan_prompt(extractions, characters, summary, party, args.session_name,
                                    summary_extractions or None)
    plan_text = stream_api(client, PLAN_SYSTEM, plan_prompt, args.model)
    print("=" * 60)

    sections = parse_plan(plan_text, len(extractions))
    if not sections:
        print("Error: could not parse plan. Raw output:", file=sys.stderr)
        print(plan_text, file=sys.stderr)
        sys.exit(1)

    print(f"\nPlan: {len(sections)} section(s)")
    for i, s in enumerate(sections, 1):
        print(f"  {i}. {s['narrator']:15s}  chunks {s['chunk_start']}–{s['chunk_end']}  "
              f"— {s.get('focus', '')}")

    if characters:
        assigned = {s["narrator"] for s in sections}
        missing = [c for c in characters if c not in assigned]
        if missing:
            print(f"\nWarning: these characters have no section: {', '.join(missing)}")
            print("  Re-run with --plan-only to inspect the plan, or add them manually.")

    if args.plan_only:
        return

    # ── Passes 2 & 3: Extract then narrate, one section at a time ─────────────
    section_texts: list[tuple[str, str]] = []
    handoff = ""

    for i, section in enumerate(sections, 1):
        narrator = section["narrator"]
        focus    = section.get("focus", "")
        chunks   = f"chunks {section['chunk_start']}–{section['chunk_end']}"

        # Pass 2: character-specific extraction (silent)
        print(f"\n[Pass 2.{i}/{len(sections)}: Extract — {narrator} ({chunks})]")
        char_extract_system = CHAR_EXTRACT_SYSTEM.replace("{narrator}", narrator)
        char_extract_prompt = build_char_extract_prompt(section, extractions,
                                                         summary_extractions or None)
        char_moments = stream_api(client, char_extract_system, char_extract_prompt,
                                  args.model, max_tokens=2048, silent=True)
        print(f"  → {len(char_moments):,} chars of {narrator}'s moments")

        # Pass 3: narrate from character-specific moments
        print(f"[Pass 3.{i}/{len(sections)}: Narrate — {narrator}]")
        print("─" * 60)
        narrate_prompt = build_narrate_prompt(narrator, focus, char_moments, party, handoff)
        narration = stream_api(client, NARRATE_SYSTEM, narrate_prompt,
                               args.model, max_tokens=4096)
        print("─" * 60)

        narration = narration.strip()
        section_texts.append((narrator, narration))

        # Last sentence becomes the handoff for the next narrator
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

    # ── Assemble ──────────────────────────────────────────────────────────────
    doc_parts: list[str] = []
    if args.session_name:
        doc_parts.append(f"# {args.session_name}\n")
    for narrator, narration in section_texts:
        doc_parts.append(f"---\n\n## {narrator}\n\n{narration}")
    doc_parts.append("---")
    full_doc = "\n\n".join(doc_parts) + "\n"

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(full_doc, encoding="utf-8")
    print(f"\nNarrative saved to: {output}")

    if not args.no_log:
        log_sections = ([("Plan", plan_text)] +
                        [(f"Section — {n}", t) for n, t in section_texts])
        log_file = save_log(str(output.parent / "logs"), log_sections, stem="narrative")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
