"""Summaries -> items: the units a presence ruling is made about.

Reads the published layout (``campaigns-public/<campaign>/summaries/``): a
``## Summary`` prose section, then ``## Scenes`` whose ``###`` headings carry no
``NNN.SS`` id. The private ``docs/summaries/`` copy is the same text after a
refactor that moves each prose paragraph under a scene by a similarity score and
numbers the scenes. Measured on all 80 Out of the Abyss and Obelisk files, scene
*k* of a public file is scene ``NNN.kk`` of the private one, title for title, so
a scene with no declared id gets its id by position and a dossier citation
resolves to it.

The two layouts differ in one way that matters here. In the public file a
scene's text (its ``####`` headline from the GM's recap and its bullets) was
written for that scene, while the prose is chapter-level. In the private file,
which scene a prose paragraph sits under was decided by the refactor's
heuristic: the paragraph is the scene's first text, between its ``###`` heading
and its first ``####`` headline, and it restates the bullets below it. So prose
is its own item, at chapter level, and is never attributed to a scene here: a
scene with a ``####`` headline gives back whatever precedes the first one as
PROSE items, numbered ``NNN.pK`` after the ``## Summary`` paragraphs. A scene
with no ``####`` headline is left as it is.

Item ids:

=========  ===========  ================================================
kind       id           text
=========  ===========  ================================================
scene      ``NNN.SS``   heading, ``####`` headline(s) and bullets
prose      ``NNN.pK``   the K-th paragraph of ``## Summary``, then those
                        placed under scenes (private layout)
moment     ``NNN.mK``   the K-th ``## Memorable Moments`` block (cut as
                        :func:`npc_link.iter_items` cuts them)
entry      ``NNN.eK``   the K-th ``## NPCs`` observation
=========  ===========  ================================================

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipelines.summary_native import npc_link, parse, schema

SCENE = "scene"
PROSE = "prose"
MOMENT = "moment"
ENTRY = "entry"
KINDS = (SCENE, PROSE, MOMENT, ENTRY)

#: The section whose paragraphs are chapter-level prose in the published layout.
SUMMARY_SECTION = "Summary"

#: ``npc`` — the category key ``parse`` gives the ``## NPCs`` section.
NPC_CATEGORY = schema.ENTITY_CATEGORIES["NPCs"]


@dataclass(frozen=True)
class Item:
    item_id: str
    kind: str
    chapter: int
    source_file: str
    line: int  # 1-based line of the item's first line in ``source_file``
    title: str | None  # a scene's title, an entry's heading; None otherwise
    #: ``(file line, text)`` for every line of the item, heading included.
    lines: tuple[tuple[int, str], ...]
    #: file lines of a scene's ``####`` headlines (the GM's recap); empty otherwise.
    headline_lines: tuple[int, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.lines).strip("\n")


@dataclass(frozen=True)
class Chapter:
    chapter: int
    source_file: str
    date: str | None
    items: tuple[Item, ...]
    title: str | None = None  # the file's ``# Chapter N ...`` line, without the ``#``


@dataclass(frozen=True)
class Corpus:
    chapters: tuple[Chapter, ...]
    #: Problems with the directory itself (no numeric prefix, duplicate chapter, ...).
    findings: tuple[str, ...]

    def items(self):
        for ch in self.chapters:
            yield from ch.items


def _strip_nl(line: str) -> str:
    return line.rstrip("\n").rstrip("\r")


def _scene_items(pf: parse.ParsedFile, chapter: int) -> tuple[list[Item], list[list[tuple[int, str]]]]:
    """``(scenes, placed)``: the scene items, and the prose paragraphs found inside them.

    In the private layout a ``## Summary`` paragraph sits under a scene, between
    its ``###`` heading and its first ``####`` headline. That text is the
    chapter's prose, placed by the refactor's heuristic, and it restates the
    scene's bullets: left in the scene, every moment appears twice and the turn
    splitter sees it twice. So for a scene with a ``####`` headline the text
    before the first one leaves the scene and is returned as ``placed`` (runs of
    non-blank lines, with their file lines) for :func:`_placed_prose_items`. A
    scene with no ``####`` headline is unchanged, and so is a public-layout
    scene, whose first line after the heading is its headline.
    """
    out, placed = [], []
    for k, sc in enumerate(pf.scenes, 1):
        sid = sc.source_scene_id or f"{chapter:03d}.{k:02d}"
        body = parse.split_lines(sc.body)
        lines = [(sc.line, f"### {sc.heading}")] + [
            (sc.line + 1 + i, _strip_nl(ln)) for i, ln in enumerate(body)
        ]
        first_headline = next((i for i, (_, t) in enumerate(lines) if i and t.startswith("#### ")), None)
        if first_headline is not None and first_headline > 1:
            placed.extend(_paragraphs(lines[1][0], "\n".join(t for _, t in lines[1:first_headline])))
            lines = lines[:1] + lines[first_headline:]
        while len(lines) > 1 and not lines[-1][1].strip():
            lines.pop()
        out.append(
            Item(
                item_id=sid,
                kind=SCENE,
                chapter=chapter,
                source_file=pf.path,
                line=sc.line,
                title=sc.title,
                lines=tuple(lines),
                headline_lines=tuple(n for n, t in lines if t.startswith("#### ")),
            )
        )
    return out, placed


@dataclass(frozen=True)
class Beat:
    """One authored beat of a scene: its ``####`` headline or a top-level ``- `` bullet.

    Indented sub-bullets, quoted lines and loose lines belong to the beat above
    them, so a beat is never smaller than what the summary wrote as one point.
    """

    beat_id: str  # ``NNN.SS.bKK``
    scene_id: str
    line: int
    lines: tuple[tuple[int, str], ...]

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.lines).strip("\n")


def beats(item: Item) -> tuple[Beat, ...]:
    """A scene's beats in order. Empty for anything that is not a scene."""
    if item.kind != SCENE:
        return ()
    groups: list[list[tuple[int, str]]] = []
    for n, t in item.lines[1:]:  # the ``###`` heading is the scene, not a beat
        starts = t.startswith("#### ") or t.startswith("- ")
        if starts or (not groups and t.strip()):
            groups.append([(n, t)])
        elif groups:
            groups[-1].append((n, t))
    out = []
    for k, g in enumerate(groups, 1):
        while g and not g[-1][1].strip():
            g.pop()
        out.append(Beat(f"{item.item_id}.b{k:02d}", item.item_id, g[0][0], tuple(g)))
    return tuple(out)


