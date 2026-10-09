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

import hashlib
import json
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.summary_native import freshness, npc_check, npc_chunked, schema
from pipelines.summary_native.npc_chunked import INVALID, OUTSIDE_CHUNK, SPAN_NOT_FOUND, UNCITED

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


#: A bullet that opens with its citation as a bold label: ``- **ch 006 / 006.01** — text``. qwen3.8 writes
#: Events this way on some calls (OOTA ch 006, 013, 035-036, 048, 050), copying the ``**Name** —`` shape of
#: the other sections; every such bullet used to be dropped as uncited.
_LEADING_CITE_RE = re.compile(
    r"^-\s*\*\*\s*\[?\s*(ch \d{3} / [A-Za-z0-9.]+(?:\s*;\s*ch \d{3} / [A-Za-z0-9.]+)*)\s*\]?\s*\*\*\s*[—–:-]+\s*(\S.*)$"
)


def citation_to_end(text: str) -> str:
    """Move a leading bold citation to the end, where the grammar puts it: ``- **ch 006 / 006.01** — The
    party …`` becomes ``- The party … [ch 006 / 006.01]``. Only where the bullet begins with nothing but a
    citation; any other bullet is returned unchanged. The moved citation is then checked like any other
    (it must resolve inside the chunk), so this changes where a citation sits, never whether it holds."""
    m = _LEADING_CITE_RE.match(text)
    if not m:
        return text
    cite = re.sub(r"\s*;\s*", "; ", m.group(1))
    return f"- {m.group(2).rstrip()} [{cite}]"


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


def chapter_block(ch: Chapter) -> str:
    """One chapter as it appears in an extraction prompt (and in a prose call's last-chunk evidence)."""
    return f"\n\n======== CHAPTER {ch.number:03d} ({ch.path.name}) ========\n\n{ch.text.rstrip()}\n"


# ── Notes, drops and the code check (T016) ──────────────────────────────────

#: Note kinds in section order: Events, Concluded, Threads, NPC Status, World, Party.
KINDS: tuple[str, ...] = ("event", "concluded", "thread", "status_row", "world", "party")
_KIND_OF = dict(zip(schema.STATE_MAP_SECTIONS, KINDS))
_NONE_RE = re.compile(r"-\s*\(?none\)?\.?", re.I)
_THREAD_TAG_RE = re.compile(rf"^-\s*\[({'|'.join(schema.THREAD_TAGS)})\]")
_WORLD_TAG_RE = re.compile(rf"^-\s*\[({'|'.join(schema.WORLD_TAGS)})\]")
_SUBJECT_RE = re.compile(r"^-\s*\[[A-Z]+\]\s*\*\*(.+?)\*\*")
#: A party bullet: an optional ``[LEVEL]`` tag, then the bold subject (research R1).
_PARTY_SUBJECT_RE = re.compile(rf"^-\s*(?:\[({schema.LEVEL_TAG})\]\s*)?\*\*(.+?)\*\*")
#: The tag written inside the bold, ``**[LEVEL] Daz**`` (a form qwen3.8 produces): the same level row.
_INNER_LEVEL_RE = re.compile(rf"^\[({schema.LEVEL_TAG})\]\s*(.+)$")
#: The number of a level row: ``- [LEVEL] **Subject** — 9 [cite]``.
_LEVEL_VALUE_RE = re.compile(r"^-\s*(?:\[[A-Z]+\]\s*)?\*\*.+?\*\*\s*[—–:-]*\s*(\d{1,2})\b")
_ROW_RE = re.compile(
    r"^-\s*\*{0,2}([^|*]+?)\*{0,2}\s*\|\s*([A-Za-z]+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*(\[ch .*\])\s*$"
)

# Drop reasons (stable strings; they appear in drops.md and in tests).
NESTED_BULLET = "nested-bullet"
MISSING_THREAD_TAG = "missing-thread-tag"
MISSING_WORLD_TAG = "missing-world-tag"
MALFORMED_ROW = "malformed-row"
MISSING_PARTY_SUBJECT = "missing-party-subject"
LEVEL_NOT_IN_CITED_TEXT = "level-not-in-cited-text"
MALFORMED_LEVEL_ROW = "malformed-level-row"

