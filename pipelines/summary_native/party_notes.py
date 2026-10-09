"""Party notes: who a note is about, what level a character is, and the files that keep every note (spec 034 US1).

Deterministic and model-free, like ``state_sections`` (guarded by ``tests/test_summary_native_no_llm.py``).
A model never decides which character a note belongs to, which level row is the latest, or what a sheet
says the level is: those are identity, ordering and attribution decisions (Principle II). It only writes
prose inside what this module hands it.

**Attribution** (research R2). A party note's subject is read verbatim from its ``**Subject**`` and
resolved by exact casefolded equality through the registry's ``forms`` and the player roster; nothing is
matched by similarity (``Dazz`` is not ``Daz``). The whole subject is resolved first and split on
``,`` / ``&`` / ``and`` only when the whole resolves to nothing, so a registry entity called "Topsy and
Turvy" stays one companion; a split subject is attributed only if *every* piece resolves.

**Level** (research R3). The latest ``[LEVEL]`` row for the character or for ``Party``, a character row
winning a tie; else the sheet's figure, shown as the sheet's, parsed only from an explicit line.

No timestamps, no absolute paths: every function is a pure function of its inputs, so a rebuild from the
same notes, registry, roster and sheets is byte-identical (FR-020).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pipelines.summary_native import notes, schema, state_sections

#: Attribution scopes (data-model "Party attribution").
CHARACTER, PARTY, COMPANION, UNATTRIBUTED = "character", "party", "companion", "unattributed"

#: Code line for a character the range records nothing about (US1 scenario 4).
NOTHING_RECORDED = "The summaries in this range record nothing for {name}."
#: Code line for a part with no party-wide or character notes at all.
NOTHING_ABOUT_PARTY = "The summaries in this range record nothing about the party."
#: The pointer a character section ends with.
FULL_NOTES_POINTER = "_Full notes: reference/party.md_"

_SPLIT_RE = re.compile(r"\s*(?:,|&)\s*|\s+and\s+", re.I)
_LEADING_AND_RE = re.compile(r"^and\s+", re.I)


# ── Attribution ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Attribution:
    """Where one distinct checked party note belongs. ``note`` is the note itself, verbatim."""

    note: notes.Note
    scope: str  # character | party | companion | unattributed
    #: Player-character names as configured, when ``scope`` is ``character`` (several for a joint subject).
    characters: tuple[str, ...] = ()
    #: Registry names of the non-player entities the subject names (``companion``; also a mixed subject).
    companions: tuple[str, ...] = ()
    #: Why the note is unattributed: the piece that resolved to nothing, or "claimed by more than one entity".
    reason: str = ""

    @property
    def note_id(self) -> str:
        return self.note.note_id

    @property
    def is_level(self) -> bool:
        return self.note.tag == schema.LEVEL_TAG


def _pc_lookup(identity: state_sections.Identity, party_names: Sequence[str]) -> dict[str, str]:
    """``casefolded form -> the player character's name``: configured names first, so they win.

    A form is the character's configured name, the registry's canonical name for it, or (for a
    character only ``players.yaml`` lists) that name; an alias reaches it through ``forms``.
    """
    forms, pcs, _ = identity
    out: dict[str, str] = {}

    def add(name: str) -> None:
        for key in (name.casefold(), forms.get(name.casefold(), name).casefold()):
            out.setdefault(key, name)

    for name in party_names:
        add(name)
    for name in sorted(pcs):
        add(name)
    return out


def _resolve(piece: str, lookup: Mapping[str, str], identity: state_sections.Identity) -> tuple[str, str]:
    """``(kind, value)``: ``pc`` (the name), ``companion`` (registry name), ``ambiguous`` (names) or ``unknown``."""
    forms, _, ambiguous = identity
    key = piece.strip().casefold()
    if key in lookup:
        return "pc", lookup[key]
    if key in forms:
        canon = forms[key]
        return ("pc", lookup[canon.casefold()]) if canon.casefold() in lookup else ("companion", canon)
    if key in ambiguous:
        return "ambiguous", ", ".join(ambiguous[key])
    return "unknown", piece.strip()


def _unresolved_reason(kind: str, names: str, piece: str, subject: str) -> str:
    """Why ``piece`` (the whole ``subject``, or one part of a split one) resolved to nothing."""
    of = "" if piece == subject else f" (part of {subject!r})"
    if kind == "ambiguous":
        return f"{piece!r}{of}: claimed by more than one entity ({names})"
    return f"{piece!r}{of} is not a player character or a registry entity"


def _attribute_subject(subject: str, lookup: Mapping[str, str], identity: state_sections.Identity) -> tuple:
    """``(scope, characters, companions, reason)`` for one subject."""
    if subject.strip().casefold() == schema.PARTY_SUBJECT.casefold():
        return PARTY, (), (), ""
    kind, value = _resolve(subject, lookup, identity)
    if kind == "pc":
        return CHARACTER, (value,), (), ""
    if kind == "companion":
        return COMPANION, (), (value,), ""
    if kind == "ambiguous":
        return UNATTRIBUTED, (), (), _unresolved_reason(kind, value, subject, subject)
    # Nothing matched the whole subject: only now split it, and every piece must resolve.
    pieces = [_LEADING_AND_RE.sub("", p).strip() for p in _SPLIT_RE.split(subject)]
    pieces = [p for p in pieces if p]
    if len(pieces) < 2:
        return UNATTRIBUTED, (), (), _unresolved_reason(kind, value, subject, subject)
    pcs: list[str] = []
    companions: list[str] = []
    for piece in pieces:
        k, v = _resolve(piece, lookup, identity)
        if k == "pc":
            if v not in pcs:
                pcs.append(v)
        elif k == "companion":
            if v not in companions:
                companions.append(v)
        else:
            return UNATTRIBUTED, (), (), _unresolved_reason(k, v, piece, subject)
    if pcs:
        return CHARACTER, tuple(pcs), tuple(companions), ""
    return COMPANION, (), tuple(companions), ""


def attribute(
    results: Sequence[notes.CheckedChunk],
    identity: state_sections.Identity,
    party_names: Sequence[str],
) -> list[Attribution]:
    """One :class:`Attribution` per distinct kept party note, in chapter order.

    ``identity`` is ``state_sections.load_identity``'s ``(forms, pcs, ambiguous)``; ``party_names`` are
    ``party.yaml``'s character names. Player characters are those names plus ``players.yaml``'s ``plays``
    (already in ``pcs``), each mapped through ``forms``. Exact duplicates (same chapter, kind and text)
    are one note; the order is by the first citation's chapter, then extraction order.
    """
    lookup = _pc_lookup(identity, party_names)
    seen: set[str] = set()
    found: list[notes.Note] = []
    for r in results:
        for n in r.notes:
            if n.kind != "party" or n.note_id in seen:
                continue
            seen.add(n.note_id)
            found.append(n)
    out = []
    for n in sorted(found, key=lambda n: n.first_chapter):  # stable: extraction order within a chapter
        scope, characters, companions, reason = _attribute_subject(n.subject or "", lookup, identity)
        out.append(Attribution(n, scope, characters, companions, reason))
    return out


def all_characters(attributions: Sequence[Attribution], party_names: Sequence[str]) -> list[str]:
    """``party_names`` in configured order, then any other player character a note was attributed to (sorted)."""
    extra = sorted({c for a in attributions for c in a.characters if c not in party_names}, key=lambda s: (s.casefold(), s))
    return [*party_names, *extra]


# ── What a prompt may see ───────────────────────────────────────────────────


def character_notes(attributions: Sequence[Attribution], name: str) -> list[notes.Note]:
    """The notes attributed to ``name`` (a joint subject counts for each), level rows left out: code writes the level."""
    return [a.note for a in attributions if a.scope == CHARACTER and name in a.characters and not a.is_level]


def party_wide_notes(attributions: Sequence[Attribution]) -> list[notes.Note]:
    return [a.note for a in attributions if a.scope == PARTY and not a.is_level]


def latest_per_character(attributions: Sequence[Attribution], names: Sequence[str], k: int = 2) -> list[notes.Note]:
    """The latest ``k`` notes of each character, once each, in chapter order."""
    keep: dict[str, notes.Note] = {}
    for name in names:
        for n in character_notes(attributions, name)[-k:]:
            keep[n.note_id] = n
    return sorted(keep.values(), key=lambda n: n.first_chapter)  # stable: dict order is the attribution order


def latest_per_companion(attributions: Sequence[Attribution], k: int = 2) -> list[notes.Note]:
    """The latest ``k`` notes about each companion (a note naming one counts for it, a mixed subject
    included), once each, in chapter order. Companions are named by the registry; nothing is guessed."""
    by_companion: dict[str, list[notes.Note]] = {}
    for a in attributions:
        if a.is_level:
            continue
        for name in a.companions:
            by_companion.setdefault(name, []).append(a.note)
    keep: dict[str, notes.Note] = {}
    for name in sorted(by_companion, key=lambda s: (s.casefold(), s)):
        for n in by_companion[name][-k:]:
            keep[n.note_id] = n
    return sorted(keep.values(), key=lambda n: n.first_chapter)  # stable: attribution order within a chapter


# ── The level line (research R3) ────────────────────────────────────────────

_NO_LEVEL = "Level: not recorded in the summaries (sheet {what})"

#: Explicit lines only. Each captures the level in group 1; nothing is read from prose.
_SHEET_PATTERNS = tuple(re.compile(p, re.I | re.M) for p in (
    # "Level: 8", "**Level:** 8", "- **Level:** 8", "| Level | 8 |"
    r"^[\s>*|-]*\**\s*Level\s*\**\s*[:|]\s*\**\s*(\d{1,2})\b",
    # "Class & Level: Wizard 9" and the front-matter key "class_level: Wizard 9": one class, one number
    r"^[\s>*|-]*\**\s*(?:Class\s*(?:&|and)\s*Level|class_level)\s*\**\s*[:|]\s*\**\s*[A-Za-z][A-Za-z' -]*?\s+(\d{1,2})\s*\**\s*\|?\s*$",
    # a header: "## Level 9"
    r"^#{1,6}\s*Level\s+(\d{1,2})\s*$",
    # a class-level header: "### 9th-level Wizard" (a spell-level header such as "### 1st Level (4 Slots)" never ends
    # in a bare class name, and "3rd Level Spells" is refused below)
    r"^#{1,6}\s*(\d{1,2})(?:st|nd|rd|th)[- ]level\s+(?!(?:spells?|slots?|features?|cantrips?|abilities)\s*$)[A-Za-z][A-Za-z' -]*$",
))


def sheet_level(sheet_text: str | None) -> int | None:
    """The character level a sheet states on an explicit line, or ``None``.

    ``None`` also when the sheet states two different figures: an unreadable sheet is reported as giving
    none rather than guessed at. A spell-slot header ("### 1st Level (4 Slots)") never counts.
    """
    if not sheet_text:
        return None
    found = {int(m.group(1)) for pat in _SHEET_PATTERNS for m in pat.finditer(sheet_text)}
    return next(iter(found)) if len(found) == 1 else None


def cite_of(note: notes.Note) -> str:
    """The note's citation brackets as written, once each, in order."""
    seen: list[str] = []
    for bracket, chapter, _ in notes.cites(note.text):
        if chapter >= 0 and bracket not in seen:
            seen.append(bracket)
    return " ".join(seen)


