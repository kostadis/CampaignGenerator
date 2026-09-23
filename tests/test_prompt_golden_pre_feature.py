"""Gap marking off changes nothing — proved against a frozen golden (#454).

`tests/golden/prompts/narrate_system_matrix.json` already asserts byte-identity
across the narrate flag matrix, and it is the right mechanism for this. But its
own workflow is *regenerate when a prompt edit is intended*, and #454 intends
one: the matrix gains a `gap_marking` dimension and doubles. A regenerated
golden agrees with whatever was built, which proves nothing about the half that
was supposed not to move.

So `specs/028-gap-marking-contract/golden_pre_feature.json` is a copy of that
file taken **before the first template edit**, and this module compares the
gap-off half against it. The live golden guards future drift; this one proves
*this* change did not move the old half. Same shape as #453's `baseline.json`.

A failure here is never a reason to regenerate the frozen file. It says the
gap-off prompt moved, which is FR-005's violation and would silently change
every render a GM has not opted into.

**One entry legitimately differs, and it is asserted separately.**
`__PROSE_MODE_INSTRUCTION` in the golden is the *raw constant*, and that
constant is now a template carrying `{gm_attribution_prose}`. FR-005 binds the
assembled prompt, not the stored template — so what must match the frozen entry
is the block after substitution, which `test_the_rendered_prose_block_is_unchanged`
checks directly.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.narrate import (  # noqa: E402
    GM_ATTRIBUTION_PROSE_ABSORB,
    PROSE_MODE_INSTRUCTION,
    _fill,
    build_narrate_system,
)

FROZEN = ROOT / "specs/028-gap-marking-contract/golden_pre_feature.json"

# Committed with the feature, like the corpus in #453. A missing one is a real
# breakage, and skipping would turn it into a green run with no signal.
if not FROZEN.is_file():
    raise AssertionError(f"the frozen pre-feature prompt golden is missing: {FROZEN}")

GOLDEN = json.loads(FROZEN.read_text(encoding="utf-8"))

# Fixture values — must match those `_build_matrix` used to generate the golden.
EXAMPLES = "Once upon a time in Phandalin a brave druid faced a manticore..."
CHAR_EX = "Brewbarry whittled a stick, eyes on the door, saying nothing for once."
VOICE_NOTE = "Brewbarry speaks in short clipped lines. Dry humour. No exclamation points."
NARRATOR = "Brewbarry"


def _gap_off_matrix() -> dict[str, str]:
    """The 256 pre-feature combinations, rebuilt with gap marking off.

    Deliberately NOT `_build_matrix()` from `test_session_doc_prompts`: that one
    gains a `gap_marking` dimension in this feature, and a test proving the old
    half did not move must not be defined in terms of the thing that changed.
    """
    out: dict[str, str] = {}
    for examples_text in (None, EXAMPLES):
        for scene in (None, "The Wave Echo Chamber"):
            for prose_mode in (False, True):
                for has_scene_events in (False, True):
                    for scene_anchored in (False, True):
                        for char_examples in (None, CHAR_EX):
                            for voice_note in (None, VOICE_NOTE):
                                for genre in (None, "First-person noir fantasy memoir"):
                                    label = (
                                        f"ex{int(examples_text is not None)}"
                                        f"_sc{int(scene is not None)}"
                                        f"_pm{int(prose_mode)}"
                                        f"_se{int(has_scene_events)}"
                                        f"_sa{int(scene_anchored)}"
                                        f"_ce{int(char_examples is not None)}"
                                        f"_vn{int(voice_note is not None)}"
                                        f"_gn{int(genre is not None)}"
                                    )
                                    out[label] = build_narrate_system(
                                        examples_text=examples_text,
                                        scene=scene,
                                        prose_mode=prose_mode,
                                        has_scene_events=has_scene_events,
                                        scene_anchored=scene_anchored,
                                        narrator=NARRATOR,
                                        char_examples=char_examples,
                                        voice_note=voice_note,
                                        genre=genre,
                                    )
    return out


@pytest.fixture(scope="module")
def gap_off() -> dict[str, str]:
    return _gap_off_matrix()


def test_the_frozen_golden_covers_the_whole_matrix():
    """Guard on the guard: 256 assembled prompts and nine standalone entries.

    A frozen file that had lost entries would let combinations pass by being
    absent, which is the failure mode of every snapshot test nobody counts.
    """
    assembled = [k for k in GOLDEN if not k.startswith("__")]
    assert len(assembled) == 256
    assert len([k for k in GOLDEN if k.startswith("__")]) == 9


def test_every_gap_off_prompt_is_byte_identical_to_the_frozen_golden(gap_off):
    """FR-005 / contract P1, for the per-scene path.

    All 256 combinations, prose mode either way. Reported one combination at a
    time: a bulk dict comparison prints two 200KB blobs and names nothing.
    """
    assert set(gap_off) == {k for k in GOLDEN if not k.startswith("__")}
    for label in sorted(gap_off):
        assert gap_off[label] == GOLDEN[label], (
            f"gap-off prompt moved for {label}. This is FR-005's violation — "
            f"every render a GM has not opted into would change. Do not "
            f"regenerate {FROZEN.name}; fix the placement instead."
        )


@pytest.mark.parametrize("label", [k for k in sorted(GOLDEN) if "_pm1_" in k][:8])
def test_the_prose_mode_combinations_specifically(gap_off, label):
    """Prose mode carries the second copy of the sentence and is off by default,
    so it is the path a spot check misses. Called out by name rather than left
    to the sweep above."""
    assert gap_off[label] == GOLDEN[label]


def test_the_rendered_prose_block_is_unchanged():
    """The one entry that legitimately differs, checked in its rendered form.

    `PROSE_MODE_INSTRUCTION` is now a template carrying
    `{gm_attribution_prose}`, so the raw constant no longer equals its frozen
    entry. FR-005 binds the assembled prompt, and after substitution with the
    absorb variant the block is byte-identical to what it always was.
    """
    rendered = _fill(
        PROSE_MODE_INSTRUCTION,
        gm_attribution_prose=GM_ATTRIBUTION_PROSE_ABSORB.strip(),
    )
    assert rendered == GOLDEN["__PROSE_MODE_INSTRUCTION"]


@pytest.mark.parametrize("name", [
    "__CONSISTENCY_SYSTEM",
    "__PLAN_SYSTEM",
    "__DIALOGUE_INSTRUCTION_FULL",
    "__DIALOGUE_INSTRUCTION_COND",
    "__AUDIT_HATCH_INSTRUCTION",
    "__NAME_FIDELITY_INSTRUCTION",
    "__REAL_NAMES_INSTRUCTION",
])
def test_the_untouched_constants_are_untouched(name):
    """Everything except the prose-mode template should be bit-for-bit equal —
    this feature has no business anywhere near them."""
    import session_doc

    attr = {
        "__CONSISTENCY_SYSTEM": "CONSISTENCY_SYSTEM",
        "__PLAN_SYSTEM": "PLAN_SYSTEM",
        "__DIALOGUE_INSTRUCTION_FULL": "DIALOGUE_INSTRUCTION_FULL",
        "__DIALOGUE_INSTRUCTION_COND": "DIALOGUE_INSTRUCTION_CONDITIONAL",
        "__AUDIT_HATCH_INSTRUCTION": "AUDIT_HATCH_INSTRUCTION",
        "__NAME_FIDELITY_INSTRUCTION": "NAME_FIDELITY_INSTRUCTION",
        "__REAL_NAMES_INSTRUCTION": "REAL_NAMES_INSTRUCTION",
    }[name]
    assert getattr(session_doc, attr) == GOLDEN[name]
