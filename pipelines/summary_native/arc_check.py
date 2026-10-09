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

# --- "states a value" (research R10, tuned in #526) -------------------------------------------------------
#
# A candidate must never put a current value, a running total or a threshold crossed in front of the GM as if
# it were decided. A miss does exactly that; a false positive only costs one candidate, which ``arc_report.md``
# lists with its reason. So every rule below errs towards dropping. Applied to the event text only, with its
# citations removed: the trigger is the GM's own words from the mechanic file, which may well say "score".
# ``tests/test_summary_native_arc.py`` carries the table of verdicts; ``specs/034-chunked-party-planning/
# arc_value_check.md`` records it.

#: Units a bare number is almost always counting (money, distance, time, hit points), never a score.
_UNITS = (
    r"(?:gp|sp|cp|pp|ep|gold|silver|copper|platinum|coins?|hp|feet|foot|ft|miles?|yards?|inch(?:es)?|lbs?|"
    r"pounds?|bells?|o'?clock|a\.?m\.?|p\.?m\.?|seconds?|minutes?|hours?|days?|nights?|weeks?|months?|years?|"
    r"rounds?|turns?)"
)
#: A street suffix: what makes "3 Waterdeep Lane" an address and "3 Obsession" a value.
_STREET = r"(?:Lane|Street|St|Road|Rd|Way|Avenue|Ave|Alley|Row|Square|Court|Place|Plaza|Gate|Ward|Hill|Market|Bridge)"
#: A number that is not an ordinal ("3rd"), not followed by a unit ("500 gp", "2 bells") and not the house number
#: of an address ("3 Waterdeep Lane": capitalised words ending in a street suffix). A capitalised word alone is
#: not an address: "now at 4 Madness" is a value followed by a score's name (#526 review).
_NUM = rf"\d+(?:\.\d+)?\b(?!\s*{_UNITS}\b)(?!(?:\s+(?-i:[A-Z])[\w'’-]*)+\s+{_STREET}\b)"
_WORDNUM = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
#: What can follow a number for it to be the end of a statement: a stop, a clause break, "N of <digits>", a
#: counter noun, or a capitalised word (a score's name: "pushes it to five Wrath"). A bare number-word ("to
#: one", "at three") is only read as a value with this behind it; "one of the Council" is not.
_TAIL = (
    r"(?=\s*(?:$|[,.;:()\]!?/%]|[—–]|\b(?:and|but|so far|already|points?|strikes?|marks?|ticks?|"
    r"stages?|steps?|stacks?)\b)|\s+(?:out\s+)?of\s+\d|\s+(?-i:[A-Z]))"
)
#: A digit run anywhere, or a number word only as the end of a clause (a move verb already says "this is a counter").
_NUM_LOOSE = rf"(?:{_NUM}|{_WORDNUM}\b{_TAIL})"
_NUM_END = rf"(?:{_NUM}{_TAIL}|{_WORDNUM}\b{_TAIL})"
#: Verbs that move a counter; "<verb> (it|the score|…) to N" and "<verb> … by N".
_MOVE = (
    r"(?:push|rais|bump|drop|lower|increas|decreas|reduc|ris|ros|rise|rose|climb|advanc|jump|fall|fell|"
    r"tip|grow|grew|shoot|shot|rack)\w*"
)
_SET_IT = r"(?:bring|brought|tak|mov|send|sent|put|set|get|got|lift|tick)\w*\s+(?:it|that|this|the (?:score|total|count|tally|number|meter|clock|track))"
#: Things that fill in boxes: "3 strikes", "a third tick". ``marks`` is handled apart: it is also ordinary prose.
_COUNTER = r"(?:strikes?|ticks?|stacks?|segments?|boxes|notches|pips)"
_ORDINAL = r"(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th))"
#: A noun an event is "at <time>": "the meeting is at 9" is not a count.
_APPOINTMENT = ("meeting", "ceremony", "feast", "dinner", "wedding", "funeral", "trial", "duel", "battle", "ritual",
                "parade", "council", "summit", "appointment", "rendezvous")
_NOT_APPOINTMENT = "".join(rf"(?<!{w}\s)" for w in _APPOINTMENT)

