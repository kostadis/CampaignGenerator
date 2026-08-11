"""Narrate-prompt construction for session_doc and sd_narrate.

Holds Pass 5's prompt templates (loaded from config/agents/session_doc/narrate/)
and the build_narrate_system / build_narrate_prompt composition logic plus
the token-budget estimator used by the per-scene loop.
"""

import re

from campaignlib import load_agent_prompt

NARRATE_SYSTEM_BASE        = load_agent_prompt("session_doc/narrate/base")
EXAMPLES_BLOCK             = load_agent_prompt("session_doc/narrate/examples_block")
PER_CHAR_EXAMPLES_BLOCK    = load_agent_prompt("session_doc/narrate/per_char_examples")
VOICE_SPEC_BLOCK           = load_agent_prompt("session_doc/narrate/voice_spec")
PREV_VOICE_CONTRAST_BLOCK  = load_agent_prompt("session_doc/narrate/prev_voice_contrast")
DIALOGUE_INSTRUCTION_FULL        = load_agent_prompt("session_doc/narrate/dialogue_full")
DIALOGUE_INSTRUCTION_CONDITIONAL = load_agent_prompt("session_doc/narrate/dialogue_conditional")
PROSE_MODE_INSTRUCTION     = load_agent_prompt("session_doc/narrate/prose_mode")
SCENE_ANCHORED_DIRECTIVE   = load_agent_prompt("session_doc/narrate/scene_anchored")

# Longest genre value still delivered as an inline ``GENRE: ...`` label.
# Anything above this is a document and gets its own delimited block.
#
# Gate on SIZE, not on the presence of a newline (#276): out-of-the-abyss'
# 16,303-char genre spec reached narrate.genre as a paste that lost its line
# structure, so a newline test handed the campaign with the *largest* rulebook
# the weakest delivery — a one-line label, repeated whole in the tail reminder.
# Erring low here is cheap (the delimited form is never wrong for a short
# directive, only two lines more verbose); erring high is the bug.
GENRE_INLINE_MAX_CHARS = 200


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
        g = genre.strip()
        if "\n" in g or len(g) > GENRE_INLINE_MAX_CHARS:
            # A full genre document, not a one-line directive: give it its own
            # delimited block so it does not read as a run-on label wedged into
            # the preamble. The tail reminder at the end of this function is
            # unaffected and still fires (recency, for small local models).
            # A flattened paste has no newlines and is still a document, so
            # length decides too — see GENRE_INLINE_MAX_CHARS.
            genre_block = ("GENRE & REGISTER (campaign-specific) — BEGIN\n"
                           f"{g}\n"
                           "GENRE & REGISTER — END\n")
        else:
            genre_block = f"GENRE: {g}\n"
    else:
        genre_block = ""
    if scene:
        scope = (f"- The scene you are writing: **{scene}**\n"
                 f"  STOP when this scene ends. Do not continue into what happened next.\n"
                 f"  Do not summarise what came before. Do not foreshadow what comes after.\n"
                 f"  This scene only.\n")
        length = ("Write as many paragraphs as needed to give every extracted moment its due — "
                  "do not compress multiple distinct beats into a single paragraph. "
                  "Target 600-900 words for a typical scene; expand each extracted moment into "
                  "2-3 sentences of observation, voice, or aside. Do NOT summarize the moments — "
                  "render each one with concrete sensory detail and the narrator's reaction. "
                  "EXPANSION MEANS NEW CONCRETE DETAIL drawn from the extracted moments. A beat "
                  "you have already rendered may not be restated, re-realised, or re-described "
                  "in different words to reach a length — that is padding, not narration. "
                  "If your draft is under 500 words AND extracted moments remain compressed or "
                  "unrendered, go back and expand those. If every moment has been given its due, "
                  "stop: a short complete scene beats a padded one. "
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
    if genre and genre.strip():
        # Repeat the genre directive at the tail of the prompt. The opening copy
        # is buried under ~150 lines of prose-mode/voice rules by the time
        # generation starts; smaller models lose the genre signal to recency.
        # Claude is unaffected by the duplicate — same instruction, same prompt.
        result += (
            "\n\nGENRE — FINAL REMINDER (this overrides any generic register the "
            "above rules suggest):\n" + genre.strip()
        )
    return result


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


def build_narrate_prompt(narrator: str, focus: str, char_moments: str,
                          party: str | None, handoff: str, roster: str = "",
                          scene_text: str | None = None,
                          context_docs: list[str] | None = None,
                          prev_narrator: str | None = None,
                          prev_voice_sample: str | None = None,
                          npc_roster: str = "") -> str:
    parts = [f"## Narrator: {narrator}\n## Focus: {focus}"]
    if roster:
        parts.append(f"## Character Classes (definitive — never contradict these)\n\n{roster}")
    if npc_roster:
        # The canonical-name channel that CANNOT corrupt a quote. Aliases used to
        # be applied to the source text as a find-and-replace before Pass 5, which
        # rewrote names inside verbatim dialogue (#223); they arrive as knowledge
        # now, so the caveat below has to be explicit or the model does the
        # substitution itself.
        parts.append(
            "## Known NPCs — canonical spellings for NARRATION ONLY\n\n"
            "Use these spellings in the prose you write. Never apply them inside "
            "quotation marks. A quoted line is a verbatim record of what somebody "
            "actually said, and the name they chose — a nickname, a title, a partial "
            "name, the wrong name — is part of what they said and part of what it "
            "reveals about them. Reproduce the speaker's own wording, then use the "
            "canonical spelling in your own sentences around it.\n\n"
            f"{npc_roster}"
        )
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
    if (prev_narrator and prev_voice_sample
            and prev_narrator.lower() != narrator.lower()):
        contrast = (PREV_VOICE_CONTRAST_BLOCK
                    .replace("{prev_narrator}", prev_narrator)
                    .replace("{prev_voice_sample}", prev_voice_sample.strip())
                    .replace("{narrator}", narrator))
        parts.append(contrast)
    if handoff:
        parts.append(f"## Handoff from previous narrator\n\"{handoff}\"")
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
