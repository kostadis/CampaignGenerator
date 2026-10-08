"""Check a model's arc-score candidates (spec 034 US4, research R10). No model call.

An arc score is a GM-owned counter attached to a player character, an NPC or a faction. The documents may
only surface *candidate events* that might advance it, never the score itself. A model proposes lines of
the form ``- <event> [cite] — trigger: "<verbatim trigger>"``; code keeps a line only when

* every citation in it is one of the subject's own checked notes' citations (``cite-not-in-notes``);
* its trigger is verbatim in the mechanic file's text (``trigger not verbatim``);
* its event text states no current value, running total or threshold crossed (``states a value``).

Every dropped line is kept with its reasons for ``arc_report.md``. Guarded by
``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pipelines.summary_native import notes, npc_check, schema

CITE_NOT_IN_NOTES = "cite-not-in-notes"
TRIGGER_NOT_VERBATIM = "trigger not verbatim"
STATES_A_VALUE = "states a value"

#: A value, a running total or a threshold crossed (research R10). Applied to the event text only, with its
#: citations removed: the trigger is the GM's own words from the mechanic file, which may well say "score".
VALUE_RE = re.compile(
    r"\b(score|total|value|points?)\b[^.]{0,30}\d|\bnow (?:at )?\d|\bthreshold\b[^.]{0,30}(?:reached|crossed|met)",
    re.I,
)
#: ``- <event> [cite] — trigger: "<trigger>"``. The dash may be an em dash, an en dash or hyphens.
_LINE_RE = re.compile(r"^-\s+(?P<event>.*?)\s*[—–-]+\s*trigger:\s*[\"“](?P<trigger>.*)[\"”]\s*\.?\s*$", re.I)
#: A trigger shorter than this is not evidence of anything: it would be "verbatim" in almost any file.
MIN_TRIGGER_CHARS = 4
#: The model's way of saying nothing in the notes could count (``state.arc.system.md``).
_NONE_RE = re.compile(r"^-\s*\(?none\)?\.?\s*$", re.I)
#: Note tags a planning NPC or faction's notes are drawn from (status rows are added by kind).
ENTITY_TAGS = ("NPC", "FACTION")


@dataclass(frozen=True)
class Drop:
    """A candidate line code dropped, and every reason, in a fixed order."""

    line: str
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class ArcSubject:
    """What the arc step did for one configured subject, as ``arc_report.md`` lists it."""

    name: str
    kind: str  # character | npc | faction
    mechanic: str | None  # the mechanic file as shown (a path), None for a trackless subject
    notes: int = 0  # how many checked notes the call was given
    kept: list = field(default_factory=list)
    drops: list = field(default_factory=list)
    trackless: bool = False


def _parts(text: str) -> set[str]:
    """The normalised ``[ch NNN / target]`` of every citation part in ``text`` (an invalid bracket yields none)."""
    return {f"[ch {c:03d} / {t}]" for _, c, t in notes.cites(text) if c >= 0}


def cites_of(ns: Iterable[notes.Note]) -> set[str]:
    """The citations of a subject's checked notes, normalised: what a candidate may cite."""
    out: set[str] = set()
    for n in ns:
        out |= _parts(n.text)
    return out


def entity_notes(results: Sequence[notes.CheckedChunk], forms: Mapping[str, str], name: str) -> list[notes.Note]:
    """The checked notes about an NPC or faction, by exact canonical subject (registry ``forms``), chapter order.

    World notes tagged ``NPC`` or ``FACTION`` and status rows, each once. A near spelling is not a match.
    """

    def canon(s: str) -> str:
        return forms.get(s.strip().casefold(), s.strip())

    want = canon(name).casefold()
    seen: set[str] = set()
    found: list[notes.Note] = []
    for r in results:
        for n in r.notes:
            if not n.subject or n.note_id in seen:
                continue
            if (n.kind == "world" and n.tag in ENTITY_TAGS) or n.kind == "status_row":
                if canon(n.subject).casefold() == want:
                    seen.add(n.note_id)
                    found.append(n)
    return sorted(found, key=lambda n: n.first_chapter)  # stable: extraction order within a chapter


def check_candidates(text: str, subject_cites: Iterable[str], mechanic_text: str) -> tuple[list[str], list[Drop]]:
    """``(kept, drops)`` for a model's candidate lines.

    ``subject_cites`` are the citations of the subject's checked notes (any bracket form; they are
    normalised here). Blank lines and the model's ``- (none)`` are neither kept nor dropped; any other line
    that is not a well-formed candidate is a drop (``trigger not verbatim``: it names no trigger to verify).
    """
    allowed: set[str] = set()
    for c in subject_cites:
        allowed |= _parts(c)
    kept: list[str] = []
    drops: list[Drop] = []
    for raw in (text or "").splitlines():
        ln = raw.strip()
        if not ln or _NONE_RE.match(ln):
            continue
        m = _LINE_RE.match(ln) if ln.startswith("-") else None
        event = m.group("event") if m else ln.lstrip("- ").strip()
        trigger = m.group("trigger").strip() if m else None
        reasons: list[str] = []
        cited = _parts(event)
        bad_brackets = [b for b, c, _ in notes.cites(event) if c < 0]
        if not cited or bad_brackets or not cited <= allowed:
            reasons.append(CITE_NOT_IN_NOTES)
        if not trigger or len(trigger) < MIN_TRIGGER_CHARS or npc_check._contains(mechanic_text or "", trigger) is None:
            reasons.append(TRIGGER_NOT_VERBATIM)
        if VALUE_RE.search(schema.STATE_CITE_RE.sub("", event)):
            reasons.append(STATES_A_VALUE)
        if reasons:
            drops.append(Drop(ln, tuple(reasons)))
        else:
            kept.append(ln)
    return kept, drops


def candidate_cell(kept: Sequence[str]) -> list[str]:
    """Kept lines as they read in a table cell: the bullet marker dropped."""
    return [k[1:].strip() if k.startswith("-") else k for k in kept]


def arc_report_md(subjects: Sequence[ArcSubject]) -> str:
    """``arc_report.md``: for every configured subject, what the arc step kept and dropped, and why."""
    out = [
        "# Arc-score candidates", "",
        "A model listed events that might advance each arc score; code kept a line only if it cites one of that "
        "subject's own checked notes, quotes its trigger verbatim from the mechanic file and states no value, "
        "total or threshold. The GM owns every score.", "",
    ]
    for s in subjects:
        out += [f"## {s.name}", ""]
        if s.trackless:
            out += [f"{s.kind.capitalize()}, trackless (no arc score by design): no call.", ""]
            continue
        out += [f"Mechanic file: `{s.mechanic}`. {s.notes} checked notes given.", ""]
        if not s.notes:
            out += [f"There are no checked notes about {s.name} in this range: no call.", ""]
            continue
        if s.kept:
            out += [f"Kept ({len(s.kept)}):", "", *s.kept, ""]
        else:
            out += ["No candidate survived the check.", ""]
        if s.drops:
            out += [f"Dropped ({len(s.drops)}):", "", *(f"- {d.line}  \n  reason: {d.reason}" for d in s.drops), ""]
    return "\n".join(out).rstrip("\n") + "\n"
