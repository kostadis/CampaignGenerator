"""Genre-block formatting tests for session_doc.narrate.build_narrate_system.

CampaignGenerator#245: a single-line genre directive gets an inline
``GENRE: ...`` label; a multi-line genre document (a full campaign
``_genre.md``) instead gets its own delimited block so it does not read
as a run-on label wedged into the preamble. Both shapes still get the
tail "FINAL REMINDER" repeat, and no genre input at all leaves no
marker in the prompt.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc  # noqa: E402

BEGIN_MARKER = "GENRE & REGISTER (campaign-specific) — BEGIN"
END_MARKER = "GENRE & REGISTER — END"
TAIL_MARKER = "GENRE — FINAL REMINDER"

SINGLE_LINE_GENRE = "First-person noir fantasy memoir"

MULTI_LINE_GENRE = (
    "Line one of the genre document.\n"
    "Line two, with extra register detail.\n"
    "Line three, closing the note."
)

REAL_GENRE_PATH = Path("/home/kroussos/src/campaigns/Phandalin/voice/_genre.md")


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
