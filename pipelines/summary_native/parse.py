"""Deterministic parser for a structured session summary.

``parse_file`` never raises on *content* problems — a missing title, a bad
scene id and a wrong prefix are all facts it records for ``validate`` to turn
into findings, so one run can report every problem in the directory (FR-005a).
It raises only when the file cannot be read (``OSError``, or undecodable
bytes), because there is nothing to report on.

Text is kept exactly as written: section and entry bodies are the verbatim
lines between headings, with ``\\n`` line endings preserved. Line numbers are
1-based. Fenced code blocks are skipped when looking for headings, so a ``##``
inside a fence is not a section.

No model call, and no import from ``campaignlib.api`` (guarded by
``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from pipelines.summary_native import schema

_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")


@dataclass(frozen=True)
class Entry:
    """A ``###`` entry: heading text, exact body, 1-based line of the heading."""

    heading: str
    body: str
    line: int


@dataclass(frozen=True)
class Section:
    """An ``##`` section: its name, exact body, and its ``###`` entries."""

    name: str
    body: str
    entries: tuple[Entry, ...]
    line: int = 0


@dataclass(frozen=True)
class Scene:
    """An entry under ``## Scenes``.

    ``source_scene_id`` is the declared ``NNN.SS`` kept verbatim, or ``None``
    when the heading does not start with one (``validate`` reports it).
    ``heading`` is the raw H3 text either way.
    """

    source_scene_id: str | None
    title: str
    synopsis: str
    body: str
    line: int
    heading: str = ""


@dataclass(frozen=True)
class EntityEntry:
    """An observation in an entity section (NPCs, Locations, ...).

    ``source_scene_id`` is ``None`` for appendix entries — the only shape the
    current format has. The field exists so a format that nests entities in a
    scene is not silently flattened (research R4); no scene is ever inferred.
    """

    category: str
    heading: str
    body: str
    line: int
    source_scene_id: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    path: str  # POSIX, relative to the campaign root
    prefix_chapter: int | None  # from the filename; None = no numeric prefix
    title_chapter: int | None  # from `# Chapter N`; None = missing
    title_line: int | None
    date: str | None
    sections: tuple[Section, ...]  # H2s in file order
    scenes: tuple[Scene, ...]
    entities: tuple[EntityEntry, ...]

    def section(self, name: str) -> Section | None:
        for s in self.sections:
            if s.name == name:
                return s
        return None


def _relpath(path: Path, campaign_root: Path) -> str:
    rel = os.path.relpath(Path(path).resolve(), Path(campaign_root).resolve())
    return Path(rel).as_posix()


def split_lines(text: str) -> list[str]:
    """Split on ``\\n`` only, keeping the terminator (round-trips with ''.join)."""
    return _LINE_RE.findall(text)


def _heading_positions(lines: list[str], pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """``(index, text)`` of lines matching ``pattern`` outside fenced code."""
    found: list[tuple[int, str]] = []
    in_fence = False
    for i, raw in enumerate(lines):
        stripped = raw.rstrip("\n").rstrip("\r")
        if stripped.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = pattern.match(stripped)
        if m:
            found.append((i, m.group(1)))
    return found


def _all_heading_indexes(lines: list[str]) -> list[tuple[int, int, str]]:
    """``(index, level, text)`` for every H2/H3 outside fences, in order."""
    out: list[tuple[int, int, str]] = []
    for i, text in _heading_positions(lines, schema.H2_RE):
        out.append((i, 2, text))
    for i, text in _heading_positions(lines, schema.H3_RE):
        out.append((i, 3, text))
    return sorted(out)


def synopsis_of(body: str) -> str:
    """``####`` lines joined with ' / '; else the first non-heading paragraph."""
    lines = body.split("\n")
    h4 = []
    for ln in lines:
        m = schema.H4_RE.match(ln.rstrip("\r"))
        if m:
            h4.append(m.group(1))
    if h4:
        return " / ".join(h4)
    para: list[str] = []
    for ln in lines:
        if ln.strip() == "":
            if para:
                break
            continue
        if ln.lstrip().startswith("#"):
            if para:
                break
            continue
        para.append(ln.rstrip("\r"))
    return "\n".join(para)


def _make_scene(entry: Entry) -> Scene:
    m = schema.SCENE_ID_RE.match(entry.heading)
    if m:
        scene_id, title = f"{m.group(1)}.{m.group(2)}", m.group(3)
    else:
        scene_id, title = None, entry.heading
    return Scene(
        source_scene_id=scene_id,
        title=title,
        synopsis=synopsis_of(entry.body),
        body=entry.body,
        line=entry.line,
        heading=entry.heading,
    )


def _build_sections(lines: list[str]) -> tuple[Section, ...]:
    marks = _all_heading_indexes(lines)
    sections: list[Section] = []
    i = 0
    while i < len(marks):
        idx, level, text = marks[i]
        if level != 2:
            i += 1  # H3 before any H2: not part of a section
            continue
        j = i + 1
        entries: list[Entry] = []
        end = len(lines)
        while j < len(marks) and marks[j][1] == 3:
            j += 1
        # section ends at the next H2 (marks[j]) or end of file
        if j < len(marks):
            end = marks[j][0]
        h3s = [m for m in marks[i + 1 : j]]
        for k, (h_idx, _, h_text) in enumerate(h3s):
            h_end = h3s[k + 1][0] if k + 1 < len(h3s) else end
            entries.append(
                Entry(heading=h_text, body="".join(lines[h_idx + 1 : h_end]), line=h_idx + 1)
            )
        sections.append(
            Section(
                name=text,
                body="".join(lines[idx + 1 : end]),
                entries=tuple(entries),
                line=idx + 1,
            )
        )
        i = j
    return tuple(sections)


def parse_text(text: str, path: str) -> ParsedFile:
    """Parse already-read text. ``path`` is stored as given (campaign-relative)."""
    lines = split_lines(text)
    name = path.rsplit("/", 1)[-1]
    pm = schema.PREFIX_RE.match(name)
    prefix = int(pm.group(1)) if pm else None

    title_chapter: int | None = None
    title_line: int | None = None
    in_fence = False
    for i, raw in enumerate(lines):
        stripped = raw.rstrip("\n").rstrip("\r")
        if stripped.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        tm = schema.TITLE_RE.match(stripped)
        if tm:
            title_chapter, title_line = int(tm.group(1)), i + 1
            break

    sections = _build_sections(lines)
    first_h2 = sections[0].line - 1 if sections else len(lines)
    date = None
    for raw in lines[:first_h2]:
        dm = schema.DATE_RE.match(raw.rstrip("\n").rstrip("\r"))
        if dm:
            date = dm.group(1)
            break

    scenes: list[Scene] = []
    entities: list[EntityEntry] = []
    for sec in sections:
        if sec.name == schema.SCENES:
            scenes.extend(_make_scene(e) for e in sec.entries)
        elif sec.name in schema.ENTITY_CATEGORIES:
            cat = schema.ENTITY_CATEGORIES[sec.name]
            entities.extend(
                EntityEntry(category=cat, heading=e.heading, body=e.body, line=e.line)
                for e in sec.entries
            )
    return ParsedFile(
        path=path,
        prefix_chapter=prefix,
        title_chapter=title_chapter,
        title_line=title_line,
        date=date,
        sections=sections,
        scenes=tuple(scenes),
        entities=tuple(entities),
    )


def parse_file(path: Path, campaign_root: Path) -> ParsedFile:
    """Read and parse one summary. Raises only if the file cannot be read."""
    text = Path(path).read_bytes().decode("utf-8")
    return parse_text(text, _relpath(path, campaign_root))
