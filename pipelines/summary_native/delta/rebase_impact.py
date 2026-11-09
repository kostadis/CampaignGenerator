"""Deterministic impact of a source correction on a grounding baseline (spec 040, T011, research R4).

What proves a line is *affected* is the one dependency index every line carries: its ``[ch NNN / ENTRY]``
citation.  Each selected chapter's old and current bytes are cut into entries (a scene ``NNN.SS``, a
``## Section`` such as ``npcs`` or ``moment``, or a named heading) and each entry is marked changed, removed,
unchanged (or added) with its byte span in each version.  A baseline line citing a changed or removed entry
is affected; a citation whose entry cannot be found in either version is affected as ``whole_chapter``
(the corrected chapter differs, and nothing narrower is provable).

Whole-file members with no per-source map (the timeline and ``reference/**``) are never guessed at: they are
listed as *unknown impact* when they cite a selected chapter or carry no citation at all.  Published NPC
dossiers that cite a selected chapter are listed as follow-up consumers.  No model, no write, no similarity.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native.claims.selection import _CITATION
from pipelines.summary_native.promotion.models import GenerationManifest

from .baseline import TIMELINE_NAME

_SCENE_ID = re.compile(r"^(\d{3,}\.\d{2})\b")
_SECTION_KEYS = {"memorable moments": "moment", "session-end state": "end"}


# --------------------------------------------------------------------------- models

class EntryDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: str
    status: str  # changed | removed | unchanged | added
    old_span: tuple[int, int] | None = None
    new_span: tuple[int, int] | None = None


class SourceImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int
    path: str
    old_sha256: str
    new_sha256: str
    entries: list[EntryDiff] = Field(default_factory=list)
    diff_ref: str


class AffectedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str
    document: str
    line_no: int
    line_sha256: str
    citation: str
    chapter: int
    entry: str
    reason: str  # changed | removed | whole_chapter
    origin: str  # baseline | pending


class AffectedAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotation_id: str
    source_sha256: str
    span: tuple[int, int] | None = None
    chapter: int | None = None


class UnknownMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member: str
    reason: str  # cites_selected | no_citations


class FollowUp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str
    chapters: list[int]


class ImpactSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[SourceImpact]
    affected_lines: list[AffectedLine]
    affected_annotations: list[AffectedAnnotation]
    unknown_members: list[UnknownMember]
    followup_consumers: list[FollowUp]
    impact_sha256: str = ""

    def seal(self) -> "ImpactSet":
        return self.model_copy(update={"impact_sha256": impact_digest(self)})

    def lines_of(self, chapter: int, origin: str | None = None) -> list[AffectedLine]:
        return [l for l in self.affected_lines if l.chapter == chapter and (origin is None or l.origin == origin)]

    def annotations_of(self, chapter: int) -> list[AffectedAnnotation]:
        return [a for a in self.affected_annotations if a.chapter == chapter]


class SourceChange(NamedTuple):
    chapter: int
    path: str
    old: bytes
    new: bytes


def impact_digest(impact: ImpactSet) -> str:
    body = impact.model_dump(mode="json")
    body.pop("impact_sha256", None)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- entries

def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def parse_entries(data: bytes) -> dict[str, tuple[int, int]]:
    """``entry -> (start, end)`` byte spans.  A ``## Section`` entry covers its ``###`` children, which are
    also entries of their own, so ``[ch 003 / Warden Hale]`` and ``[ch 003 / npcs]`` both resolve."""
    lines = data.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)
    total = len(data)
    heads: list[tuple[int, int, str]] = []  # (line index, level, text)
    for i, raw in enumerate(lines):
        text = raw.decode("utf-8", "replace").rstrip("\r\n")
        m = re.match(r"^(#{2,3})\s+(.+?)\s*#*\s*$", text)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    entries: dict[str, tuple[int, int]] = {}

    def add(key: str, start: int, end: int) -> None:
        base, n = key, 1
        while key in entries:
            n += 1
            key = f"{base}#{n}"
        entries[key] = (start, end)

    first = offsets[heads[0][0]] if heads else total
    if first > 0:
        add("_header", 0, first)
    section = ""
    for h, (i, level, text) in enumerate(heads):
        start = offsets[i]
        end = total
        for j, lv, _t in heads[h + 1:]:
            if lv <= level:
                end = offsets[j]
                break
        if level == 2:
            section = _slug(text)
            add(_SECTION_KEYS.get(section, section), start, end)
            if section == "scenes":  # the scenes section's own text is only what precedes its first scene
                child = next((offsets[j] for j, lv, _t in heads[h + 1:] if lv == 3 and j > i), None)
                if child is not None and child < end:
                    entries["scenes"] = (start, child)
        else:
            m = _SCENE_ID.match(text)
            add(m.group(1) if m else _slug(text), start, end)
    return entries


def diff_entries(old: bytes, new: bytes) -> list[EntryDiff]:
    a, b = parse_entries(old), parse_entries(new)
    out: list[EntryDiff] = []
    for key in list(a) + [k for k in b if k not in a]:
        o, n = a.get(key), b.get(key)
        if o is None:
            status = "added"
        elif n is None:
            status = "removed"
        else:
            status = "unchanged" if old[o[0]:o[1]] == new[n[0]:n[1]] else "changed"
        out.append(EntryDiff(entry=key, status=status, old_span=o, new_span=n))
    return out


def changed_old_regions(old: bytes, new: bytes) -> list[tuple[int, int]]:
    """Byte ranges of ``old`` that were replaced or deleted (an insert-only change touches no old byte)."""
    a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in a:
        offsets.append(pos)
        pos += len(ln)
    offsets.append(pos)
    return [(offsets[i1], offsets[i2]) for tag, i1, i2, _j1, _j2
            in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag in ("replace", "delete")]


# --------------------------------------------------------------------------- lines

def line_id(document: str, line: bytes, occurrence: int) -> str:
    """``<doc>#<sha256(line)[:12]>@<occurrence>`` (1-based among byte-identical lines of the document); stable
    against unrelated line-number shifts.  The line is hashed without its terminator."""
    digest = _sha(line.rstrip(b"\r\n"))
    return f"{document}#{digest[:12]}@{occurrence}"


def indexed_lines(document: str, data: bytes) -> list[tuple[str, int, bytes]]:
    """``(line_id, line_no, line)`` for every line of ``data``."""
    seen: dict[bytes, int] = {}
    out = []
    for n, raw in enumerate(data.splitlines(keepends=True), start=1):
        key = raw.rstrip(b"\r\n")
        seen[key] = seen.get(key, 0) + 1
        out.append((line_id(document, raw, seen[key]), n, raw))
    return out


def find_line(docs: Mapping[str, bytes], lid: str) -> tuple[str, int, bytes] | None:
    """``(document, line_no, line)`` the id addresses in ``docs`` (None when it addresses nothing)."""
    document = lid.split("#", 1)[0]
    if document not in docs:
        return None
    for found, n, raw in indexed_lines(document, docs[document]):
        if found == lid:
            return document, n, raw
    return None


def _classify(line: str, sources: Mapping[int, SourceImpact]) -> list[tuple[str, int, str, str]]:
    """``(citation, chapter, entry, reason)`` for the first citation of ``line`` into each changed source.

    One record per distinct selected chapter: a line citing two corrected chapters is affected for both, so
    each chapter's ruling (and the FR-009 gate over ``lines_of(chapter)``) sees it."""
    found: dict[int, tuple[str, int, str, str]] = {}
    for m in _CITATION.finditer(line):
        chapter, entry = int(m.group(1)), m.group(2).strip()
        src = sources.get(chapter)
        if src is None or chapter in found:
            continue
        key = _slug(entry)
        by_key = {e.entry: e for e in src.entries}
        sid = _SCENE_ID.match(entry)
        hit = by_key.get(sid.group(1) if sid else _SECTION_KEYS.get(key, key))
        if hit is None:
            found[chapter] = (m.group(0), chapter, entry, "whole_chapter")
        elif hit.status in ("changed", "removed"):
            found[chapter] = (m.group(0), chapter, entry, hit.status)
    return [found[c] for c in sorted(found)]


