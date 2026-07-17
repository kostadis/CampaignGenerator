"""Tests for campaignlib.citations — the deterministic hallucination check
for distill.py's extract pass (no model calls, plain substring matching)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaignlib.citations import (
    CitationIdAssigner,
    extract_citations,
    find_citation_refs,
    find_uncited_bullets,
    find_unreferenced_claims,
    render_report,
    render_sources_section,
    render_synthesis_report,
    strip_citation_tags,
    verify_citations,
    verify_id_citations,
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


def test_render_report_default_tool_name_preserves_distill_wording():
    citations = verify_citations('- Bad claim. [cite: "not real"]', "different text")
    report = render_report({"extract_001.md": (citations, [])})
    assert "Generated by distill.py's citation check" in report


def test_render_report_custom_tool_name():
    citations = verify_citations('- Bad claim. [cite: "not real"]', "different text")
    report = render_report({"extract_001.md": (citations, [])}, tool_name="planning.py")
    assert "Generated by planning.py's citation check" in report
    assert "distill.py" not in report


# ── CitationIdAssigner ───────────────────────────────────────────────────────

def test_citation_id_assigner_tags_sequentially():
    assigner = CitationIdAssigner()
    out = assigner('- Claim one. [cite: "quote one"]\n- Claim two. [cite: "quote two"]')
    assert out == (
        '- Claim one. [cite:1 "quote one"]\n'
        '- Claim two. [cite:2 "quote two"]'
    )
    assert assigner.id_to_quote == {1: "quote one", 2: "quote two"}


def test_citation_id_assigner_continues_across_calls():
    # Must number sequentially across every file it's called on, in call
    # order — matches run_synthesize_pipeline's per-file rendering loop.
    assigner = CitationIdAssigner()
    assigner('- Claim. [cite: "quote a"]')
    assigner('- Claim. [cite: "quote b"]')
    assert assigner.id_to_quote == {1: "quote a", 2: "quote b"}


def test_citation_id_assigner_leaves_non_citation_text_untouched():
    assigner = CitationIdAssigner()
    out = assigner('## NPCs\n- Faction: Earth Temple.\n')
    assert out == '## NPCs\n- Faction: Earth Temple.\n'
    assert assigner.id_to_quote == {}


# ── Synthesis citation IDs ───────────────────────────────────────────────────

KNOWN_IDS = {
    1: "declared himself Supreme Prophet of the Earth Temple, and named the party",
    2: "killed him in his private chamber",
}

SYNTH_DOC = (
    '## NPCs\n'
    '- Hartsch became Supreme Prophet after the coup. [1]\n'
    '- Faction: Earth Temple.\n'
    '- Romag was killed in his chamber. [2]\n'
)


def test_find_citation_refs_finds_trailing_markers():
    refs = find_citation_refs(SYNTH_DOC)
    assert ("- Hartsch became Supreme Prophet after the coup. [1]", [1]) in refs
    assert ("- Romag was killed in his chamber. [2]", [2]) in refs


def test_find_citation_refs_handles_multiple_markers():
    text = '- Merged claim from two sources. [2][5]'
    assert find_citation_refs(text) == [("- Merged claim from two sources. [2][5]", [2, 5])]


def test_find_unreferenced_claims_flags_missing_marker():
    text = '- Cited claim. [1]\n- Uncited claim with no marker.\n'
    assert find_unreferenced_claims(text) == ["- Uncited claim with no marker."]


def test_find_unreferenced_claims_exempts_classification_labels():
    assert find_unreferenced_claims(SYNTH_DOC) == []


def test_verify_id_citations_true_for_known_id():
    results = verify_id_citations(SYNTH_DOC, KNOWN_IDS)
    assert len(results) == 2
    assert all(r.verified for r in results)


def test_verify_id_citations_false_for_id_the_model_was_never_shown():
    text = '- Claim citing a fabricated ID. [99]'
    results = verify_id_citations(text, KNOWN_IDS)
    assert results[0].number == 99
    assert results[0].verified is False


def test_render_synthesis_report_lists_flagged_categories():
    results = verify_id_citations('- Claim. [99]', KNOWN_IDS)
    report = render_synthesis_report(results, unreferenced=["- Missing a citation."])
    assert "[99]" in report
    assert "Missing a citation." in report


def test_render_synthesis_report_clean_when_nothing_flagged():
    results = verify_id_citations(SYNTH_DOC, KNOWN_IDS)
    report = render_synthesis_report(results, unreferenced=[])
    assert "No flagged claims" in report


def test_render_synthesis_report_default_tool_name_preserves_distill_wording():
    results = verify_id_citations('- Claim. [99]', KNOWN_IDS)
    report = render_synthesis_report(results, unreferenced=[])
    assert "Generated by distill.py's synthesis citation check" in report


def test_render_synthesis_report_custom_tool_name():
    results = verify_id_citations('- Claim. [99]', KNOWN_IDS)
    report = render_synthesis_report(results, unreferenced=[], tool_name="party.py")
    assert "Generated by party.py's synthesis citation check" in report
    assert "distill.py" not in report


# ── render_sources_section ───────────────────────────────────────────────────

def test_render_sources_section_lists_only_used_ids():
    section = render_sources_section({1}, KNOWN_IDS)
    assert '[1] "declared himself Supreme Prophet of the Earth Temple, and named the party"' in section
    assert "[2]" not in section


def test_render_sources_section_flags_unknown_id():
    section = render_sources_section({99}, KNOWN_IDS)
    assert "<unknown citation>" in section


# ── strip_citation_tags ──────────────────────────────────────────────────────

def test_strip_citation_tags_removes_extract_style_tag():
    text = '- Hartsch became Supreme Prophet. [cite: "declared himself Supreme Prophet"]'
    assert strip_citation_tags(text) == "- Hartsch became Supreme Prophet."


def test_strip_citation_tags_removes_synthesis_style_tag_with_id():
    text = '- Hartsch became Supreme Prophet. [cite:12 "declared himself Supreme Prophet"]'
    assert strip_citation_tags(text) == "- Hartsch became Supreme Prophet."


def test_strip_citation_tags_leaves_untagged_text_untouched():
    text = "- Plain bullet with no citation at all."
    assert strip_citation_tags(text) == text


def test_strip_citation_tags_strips_across_multiple_lines():
    text = (
        '- First claim. [cite: "one"]\n'
        '- Second claim. [cite:2 "two"]\n'
        '- Third claim, uncited.\n'
    )
    assert strip_citation_tags(text) == (
        "- First claim.\n"
        "- Second claim.\n"
        "- Third claim, uncited.\n"
    )