def _paragraphs(first_line: int, body: str) -> list[list[tuple[int, str]]]:
    """Runs of non-blank lines; a run that opens with a heading is not prose."""
    paras, cur = [], []
    for i, raw in enumerate(parse.split_lines(body)):
        text = _strip_nl(raw)
        if text.strip():
            cur.append((first_line + i, text))
        elif cur:
            paras.append(cur)
            cur = []
    if cur:
        paras.append(cur)
    return [p for p in paras if not p[0][1].lstrip().startswith("#")]


def _prose_items(pf: parse.ParsedFile, chapter: int,
                 placed: list[list[tuple[int, str]]] | None = None) -> list[Item]:
    """The chapter's prose: ``## Summary`` paragraphs, then (private layout) the placed ones.

    Numbering is ``NNN.pK`` across both, ``## Summary`` first, then the placed
    paragraphs in file order, so an id never depends on which scene held it.
    """
    sec = pf.section(SUMMARY_SECTION)
    paras = _paragraphs(sec.line + 1, sec.body) if sec is not None else []
    return [
        Item(
            item_id=f"{chapter:03d}.p{k:02d}",
            kind=PROSE,
            chapter=chapter,
            source_file=pf.path,
            line=para[0][0],
            title=None,
            lines=tuple(para),
        )
        for k, para in enumerate(paras + list(placed or []), 1)
    ]


def _moment_items(pf: parse.ParsedFile, chapter: int) -> list[Item]:
    moments = [c for c in npc_link.iter_items(pf) if c.kind == "moment"]
    return [
        Item(
            item_id=f"{chapter:03d}.m{k:02d}",
            kind=MOMENT,
            chapter=chapter,
            source_file=pf.path,
            line=c.line,
            title=None,
            lines=c.lines,
        )
        for k, c in enumerate(moments, 1)
    ]


def _entry_items(pf: parse.ParsedFile, chapter: int) -> list[Item]:
    out = []
    for k, e in enumerate((e for e in pf.entities if e.category == NPC_CATEGORY), 1):
        body = parse.split_lines(e.body)
        lines = [(e.line, f"### {e.heading}")] + [
            (e.line + 1 + i, _strip_nl(ln)) for i, ln in enumerate(body)
        ]
        while len(lines) > 1 and not lines[-1][1].strip():
            lines.pop()
        out.append(
            Item(
                item_id=f"{chapter:03d}.e{k:02d}",
                kind=ENTRY,
                chapter=chapter,
                source_file=pf.path,
                line=e.line,
                title=e.heading,
                lines=tuple(lines),
            )
        )
    return out


def parse_chapter(text: str, name: str) -> tuple[Chapter | None, list[str]]:
    """One summary's text -> its chapter, or ``None`` and why."""
    pf = parse.parse_text(text, name)
    if pf.prefix_chapter is None:
        return None, [f"{name}: no numeric chapter prefix; skipped"]
    ch = pf.prefix_chapter
    findings = []
    if pf.title_chapter is not None and pf.title_chapter != ch:
        findings.append(f"{name}: title says chapter {pf.title_chapter}, filename says {ch}")
    declared = [s.source_scene_id for s in pf.scenes]
    if any(declared) and not all(declared):
        findings.append(f"{name}: some scene headings carry an id and some do not")
    scenes, placed = _scene_items(pf, ch)
    items = scenes + _prose_items(pf, ch, placed) + _moment_items(pf, ch) + _entry_items(pf, ch)
    title = pf.first_h1[1:].strip() if pf.first_h1 else None
    return Chapter(chapter=ch, source_file=name, date=pf.date, items=tuple(items), title=title), findings


def load_corpus(summaries_dir: Path) -> Corpus:
    """Every top-level ``*.md`` in ``summaries_dir``, in chapter order."""
    chapters: dict[int, Chapter] = {}
    findings: list[str] = []
    for p in sorted(Path(summaries_dir).glob("*.md")):
        ch, fs = parse_chapter(p.read_bytes().decode("utf-8-sig"), p.name)
        findings.extend(fs)
        if ch is None:
            continue
        if ch.chapter in chapters:
            findings.append(
                f"{p.name}: chapter {ch.chapter} already read from {chapters[ch.chapter].source_file}; skipped"
            )
            continue
        chapters[ch.chapter] = ch
    return Corpus(chapters=tuple(chapters[k] for k in sorted(chapters)), findings=tuple(findings))