# ── Levels (research R1) ────────────────────────────────────────────────────

_CARDINALS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty"
).split()
_ORDINALS = (
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
    "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth"
).split()
#: A phrase naming a spell level or slot is not a character level: "4th-level slot", "level 9 spells".
_SPELL_AFTER_RE = re.compile(r"[\s-]*(?:spells?|slots?)\b", re.I)


def _ordinal_digits(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _level_patterns(n: int) -> list["re.Pattern[str]"]:
    """The level phrases that state ``n`` (research R1): digit, word and ordinal spellings."""
    cardinal = [str(n)] + ([_CARDINALS[n]] if n < len(_CARDINALS) else [])
    ordinal = [_ordinal_digits(n)] + ([_ORDINALS[n]] if n < len(_ORDINALS) else [])
    any_form = "|".join(re.escape(f) for f in cardinal + ordinal)
    ord_form = "|".join(re.escape(f) for f in ordinal)
    return [re.compile(p, re.I) for p in (
        rf"\blevel\s+(?:{any_form})\b",                         # level 9 / level nine
        rf"\b(?:{ord_form})[\s-]+level\b",                      # 9th level / ninth-level
        rf"\blevels?\s+(?:up\s+)?to\s+(?:{any_form})\b",        # levels to 9 / levels up to 9
        rf"\breach(?:es|ed)?\s+(?:level\s+)?(?:{any_form})\b",  # reaches 9 / reached level nine
    )]


def level_stated(text: str, n: int) -> bool:
    """Whether ``text`` states character level ``n`` in a level phrase that is not a spell level."""
    for pat in _level_patterns(n):
        for m in pat.finditer(text):
            if not _SPELL_AFTER_RE.match(text, m.end()):
                return True
    return False


def target_text(ch: Chapter, target: str) -> str:
    """The text a citation target points to inside ``ch``: a scene (``NNN.SS``, from its ``###`` heading
    to the next ``###`` or ``##`` heading) or a section (``moment``, ``npcs``, ... from its ``##``
    heading to the next one). ``""`` when the chapter has no such target."""
    lines = ch.text.splitlines()
    out: list[str] = []
    taking = False
    for line in lines:
        if "." in target:
            m = schema.H3_RE.match(line)
            if m:
                taking = m.group(1).split(" ", 1)[0] == target
            elif line.startswith("## "):
                taking = False
        else:
            m = schema.H2_RE.match(line)
            if m:
                taking = _H2_TO_KEY.get(m.group(1)) == target
        if taking:
            out.append(line)
    return "\n".join(out)


def cited_text(text: str, by_number: dict[int, Chapter]) -> str:
    """The text of every section ``text`` cites, from the chapters in ``by_number``."""
    parts: list[str] = []
    seen: set[tuple[int, str]] = set()
    for _, chapter, target in cites(text):
        if chapter < 0 or (chapter, target) in seen or chapter not in by_number:
            continue
        seen.add((chapter, target))
        parts.append(target_text(by_number[chapter], target))
    return "\n".join(parts)


# ── Note ids (research R6) ──────────────────────────────────────────────────


def note_id(note: "Note") -> str:
    """A stable id: the same chapter, kind and text give the same id across re-extraction and chunking."""
    return "n-" + hashlib.sha1(f"{note.first_chapter:03d}|{note.kind}|{note.text}".encode("utf-8")).hexdigest()[:10]

#: A chunk is an outlier (a possible runaway call) above this multiple of the run's median drops
#: per chunk, and at or above this many drops (research R4).
OUTLIER_FACTOR = 3
OUTLIER_FLOOR = 20


@dataclass(frozen=True)
class Note:
    """One kept, checked statement (data-model.md). ``text`` is the bullet verbatim, "- " included."""

    kind: str
    text: str
    first_chapter: int
    chunk: str
    tag: str | None = None
    subject: str | None = None
    # a status row only
    status: str | None = None
    location: str | None = None
    disposition: str | None = None
    cite: str | None = None
    # a party level row only: the checked number (spec 034)
    level: int | None = None

    _FIELDS = ("kind", "text", "first_chapter", "chunk", "tag", "subject", "status", "location", "disposition",
               "cite", "level")

    @property
    def note_id(self) -> str:
        """The stable id of this note (research R6); see :func:`note_id`."""
        return note_id(self)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self._FIELDS}

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        return cls(**{k: d.get(k) for k in cls._FIELDS})


