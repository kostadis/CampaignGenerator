"""Tests for cue-indexed transcript corrections (#250 R4).

R4 makes `*.transcript.cleaned.vtt` a **generated** file. Three properties
carry that claim, and each is asserted directly rather than assumed:

    the raw tape is never written
    a stale correction fails loudly, never silently mis-applies
    regenerating twice produces identical bytes

The fixture is the shape of the real defect. On Phandalin ch46 the cleaned
tape carried 74 substitutions over its raw sibling with no record of any of
them — proper-noun repairs, but also a surname nobody said and a plural
turned singular. `import` exists to turn that into a reviewable list, which is
why its entries land unverified.
"""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import campaignlib  # noqa: E402

# See tests/test_locate_quote_parity.py for why this guard exists.
_resolved = Path(campaignlib.__file__).resolve().parent.parent
if _resolved != _REPO_ROOT:
    pytest.skip(
        f"campaignlib resolved to {_resolved}, not this worktree ({_REPO_ROOT}).",
        allow_module_level=True,
    )

from campaignlib.transcript_corrections import (  # noqa: E402
    CorrectionsError,
    TranscriptCorrection,
    TranscriptCorrectionRecord,
    apply_record,
    diff_cues,
    dump_record,
    import_edits,
    load_record,
)
from campaignlib.vtt import GENERATED_MARK, VttError, parse, render  # noqa: E402

RAW = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Gary Young: I mean, the town has been protected by the strength of the pandemic.

2
00:00:05.000 --> 00:00:08.000
Kostadis Roussos: Alright, Brynn and Giles are actually in the temple.

3
00:00:09.000 --> 00:00:12.000
David Mendenhall: I'm thinking like you, Blueberry, I've got a plan.
"""

# The shape a hand-edited `.cleaned.vtt` really has: repairs mixed with an
# insertion nobody said, and a prose NOTE block explaining none of it.
EDITED = """WEBVTT

NOTE Cleaned by hand on 2026-08-10 - proper nouns only.

1
00:00:01.000 --> 00:00:04.000
Gary Young: I mean, the town has been protected by the strength of Lathander.

2
00:00:05.000 --> 00:00:08.000
Kostadis Roussos: Alright, Brynn and Giles Slipper-Shine are actually in the temple.

