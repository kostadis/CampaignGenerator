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
    Rule,
    SourceTranscript,
    Verdict,
    annotate_text,
    classify,
    editorial_brackets,
    parse_scene_quotes,
    parse_scene_summary_spans,
    parse_summary_quotes,
    refusal_marker,
    render_report,
    verify_artifact,
    verify_artifact_contract,
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


# ── Extraction contract #250 — R1 and R3 ─────────────────────────────────────
#
# The fixture encodes each branch of both rules against a tape that garbles
# things, because that is what real tapes do. Cue 1 is the measured shape of
# the defect this contract exists for: Zoom heard "Lathander" as "the
# pandemic", and both extraction stages quietly repaired it inside a span
# marked verbatim.

CONTRACT_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Wade Brown: The town has been protected by the strength of the pandemic.

2
00:00:05.000 --> 00:00:08.000
Gary Young: I do, like, cross promotions.

3
00:00:09.000 --> 00:00:13.000
David Mendenhall: We rode north for three days and nothing happened at all.

4
00:00:14.000 --> 00:00:17.000
Stephane Bourdeaud: The bathrobes are in the wagon.

5
00:00:18.000 --> 00:00:21.000
Stephane Bourdeaud: The bathrobes are in the cart.
"""

CONTRACT_SCENE = '''---
scene: Return to Phandalin
---

# Return to Phandalin

## Scene summary (from gm-assist, verbatim)

- Wade invokes his god: "The town has been protected by the strength of [Lathander]."
- Stephane corrects himself: "The bathrobes are in the wagon."
- David sums up the road: "We rode north for three days and nothing happened."
- The sign read "Neverwinter".

## Verbatim moments

**[Wade Brown]** — swearing by his god
> "The town has been protected by the strength of Lathander."

**[Stephane Bourdeaud]** — correcting himself
> "The bathrobes are in the cart."

**[David Mendenhall]** — on the journey
> "We rode north for three days and nothing happened at all."

**[Gary Young]** — the pitch
> "I do cross promotions [in the market]."
> "I do, like, cross [inaudible] promotions."
> "I do, like, cross promotions [inaudible — probably 'in the market']."
> "[inaudible]"
'''


@pytest.fixture
def contract_tape(tmp_path):
    p = tmp_path / "contract.vtt"
    p.write_text(CONTRACT_VTT, encoding="utf-8")
    return SourceTranscript.load(p)


@pytest.fixture
def contract_scene(tmp_path):
    p = tmp_path / "01_return_to_phandalin.md"
    p.write_text(CONTRACT_SCENE, encoding="utf-8")
    return p


@pytest.fixture
def contract(contract_tape, contract_scene):
    return verify_artifact_contract(contract_scene, contract_tape, kind="scene")


def _refusals(result, rule):
    return [r for r in result.refusals if r.rule is rule]


# ── R3 — an editorial insertion inside a span marked verbatim ────────────────

def test_r3_refuses_an_editorial_insertion(contract):
    texts = [r.quote.text for r in _refusals(contract, Rule.R3)]
    assert 'I do cross promotions [in the market].' in texts


def test_r3_preserves_a_bare_transcription_marker(contract):
    """Class 3 — a fact about the tape. Deleting one fabricates certainty."""
    texts = [r.quote.text for r in _refusals(contract, Rule.R3)]
    assert 'I do, like, cross [inaudible] promotions.' not in texts


def test_r3_refuses_a_marker_carrying_a_conjecture(contract):
    """The hybrid case: the marker half is a fact, the reconstruction is the
    editor's, and it is the reconstruction that would render."""
    texts = [r.quote.text for r in _refusals(contract, Rule.R3)]
    assert any("probably 'in the market'" in t for t in texts)


def test_r3_leaves_a_whole_quote_marker_alone(contract):
    """`[inaudible]` as the entire quote is EXEMPT — there is no verbatim span
    for a bracket to sit inside, so R3 has nothing to object to."""
    assert "[inaudible]" not in [r.quote.text for r in _refusals(contract, Rule.R3)]


def test_r3_does_not_fire_on_a_speaker_block_header(contract):
    """`**[Wade Brown]**` is structure, not an insertion — it is not inside a
    quote, so position-based classification never sees it."""
    assert not any("Wade Brown" in r.detail for r in _refusals(contract, Rule.R3))


def test_r3_count_is_exactly_the_two_editorial_spans(contract):
    assert len(_refusals(contract, Rule.R3)) == 2