@dataclass(frozen=True)
class Level:
    """A character's level line and where it came from (for ``party_report.md``)."""

    line: str
    level: int | None
    source: str


def level_for(
    name: str,
    results: Sequence[notes.CheckedChunk],
    attributions: Sequence[Attribution],
    sheet_text: str | None,
) -> Level:
    """The code-built level line of ``name`` and its source.

    The latest ``[LEVEL]`` row about ``name`` or ``Party`` wins, by first chapter; a character row beats
    a party row in the same chapter; of two rows tied on both, the later in extraction order wins.
    Without a row the line says the summaries record none and shows the sheet's figure as the sheet's.
    """
    best: tuple[tuple[int, int, int], Attribution] | None = None
    for i, a in enumerate(attributions):
        if not a.is_level or a.note.level is None:
            continue
        if a.scope == CHARACTER and name in a.characters:
            weight = 1
        elif a.scope == PARTY:
            weight = 0
        else:
            continue
        key = (a.note.first_chapter, weight, i)
        if best is None or key > best[0]:
            best = (key, a)
    if best is not None:
        a = best[1]
        who = "Party" if a.scope == PARTY else (a.note.subject or name)
        return Level(
            f"Level: {a.note.level} {cite_of(a.note)}".rstrip(), a.note.level,
            f"[{schema.LEVEL_TAG}] row for {who}, ch {a.note.first_chapter:03d} {cite_of(a.note)}".rstrip(),
        )
    n = sheet_level(sheet_text)
    if n is None:
        return Level(_NO_LEVEL.format(what="gives none"), None, "no [LEVEL] row; the sheet gives none")
    return Level(_NO_LEVEL.format(what=f"says {n}"), None, f"no [LEVEL] row; the sheet says {n}")