def _scan_document(document: str, data: bytes, sources, origin: str, skip: set[bytes] | None = None):
    for lid, n, raw in indexed_lines(document, data):
        if skip is not None and raw.rstrip(b"\r\n") in skip:
            continue
        text = raw.decode("utf-8", "replace")
        for citation, chapter, entry, reason in _classify(text, sources):
            yield AffectedLine(line_id=lid, document=document, line_no=n,
                               line_sha256=_sha(raw.rstrip(b"\r\n")), citation=citation, chapter=chapter,
                               entry=entry, reason=reason, origin=origin)


# --------------------------------------------------------------------------- annotations, members, consumers

def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)


def _annotations(generation_dir: Path, manifest: GenerationManifest,
                 changes: Sequence[SourceChange]) -> list[AffectedAnnotation]:
    """Retained claim annotations whose ``source_sha256`` is a selected OLD digest and whose span meets a change."""
    by_old = {_sha(c.old): c for c in changes}
    regions = {_sha(c.old): changed_old_regions(c.old, c.new) for c in changes}
    found: dict[str, AffectedAnnotation] = {}
    for record in manifest.retained_records:
        try:
            payload = json.loads((generation_dir / record.retained_path).read_bytes())
        except (OSError, ValueError):
            continue
        for node in _walk(payload):
            digest = node.get("source_sha256")
            if digest not in by_old:
                continue
            s, e = node.get("start_byte"), node.get("end_byte")
            span = (s, e) if isinstance(s, int) and isinstance(e, int) else None
            if span is not None and not any(s < r1 and r0 < e for r0, r1 in regions[digest]):
                continue
            aid = str(node.get("occurrence_id") or node.get("annotation_id")
                      or _sha(json.dumps(node, sort_keys=True, default=str).encode("utf-8"))[:16])
            found[aid] = AffectedAnnotation(annotation_id=aid, source_sha256=digest, span=span,
                                            chapter=by_old[digest].chapter)
    return [found[k] for k in sorted(found)]