def test_r3_refuses_a_span_that_is_verbatim(contract_tape, tmp_path):
    """The orthogonality property, and the whole reason refusals are not a
    fourth verdict: this span matches the tape once the bracket is stripped,
    and is still an editorial hand inside something marked verbatim."""
    art = tmp_path / "02_scene.md"
    art.write_text(
        "## Scene summary (from gm-assist, verbatim)\n\nnothing here\n\n"
        "## Verbatim moments\n\n"
        '> "I do, like, cross [obviously] promotions."\n',
        encoding="utf-8",
    )
    result = verify_artifact_contract(art, contract_tape, kind="scene")
    assert [f.verdict for f in result.findings] == [Verdict.VERIFIED]
    assert len(_refusals(result, Rule.R3)) == 1


def test_editorial_brackets_classifies_by_position_not_token():
    """Keying on the token is what made the first ch46 count 3 instead of 12:
    `[Lathander]` is a speaker label elsewhere in the same file, and every
    marker carrying a comment matched no known token and fell through."""
    assert editorial_brackets("respect for [Lathander], yes.") == ["[Lathander]"]
    assert editorial_brackets("he said [inaudible] then left") == []
    assert editorial_brackets("he said [unclear] then [left]") == ["[left]"]


# ── R1 — the two sections disagree and the tape cannot settle it ─────────────

def test_r1_refuses_when_neither_copy_is_verbatim(contract):
    r1 = _refusals(contract, Rule.R1)
    assert len(r1) == 1
    assert "strength of Lathander" in r1[0].quote.text
    assert r1[0].counterpart is not None
    assert "[Lathander]" in r1[0].counterpart.text


def test_r1_never_fires_when_both_copies_are_verbatim(contract):
    """The load-bearing exclusion. Without it the rule fires on any two
    similar-but-distinct real utterances and the GM is woken up to adjudicate
    between two facts."""
    assert contract.conflicts.consistent == 1
    assert not any("bathrobes" in r.quote.text for r in _refusals(contract, Rule.R1))


def test_r1_does_not_fire_when_the_tape_settles_it(contract):
    """Exactly one copy verbatim — the tape has already named the winner, and
    the loser is reported by its own verdict."""
    assert contract.conflicts.settled == 1
    assert not any("rode north" in r.quote.text for r in _refusals(contract, Rule.R1))


def test_r1_reports_its_denominator(contract):
    """Two refusals out of eight pairs is a working rule; two out of two is a
    broken one. The count alone cannot tell them apart."""
    scan = contract.conflicts
    assert scan.paired == 3
    assert scan.consistent + scan.settled + scan.refused == scan.paired


def test_r1_ignores_short_summary_spans(contract_scene):
    """`"Neverwinter"` is a label, not speech — the same judgement the
    blockquote parser makes by refusing inline quotes outright (D5)."""
    spans = [q.text for q in parse_scene_summary_spans(
        contract_scene.read_text(), contract_scene)]
    assert "Neverwinter" not in spans


def test_r1_pairing_never_turns_the_human_half_into_a_finding(contract):
    """D4 stands: `## Scene summary` is the GM's own hand-authored content.
    Its spans exist only as the *other copy*, never as an accusation."""
    assert all(f.quote.section != "Scene summary" for f in contract.findings)


def test_r1_does_not_run_on_a_stage_1_summary(contract_tape, tmp_path):
    """A summary has one section, so there is no second copy to conflict with."""
    art = tmp_path / "session-summary.md"
    art.write_text('> "The town has been protected by the strength of Lathander."\n',
                   encoding="utf-8")
    result = verify_artifact_contract(art, contract_tape, kind="summary")
    assert result.conflicts.paired == 0
    assert not _refusals(result, Rule.R1)


def test_summary_span_line_numbers_point_at_the_real_line(contract_scene):
    lines = contract_scene.read_text().splitlines()
    for q in parse_scene_summary_spans(contract_scene.read_text(), contract_scene):
        assert q.text in lines[q.line_no - 1]


# ── Refusal annotation ───────────────────────────────────────────────────────

def test_refusal_marker_is_added_and_is_idempotent(contract, contract_scene):
    text = contract_scene.read_text()
    once, added1 = annotate_text(text, contract.findings, contract.refusals)
    twice, added2 = annotate_text(once, contract.findings, contract.refusals)
    assert added1 > 0 and added2 == 0
    assert once == twice
    assert refusal_marker(Rule.R3) in once


