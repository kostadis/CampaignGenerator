"""Tests for the session_doc quote verifier (spec 007, US1).

The fixture encodes the four cases that define the feature, taken from the
real failure modes measured in research D1:

    exact              -> verified
    disfluency-edited  -> near        (the 36% majority; must NOT be an accusation)
    fabricated         -> unverified  (the signal the GM actually asked for)
    [inaudible]        -> exempt      (an editorial marker, not a quote)

Two of these are safety properties rather than features: quote text is never
modified, and re-running never changes the file. Both are asserted directly —
an unasserted safety property is a wish.
"""

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import campaignlib  # noqa: E402

# See tests/test_locate_quote_parity.py for why this guard exists: the
# editable-install .pth points at the main checkout, so an earlier-collected
# test module can pin main's campaignlib in sys.modules and make a worktree run
# silently test the wrong code.
_resolved = Path(campaignlib.__file__).resolve().parent.parent
if _resolved != _REPO_ROOT:
    pytest.skip(
        f"campaignlib resolved to {_resolved}, not this worktree ({_REPO_ROOT}) "
        f"— this run would be testing main's code. Run this file on its own.",
        allow_module_level=True,
    )

from session_doc.verify_quotes import (  # noqa: E402
    ANNOTATION,
    SourceTranscript,
    Verdict,
    annotate_text,
    classify,
    parse_scene_quotes,
    parse_summary_quotes,
    render_report,
    verify_artifact,
    VerificationReport,
    now_iso,
)

VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
David Mendenhall: I do, like, cross promotions.

2
00:00:05.000 --> 00:00:09.000
Wade Brown: The town has been protected by the strength of Lathander.

3
00:00:10.000 --> 00:00:16.000
Stephane Bourdeaud: I'm... I'm... I think, from now on, every time we find
treasure, there should be a finder's fee.

