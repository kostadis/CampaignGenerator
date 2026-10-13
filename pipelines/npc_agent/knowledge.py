"""Knowledge notes: summary beats that say someone does not know something.

The summaries are written from the GM's side of the screen, and some beats say
outright that a character does not know a thing: "Sylvira is Moziqodo's mother,
but does not yet know that the party killed her son" (067.03). An NPC present
at that scene must not be given that beat as something they could know. This
module finds such beats and reads the GM's answer on each.

**The search finds candidates; it rules nothing.** It is a fixed list of
phrasings (:data:`PATTERN`: "does not know", "unaware of", "has no idea", "has
not been told", ...) matched on scene beats only, outside quoted speech and
outside ``>`` quote lines, the first matching line of each beat. The same words
cover three different things, and only the GM can tell them apart:

=========  ===========================================================  ========================
kind       what the beat is                                             effect
=========  ===========================================================  ========================
secret     the GM's note on a secret, hidden from named character(s)    left out of what each of
           ("Themberchaud doesn't know about the egg")                  them could know; a leak
                                                                        case
party      about what the party does not know                           none here (a player-side
           ("the party does not know which spells")                     view's concern)
said       a character tells the party they don't know something;      none: it was said in the
           said in the scene, so it is part of the scene               scene
unsure     the GM cannot say                                            none; listed apart
=========  ===========================================================  ========================

Ruling file (version 1), one block per campaign, since beat ids repeat across
campaigns::

    version: 1
    campaigns:
      out-of-the-abyss:
        "067.03.b04":
          kind: secret
          hidden_from: [Sylvira Savikas]
          note: she learns it later        # optional
        "015.02.b07": {kind: said}

``hidden_from`` names are the GM's, not matched: a name counts for a dossier
when it is that dossier's subject or one of the forms it lists. A name with no
published dossier (Themberchaud) is kept: it is still a leak case.

**A leak case** is one ``secret`` beat and one name it is hidden from: as of
that beat's scene, that character must not know what it says. The horizon
enforces it for the beat itself; a later agent's output is checked against it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipelines.npc_agent.corpus import SCENE, Corpus, beats
from pipelines.npc_agent.dossier import Dossier

VERSION = 1
SECRET = "secret"
PARTY = "party"
SAID = "said"
UNSURE = "unsure"
KINDS = (SECRET, PARTY, SAID, UNSURE)

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


@dataclass(frozen=True)
class Note:
    beat_id: str
    kind: str
    hidden_from: tuple[str, ...] = ()
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
                m = PATTERN.search(_unquoted(t))
                if m:
                    out.append(Candidate(b.beat_id, it.item_id, it.chapter, it.source_file, n,
                                         t[m.start():m.end()], b.text, it.title))
                    break
    return out


def _names_in(corpus: Corpus) -> str:
    return "\n".join(t for it in corpus.items() for _, t in it.lines)


def load_knowledge(path: Path, campaign: str, corpus: Corpus) -> dict[str, Note]:
    """``{beat_id: Note}`` for ``campaign``; other campaigns' blocks are not read.

    Refuses anything it cannot apply: an unknown kind, a beat not in the
    summaries, ``secret`` without a name, a name on any other kind, a name that
    appears nowhere in the summaries.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise KnowledgeError(f"{path}: cannot read ({e.strerror})") from None
    except yaml.YAMLError as e:
        raise KnowledgeError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(raw, dict) or set(raw) - {"version", "campaigns"}:
        raise KnowledgeError(f"{path}: expected a mapping with 'version' and 'campaigns'")
    if raw.get("version") != VERSION:
        raise KnowledgeError(f"{path}: version must be {VERSION}, got {raw.get('version')!r}")
    campaigns = raw.get("campaigns") or {}
    if not isinstance(campaigns, dict):
        raise KnowledgeError(f"{path}: 'campaigns' must be a mapping of campaign -> notes")
    block = campaigns.get(campaign) or {}
    if not isinstance(block, dict):
        raise KnowledgeError(f"{path}: {campaign!r} must be a mapping of beat id -> note")
    beat_ids = {b.beat_id for it in corpus.items() if it.kind == SCENE for b in beats(it)}
    text = _names_in(corpus)
    problems: list[str] = []
    out: dict[str, Note] = {}
    for beat_id, n in block.items():
        beat_id, where = str(beat_id), f"{campaign} {beat_id}"
        if n is None:
            continue
        if not isinstance(n, dict) or set(n) - {"kind", "hidden_from", "note"}:
            problems.append(f"{where}: expected a mapping with 'kind', 'hidden_from' and/or 'note'")
            continue
        if beat_id not in beat_ids:
            problems.append(f"{where}: not a beat (NNN.SS.bKK) of any scene in these summaries")
            continue
        kind, names = n.get("kind"), n.get("hidden_from") or []
        if kind not in KINDS:
            problems.append(f"{where}: kind {kind!r} is not one of {', '.join(KINDS)}")
            continue
        if not isinstance(names, list) or not all(isinstance(x, str) and x.strip() for x in names):
            problems.append(f"{where}: hidden_from must be a list of names")
            continue
        names = [x.strip() for x in names]
        if kind == SECRET and not names:
            problems.append(f"{where}: a secret needs hidden_from: who does not know")
            continue
        if kind != SECRET and names:
            problems.append(f"{where}: hidden_from is for a secret; this note is {kind!r}")
            continue
        missing = [x for x in names if not re.search(rf"(?<!\w){re.escape(x)}(?!\w)", text)]
        if missing:
            problems.append(f"{where}: {', '.join(missing)} appears nowhere in the summaries; check the spelling")
            continue
        note = n.get("note")
        out[beat_id] = Note(beat_id, kind, tuple(dict.fromkeys(names)), None if note is None else str(note))
    if problems:
        raise KnowledgeError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out


def names_dossier(name: str, d: Dossier) -> bool:
    """The GM's name is this dossier's subject or a form the dossier itself lists."""
    return name == d.subject or name in d.forms


def hidden_from(notes: dict[str, Note], d: Dossier) -> frozenset[str]:
    """Beat ids of every secret the GM says is hidden from this NPC."""
    return frozenset(
        n.beat_id for n in notes.values() if n.kind == SECRET and any(names_dossier(x, d) for x in n.hidden_from)
    )


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
    """One case per secret beat and name hidden from, in corpus order."""
    by_beat = {b.beat_id: (it, b) for it in corpus.items() if it.kind == SCENE for b in beats(it)}
    order = {bid: i for i, bid in enumerate(by_beat)}
    out: list[LeakCase] = []
    for n in sorted(notes.values(), key=lambda n: order[n.beat_id]):
        if n.kind != SECRET:
            continue
        it, b = by_beat[n.beat_id]
        for who in n.hidden_from:
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