def level_line(
    name: str,
    results: Sequence[notes.CheckedChunk],
    attributions: Sequence[Attribution],
    sheet_text: str | None,
) -> str:
    """:func:`level_for`'s line: ``Level: N [cite]`` or ``Level: not recorded in the summaries (sheet says N)``."""
    return level_for(name, results, attributions, sheet_text).line


# ── reference/party.md and party_report.md ──────────────────────────────────

_GROUP_HEAD = "## {}"
PARTY_GROUP, COMPANIONS_GROUP, UNATTRIBUTED_GROUP = "Party", "Companions", "Unattributed"


def _bullets(ns: Sequence[notes.Note]) -> list[str]:
    return [n.text for n in ns] if ns else [schema.NONE_VERIFIED]


def reference_md(
    results: Sequence[notes.CheckedChunk],
    attributions: Sequence[Attribution],
    party_names: Sequence[str],
) -> str:
    """``reference/party.md``: every checked party note, verbatim, in chapter order within its group.

    Groups: each player character in ``party.yaml`` order (then any other player character a note
    names), ``Party`` (whole-party notes), ``Companions`` (by name) and ``Unattributed``. A joint note
    is kept under each character it names; a character with no notes still has a group.
    """
    groups = all_characters(attributions, party_names)
    lines: list[str] = []
    non_empty = 0
    for name in groups:
        ns = [a.note for a in attributions if a.scope == CHARACTER and name in a.characters]
        non_empty += bool(ns)
        lines += [_GROUP_HEAD.format(name), *_bullets(ns), ""]
    party = [a.note for a in attributions if a.scope == PARTY]
    non_empty += bool(party)
    lines += [_GROUP_HEAD.format(PARTY_GROUP), *_bullets(party), ""]
    comps = sorted({c for a in attributions for c in a.companions}, key=lambda s: (s.casefold(), s))
    non_empty += len(comps)
    lines.append(_GROUP_HEAD.format(COMPANIONS_GROUP))
    if not comps:
        lines.append(schema.NONE_VERIFIED)
    for c in comps:
        lines += ["", f"### {c}", *(a.note.text for a in attributions if c in a.companions)]
    lines.append("")
    un = [a.note for a in attributions if a.scope == UNATTRIBUTED]
    non_empty += bool(un)
    lines += [_GROUP_HEAD.format(UNATTRIBUTED_GROUP), *_bullets(un), ""]
    head = [
        "# Reference: Party", "",
        f"{len(attributions)} checked notes, {non_empty} subjects, chapter order within each. "
        "Built by code from the checked notes; nothing is reworded.", "",
    ]
    return "\n".join(head + lines)


