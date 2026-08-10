"""Structural WebVTT parsing — cues you can address, edit, and write back.

``session_doc/io.py:parse_vtt`` is the *lossy* reader: it throws away cue
numbers, timings and structure and hands back speaker dialogue, which is all
the generation stages need. This module is the lossless one. It exists because
the extraction contract (#250, R4) makes ``*.transcript.cleaned.vtt`` a
**generated** file, and generating one means being able to rewrite a single
cue's text and re-emit everything else byte-for-byte.

**Cue index, never file line.** Applying corrections to a transcript shifts
every line number in the document while every cue index stays exactly where it
was — that is the whole reason the contract keys on cues (#250, C2). The parser
preserves the cue number *as written* rather than renumbering, so an index in a
correction file keeps pointing at the same utterance forever.

**Generated NOTE blocks are dropped on read.** A round-trip must be a fixed
point: parse → render → parse gives the same cues and the same generated
header. Anything the generator wrote is therefore not input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: `00:02:41.730 --> 00:02:42.520`, optionally followed by cue settings.
TIMING_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}(?:\s+\S.*)?$"
)
_CUE_NUMBER_RE = re.compile(r"^\d+$")

#: Marks a NOTE block this module wrote. Reading drops these; every other NOTE
#: in the file is the author's and is preserved. Colon-free on purpose — see
#: :func:`render`; the obvious `cg:generated` is rejected by render's own guard.
GENERATED_MARK = "cg-generated"


class VttError(ValueError):
    """The file is not WebVTT, or a cue is malformed."""


@dataclass
class Cue:
    """One utterance. ``index`` is the number as written in the file."""

    index: int
    timing: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Payload as one string. Multi-line cues join with a newline."""
        return "\n".join(self.lines)

    def with_text(self, text: str) -> "Cue":
        return Cue(index=self.index, timing=self.timing, lines=text.split("\n"))


@dataclass
class Transcript:
    """A parsed WebVTT file: a header, author NOTE blocks, and cues."""

    signature: str                       # the WEBVTT line, verbatim
    notes: list[list[str]] = field(default_factory=list)   # author NOTE blocks
    cues: list[Cue] = field(default_factory=list)

    def by_index(self) -> dict[int, Cue]:
        return {c.index: c for c in self.cues}

    def cue(self, index: int) -> Cue | None:
        return self.by_index().get(index)


def _is_note(block: list[str]) -> bool:
    return bool(block) and block[0].upper().startswith("NOTE")


def parse(text: str) -> Transcript:
    """Parse WebVTT losslessly enough to write it back.

    Tolerant of CRLF (every line ending is normalised away — see
    :func:`render`, which emits LF and says so). Raises rather than returning
    an empty transcript: a caller that regenerates a tape from a file it could
    not parse would write an empty tape over a real one.
    """
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    if not lines or not lines[0].lstrip("﻿").upper().startswith("WEBVTT"):
        raise VttError("not a WebVTT file — first line is not WEBVTT")

    signature = lines[0].lstrip("﻿")
    blocks: list[list[str]] = []
    current: list[str] = []
    for ln in lines[1:]:
        if ln.strip():
            current.append(ln)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    tx = Transcript(signature=signature)
    for block in blocks:
        if _is_note(block):
            if not any(GENERATED_MARK in ln for ln in block):
                tx.notes.append(block)
            continue

        # A cue is [number] timing payload..., or timing payload... when the
        # producer omitted numbers. Zoom always numbers; handle both.
        head = 0
        index: int | None = None
        if _CUE_NUMBER_RE.match(block[0].strip()):
            index = int(block[0].strip())
            head = 1
        if head >= len(block) or not TIMING_RE.match(block[head].strip()):
            raise VttError(
                f"malformed cue near {block[0]!r} — expected a timing line, got "
                f"{block[head].strip()!r}" if head < len(block)
                else f"malformed cue near {block[0]!r} — no timing line"
            )
        if index is None:
            index = len(tx.cues) + 1
        payload = block[head + 1:]
        if not payload:
            raise VttError(f"cue {index} has a timing line but no text")
        tx.cues.append(Cue(index=index, timing=block[head].strip(), lines=payload))

    if not tx.cues:
        raise VttError("parsed to zero cues — wrong file, or not a WebVTT?")
    return tx


def render(tx: Transcript, generated_note: list[str] | None = None) -> str:
    """Serialise back to WebVTT text. **Always LF**, whatever came in.

    The line-ending normalisation is deliberate and is declared rather than
    silent: the raw Zoom tapes are CRLF, the hand-edited `.cleaned` siblings
    were LF, and nothing downstream cares — but a generator that quietly
    rewrote every line ending would make a byte-comparison between the two
    files useless, which is exactly the check that proves the record complete.

    ``generated_note`` lines must be colon-free. ``session_doc/io.py``'s reader
    skips `^NOTE`, but ``session_doc/vtt_voice_compare.py``'s does not — it
    keeps anything matching ``^([^:]+):\\s*(.+)$``, so a NOTE line containing a
    colon leaks into that tool as a line of dialogue.
    """
    out: list[str] = [tx.signature, ""]
    if generated_note:
        for ln in generated_note:
            if ":" in ln:
                raise VttError(
                    f"generated NOTE line contains a colon and would be read as "
                    f"dialogue by vtt_voice_compare: {ln!r}"
                )
            out.append(ln if ln.upper().startswith("NOTE") else f"NOTE {ln}")
        out.append("")
    for block in tx.notes:
        out.extend(block)
        out.append("")
    for cue in tx.cues:
        out.append(str(cue.index))
        out.append(cue.timing)
        out.extend(cue.lines)
        out.append("")
    return "\n".join(out)
