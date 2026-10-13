"""Prep passages: what the GM wrote down, sorted into what the NPC knows and what only the GM knows.

Prep is written from the GM's side of the screen. A paragraph may be something
the NPC holds ("Sylvira keeps the key in her sleeve"), or something only the GM
holds (a stage direction, another character's secret, a mechanic). Code cannot
tell them apart, so it cuts the file into **passages** and the GM rules each one:

========  ==============================================  ===========================
ruling    meaning                                         reaches the agent
========  ==============================================  ===========================
``hers``  she knows or believes it, and may act on it      yes
``gm``    anything she must not know (stage directions,    never
          other characters' secrets, mechanics)
========  ==============================================  ===========================

**Passages.** A heading line (``#``..``####``) opens a section. Inside a section
each paragraph, each top-level list item (with its indented continuation), each
blockquote run and each table row (not the header or separator) is one passage.
A horizontal rule is not a passage. :func:`extract` takes either every passage
under one heading (``section``, a heading-text prefix; subsections included) or
only the passages that name the NPC (any form, word-bounded, case-sensitive).

**Identity.** ``pid`` is ``<file stem>:<line>:<sha8 of the text>``. An edited
passage gets a new pid, so a ruling on the old wording goes stale instead of
being silently re-attached to words the GM never ruled on
(:func:`load_rulings` refuses it).

**The ruling file** (``prep.json``; JSON is valid YAML), version 1::

    {"version": 1, "npc": "Sylvira Savikas",
     "targets": {"061.05": {"source": "reader_interviews.md", "section": "SCENE B",
                            "passages": {"reader_interviews:41:ab12cd34": "hers"}}}}

:func:`sheet` renders the ``hers`` passages only, in file order, under their
nearest heading, with no line numbers and no file names: the agent must not see
the GM's apparatus. It refuses while any passage is unruled.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

VERSION = 1
HERS = "hers"
GM = "gm"
VALUES = (HERS, GM)

_HEADING = re.compile(r"^(#{1,4})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_ITEM = re.compile(r"^([-*]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s{0,3}>")
_ROW = re.compile(r"^\s*\|")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$")


class PrepError(Exception):
    """The prep file or its ruling file cannot be used; the message is user-facing."""


@dataclass(frozen=True)
class Passage:
    pid: str
    file: str
    line: int  # 1-based
    heading: tuple[str, ...]
    text: str


def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _word(form: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(form)}(?!\w)", text) is not None


def _blocks(lines: list[str]):
    """Yield ``(line_no, text, stack)``; ``stack`` is ``((level, heading text), ...)`` above the passage."""
    stack: list[tuple[int, str]] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        h = _HEADING.match(line)
        if h:
            level = len(h.group(1))
            stack = [s for s in stack if s[0] < level] + [(level, h.group(2))]
            i += 1
            continue
        if _RULE.match(line):
            i += 1
            continue
        start = i
        if _ROW.match(line):
            j = i
            while j < n and _ROW.match(lines[j]):
                j += 1
            rows = list(range(i, j))
            if len(rows) > 1 and _SEPARATOR.match(lines[rows[1]]):
                rows = rows[2:]  # the first row is the header
            for r in rows:
                if not _SEPARATOR.match(lines[r]):
                    yield r + 1, lines[r].strip(), tuple(stack)
            i = j
            continue
        if _QUOTE.match(line):
            j = i
            while j < n and _QUOTE.match(lines[j]):
                j += 1
            yield start + 1, "\n".join(x.strip() for x in lines[i:j]), tuple(stack)
            i = j
            continue
        if _ITEM.match(line):
            j = i + 1
            while j < n:
                nxt = lines[j]
                if not nxt.strip():
                    k = j
                    while k < n and not lines[k].strip():
                        k += 1
                    if k < n and lines[k][:1] in (" ", "\t"):
                        j = k + 1
                        continue
                    break
                if _HEADING.match(nxt) or _ITEM.match(nxt) or _RULE.match(nxt) or _QUOTE.match(nxt) or _ROW.match(nxt):
                    break
                j += 1
            yield start + 1, "\n".join(x.rstrip() for x in lines[i:j]).strip(), tuple(stack)
            i = j
            continue
        j = i + 1
        while j < n and lines[j].strip() and not (
                _HEADING.match(lines[j]) or _RULE.match(lines[j]) or _ITEM.match(lines[j])
                or _QUOTE.match(lines[j]) or _ROW.match(lines[j])):
            j += 1
        yield start + 1, "\n".join(x.strip() for x in lines[i:j]), tuple(stack)
        i = j


def extract(text: str, forms, section: str | None = None, *, file: str = "prep.md") -> list[Passage]:
    """The prep passages for one target, in file order.

    With ``section`` (a heading-text prefix), every passage under a matching
    heading, subsections included. Without it, only the passages that name the
    NPC by one of ``forms``.
    """
    stem = Path(file).stem
    out: list[Passage] = []
    matched = False
    for line, body, stack in _blocks(text.splitlines()):
        if section:
            if not any(t.startswith(section) for _, t in stack):
                continue
            matched = True
        elif not any(_word(f, body) for f in forms):
            continue
        out.append(Passage(f"{stem}:{line}:{_sha8(body)}", Path(file).name, line,
                           tuple(t for _, t in stack), body))
    if section and not matched:
        # An empty section is a heading with nothing under it; a missing one is a typo.
        if not any(t.startswith(section) for t in _heading_texts(text)):
            raise PrepError(f"{file}: no heading starts with {section!r}")
    return out


def _heading_texts(text: str) -> list[str]:
    return [m.group(2) for m in (_HEADING.match(x) for x in text.splitlines()) if m]


def load_rulings(path: Path, npc: str, target: str, passages: list[Passage]) -> dict[str, str]:
    """The GM's rulings for ``target``: ``{pid: "hers" | "gm"}``.

    A target the file does not mention has no rulings yet. Refuses a different
    NPC, an unknown version or key, a value other than hers/gm, and any pid that
    is not in the current extraction (the prep file changed since it was ruled).
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise PrepError(f"{path}: cannot read ({e.strerror})") from None
    except yaml.YAMLError as e:
        raise PrepError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(raw, dict) or set(raw) - {"version", "npc", "targets"}:
        raise PrepError(f"{path}: expected a mapping with 'version', 'npc' and 'targets'")
    if raw.get("version") != VERSION:
        raise PrepError(f"{path}: version must be {VERSION}, got {raw.get('version')!r}")
    if raw.get("npc") != npc:
        raise PrepError(f"{path}: rulings are for {raw.get('npc')!r}, not {npc!r}")
    targets = raw.get("targets") or {}
    if not isinstance(targets, dict):
        raise PrepError(f"{path}: 'targets' must be a mapping of target -> rulings")
    for t, block in targets.items():
        if not isinstance(block, dict) or set(block) - {"source", "section", "passages"}:
            raise PrepError(f"{path}: target {t!r} must be a mapping with 'source', 'section', 'passages'")
    block = targets.get(target) or {}
    ruled = block.get("passages") or {}
    if not isinstance(ruled, dict):
        raise PrepError(f"{path}: target {target!r} passages must be a mapping of pid -> hers|gm")
    known = {p.pid for p in passages}
    bad = [f"{pid}: {v!r}" for pid, v in ruled.items() if v not in VALUES]
    if bad:
        raise PrepError(f"{path}: {target}: a ruling must be 'hers' or 'gm' ({'; '.join(bad)})")
    stale = [pid for pid in ruled if pid not in known]
    if stale:
        raise PrepError(
            f"{path}: {target}: the prep file changed since it was ruled; re-rule these "
            f"{len(stale)} passage(s): {', '.join(stale)}"
        )
    return {str(pid): str(v) for pid, v in ruled.items()}


def unruled(passages: list[Passage], rulings: dict[str, str]) -> list[str]:
    return [p.pid for p in passages if p.pid not in rulings]


def sheet(passages: list[Passage], rulings: dict[str, str], *, require_complete: bool = True) -> str:
    """Markdown of the passages ruled ``hers``, in file order, under their nearest heading.

    No line numbers, no file names, no ``gm`` or unruled passage.
    """
    if require_complete:
        missing = unruled(passages, rulings)
        if missing:
            raise PrepError(f"{len(missing)} passage(s) are not ruled yet: {', '.join(missing)}")
    parts: list[str] = []
    last: tuple[str, ...] | None = None
    for p in passages:
        if rulings.get(p.pid) != HERS:
            continue
        near = p.heading[-1] if p.heading else ""
        if p.heading != last:
            if near:
                parts.append(f"### {near}")
            last = p.heading
        parts.append(p.text)
    return "\n\n".join(parts) + ("\n" if parts else "")
