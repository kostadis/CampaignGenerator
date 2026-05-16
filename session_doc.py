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

from campaignlib import (
    build_alias_normalizer,
    format_npc_roster,
    load_alias_map,
    load_file_optional,
    make_client,
    save_log,
    stream_api,
)


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
- Distribute narrators based on who has the most interesting perspective on each scene.
  A character may narrate more than one scene. Rotate when perspectives are equal.

CRITICAL: If a "Session Scenes" checklist is provided:
- Use EXACTLY those scenes and no others. Do not invent additional scenes.
- Every scene on the checklist must appear in your plan with a narrator assigned.
- The checklist is the complete and authoritative list of scenes for this session.

If no checklist is provided, identify the key scenes yourself and cover the entire
session chronologically.

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

(assign every scene a narrator — pick the best perspective — every character should appear if possible)
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

Keep everything in chronological order, following the sequence of events as they appear
in the scene scope. The scene scope defines the authoritative event order — do not
reorder, skip, or reorganise events. Do not skip quiet or wordless moments — they are
the texture between the dramatic exchanges.

IMPORTANT: Only extract dialogue that actually appears in the Roleplay Extractions.
Do not invent or paraphrase exchanges. If no verbatim dialogue exists for this scene,
extract action beats and environmental moments only — that is a valid output.

SPEAKER LABEL NORMALISATION — apply to every dialogue attribution line:
- GM or DM with any player name in parentheses → always write as "GM"
  e.g. "GM (Kostadis)", "DM (Kostadis)", "Kostadis (GM)" → "GM"
- Character names with a player name in parentheses → strip the parenthetical
  e.g. "Thorin (Joe)" → "Thorin", "Grygum (Ben Pfaff)" → "Grygum"
- Unnamed NPCs (e.g. "Warrior", "Guard", "Voice") → keep as-is; do not invent a name

Output only the extracted moments. No preamble.
"""

# ── Pass 5: Per-character narration ───────────────────────────────────────────

NARRATE_SYSTEM_BASE = """\
You are writing one section of a first-person D&D session narrative.
{genre_directive}
You will be given:
- The narrator's name and a one-sentence focus
{scene_scope_line}{scene_events_line}- A handoff line from the previous narrator (if any)
- This character's extracted moments — their exact dialogue, reactions, and emotional beats
- A party document with backstory, personality, and relationships
{examples_block}
{rendering_instruction}{length_instruction}
Every significant moment in the extracted list should appear in the text.

{dialogue_instruction}

FOCUS ON:
- The emotional weight of each moment: why did they do or say that, what did it cost them
- What this character personally felt, feared, hoped for, or noticed in this moment
- How their backstory and relationships colour what they said and why

ALLOW:
- Non-linear structure for the narrator's inner life — flashbacks, memories, digressions,
  a character's mind drifting to something from their past
- The narrator's voice intruding on the action ("He tries not to stare...")
- Humour, irony, self-deprecation — if that fits the character
- Short, punchy paragraphs and sentence fragments for rhythm
- Dates or scene headers if they help orient the reader

CRITICAL: The actual events of the session must appear in the order they occur in the
extracted moments. Do not reorder, move, or restructure session events — only the
narrator's internal thoughts and memories may be non-linear.

CRITICAL: This is a first-person memoir. The narrator is always "I". Never use "he",
"she", or "they" to refer to the narrator — not even in passing. If you find yourself
writing "[Name] did X", you have left first person — recast it as "I did X". Third
person is a hard failure in this narration.

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

PER_CHAR_EXAMPLES_BLOCK = """\
STYLE REFERENCE — {narrator}'s VOICE SPECIFICALLY:
Match this voice. Any global examples above show overall quality; the passages below
show how {narrator} sounds in particular — the cadence, the vocabulary, the rhythm,
the particular way this character sees the world. When the general examples and these
disagree, these win. Prioritize matching them.

{examples}

END OF {narrator}-SPECIFIC STYLE REFERENCE
"""

VOICE_SPEC_BLOCK = """\
AUTHORITATIVE VOICE SPEC — {narrator}:
The following notes are written by {narrator}'s player. They override any conflicting
style guidance above. Match the cadence, vocabulary, and tics described here. When in
doubt about how a sentence should sound, refer to this section first.

{voice_note}

END OF VOICE SPEC
"""

