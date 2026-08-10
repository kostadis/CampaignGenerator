"""The scene-extraction prompt must carry the extraction contract (#250).

Asserting prompt *text* is usually brittle and usually not worth it. These
four rules are the exception: each one corresponds to a measured defect class
in `scene_extractions_new/` on Phandalin ch46, and each was invisible until
`sd_verify_quotes` grew the rules that found it. A later edit that tidies the
prompt and drops one of them would re-open a defect class silently, which is
exactly the failure mode the contract exists to close.

Deliberately matched on *substance* (a distinctive phrase per rule), not on
whole paragraphs, so the prompt stays free to be reworded.
"""

from pathlib import Path

import pytest

_PROMPT = Path(__file__).resolve().parent.parent / "config" / "agents" / "scene_extract.md"


@pytest.fixture(scope="module")
def prompt() -> str:
    """Whitespace-collapsed, so a phrase that gets rewrapped still matches."""
    return " ".join(_PROMPT.read_text(encoding="utf-8").split()).casefold()


def test_the_prompt_exists():
    assert _PROMPT.is_file(), f"{_PROMPT} is the contract's only reachable surface"


def test_it_forbids_repairing_a_mishearing_inside_a_quote(prompt):
    """Every R1 refusal and all 12 R3 brackets on ch46 were this: Zoom
    mishears, the extraction quietly repairs it inside a verbatim span."""
    assert "the strength of the pandemic" in prompt
    assert "owns its own mistakes" in prompt


def test_it_forbids_an_editorial_insertion_inside_a_quote(prompt):
    """R3. 12 spans a session before this rule existed."""
    assert "editorial insertion" in prompt


def test_it_keeps_bare_markers_legal(prompt):
    """Class 3 is a fact about the tape — deleting one fabricates certainty.
    The prompt has to permit the marker while refusing the guess attached."""
    assert "[inaudible]" in prompt
    assert "a guess" in prompt


def test_it_forbids_stitching_and_folding_narration_into_a_quote(prompt):
    """Defect B (two utterances joined across a third speaker's interruption)
    and defect A's splice (`How much you got? Toblen says: well —`)."""
    assert "never join two utterances" in prompt
    assert "stage" in prompt and "direction" in prompt


def test_it_still_says_the_original_verbatim_rule(prompt):
    """The new rules narrow the old one; they must not have replaced it."""
    assert "quote dialogue verbatim" in prompt
