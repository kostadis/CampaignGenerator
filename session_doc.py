#!/usr/bin/env python3
"""Generate a D&D session document combining narrative voice with enhanced structured sections.

Runs five passes:

  1. Consistency check (silent) — compares the recap against campaign context
     documents and produces a list of errors and contradictions.

  2. Enhance structured sections — rewrites Memorable Moments, appends
     Consistency Notes, and preserves Scenes/NPCs/Locations/Items/Spells.
     The Summary is intentionally omitted here — it is replaced by passes 3–5.

  3. Narrative plan — reads roleplay extractions and assigns each character
     a chunk range and a one-sentence dramatic focus.

  4. Character extraction (silent, once per character) — pulls only that
     character's moments (dialogue, action, environment) from their assigned chunks.

  5. Narration (once per character) — writes 3–5 paragraphs of first-person
     prose from each character's extracted moments.

The final document: rotating-voice narrative sections followed by the enhanced
structured sections (Memorable Moments, Scenes, NPCs, Locations, Items, Spells,
Consistency Notes).

Usage:
  python session_doc.py session-mar \\
      --roleplay-extract-dir vtt_roleplay_extractions/ \\
      --summary-extract-dir  vtt_extractions/ \\
      --context docs/campaign_state.md docs/world_state.md docs/party.md \\
      --characters "Vukradin, Valphine, Soma, Brewbarry" \\
      --examples examples/vukradin_arrival.md examples/valphine_gnomekings.md \\
                 examples/soma_sharks.md examples/brewbarry_corbin.md \\
      --output session-doc.md
"""

import argparse
import re
import sys
from pathlib import Path

from campaignlib import make_client, stream_api, save_log


# ── Pass 1: Consistency check ──────────────────────────────────────────────────

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

# ── Pass 2: Enhance structured sections ───────────────────────────────────────

ENHANCE_SYSTEM = """\
You are enhancing the structured sections of a D&D session recap.
You will be given:
- The original recap
- Roleplay extractions — raw quoted dialogue and character moments from the session
- Session extractions — action detail, events, environmental context
- A consistency report flagging errors in the original
- (Optionally) a party document for character voice reference

Your job: produce improved versions of the NON-SUMMARY sections only.
The Summary will be replaced by a separate narrative pass — do not include it.

1. MEMORABLE MOMENTS — Keep all existing entries. Add new ones for any significant
   roleplay moment, memorable line, or dramatic beat in the extractions that isn't
   already captured. Format new entries consistently with the existing ones:
   bold description, italicised context note, blockquote for direct quotes.

2. CONSISTENCY NOTES — Append a new section at the end listing any issues from the
   consistency report that couldn't be silently fixed in the text (ambiguities,
   unresolved contradictions, things the GM should verify). Omit this section if
   there are no issues to flag.

3. ALL OTHER SECTIONS (Scenes, NPCs, Locations, Items, Spells) — Preserve exactly
   as they are. Do not rewrite, reorder, or add to them.

Output starting from ## Memorable Moments (or the first non-Summary section in the recap).
Do not include a Summary section — it is generated separately.
No preamble or commentary.
"""

# ── Pass 3: Narrative plan ─────────────────────────────────────────────────────

PLAN_SYSTEM = """\
You are planning a first-person D&D narrative in the style of a novel with rotating
character perspectives — like a book where Chapter 1 is Vukradin, Chapter 2 is Valphine,
Chapter 3 is Soma, each covering a different part of the story from their own POV.

You will be given numbered roleplay extractions (Chunk 1, Chunk 2, …).
Each chunk covers a chronological slice of the session.

Your job: divide the session into one section per character, assigning each character
a chronological portion of the session to narrate from their perspective.

CRITICAL: If an "Available narrators" list is provided, EVERY character on that list
must appear as the narrator of exactly one section. Do not skip anyone.

CRITICAL: Together, all sections must cover the ENTIRE session. Distribute the chunks
so that every chunk appears in at least one section. Do not leave any chunk uncovered.

For each section:
- Assign one narrator
- Assign the chunk range they will draw from, e.g. "chunks: 1-2"
- Write a one-sentence FOCUS on the emotional/dramatic core of this character's experience

How to divide:
- With 4 characters and 2 chunks: give 2 characters chunk 1 and 2 characters chunk 2.
  The standard distribution is 1, 1, 2, 2 — or 1, 1-2, 2, 2 if one character bridges.
- Do NOT give every character all chunks — that creates redundant coverage.
- The goal is a flowing narrative where each voice hands off to the next chronologically,
  not four characters all describing the same events.

OVERLAP RULE — read carefully:
- A character may span two chunks (e.g. "chunks: 1-2") ONLY when their single most
  important moment straddles the boundary between those chunks.
- If Character A has chunks 1-2 and Character B has chunks 2, they will BOTH narrate
  all of chunk 2 — the stone giants, the glacier, the drake, everything. That is
  redundant and wrong. Avoid it.
- Two characters should share the same chunk only when they each have ONE distinct moment
  in it, not when both are present for the entire thing.
- When in doubt, give a character the narrower range. It is better to have focused
  sections than overlapping ones.

Output ONLY the plan in this exact format — no preamble, no commentary:

## Section 1
narrator: [name]
chunks: 1
focus: [one sentence — the emotional/dramatic core of this character's experience]

## Section 2
narrator: [name]
chunks: 1
focus: [one sentence]

## Section 3
narrator: [name]
chunks: 2
focus: [one sentence]

## Section 4
narrator: [name]
chunks: 2
focus: [one sentence]

(one section per character — every character in the roster must appear —
 every chunk must be covered by at least one section)
"""