PREV_VOICE_CONTRAST_BLOCK = """\
## Previous Section's Voice (for contrast — do NOT imitate)

The previous section was narrated by {prev_narrator}. A sample of their voice:

> {prev_voice_sample}

{narrator}'s voice should sound clearly different from {prev_narrator}'s. Lean into
what makes {narrator} distinct — their rhythm, their concerns, their particular way
of speaking — and away from anything that would make these two sections feel written
by the same hand."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_character_roster(party_text: str) -> str:
    """Parse party.md and return a compact name → class list for prompt injection.

    Expects sections like:
        ## Soma
        **Tortle Druid 5, Player: Wade**

    Outputs:
        - Soma (Wade): Tortle Druid 5
    """
    roster = []
    current_name: str | None = None
    for line in party_text.splitlines():
        m = re.match(r'^## (.+)$', line.strip())
        if m:
            current_name = m.group(1).strip()
        elif current_name:
            cm = re.match(r'^\*\*(.+\d+.+)\*\*$', line.strip())
            if cm:
                class_info = cm.group(1)
                # Extract player name(s) if present
                # Supports: "Player: Wade", "Player: Wade/Kostadis"
                pm = re.search(r',\s*Player:\s*(.+)', class_info)
                if pm:
                    player = pm.group(1).strip().rstrip('*')
                    class_only = class_info[:pm.start()].strip()
                    roster.append(f"- {current_name} ({player}): {class_only}")
                else:
                    roster.append(f"- {current_name}: {class_info}")
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


def get_char_examples(per_char_examples: dict[str, str], narrator: str) -> str | None:
    """Look up per-character style examples by case-insensitive first-name match."""
    key = narrator.lower().split()[0]
    return per_char_examples.get(key) or per_char_examples.get(narrator.lower())


def extract_contrast_sample(text: str, max_sentences: int = 5) -> str:
    """First substantive paragraph's first ~5 sentences — Phase-3 contrast signal.

    Skips markdown headings, italic-only captions, and `---` separators so the
    sample is drawn from the first verbatim passage in a per-char examples file
    rather than the file's title or subtitle. Title and italic subtitle are often
    joined into one paragraph (single newline between them), so the skip checks
    chrome line-by-line, not chunk-as-a-whole.
    """
    def is_chrome(line: str) -> bool:
        s = line.strip()
        if not s or s == "---":
            return True
        if s.startswith("#"):
            return True
        if s.startswith("*") and s.endswith("*") and len(s) > 1:
            return True
        return False

    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk or chunk == "---":
            continue
        lines = [ln for ln in chunk.splitlines() if ln.strip()]
        if not lines or all(is_chrome(ln) for ln in lines):
            continue
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chunk) if s.strip()]
        if not sentences:
            return chunk
        return " ".join(sentences[:max_sentences])
    return ""


def load_extractions(path: Path) -> list[tuple[str, str]]:
    files = sorted(path.glob("extract_*.md"))
    return [(f.name, f.read_text(encoding="utf-8").strip()) for f in files]


_SCENE_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)


def _split_scene_body(body: str) -> tuple[str, str]:
    """Split the body of a scene_extract.py file into (gm_summary, verbatim_moments).

    The conventional shape produced by scene_extract.py:
        # Scene Name
        ## Scene summary (from gm-assist, verbatim)
        <gm-assist body>
        ## Verbatim moments
        <vtt-derived moments>

    Returns ('', body) when the headings are absent — the caller treats the
    whole file as moments and lets Pass 5 work out the structure.
    """
    summary_match = re.search(r"(?ms)^## Scene summary[^\n]*\n(.*?)(?=^## |\Z)", body)
    moments_match = re.search(r"(?ms)^## Verbatim moments[^\n]*\n(.*?)(?=^## |\Z)", body)
    if summary_match and moments_match:
        return summary_match.group(1).strip(), moments_match.group(1).strip()
    return "", body.strip()


def load_scene_extractions(path: Path) -> list[dict]:
    """Load scene-anchored extraction files written by scene_extract.py.

    Looks for `NN_*.md` files (sorted), parses the YAML frontmatter for the
    canonical `scene:` name, and returns ordered dicts:
        [{"name": str, "path": Path, "summary": str, "moments": str, "body": str}, ...]

    For each scene, prefers the user-edited `NN_<slug>.scaffold.md` over
    the raw Stage-2 `NN_<slug>.md` when both exist — matching the Editor
    behavior in `server/routers/scene_editor.py` so Narrate consumes the
    same file the GM was looking at.

    `summary` is the gm-assist scene body (used as Pass 5's structural
    skeleton) and `moments` is the VTT-derived verbatim extraction (used as
    Pass 5's quote source). When a file does not follow the dual-section
    layout, `summary` is empty and `moments` holds the full body.

    Files named `plan.md`, `enhanced_sections.md`, `consistency_report.md`,
    or starting with `_` are skipped (they are sibling artifacts, not scene
    extractions).
    """
    SKIP = {"plan.md", "enhanced_sections.md", "consistency_report.md"}
    by_stem: dict[str, Path] = {}
    for f in path.glob("*.md"):
        if f.name in SKIP or f.name.startswith("_"):
            continue
        if f.name.endswith(".scaffold.md"):
            stem = f.name[: -len(".scaffold.md")]
            is_scaffold = True
        else:
            stem = f.stem
            is_scaffold = False
        if not re.match(r"^\d{2}_", stem):
            continue
        # Scaffold wins over Stage-2; otherwise first one in.
        if is_scaffold or stem not in by_stem:
            by_stem[stem] = f
    items: list[dict] = []
    for stem in sorted(by_stem):
        f = by_stem[stem]
        text = f.read_text(encoding="utf-8")
        fallback_name = stem.split("_", 1)[1].replace("_", " ").title() if "_" in stem else stem
        m = _SCENE_FRONTMATTER_RE.match(text)
        if m:
            name = ""
            for line in m.group(1).splitlines():
                if line.strip().lower().startswith("scene:"):
                    name = line.split(":", 1)[1].strip()
                    break
            body = m.group(2).strip()
            if not name:
                name = fallback_name
        else:
            name = fallback_name
            body = text.strip()
        summary, moments = _split_scene_body(body)
        items.append({
            "name": name,
            "path": f,
            "body": body,
            "summary": summary,
            "moments": moments,
        })
    return items


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

PROSE_MODE_INSTRUCTION = """\
PROSE MODE — IMMERSIVE NARRATION ONLY:

CRITICAL: No mechanical numbers may appear in the prose — not damage values, not hit
points, not spell slot numbers, not AC, not DCs, not die rolls. Not even in passing.
Not even as part of a verbatim player quote. If a player said "I've got 16 HP left"
or "that was 22 damage", those are table-talk, not story. Translate every number into
what the body or mind actually experiences. A number that reaches the page is a failure.

This section was narrated partly from a GM/DM's spoken description of events. Do NOT
carry any of that framing into the prose:

- The narrator experiences the world directly. There is no "the DM told us" or "the GM
  described" or "we were informed by the narrator." The world simply is, and the
  character perceives it.
- NPCs speak. Their dialogue is heard, not relayed. Never write "the DM said [NPC]
  told us X" — write what the NPC said, or what the narrator heard.
- All mechanical language must be converted to narrative consequence:
    BAD: "she failed her saving throw against the DC 15 Wisdom check"
    GOOD: "she flinched, something behind her eyes going distant and soft"
    BAD: "he took 14 piercing damage and dropped to 7 HP"
    GOOD: "the bolt punched through his shoulder and he went down hard"
    BAD: "I used my last spell slot"
    GOOD: "there was nothing left — whatever I had in me, I had already spent it"
- Game mechanic instructions ("Roll a DC-14 Wisdom saving throw", "Make a Dexterity
  check", "Roll for initiative") mark the moment a challenge arrives — they are NOT
  prose. Translate them to what the character experiences in that instant:
    BAD:  "Roll a DC-14 Wisdom saving throw."
    BAD:  "*Roll a DC-14 Wisdom saving throw.*"
    GOOD: "Something pressed against my mind — cold, insistent, trying to get in."
    GOOD: "My focus narrowed to a single point. Hold. Just hold."
  Never reproduce the instruction in any form, italicised or otherwise.
- DC numbers are difficulty, not prose. Translate them by scale:
    DC 10 or below → a routine effort, something that costs focus but little else
    DC 14–15       → a hard push, real resistance, the outcome genuinely uncertain
    DC 20          → near the edge of what a person can do; draining, costly
    DC 25+         → the kind of thing that leaves a mark; almost impossible
  Translate the ability or skill into the thing it actually represents:
    Wisdom / Will   → clarity under pressure, holding the self together, not flinching
    Intelligence    → recall, deduction, the mind working fast under duress
    Charisma        → force of presence, the voice that cuts through, force of will
    Strength        → raw physical effort, the body pushed to its limit
    Dexterity       → speed, precision, the body moving before the mind catches up
    Constitution    → endurance, absorbing punishment, staying on your feet
    Skill checks    → the specific act: a Stealth check is breath held and footfall
                      controlled; an Athletics check is muscle and will against weight;
                      a Persuasion check is every ounce of personality directed at one person
    BAD: "Roll a DC-14 Wisdom saving throw."
    GOOD: "Something in her pressed back — the part that stays calm when everything
           else is coming apart. It held. Barely."
- "Turn" language reflects the rhythm of combat — not a game mechanic. Translate:
    "my turn"            → my moment, when the opening came, when I had room to act
    "end of my turn"     → when the moment passed, when I had a breath, before I moved again
    "next turn"          → the next time I had an opening, when I got my footing back
    "saving throw at     → waiting for the condition to break — enduring it, holding on
     end of my turn"       until I could shake it or someone reached me
    BAD:  "I waited for the end of my turn. The fear would break then."
    GOOD: "I held my ground and waited for the feeling to pass — the cold clutch of it
           loosening beat by beat until I could think straight again and move."
- Damage amounts reflect the wearing down of endurance, focus, and defenses — not literal
  flesh wounds. Scale the narrative weight to the number, with no blood or gore:
    1–10   → glancing, absorbed, barely registers — a bruise through armor, a scrape,
              something shaken off without breaking stride
    10–20  → real impact, felt through the defenses — a hard hit that costs something,
              the kind that makes you adjust, tighten up, recalculate
    20–40  → serious — a blow that takes a chunk out of what's left, the body or mind
              warning that there isn't much margin remaining
    40+    → brutal — the kind of hit that drops lesser creatures outright; for a typed
              source (necrotic drain, dragon breath, fireball, cold, lightning) it is
              acceptable to describe pain, suffering, or the specific sensation of that
              damage type — the burning, the cold seeping in, the vital energy being pulled
              away — but keep it visceral rather than gory
  Examples:
    BAD:  "She took 48 points of bludgeoning damage."
    BAD:  "The attack dealt 8 damage."
    GOOD (8 damage):  "The blow landed but didn't bite deep — she'd felt worse."
    GOOD (22 damage): "That one got through. Something cracked — not broke, but the margin
                       was shrinking."
    GOOD (48 damage, bludgeoning): "The impact was enormous. The kind that doesn't just
                       hurt — it reorganizes your understanding of what hurt means."
    GOOD (48 damage, necrotic): "Something cold and wrong moved through her — not pain
                       exactly, more like absence, like warmth being taken rather than
                       heat being applied. She could feel what it was pulling away."
- When a player states remaining HP ("I've got 18 hit points left of 44"), translate this
  to the character's felt condition — never mention the number. The threshold that matters
  is whether they're likely to survive the next serious hit:
      < 10 HP  → on the verge of collapse; barely standing; the next solid hit ends it;
                  running on instinct and survival reflex alone
      10–19 HP → the edge; one more bad round and it's over; the character knows this —
                  it changes how they move, what risks they take, how much they're pushing
                  through rather than fighting clean
      20–35 HP → worn down, feeling it, the hits have accumulated — but there's still
                  margin; they can take more, though not much more
      35+ HP   → hurt but functional; the fight has cost something real but the reserve
                  is still there
  A player saying "I think I can take one more round of hits" is the character doing
  internal triage — counting what's left and knowing the answer isn't comfortable.
  Render that calculation, not the arithmetic.
      BAD:  "I had 18 hit points remaining."
      BAD:  "I was at less than half health."
      GOOD (18 HP): "I was still on my feet. Barely. One more round like that and I
                     wouldn't be."
      GOOD (8 HP):  "I was running on something that wasn't quite strength anymore —
                     reflex, maybe, or the body's last argument against stopping."
- When a character rolls a critical success (natural 20) on an ABILITY CHECK or SKILL
  CHECK — not an attack roll — the narration should reflect that something exceptional
  happened, not just that it worked. This is the moment where everything clicked: the
  body moved perfectly, the mind was razor-sharp, the words landed exactly right. The
  character should feel it — the rare, clean sensation of having absolutely nailed
  something. Not lucky. Not barely. Definitively.
    BAD: "I picked the lock." (success but flat)
    BAD: "I managed to persuade her." (success but flat)
    GOOD: "My fingers found the tumblers before I even thought about it — the lock gave
           like it had been waiting for me. I almost laughed."
    GOOD: "I said the right thing. I knew it the moment it left my mouth — the exact
           word, the exact weight. I could see it land."
- Dice rolls, attack rolls, spell slots, challenge ratings, and game statistics have no
  place in this prose. Replace every one of them with what the character would actually
  experience, feel, or observe.
- DM scene descriptions are the world as the character PERCEIVES it — not commentary
  from a narrator standing outside the story. When the source material contains the DM
  setting a scene ("the hall is dark, torches sputtering, the smell of blood in the
  air"), render it as direct sensory experience:
    BAD:  "the DM described a dark hall with guttering torches"
    BAD:  "we were told the air smelled of blood"
    GOOD: "the torches had gone out, and the dark pressed in; the smell hit me first"
- DM dramatic framing is the character's emotional reality — not a narrator's
  commentary on the significance of events. When the source material contains the DM
  building stakes or emotional weight ("this isn't just a fight — she is everything
  you've been fighting toward"), render it as what the character FEELS in that moment:
    BAD:  "the encounter was described as momentous"
    BAD:  "the narrator told us this enemy was significant"
    GOOD: "something in my chest understood, before my mind caught up, that this was
           what all of it had been building toward"
- GM/DM out-of-character remarks — table banter, reactions to player jokes, meta-commentary,
  anything the GM says as a person at the table rather than as a narrator or NPC voice — are
  cut entirely. They have no narrative equivalent. Do not paraphrase them, attribute them,
  or let them leave a trace in the prose. If the GM laughs at a player's quip, that laugh
  does not exist in the story.
    BAD:  "The GM, to his credit, said he hoped more pleasantly."
    BAD:  "Kostadis laughed."
    GOOD: [the line simply does not appear]
  The rule of thumb: if a GM line is responding to a player — rather than describing the
  world or voicing an NPC — it gets cut.
- Speaker labels such as "GM (Kostadis)", "DM (Kostadis)", "GM (Name)", "DM (Name)",
  "Kostadis (GM)", or "Kostadis (DM)" all identify the game master's out-of-character
  voice. GM and DM are the same role — the same person. Never reference these people by name in the prose
  — not as players, not as someone who "handed" or "told" the narrator something, not in
  any form. The narrator does not receive information from a person at the table. They
  simply know, perceive, or realize the thing. Tactical explanations become instinct or
  calculation. Scene-setting becomes direct sensory experience. The real person's name
  must not appear in the output.\
"""


SCENE_ANCHORED_DIRECTIVE = """\
NARRATOR FOCUS — the moments below are SCENE-LEVEL, not pre-filtered to one character.
They capture the whole scene as it happened around everyone present. Your job is to
render that scene through {narrator}'s eyes specifically:
- Foreground what {narrator} said, did, noticed, and felt — give those beats weight.
- Other characters' actions are visible only as {narrator} would experience them
  — what they saw, heard, or reacted to. No internal monologue for anyone but {narrator}.
- Every verbatim quote in the moments belongs in the prose, even when {narrator} did
  not speak it — they were there, they heard it, render it as heard.
- Do not narrate from an omniscient camera. Stay in {narrator}'s body and point of view.\
"""


def build_narrate_system(examples_text: str | None, scene: str | None = None,
                         prose_mode: bool = False,
                         has_scene_events: bool = False,
                         scene_anchored: bool = False,
                         narrator: str = "",
                         char_examples: str | None = None,
                         voice_note: str | None = None,
                         genre: str | None = None) -> str:
    if examples_text:
        block = "\n" + EXAMPLES_BLOCK.replace("{examples}", examples_text.strip()) + "\n"
    else:
        block = ""
    if genre and genre.strip():
        genre_block = f"GENRE: {genre.strip()}\n"
    else:
        genre_block = ""
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
    if has_scene_events:
        scene_events_line = ("- Scene Events (authoritative) — the ordered account of what "
                             "happened; render from this faithfully\n"
                             "- Campaign Context — character backstory, NPC states, world detail\n")
        rendering = ("The Scene Events list is the authoritative account of what occurred. "
                     "Render it in this character's voice. Do not add events that are not listed. "
                     "The extracted moments below are your primary source for verbatim quotes — "
                     "weave those lines in exactly as written.\n\n")
    else:
        scene_events_line = ""
        rendering = ""
    result = (NARRATE_SYSTEM_BASE
              .replace("{genre_directive}", genre_block)
              .replace("{examples_block}", block)
              .replace("{scene_scope_line}", scope)
              .replace("{scene_events_line}", scene_events_line)
              .replace("{rendering_instruction}", rendering)
              .replace("{length_instruction}", length)
              .replace("{dialogue_instruction}", dialogue))
    if scene_anchored and narrator:
        result += "\n\n" + SCENE_ANCHORED_DIRECTIVE.replace("{narrator}", narrator)
    if prose_mode:
        result += "\n\n" + PROSE_MODE_INSTRUCTION
    if char_examples and narrator:
        block = (PER_CHAR_EXAMPLES_BLOCK
                 .replace("{narrator}", narrator)
                 .replace("{examples}", char_examples.strip()))
        result += "\n\n" + block
    if voice_note and narrator:
        block = (VOICE_SPEC_BLOCK
                 .replace("{narrator}", narrator)
                 .replace("{voice_note}", voice_note.strip()))
        result += "\n\n" + block
    return result


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


def extract_section_text(recap: str, section_name: str) -> str:
    """Return the body text of a ## section from the recap (e.g. 'Summary', 'Memorable Moments')."""
    lines = recap.splitlines()
    in_target = False
    collected: list[str] = []
    for line in lines:
        if line.strip().lower() == f"## {section_name.lower()}":
            in_target = True
            continue
        if in_target and line.startswith("## "):
            break
        if in_target:
            collected.append(line)
    return "\n".join(collected).strip()


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
                               recap: str = "",
                               session_summary: str = "") -> str:
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
        # The recap's Summary and Memorable Moments provide narrative detail and
        # character moments (e.g. backstory reflections) that may not appear in the
        # VTT roleplay extractions.
        scene_text = extract_scene_text(recap, scene_name)
        if scene_text:
            parts.append(
                f"## Scene scope: {scene_name}\n"
                f"(defines what this scene covers — stay within these boundaries)\n\n"
                f"{scene_text}"
            )
            # Include recap narrative sections for character moments and
            # backstory beats that the VTT extraction may have missed
            recap_context_parts = []
            for section_name in ("Summary", "Memorable Moments"):
                text = extract_section_text(recap, section_name)
                if text:
                    recap_context_parts.append(f"### {section_name}\n\n{text}")
            if recap_context_parts:
                parts.append(
                    "## Recap Context\n"
                    "(narrative detail, character reflections, and memorable quotes from "
                    "the GM recap — incorporate any moments relevant to this scene)\n\n"
                    + "\n\n".join(recap_context_parts)
                )
            parts.append(
                f"## Roleplay Extractions\n"
                f"(verbatim dialogue and character moments — primary source for quotes)\n\n"
                f"{roleplay_text}"
            )
            if session_summary:
                parts.append(
                    "## Session Events (VTT Summary)\n"
                    "(authoritative event log — use for action beats, mechanics, and "
                    "anything not captured in dialogue)\n\n"
                    + session_summary.strip()
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
                          roleplay_summary: str | None = None,
                          scene_text: str | None = None,
                          context_docs: list[str] | None = None,
                          prev_narrator: str | None = None,
                          prev_voice_sample: str | None = None) -> str:
    parts = [f"## Narrator: {narrator}\n## Focus: {focus}"]
    if roster:
        parts.append(f"## Character Classes (definitive — never contradict these)\n\n{roster}")
    if party:
        parts.append(f"## Party Document (authoritative source for character classes, "
                     f"abilities, and roles)\n\n{party.strip()}")
    if context_docs:
        combined = "\n\n---\n\n".join(context_docs)
        parts.append(
            f"## Campaign History\n\n"
            f"This is the accumulated campaign context — past events, faction relationships, "
            f"NPC histories, world conditions. When the current scene creates a natural "
            f"opening, draw on this for a brief memory, reflection, or flashback:\n"
            f"- A past decision that echoes in the current one\n"
            f"- An NPC the narrator has history with\n"
            f"- A cost or consequence that has been accumulating\n"
            f"- A pattern the narrator has noticed repeating\n\n"
            f"Keep it brief: one or two sentences of interior thought, then return to the "
            f"present. Do not summarize the history. Let it surface as the narrator's "
            f"inner life.\n\n"
            f"{combined}"
        )
    if scene_text:
        parts.append(
            f"## Scene: What Happened\n\n"
            f"This is the GM's authoritative account of what occurred in this scene. "
            f"Use it as the structural skeleton — the events, decisions, and NPC reactions "
            f"that the narration must cover. The character's Roleplay Moments (below) "
            f"provide verbatim quotes and character-specific beats to weave in.\n\n"
            f"{scene_text.strip()}"
        )
    if roleplay_summary:
        parts.append(
            f"## Session Roleplay Summary\n\n"
            f"This document covers the full session — use it for voice and style reference only.\n"
            f"- **Character Voices**: match the speech patterns and register shown here\n"
            f"- **Voice Keeper Notes**: let PC emotional states and NPC patterns shape the prose\n\n"
            f"The dialogue to include in this scene comes exclusively from "
            f"## {narrator}'s Roleplay Moments below — not from this document.\n\n"
            f"{roleplay_summary.strip()}"
        )
    if (prev_narrator and prev_voice_sample
            and prev_narrator.lower() != narrator.lower()):
        contrast = (PREV_VOICE_CONTRAST_BLOCK
                    .replace("{prev_narrator}", prev_narrator)
                    .replace("{prev_voice_sample}", prev_voice_sample.strip())
                    .replace("{narrator}", narrator))
        parts.append(contrast)
    if handoff:
        parts.append(f"## Handoff from previous narrator\n\"{handoff}\"")
    # When an authoritative scene account is provided, rename the extraction block to
    # make clear it is the quote source, not the event source
    if scene_text:
        parts.append(f"## Verbatim Quotes — {narrator}\n"
                     f"(weave these into the narrative exactly as written)\n\n"
                     f"{char_moments.strip()}")
    else:
        parts.append(
            f"## {narrator}'s Scene Moments\n"
            f"(grouped format: each action beat line starting with \"-\" is followed by "
            f"the dialogue that occurred during it — narrate beat and quotes together "
            f"as a single moment; beats with no quotes are action-only moments)\n\n"
            f"{char_moments.strip()}"
        )
    return "\n\n---\n\n".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a D&D session document: narrative voice + enhanced structured sections."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Existing session recap file (e.g. from gmassisstant.app)")
    parser.add_argument("--output", "-o", default=None, metavar="FILE",
                        help="Where to save the final assembled document. "
                             "Required unless --per-scene-output is set.")
    parser.add_argument("--per-scene-output", default=None, metavar="DIR",
                        help="Stage 3 mode: write one narration file per scene "
                             "(session_doc_scene_NN_<slug>.md, with YAML "
                             "frontmatter) into this directory and skip the "
                             "final-doc assembly. Use Stage 4 / assemble.py to "
                             "combine the per-scene files later. Compatible with "
                             "--scene N for re-narrating a single scene.")
    parser.add_argument("--roleplay-extract-dir", metavar="DIR",
                        help="vtt_roleplay_extractions/ — quoted dialogue and character moments")
    parser.add_argument("--summary-extract-dir", metavar="DIR",
                        help="vtt_extractions/ — action detail and event context")
    parser.add_argument("--session-summary", metavar="FILE",
                        help="Synthesised VTT session summary (e.g. session-clean.md). "
                             "Used as an authoritative event log in passes 1, 3, and 4.")
    parser.add_argument("--context", nargs="+", metavar="FILE",
                        help="Campaign context files for consistency check "
                             "(e.g. campaign_state.md world_state.md party.md)")
    parser.add_argument("--party", metavar="FILE",
                        help="party.md — backstory, personality, relationships")
    parser.add_argument("--characters", metavar="NAMES",
                        help='Comma-separated roster, e.g. "Vukradin, Valphine, Soma, Brewbarry"')
    parser.add_argument("--session-name", default="", metavar="NAME",
                        help='e.g. "Session 12 — Icespire Hold"')
    parser.add_argument("--examples", metavar="DIR",
                        help="Directory of handcrafted summary files as style references for narration")
    parser.add_argument("--voice-dir", metavar="DIR",
                        help="Directory of per-character voice files written by players. "
                             "Name files {character}_voice.md or {character}.md. "
                             "Each file is injected only into that character's narration pass.")
    parser.add_argument("--roleplay-summary", metavar="FILE",
                        help="Synthesised roleplay highlights document (session-roleplay.md). "
                             "Injected into every narration pass: character voices with actual "
                             "quotes, verbatim memorable exchanges, and Voice Keeper Notes.")
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
    parser.add_argument("--no-plan-review", action="store_true",
                        help="Skip the Pass 3 plan-review checkpoint and continue into "
                             "extraction immediately. Use when --plan-file is not available "
                             "but the plan is already known-good.")
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
    parser.add_argument("--prose-mode", action="store_true",
                        help="Strip all mechanical/game language and GM framing from narration. "
                             "GM descriptions become direct world perception; dice rolls and HP "
                             "become narrative consequence.")
    parser.add_argument("--narration-genre", default=None, metavar="TEXT",
                        help="One-line genre/register directive injected into the "
                             "Pass-5 narration system prompt (e.g. 'First-person "
                             "comic-noir fantasy memoir — observational, dry, "
                             "irony-forward'). When unset, no genre line is "
                             "added — narration prompt is identical to no-flag "
                             "behaviour.")
    parser.add_argument("--reflections", action="store_true",
                        help="Inject campaign_state and world_state context into the narration "
                             "prompt so the narrator can draw on past events as memories, "
                             "flashbacks, and reflections. Requires --context files.")
    parser.add_argument("--no-log", action="store_true")
    parser.add_argument("--verbose", action="store_true",
                        help="Print the full system and user prompt before each API call")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--enhanced-sections", metavar="FILE",
                        help="Use a pre-saved Pass 2 output file instead of re-running Pass 2. "
                             "When --from-extractions is used, auto-detected as "
                             "enhanced_sections.md in that directory. Injected as scene context "
                             "and campaign context in narration (Pass 5).")
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku instead of Sonnet (~4x cheaper, faster, slightly lower quality)")
    parser.add_argument("--dossier-dir", metavar="DIR", default=None,
                        help="Directory of per-NPC dossier files (built by "
                             "planning.py --build-dossiers). If given, every "
                             "alias in dossier frontmatter is rewritten to its "
                             "canonical name in recap/extractions before Pass 4, "
                             "and a 'Known NPCs' roster seeds the extract prompt.")
    parser.add_argument("--scene-extractions", metavar="DIR", default=None,
                        help="Directory of scene-anchored extractions (written by "
                             "scene_extract.py). When supplied, Pass 4 is skipped: "
                             "each section's matching scene file is fed directly to "
                             "Pass 5 with a narrator-POV directive. Pass 3 reads the "
                             "scene checklist from this directory's filenames/frontmatter "
                             "instead of the recap. Forces --by-scene.")
    parser.add_argument("--campaign-dir", default=None,
                        help="Campaign workspace root (default: $CAMPAIGN_DIR "
                             "or the recap file's parent directory). Used to "
                             "locate docs/dossier_proposal.md.")
    parser.add_argument("--require-proposal", action="store_true",
                        help="Refuse to run unless "
                             "<campaign-dir>/docs/dossier_proposal.md exists "
                             "and has been approved (status banner edited "
                             "away from `candidates only`).")
    args = parser.parse_args()
    if args.output is None and args.per_scene_output is None and not args.plan_only and not args.extract_only:
        parser.error("either --output or --per-scene-output must be set "
                     "(or use --plan-only / --extract-only).")
    if args.fast:
        args.model = "claude-haiku-4-5-20251001"
        print("  [fast mode: claude-haiku-4-5-20251001]")
    per_scene_output_dir: Path | None = None
    if args.per_scene_output:
        per_scene_output_dir = Path(args.per_scene_output).expanduser()
        per_scene_output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve the proposal check BEFORE any Claude calls. Everything
    # below this point may hit stream_api — the refuse guard lives here.
    import os as _os

    from proposal_loader import (
        ProposalNotApproved,
        ProposalRequired,
        require_approved_proposal,
    )
    _session_doc_campaign_dir = (
        args.campaign_dir
        or _os.environ.get("CAMPAIGN_DIR")
        or str(Path(args.recap).expanduser().resolve().parent)
    )
    if args.require_proposal:
        try:
            require_approved_proposal(_session_doc_campaign_dir)
        except (ProposalRequired, ProposalNotApproved) as exc:
            parser.error(str(exc))

    # ── Load inputs ───────────────────────────────────────────────────────────
    recap_path = Path(args.recap).expanduser()
    if not recap_path.exists():
        print(f"Error: recap file not found: {recap_path}", file=sys.stderr)
        sys.exit(1)
    recap = recap_path.read_text(encoding="utf-8")
    print(f"  Recap: {recap_path.name} ({len(recap):,} chars)")

    alias_map = load_alias_map(args.dossier_dir)
    normalize, _ = build_alias_normalizer(alias_map)
    npc_roster = format_npc_roster(alias_map)
    if alias_map:
        print(f"  Alias map: {len(alias_map)} NPC(s) from {args.dossier_dir}")
    recap = normalize(recap)

    scene_extractions: list[dict] = []
    if args.scene_extractions:
        sx_dir = Path(args.scene_extractions).expanduser()
        if not sx_dir.is_dir():
            print(f"Error: --scene-extractions directory not found: {sx_dir}", file=sys.stderr)
            sys.exit(1)
        scene_extractions = load_scene_extractions(sx_dir)
        if not scene_extractions:
            print(f"Error: no scene extraction files found in {sx_dir} "
                  f"(expected NN_*.md files written by scene_extract.py)", file=sys.stderr)
            sys.exit(1)
        if not args.by_scene:
            print("  --scene-extractions implies --by-scene; enabling.")
            args.by_scene = True
        print(f"  Scene extractions: {len(scene_extractions)} scene(s) from {sx_dir}")
        for i, sx in enumerate(scene_extractions, 1):
            print(f"    {i}. {sx['name']}")

    roleplay_extractions: list[tuple[str, str]] = []
    if args.roleplay_extract_dir:
        roleplay_extractions = load_extractions(Path(args.roleplay_extract_dir).expanduser())
        if alias_map:
            roleplay_extractions = [(n, normalize(c)) for n, c in roleplay_extractions]
        print(f"  Roleplay extractions: {len(roleplay_extractions)} chunk(s)")
    if not roleplay_extractions and not scene_extractions:
        print("Error: --roleplay-extract-dir is required (unless --scene-extractions is given)",
              file=sys.stderr)
        sys.exit(1)

    summary_extractions: list[tuple[str, str]] = []
    if args.summary_extract_dir:
        summary_extractions = load_extractions(Path(args.summary_extract_dir).expanduser())
        if alias_map:
            summary_extractions = [(n, normalize(c)) for n, c in summary_extractions]
        print(f"  Session extractions:  {len(summary_extractions)} chunk(s)")

    session_summary: str = ""
    if args.session_summary:
        _p = Path(args.session_summary).expanduser()
        if not _p.exists():
            print(f"Error: --session-summary file not found: {_p}", file=sys.stderr)
            sys.exit(1)
        session_summary = normalize(_p.read_text(encoding="utf-8"))
        print(f"  Session summary:      {_p.name} ({len(session_summary):,} chars)")

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
        _p = Path(args.party).expanduser()
        if not _p.exists():
            print(f"Error: --party file not found: {_p}", file=sys.stderr)
            sys.exit(1)
        party = _p.read_text(encoding="utf-8")
        roster = extract_character_roster(party)
        if roster:
            print(f"  Character roster: {roster.count(chr(10)) + 1} character(s)")

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

    roleplay_summary: str | None = None
    if args.roleplay_summary:
        _p = Path(args.roleplay_summary).expanduser()
        if not _p.exists():
            print(f"Error: --roleplay-summary file not found: {_p}", file=sys.stderr)
            sys.exit(1)
        roleplay_summary = _p.read_text(encoding="utf-8")
        print(f"  Roleplay summary: {_p.name} ({len(roleplay_summary):,} chars)")

    characters = (
        [c.strip() for c in args.characters.split(",") if c.strip()]
        if args.characters else []
    )

    examples_text: str | None = None
    per_char_examples: dict[str, str] = {}
    if args.examples:
        ed = Path(args.examples).expanduser()
        if ed.is_dir():
            # Files whose stem (after stripping an optional _examples suffix)
            # matches a character's first name route to that character only.
            # Everything else falls into the global pool, preserving the
            # pre-existing behaviour.
            char_keys = {c.lower().split()[0] for c in characters if c}
            global_parts: list[str] = []
            for p in sorted(ed.glob("*.md")):
                stem_lower = p.stem.lower()
                key = stem_lower.removesuffix("_examples")
                snippet = f"### Example: {p.name}\n\n{p.read_text(encoding='utf-8').strip()}"
                if key in char_keys:
                    existing = per_char_examples.get(key, "")
                    per_char_examples[key] = (
                        existing + "\n\n---\n\n" + snippet if existing else snippet
                    )
                else:
                    global_parts.append(snippet)
            if global_parts:
                examples_text = "\n\n---\n\n".join(global_parts)
                print(f"  Style examples (global): {len(global_parts)} file(s) "
                      f"from {ed} ({len(examples_text):,} chars)")
            if per_char_examples:
                print(f"  Style examples (per-character): "
                      f"{', '.join(sorted(per_char_examples.keys()))}")
            if not global_parts and not per_char_examples:
                print(f"  Warning: no .md files found in examples dir: {ed}", file=sys.stderr)
        else:
            print(f"  Warning: examples dir not found: {ed}", file=sys.stderr)

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

    # Load enhanced sections (Pass 2 output saved from a prior run)
    enhanced_sections: str = ""
    if args.enhanced_sections:
        _p = Path(args.enhanced_sections).expanduser()
        if not _p.exists():
            print(f"Error: --enhanced-sections file not found: {_p}", file=sys.stderr)
            sys.exit(1)
        enhanced_sections = _p.read_text(encoding="utf-8")
        print(f"  Enhanced sections: {_p.name} ({len(enhanced_sections):,} chars)")
    elif from_extractions_dir:
        auto_enhanced = from_extractions_dir / "enhanced_sections.md"
        if auto_enhanced.exists():
            enhanced_sections = auto_enhanced.read_text(encoding="utf-8")
            print(f"  Enhanced sections: auto-detected ({len(enhanced_sections):,} chars)")

    client = make_client()

    single_narrator = args.narrator.strip() if args.narrator else None

    # Re-narration: explicit plan + scene filter means Passes 1–2 already ran.
    renarration_mode = bool(args.plan_file and args.scene)

    # ── Pass 1: Consistency check ─────────────────────────────────────────────
    consistency_report = ""
    if from_extractions_dir:
        print("\n[Passes 1–4: Skipped — loading extractions from disk]")
    elif renarration_mode:
        print("\n[Pass 1: Skipped — re-narration (--plan-file + --scene)]")
    elif single_narrator:
        print(f"\n[Pass 1: Skipped — single-narrator mode ({single_narrator})]")
    elif enhanced_sections:
        print(f"\n[Pass 1: Skipped — pre-saved enhanced sections already include consistency review]")
    elif context_parts:
        print(f"\n[Pass 1: Consistency check | model: {args.model}]")
        print("=" * 60)
        consistency_parts = ["## Session Recap\n\n" + recap.strip()]
        if session_summary:
            consistency_parts.append(
                "## This Session — VTT Summary (authoritative event log)\n\n"
                + session_summary.strip()
            )
        consistency_parts.append(
            "## Campaign Context\n\n" + "\n\n---\n\n".join(context_parts)
        )
        consistency_prompt = "\n\n---\n\n".join(consistency_parts)
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

        # Save to disk so the user can read the report on its own (it also
        # gets folded into Pass 2's enhanced_sections.md, but that's buried
        # in a much larger file).
        report_dir = extract_dir or per_scene_output_dir
        if report_dir and consistency_report.strip():
            report_out = report_dir / "consistency_report.md"
            report_out.write_text(consistency_report, encoding="utf-8")
            print(f"  Consistency report saved: {report_out}")
    else:
        print("\n[Pass 1: Consistency check skipped — no --context files provided]")

    # ── Pass 2: Enhance structured sections ───────────────────────────────────
    if from_extractions_dir or single_narrator:
        if not from_extractions_dir:
            print(f"[Pass 2: Skipped — single-narrator mode]")
    elif renarration_mode:
        print("\n[Pass 2: Skipped — re-narration (--plan-file + --scene)]")
    elif enhanced_sections:
        print(f"\n[Pass 2: Skipped — using pre-saved enhanced sections ({len(enhanced_sections):,} chars)]")
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
        enhanced_sections = stream_api(client, ENHANCE_SYSTEM, enhance_prompt, args.model,
                                       verbose=args.verbose)
        print("=" * 60)

        # Save to disk so the user can review, edit, and reuse in narration
        cache_dir = extract_dir or per_scene_output_dir
        if cache_dir and enhanced_sections:
            enhanced_out = cache_dir / "enhanced_sections.md"
            enhanced_out.write_text(enhanced_sections, encoding="utf-8")
            print(f"  Enhanced sections saved: {enhanced_out}")

    # ── Pass 3: Narrative plan ─────────────────────────────────────────────────
    if args.plan_file:
        plan_path = Path(args.plan_file).expanduser()
        if not plan_path.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        plan_text = plan_path.read_text(encoding="utf-8")
        print(f"\n[Pass 3: Narrative plan loaded from {plan_path.name}]")
    else:
        chunk_count = len(roleplay_extractions) if roleplay_extractions else len(scene_extractions)
        print(f"\n[Pass 3: Narrative plan | {chunk_count} {'scene' if scene_extractions else 'chunk'}(s) | model: {args.model}]")
        print("=" * 60)

        plan_parts: list[str] = []
        if args.session_name:
            plan_parts.append(f"# Session: {args.session_name}")
        if characters:
            plan_parts.append("## Available narrators\n" + "\n".join(f"- {c}" for c in characters))
        if roleplay_extractions:
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
        if session_summary:
            plan_parts.append(
                "## Session Summary (authoritative — use to understand the full event arc "
                "and assign scenes to the character with the most interesting perspective)\n\n"
                + session_summary.strip()
            )
        if party:
            plan_parts.append(f"## Party Document\n\n{party.strip()}")
        if args.by_scene:
            scene_lines: list[str] = []
            if scene_extractions:
                # Authoritative checklist: the scene_extractions/ directory.
                # The recap is irrelevant here — the user has already committed to
                # the human-verified scene list when they ran scene_extract.py.
                scene_lines = [f"### {sx['name']}" for sx in scene_extractions]
            else:
                # Fall back to the recap's ## Scenes section.
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
                source = "scene_extractions/" if scene_extractions else "recap"
                plan_parts.append(
                    f"## Session Scenes (from {source} — every scene below must "
                    f"appear in your plan, in this exact order)\n\n"
                    + checklist
                )

        plan_system = PLAN_SCENE_SYSTEM if args.by_scene else PLAN_SYSTEM
        plan_text = stream_api(client, plan_system, "\n\n---\n\n".join(plan_parts), args.model,
                               verbose=args.verbose)
        print("=" * 60)

    plan_total_chunks = len(roleplay_extractions) or len(scene_extractions) or 1
    sections = parse_plan(plan_text, plan_total_chunks)
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

    # Plan-position lookup for the Phase 3 contrast signal — survives --scene
    # filtering so single-scene runs can still look up the prior narrator.
    plan_narrator_by_scene: dict[int, str] = {
        idx: s["narrator"] for idx, s in enumerate(sections, 1)
    }

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

    # Save the plan alongside extractions so --from-extractions can reload it.
    # Must happen before the --plan-only return so Plan & Check actually
    # writes plan.md (with narrators and per-scene focus) to disk.
    plan_cache_dir = extract_dir or per_scene_output_dir
    if plan_cache_dir:
        plan_save = plan_cache_dir / "plan.md"
        plan_save.write_text(plan_text, encoding="utf-8")
        print(f"  Plan saved to: {plan_save}")

    if args.plan_only:
        return

    if extract_dir:
        # Mandatory human checkpoint: stop here so the user can review plan.md
        # before Pass 4 commits tokens to per-scene extraction.
        # Does NOT fire when --plan-file was supplied (human already reviewed it),
        # --from-extractions is active (narration-only mode), or --no-plan-review.
        if not args.plan_file and not from_extractions_dir and not args.no_plan_review:
            print(
                f"\n[Pass 3 checkpoint] Review the plan before running extraction:\n"
                f"  {plan_save}\n\n"
                f"Then re-run with:\n"
                f"  --plan-file {plan_save} --extract-only\n"
                f"  or --from-extractions {extract_dir}  (if extractions already exist)"
            )
            return

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

        # Extraction pulls verbatim dialogue — output scales with input size.
        # Estimate ~1 output token per 4 input chars, with a floor of 1500 and cap of 8192.
        extract_tokens = 4096  # updated after prompt is built (scene mode)
        narrate_tokens = args.narrate_tokens or 16000
        file_token_override: int | None = None

        # Pass 4: character-specific extraction (silent)
        scene_summary_override: str | None = None
        if scene_extractions:
            # Scene-anchored mode — Pass 4 is skipped. Load the scene file by
            # name match (case-insensitive); fall back to the i-th file.
            match: dict | None = None
            sn = (scene_name or "").lower().strip()
            if sn:
                for sx in scene_extractions:
                    if sx["name"].lower().strip() == sn:
                        match = sx
                        break
            if match is None and 1 <= i <= len(scene_extractions):
                match = scene_extractions[i - 1]
            if match is None:
                print(f"Error: no scene extraction matches '{scene_name}' (scene {i}).",
                      file=sys.stderr)
                sys.exit(1)
            char_moments = match["moments"] or match["body"]
            scene_summary_override = match["summary"] or None
            print(f"\n[Pass 4 scene {i}: Skipped — scene-anchored extraction loaded — {label}]")
            est = estimate_narration_tokens(char_moments)
            warn = f"  ⚠ estimated {est} — add 'tokens: {est}' to override" if est > narrate_tokens else ""
            print(f"  → {len(char_moments):,} chars from {match['path'].name}"
                  f"  (limit: {narrate_tokens}, est. ~{est}){warn}")
        elif from_extractions_dir:
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
            if npc_roster:
                char_extract_system = char_extract_system + "\n\n" + npc_roster
            char_extract_prompt = build_char_extract_prompt(
                section, roleplay_extractions, summary_extractions or None,
                roster, recap, session_summary
            )

            # Scale extraction tokens with input — verbatim dialogue extraction
            # produces output roughly proportional to the roleplay content in scope.
            # Floor 1500, cap 8192.
            if scene_name:
                extract_tokens = min(8192, max(1500, len(char_extract_prompt) // 4))

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
        char_examples = (get_char_examples(per_char_examples, narrator)
                         if per_char_examples else None)
        # Phase 3 contrast: sample the previous narrator's voice from their
        # per-char examples (not from the prior scene's output) so single-scene
        # runs from the UI still get the contrast signal.
        prev_narrator = plan_narrator_by_scene.get(i - 1)
        prev_voice_sample = None
        if prev_narrator and prev_narrator.lower() != narrator.lower():
            prev_text = (get_char_examples(per_char_examples, prev_narrator)
                         if per_char_examples else None)
            if prev_text:
                prev_voice_sample = extract_contrast_sample(prev_text)
            else:
                prev_narrator = None
        # In --from-extractions mode the extraction file IS the scope — do not pass
        # scene_text or the model will narrate content from the recap that the user
        # intentionally left out of the extraction.
        scene_events_str = ""
        if scene_summary_override:
            # Scene-anchored mode: the extraction file already carries the
            # gm-assist scene body. That is the authoritative event skeleton.
            scene_events_str = scene_summary_override
        elif not from_extractions_dir:
            if enhanced_sections and scene_name:
                scene_events_str = extract_scene_text(enhanced_sections, scene_name)
            elif scene_name and recap:
                scene_events_str = extract_scene_text(recap, scene_name)
        narrate_context = context_parts if args.reflections and context_parts else None
        extras = [x for x in ["voice notes" if voice_note else "",
                               "per-char examples" if char_examples else "",
                               "prev-narrator contrast" if prev_voice_sample else "",
                               "roleplay summary" if roleplay_summary else "",
                               "enhanced context" if (scene_events_str or narrate_context) else ""] if x]
        print(f"[Pass 5 scene {i}: Narrate — {label}"
              f"{' (' + ', '.join(extras) + ')' if extras else ''}]")
        print("─" * 60)
        # In scene mode skip the heavy examples block to keep the prompt lean —
        # the style constraint is already carried by voice notes and the handoff.
        narrate_system = build_narrate_system(
            None if scene_name else examples_text,
            scene=scene_name or None,
            prose_mode=args.prose_mode,
            has_scene_events=bool(scene_events_str or narrate_context),
            scene_anchored=bool(scene_extractions and scene_summary_override),
            narrator=narrator,
            char_examples=char_examples,
            voice_note=voice_note,
            genre=args.narration_genre,
        )
        narrate_prompt = build_narrate_prompt(narrator, focus, char_moments, party, handoff,
                                              roster, roleplay_summary,
                                              scene_text=scene_events_str or None,
                                              context_docs=narrate_context,
                                              prev_narrator=prev_narrator,
                                              prev_voice_sample=prev_voice_sample)
        narration = stream_api(client, narrate_system, narrate_prompt,
                               args.model, max_tokens=narrate_tokens, verbose=args.verbose)
        print("─" * 60)

        narration = narration.strip()
        section_texts.append((label, narration))
        handoff = narration.rsplit("\n", 1)[-1].strip().strip('"').strip("'")

        # Stage 3 per-scene output: write narration to disk immediately so
        # users can edit single scenes and re-assemble via Stage 4.
        if per_scene_output_dir is not None:
            slug_scene = re.sub(r"[^a-z0-9]+", "_", (scene_name or narrator).lower()).strip("_")
            session_id = recap_path.parent.name
            per_scene_file = per_scene_output_dir / f"session_doc_scene_{i:02d}_{slug_scene}.md"
            frontmatter = (
                "---\n"
                f"scene: {i:02d}\n"
                f"slug: {slug_scene}\n"
                f"narrator: {narrator}\n"
                f"scene_name: {scene_name}\n"
                f"session: {session_id}\n"
                "---\n\n"
            )
            per_scene_file.write_text(frontmatter + narration + "\n", encoding="utf-8")
            print(f"  Wrote per-scene narration: {per_scene_file.name}")

    if args.extract_only:
        print(f"\nExtractions saved to: {extract_dir}")
        print("Review and edit the files, then re-run with --from-extractions to narrate.")
        return

    if per_scene_output_dir is not None and args.output is None:
        print(f"\nWrote {len(section_texts)} per-scene narration file(s) to: {per_scene_output_dir}")
        print("Run assemble.py to combine them into a single session document.")
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
                 ("Structured Sections", enhanced_sections),
                 ("Narrative Plan", plan_text)] +
                [(f"Section — {n}", t) for n, t in section_texts]
            )
        log_file = save_log(str(output.parent / "logs"), log_sections, stem="session_doc")
        print(f"Log saved to: {log_file}")


if __name__ == "__main__":
    main()
