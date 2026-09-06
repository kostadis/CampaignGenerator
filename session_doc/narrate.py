"""Narrate-prompt construction for session_doc and sd_narrate.

Holds Pass 5's prompt templates (loaded from config/agents/session_doc/narrate/)
and the build_narrate_system / build_narrate_prompt composition logic plus
the token-budget estimator used by the per-scene loop.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from campaignlib import load_agent_prompt, split_batched_response

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _fill(template: str, **values: str) -> str:
    """Substitute every ``{placeholder}`` in ``template``, and prove it.

    Replaces the ``.replace()`` chains this module used to build prompts with.
    A chain is a list of intentions that nothing checks: delete one line and the
    template's ``{rendering_instruction}`` survives into the prompt as literal
    text, which is #302's failure with the direction reversed — still silent,
    still green (found reviewing #302 itself).

    Here the substitution is driven by the template, so a value that is not
    supplied cannot be skipped: it raises. And because the walk emits each
    value verbatim rather than re-scanning the joined result, a rulebook or
    voice spec that happens to contain ``{narrator}`` is passed through
    untouched instead of being mistaken for an unsubstituted placeholder.
    """
    out: list[str] = []
    pos = 0
    for m in _PLACEHOLDER_RE.finditer(template):
        name = m.group(1)
        if name not in values:
            raise ValueError(
                f"narrate prompt assembly is missing a value for "
                f"{{{name}}} — the template asks for it and nothing supplies "
                f"it, so it would reach the model as literal text."
            )
        out.append(template[pos:m.start()])
        out.append(values[name])
        pos = m.end()
    out.append(template[pos:])
    return "".join(out)


def _template_candidates(name: str) -> list[str]:
    """The paths ``load_agent_prompt`` searches, in its order.

    Named in the drift error because the campaign override wins: reporting only
    the repo's copy sends a GM to a file that is correct, with no hint that a
    different one was loaded (mirrors ``load_agent_prompt``'s own
    FileNotFoundError, which lists both).
    """
    rel = Path("config/agents") / f"{name}.md"
    repo_root = Path(__file__).resolve().parents[1]
    return [str(Path.cwd() / rel), str(repo_root / rel)]


def _load_template(name: str, *placeholders: str) -> str:
    """Load a narrate template and verify its placeholders, both directions.

    ``load_agent_prompt`` already offers exactly this check — "every ``{key}``
    in the template must appear in ``placeholders``, and every key in
    ``placeholders`` must appear in the template [...] so prompt drift surfaces
    loudly instead of silently producing a malformed prompt" — but only when a
    ``placeholders`` dict is passed, and this module cannot pass one: the
    values are computed per call, conditionally, while the templates are
    constants loaded once at import.

    So the module declined the check and hand-rolled ``str.replace`` instead,
    which is a no-op on an absent needle. Renaming ``{genre_directive}`` in
    ``base.md`` deleted the genre rulebook from every system prompt with no
    error, no warning and a green suite (#302) — in the pipeline that had just
    lost that rulebook for months (#295).

    This restores the guarantee against the names the module actually
    substitutes. A campaign override under ``config/agents/`` is checked too,
    since ``load_agent_prompt`` resolves those first — an override that drops a
    placeholder is exactly the silent case worth failing on.

    Called via ``_load_template_deferred`` at import; the error it raises is
    held and re-raised by the prompt builders, so a drifted template does not
    take down the rest of the package. See that constant's note.

    This is one half of the contract. The other is ``_fill``, which guarantees
    every placeholder the template *does* have receives a value — the two
    together close both directions.
    """
    text = load_agent_prompt(name)
    found = set(_PLACEHOLDER_RE.findall(text))
    expected = set(placeholders)
    if found != expected:
        missing = sorted(expected - found)
        unknown = sorted(found - expected)
        detail = []
        if missing:
            detail.append(
                f"template is missing {missing} — the code substitutes "
                f"{'them' if len(missing) > 1 else 'it'}, so "
                f"{'those blocks' if len(missing) > 1 else 'that block'} "
                f"would silently never appear in the prompt"
            )
        if unknown:
            detail.append(
                f"template contains {unknown}, which nothing substitutes — "
                f"{'they' if len(unknown) > 1 else 'it'} would reach the model "
                f"as literal text"
            )
        searched = "\n    ".join(_template_candidates(name))
        raise ValueError(
            f"{name}.md placeholder drift: " + "; ".join(detail)
            + f"\n  loaded from the first of:\n    {searched}"
        )
    return text


#: A drifted template must not take down `import session_doc`.
#:
#: `session_doc/__init__.py` re-exports these constants, so raising at import
#: made a bad narrate template break everything in the package: the editor's
#: `GET /api/scenes` (which only wants `parse_plan`) 500s, and sd_consistency,
#: sd_plan, sd_corrections and assemble refuse to start — none of which build a
#: narrate prompt. `server/main.py` chdirs into the campaign, so a GM's own
#: `config/agents/` override is enough to trigger it. The error is held here
#: and raised by the two functions that actually assemble a prompt, which is
#: where the damage is and where the message makes sense (found reviewing #302).
_TEMPLATE_ERROR: Exception | None = None


def _load_template_deferred(name: str, *placeholders: str) -> str:
    global _TEMPLATE_ERROR
    try:
        return _load_template(name, *placeholders)
    except ValueError as exc:
        if _TEMPLATE_ERROR is None:
            _TEMPLATE_ERROR = exc
        return ""          # never reaches a prompt: _require_templates() raises


def _require_templates() -> None:
    """Raise the deferred drift error, if any. Called before any prompt build."""
    if _TEMPLATE_ERROR is not None:
        raise _TEMPLATE_ERROR


NARRATE_SYSTEM_BASE        = _load_template_deferred(
    "session_doc/narrate/base",
    "genre_directive", "examples_block", "scene_scope_line", "scene_events_line",
    "rendering_instruction", "length_instruction", "dialogue_instruction",
)
EXAMPLES_BLOCK             = _load_template_deferred(
    "session_doc/narrate/examples_block", "examples")
PER_CHAR_EXAMPLES_BLOCK    = _load_template_deferred(
    "session_doc/narrate/per_char_examples", "narrator", "examples")
VOICE_SPEC_BLOCK           = _load_template_deferred(
    "session_doc/narrate/voice_spec", "narrator", "voice_note")
PREV_VOICE_CONTRAST_BLOCK  = _load_template_deferred(
    "session_doc/narrate/prev_voice_contrast",
    "prev_narrator", "prev_voice_sample", "narrator")
DIALOGUE_INSTRUCTION_FULL        = _load_template_deferred(
    "session_doc/narrate/dialogue_full")
DIALOGUE_INSTRUCTION_CONDITIONAL = _load_template_deferred(
    "session_doc/narrate/dialogue_conditional")
PROSE_MODE_INSTRUCTION     = _load_template_deferred("session_doc/narrate/prose_mode")
SCENE_ANCHORED_DIRECTIVE   = _load_template_deferred(
    "session_doc/narrate/scene_anchored", "narrator")
BUNDLE_SYSTEM_BASE         = _load_template_deferred(
    "session_doc/narrate/bundle_base",
    "genre_directive", "shared_examples_block", "prose_mode_block",
    "shared_context", "scene_count", "dialogue_instruction",
)
BUNDLE_SCENE_TEMPLATE      = _load_template_deferred(
    "session_doc/narrate/bundle_scene",
    "index", "scene_name", "narrator", "focus", "scene_events",
    "moments", "voice_block", "examples_block", "contrast_block",
)

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
    _require_templates()
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
    result = _fill(NARRATE_SYSTEM_BASE,
                   genre_directive=genre_block,
                   examples_block=block,
                   scene_scope_line=scope,
                   scene_events_line=scene_events_line,
                   rendering_instruction=rendering,
                   length_instruction=length,
                   dialogue_instruction=dialogue)
    if scene_anchored and narrator:
        result += "\n\n" + _fill(SCENE_ANCHORED_DIRECTIVE, narrator=narrator)
    if prose_mode:
        result += "\n\n" + PROSE_MODE_INSTRUCTION
    if char_examples and narrator:
        result += "\n\n" + _fill(PER_CHAR_EXAMPLES_BLOCK,
                                 narrator=narrator,
                                 examples=char_examples.strip())
    if voice_note and narrator:
        result += "\n\n" + _fill(VOICE_SPEC_BLOCK,
                                 narrator=narrator,
                                 voice_note=voice_note.strip())
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


@dataclass(frozen=True)
class NarrationScene:
    """One full-plan narration scene prepared before a bundle call."""

    index: int
    scene_name: str
    narrator: str
    focus: str
    source_path: Path
    source_kind: str
    scene_events: str
    moments: str
    voice_note: str | None
    character_examples: str | None
    previous_narrator: str | None
    previous_voice_sample: str | None
    estimated_output_tokens: int
    output_path: Path
    output_existed: bool

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError("narration scene index must be positive")
        if self.source_kind not in {"base", "override"}:
            raise ValueError("narration scene source_kind must be base or override")

    def split_entry(self) -> dict:
        return {"i": self.index, "name": self.scene_name}


@dataclass(frozen=True)
class BundleSelection:
    """Validated, ordered scope for exactly one bundled exchange."""

    scenes: tuple[NarrationScene, ...]
    bundle_ceiling: int
    provider_batch: bool = False

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ValueError("bundled narration requires at least one selected scene")
        indices = [scene.index for scene in self.scenes]
        if any(i < 1 for i in indices) or len(set(indices)) != len(indices):
            raise ValueError("bundled narration scene indices must be unique and positive")
        if indices != sorted(indices):
            raise ValueError("bundled narration scenes must be in full-plan order")
        if self.bundle_ceiling < 1:
            raise ValueError("--batch-max-tokens must be a positive integer")

    @property
    def projected_output_tokens(self) -> int:
        # Covers both sentinel lines and whitespace around each section. It is
        # deliberately small and fixed; narration prose dominates the estimate.
        return sum(s.estimated_output_tokens + 32 for s in self.scenes)


def _genre_block(genre: str | None) -> str:
    if not genre or not genre.strip():
        return ""
    value = genre.strip()
    if "\n" in value or len(value) > GENRE_INLINE_MAX_CHARS:
        return ("GENRE & REGISTER (campaign-specific) — BEGIN\n"
                f"{value}\nGENRE & REGISTER — END")
    return f"GENRE: {value}"


def _shared_narration_context(*, party: str | None, roster: str,
                              npc_roster: str,
                              context_docs: list[str] | None) -> str:
    parts: list[str] = []
    if roster:
        parts.append("## Character Classes (definitive — never contradict these)\n\n" + roster)
    if npc_roster:
        parts.append(
            "## Known NPCs — canonical spellings for NARRATION ONLY\n\n"
            "Use these spellings only in prose. Never alter words inside quotation marks.\n\n"
            + npc_roster
        )
    if party:
        parts.append(
            "## Party Document (authoritative source for character classes, abilities, and roles)\n\n"
            + party.strip()
        )
    if context_docs:
        parts.append(
            "## Campaign History\n\nUse this only for brief, relevant memories; do not summarize it.\n\n"
            + "\n\n---\n\n".join(context_docs)
        )
    return "\n\n---\n\n".join(parts)


def build_bundled_narrate_prompts(
    scenes: list[NarrationScene] | tuple[NarrationScene, ...],
    *,
    shared_examples: str | None = None,
    party: str | None = None,
    roster: str = "",
    npc_roster: str = "",
    context_docs: list[str] | None = None,
    prose_mode: bool = False,
    genre: str | None = None,
) -> tuple[str, str]:
    """Build one shared system prompt and ordered scene-packet user prompt."""
    _require_templates()
    if not scenes:
        raise ValueError("cannot build a narration bundle with no scenes")
    shared_style = (
        _fill(EXAMPLES_BLOCK, examples=shared_examples.strip())
        if shared_examples else ""
    )
    system = _fill(
        BUNDLE_SYSTEM_BASE,
        genre_directive=_genre_block(genre),
        shared_examples_block=shared_style,
        prose_mode_block=PROSE_MODE_INSTRUCTION if prose_mode else "",
        dialogue_instruction=DIALOGUE_INSTRUCTION_CONDITIONAL,
        shared_context=_shared_narration_context(
            party=party, roster=roster, npc_roster=npc_roster,
            context_docs=context_docs,
        ),
        scene_count=str(len(scenes)),
    )
    packets: list[str] = []
    for scene in scenes:
        voice_block = (
            _fill(VOICE_SPEC_BLOCK, narrator=scene.narrator,
                  voice_note=scene.voice_note.strip())
            if scene.voice_note else ""
        )
        examples_block = (
            _fill(PER_CHAR_EXAMPLES_BLOCK, narrator=scene.narrator,
                  examples=scene.character_examples.strip())
            if scene.character_examples else ""
        )
        contrast_block = (
            _fill(PREV_VOICE_CONTRAST_BLOCK,
                  prev_narrator=scene.previous_narrator,
                  prev_voice_sample=scene.previous_voice_sample.strip(),
                  narrator=scene.narrator)
            if scene.previous_narrator and scene.previous_voice_sample else ""
        )
        packets.append(_fill(
            BUNDLE_SCENE_TEMPLATE,
            index=f"{scene.index:02d}", scene_name=scene.scene_name,
            narrator=scene.narrator, focus=scene.focus,
            scene_events=scene.scene_events.strip(), moments=scene.moments.strip(),
            voice_block=voice_block, examples_block=examples_block,
            contrast_block=contrast_block,
        ))
    return system.strip(), "\n\n".join(packets).strip()


_BUNDLE_MARKER_RE = re.compile(
    r"^<<<CG-SCENE (\d+) (?:(BEGIN): (.*)|(END))>>>[ \t\r]*$", re.MULTILINE
)


def split_bundled_narration(text: str, scenes: list[NarrationScene] | tuple[NarrationScene, ...]) -> dict:
    """Validate bundle order/end pairing, then use the shared scene splitter."""
    expected = [scene.index for scene in scenes]
    seen_begins: list[int] = []
    open_index: int | None = None
    for marker in _BUNDLE_MARKER_RE.finditer(text):
        index = int(marker.group(1))
        if marker.group(2) == "BEGIN":
            seen_begins.append(index)
            if open_index is not None:
                return {
                    "failed": True, "failure_reason": "NESTED_SECTION",
                    "failure_detail": (
                        f"scene {index:02d} BEGIN appears before scene "
                        f"{open_index:02d}'s END"
                    ),
                    "sections": [],
                }
            open_index = index
        else:
            if open_index is None or index != open_index:
                return {
                    "failed": True, "failure_reason": "MISMATCHED_END",
                    "failure_detail": f"END {index:02d} does not close the open scene",
                    "sections": [],
                }
            open_index = None
    expected_positions = {index: pos for pos, index in enumerate(expected)}
    known_begins = [i for i in seen_begins if i in expected_positions]
    if any(expected_positions[a] > expected_positions[b]
           for a, b in zip(known_begins, known_begins[1:])):
        return {
            "failed": True, "failure_reason": "OUT_OF_ORDER",
            "failure_detail": "response scene sections are not in requested plan order",
            "sections": [],
        }
    return split_batched_response(text, [scene.split_entry() for scene in scenes])


def build_narrate_prompt(narrator: str, focus: str, char_moments: str,
                          party: str | None, handoff: str, roster: str = "",
                          scene_text: str | None = None,
                          context_docs: list[str] | None = None,
                          prev_narrator: str | None = None,
                          prev_voice_sample: str | None = None,
                          npc_roster: str = "") -> str:
    _require_templates()
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
        parts.append(_fill(PREV_VOICE_CONTRAST_BLOCK,
                           prev_narrator=prev_narrator,
                           prev_voice_sample=prev_voice_sample.strip(),
                           narrator=narrator))
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