# ── Pass 3 (scene mode): Scene-by-scene plan ──────────────────────────────────

PLAN_SCENE_SYSTEM = """\
You are planning a first-person D&D narrative in the style of a novel where each
scene is narrated by a different character — like a book where one scene is Vukradin,
the next is Soma, the next is Valphine, each showing the same unfolding story from
their own eyes.

You will be given numbered roleplay extractions (Chunk 1, Chunk 2, …).
Each chunk covers a chronological slice of the session.

Your job: identify the key scenes in the session and assign one narrator to each.

CRITICAL: If an "Available narrators" list is provided:
- Use ONLY those characters as narrators. Never assign a scene to an NPC, a guest
  character, or anyone not on the list — even if they have interesting moments.
- Each character must narrate at least one scene per chunk. With 4 characters and
  2 chunks, every character should appear in chunk 1 AND in chunk 2.
- Distribute scenes as evenly as possible — aim for the same number of scenes per
  character. Do not give one character three scenes and another only one.

CRITICAL: Together, the scenes must cover the ENTIRE session chronologically.
If a "Session Scenes" checklist is provided, every scene on that list must appear
in your plan. Do not stop until all of them are assigned a narrator.

For each scene:
- Give it a short name (3–6 words)
- Assign the chunk it comes from
- Assign one narrator — the character with the most interesting or revealing perspective
  on that scene. Rotate through the roster so no character dominates.
- Write a one-sentence FOCUS on what makes this scene theirs specifically

Output ONLY the plan in this exact format — no preamble, no commentary:

## Scene 1
narrator: [name]
chunks: 1
scene: [short scene name]
focus: [one sentence — why this character narrates this scene]

## Scene 2
narrator: [name]
chunks: 1
scene: [short scene name]
focus: [one sentence]

## Scene 3
narrator: [name]
chunks: 2
scene: [short scene name]
focus: [one sentence]

(cover all major events — rotate narrators — every character must appear at least once)
"""

# ── Pass 4: Per-character extraction ──────────────────────────────────────────

CHAR_EXTRACT_SYSTEM = """\
You are extracting roleplay moments for a specific character from D&D session notes.

Character: {narrator}
{scene_block}
Your job: pull out every moment worth narrating from {narrator}'s perspective — dialogue,
action, and environment alike.

THREE TYPES OF MOMENTS — capture all of them:

1. DIALOGUE EXCHANGES
   A conversation has two sides. When {narrator} says something, include what the other
   person said — before and after — so the full exchange is present. Attribute every line.
   COPY EVERY LINE VERBATIM, exactly as it appears in the source — do not shorten,
   paraphrase, or cut mid-sentence. If a line is cut off in the source, copy what is there
   and mark it (truncated). Only mark (paraphrase) when no direct quote exists at all.

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
the texture between the dramatic exchanges.

IMPORTANT: Only extract dialogue that actually appears in the Roleplay Extractions.
Do not invent or paraphrase exchanges. If no verbatim dialogue exists for this scene,
extract action beats and environmental moments only — that is a valid output.

Output only the extracted moments. No preamble.
"""

# ── Pass 5: Per-character narration ───────────────────────────────────────────

NARRATE_SYSTEM_BASE = """\
You are writing one section of a first-person D&D session narrative.

You will be given:
- The narrator's name and a one-sentence focus
{scene_scope_line}- A handoff line from the previous narrator (if any)
- This character's extracted moments — their exact dialogue, reactions, and emotional beats
- A party document with backstory, personality, and relationships
{examples_block}
{length_instruction}
Every significant moment in the extracted list should appear in the text.

{dialogue_instruction}

FOCUS ON:
- The emotional weight of each moment: why did they do or say that, what did it cost them
- What this character personally felt, feared, hoped for, or noticed in this moment
- How their backstory and relationships colour what they said and why

ALLOW:
- Non-linear structure — flashbacks, digressions, a character's mind drifting
- The narrator's voice intruding on the action ("He tries not to stare...")
- Humour, irony, self-deprecation — if that fits the character
- Short, punchy paragraphs and sentence fragments for rhythm
- Dates or scene headers if they help orient the reader

AVOID:
- Summarizing or paraphrasing lines that are already quoted — use the actual words
- Dry event recaps ("then we went to X and fought Y")
- Mechanical detail (rolls, HP, spell slots)
- Generic fantasy prose that could belong to any character

VOICE:
- First person, emotionally honest, distinctly this character — not a generic narrator
- The prose between quoted lines should sound like this character reflecting —
  use their vocabulary, their rhythm, their particular way of seeing the world
- The Party Document is the authoritative source for each character's class, abilities,
  and role. Never infer class from the moments list or generic D&D archetypes.

CONTINUITY:
- If a handoff is provided, pick up naturally from that line
- End at a natural emotional pause that another voice could follow

Output only the narration. No heading, no name prefix, no commentary.
"""

