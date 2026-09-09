"""The two extraction prompts must describe one speaker-label format — #459.

`scene_extract.md` (per-scene) and `scene_extract_batched.md` (all scenes, one
call) are separate files that ask for the same artifact. They had drifted: the
batched one wrote `**Speaker**` and spelled out why brackets are not part of a
label; the per-scene one still wrote `**[Speaker]**` four lines above
`**[scene tag — e.g. The Drow Spy Spotted]**`, so the speaker template and the
apparatus template were the same shape.

The model split both ways rather than guessing consistently. Across the four
sessions frozen in `experiments/20260907-phandalin-gm-gaps-confirm/inputs/`:

    brewbarry_source.md    95 labels,   1 bracketed
    soma_source.md        115 labels,   3 bracketed
    valphine_source.md     30 labels,  30 bracketed
    vukradin_source.md    134 labels, 134 bracketed

Two sessions copied the brackets onto every speaker; two did not. That is one
prompt producing two incompatible formats, and `session_doc/plan_eligibility.py`
exists partly to recover from it (#453).

The same runs truncated a name they were handed in full — `**[Valphine]**`
eight times against a roster declaring `Valphine Sotorra`, which resolves to
nobody and cost her every scene (#460). The speaker map rewrites VTT labels to
declared character names in code, before the model sees them, so that is a
label the model reformatted rather than one it inferred.

These tests do not check prose. They check that a rule with a demonstrated
failure behind it is present in both files, so fixing one and leaving the other
fails the build instead of shipping.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaignlib.config import load_agent_prompt  # noqa: E402

PER_SCENE = load_agent_prompt("scene_extract")
BATCHED = load_agent_prompt("scene_extract_batched")
BOTH = {"scene_extract": PER_SCENE, "scene_extract_batched": BATCHED}


def test_neither_prompt_shows_a_bracketed_speaker_template():
    """`**[Speaker]**` means the brackets metasyntactically and `**[scene tag
    — …]**` means them literally. Nothing in the text says which is which, and
    two of four corpus sessions read it the wrong way."""
    for name, text in BOTH.items():
        assert "**[Speaker]**" not in text, name


def test_both_prompts_show_the_same_unbracketed_speaker_template():
    for name, text in BOTH.items():
        assert "**Speaker** — *brief context*" in text, name


def test_both_prompts_state_that_brackets_are_not_part_of_a_label():
    for name, text in BOTH.items():
        assert "Square brackets are NOT part of a speaker label" in text, name


def test_neither_prompt_puts_the_words_scene_tag_in_its_beat_template():
    """The beat template's bracket holds the model's own title for what
    happened. `**[scene tag — e.g. …]**` named the slot, and the corpus has 17
    distinct labels that copied the words `scene tag —` into the output."""
    template = re.compile(r"(?m)^\*\*\[scene tag")
    for name, text in BOTH.items():
        assert not template.search(text), name


def test_both_prompts_forbid_improving_the_label_they_were_given():
    """Two failure modes, one rule. Swapping a participant for the character
    they play is an inferred identity; shortening `Valphine Sotorra` to
    `Valphine` is a reformatted one. Both produce a label that no longer
    matches the file it came from, and downstream matching is exact — so
    neither degrades into a near-miss, they resolve to nobody."""
    for name, text in BOTH.items():
        assert "Do NOT replace a participant's name with the character" in text, name

    # The truncation half is the one #460 is about, and it is stated where the
    # evidence for it is: the per-scene prompt, which produced those labels.
    assert "do NOT shorten, expand, re-case or re-spell" in PER_SCENE