3
00:00:09.000 --> 00:00:12.000
David Mendenhall: I'm thinking like you, Brewbarry, I've got a plan.
"""


@pytest.fixture
def session(tmp_path):
    d = tmp_path / "20260623"
    d.mkdir()
    (d / "rec.transcript.vtt").write_text(RAW, encoding="utf-8")
    (d / "rec.transcript.cleaned.vtt").write_text(EDITED, encoding="utf-8")
    return d


def _record(**over):
    base = dict(
        id="cue-0001", cue=1,
        was="Gary Young: I mean, the town has been protected by the strength of the pandemic.",
        now="Gary Young: I mean, the town has been protected by the strength of Lathander.",
        recorded=date(2026, 8, 10),
    )
    base.update(over)
    return TranscriptCorrectionRecord(
        transcript="rec.transcript.vtt",
        corrections=[TranscriptCorrection(**base)],
    )


# ── The VTT layer ────────────────────────────────────────────────────────────

def test_round_trip_preserves_every_cue():
    tx = parse(RAW)
    again = parse(render(tx))
    assert [(c.index, c.timing, c.text) for c in tx.cues] == \
           [(c.index, c.timing, c.text) for c in again.cues]


def test_crlf_input_renders_as_lf():
    """Declared normalisation. The raw Zoom tapes are CRLF and the hand-edited
    `.cleaned` siblings were LF — a silent rewrite would make the byte
    comparison that proves the record complete meaningless."""
    out = render(parse(RAW.replace("\n", "\r\n")))
    assert "\r" not in out


def test_cue_numbers_are_preserved_not_renumbered():
    """The contract keys on cue index (#250 C2). Renumbering on write would
    invalidate every correction the first time a cue was dropped."""
    text = RAW.replace("\n3\n", "\n97\n")
    assert [c.index for c in parse(text).cues] == [1, 2, 97]
    assert [c.index for c in parse(render(parse(text))).cues] == [1, 2, 97]


def test_author_notes_survive_and_generated_notes_do_not():
    """A round-trip must be a fixed point: what the generator wrote is not
    input, or every regeneration would accrete another header."""
    once = render(parse(EDITED), [f"NOTE {GENERATED_MARK} - hello"])
    twice = render(parse(once), [f"NOTE {GENERATED_MARK} - hello"])
    assert once == twice
    assert "Cleaned by hand" in twice
    assert twice.count(GENERATED_MARK) == 1


def test_not_webvtt_raises():
    with pytest.raises(VttError, match="not a WebVTT"):
        parse("1\n00:00:01.000 --> 00:00:02.000\nhi\n")


def test_no_cues_raises_rather_than_returning_empty():
    """A caller regenerating a tape from a file it could not parse would write
    an empty tape over a real one."""
    with pytest.raises(VttError, match="zero cues"):
        parse("WEBVTT\n\n")


# ── Applying ─────────────────────────────────────────────────────────────────

def test_apply_rewrites_only_the_named_cue(session):
    result = apply_record(_record(), parse(RAW))
    assert result.ok
    cues = parse(result.text).by_index()
    assert "Lathander" in cues[1].text
    assert cues[2].text == parse(RAW).by_index()[2].text
    assert cues[3].text == parse(RAW).by_index()[3].text


def test_a_stale_was_refuses_rather_than_pasting_over_new_words():
    """The self-invalidating property. If the raw tape is ever replaced, a
    correction written for the old one must fail, not apply blindly."""
    rec = _record(was="Gary Young: something the tape has never said.")
    result = apply_record(rec, parse(RAW))
    assert not result.ok
    assert "does not say what `was` claims" in result.problems[0]


def test_a_missing_cue_is_reported_with_the_file_line_hint():
    result = apply_record(_record(cue=9999), parse(RAW))
    assert not result.ok
    assert "file line number" in result.problems[0]


def test_apply_is_deterministic():
    """Regenerating twice must produce identical bytes, so nothing downstream
    sees a spurious change. That is why the header carries no timestamp."""
    a = apply_record(_record(), parse(RAW)).text
    b = apply_record(_record(), parse(RAW)).text
    assert a == b


def test_apply_output_reparses(session):
    result = apply_record(_record(), parse(RAW))
    assert len(parse(result.text).cues) == 3


# ── The record model ─────────────────────────────────────────────────────────

def test_two_corrections_on_one_cue_are_refused():
    """Which one wins would depend on file order — the second's `was`
    describes a tape the first already changed."""
    with pytest.raises(ValueError, match="more than one correction"):
        TranscriptCorrectionRecord(
            transcript="rec.transcript.vtt",
            corrections=[
                TranscriptCorrection(id="a", cue=1, was="x", now="y", recorded=date(2026, 8, 10)),
                TranscriptCorrection(id="b", cue=1, was="y", now="z", recorded=date(2026, 8, 10)),
            ],
        )


def test_a_correction_that_changes_nothing_is_refused():
    with pytest.raises(ValueError, match="changes nothing"):
        TranscriptCorrection(id="a", cue=1, was="x", now="x", recorded=date(2026, 8, 10))


def test_cue_zero_is_refused():
    with pytest.raises(ValueError, match="1-based cue index"):
        TranscriptCorrection(id="a", cue=0, was="x", now="y", recorded=date(2026, 8, 10))


def test_output_name_is_derived_from_the_raw_name():
    assert _record().output_name() == "rec.transcript.cleaned.vtt"


def test_pointing_transcript_at_the_cleaned_file_is_refused():
    """That would make the generated file its own input."""
    rec = TranscriptCorrectionRecord(transcript="rec.transcript.cleaned.vtt")
    with pytest.raises(CorrectionsError, match="already a .cleaned"):
        rec.output_name()


def test_record_round_trips_through_yaml(tmp_path):
    p = tmp_path / "transcript_corrections.yaml"
    p.write_text(dump_record(_record()), encoding="utf-8")
    back = load_record(p)
    assert back.corrections[0].was == _record().corrections[0].was
    assert back.corrections[0].recorded == date(2026, 8, 10)


def test_unknown_key_is_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("version: 1\ntranscript: a.vtt\ncorrections: []\nnonsense: 1\n",
                 encoding="utf-8")
    with pytest.raises(CorrectionsError, match="failed validation"):
        load_record(p)


# ── Importing an already-edited tape ─────────────────────────────────────────

def test_import_captures_every_difference():
    rec = import_edits(parse(RAW), parse(EDITED),
                       transcript_name="rec.transcript.vtt", recorded=date(2026, 8, 10))
    assert [c.cue for c in rec.corrections] == [1, 2, 3]


def test_imported_entries_are_unverified_by_default():
    """They were never reviewed — that is why the import exists. Marking them
    verified would launder an unreviewed model pass into the one file the whole
    pipeline treats as ground truth."""
    rec = import_edits(parse(RAW), parse(EDITED),
                       transcript_name="rec.transcript.vtt", recorded=date(2026, 8, 10))
    assert len(rec.unverified) == 3


def test_import_then_apply_reproduces_the_edited_cues():
    """The completeness proof, in miniature: if every edit is captured, the
    regenerated tape has the same cues as the one somebody hand-edited."""
    rec = import_edits(parse(RAW), parse(EDITED),
                       transcript_name="rec.transcript.vtt", recorded=date(2026, 8, 10))
    result = apply_record(rec, parse(RAW))
    assert result.ok
    assert not diff_cues(parse(result.text), parse(EDITED))


def test_mismatched_cue_sets_refuse_rather_than_pairing_positionally():
    """A tape whose cues were added or renumbered is not an edit of the other,
    and pairing positionally would attribute the wrong repair to every cue
    after the first divergence."""
    short = "\n".join(EDITED.split("\n")[:-5]) + "\n"
    with pytest.raises(CorrectionsError, match="same cue indices"):
        diff_cues(parse(RAW), parse(short))


# ── CLI ──────────────────────────────────────────────────────────────────────

def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "session_doc.sd_corrections", *args],
        capture_output=True, text=True, cwd=str(_REPO_ROOT),
    )


def test_cli_import_apply_check_cycle(session):
    assert _run("import", "--dir", str(session)).returncode == 0
    assert _run("apply", "--dir", str(session)).returncode == 0
    r = _run("check", "--dir", str(session))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "reproducible" in r.stdout


def test_cli_never_writes_the_raw_tape(session):
    before = (session / "rec.transcript.vtt").read_bytes()
    _run("import", "--dir", str(session))
    _run("apply", "--dir", str(session))
    assert (session / "rec.transcript.vtt").read_bytes() == before


def test_cli_check_catches_an_edit_nobody_wrote_down(session):
    """The finding the whole feature exists to produce."""
    _run("import", "--dir", str(session))
    _run("apply", "--dir", str(session))
    cleaned = session / "rec.transcript.cleaned.vtt"
    cleaned.write_text(
        cleaned.read_text(encoding="utf-8").replace("I've got a plan", "I have a scheme"),
        encoding="utf-8",
    )
    r = _run("check", "--dir", str(session))
    assert r.returncode == 1
    assert "without writing it down" in r.stdout
    assert "cue 3" in r.stdout


def test_cli_apply_writes_nothing_when_a_correction_does_not_fit(session):
    _run("import", "--dir", str(session))
    rec = session / "transcript_corrections.yaml"
    rec.write_text(rec.read_text(encoding="utf-8").replace(
        "the strength of the pandemic", "words never spoken"), encoding="utf-8")
    cleaned = session / "rec.transcript.cleaned.vtt"
    before = cleaned.read_bytes()
    r = _run("apply", "--dir", str(session))
    assert r.returncode == 2
    assert "Nothing written" in r.stderr
    assert cleaned.read_bytes() == before


def test_cli_import_refuses_to_clobber_without_force(session):
    assert _run("import", "--dir", str(session)).returncode == 0
    r = _run("import", "--dir", str(session))
    assert r.returncode == 2
    assert "--force" in r.stderr
    assert _run("import", "--dir", str(session), "--force").returncode == 0


def test_cli_apply_is_idempotent(session):
    _run("import", "--dir", str(session))
    _run("apply", "--dir", str(session))
    once = (session / "rec.transcript.cleaned.vtt").read_bytes()
    _run("apply", "--dir", str(session))
    assert (session / "rec.transcript.cleaned.vtt").read_bytes() == once


def test_cli_has_no_model_flags():
    """Deciding which mishearings deserve fixing is the scope decision this
    contract exists to take out of the pipeline."""
    out = _run("--help").stdout + _run("apply", "--help").stdout
    for flag in ("--model", "--backend", "--endpoint", "--fast"):
        assert flag not in out