_VALUE_PATTERNS = (
    # "score is now 3", "total reaches 5", "value rises to 2", "gains points, bringing it to 6". A number
    # inside the window that is an ordinal ("3rd gate"), a unit ("2 bells") or an address does not count.
    rf"\b(?:score|total|values?|points?)\b[^.\d]{{0,30}}\b{_NUM}",
    # "a score of seven", "his score is seven"; "a total of seven guards" is a count of guards
    rf"\b(?:score|total|values?|points?|tally|count)\b[^.\d]{{0,30}}\b{_WORDNUM}\b{_TAIL}",
    rf"\b(?:\d+|{_WORDNUM})\s+points?\b",  # "gains 2 points", "gains one point"
    # "the tally is 4", "Daz's arc is at 3": a counter's own noun near a number
    rf"\b(?:arc|tally|count|meter)\b[^.\d]{{0,15}}\b{_NUM}",
    # "now at 4", "now 4", "is now at level 3": 'now' + the number as the end of the clause. "now sees 3
    # banners" and "now at 3 Waterdeep Lane" are not.
    rf"\bnow\b(?:\s+(?:is|are|at|on|stands?|sits?|reads?|=))*\s+(?:at\s+)?{_NUM_END}",
    # "Daz is at 3", "he is now at five": 'is at N' ending the clause, unless an appointment ("meeting is at 9")
    rf"{_NOT_APPOINTMENT}\b(?:is|are|was|were|sits?|stands?)\s+(?:now\s+)?at\s+{_NUM_END}",
    # "stands at 3", "reaches 5", "totals 4", "currently 2", "sits at 3 strikes"
    rf"\b(?:stands?|sits?|standing|sitting|currently|reach(?:es|ed)?|totals?|totalled|totaled|equals?)\b(?:\s+(?:at|on|is|=))?\s+{_NUM_END}",
    # "pushes it to 5", "drops to 2", "climbs up to 4": a counter-moving verb a few words before "to N"
    rf"\b{_MOVE}\b(?:\s+\w+){{0,3}}?\s+(?:up\s+|down\s+)?to\s+(?:a\s+|an\s+)?{_NUM_LOOSE}",
    rf"\b{_SET_IT}\s+(?:up\s+|down\s+)?to\s+(?:a\s+|an\s+)?{_NUM_LOOSE}",
    # "rises by 2", "pushes the count up by 1"
    rf"\b{_MOVE}\b(?:\s+\w+){{0,3}}?\s+by\s+{_NUM_LOOSE}",
    # "goes from 2 to 3" (not "from 3 to 4 days": the unit rides on the second number); "ticks up"
    rf"\bfrom\s+(?:\d+|{_WORDNUM})\s+to\s+{_NUM_LOOSE}",
    r"\btick(?:s|ed|ing)?\s+(?:up|down)\b",
    # a signed delta: "Wrath +2", "a +1", "Wrath -1", "Wrath−2". Plus needs no space before; minus must
    # stand alone ("level-3" and "Daz-2" are not deltas).
    r"(?:^|[\s(\w])\+\s?\d+\b",
    rf"(?:^|\s)[-−–]\d+\b(?!\s*{_UNITS}\b)",
    # a fraction: "(2/3)", "strike 2/3". "2 of 3 strikes" only when a counter noun carries it.
    r"\d+\s*/\s*\d+",
    r"\b(?:strikes?|marks?|ticks?|stages?|steps?|warnings?|stacks?|charges?)\s+(?:is |are |at )?\d+\s+(?:of|out of)\s+\d+",
    # a bare count of a counter noun: "has 3 strikes against him", "two more strikes". "marks" is also a
    # plain word ("two marks on the door"), so it counts only after a possessing verb or before 'now'.
    rf"\b(?:\d+|{_WORDNUM})\s+(?:more\s+)?{_COUNTER}\b",
    rf"\b(?:has|have|had|with|gets?|gains?|earns?|carries|bears|at)\s+(?:\d+|{_WORDNUM})\s+marks?\b",
    rf"\b(?:\d+|{_WORDNUM})\s+marks?\s+(?:now|so far|in all|total)\b|\bmarks?:\s*\d",
    # "a second strike against him", "his third tick", "strike two", "strike 2": not "the first strike on the ogre"
    rf"\b{_ORDINAL}\s+(?:strike|tick|segment|box)s?\b(?!\s+(?:on|at|to|with|from)\b)",
    rf"\b(?:strike|tick)\s+{_NUM_END}",
    # a meter filling: "the meter fills", "Daz's meter is full" (not "the track is full of mud")
    r"\b(?:meter|tracker|track|clock|gauge)\b[^.]{0,10}\b(?:fills?|filled|full(?!\s+of\b)|complete[sd]?|maxe[sd])\b",
    # "one mark away from the threshold"
    r"\baway from (?:the |his |her |its |their )?(?:\w+ )?threshold\b",
    # a threshold crossed: "the threshold is reached", "crosses the threshold", "the threshold of 5"
    r"\bthreshold\b[^.]{0,30}(?:reached|crossed|met|exceeded|passed|hit|triggered)",
    r"\b(?:reach|cross|meet|exceed|pass|hit|trip|break)\w*\s+(?:the\s+|his\s+|her\s+|its\s+|their\s+)?(?:\w+\s+)?threshold\b(?!\s+(?:of|to|into)\b)",
    rf"\bthreshold\b[^.\d]{{0,20}}\b{_NUM}",
)
#: What may sit between a score's own name and its number: "Obsession now at 4", "Obsession total reaches 5",
#: "Obsession: 4", "Obsession is at level 3". Filler is short on purpose; a name alone is not a value.
_NAME_FILLER = (
    r"(?:\s*[:=]|\s+(?:'s\s+)?(?:score|total|value|points?|level|stage|rank|tier|tally|count|meter|"
    r"is|are|was|now|currently|stands?|sits?|rises?|climbs?|reaches|hits|goes|jumps|moves|at|to|by|on|up|down)\b)"
)

