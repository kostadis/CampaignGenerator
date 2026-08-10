"""Tests for session_doc/voice_lint.py's banned-construction checks.

The behavioral-taxonomy family is banned in base.md as a MOVE, not a wording
(#246). The #245 Opus-vs-Fable benchmark then showed it surviving that ban by
rotating shells: every mechanical scan returned zero hits across all 12 scenes
while reading found three confirmed instances, none of which PORTRAIT_RE's
"with the X of a man who ..." pattern can match. TAXONOMY_RE (#251) covers the
rotated shell, and the three instances below are pinned verbatim from the issue
so a future regex tidy-up cannot quietly reopen the hole.
"""
import pytest

from session_doc.voice_lint import PORTRAIT_RE, TAXONOMY_RE, lint

# Verbatim from CG#251 — all three found by reading the opus benchmark arm.
BENCHMARK_INSTANCES = [
    "He said *aha*, in the way men say it when they have understood nothing.",
    "…everyone looked at me the way they do when they want someone else to decide.",
    "The third one said it plain, the way they say things at that age…",
]


@pytest.mark.parametrize("line", BENCHMARK_INSTANCES)
def test_taxonomy_re_catches_every_benchmark_instance(line):
    assert TAXONOMY_RE.search(line), f"TAXONOMY_RE missed a confirmed #251 instance: {line!r}"


@pytest.mark.parametrize("line", BENCHMARK_INSTANCES)
def test_portrait_re_misses_them_which_is_why_taxonomy_re_exists(line):
    """Documents the gap: the #246-era pattern cannot see the rotated shell."""
    assert not PORTRAIT_RE.search(line)


@pytest.mark.parametrize("line", [
    # One named individual or one person is a specific observation, not a class.
    "I liked the way she said my name.",
    "He fixed it the way Brewbarry does, badly.",
    # No taxonomy verb at all.
    "I went the way he pointed.",
    "That is the way home when the river floods.",
    # `when` with no "the way X <verb>" lead-in.
    "She smiled when the song ended.",
])
def test_taxonomy_re_does_not_over_fire(line):
    assert not TAXONOMY_RE.search(line), f"false positive on legitimate prose: {line!r}"


def test_taxonomy_hit_is_reported_by_lint():
    """A single occurrence warns; more than one is a hard error (doc-level rule)."""
    one = "## Vukradin — Scene 02\n\n" + BENCHMARK_INSTANCES[0] + "\n"
    errors, warns = lint(one)
    assert not errors
    assert any("the-way-X-do-when" in w for w in warns), warns

    two = ("## Vukradin — Scene 02\n\n" + BENCHMARK_INSTANCES[0] + "\n"
           "\n## Soma — Scene 05\n\n" + BENCHMARK_INSTANCES[1] + "\n")
    errors, warns = lint(two)
    assert any("the-way-X-do-when" in e for e in errors), errors


def test_clean_narration_trips_nothing():
    text = ("## Brewbarry — Scene 01\n\n"
            "He said *aha* and looked at his hands. Nobody answered him.\n"
            "I counted the coins twice and put them back in the bag.\n")
    errors, warns = lint(text)
    assert (errors, warns) == ([], [])