def report_md(
    results: Sequence[notes.CheckedChunk],
    attributions: Sequence[Attribution],
    party_names: Sequence[str],
    levels: Mapping[str, Level],
    *,
    since: int,
    until: int,
    budgets: Mapping[str, Mapping] | None = None,
) -> str:
    """``party_report.md``: what code decided, for the GM to check.

    The unattributed subjects with their text and citation (fix at source or declare them), the
    companions by name, the level source per character, and (when given) each section's word count
    against its budget. ``budgets`` is ``{name: {"budget", "words", "over"}}``.
    """
    by_scope = {s: [a for a in attributions if a.scope == s] for s in (CHARACTER, PARTY, COMPANION, UNATTRIBUTED)}
    lines = [
        "# Party report", "",
        f"ch {since:03d}-{until:03d}. {len(attributions)} checked party notes: {len(by_scope[CHARACTER])} attributed to "
        f"a player character, {len(by_scope[PARTY])} whole-party, {len(by_scope[COMPANION])} companion, "
        f"{len(by_scope[UNATTRIBUTED])} unattributed.", "",
        "## Level source per character", "",
    ]
    for name in party_names:
        lv = levels.get(name)
        lines.append(f"- {name}: " + (f"{lv.line} ({lv.source})" if lv else "no level computed"))
    comps = sorted({c for a in attributions for c in a.companions}, key=lambda s: (s.casefold(), s))
    lines += ["", f"## Companions ({len(comps)})", ""]
    lines += [f"- {c}: {sum(1 for a in attributions if c in a.companions)} notes" for c in comps] or ["- (none)"]
    lines += ["", f"## Unattributed ({len(by_scope[UNATTRIBUTED])}) — declare the subject in players.yaml or the "
              "entity registry, or fix it in the summary", ""]
    lines += [f"- {a.note.text.removeprefix('- ')} — {a.reason}" for a in by_scope[UNATTRIBUTED]] or ["- (none)"]
    others = [c for c in all_characters(attributions, party_names) if c not in party_names]
    if others:
        lines += ["", "## Player characters with notes but no party.yaml entry (no section is written)", ""]
        lines += [f"- {c}" for c in others]
    if budgets:
        lines += ["", "## Budgets", ""]
        lines += [f"- {k}: {v['words']}/{v['budget']} words" + ("  OVER (kept whole, not trimmed)" if v["over"] else "")
                  for k, v in budgets.items()]
    return "\n".join(lines) + "\n"