@dataclass(frozen=True)
class Drop:
    """A dropped note with the reason (``chunk``, ``kind``, ``reason``, ``text``)."""

    chunk: str
    kind: str
    reason: str
    text: str

    def to_dict(self) -> dict:
        return {"chunk": self.chunk, "kind": self.kind, "reason": self.reason, "text": self.text}


@dataclass
class CheckedChunk:
    """What survived the code check for one chunk, and what did not."""

    chunk: str  # "002-003"
    notes: list[Note] = field(default_factory=list)
    drops: list[Drop] = field(default_factory=list)
    #: Outline headings the raw output never wrote. A chunk with any is a failed chunk and is not
    #: saved, so a ``checked.json`` carries the key only if one was written by hand.
    missing: list[str] = field(default_factory=list)

    def kept(self, kind: str) -> list[Note]:
        return [n for n in self.notes if n.kind == kind]

    def counts(self) -> dict:
        reasons: dict[str, int] = {}
        for d in self.drops:
            key = d.reason.split(" ")[0]
            reasons[key] = reasons.get(key, 0) + 1
        return {
            "kept": {k: len(self.kept(k)) for k in KINDS},
            "dropped": len(self.drops),
            "reasons": dict(sorted(reasons.items())),
        }

    def to_dict(self) -> dict:
        d = {"chunk": self.chunk, "notes": [n.to_dict() for n in self.notes], "drops": [d.to_dict() for d in self.drops]}
        if self.missing:
            d["missing"] = list(self.missing)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CheckedChunk":
        return cls(
            d["chunk"],
            [Note.from_dict(n) for n in d.get("notes", [])],
            [Drop(x["chunk"], x["kind"], x["reason"], x["text"]) for x in d.get("drops", [])],
            list(d.get("missing", [])),
        )