def test_a_line_that_is_both_unverified_and_refused_gets_both_markers(
        contract, contract_scene):
    out, _ = annotate_text(contract_scene.read_text(),
                           contract.findings, contract.refusals)
    both = [ln for ln in out.splitlines()
            if ANNOTATION in ln and "cg:refused" in ln]
    assert both, "expected at least one line carrying both markers"
    for ln in both:
        assert ln.count(ANNOTATION) == 1


def test_refusal_annotation_never_alters_quote_text(contract, contract_scene):
    import re
    before = contract_scene.read_text()
    after, _ = annotate_text(before, contract.findings, contract.refusals)
    pat = re.compile(r'"([^"]*)"')
    assert pat.findall(before) == pat.findall(after)


# ── Refusals in the report ───────────────────────────────────────────────────

def _contract_report(tape, result):
    r = VerificationReport(transcript=tape.path, threshold=0.85,
                           min_tokens=4, generated_at=now_iso())
    r.artifacts.append(result.path)
    r.findings.extend(result.findings)
    r.refusals.extend(result.refusals)
    r.conflicts = result.conflicts
    return r


def test_report_has_a_refused_section_even_when_empty(contract_tape, summary):
    r = VerificationReport(transcript=contract_tape.path, threshold=0.85,
                           min_tokens=4, generated_at=now_iso())
    r.artifacts.append(summary)
    r.findings.extend(verify_artifact(summary, contract_tape, kind="summary"))
    text = render_report(r)
    assert "## Refused" in text
    assert "No span was refused" in text


def test_report_puts_refused_before_unverified(contract_tape, contract):
    text = render_report(_contract_report(contract_tape, contract))
    assert text.index("## Refused") < text.index("## Unverified")


def test_report_states_the_conflict_denominator(contract_tape, contract):
    text = render_report(_contract_report(contract_tape, contract))
    assert "R1 scanned **3** span(s)" in text
    assert "**1** settled by the transcript" in text


def test_report_verdict_table_still_parses_for_the_editor(contract_tape, contract):
    """The Session Doc Editor's status strip reads the verdict table by regex.
    Adding a refusals section must not move a row out from under it."""
    from server.routers.scene_editor import _parse_quote_report_counts
    import tempfile
    text = render_report(_contract_report(contract_tape, contract))
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(text)
        p = Path(fh.name)
    counts = _parse_quote_report_counts(p)
    p.unlink()
    assert set(counts) == {"verified", "near", "unverified", "unscored", "exempt"}
    assert counts["verified"] is not None
    assert sum(counts.values()) == len(contract.findings)


# ── Refusals through the CLI ─────────────────────────────────────────────────

def test_cli_exits_1_on_refusals_alone(tmp_path):
    """A refusal is a finding. Exiting 0 because nothing was *unverified* would
    hide the spans the contract declined to choose."""
    vtt = tmp_path / "c.vtt"
    vtt.write_text(CONTRACT_VTT, encoding="utf-8")
    d = tmp_path / "scenes"
    d.mkdir()
    (d / "01_scene.md").write_text(
        "## Scene summary (from gm-assist, verbatim)\n\nnothing here\n\n"
        "## Verbatim moments\n\n"
        '> "I do, like, cross [obviously] promotions."\n',
        encoding="utf-8",
    )
    out = tmp_path / "report.md"
    r = _run_cli("--vtt", str(vtt), "--scene-extractions", str(d),
                 "--out", str(out), "--report-only")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "refused" in r.stdout
    assert "0 unverified quote(s), 1 refused span(s)" in r.stdout


def test_cli_annotates_refusals_when_not_report_only(tmp_path):
    vtt = tmp_path / "c.vtt"
    vtt.write_text(CONTRACT_VTT, encoding="utf-8")
    d = tmp_path / "scenes"
    d.mkdir()
    scene = d / "01_scene.md"
    scene.write_text(
        "## Scene summary (from gm-assist, verbatim)\n\nnothing here\n\n"
        "## Verbatim moments\n\n"
        '> "I do, like, cross [obviously] promotions."\n',
        encoding="utf-8",
    )
    _run_cli("--vtt", str(vtt), "--scene-extractions", str(d),
             "--out", str(tmp_path / "r.md"))
    assert refusal_marker(Rule.R3) in scene.read_text()
