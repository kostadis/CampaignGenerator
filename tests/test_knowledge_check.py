"""Tests for the unknown-name warning (#223 A.3).

The check answers one question: did the narration put a name into PROSE that
appears nowhere in the campaign's shared record? It warns and never edits, so
the design bias is recall — a missed leak is invisible in the output, whereas
a false positive is one line of stderr somebody skims.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from session_doc.knowledge_check import (  # noqa: E402
    extract_candidate_names,
    find_unknown_names,
    format_warning,
)

BIBLE = (
    "The party travelled to Neverwinter and met Lord Cassian at the docks.\n"
    "Aldus kept the ledger. House Margaster paid the Zhentarim in silver.\n"
)


def test_known_names_are_not_flagged():
    assert find_unknown_names("I met Lord Cassian by the docks.", [BIBLE]) == []


def test_unknown_name_mid_sentence_is_flagged():
    assert "Kazneporium" in find_unknown_names(
        "I thought of Kazneporium and said nothing.", [BIBLE])


def test_unknown_name_is_flagged_even_when_only_ever_sentence_initial():
    """The recall guard. An earlier draft dropped candidates that never
    appeared mid-sentence, which silently missed exactly this shape."""
    assert "Kazneporium" in find_unknown_names(
        "Kazneporium had been here. I could feel it.", [BIBLE])


def test_quoted_speech_is_not_checked():
    """A speaker may call anyone anything, and #223 made quoted text a record
    rather than the pipeline's prose. Fabricated quotes are sd_verify_quotes's
    problem, not this check's."""
    assert find_unknown_names('He said "Kazneporium sent me." I stared.', [BIBLE]) == []


def test_italic_spans_are_not_checked():
    assert find_unknown_names("I stared. *Kazneporium, cut off*", [BIBLE]) == []


def test_sentence_opener_glued_to_a_known_name_is_dropped():
    """"Then Aldus", "Said House", "For Meliamne" — the head is a sentence
    opener, not part of a name, and the tail is already known."""
    flagged = find_unknown_names("Then Aldus counted the coins again.", [BIBLE])
    assert flagged == []


def test_two_word_leak_with_an_unknown_tail_survives_that_rule():
    assert "Kazneporium Ketternopappux" in find_unknown_names(
        "Kazneporium Ketternopappux had been here.", [BIBLE])


def test_alias_expansion_regression_the_ch47_finding():
    """The real defect: the source says "Aldus" and never "Aldus Hern", the
    bible has neither "Aldus Hern" nor "Hern", and a registry alias expansion
    put the surname into narration prose nine times."""
    session_source = "Aldus goes to the counting house. Aldus reads the writ."
    narration = "Aldus Hern met us at the counting house. Hern did not smile."
    flagged = find_unknown_names(narration, [BIBLE, session_source])
    assert "Aldus Hern" in flagged
    assert "Hern" in flagged
    # ...and the first name itself, which IS in the source, stays clean.
    assert "Aldus" not in flagged


def test_a_name_known_only_from_this_session_is_not_flagged():
    """The bible is an allowlist, not a denylist — union it with the session's
    own extractions or every on-stage NPC absent from the bible gets flagged."""
    assert find_unknown_names(
        "Vyldara handed me the writ.", [BIBLE, "Vyldara: I have the writ."]) == []


def test_headings_and_frontmatter_are_not_narration():
    doc = ("---\nchapter: 47\ntitle: 'Neverwinter, Never a Dull Moment'\n---\n\n"
           "# Chapter 47: Neverwinter, Never a Dull Moment\n\n"
           "## Soma — Arrival\n\nI met Lord Cassian by the docks.\n")
    assert find_unknown_names(doc, [BIBLE]) == []


def test_candidates_record_whether_every_occurrence_starts_a_sentence():
    cands = extract_candidate_names("Neverwinter is cold. I left Neverwinter.")
    assert cands["Neverwinter"] is False
    cands = extract_candidate_names("Neverwinter is cold.")
    assert cands["Neverwinter"] is True


def test_empty_inputs_are_clean():
    assert find_unknown_names("", [BIBLE]) == []
    assert find_unknown_names("I met Lord Cassian.", []) == ["Lord Cassian"]


def test_format_warning_is_empty_when_clean():
    assert format_warning("scene 1", []) == ""


def test_format_warning_names_the_scene_and_every_finding():
    out = format_warning("scene 3 (Soma — Docks)", ["Hern", "Kazneporium"])
    assert "scene 3 (Soma — Docks)" in out
    assert "2 name(s)" in out
    assert "- Hern" in out and "- Kazneporium" in out
    assert "warning only" in out