#: Words before "arc/score/…" in a mechanic file that are not the score's name (articles, the nouns that
#: follow, and the capitalised words prose and instructions start a sentence with).
_NOT_A_NAME = frozenset(
    "the this that each every his her their its our your my a an of for and or but arc score track tracker meter "
    "counter clock pool tally current running total final new whole entire overall character characters npc faction "
    "when if per one any all only single same next last first main player party story campaign session long short "
    "gm dm with without while what which how keep time ability add use roll record note mark marks count tick "
    "update reset write set take make give get check see read apply start stop end then also here there these "
    "those some such both other another more most less least base basic simple default custom hidden visible "
    "shared private public total overall between".split()
)
#: ``Obsession arc``, ``the Obsession score``, ``his obsession meter``: the word before the noun, a name when it
#: is capitalised or follows an article/possessive.
_NAME_RE = re.compile(
    r"\b(?:(?-i:(?P<cap>[A-Z][\w'’-]{2,}))|(?:the|his|her|its|their)\s+(?P<low>[a-z][\w'’-]{3,}))\s+"
    r"(?:arc|score|track|tracker|meter|counter|clock|tally|pool)\b",
    re.I,
)
#: What precedes a sentence-initial word (start of text or line, a stop, a bullet): there a capital says nothing.
_SENTENCE_START = re.compile(r"(?:^|[.!?:]\s+|\n\s*(?:[-*]\s+)?)$")

_VALUE_RE = re.compile("|".join(f"(?:{p})" for p in _VALUE_PATTERNS), re.I)


def score_names(mechanic_text: str) -> frozenset[str]:
    """The score names a mechanic file uses for itself ("Obsession arc" -> ``obsession``), folded.

    Read from free prose, so it is a hint, not an authority: it only widens what counts as a stated value
    (``Obsession climbs to 4``), and a wrong name costs a candidate at most. A capitalised word that merely
    starts a sentence ("Keep score") and common words (``_NOT_A_NAME``) are not names. A player character's
    name next to "arc" is not told apart here: ``arc_check`` is not given the roster.
    """
    text = mechanic_text or ""
    found = set()
    for m in _NAME_RE.finditer(text):
        if m.group("cap") and _SENTENCE_START.search(text[: m.start()]):
            continue
        w = (m.group("cap") or m.group("low") or "").strip("'’-").casefold()
        if len(w) >= 3 and w not in _NOT_A_NAME:
            found.add(w)
    return frozenset(found)


def _name_re(names: Iterable[str]) -> re.Pattern | None:
    """Patterns anchored on the mechanic file's own score names, or None when there are none.

    ``<name> [filler] N``, ``<name> +N``, ``N <name>`` ("gains 1 Obsession"), ``<name> point(s)``, ``<name> full``,
    ``<name>, now at N`` and ``<name> … threshold``.
    """
    alts = "|".join(re.escape(n) for n in sorted({n.strip().casefold() for n in names if n and n.strip()}, key=len, reverse=True))
    if not alts:
        return None
    nm = rf"\b(?:{alts})\b(?:'s|’s)?"
    return re.compile(
        rf"{nm}(?:{_NAME_FILLER}){{0,3}}\s*(?:{_NUM}|{_WORDNUM}\b{_TAIL}|[+−–-]\s?\d)"
        rf"|{nm}[^.]{{0,30}}\bthreshold\b"
        rf"|\b(?:\d+|{_WORDNUM})\s+(?:(?:more|extra|additional)\s+)?(?:{alts})\b"
        rf"|{nm}\s+points?\b|\bpoints?\s+of\s+(?:{alts})\b"
        rf"|{nm}\s+(?:is\s+|now\s+)?(?:full|maxed|maxes|at (?:its|his|her|the) (?:max(?:imum)?|peak|limit)|ticks?)\b"
        rf"|{nm}[^.]{{0,20}}\b(?:reach(?:es|ed)?|climbs?\s+to|hits?)\s+(?:its|his|her|the)\s+(?:max(?:imum)?|peak|limit)\b"
        rf"|{nm},\s+(?:now\s+)?(?:at\s+)?{_NUM}",
        re.I,
    )


def states_a_value(event: str, names: Iterable[str] = ()) -> bool:
    """Does ``event`` (citations already removed) state a current value, a running total or a threshold crossed?

    ``names`` are the mechanic file's score names (``score_names``); with them, "<name> … N" is a value too.
    Deliberately over-eager: a false positive costs one listed candidate, a miss puts a number in front of the GM.
    """
    if _VALUE_RE.search(event):
        return True
    rx = _name_re(names)
    return bool(rx and rx.search(event))


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
    names = score_names(mechanic_text)
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
        if states_a_value(schema.STATE_CITE_RE.sub("", event), names):
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