EXAMPLES_BLOCK = """\
- Style reference examples showing the voice, structure, and tone to aim for

STYLE REFERENCE — HANDCRAFTED EXAMPLES:
Study these carefully. They show what good looks like: the mix of internal monologue and
dialogue, the non-linear structure, the humour, the character-specific voice, the way
the narrator's perspective colours everything. Match this quality and style.

{examples}

END OF STYLE REFERENCE
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_character_roster(party_text: str) -> str:
    """Parse party.md and return a compact name → class list for prompt injection."""
    roster = []
    current_name: str | None = None
    for line in party_text.splitlines():
        m = re.match(r'^## (.+)$', line.strip())
        if m:
            current_name = m.group(1).strip()
        elif current_name:
            cm = re.match(r'^\*\*(.+\d+.+)\*\*$', line.strip())
            if cm:
                roster.append(f"- {current_name}: {cm.group(1)}")
                current_name = None
    return "\n".join(roster)


def load_voice_files(voice_dir: Path) -> dict[str, str]:
    """Load per-character voice files from a directory.

    Looks for files named {character_name}_voice.md or {character_name}.md
    (case-insensitive). Returns a dict mapping lowercased character name to content.
    """
    voices: dict[str, str] = {}
    for f in voice_dir.glob("*.md"):
        stem = f.stem.lower()
        # Strip trailing _voice suffix if present
        key = stem.removesuffix("_voice")
        voices[key] = f.read_text(encoding="utf-8").strip()
    return voices


def get_voice_note(voices: dict[str, str], narrator: str) -> str | None:
    """Look up a voice note for a narrator by case-insensitive name match."""
    key = narrator.lower().split()[0]  # match on first name
    return voices.get(key) or voices.get(narrator.lower())


def load_extractions(path: Path) -> list[tuple[str, str]]:
    files = sorted(path.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


def format_extractions(extractions: list[tuple[str, str]], heading: str) -> str:
    parts = [f"### Chunk {i}\n\n{content}"
             for i, (_, content) in enumerate(extractions, 1)]
    return f"## {heading}\n\n" + "\n\n---\n\n".join(parts)


DIALOGUE_INSTRUCTION_FULL = """\
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
the silence between lines. Build prose around the exchanges, not in place of them.\
"""

DIALOGUE_INSTRUCTION_CONDITIONAL = """\
USE DIALOGUE IF PRESENT. If the extracted moments include verbatim exchanges, write them
as full scenes with both voices — every line should appear in the text, not summarised.
If the extracted moments contain no dialogue (a wordless combat, a solo crossing, a quiet
moment of action), write from action beats and environment only.
DO NOT invent or paraphrase dialogue that is not in the extracted moments.\
"""


def build_narrate_system(examples_text: str | None, scene: str | None = None) -> str:
    if examples_text:
        block = "\n" + EXAMPLES_BLOCK.replace("{examples}", examples_text.strip()) + "\n"
    else:
        block = ""
    if scene:
        scope = (f"- The scene you are writing: **{scene}**\n"
                 f"  STOP when this scene ends. Do not continue into what happened next.\n"
                 f"  Do not summarise what came before. Do not foreshadow what comes after.\n"
                 f"  This scene only.\n")
        length = ("Write as many paragraphs as needed to give every extracted moment its due — "
                  "do not compress multiple distinct beats into a single paragraph. "
                  "Stop as soon as the scene is complete. "
                  "If you find yourself describing a new location or the next event, you have gone too far — stop.")
        dialogue = DIALOGUE_INSTRUCTION_CONDITIONAL
    else:
        scope = ""
        length = "Write as many paragraphs as needed to cover all the extracted moments — typically 4–8, but do not stop early."
        dialogue = DIALOGUE_INSTRUCTION_FULL
    return (NARRATE_SYSTEM_BASE
            .replace("{examples_block}", block)
            .replace("{scene_scope_line}", scope)
            .replace("{length_instruction}", length)
            .replace("{dialogue_instruction}", dialogue))


def parse_plan(plan_text: str, total_chunks: int) -> list[dict]:
    sections = []
    for block in re.split(r"(?m)^## (?:Section|Scene) \d+", plan_text):
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
            elif line.startswith("scene:"):
                section["scene"] = line.split(":", 1)[1].strip()
            elif line.startswith("focus:"):
                section["focus"] = line.split(":", 1)[1].strip()
        if "narrator" in section and "chunk_start" in section:
            section["chunk_start"] = max(1, min(section["chunk_start"], total_chunks))
            section["chunk_end"]   = max(section["chunk_start"],
                                         min(section["chunk_end"], total_chunks))
            sections.append(section)
    return sections


def extraction_filename(index: int, narrator: str, scene: str) -> str:
    """Return a sortable filename for a per-scene extraction, e.g. '03_soma_glacier_crossing.md'."""
    def slugify(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    suffix = f"_{slugify(scene)}" if scene else ""
    return f"{index:02d}_{slugify(narrator)}{suffix}.md"


def estimate_narration_tokens(text: str) -> int:
    """Rough estimate of how many tokens the narration pass will need.

    Prose narration expands compressed extraction notes by roughly 4x for
    dialogue-heavy scenes (the quotes are written out in full) and 3x for
    action/environment-only scenes. Rounded up to the nearest 250.
    """
    has_dialogue = bool(re.search(r'(?m)^[A-Z][^:\n]+:\s*"', text))
    expansion = 4 if has_dialogue else 3
    estimated = int(len(text) / 4 * expansion)
    return max(500, ((estimated + 249) // 250) * 250)


def parse_extraction_file(text: str) -> tuple[str, int | None]:
    """Return (content, token_override) from an extraction file.

    If the file starts with a 'tokens: N' line, strip it and return N as the
    token override. Otherwise return the full text and None.
    """
    first, _, rest = text.partition("\n")
    m = re.match(r"^tokens:\s*(\d+)\s*$", first.strip())
    if m:
        return rest.lstrip("\n"), int(m.group(1))
    return text, None


def extract_scene_text(recap: str, scene_name: str) -> str:
    """Return the text of a single named scene from the recap's ## Scenes section."""
    lines = recap.splitlines()
    in_scenes = False
    in_target = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == "## Scenes":
            in_scenes = True
            continue
        if in_scenes and line.startswith("## "):
            break  # left the Scenes section
        if in_scenes and line.startswith("### "):
            if in_target:
                break  # reached the next scene
            if line.strip("# ").strip().lower() == scene_name.lower():
                in_target = True
            continue
        if in_target:
            collected.append(line)
    return "\n".join(collected).strip()


