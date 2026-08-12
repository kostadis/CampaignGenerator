"""Cue-indexed transcript corrections — the record the tape is generated from.

Extraction contract #250, **R4**. A transcription garble is a defect in the
ground truth (R2), and the remedy is a per-cue correction — never a global
string replace, which would need a model to carve out the exceptions and would
flatten a deliberate in-character fumble on the way past.

R4 decides where those corrections *live*. Before it, the answer was "someone
edits ``*.transcript.cleaned.vtt`` and explains it in a NOTE block", and the
consequence was measurable: on Phandalin ch46 the cleaned tape carried **74
unrecorded substitutions** over its raw sibling, made by a chat-driven spell
pass with no reviewable output. Among them, ``"Brynn and Giles"`` became
``"Brynn and Giles Slipper-Shine"`` — a surname nobody said, written into the
ground truth — and ``"the Telosians have been defeated"`` became ``"the
Talosian have been defeated"``, fixing the spelling and breaking the grammar.
Neither was reviewable, because nothing enumerated the edits.

So: **the record is the source of truth and the cleaned tape is output.**

* the raw ``*.transcript.vtt`` is the archive and is never written
* ``transcript_corrections.yaml`` is hand-authored, one entry per cue
* ``apply`` regenerates the cleaned tape from those two, deterministically

**``was`` is checked, not trusted.** Applying refuses when a cue's current text
does not equal the correction's ``was``. That is what makes the record
self-invalidating rather than silently wrong: if the raw tape is ever replaced,
every stale correction fails loudly instead of pasting yesterday's repair over
today's words.

**``verified: false`` is a question, not a fact** — the same meaning it carries
in ``provenance/corrections.py``. Entries reverse-engineered from an
already-edited tape start unverified by construction, because nobody reviewed
them; they are a backlog, and reporting them as settled would launder an
unreviewed model pass into canon.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .vtt import GENERATED_MARK, Cue, Transcript, VttError, parse, render

#: Conventional filename, beside the transcript it governs.
RECORD_NAME = "transcript_corrections.yaml"

#: What ``apply`` writes when the record does not name an output explicitly.
_RAW_SUFFIX = ".vtt"
_CLEAN_SUFFIX = ".cleaned.vtt"


class CorrectionsError(Exception):
    """The record could not be loaded, or does not fit the transcript."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptCorrection(_Strict):
    """One cue, one repair, one piece of evidence."""

    id: str
    cue: int
    was: str
    now: str
    recorded: date
    recorded_by: str = "GM"
    verified: bool = True
    note: str | None = None

    @field_validator("id")
    @classmethod
    def _id_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("id must be a non-empty slug so a GM can refer to one")
        return v

    @field_validator("cue")
    @classmethod
    def _cue_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("cue must be a 1-based cue index, not a file line number")
        return v

    @model_validator(mode="after")
    def _is_a_change(self) -> "TranscriptCorrection":
        if self.was == self.now:
            raise ValueError(
                f"correction {self.id!r} changes nothing — was and now are identical"
            )
        return self