4
00:00:17.000 --> 00:00:19.000
Gary Young: The bathrobes.
"""

SUMMARY = '''# Session

## Summary

The party passed a stone plaque honouring the "liberators of the Ordning".

## Memorable Moments

> "The town has been protected by the strength of Lathander."
> — Wade

> "I do cross promotions."
> — David

> "I have always hated the sea and everything in it."
> — Wade

> "[inaudible]"
> — Wade

> "The bathrobes."
> — Gary
'''


@pytest.fixture
def transcript(tmp_path):
    p = tmp_path / "s.vtt"
    p.write_text(VTT, encoding="utf-8")
    return SourceTranscript.load(p)


@pytest.fixture
def summary(tmp_path):
    p = tmp_path / "session-summary.md"
    p.write_text(SUMMARY, encoding="utf-8")
    return p


def _verdicts(findings):
    return {f.quote.text: f.verdict for f in findings}


# ── Transcript loading ───────────────────────────────────────────────────────

def test_speaker_prefixes_are_stripped_for_matching(transcript):
    assert transcript.speakers[0] == "David Mendenhall"
    assert transcript.spoken[0] == "I do, like, cross promotions."
    assert "david mendenhall" not in transcript.haystack


def test_missing_transcript_raises_rather_than_condemning_everything(tmp_path):
    """FR-011: a missing VTT must never read as a 100% fabrication rate."""
    with pytest.raises(ValueError, match="not readable"):
        SourceTranscript.load(tmp_path / "nope.vtt")


def test_transcript_with_no_dialogue_raises(tmp_path):
    p = tmp_path / "empty.vtt"
    p.write_text("WEBVTT\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no dialogue"):
        SourceTranscript.load(p)


# ── Classification — the four defining cases ─────────────────────────────────

def test_exact_quote_is_verified(transcript, summary):
    v = _verdicts(verify_artifact(summary, transcript, kind="summary"))
    assert v["The town has been protected by the strength of Lathander."] is Verdict.VERIFIED


def test_disfluency_edit_is_near_not_unverified(transcript, summary):
    """The 36% case from D1. Flagging these as fabrication is the failure mode
    that would make the whole report unusable."""
    v = _verdicts(verify_artifact(summary, transcript, kind="summary"))
    assert v["I do cross promotions."] is Verdict.NEAR


def test_fabricated_quote_is_unverified(transcript, summary):
    v = _verdicts(verify_artifact(summary, transcript, kind="summary"))
    assert v["I have always hated the sea and everything in it."] is Verdict.UNVERIFIED


def test_editorial_marker_is_exempt(transcript, summary):
    v = _verdicts(verify_artifact(summary, transcript, kind="summary"))
    assert v["[inaudible]"] is Verdict.EXEMPT


def test_short_quote_that_is_verbatim_is_still_verified(transcript, summary):
    """Length only makes the *fuzzy* score meaningless. A genuine verbatim span
    is a fact regardless of length, so VERIFIED is checked before the gate."""
    v = _verdicts(verify_artifact(summary, transcript, kind="summary"))
    assert v["The bathrobes."] is Verdict.VERIFIED


def test_short_quote_that_is_absent_is_unscored_not_accused(transcript, tmp_path):
    """D7: a two-word quote matches something in any transcript, so a low score
    is as meaningless as a high one. Report it; never accuse it."""
    from session_doc.verify_quotes import Quote
    q = Quote(text="Utterly absent.", artifact=tmp_path / "a.md", line_no=1)
    assert classify(q, transcript).verdict is Verdict.UNSCORED


def test_only_unverified_counts_as_a_problem(transcript, summary):
    findings = verify_artifact(summary, transcript, kind="summary")
    assert [f.quote.text for f in findings if f.is_problem] == [
        "I have always hated the sea and everything in it."
    ]


def test_reflow_does_not_produce_a_finding(transcript, tmp_path):
    """SC-002: whitespace/line-break differences alone are not findings.

    The transcript wraps this line mid-sentence; the quote is one span. The
    whitespace-tolerant tier of `locate_quote` is what has to bridge that.
    """
    from session_doc.verify_quotes import Quote
    q = Quote(
        text="every time we find treasure, there should be a finder's fee.",
        artifact=tmp_path / "a.md", line_no=1,
    )
    assert classify(q, transcript).verdict is Verdict.VERIFIED


def test_multi_line_quotes_are_counted_as_unparsed(tmp_path):
    """Every quote in the 534-quote measured corpus is single-line, so the
    parser only handles that shape — but silence about the rest would read as
    a pass. They are counted so the report can say what it skipped."""
    from session_doc.verify_quotes import count_unparsed_quote_lines
    text = (
        '> "a quote that opens here\n'
        '> and closes on the next line"\n'
        '> "a normal single-line quote."\n'
    )
    assert count_unparsed_quote_lines(text) == 1


def test_bracketed_insertion_inside_a_quote_is_stripped_before_matching(transcript, tmp_path):
    """D3: a GM clarification inside a real quote must not fail it."""
    from session_doc.verify_quotes import Quote
    art = tmp_path / "a.md"
    q = Quote(
        text="The town has been protected by the strength of [Lathander].",
        artifact=art, line_no=1,
    )
    assert classify(q, transcript).verdict is Verdict.VERIFIED


def test_threshold_moves_the_near_unverified_boundary(transcript, summary):
    strict = _verdicts(verify_artifact(summary, transcript, kind="summary", threshold=0.999))
    assert strict["I do cross promotions."] is Verdict.UNVERIFIED


# ── Stage 1 parser ───────────────────────────────────────────────────────────

def test_inline_prose_quotes_are_not_parsed(summary):
    """D5: `the "liberators of the Ordning"` is a label, not speech."""
    texts = [q.text for q in parse_summary_quotes(summary.read_text(), summary)]
    assert not any("liberators" in t for t in texts)


def test_attribution_line_becomes_speaker_hint_not_a_quote(summary):
    quotes = parse_summary_quotes(summary.read_text(), summary)
    assert not any(q.text.startswith("—") for q in quotes)
    by_text = {q.text: q for q in quotes}
    assert by_text["I do cross promotions."].speaker_hint == "David"


def test_section_is_tracked(summary):
    quotes = parse_summary_quotes(summary.read_text(), summary)
    assert all(q.section == "Memorable Moments" for q in quotes)


def test_line_numbers_point_at_the_real_line(summary):
    lines = summary.read_text().splitlines()
    for q in parse_summary_quotes(summary.read_text(), summary):
        assert q.text in lines[q.line_no - 1]


# ── Stage 2 parser ───────────────────────────────────────────────────────────

SCENE = '''---
scene: Return to Phandalin
---

# Return to Phandalin

## Scene summary (from gm-assist, verbatim)

- Brewbarry suggests a finder's fee: *"every time we find treasure"*
> "A gm-assist quote that must not be checked."

## Verbatim moments

**[David Mendenhall]** — reacting
> "I do cross promotions."
> "Something nobody ever said out loud at this table." (GM)
'''


def test_scene_summary_section_is_not_checked(tmp_path):
    """D4: `## Scene summary` is the GM's own hand-authored content."""
    art = tmp_path / "01_scene.md"
    art.write_text(SCENE, encoding="utf-8")
    texts = [q.text for q in parse_scene_quotes(SCENE, art)]
    assert "A gm-assist quote that must not be checked." not in texts
    assert "I do cross promotions." in texts


def test_scene_speaker_block_becomes_hint(tmp_path):
    art = tmp_path / "01_scene.md"
    art.write_text(SCENE, encoding="utf-8")
    by_text = {q.text: q for q in parse_scene_quotes(SCENE, art)}
    assert by_text["I do cross promotions."].speaker_hint == "David Mendenhall"
    assert by_text["Something nobody ever said out loud at this table."].speaker_hint == "GM"


def test_scene_line_numbers_are_file_relative(tmp_path):
    art = tmp_path / "01_scene.md"
    art.write_text(SCENE, encoding="utf-8")
    lines = SCENE.splitlines()
    for q in parse_scene_quotes(SCENE, art):
        assert q.text in lines[q.line_no - 1]


# ── Annotation: the two safety properties ────────────────────────────────────

