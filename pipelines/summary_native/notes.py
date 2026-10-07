"""The deterministic half of chunked state extraction (spec 033). No model call.

``extract`` makes the model calls; every decision about what a note may cite, quote or claim
is made here, by code, so no extraction output reaches a prose call unchecked (Principle II).

This module holds the shared primitives: loading the summaries for a range, reading a note's
citations, checking a quoted span against the evidence, and splitting a note into claims. The
code check itself, the drops report, the cache keys and the routing (T016) are added to it.

Quote matching and the citation grammar's building blocks are ``npc_check``'s, shared with
``npc_verify`` (Principle V). Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.summary_native import npc_check, schema
from pipelines.summary_native.npc_chunked import INVALID, OUTSIDE_CHUNK, UNCITED

#: Sorts a note whose citations cannot be read after every note that has one.
NO_CHAPTER = 9999

_SCENE_HEADING_RE = re.compile(r"^### (\d{3}\.\d{2})\b", re.M)
_FULL_CITE_RE = re.compile(r"\[ch \d{3} / [a-z0-9.]+(?:; ch \d{3} / [a-z0-9.]+)*\]")
#: The target part of a citation, when it is words (a section's heading text), not a scene id.
_WORD_TARGET_RE = re.compile(r"(ch \d{3} / )([A-Za-z][A-Za-z -]*[A-Za-z])(?=[;\]])")

#: A section cited by its own heading text is the same target as its key. Exact lookup over the
#: real headings (and two spellings of Memorable Moments), any case. Nothing else is accepted.
HEADING_KEYS: dict[str, str] = {
    **{h.casefold(): key for h, key in schema.SECTION_TARGETS.items()},
    **schema.SECTION_TARGET_ALIASES,
}
_H2_TO_KEY = {h: key for h, key in schema.SECTION_TARGETS.items()}


# ── Loading ─────────────────────────────────────────────────────────────────


@dataclass
class Chapter:
    """One session summary: its number, its path, its verbatim text and what may be cited in it.

    ``number`` and ``text`` are what ``npc_chunked.make_chunks`` needs.
    """

    number: int
    path: Path
    text: str
    #: Scene ids (``NNN.SS``) plus the section keys (``moment``, ``npcs`` ...) this chapter has.
    targets: set[str] = field(default_factory=set)


def load_chapters(summaries_dir: Path, since: int, until: int) -> list[Chapter]:
    """The summaries numbered ``since``..``until`` inclusive, in chapter order.

    A file is a chapter when its name starts with a number and a separator (``schema.PREFIX_RE``).
    The text is the file, verbatim. Sorted by chapter number, then file name, so the order never
    depends on the filesystem.
    """
    found: list[tuple[int, str, Path]] = []
    for p in Path(summaries_dir).glob("*.md"):
        m = schema.PREFIX_RE.match(p.name)
        if m and since <= int(m.group(1)) <= until:
            found.append((int(m.group(1)), p.name, p))
    out = []
    for number, _, p in sorted(found):
        text = p.read_text(encoding="utf-8")
        targets = set(_SCENE_HEADING_RE.findall(text))
        for line in text.splitlines():
            m = schema.H2_RE.match(line)
            if m and m.group(1) in _H2_TO_KEY:
                targets.add(_H2_TO_KEY[m.group(1)])
        out.append(Chapter(number, p, text, targets))
    return out


# ── Citations ───────────────────────────────────────────────────────────────


def _normalise_cite(bracket: str) -> str:
    return _WORD_TARGET_RE.sub(
        lambda m: m.group(1) + HEADING_KEYS.get(m.group(2).casefold(), m.group(2)), bracket
    )


def cites(text: str) -> list[tuple[str, int, str]]:
    """``[(bracket, chapter, target)]``, one per citation part, in text order.

    A heading's own text is accepted as its key, case-insensitively (``[ch 031 / NPCs]`` is
    ``npcs``); the returned bracket is the normalised one. A bracket that breaks the grammar,
    or names a heading that is not one of the section headings, yields chapter ``-1`` and an
    empty target, so callers count it as invalid.
    """
    out: list[tuple[str, int, str]] = []
    for raw in schema.STATE_CITE_RE.findall(text):
        b = _normalise_cite(raw)
        parts = schema.STATE_CITE_PART_RE.findall(b) if _FULL_CITE_RE.fullmatch(b) else []
        if not parts:
            out.append((b, -1, ""))
            continue
        for c, t in parts:
            out.append((b, int(c), t))
    return out


def cite_problem(text: str, allowed: dict[int, set[str]]) -> str | None:
    """Why ``text``'s citations are not good enough, or ``None`` when it has one and all resolve.

    ``allowed`` maps each chapter in the chunk to the targets that exist in it. Reasons are
    ``uncited``, ``invalid-citation <bracket>`` (malformed, an unknown heading, or a scene id
    belonging to another chapter) and ``outside-chunk <bracket>`` (well-formed, but not in
    this chunk).
    """
    found = cites(text)
    if not found:
        return UNCITED
    for bracket, ch, tgt in found:
        if ch < 0 or ("." in tgt and int(tgt[:3]) != ch):
            return f"{INVALID} {bracket}"
        if ch not in allowed or tgt not in allowed[ch]:
            return f"{OUTSIDE_CHUNK} {bracket}"
    return None


def first_chapter(text: str) -> int:
    """The chapter of ``text``'s first citation; ``NO_CHAPTER`` when it has none that parses."""
    found = cites(text)
    return found[0][1] if found and found[0][1] >= 0 else NO_CHAPTER


def claims_of(text: str) -> list[str]:
    """``text`` split after every citation bracket: each piece ends with the citation that backs it.

    Whatever follows the last bracket backs nothing and is not a claim.
    """
    out, last = [], 0
    for m in schema.STATE_CITE_RE.finditer(text):
        out.append(text[last : m.end()])
        last = m.end()
    return out


# ── Quoted spans ────────────────────────────────────────────────────────────


def bad_span(text: str, hay: str) -> str | None:
    """The first double-quoted span in ``text`` that is not verbatim in ``hay``, else ``None``.

    Verbatim means ``npc_check``'s comparison: exact, or equal after folding quote marks and
    apostrophes. A span shorter than four characters once its marks are stripped is too short to
    be evidence of anything and is skipped.
    """
    for span in npc_check.SPAN_RE.findall(text):
        inner = npc_check.strip_quote_marks(span)
        if len(inner) < 4:
            continue
        if npc_check._contains(hay, inner) is None:
            return span
    return None