def check_chunk(raw: str, chunk: Sequence[Chapter], label: str | None = None) -> CheckedChunk:
    """Check one extraction output against its chunk's chapters: keep what passes, drop what does not.

    A heading of ``schema.STATE_MAP_SECTIONS`` absent from ``raw`` is listed in ``missing``; present
    but empty (or ``- (none)``) is a legitimate empty answer.

    Order of checks, first failure wins: nested bullet, citation (uncited / invalid / outside the
    chunk), quoted span, then the tag or row format of the section. A drop keeps the note's text and
    the reason, so nothing disappears without a record.
    """
    label = label or npc_chunked.chunk_range(chunk)
    allowed = {c.number: c.targets for c in chunk}
    by_number = {c.number: c for c in chunk}
    hay = npc_chunked.chunk_text(chunk)
    secs = npc_check.parse_sections(raw)
    res = CheckedChunk(label)
    for heading in schema.STATE_MAP_SECTIONS:
        kind = _KIND_OF[heading]
        # An absent heading is not an empty answer: the prompt requires all six sections, and an empty
        # one is left empty or written `- (none)`, so a section never written is one the model skipped
        # (#515). The caller fails the chunk.
        if heading not in secs:
            res.missing.append(heading)
        first, lines = secs.get(heading, (0, []))
        for b in npc_check.bullets(lines, first):
            text = b.text

            def drop(reason: str) -> None:
                res.drops.append(Drop(label, kind, reason, text))

            if b.indent:
                drop(NESTED_BULLET)
                continue
            if _NONE_RE.fullmatch(text):
                continue
            text = citation_to_end(text)
            why = cite_problem(text, allowed)
            if why:
                drop(why)
                continue
            span = bad_span(text, hay)
            if span:
                drop(f"{SPAN_NOT_FOUND} {span}")
                continue
            fc = first_chapter(text)
            if kind == "thread":
                m = _THREAD_TAG_RE.match(text)
                if not m:
                    drop(MISSING_THREAD_TAG)
                    continue
                s = _SUBJECT_RE.match(text)
                res.notes.append(Note(kind, text, fc, label, tag=m.group(1), subject=s.group(1).strip() if s else None))
            elif kind == "world":
                m = _WORLD_TAG_RE.match(text)
                if not m:
                    drop(MISSING_WORLD_TAG)
                    continue
                s = _SUBJECT_RE.match(text)
                res.notes.append(Note(kind, text, fc, label, tag=m.group(1), subject=s.group(1).strip() if s else None))
            elif kind == "status_row":
                m = _ROW_RE.match(text)
                if not m or m.group(2) not in schema.STATUSES:
                    drop(MALFORMED_ROW)
                    continue
                res.notes.append(Note(
                    kind, text, fc, label, subject=m.group(1).strip(), status=m.group(2),
                    location=m.group(3) or "—", disposition=m.group(4) or "—", cite=_normalise_cite(m.group(5)),
                ))
            elif kind == "party":
                m = _PARTY_SUBJECT_RE.match(text)
                if not m:
                    drop(MISSING_PARTY_SUBJECT)
                    continue
                subject, tag, level = m.group(2).strip(), m.group(1), None
                inner = _INNER_LEVEL_RE.match(subject)
                if inner and tag is None:
                    tag, subject = inner.group(1), inner.group(2).strip()
                if tag == schema.LEVEL_TAG:
                    v = _LEVEL_VALUE_RE.match(text)
                    if not v:
                        drop(MALFORMED_LEVEL_ROW)
                        continue
                    level = int(v.group(1))
                    if not level_stated(cited_text(text, by_number), level):
                        drop(LEVEL_NOT_IN_CITED_TEXT)
                        continue
                res.notes.append(Note(kind, text, fc, label, tag=tag, subject=subject, level=level))
            else:
                res.notes.append(Note(kind, text, fc, label))
    return res


