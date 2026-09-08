"""What the gap-marking mode puts in the prompt, and what it takes out — #454.

`sd_narrate` asks one call to reshape recorded dialogue *and* author the scene
around it. Where the source attributes a passage to the GM, the prompt forbids
"the GM as a character" and offers no third option, so silent reassignment is
the compliant move: of six drafts of one scene by three renderers, four gave
the GM's explanation to a player character, dissolved it into a PC's own
observation, or dropped it, and the finished prose does not say which.

The contract that fixes it was tested against a standalone experiment prompt
that this repo does not use. Two fragments of the prompt it *does* use instruct
exactly the absorption the contract forbids — `writing_brief.md` always, and
`prose_mode.md` under `--prose-mode`. These tests are the port's guarantee:
whichever rule is in force is the **only** one present.

Byte-identity for the mode-off half lives in
`tests/test_prompt_golden_pre_feature.py`. This file is the mode-on half.

None of it is a claim about what the model *does* with the prompt. That is what
the re-confirmation run against `accepted_gaps.json` is for.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.narrate import build_narrate_system  # noqa: E402

#: The sentence the contract contradicts. Its first clause is the conflict; it
#: appears in `writing_brief.md` always and in `prose_mode.md` under prose mode.
ABSORBING_CLAUSE = "GM descriptions become experienced facts"

#: The marker the contract asks for, and the phrase that makes it non-optional.
MARKER_OPEN = "[GM NARRATION — TO BE WRITTEN:"
MARKER_REQUIRED = "required output, not commentary"

#: The rule that must survive the port: adjudication is still dropped.
ADJUDICATION_RULE = "only confirms or adjudicates"

NARRATOR = "Brewbarry"


def prompt(*, gap_marking: bool, prose_mode: bool = False) -> str:
    return build_narrate_system(
        examples_text=None,
        scene="The Wave Echo Chamber",
        prose_mode=prose_mode,
        narrator=NARRATOR,
        gap_marking=gap_marking,
    )


# ── P2: the contradiction is gone ───────────────────────────────────────────

@pytest.mark.parametrize("prose_mode", [False, True])
def test_gap_on_removes_every_instruction_to_absorb_gm_description(prose_mode):
    """FR-004 binds every fragment carrying the sentence, not only the always-on
    one. Parametrised over prose mode because that is the second copy, and the
    one an implementation forgets: it is off by default, so a spot check on the
    default path passes while the mode that most needs the contract still
    argues with it."""
    assert ABSORBING_CLAUSE not in prompt(gap_marking=True, prose_mode=prose_mode)


@pytest.mark.parametrize("prose_mode", [False, True])
def test_gap_off_keeps_it(prose_mode):
    """The other half of the switch. Off is today's behaviour, unchanged —
    asserted here as intent, and byte-for-byte in the frozen-golden module."""
    assert ABSORBING_CLAUSE in prompt(gap_marking=False, prose_mode=prose_mode)


# ── P3: the marker is asked for, and is not optional ────────────────────────

@pytest.mark.parametrize("prose_mode", [False, True])
def test_gap_on_asks_for_the_marker_on_its_own_line(prose_mode):
    p = prompt(gap_marking=True, prose_mode=prose_mode)
    assert MARKER_OPEN in p
    assert "on its own line" in p


@pytest.mark.parametrize("prose_mode", [False, True])
def test_gap_on_says_the_markers_are_required_output(prose_mode):
    """Tested wording, kept verbatim. Without it a model reads the marker as an
    editorial aside it may decline to emit, and a scene with no markers is
    indistinguishable from a scene with no GM description in it."""
    assert MARKER_REQUIRED in prompt(gap_marking=True, prose_mode=prose_mode)


def test_gap_off_asks_for_no_marker():
    assert MARKER_OPEN not in prompt(gap_marking=False)
    assert MARKER_OPEN not in prompt(gap_marking=False, prose_mode=True)


# ── P4: adjudication is still dropped ───────────────────────────────────────

@pytest.mark.parametrize("prose_mode", [False, True])
def test_gap_on_keeps_the_adjudication_rule(prose_mode):
    """The contract narrows what is written, not what is dropped. A GM turn that
    only confirms a player's question is table operation and stays dropped —
    gapping those would bury the real gaps under `"Yep."`"""
    assert ADJUDICATION_RULE in prompt(gap_marking=True, prose_mode=prose_mode)


# ── The contract arrives whole ──────────────────────────────────────────────

@pytest.mark.parametrize("fragment", [
    "must not become a character's speech, perception, memory, or inference",
    "must not be absorbed unmarked into the narrator's voice",
    "is the human author's to write",
    "Write everything the players said and did normally",
])
def test_each_clause_of_the_tested_contract_reaches_the_prompt(fragment):
    """Verbatim from `experiments/20260907-phandalin-fable-gm-gaps/prompt.diff`.

    The wording is the tested artifact — the 31 accepted gaps were produced by
    these exact sentences — so a paraphrase invalidates the transfer that
    `accepted_gaps.json` is the fixture for.
    """
    assert fragment in prompt(gap_marking=True)


# ── P6: the rule is stated once ─────────────────────────────────────────────

@pytest.mark.parametrize("prose_mode", [False, True])
def test_the_contract_appears_exactly_once(prose_mode):
    """Not once per fragment, and not once per mode with the other still there.

    #435 is the precedent: `scene_anchored.md` and `bundle_scene.md` each
    restated three rules the brief already owned, the restatements had drifted
    from the brief and from each other, and nothing failed. A repeated rule
    becomes two rules.

    **Binds gap-ON only, and that narrowing is the point.** Gap-off with prose
    mode on carries the absorbing clause *twice* — once from the brief and once
    from the prose block — and always has. That duplication is the state #454
    describes, and FR-005 forbids touching it: deduplicating would move the
    gap-off prompt for every render a GM has not opted into. See
    `test_gap_off_keeps_its_pre_existing_duplication` below, which pins it so
    that nobody tidies it by accident.
    """
    p = prompt(gap_marking=True, prose_mode=prose_mode)
    assert p.count("Where the source attributes a passage to the GM") == 1
    assert p.count(ABSORBING_CLAUSE) == 0


@pytest.mark.parametrize("prose_mode,expected", [(False, 1), (True, 2)])
def test_gap_off_keeps_its_pre_existing_duplication(prose_mode, expected):
    """Today's state, pinned rather than fixed.

    `writing_brief.md` and `prose_mode.md` each carry the absorbing clause, so
    prose mode has always delivered it twice. This feature is not licensed to
    change that — FR-005 makes gap-off byte-identical, and a tidy-up here would
    silently alter every existing render.

    Recorded as an assertion so the asymmetry with the test above reads as a
    decision rather than as an oversight.
    """
    assert prompt(gap_marking=False, prose_mode=prose_mode).count(
        ABSORBING_CLAUSE) == expected


def test_gap_on_with_prose_on_keeps_the_compatible_clause_and_drops_the_other():
    """The prose fragment's two clauses are not the same fact.

    Its first clause conflicts with the contract and must go. Its second — that
    speech the GM supplies for an identified NPC or PC stays with that
    character — is a rule the contract never replaces, and it is what the
    tested model got right unprompted, writing the banker's ten turns as
    dialogue and gapping only the four descriptive passages.

    Asserted on both halves: a variant that dropped the whole sentence would
    pass a presence-only check on the first assertion alone.
    """
    p = prompt(gap_marking=True, prose_mode=True)
    assert ABSORBING_CLAUSE not in p
    assert "Speech the GM supplies for an identified NPC or PC" in p


def test_no_third_copy_of_the_rule_hides_in_another_fragment():
    """T018's grep, as an assertion rather than a one-off check.

    Two sites are known. This proves there is no third — including in the
    scene-anchored directive and the per-character blocks, which are exactly
    where #435 found rules the brief already owned.
    """
    every_flag_on = build_narrate_system(
        examples_text="An example.",
        scene="The Wave Echo Chamber",
        prose_mode=True,
        has_scene_events=True,
        scene_anchored=True,
        narrator=NARRATOR,
        char_examples="A character example.",
        voice_note="Clipped.",
        genre="First-person noir fantasy memoir",
        gap_marking=True,
    )
    assert ABSORBING_CLAUSE not in every_flag_on
    assert every_flag_on.count("Where the source attributes a passage to the GM") == 1


# ── P5: the bundle path carries the same contract ───────────────────────────

def _bundle(*, gap_marking: bool, prose_mode: bool = False) -> str:
    """The bundled prompt, built from the same scene fixture the apparatus
    producer test uses — one `NarrationScene` shape, not a second one that
    drifts from it."""
    from session_doc.narrate import build_bundled_narrate_prompts
    from test_narrate_template_contract import _bundle_scene

    system, user = build_bundled_narrate_prompts(
        [_bundle_scene(1, "Arrival", "Alice"), _bundle_scene(2, "Departure", "Bob")],
        prose_mode=prose_mode, gap_marking=gap_marking)
    return system + "\n" + user


@pytest.mark.parametrize("prose_mode", [False, True])
def test_the_bundle_path_carries_the_contract(prose_mode):
    """Per the GM's Q2 ruling the mode reaches both render paths rather than
    refusing the combination. A bundle rendered without the contract is the
    silent variant of the failure: a whole session of reassigned GM material
    that looks finished, in the mode where the GM believes they are protected.

    Note what this does NOT show. The contract's behavioural evidence is four
    scenes rendered as four separate calls; whether marker discipline survives
    one response carrying every scene is untested, and SC-009 is where that gets
    answered.
    """
    b = _bundle(gap_marking=True, prose_mode=prose_mode)
    assert ABSORBING_CLAUSE not in b
    assert MARKER_OPEN in b
    assert MARKER_REQUIRED in b
    assert ADJUDICATION_RULE in b


@pytest.mark.parametrize("prose_mode", [False, True])
def test_the_bundle_path_is_unchanged_with_the_mode_off(prose_mode):
    """`bundle_base.md` interpolates `{writing_brief}` too, so it moves if the
    placeholder was placed wrongly."""
    b = _bundle(gap_marking=False, prose_mode=prose_mode)
    assert ABSORBING_CLAUSE in b
    assert MARKER_OPEN not in b


def test_both_paths_use_one_contract_text():
    """One fragment, two render paths — never a bundle-specific variant, which
    is how two statements of a rule start."""
    per_scene = prompt(gap_marking=True)
    bundled = _bundle(gap_marking=True)
    clause = "must not be absorbed unmarked into the narrator's voice"
    assert clause in per_scene and clause in bundled


# ── FR-008: a missing contract refuses; it never renders without it ─────────

def test_the_contract_is_loaded_eagerly_so_a_missing_one_cannot_be_skipped():
    """FR-008 is satisfied by the existing loader, not by a second mechanism.

    `GM_ATTRIBUTION_GAP` is a module-level constant loaded through
    `load_agent_prompt`, which raises `FileNotFoundError` naming both candidate
    paths when the file is absent — at import, before any render. That is
    *stricter* than the contract asked for: it refuses whether or not gap
    marking is on, because a missing repo prompt fragment is corruption rather
    than a mode being unavailable, and it is how `name_fidelity.md`,
    `real_names.md` and every other fragment already behave.

    A gap-specific refusal inside `sd_narrate` would be a second statement of
    one rule — the thing this feature exists to stop doing.
    """
    from session_doc.narrate import GM_ATTRIBUTION_GAP

    assert GM_ATTRIBUTION_GAP.strip()
    assert MARKER_OPEN in GM_ATTRIBUTION_GAP


def test_a_missing_fragment_names_the_path_it_looked_for():
    """The half FR-008 cares about: the refusal is actionable."""
    from campaignlib.config import load_agent_prompt

    with pytest.raises(FileNotFoundError) as exc:
        load_agent_prompt("session_doc/narrate/gm_attribution_gap_absent")
    assert "config/agents/session_doc/narrate/gm_attribution_gap_absent.md" in str(exc.value)