def build_char_extract_prompt(section: dict,
                               extractions: list[tuple[str, str]],
                               summary_extractions: list[tuple[str, str]] | None,
                               roster: str = "",
                               recap: str = "") -> str:
    start = section["chunk_start"] - 1
    end   = section["chunk_end"]
    scene_name = section.get("scene", "")

    parts = []
    if roster:
        parts.append(f"## Character Classes (definitive — never contradict these)\n\n{roster}")

    roleplay_chunks = [f"### Chunk {start + i + 1}\n\n{content}"
                       for i, (_, content) in enumerate(extractions[start:end])]
    roleplay_text = "\n\n---\n\n".join(roleplay_chunks)

    if scene_name and recap:
        # In scene mode: use the recap scene as the scope boundary, and the roleplay
        # extractions as the dialogue source. The model is told to stay within the
        # scene defined by the recap, but pull verbatim quotes from the extractions.
        scene_text = extract_scene_text(recap, scene_name)
        if scene_text:
            parts.append(
                f"## Scene scope: {scene_name}\n"
                f"(defines what this scene covers — stay within these boundaries)\n\n"
                f"{scene_text}"
            )
            parts.append(
                f"## Roleplay Extractions\n"
                f"(verbatim dialogue and character moments — primary source for quotes)\n\n"
                f"{roleplay_text}"
            )
            return "\n\n---\n\n".join(parts)

    # Non-scene mode (or scene not found in recap): send the full chunk extractions
    parts.append("## Roleplay Extractions\n"
                 "(dialogue, character voice, emotional beats — primary source)\n\n"
                 + roleplay_text)

    if summary_extractions:
        summary_chunks = [f"### Chunk {start + i + 1}\n\n{content}"
                          for i, (_, content) in enumerate(summary_extractions[start:end])]
        if summary_chunks:
            parts.append("## Session Extractions\n"
                         "(action detail, events, environmental context — use for texture)\n\n"
                         + "\n\n---\n\n".join(summary_chunks))

    return "\n\n---\n\n".join(parts)