def test_annotation_marks_only_unverified(transcript, summary):
    findings = verify_artifact(summary, transcript, kind="summary")
    out, added = annotate_text(summary.read_text(), findings)
    assert added == 1
    marked = [ln for ln in out.splitlines() if ANNOTATION in ln]
    assert len(marked) == 1
    assert "I have always hated the sea" in marked[0]


def test_annotation_is_idempotent(transcript, summary):
    """SC-006: re-running leaves the file byte-identical."""
    findings = verify_artifact(summary, transcript, kind="summary")
    once, added1 = annotate_text(summary.read_text(), findings)
    twice, added2 = annotate_text(once, findings)
    assert added1 == 1 and added2 == 0
    assert once == twice


def test_annotation_never_alters_quote_text(transcript, summary):
    """SC-007 / FR-006 — the one thing this tool must never do."""
    import re
    before = summary.read_text()
    findings = verify_artifact(summary, transcript, kind="summary")
    after, _ = annotate_text(before, findings)
    pat = re.compile(r'"([^"]*)"')
    assert pat.findall(before) == pat.findall(after)


def test_annotation_preserves_line_endings(transcript, tmp_path):
    """A CRLF file must not come back LF-only.

    `Path.read_text()` applies universal-newline translation, so reading and
    writing back would silently rewrite every line in the document — a far
    larger modification than the one marker FR-006 permits.
    """
    from session_doc.verify_quotes import read_preserving_newlines
    art = tmp_path / "crlf.md"
    art.write_bytes(b'> "I have always hated the sea and everything in it."\r\n')
    findings = verify_artifact(art, transcript, kind="summary")
    out, added = annotate_text(read_preserving_newlines(art), findings)
    assert added == 1
    assert out.endswith("\r\n")
    assert "\n\n" not in out


# ── Report ───────────────────────────────────────────────────────────────────

def _report(transcript, summary):
    r = VerificationReport(transcript=transcript.path, threshold=0.85,
                           min_tokens=4, generated_at=now_iso())
    r.artifacts.append(summary)
    r.findings.extend(verify_artifact(summary, transcript, kind="summary"))
    return r


def test_report_counts_sum_to_quotes_parsed(transcript, summary):
    r = _report(transcript, summary)
    assert sum(r.counts.values()) == len(r.findings)


def test_report_never_has_an_empty_not_checked_section(transcript, summary):
    """Principle VIII — state what was not checked."""
    r = _report(transcript, summary)
    text = render_report(r)
    assert "## Not checked" in text
    assert r.not_checked
    assert "Inline" in text and "Speaker attribution" in text


def test_report_puts_unverified_before_near(transcript, summary):
    text = render_report(_report(transcript, summary))
    assert text.index("## Unverified") < text.index("## Near")


def test_report_names_the_transcript_and_threshold(transcript, summary):
    text = render_report(_report(transcript, summary))
    assert transcript.path.name in text
    assert "0.85" in text


def test_no_quotes_is_distinct_from_all_verified(transcript, tmp_path):
    """FR-010 — an empty artifact is suspicious, not a pass."""
    empty = tmp_path / "empty.md"
    empty.write_text("# Nothing here\n", encoding="utf-8")
    r = VerificationReport(transcript=transcript.path, threshold=0.85,
                           min_tokens=4, generated_at=now_iso())
    r.artifacts.append(empty)
    r.findings.extend(verify_artifact(empty, transcript, kind="summary"))
    text = render_report(r)
    assert "No quotes found" in text
    assert "not the same as everything passing" in text


# ── CLI ──────────────────────────────────────────────────────────────────────

def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "session_doc.sd_verify_quotes", *args],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )


def test_cli_exit_1_on_findings(tmp_path, summary):
    vtt = tmp_path / "s.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    out = tmp_path / "report.md"
    r = _run_cli("--vtt", str(vtt), "--summary", str(summary),
                 "--out", str(out), "--report-only")
    assert r.returncode == 1, r.stderr
    assert out.exists()
    assert "unverified quote(s)" in r.stdout


def test_cli_exit_2_when_transcript_missing(tmp_path, summary):
    r = _run_cli("--vtt", str(tmp_path / "nope.vtt"), "--summary", str(summary),
                 "--out", str(tmp_path / "r.md"))
    assert r.returncode == 2
    assert "not readable" in r.stderr
    assert not (tmp_path / "r.md").exists()


def test_cli_exit_2_without_any_artifact(tmp_path):
    vtt = tmp_path / "s.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    r = _run_cli("--vtt", str(vtt))
    assert r.returncode == 2
    assert "implicit" in r.stderr


def test_cli_report_only_leaves_the_artifact_untouched(tmp_path, summary):
    vtt = tmp_path / "s.vtt"
    vtt.write_text(VTT, encoding="utf-8")
    before = summary.read_text()
    _run_cli("--vtt", str(vtt), "--summary", str(summary),
             "--out", str(tmp_path / "r.md"), "--report-only")
    assert summary.read_text() == before


def test_cli_has_no_model_flags():
    """FR-003: offering --model/--backend would imply a cost this cannot incur."""
    r = _run_cli("--help")
    for flag in ("--model", "--backend", "--fast", "--batch", "--endpoint"):
        assert flag not in r.stdout
