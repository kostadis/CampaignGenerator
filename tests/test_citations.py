"""Tests for campaignlib.citations — the deterministic hallucination check
for distill.py's extract pass (no model calls, plain substring matching)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaignlib.citations import (
    extract_citations,
    extract_endnote_definitions,
    find_dangling_refs,
    find_endnote_refs,
    find_orphan_definitions,
    find_uncited_bullets,
    find_unreferenced_claims,
    render_report,
    render_synthesis_report,
    verify_citations,
    verify_endnotes,
)

SOURCE = (
    'Hartsch declared himself Supreme Prophet of the Earth Temple and named '
    'the party "the Obsidian Edge" before the assembled temple.'
)


# ── extract_citations ────────────────────────────────────────────────────────

def test_extract_citations_parses_bullet_and_quote():
    text = '- Hartsch became Supreme Prophet. [cite: "declared himself Supreme Prophet"]'
    result = extract_citations(text)
    assert result == [("- Hartsch became Supreme Prophet.", "declared himself Supreme Prophet")]


def test_extract_citations_accepts_curly_quotes():
    text = '- Hartsch became Supreme Prophet. [cite: “declared himself Supreme Prophet”]'
    result = extract_citations(text)
    assert result == [("- Hartsch became Supreme Prophet.", "declared himself Supreme Prophet")]


def test_extract_citations_multiple_bullets():
    text = (
        '- First claim. [cite: "one"]\n'
        '- Second claim. [cite: "two"]\n'
    )
    result = extract_citations(text)
    assert [q for _, q in result] == ["one", "two"]


def test_extract_citations_ignores_non_bullet_lines():
    text = '## NPCs\nSome prose with [cite: "not a bullet"] in it.'
    assert extract_citations(text) == []


# ── find_uncited_bullets ─────────────────────────────────────────────────────

def test_find_uncited_bullets_flags_missing_tag():
    text = (
        '- Cited claim. [cite: "declared himself Supreme Prophet"]\n'
        '- Uncited claim with no tag.\n'
    )
    assert find_uncited_bullets(text) == ["- Uncited claim with no tag."]


def test_find_uncited_bullets_empty_when_all_cited():
    text = '- Cited claim. [cite: "declared himself Supreme Prophet"]'
    assert find_uncited_bullets(text) == []


def test_find_uncited_bullets_exempts_classification_labels():
    text = (
        '- Faction: Water Temple (former high priest).\n'
        '- Current location: Earth Temple territory.\n'
        '- Current goals: Unknown; in disarray.\n'
    )
    assert find_uncited_bullets(text) == []


def test_find_uncited_bullets_exempts_bare_absence():
    text = (
        '- Does not appear in this session.\n'
        '- Not visited in this session.\n'
        '- Not directly encountered this chunk.\n'
    )
    assert find_uncited_bullets(text) == []


def test_find_uncited_bullets_still_flags_current_state_and_recent_actions():
    text = (
        '- Current state: Dead; killed at the outset of the ambush.\n'
        '- Recent actions: Bargained knowledge for freedom.\n'
    )
    assert find_uncited_bullets(text) == [
        "- Current state: Dead; killed at the outset of the ambush.",
        "- Recent actions: Bargained knowledge for freedom.",
    ]


def test_find_uncited_bullets_absence_with_extra_clause_still_flagged():
    # A real assertion tacked onto the negation isn't exempt — only a bare
    # "didn't appear" statement is.
    text = '- Does not appear in this session; sent a threatening letter to the party.'
    assert find_uncited_bullets(text) == [text.strip()]


def test_find_uncited_bullets_ignores_headings():
    text = '## NPCs\n- Uncited claim.'
    assert find_uncited_bullets(text) == ["- Uncited claim."]


# ── verify_citations ─────────────────────────────────────────────────────────

def test_verify_citations_true_for_exact_substring():
    text = '- Claim. [cite: "declared himself Supreme Prophet"]'
    results = verify_citations(text, SOURCE)
    assert len(results) == 1
    assert results[0].verified is True


def test_verify_citations_false_for_fabricated_quote():
    text = '- Claim. [cite: "words that never appeared in the source"]'
    results = verify_citations(text, SOURCE)
    assert results[0].verified is False


def test_verify_citations_tolerates_whitespace_and_case_drift():
    text = '- Claim. [cite: "DECLARED   himself  supreme prophet"]'
    results = verify_citations(text, SOURCE)
    assert results[0].verified is True


def test_verify_citations_false_for_empty_quote():
    text = '- Claim. [cite: ""]'
    results = verify_citations(text, SOURCE)
    assert results[0].verified is False


def test_verify_citations_checks_against_its_own_chunk_only():
    text = '- Claim. [cite: "declared himself Supreme Prophet"]'
    results = verify_citations(text, "an unrelated chunk of source text")
    assert results[0].verified is False


# ── render_report ─────────────────────────────────────────────────────────────

def test_render_report_lists_unverified_and_uncited():
    citations = verify_citations(
        '- Bad claim. [cite: "not real"]', "totally different text"
    )
    uncited = ["- Missing citation entirely."]
    report = render_report({"extract_001.md": (citations, uncited)})
    assert "extract_001.md" in report
    assert "Unverified citations" in report
    assert "not real" in report
    assert "Bullets missing a citation" in report
    assert "Missing citation entirely." in report


def test_render_report_clean_when_nothing_flagged():
    citations = verify_citations(
        '- Good claim. [cite: "declared himself Supreme Prophet"]', SOURCE
    )
    report = render_report({"extract_001.md": (citations, [])})
    assert "extract_001.md" not in report
    assert "No flagged claims" in report


# ── Synthesis endnotes ───────────────────────────────────────────────────────

KNOWN_CITATIONS = {
    "declared himself Supreme Prophet of the Earth Temple, and named the party",
    "killed him in his private chamber",
}

SYNTH_DOC = (
    '## NPCs\n'
    '- Hartsch became Supreme Prophet after the coup. [1]\n'
    '- Faction: Earth Temple.\n'
    '- Romag was killed in his chamber. [2]\n'
    '\n'
    '## Citations\n'
    '\n'
    '[1] "declared himself Supreme Prophet of the Earth Temple, and named the party"\n'
    '[2] "killed him in his private chamber"\n'
)


def test_extract_endnote_definitions_parses_citations_section():
    assert extract_endnote_definitions(SYNTH_DOC) == {
        1: "declared himself Supreme Prophet of the Earth Temple, and named the party",
        2: "killed him in his private chamber",
    }


def test_find_endnote_refs_finds_trailing_markers():
    refs = find_endnote_refs(SYNTH_DOC)
    assert ("- Hartsch became Supreme Prophet after the coup. [1]", [1]) in refs
    assert ("- Romag was killed in his chamber. [2]", [2]) in refs


def test_find_endnote_refs_handles_multiple_markers():
    text = '- Merged claim from two sources. [2][5]'
    assert find_endnote_refs(text) == [("- Merged claim from two sources. [2][5]", [2, 5])]


def test_find_unreferenced_claims_flags_missing_marker():
    text = '- Cited claim. [1]\n- Uncited claim with no marker.\n'
    assert find_unreferenced_claims(text) == ["- Uncited claim with no marker."]


def test_find_unreferenced_claims_exempts_classification_labels():
    assert find_unreferenced_claims(SYNTH_DOC) == []


def test_find_dangling_refs_flags_undefined_marker():
    text = '- Claim citing a marker nobody defined. [9]\n\n## Citations\n\n[1] "real quote"\n'
    assert find_dangling_refs(text) == [9]


def test_find_orphan_definitions_flags_unused_entry():
    text = '- Claim. [1]\n\n## Citations\n\n[1] "used quote"\n[2] "never referenced"\n'
    assert find_orphan_definitions(text) == [2]


def test_verify_endnotes_true_for_known_citation():
    results = verify_endnotes(SYNTH_DOC, KNOWN_CITATIONS)
    assert all(e.verified for e in results)


def test_verify_endnotes_false_for_fabricated_quote():
    text = '- Claim. [1]\n\n## Citations\n\n[1] "a quote synthesis made up"\n'
    results = verify_endnotes(text, KNOWN_CITATIONS)
    assert results[0].verified is False


def test_verify_endnotes_tolerates_quote_style_and_whitespace_drift():
    text = '- Claim. [1]\n\n## Citations\n\n[1] "declared himself  Supreme Prophet of the Earth Temple, and named the party"\n'
    results = verify_endnotes(text, KNOWN_CITATIONS)
    assert results[0].verified is True


def test_render_synthesis_report_lists_all_flag_categories():
    endnotes = verify_endnotes(
        '- Claim. [1]\n\n## Citations\n\n[1] "fabricated quote"\n', KNOWN_CITATIONS)
    report = render_synthesis_report(
        endnotes, unreferenced=["- Missing an endnote."],
        dangling=[9], orphans=[3])
    assert "fabricated quote" in report
    assert "Missing an endnote." in report
    assert "[9]" in report
    assert "[3]" in report


def test_render_synthesis_report_clean_when_nothing_flagged():
    endnotes = verify_endnotes(SYNTH_DOC, KNOWN_CITATIONS)
    report = render_synthesis_report(endnotes, unreferenced=[], dangling=[], orphans=[])
    assert "No flagged claims" in report
