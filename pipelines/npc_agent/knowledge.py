"""Knowledge notes: summary beats that say someone does not know something.

The summaries are written from the GM's side of the screen, and some beats say
outright that someone does not know a thing: "Sylvira is Moziqodo's mother, but
does not yet know that the party killed her son" (067.03). An NPC present at
that scene must not be given that beat as something they could know. This
module finds such beats and reads the GM's answer on each.

**The search finds candidates; it rules nothing.** It is a fixed list of
phrasings (:data:`PATTERN`: "does not know", "unaware of", "has no idea", "has
not been told", ...) matched on scene beats only, outside quoted speech and
outside ``>`` quote lines, the first matching line of each beat.

**Two questions per beat** (GM, 2026-10-13: "Most of the cards were 'the
object of the sentence doesn't know'", e.g. "Asha doesn't know"). The first
version asked what kind of beat it was; the GM read every card as "someone
doesn't know" and answered accordingly. So the questions are about that someone:

1. **Who doesn't know?** One or more characters, ``party``, or ``unsure``
   (nobody in particular: "anyone who did not know which key was genuine").
2. For characters: **does the beat give away what they don't know?**
   ``gives_away: true`` (Sylvira's son's death, Themberchaud's egg): the beat
   is left out of what each of them could know, wherever they were present, and
   it is a leak case. ``gives_away: false`` (Hgraam "does not know where it
   is"): the beat stays; not knowing is part of what they know.

The search suggests the name it finds right before the phrase ("Asha remained
unaware", "Nym and Kaelira genuinely did not know") and any published dossier
named in the beat. A suggestion is a button on the review page; only the GM's
answer is read here.

Ruling file (version 2), one block per campaign, since beat ids repeat across
campaigns::

    version: 2
    campaigns:
      out-of-the-abyss:
        "067.03.b04": {who: [Sylvira Savikas], gives_away: true}
        "026.04.b08": {who: [Hgraam], gives_away: false}
        "062.06.b09": {who: party}
        "063.06.b08": {who: unsure, note: anyone holding the fake}

``who`` names are the GM's, not matched: a name counts for a dossier when it is
that dossier's subject or one of the forms it lists. A name with no published
dossier (Themberchaud) is kept: it is still a leak case.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipelines.npc_agent.corpus import SCENE, Corpus, beats
from pipelines.npc_agent.dossier import Dossier

VERSION = 2
PARTY = "party"
UNSURE = "unsure"

_NEG = r"(?:n[’']t| not)"
#: Third-person statements that someone does not know something. Widen it and
#: the candidate list grows; it never decides anything, so a false hit costs one
#: card on the review page and a missed phrasing costs a beat nobody reviews.
PATTERN = re.compile(
    r"\b("
    rf"does{_NEG}(?: yet)? know|did{_NEG}(?: yet)? know"
    r"|(?:is|was|are|were|remains?|remained) (?:still |completely |entirely )?unaware|unaware of"
    r"|(?:has|had) no idea|(?:is|was|are|were) not aware"
    r"|never (?:learned|learns|found out|realized|realised)|unbeknownst"
    rf"|(?:has|had){_NEG} (?:yet )?been told"
    rf"|does{_NEG} (?:yet )?(?:realize|realise|suspect)|did{_NEG} (?:yet )?(?:realize|realise|suspect)"
    r"|still believes?|still thinks?"
    r")\b",
    re.I,
)
_QUOTED = re.compile(r"“[^”]*”|\"[^\"]*\"")
_NAME = r"[A-Z][\w'’-]*(?: [A-Z][\w'’-]*)*"
#: The capitalised name(s) right before the phrase, with an optional adverb:
#: "Asha remained", "Nym and Kaelira genuinely", "Tadric".
_BEFORE = re.compile(rf"(?:^|[^\w'’-])({_NAME}(?: and {_NAME})?) (?:\w+ly )?$")
_PARTY_BEFORE = re.compile(r"\bthe party (?:\w+ly )?$", re.I)
_NOT_NAMES = frozenset({"He", "She", "They", "It", "The", "This", "That", "GM", "The GM"})


class KnowledgeError(Exception):
    """The knowledge ruling file cannot be used; the message is user-facing."""


@dataclass(frozen=True)
class Candidate:
    beat_id: str
    scene_id: str
    chapter: int
    source_file: str
    line: int  # the matching line
    phrase: str  # the words that matched, as written
    text: str  # the whole beat
    scene_title: str
    before: str  # the matching line up to the phrase, quoted speech blanked


@dataclass(frozen=True)
class Note:
    beat_id: str
    who: tuple[str, ...] = ()  # characters; empty for party or unsure
    party: bool = False
    unsure: bool = False
    gives_away: bool | None = None  # set exactly when ``who`` names characters
    note: str | None = None


def _unquoted(line: str) -> str:
    """The line with quoted speech blanked (same length), or "" for a ``>`` quote line."""
    if line.lstrip().startswith(">"):
        return ""
    return _QUOTED.sub(lambda m: " " * len(m.group(0)), line)


def find(corpus: Corpus) -> list[Candidate]:
    """Every scene beat with a not-knowing phrase outside quoted speech, in corpus order."""
    out: list[Candidate] = []
    for it in corpus.items():
        if it.kind != SCENE:
            continue
        for b in beats(it):
            for n, t in b.lines:
                u = _unquoted(t)
                m = PATTERN.search(u)
                if m:
                    out.append(Candidate(b.beat_id, it.item_id, it.chapter, it.source_file, n,
                                         t[m.start():m.end()], b.text, it.title, u[:m.start()]))
                    break
    return out


def _word(form: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(form)}(?!\w)", text) is not None


def suggest(c: Candidate, dossiers: list[Dossier]) -> tuple[tuple[str, ...], bool]:
    """``(names, party)``: who the beat seems to say does not know. A suggestion only.

    Names: the capitalised name(s) right before the phrase, then each published
    dossier one of whose forms the beat names (by subject). ``party`` when the
    phrase follows "the party".
    """
    before = c.before.rstrip(" ") + " "
    names: list[str] = []
    m = _BEFORE.search(before)
    if m:
        names += [x for x in m.group(1).split(" and ") if x not in _NOT_NAMES]
    for d in sorted(dossiers, key=lambda d: d.subject):
        if any(_word(f, c.text) for f in (d.subject, *d.forms)) and not any(
            x == d.subject or x in d.forms for x in names
        ):
            names.append(d.subject)
    return tuple(dict.fromkeys(names)), bool(_PARTY_BEFORE.search(before))


def load_knowledge(path: Path, campaign: str, corpus: Corpus) -> dict[str, Note]:
    """``{beat_id: Note}`` for ``campaign``; other campaigns' blocks are not read.

    Refuses anything it cannot apply: a beat not in the summaries, ``who``
    missing or malformed, ``gives_away`` missing for characters or given for the
    party or unsure, a name that appears nowhere in the summaries.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise KnowledgeError(f"{path}: cannot read ({e.strerror})") from None
    except yaml.YAMLError as e:
        raise KnowledgeError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(raw, dict) or set(raw) - {"version", "campaigns"}:
        raise KnowledgeError(f"{path}: expected a mapping with 'version' and 'campaigns'")
    if raw.get("version") == 1:
        raise KnowledgeError(
            f"{path}: version 1 (kind: secret/party/said/unsure) is no longer read. In version 2, "
            "'kind: party' is 'who: party', 'kind: unsure' is 'who: unsure', and 'kind: secret, "
            "hidden_from: [X]' is 'who: [X], gives_away: true'; 'kind: said' needs who answered again"
        )
    if raw.get("version") != VERSION:
        raise KnowledgeError(f"{path}: version must be {VERSION}, got {raw.get('version')!r}")
    campaigns = raw.get("campaigns") or {}
    if not isinstance(campaigns, dict):
        raise KnowledgeError(f"{path}: 'campaigns' must be a mapping of campaign -> notes")
    block = campaigns.get(campaign) or {}
    if not isinstance(block, dict):
        raise KnowledgeError(f"{path}: {campaign!r} must be a mapping of beat id -> note")
    beat_ids = {b.beat_id for it in corpus.items() if it.kind == SCENE for b in beats(it)}
    text = "\n".join(t for it in corpus.items() for _, t in it.lines)
    problems: list[str] = []
    out: dict[str, Note] = {}
    for beat_id, n in block.items():
        beat_id, where = str(beat_id), f"{campaign} {beat_id}"
        if n is None:
            continue
        if not isinstance(n, dict) or "who" not in n or set(n) - {"who", "gives_away", "note"}:
            problems.append(f"{where}: expected a mapping with 'who', and 'gives_away' and/or 'note'")
            continue
        if beat_id not in beat_ids:
            problems.append(f"{where}: not a beat (NNN.SS.bKK) of any scene in these summaries")
            continue
        who, gives = n["who"], n.get("gives_away")
        note = None if n.get("note") is None else str(n["note"])
        if who in (PARTY, UNSURE):
            if gives is not None:
                problems.append(f"{where}: gives_away is for characters; who is {who!r}")
                continue
            out[beat_id] = Note(beat_id, party=who == PARTY, unsure=who == UNSURE, note=note)
            continue
        if not isinstance(who, list) or not who or not all(isinstance(x, str) and x.strip() for x in who):
            problems.append(f"{where}: who must be 'party', 'unsure', or a list of names")
            continue
        if not isinstance(gives, bool):
            problems.append(f"{where}: gives_away must be true or false: does the beat give away what they don't know?")
            continue
        names = [x.strip() for x in who]
        missing = [x for x in names if not _word(x, text)]
        if missing:
            problems.append(f"{where}: {', '.join(missing)} appears nowhere in the summaries; check the spelling")
            continue
        out[beat_id] = Note(beat_id, tuple(dict.fromkeys(names)), gives_away=gives, note=note)
    if problems:
        raise KnowledgeError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out


