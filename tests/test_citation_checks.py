"""Tests for campaignlib.citation_checks — the file I/O + reporting wiring
over campaignlib.citations' pure verification functions (check_citations /
check_synthesis_citations). Moved out of distill.py in Phase 1 of the
citation-grounding extension so planning.py/party.py can share it; these
tests guard the `tool_name` and `flag_unreferenced` parameters that make the
wiring generic across callers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaignlib.citation_checks import check_citations, check_synthesis_citations

SOURCE = (
    "Hartsch declared himself Supreme Prophet of the Earth Temple after "
    "killing Romag in his private chamber."
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# ── check_citations ──────────────────────────────────────────────────────────

def test_check_citations_writes_report_when_flagged(tmp_path, capsys):
    extract_dir = tmp_path / "extractions"
    extract_dir.mkdir()
    extract_file = _write(
        extract_dir / "extract_001.md",
        '- Hartsch became Supreme Prophet. [cite: "words never in the source"]\n'
        '- Uncited claim with no tag.\n',
    )

    check_citations(SOURCE, None, [extract_file], 60000, None, extract_dir)

    report_path = extract_dir / "citation_report.md"
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "words never in the source" in report
    assert "Uncited claim with no tag." in report
    out = capsys.readouterr().out
    assert "flagged claim(s) for review" in out


def test_check_citations_no_report_when_clean(tmp_path, capsys):
    extract_dir = tmp_path / "extractions"
    extract_dir.mkdir()
    extract_file = _write(
        extract_dir / "extract_001.md",
        '- Hartsch declared himself Supreme Prophet. '
        '[cite: "declared himself Supreme Prophet of the Earth Temple"]\n',
    )

    check_citations(SOURCE, None, [extract_file], 60000, None, extract_dir)

    assert not (extract_dir / "citation_report.md").exists()
    out = capsys.readouterr().out
    assert "flagged claim(s)" not in out


def test_check_citations_tool_name_appears_in_report(tmp_path):
    extract_dir = tmp_path / "extractions"
    extract_dir.mkdir()
    extract_file = _write(
        extract_dir / "extract_001.md",
        '- Fabricated claim. [cite: "not in the source at all"]\n',
    )

    check_citations(SOURCE, None, [extract_file], 60000, None, extract_dir, tool_name="planning.py")

    report = (extract_dir / "citation_report.md").read_text(encoding="utf-8")
    assert "planning.py" in report
    assert "distill.py" not in report


# ── check_synthesis_citations ────────────────────────────────────────────────

KNOWN_IDS = {1: "declared himself Supreme Prophet of the Earth Temple"}


def test_check_synthesis_citations_writes_report_when_flagged(tmp_path):
    world_state = (
        "- Hartsch became Supreme Prophet. [1]\n"
        "- Claim citing a fabricated ID. [99]\n"
    )
    result = check_synthesis_citations(world_state, KNOWN_IDS, tmp_path)

    report_path = tmp_path / "synthesis_citation_report.md"
    assert report_path.exists()
    report = report_path.read_text(encoding="utf-8")
    assert "[99]" in report
    assert "## Sources" in result


def test_check_synthesis_citations_no_report_when_clean(tmp_path):
    world_state = "- Hartsch became Supreme Prophet. [1]\n"
    check_synthesis_citations(world_state, KNOWN_IDS, tmp_path)
    assert not (tmp_path / "synthesis_citation_report.md").exists()


def test_check_synthesis_citations_tool_name_appears_in_report(tmp_path):
    world_state = "- Claim citing a fabricated ID. [99]\n"
    check_synthesis_citations(world_state, KNOWN_IDS, tmp_path, tool_name="party.py")

    report = (tmp_path / "synthesis_citation_report.md").read_text(encoding="utf-8")
    assert "party.py" in report
    assert "distill.py" not in report


def test_check_synthesis_citations_flag_unreferenced_true_is_default_behavior(tmp_path, capsys):
    world_state = (
        "- Hartsch became Supreme Prophet. [1]\n"
        "- Unreferenced claim with no citation ID.\n"
    )
    check_synthesis_citations(world_state, KNOWN_IDS, tmp_path)

    report = (tmp_path / "synthesis_citation_report.md").read_text(encoding="utf-8")
    assert "Unreferenced claim with no citation ID." in report
    out = capsys.readouterr().out
    assert "1 claim(s) missing a citation." in out


def test_check_synthesis_citations_flag_unreferenced_false_excludes_from_report_and_count(tmp_path, capsys):
    world_state = (
        "- Claim citing a fabricated ID. [99]\n"
        "- Unreferenced claim with no citation ID.\n"
    )
    check_synthesis_citations(world_state, KNOWN_IDS, tmp_path, flag_unreferenced=False)

    report = (tmp_path / "synthesis_citation_report.md").read_text(encoding="utf-8")
    # Fabrication detection (verify_id_citations) still counts fully — the
    # anti-hallucination guarantee never weakens.
    assert "[99]" in report
    # But the unreferenced claim is excluded from both the report...
    assert "Unreferenced claim with no citation ID." not in report
    out = capsys.readouterr().out
    # ...and from the flagged count (only the fabricated ID is flagged: 1, not 2).
    assert "1 flagged item(s) for review" in out
    # It's still surfaced separately as an FYI line, not silently dropped.
    assert "not flagged for this tool" in out


def test_check_synthesis_citations_flag_unreferenced_false_no_report_when_only_unreferenced(tmp_path):
    # With no ID-fabrication and flag_unreferenced=False, an unreferenced-only
    # doc should produce no report at all (nothing meets the bar to flag).
    world_state = "- Unreferenced claim with no citation ID.\n"
    check_synthesis_citations(world_state, KNOWN_IDS, tmp_path, flag_unreferenced=False)
    assert not (tmp_path / "synthesis_citation_report.md").exists()
