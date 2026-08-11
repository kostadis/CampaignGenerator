"""Genre-block formatting tests for session_doc.narrate.build_narrate_system.

CampaignGenerator#245: a single-line genre directive gets an inline
``GENRE: ...`` label; a multi-line genre document (a full campaign
``_genre.md``) instead gets its own delimited block so it does not read
as a run-on label wedged into the preamble. Both shapes still get the
tail "FINAL REMINDER" repeat, and no genre input at all leaves no
marker in the prompt.

CampaignGenerator#276 (fix 1): the delimited block is chosen by *size*,
not by the presence of a newline. out-of-the-abyss' 16,303-char genre
spec reached ``narrate.genre`` as a paste that lost its line structure,
so the newline test delivered the largest rulebook in any campaign as a
single-line ``GENRE:`` label — twice, since the tail reminder repeats it
whole. A newline-free document must still get the delimited form.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc  # noqa: E402
from session_doc.narrate import GENRE_INLINE_MAX_CHARS  # noqa: E402

BEGIN_MARKER = "GENRE & REGISTER (campaign-specific) — BEGIN"
END_MARKER = "GENRE & REGISTER — END"
TAIL_MARKER = "GENRE — FINAL REMINDER"

SINGLE_LINE_GENRE = "First-person noir fantasy memoir"

MULTI_LINE_GENRE = (
    "Line one of the genre document.\n"
    "Line two, with extra register detail.\n"
    "Line three, closing the note."
)

# The #276 shape: a real genre document whose newlines were lost on the way
# into YAML. Sized like out-of-the-abyss' live value (16,303 chars, 0 newlines).
FLATTENED_GENRE = ((
    "GENRE & REGISTER. First-person noir fantasy memoir. "
    "Each narrator keeps their own vocabulary and their own bookkeeping cap. "
) * 160).strip()

REAL_GENRE_PATH = Path("/home/kroussos/src/campaigns/Phandalin/voice/_genre.md")
OOTA_SESSION_DOC = Path("/home/kroussos/src/campaigns/out-of-the-abyss/config/session_doc.yaml")


def _build(genre):
    return session_doc.build_narrate_system(examples_text=None, genre=genre)


def test_single_line_genre_uses_inline_label():
    prompt = _build(SINGLE_LINE_GENRE)
    assert f"GENRE: {SINGLE_LINE_GENRE}" in prompt
    # The delimited-block markers must not appear before the tail reminder
    # (in fact they must not appear at all for a single-line genre).
    tail_idx = prompt.index(TAIL_MARKER)
    assert BEGIN_MARKER not in prompt[:tail_idx]
    assert "GENRE & REGISTER" not in prompt


def test_multi_line_genre_uses_a_delimited_block():
    prompt = _build(MULTI_LINE_GENRE)
    assert BEGIN_MARKER in prompt
    assert END_MARKER in prompt
    begin = prompt.index(BEGIN_MARKER)
    end = prompt.index(END_MARKER)
    assert begin < end
    block = prompt[begin:end]
    assert MULTI_LINE_GENRE in block


@pytest.mark.skipif(
    not REAL_GENRE_PATH.exists(),
    reason=f"campaigns checkout not present: {REAL_GENRE_PATH}",
)
def test_real_genre_file_uses_delimited_block():
    real_genre = REAL_GENRE_PATH.read_text(encoding="utf-8").strip()
    assert "\n" in real_genre  # sanity: this fixture is the multi-line case
    prompt = _build(real_genre)
    assert BEGIN_MARKER in prompt
    assert END_MARKER in prompt
    begin = prompt.index(BEGIN_MARKER)
    end = prompt.index(END_MARKER)
    block = prompt[begin:end]
    assert real_genre in block


def test_flattened_genre_document_still_uses_delimited_block():
    """#276 fix 1: no newlines, but far too long to read as a label."""
    assert "\n" not in FLATTENED_GENRE
    assert len(FLATTENED_GENRE) > 15_000  # the live out-of-the-abyss magnitude
    prompt = _build(FLATTENED_GENRE)
    assert BEGIN_MARKER in prompt
    assert END_MARKER in prompt
    begin = prompt.index(BEGIN_MARKER)
    end = prompt.index(END_MARKER)
    assert begin < end
    assert FLATTENED_GENRE in prompt[begin:end]
    # And it must NOT also be delivered as the inline label it used to be.
    assert f"GENRE: {FLATTENED_GENRE}" not in prompt


def test_inline_label_threshold_is_a_boundary_not_a_cliff():
    """At the cap: inline. One character over: delimited."""
    at_cap = "x" * GENRE_INLINE_MAX_CHARS
    over_cap = "x" * (GENRE_INLINE_MAX_CHARS + 1)

    prompt_at = _build(at_cap)
    assert f"GENRE: {at_cap}" in prompt_at
    assert "GENRE & REGISTER" not in prompt_at

    prompt_over = _build(over_cap)
    assert BEGIN_MARKER in prompt_over
    assert f"GENRE: {over_cap}" not in prompt_over


@pytest.mark.skipif(
    not OOTA_SESSION_DOC.exists(),
    reason=f"campaigns checkout not present: {OOTA_SESSION_DOC}",
)
def test_live_oota_genre_value_reaches_the_delimited_block():
    """The actual value #276 was filed about, whatever state it is in now.

    Passes both before and after the campaign-side value is un-flattened, so
    it does not become a false green once the paste is repaired: the assertion
    is about delivery form, not about the value's newlines.
    """
    import yaml

    cfg = yaml.safe_load(OOTA_SESSION_DOC.read_text(encoding="utf-8"))
    genre = ((cfg.get("narrate") or {}).get("genre") or "").strip()
    if not genre:
        pytest.skip("out-of-the-abyss has no narrate.genre set")
    prompt = _build(genre)
    assert BEGIN_MARKER in prompt, (
        f"OOTA genre ({len(genre)} chars, {genre.count(chr(10))} newlines) "
        "was not delivered as a delimited block"
    )
    assert genre in prompt[prompt.index(BEGIN_MARKER):prompt.index(END_MARKER)]


def test_genre_text_is_not_truncated():
    prompt = _build(MULTI_LINE_GENRE)
    for line in MULTI_LINE_GENRE.splitlines():
        assert line in prompt


def test_tail_reminder_still_fires_for_both_shapes():
    prompt_single = _build(SINGLE_LINE_GENRE)
    assert prompt_single.count(TAIL_MARKER) == 1
    assert prompt_single.count(SINGLE_LINE_GENRE) == 2

    prompt_multi = _build(MULTI_LINE_GENRE)
    assert prompt_multi.count(TAIL_MARKER) == 1
    assert prompt_multi.count(MULTI_LINE_GENRE) == 2


@pytest.mark.parametrize("genre", [None, "", "   "])
def test_no_genre_leaves_no_marker(genre):
    prompt = _build(genre)
    assert "GENRE:" not in prompt
    assert "GENRE & REGISTER" not in prompt
    assert TAIL_MARKER not in prompt