def _cited_chapters(data: bytes) -> set[int]:
    return {int(m.group(1)) for m in _CITATION.finditer(data.decode("utf-8", "replace"))}


def _unknown_members(root: Path, manifest: GenerationManifest, selected: set[int]) -> list[UnknownMember]:
    published = root / manifest.published_path
    out = []
    for item in sorted(manifest.members, key=lambda m: m.path):
        if item.path != TIMELINE_NAME and not item.path.startswith("reference/"):
            continue
        try:
            data = (published / item.path).read_bytes()
        except OSError:
            out.append(UnknownMember(member=item.path, reason="no_citations"))
            continue
        cited = _cited_chapters(data)
        if cited & selected:
            out.append(UnknownMember(member=item.path, reason="cites_selected"))
        elif not cited:
            out.append(UnknownMember(member=item.path, reason="no_citations"))
    return out


def _followups(root: Path, selected: set[int]) -> list[FollowUp]:
    out = []
    for path in sorted((root / "docs" / "npcs").glob("*.md")):
        data = path.read_bytes()
        hit = sorted(_cited_chapters(data) & selected)
        if hit:
            out.append(FollowUp(path=path.relative_to(root).as_posix(), sha256=_sha(data), chapters=hit))
    return out


# --------------------------------------------------------------------------- entry point

def compute_impact(root: Path | str, manifest: GenerationManifest, docs: Mapping[str, bytes],
                   changes: Sequence[SourceChange], *,
                   pending_candidates: Mapping[str, bytes] | None = None) -> ImpactSet:
    """The sealed :class:`ImpactSet` of ``changes`` on the baseline ``docs`` (and a pending plan's candidates)."""
    root = Path(root).absolute()
    sources = [SourceImpact(
        chapter=c.chapter, path=c.path, old_sha256=_sha(c.old), new_sha256=_sha(c.new),
        entries=diff_entries(c.old, c.new), diff_ref=f"docs/summaries/delta/custody/objects/{_sha(c.old)}..{_sha(c.new)}")
        for c in sorted(changes, key=lambda c: c.chapter)]
    by_chapter = {s.chapter: s for s in sources}
    lines: list[AffectedLine] = []
    for name in sorted(docs):
        lines.extend(_scan_document(name, docs[name], by_chapter, "baseline"))
    for name in sorted(pending_candidates or {}):
        base = {l.rstrip(b"\r\n") for l in docs.get(name, b"").splitlines(keepends=True)}
        lines.extend(_scan_document(name, pending_candidates[name], by_chapter, "pending", skip=base))
    generation_dir = (root / manifest.published_path).parent
    selected = set(by_chapter)
    return ImpactSet(
        sources=sources, affected_lines=lines,
        affected_annotations=_annotations(generation_dir, manifest, changes),
        unknown_members=_unknown_members(root, manifest, selected),
        followup_consumers=_followups(root, selected)).seal()