def names_dossier(name: str, d: Dossier) -> bool:
    """The GM's name is this dossier's subject or a form the dossier itself lists."""
    return name == d.subject or name in d.forms


def hidden_from(notes: dict[str, Note], d: Dossier) -> frozenset[str]:
    """Beat ids that give away what this NPC does not know."""
    return frozenset(n.beat_id for n in notes.values() if n.gives_away and any(names_dossier(x, d) for x in n.who))


def tally(notes: dict[str, Note]) -> dict[str, int]:
    return {
        "gives away (hidden)": sum(1 for n in notes.values() if n.gives_away),
        "only says they don't know (kept)": sum(1 for n in notes.values() if n.gives_away is False),
        "the party": sum(1 for n in notes.values() if n.party),
        "unsure": sum(1 for n in notes.values() if n.unsure),
    }


@dataclass(frozen=True)
class LeakCase:
    who: str
    subject: str | None  # the published dossier the name resolves to, if any
    beat_id: str
    scene_id: str
    chapter: int
    text: str
    note: str | None


def leak_cases(notes: dict[str, Note], corpus: Corpus, dossiers: list[Dossier]) -> list[LeakCase]:
    """One case per beat that gives something away and name it is hidden from, in corpus order."""
    by_beat = {b.beat_id: (it, b) for it in corpus.items() if it.kind == SCENE for b in beats(it)}
    order = {bid: i for i, bid in enumerate(by_beat)}
    out: list[LeakCase] = []
    for n in sorted(notes.values(), key=lambda n: order[n.beat_id]):
        if not n.gives_away:
            continue
        it, b = by_beat[n.beat_id]
        for who in n.who:
            subj = next((d.subject for d in dossiers if names_dossier(who, d)), None)
            out.append(LeakCase(who, subj, n.beat_id, it.item_id, it.chapter, b.text, n.note))
    return out


def leak_cases_yaml(campaign: str, cases: list[LeakCase]) -> str:
    """The leak cases as a YAML document a later prototype's checks read."""
    body = {
        "campaign": campaign,
        "cases": [
            {k: v for k, v in (
                ("who", c.who), ("dossier", c.subject), ("beat", c.beat_id), ("scene", c.scene_id),
                ("chapter", c.chapter), ("must_not_know", c.text), ("note", c.note),
            ) if v is not None}
            for c in cases
        ],
    }
    head = (
        "# Leak cases: as of each beat's scene, the character named must not know what it says.\n"
        "# Generated by npc_agent leaks from the GM's knowledge rulings; regenerate, do not edit.\n"
    )
    return head + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)