def build_narrate_prompt(narrator: str, focus: str, char_moments: str,
                          party: str | None, handoff: str, roster: str = "",
                          voice_note: str | None = None) -> str:
    parts = [f"## Narrator: {narrator}\n## Focus: {focus}"]
    if roster:
        parts.append(f"## Character Classes (definitive — never contradict these)\n\n{roster}")
    if party:
        parts.append(f"## Party Document (authoritative source for character classes, "
                     f"abilities, and roles)\n\n{party.strip()}")
    if voice_note:
        parts.append(f"## {narrator}'s Voice Notes (written by the player — "
                     f"follow these precisely)\n\n{voice_note}")
    if handoff:
        parts.append(f"## Handoff from previous narrator\n\"{handoff}\"")
    parts.append(f"## {narrator}'s Roleplay Moments\n\n{char_moments.strip()}")
    return "\n\n---\n\n".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a D&D session document: narrative voice + enhanced structured sections."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Existing session recap file (e.g. from gmassisstant.app)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to save the final document")
    parser.add_argument("--roleplay-extract-dir", metavar="DIR",
                        help="vtt_roleplay_extractions/ — quoted dialogue and character moments")
    parser.add_argument("--summary-extract-dir", metavar="DIR",
                        help="vtt_extractions/ — action detail and event context")
    parser.add_argument("--context", nargs="+", metavar="FILE",
                        help="Campaign context files for consistency check "
                             "(e.g. campaign_state.md world_state.md party.md)")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — backstory, personality, relationships")
    parser.add_argument("--characters", metavar="NAMES",
                        help='Comma-separated roster, e.g. "Vukradin, Valphine, Soma, Brewbarry"')
    parser.add_argument("--session-name", default="", metavar="NAME",
                        help='e.g. "Session 12 — Icespire Hold"')
    parser.add_argument("--examples", nargs="+", metavar="FILE",
                        help="Handcrafted summary files as style references for narration")
    parser.add_argument("--voice-dir", metavar="DIR",
                        help="Directory of per-character voice files written by players. "
                             "Name files {character}_voice.md or {character}.md. "
                             "Each file is injected only into that character's narration pass.")
    parser.add_argument("--narrator", metavar="NAME",
                        help="Generate narration for one character only (skips passes 1–2, "
                             "runs the plan, then extracts and narrates the named character). "
                             "Useful for tweaking voice files without regenerating the full doc.")
    parser.add_argument("--by-scene", action="store_true",
                        help="Scene-by-scene mode: each scene is narrated by one character "
                             "in rotation, rather than each character covering a chunk of the "
                             "session. Matches the style of the handcrafted campaign summaries.")
    parser.add_argument("--plan-file", metavar="FILE",
                        help="Use a pre-written plan file instead of running pass 3. "
                             "Write the file in the same format as --plan-only output. "
                             "Useful when the auto-generated plan has overlap issues.")
    parser.add_argument("--plan-only", action="store_true",
                        help="Run through the narrative plan and exit without generating text")
    parser.add_argument("--extract-dir", metavar="DIR",
                        help="Save each scene's pass-4 extraction to this directory (one file "
                             "per scene, plus plan.md). Edit the files, then re-run with "
                             "--from-extractions to narrate from the edited versions.")
    parser.add_argument("--scene", nargs="+", type=int, metavar="N",
                        help="Run only the specified scene number(s) from the plan (1-based). "
                             "Useful for re-running a single scene without regenerating the rest. "
                             "Combine with --from-extractions to load from disk.")
    parser.add_argument("--extract-only", action="store_true",
                        help="Run passes 1–4, save extractions to --extract-dir, then stop. "
                             "Skips narration so you can review/edit before committing tokens.")
    parser.add_argument("--from-extractions", metavar="DIR",
                        help="Skip passes 1–4. Load per-scene extraction files from this "
                             "directory (written by a previous --extract-dir run) and run "
                             "narration only. Loads plan.md from the same directory unless "
                             "--plan-file is also given.")
    parser.add_argument("--narrate-tokens", type=int, default=None, metavar="N",
                        help="Override the narration token limit for all scenes in this run "
                             "(default: 1500 for scene mode, 12000 for chunk mode). "
                             "Individual scenes can also be overridden by adding 'tokens: N' "
                             "as the first line of their extraction file.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build and print all prompts for passes 4-5 without calling the API. "
                             "Useful for inspecting what each scene sends before committing.")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--verbose", action="store_true",
                        help="Print the full system and user prompt before each API call")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster, slightly lower quality)")
    args = parser.parse_args()
    if args.fast:
        args.model = "claude-haiku-4-5-20251001"
        print("  [fast mode: claude-haiku-4-5-20251001]")

    # ── Load inputs ───────────────────────────────────────────────────────────
    recap_path = Path(args.recap).expanduser()
    if not recap_path.exists():
        print(f"Error: recap file not found: {recap_path}", file=sys.stderr)
        sys.exit(1)
    recap = recap_path.read_text(encoding="utf-8")
    print(f"  Recap: {recap_path.name} ({len(recap):,} chars)")

    roleplay_extractions: list[tuple[str, str]] = []
    if args.roleplay_extract_dir:
        roleplay_extractions = load_extractions(Path(args.roleplay_extract_dir).expanduser())
        print(f"  Roleplay extractions: {len(roleplay_extractions)} chunk(s)")
    if not roleplay_extractions:
        print("Error: --roleplay-extract-dir is required", file=sys.stderr)
        sys.exit(1)

    summary_extractions: list[tuple[str, str]] = []
    if args.summary_extract_dir:
        summary_extractions = load_extractions(Path(args.summary_extract_dir).expanduser())
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

    party: str | None = None
    roster: str = ""
    if args.party:
        p = Path(args.party).expanduser()
        if p.exists():
            party = p.read_text(encoding="utf-8")
            roster = extract_character_roster(party)
            if roster:
                print(f"  Character roster: {roster.count(chr(10)) + 1} character(s)")
        else:
            print(f"  Warning: party file not found: {p}", file=sys.stderr)

    voice_files: dict[str, str] = {}
    if args.voice_dir:
        vd = Path(args.voice_dir).expanduser()
        if vd.is_dir():
            voice_files = load_voice_files(vd)
            if voice_files:
                print(f"  Voice files: {len(voice_files)} character(s) "
                      f"({', '.join(voice_files.keys())})")
        else:
            print(f"  Warning: voice-dir not found: {vd}", file=sys.stderr)

    examples_text: str | None = None
    if args.examples:
        parts = []
        for ex in args.examples:
            p = Path(ex).expanduser()
            if p.exists():
                parts.append(f"### Example: {p.name}\n\n{p.read_text(encoding='utf-8').strip()}")
            else:
                print(f"  Warning: example file not found: {p}", file=sys.stderr)
        if parts:
            examples_text = "\n\n---\n\n".join(parts)
            print(f"  Style examples: {len(parts)} file(s) ({len(examples_text):,} chars)")

    characters = (
        [c.strip() for c in args.characters.replace(",", " ").split() if c.strip()]
        if args.characters else []
    )

    # Resolve extract-dir paths early so validation happens before any API calls
    extract_dir: Path | None = None
    if args.extract_dir:
        extract_dir = Path(args.extract_dir).expanduser()
        extract_dir.mkdir(parents=True, exist_ok=True)

    from_extractions_dir: Path | None = None
    if args.from_extractions:
        from_extractions_dir = Path(args.from_extractions).expanduser()
        if not from_extractions_dir.is_dir():
            print(f"Error: --from-extractions directory not found: {from_extractions_dir}",
                  file=sys.stderr)
            sys.exit(1)
        # Auto-load plan from the directory unless --plan-file is given
        if not args.plan_file:
            auto_plan = from_extractions_dir / "plan.md"
            if auto_plan.exists():
                args.plan_file = str(auto_plan)
                print(f"  Plan: loaded from {auto_plan}")
            else:
                print("Error: --from-extractions requires a plan.md in the directory "
                      "(or pass --plan-file explicitly).", file=sys.stderr)
                sys.exit(1)

    client = make_client()

    single_narrator = args.narrator.strip() if args.narrator else None

    # ── Pass 1: Consistency check ─────────────────────────────────────────────
    consistency_report = ""
    if from_extractions_dir:
        print("\n[Passes 1–4: Skipped — loading extractions from disk]")
    elif single_narrator:
        print(f"\n[Pass 1: Skipped — single-narrator mode ({single_narrator})]")
    elif context_parts:
        print(f"\n[Pass 1: Consistency check | model: {args.model}]")
        print("=" * 60)
        consistency_prompt = (
            "## Session Recap\n\n" + recap.strip() +
            "\n\n---\n\n## Campaign Context\n\n" +
            "\n\n---\n\n".join(context_parts)
        )
        consistency_report = stream_api(client, CONSISTENCY_SYSTEM, consistency_prompt,
                                        args.model, silent=True, verbose=args.verbose)
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

    # ── Pass 2: Enhance structured sections ───────────────────────────────────
    structured_sections = ""
    if from_extractions_dir or single_narrator:
        if not from_extractions_dir:
            print(f"[Pass 2: Skipped — single-narrator mode]")
    else:
        print(f"\n[Pass 2: Enhance structured sections | model: {args.model}]")
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
        if party:
            enhance_parts.append("## Party Document (character voice reference)\n\n"
                                 + party.strip())

        enhance_prompt = "\n\n---\n\n".join(enhance_parts)
        structured_sections = stream_api(client, ENHANCE_SYSTEM, enhance_prompt, args.model,
                                          verbose=args.verbose)
        print("=" * 60)

    # ── Pass 3: Narrative plan ─────────────────────────────────────────────────
    if args.plan_file:
        plan_path = Path(args.plan_file).expanduser()
        if not plan_path.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        plan_text = plan_path.read_text(encoding="utf-8")
        print(f"\n[Pass 3: Narrative plan loaded from {plan_path.name}]")
    else:
        print(f"\n[Pass 3: Narrative plan | {len(roleplay_extractions)} chunk(s) | model: {args.model}]")
        print("=" * 60)

        plan_parts: list[str] = []
        if args.session_name:
            plan_parts.append(f"# Session: {args.session_name}")
        if characters:
            plan_parts.append("## Available narrators\n" + "\n".join(f"- {c}" for c in characters))
        chunk_parts = [f"### Chunk {i}\n\n{content}"
                       for i, (_, content) in enumerate(roleplay_extractions, 1)]
        plan_parts.append("## Roleplay Extractions\n"
                          "(dialogue, character voice, emotional beats)\n\n"
                          + "\n\n---\n\n".join(chunk_parts))
        if summary_extractions:
            s_parts = [f"### Chunk {i}\n\n{content}"
                       for i, (_, content) in enumerate(summary_extractions, 1)]
            plan_parts.append("## Session Extractions\n"
                              "(action detail, events, environmental context)\n\n"
                              + "\n\n---\n\n".join(s_parts))
        if party:
            plan_parts.append(f"## Party Document\n\n{party.strip()}")
        if args.by_scene:
            # Extract scene names from the ## Scenes section of the recap
            scene_lines = []
            in_scenes = False
            for line in recap.splitlines():
                if line.strip() == "## Scenes":
                    in_scenes = True
                elif line.startswith("## ") and in_scenes:
                    break  # left the Scenes section
                elif in_scenes and line.startswith("### "):
                    scene_lines.append(line.strip())
            if scene_lines:
                checklist = "\n".join(scene_lines)
                plan_parts.append(
                    "## Session Scenes (from recap — every scene below must appear in your plan)\n\n"
                    + checklist
                )

        plan_system = PLAN_SCENE_SYSTEM if args.by_scene else PLAN_SYSTEM
        plan_text = stream_api(client, plan_system, "\n\n---\n\n".join(plan_parts), args.model,
                               verbose=args.verbose)
        print("=" * 60)

    sections = parse_plan(plan_text, len(roleplay_extractions))
    if not sections:
        print("Error: could not parse narrative plan. Raw output:", file=sys.stderr)
        print(plan_text, file=sys.stderr)
        sys.exit(1)

    print(f"\nPlan: {len(sections)} section(s)")
    for i, s in enumerate(sections, 1):
        scene_label = f"  [{s['scene']}]" if s.get("scene") else ""
        print(f"  {i}. {s['narrator']:15s}  chunks {s['chunk_start']}–{s['chunk_end']}"
              f"{scene_label}  — {s.get('focus', '')}")

    if characters:
        # Warn about narrators the model invented outside the roster
        roster_lower = {c.lower() for c in characters}
        intruders = [s["narrator"] for s in sections
                     if s["narrator"].lower() not in roster_lower]
        if intruders:
            print(f"\nWarning: plan contains narrator(s) not in --characters: "
                  f"{', '.join(intruders)}")
            print("  Re-run with --plan-only or use --plan-file to fix.")

        assigned = {s["narrator"] for s in sections}
        missing = [c for c in characters if c not in assigned]
        if missing:
            print(f"\nWarning: these characters have no section: {', '.join(missing)}")
            print("  Re-run with --plan-only to inspect the plan.")

    # Warn when characters share a multi-chunk overlap — two chars on the same
    # single chunk is the normal 2+2 distribution and is fine (extraction
    # isolates their moments). The problem is when one char's range spans
    # multiple chunks that another char is also covering in full.
    for i, a in enumerate(sections):
        for b in sections[i + 1:]:
            a_range = set(range(a["chunk_start"], a["chunk_end"] + 1))
            b_range = set(range(b["chunk_start"], b["chunk_end"] + 1))
            overlap = a_range & b_range
            if overlap and (len(a_range) > 1 or len(b_range) > 1):
                print(f"\nWarning: {a['narrator']} (chunks {a['chunk_start']}–{a['chunk_end']}) "
                      f"and {b['narrator']} (chunks {b['chunk_start']}–{b['chunk_end']}) "
                      f"overlap — they will both narrate the same events.")
                print("  Consider re-running with --plan-only and adjusting the plan.")

    if single_narrator:
        matched = [s for s in sections
                   if s["narrator"].lower() == single_narrator.lower()]
        if not matched:
            names = ", ".join(s["narrator"] for s in sections)
            print(f"Error: narrator '{single_narrator}' not found in plan. "
                  f"Plan has: {names}", file=sys.stderr)
            sys.exit(1)
        sections = matched
        print(f"\nSingle-narrator mode: running passes 4–5 for {sections[0]['narrator']} only.")

    if args.scene:
        total = len(sections)
        bad = [n for n in args.scene if n < 1 or n > total]
        if bad:
            print(f"Error: scene number(s) out of range: {bad} (plan has {total} scene(s))",
                  file=sys.stderr)
            sys.exit(1)
        # Keep original 1-based index on the section so filenames stay consistent
        sections = [(n, sections[n - 1]) for n in args.scene]
        labels = ", ".join(
            f"{n}. {s['narrator']}" + (f" [{s['scene']}]" if s.get('scene') else "")
            for n, s in sections
        )
        print(f"\nScene filter: running passes 4–5 for {labels} only.")
    else:
        sections = list(enumerate(sections, 1))

    if args.plan_only:
        return

    # Save the plan alongside extractions so --from-extractions can reload it
    if extract_dir:
        plan_save = extract_dir / "plan.md"
        plan_save.write_text(plan_text, encoding="utf-8")
        print(f"  Plan saved to: {plan_save}")

    # ── Passes 4 & 5: Extract then narrate ────────────────────────────────────
    section_texts: list[tuple[str, str]] = []
    handoff = ""

    for i, section in sections:
        narrator   = section["narrator"]
        focus      = section.get("focus", "")
        scene_name = section.get("scene", "")
        chunks     = f"chunks {section['chunk_start']}–{section['chunk_end']}"
        label      = f"{narrator} — {scene_name}" if scene_name else narrator
        fname      = extraction_filename(i, narrator, scene_name)

        # Scene mode needs far fewer output tokens — one scene is 2-3 paragraphs
        extract_tokens = 1500 if scene_name else 4096
        narrate_tokens = args.narrate_tokens or (1500 if scene_name else 12000)
        file_token_override: int | None = None

        # Pass 4: character-specific extraction (silent)
        if from_extractions_dir:
            extract_file = from_extractions_dir / fname
            if not extract_file.exists():
                print(f"Error: extraction file not found: {extract_file}", file=sys.stderr)
                sys.exit(1)
            raw = extract_file.read_text(encoding="utf-8")
            char_moments, file_token_override = parse_extraction_file(raw)
            if file_token_override:
                narrate_tokens = file_token_override
            print(f"\n[Pass 4 scene {i}: Loaded from disk — {label}]")
            est = estimate_narration_tokens(char_moments)
            warn = f"  ⚠ estimated {est} — add 'tokens: {est}' to override" if est > narrate_tokens else ""
            print(f"  → {len(char_moments):,} chars from {extract_file.name}"
                  f"  (limit: {narrate_tokens}, est. ~{est}){warn}")
        else:
            print(f"\n[Pass 4 scene {i}: Extract — {label} ({chunks})]")
            scene_block = (
                f"Scene: '{scene_name}'\n"
                f"You will be given two sources:\n"
                f"1. Scene scope — the recap description of this scene. Use it to define the\n"
                f"   boundaries: what belongs in this scene and what does not.\n"
                f"2. Roleplay extractions — verbatim dialogue and character moments from the full\n"
                f"   session. Mine these for actual quotes and exchanges that fall within the scene.\n"
                f"Extract ONLY moments that belong to this scene. Ignore anything outside it.\n"
                f"Capture everything {narrator} witnessed — their own actions AND what others did.\n"
                if scene_name else "")
            char_extract_system = (CHAR_EXTRACT_SYSTEM
                                   .replace("{narrator}", narrator)
                                   .replace("{scene_block}", scene_block))
            char_extract_prompt = build_char_extract_prompt(
                section, roleplay_extractions, summary_extractions or None, roster, recap
            )

            if args.dry_run:
                print(f"\n{'▲' * 60}")
                print(f"PASS 4 SYSTEM — {label}:")
                print(char_extract_system)
                print("─" * 60)
                print(f"PASS 4 USER — {label}:")
                print(char_extract_prompt)
                print(f"{'▲' * 60}\n")
                continue

            char_moments = stream_api(client, char_extract_system, char_extract_prompt,
                                      args.model, max_tokens=extract_tokens, silent=True,
                                      verbose=args.verbose)
            print(f"  → {len(char_moments):,} chars of {narrator}'s moments")

            if extract_dir:
                out = extract_dir / fname
                out.write_text(char_moments, encoding="utf-8")
                est = estimate_narration_tokens(char_moments)
                warn = f"  ⚠ estimated {est} — add 'tokens: {est}' to override" if est > narrate_tokens else ""
                print(f"  Saved: {out.name}  (est. ~{est} tokens){warn}")

        if args.extract_only:
            continue

        # Pass 5: narrate from character-specific moments
        voice_note = get_voice_note(voice_files, narrator) if voice_files else None
        print(f"[Pass 5 scene {i}: Narrate — {label}"
              f"{' (voice notes)' if voice_note else ''}]")
        print("─" * 60)
        # In scene mode skip the heavy examples block to keep the prompt lean —
        # the style constraint is already carried by voice notes and the handoff.
        narrate_system = build_narrate_system(
            None if scene_name else examples_text,
            scene=scene_name or None
        )
        narrate_prompt = build_narrate_prompt(narrator, focus, char_moments, party, handoff,
                                              roster, voice_note)
        narration = stream_api(client, narrate_system, narrate_prompt,
                               args.model, max_tokens=narrate_tokens, verbose=args.verbose)
        print("─" * 60)

        narration = narration.strip()
        section_texts.append((label, narration))
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

    if args.extract_only:
        print(f"\nExtractions saved to: {extract_dir}")
        print("Review and edit the files, then re-run with --from-extractions to narrate.")
        return

    # ── Assemble final document ────────────────────────────────────────────────
    doc_parts: list[str] = []

    if single_narrator:
        narrator, narration = section_texts[0]
        doc_parts.append(f"## {narrator}\n\n{narration}")
    else:
        title = args.session_name or recap_path.stem
        doc_parts.append(f"# {title}\n")
        for narrator, narration in section_texts:
            doc_parts.append(f"---\n\n## {narrator}\n\n{narration}")
        doc_parts.append("---\n\n" + structured_sections.strip())

    full_doc = "\n\n".join(doc_parts) + "\n"

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(full_doc, encoding="utf-8")
    print(f"\nSession document saved to: {output}")

    if not args.no_log:
        if single_narrator:
            log_sections = (
                [("Narrative Plan", plan_text)] +
                [(f"Section — {n}", t) for n, t in section_texts]
            )
        else:
            log_sections = (
                [("Consistency Report", consistency_report or "(skipped)"),
                 ("Structured Sections", structured_sections),
                 ("Narrative Plan", plan_text)] +
                [(f"Section — {n}", t) for n, t in section_texts]
            )
        log_file = save_log(str(output.parent / "logs"), log_sections, stem="session_doc")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