class TranscriptCorrectionRecord(_Strict):
    version: int = 1
    transcript: str
    output: str | None = None
    corrections: list[TranscriptCorrection] = []

    @field_validator("version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != 1:
            raise ValueError(f"unknown record version {v!r}; this build understands version 1")
        return v

    @model_validator(mode="after")
    def _one_entry_per_cue_and_unique_ids(self) -> "TranscriptCorrectionRecord":
        seen_ids: set[str] = set()
        seen_cues: set[int] = set()
        for c in self.corrections:
            if c.id in seen_ids:
                raise ValueError(f"duplicate correction id {c.id!r}")
            # Two corrections on one cue cannot both hold: the second's `was`
            # describes a tape the first already changed, so which wins would
            # depend on file order. Refuse instead of picking.
            if c.cue in seen_cues:
                raise ValueError(
                    f"cue {c.cue} has more than one correction — merge them into "
                    f"one entry whose `now` is the final text"
                )
            seen_ids.add(c.id)
            seen_cues.add(c.cue)
        return self

    @property
    def unverified(self) -> list[TranscriptCorrection]:
        return [c for c in self.corrections if not c.verified]

    def output_name(self) -> str:
        if self.output:
            return self.output
        if self.transcript.endswith(_CLEAN_SUFFIX):
            raise CorrectionsError(
                f"transcript {self.transcript!r} is already a .cleaned.vtt — point "
                f"`transcript:` at the raw archive, which is what gets regenerated from"
            )
        if not self.transcript.endswith(_RAW_SUFFIX):
            raise CorrectionsError(f"transcript {self.transcript!r} is not a .vtt")
        return self.transcript[: -len(_RAW_SUFFIX)] + _CLEAN_SUFFIX


# ── Loading ──────────────────────────────────────────────────────────────────

def load_record(path: str | Path) -> TranscriptCorrectionRecord:
    path = Path(path)
    if not path.is_file():
        raise CorrectionsError(f"no transcript-corrections record at {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CorrectionsError(f"{path} is not valid YAML:\n  {exc}") from exc
    if raw is None:
        raise CorrectionsError(f"{path} is empty")
    if not isinstance(raw, dict):
        raise CorrectionsError(f"{path} must contain a mapping at the top level")
    try:
        return TranscriptCorrectionRecord.model_validate(raw)
    except ValidationError as exc:
        raise CorrectionsError(f"{path} failed validation:\n{exc}") from exc


def load_transcript(path: str | Path) -> Transcript:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CorrectionsError(f"transcript not readable: {path} ({exc})") from exc
    try:
        return parse(text)
    except VttError as exc:
        raise CorrectionsError(f"{path}: {exc}") from exc


# ── Applying ─────────────────────────────────────────────────────────────────

@dataclass
class ApplyResult:
    text: str
    applied: list[TranscriptCorrection] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def generated_note(record: TranscriptCorrectionRecord) -> list[str]:
    """The header block the regenerated tape carries.

    Historically colon-free because :func:`campaignlib.vtt.render` guarded
    against it — that guard existed only for the old
    ``session_doc/vtt_voice_compare.py`` regex scan, which had no NOTE rule
    and would misread a colon here as dialogue. That reader was rewired onto
    structural parsing and the guard removed (#263); the " - " separator
    below is kept as-is regardless, since changing generated output is out
    of scope here. Carries no timestamp, so regenerating twice produces
    identical bytes; the record's own ``recorded`` dates are where "when"
    lives.
    """
    n = len(record.corrections)
    unverified = len(record.unverified)
    lines = [
        f"NOTE {GENERATED_MARK} - do not hand-edit this file.",
        f"NOTE Generated from {record.transcript} plus {RECORD_NAME}",
        "NOTE per CampaignGenerator issue 250 rule R4. The raw sibling is the",
        "NOTE untouched archive; edits belong in the record, not here.",
        f"NOTE {n} correction(s) applied, line endings normalised to LF.",
    ]
    if unverified:
        lines.append(
            f"NOTE {unverified} of them are unreviewed - see verified false in the record."
        )
    return lines


def apply_record(
    record: TranscriptCorrectionRecord, transcript: Transcript
) -> ApplyResult:
    """Regenerate the cleaned tape. Refuses per-correction rather than guessing.

    A correction whose cue is missing, or whose ``was`` no longer matches, is
    **not applied** and is reported. Partial application is the right failure
    mode here: the caller writes nothing unless every correction held, so a
    tape is never left half-repaired, but the report names each failure so the
    GM fixes the record rather than re-deriving which entry went stale.
    """
    by_index = transcript.by_index()
    result = ApplyResult(text="")
    fixed: dict[int, Cue] = {}

    for c in record.corrections:
        cue = by_index.get(c.cue)
        if cue is None:
            result.problems.append(
                f"{c.id}: cue {c.cue} is not in {record.transcript} "
                f"(it has {len(transcript.cues)} cues) — a file line number, perhaps?"
            )
            continue
        if cue.text != c.was:
            result.problems.append(
                f"{c.id}: cue {c.cue} does not say what `was` claims.\n"
                f"      record: {c.was!r}\n"
                f"      tape:   {cue.text!r}"
            )
            continue
        fixed[c.cue] = cue.with_text(c.now)
        result.applied.append(c)

    out = Transcript(
        signature=transcript.signature,
        notes=list(transcript.notes),
        cues=[fixed.get(c.index, c) for c in transcript.cues],
    )
    result.text = render(out, generated_note(record))
    return result


# ── Importing an already-edited tape ─────────────────────────────────────────

def diff_cues(raw: Transcript, edited: Transcript) -> list[tuple[int, str, str]]:
    """Every cue whose text differs, as (index, raw_text, edited_text).

    Raises when the two files do not share a cue index set. That is not
    pedantry: a tape whose cues were added, removed or renumbered is not an
    edit of the other one, and pairing them positionally would attribute the
    wrong repair to every cue after the first divergence.
    """
    a, b = raw.by_index(), edited.by_index()
    if set(a) != set(b):
        only_raw = sorted(set(a) - set(b))[:5]
        only_edit = sorted(set(b) - set(a))[:5]
        raise CorrectionsError(
            "the two transcripts do not carry the same cue indices, so one is "
            "not an edit of the other.\n"
            f"      only in raw:    {only_raw or 'none'}\n"
            f"      only in edited: {only_edit or 'none'}"
        )
    return [(i, a[i].text, b[i].text) for i in sorted(a) if a[i].text != b[i].text]


def import_edits(
    raw: Transcript,
    edited: Transcript,
    *,
    transcript_name: str,
    recorded: date,
    verified: bool = False,
    recorded_by: str = "GM",
) -> TranscriptCorrectionRecord:
    """Reverse-engineer a record from a tape somebody already hand-edited.

    ``verified`` defaults to **False** and should stay there for a real import.
    These entries were not reviewed — that is the entire reason the import
    exists — and marking them verified would launder an unreviewed pass into
    canon in the one file the whole pipeline treats as ground truth.
    """
    corrections = [
        TranscriptCorrection(
            id=f"cue-{index:04d}",
            cue=index,
            was=was,
            now=now,
            recorded=recorded,
            recorded_by=recorded_by,
            verified=verified,
            note="reverse-engineered from an already-edited transcript; not reviewed",
        )
        for index, was, now in diff_cues(raw, edited)
    ]
    return TranscriptCorrectionRecord(
        version=1, transcript=transcript_name, corrections=corrections
    )


def dump_record(record: TranscriptCorrectionRecord) -> str:
    """Serialise for hand-editing: block scalars off, keys in authoring order."""
    payload = {
        "version": record.version,
        "transcript": record.transcript,
        **({"output": record.output} if record.output else {}),
        "corrections": [
            {
                "id": c.id,
                "cue": c.cue,
                "was": c.was,
                "now": c.now,
                "recorded": c.recorded,
                **({"recorded_by": c.recorded_by} if c.recorded_by != "GM" else {}),
                "verified": c.verified,
                **({"note": c.note} if c.note else {}),
            }
            for c in record.corrections
        ],
    }
    header = (
        "# Transcript corrections — the record the .cleaned.vtt is generated from.\n"
        "# CampaignGenerator #250 R4. Edit this file, then run:\n"
        "#     sd_corrections apply --dir .\n"
        "# `was` is checked against the raw tape on every apply, so a stale entry\n"
        "# fails loudly instead of pasting an old repair over new words.\n"
        "# `verified: false` means nobody has reviewed this one yet.\n"
    )
    return header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=10**6)