def cache_key(*, system: str, user: str, backend: str, model: str | None, max_tokens: int, chunk_chars: int,
              audience: str = "gm", filtered_payload_digest: str | None = None,
              authority_policy_version: int | None = None, authority_records_digest: str | None = None,
              source_digest: str | None = None, selection_membership_digest: str | None = None) -> str:
    """Hash of everything that decides a chunk's extraction (research R5): the prompts (the user
    prompt holds the chapter texts and the outline), backend, model, ``max_tokens`` and ``chunk_chars``."""
    sha = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()  # noqa: E731
    payload = {
        "system_sha": sha(system), "user_sha": sha(user), "backend": backend, "model": model,
        "max_tokens": max_tokens, "chunk_chars": chunk_chars,
        "audience": audience, "filtered_payload_digest": filtered_payload_digest,
        "authority_policy_version": authority_policy_version,
        "authority_records_digest": authority_records_digest, "source_digest": source_digest,
        "selection_membership_digest": selection_membership_digest,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


# ── Routing (research R8) ───────────────────────────────────────────────────


def stitched(results: Sequence[CheckedChunk], kind: str, tag: str | None = None) -> list[str]:
    """The kept notes of ``kind`` (optionally one ``tag``) from every chunk: exact duplicates removed,
    stably sorted by the chapter of the first citation. Nothing is merged, reworded or reordered beyond that."""
    seen: set[str] = set()
    keyed: list[tuple[int, str]] = []
    for r in results:
        for n in r.notes:
            if n.kind != kind or (tag and not n.text.startswith(f"- [{tag}]")) or n.text in seen:
                continue
            seen.add(n.text)
            keyed.append((n.first_chapter, n.text))
    return [t for _, t in sorted(keyed, key=lambda kt: kt[0])]


def thread_ledger(results: Sequence[CheckedChunk]) -> list[str]:
    """Every thread note (opened, advanced, resolved, abandoned), in chapter order."""
    return stitched(results, "thread")


# ── Drops report ────────────────────────────────────────────────────────────


def outliers_of(drop_counts: Sequence[tuple[str, int]]) -> list[str]:
    """The labels of ``(label, drops)`` pairs above 3x the median and at least 20: a possible runaway call."""
    if not drop_counts:
        return []
    median = statistics.median(n for _, n in drop_counts)
    return [label for label, n in drop_counts if n > OUTLIER_FACTOR * median and n >= OUTLIER_FLOOR]


def outlier_chunks(results: Sequence[CheckedChunk]) -> list[str]:
    """Chunks whose drop count is above 3x the run's median and at least 20: a possible runaway call."""
    return outliers_of([(r.chunk, len(r.drops)) for r in results])


def render_drops_md(results: Sequence[CheckedChunk], incomplete: Sequence[tuple[str, Sequence[str]]] = ()) -> str:
    """``drops.md``: counts per chunk and per reason, outliers flagged, then every drop with its text.

    ``incomplete`` is ``(chunk, missing headings)`` for each chunk that failed for want of a section;
    those chunks have no notes, so they would otherwise not appear here at all (#515)."""
    out_set = set(outlier_chunks(results))
    median = statistics.median(len(r.drops) for r in results) if results else 0
    total = sum(len(r.drops) for r in results)
    kept = sum(len(r.notes) for r in results)
    lines = [
        "# Extraction drops", "",
        f"{total} notes dropped across {len(results)} chunks ({kept} kept). Every drop is listed with its reason.",
        "", "## Chunks", "", "| Chunk | Kept | Dropped | |", "|---|---|---|---|",
    ]
    for r in results:
        flag = f"⚠ OUTLIER (more than {OUTLIER_FACTOR}x the median of {median:g}; possible runaway)" if r.chunk in out_set else ""
        lines.append(f"| {r.chunk} | {len(r.notes)} | {len(r.drops)} | {flag} |")
    by_reason: dict[str, int] = {}
    for r in results:
        for k, n in r.counts()["reasons"].items():
            by_reason[k] = by_reason.get(k, 0) + n
    lines += ["", "## Dropped by reason", ""]
    lines += [f"- {k}: {n}" for k, n in sorted(by_reason.items())] or ["- (none)"]
    if incomplete:
        lines += ["", "## Incomplete chunks (failed: output missing outline sections; no notes kept)", ""]
        lines += [f"- {chunk}: missing {', '.join(missing)}" for chunk, missing in incomplete]
    for r in results:
        if not r.drops:
            continue
        lines += ["", f"## Chunk {r.chunk} — {len(r.drops)} dropped" + ("  ⚠ OUTLIER" if r.chunk in out_set else "")]
        lines += [f"- [{d.kind}] {d.reason}: {d.text.replace(chr(10), ' // ')}" for d in r.drops]
    return "\n".join(lines) + "\n"


# ── Reading the notes back ──────────────────────────────────────────────────


class NotesIncomplete(ValueError):
    """The extraction did not finish: a chunk is failed, pending or no longer matches its cache key."""


def chunk_stem(index: int, chapters: str) -> str:
    return f"chunk{index:02d}.{chapters}"


def load_checked(range_dir: Path, *, audience: str = "gm") -> tuple[dict, list[CheckedChunk]]:
    """``(manifest, [CheckedChunk])`` for a finished extraction, in chunk order.

    Raises ``NotesIncomplete`` naming every chunk that has no checked result matching the manifest.
    """
    nd = freshness.notes_dir(range_dir, audience)
    manifest = json.loads((nd / freshness.NOTES_MANIFEST).read_text(encoding="utf-8"))
    results: list[CheckedChunk] = []
    missing: list[str] = []
    for c in manifest.get("chunks", []):
        p = nd / f"{chunk_stem(c['index'], c['chapters'])}.checked.json"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            missing.append(c["chapters"])
            continue
        if data.get("cache_key") != c.get("cache_key"):
            missing.append(c["chapters"])
            continue
        results.append(CheckedChunk.from_dict(data))
    if missing or not manifest.get("complete"):
        raise NotesIncomplete(
            "the extraction is incomplete" + (f" (no checked notes for chunk(s) {', '.join(missing)})" if missing else "")
        )
    return manifest, results
