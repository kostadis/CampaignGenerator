"""Character-sheet identity parsing — the ``## Identity`` block and frontmatter.

These parsers were born in ``pipelines/content_ingest/sheet_frontmatter.py``
(issue #265) and moved down here for feature 008, which has to read the class
and level off a sheet it is about to displace. ``campaignlib`` cannot import
``pipelines`` (``tests/test_layering.py`` enforces the arrow), so the parser
moves rather than being duplicated — two parsers for one format is the exact
drift that guard was written to prevent. ``sheet_frontmatter`` imports every
name back from here and its behaviour is unchanged.

**Frontmatter is not guaranteed.** Every sheet in every campaign predates
``dnd_sheet`` emitting it: all four live Phandalin sheets, and all four the GM
archived by hand under ``old/level/5/``, begin at ``# Name`` with no ``---``
block. So the ``## Identity`` block is the only universally available source
and :func:`read_class_level` falls back to it rather than requiring the
machine channel.

Deterministic and zero-token: a regex pass over text already on disk, no API
call. See ``tests/test_retrieve_render_isolation.py``.
"""

from __future__ import annotations

import re

from campaignlib.textproc import split_frontmatter

# The '## Identity' keys dnd_sheet.py's SYSTEM_PROMPT specifies (D1(a) added
# Subclass). Anything else found in the block is reported as unrecognised,
# never silently dropped.
_KNOWN_IDENTITY_KEYS = {
    "class & level", "subclass", "species", "background",
    "player", "alignment", "age / gender / size",
}

_H1_RE = re.compile(r'^#\s+(.+?)\s*$', re.MULTILINE)
_IDENTITY_HEADING_RE = re.compile(r'^##\s+Identity\s*$', re.MULTILINE)
_NEXT_HEADING_RE = re.compile(r'^#{1,2}[^#]', re.MULTILINE)
_FIELD_RE = re.compile(r'^-\s+\*\*([^*:]+):\*\*\s*(.*)$')

#: A class-and-level phrase ends in the level: "Monk 8", "Druid 5".
_LEVEL_RE = re.compile(r'^(?P<class_>.*\S)\s+(?P<level>\d+)$')

#: What separates two class-and-level segments in a multiclass phrase —
#: "Human Fighter 9 / Bard 2" is a real Hillsfar value. Every segment must
#: carry its own level; :func:`parse_level` adds them up.
_MULTICLASS_SPLIT_RE = re.compile(r'\s*[/,;]\s*|\s+\band\b\s+')


class SheetParseError(Exception):
    """No ``## Identity`` block found — clean refusal, no write."""


class AmbiguousLevelError(Exception):
    """The sheet states no level the archive can be keyed by.

    Raised for a missing or non-numeric class-and-level phrase, and for a
    multiclass phrase in which any one segment carries no level —
    ``Fighter 9 / Bard`` has a total only if you guess the missing half.

    A multiclass phrase whose segments *all* carry a level is not ambiguous;
    see :func:`parse_level`.
    """


def identity_block_span(text: str) -> tuple[int, int] | None:
    """``(start, end)`` of the ``## Identity`` block's body, or ``None``.

    Offsets rather than the substring, so a caller rewriting one field inside
    the block can splice its replacement back without re-finding it — and
    without a stray ``- **Player:**`` elsewhere in the document being in scope.
    """
    m = _IDENTITY_HEADING_RE.search(text)
    if not m:
        return None
    start = m.end()
    nxt = _NEXT_HEADING_RE.search(text[start:])
    return start, (start + nxt.start()) if nxt else len(text)


def _find_identity_block(text: str) -> str:
    span = identity_block_span(text)
    if span is None:
        raise SheetParseError("no '## Identity' section found")
    return text[span[0]:span[1]]


def parse_identity_fields(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the ``## Identity`` block into ``({lower_key: value}, [unrecognised keys])``.

    Raises :class:`SheetParseError` when there is no ``## Identity`` heading
    at all. Unrecognised keys are collected (original case preserved) rather
    than dropped, per D5.
    """
    block = _find_identity_block(text)
    fields: dict[str, str] = {}
    unrecognised: list[str] = []
    for line in block.splitlines():
        m = _FIELD_RE.match(line.strip())
        if not m:
            continue
        key = m.group(1).strip()
        value = m.group(2).strip()
        if key.lower() not in _KNOWN_IDENTITY_KEYS:
            unrecognised.append(key)
            continue
        fields[key.lower()] = value
    return fields, unrecognised


def sheet_name(text: str) -> str | None:
    """The character name from the sheet's first ``# `` (H1) heading."""
    m = _H1_RE.search(text)
    return m.group(1).strip() if m else None


def read_class_level(text: str) -> str | None:
    """The sheet's class-and-level phrase, or ``None`` if it states none.

    Frontmatter ``class_level`` wins when present — it is the machine channel
    and #293 landed it on 19 sheets — falling back to the ``## Identity``
    block's ``**Class & Level:**`` value, which is all the older sheets have.
    A sheet with neither (or with an empty value in both) yields ``None``;
    turning that into a refusal is the caller's decision, not the parser's.
    """
    frontmatter, _body = split_frontmatter(text)
    fm_value = frontmatter.get("class_level")
    if isinstance(fm_value, str) and fm_value.strip():
        return fm_value.strip()

    try:
        fields, _unrecognised = parse_identity_fields(text)
    except SheetParseError:
        return None
    value = fields.get("class & level", "").strip()
    return value or None


def read_player(text: str) -> str | None:
    """The player name the sheet currently states, or ``None``.

    Same precedence as :func:`read_class_level`. Used only to *report* what a
    conversion replaced — the roster is the authority for this field, and a
    D&D Beyond export stamps the downloader's name here, so this value is never
    carried forward (FR-009).
    """
    frontmatter, _body = split_frontmatter(text)
    fm_value = frontmatter.get("player")
    if isinstance(fm_value, str) and fm_value.strip():
        return fm_value.strip()

    try:
        fields, _unrecognised = parse_identity_fields(text)
    except SheetParseError:
        return None
    return fields.get("player", "").strip() or None


def parse_level(phrase: str | None) -> int:
    """The character level a class-and-level phrase states.

    ``"Monk 8"`` → ``8``. A multiclass phrase is the sum of its segments:
    ``"Fighter 9 / Bard 2"`` → ``11``. That reverses D4, which refused here on
    the grounds that picking 11 invents precision the source lacks. It does
    not: 5e *defines* a character's level as the total of their class levels,
    so 11 is read off the sheet by the game's own rule, and the single-class
    case is simply the one-segment case of it. Keying the archive on the total
    also makes ``old/level/<N>/`` mean one thing for every character rather
    than two.

    First-wins and last-wins remain refusals — those really would be a pick.
    So does a segment carrying no level of its own: ``"Fighter 9 / Bard"``
    states no total, and :class:`AmbiguousLevelError` says which segment lost
    it rather than quietly summing the readable half.
    """
    if phrase is None or not phrase.strip():
        raise AmbiguousLevelError("no class & level recorded")

    text = phrase.strip()
    segments = [s.strip() for s in _MULTICLASS_SPLIT_RE.split(text) if s.strip()]
    if not segments:
        raise AmbiguousLevelError(f"no class & level found in {phrase!r}")

    total = 0
    for segment in segments:
        m = _LEVEL_RE.match(segment)
        if not m:
            where = f"{segment!r} in {phrase!r}" if len(segments) > 1 else repr(phrase)
            raise AmbiguousLevelError(f"no level found in {where}")
        total += int(m.group("level"))
    return total
