"""Knowledge notes: summary beats that say someone does not know something.

The summaries are written from the GM's side of the screen, and some beats say
outright that someone does not know a thing: "Sylvira is Moziqodo's mother, but
does not yet know that the party killed her son" (067.03). An NPC present at
that scene must not be given that beat as something they could know.

**The search.** A fixed list of phrasings (:data:`PATTERN`: "does not know",
"unaware of", "has no idea", "has not been told", ...) matched on scene beats
only, outside quoted speech and outside ``>`` quote lines, the first matching
line of each beat (21 beats in Out of the Abyss, 7 in Obelisk).

**The sentence decides what is hidden** (GM, 2026-10-13: "I already verified
that all of the sentences are correct, so why ask me?"). The summaries are
reviewed; the grammar of the sentence says whether the beat states the thing
someone does not know:

==========  =================================================  ===========================
outcome     what follows the phrase                            example
==========  =================================================  ===========================
``hides``   a "that" clause, a bare clause, "about"/"of" X,    "does not yet know *that the
            or a "has not been told" with the fact before it   party killed her son*"
``keeps``   a question (where, which, how, ...), a name or a   "didn't know *where the
            noun, or nothing (an answer to a question asked     secret room was*"
            in the beat)
==========  =================================================  ===========================

A ``keeps`` beat states nothing hidden: "Fargas didn't know where the secret
room was" does not say where it was. It stays in what anyone present could know,
whoever "he" is, so nobody is asked about it.

**Who does not know** matters only for a ``hides`` beat. It is read from the
sentence when the sentence names them: the name right before the phrase ("Asha
remained unaware"), the subject of the sentence when the phrase is its second
verb ("Sylvira is Moziqodo's mother, but does not yet know"), or "the party".
When the sentence gives a description ("the dragon", "the lone guard"), saying
which character that is, is the GM's ruling, in a file (version 3)::

    version: 3
    campaigns:
      out-of-the-abyss:
        who:
          "014.07.b02": [Themberchaud]     # "the dragon"
          "017.04.b22": [Themberchaud]

A ruling also overrides a name read from the sentence. A ruling on a ``keeps``
beat is refused: nothing in it is hidden.

A value may also be one of two words instead of a list::

          "014.07.b03": party     # hidden from the party; no NPC case
          "017.04.b22": nobody    # about creatures or people no NPC agent plays

Either one *resolves* the beat: it is no longer unresolved, so it holds back no
agent's horizon, and it hides the beat from no NPC and gives no leak case.
``party`` says the sentence is about the players' side ("the party does not know
the lich's name") when the sentence itself did not say "the party"; ``nobody``
says whoever does not know it is nobody an agent plays (an ooze, a stranger), so
there is no one to leak it to.

``who`` names count for a dossier when they are its subject or a form it lists.
A name with no published dossier (Themberchaud, Asha) still gives a leak case.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from pipelines.npc_agent.corpus import SCENE, Corpus, beats
from pipelines.npc_agent.dossier import Dossier

VERSION = 3
HIDES = "hides"
KEEPS = "keeps"
PARTY = "party"
NOBODY = "nobody"
#: Where ``who`` came from.
FROM_SENTENCE = "sentence"
FROM_GM = "gm"

_NEG = r"(?:n[’']t| not)"
#: Third-person statements that someone does not know something. Widen it and
#: the candidate list grows; a missed phrasing is a beat nobody looks at.
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
#: The capitalised name(s) right before the phrase: "Asha", "Nym and Kaelira genuinely".
_BEFORE = re.compile(rf"(?:^|[^\w'’-])({_NAME}(?: and {_NAME})?) (?:\w+ly )?$")
#: The sentence's subject when the phrase is its second verb: "Sylvira is ..., but ".
_SUBJECT = re.compile(rf"^[\s>*-]*({_NAME}) [^.;:!?]*(?:,? but|,? and|,? yet) (?:\w+ly )?$")
_PARTY_BEFORE = re.compile(r"\bthe party (?:\w+ly )?$", re.I)
_NOT_NAMES = frozenset({"He", "She", "They", "It", "The", "This", "That", "GM", "The GM", "Then", "When"})
#: Where "what they don't know" ends: the sentence, or a clause that moves on.
_WHAT_END = re.compile(r"[.;:!?]|,? (?:only|but|though|so)\b|,? and (?:is|was|are|were|appears?|has|had)\b")
#: A question: it never answers itself.
_QUESTION = re.compile(r"^(?:\w+ly )?(?:where|which|what|who|whom|whose|why|how|when|whether|if)\b", re.I)
#: A statement: "that ...", "about X", "of X", or a bare clause ("he is being groomed").
_STATEMENT = re.compile(
    r"^(?:that|about|of)\b"
    rf"|^(?:he|she|they|it|we|{_NAME}|the \w+) (?:is|was|are|were|has|had|have|will|would|did|does|can|could)\b",
)
#: Phrasings whose fact comes before them: "He is a simulacrum, and the party has not been told."
_FACT_BEFORE = re.compile(r"been told|unbeknownst", re.I)


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
    what: str  # what they don't know, as written after the phrase; "" if the bullet does not say


@dataclass(frozen=True)
class Resolved:
    candidate: Candidate
    outcome: str  # HIDES | KEEPS
    who: tuple[str, ...]  # characters it is hidden from; empty for the party, nobody, or when unknown
    party: bool
    source: str | None  # FROM_SENTENCE | FROM_GM; None when nobody is known
    nobody: bool = False  # the GM ruled it is about people no NPC agent plays

    @property
    def unresolved(self) -> bool:
        """A beat that hides something from someone the sentence does not name."""
        return self.outcome == HIDES and not self.who and not self.party and not self.nobody


def _unquoted(line: str) -> str:
    """The line with quoted speech blanked (same length), or "" for a ``>`` quote line."""
    if line.lstrip().startswith(">"):
        return ""
    return _QUOTED.sub(lambda m: " " * len(m.group(0)), line)


def _what(after: str, after_unquoted: str) -> str:
    """The rest of the clause after the phrase; the cut is found outside quoted speech."""
    m = _WHAT_END.search(after_unquoted)
    return after[: m.start() if m else len(after)].strip(" ,*")


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
                                         t[m.start():m.end()], b.text, it.title, u[:m.start()],
                                         _what(t[m.end():], u[m.end():])))
                    break
    return out


def outcome(c: Candidate) -> str:
    """HIDES when the sentence states what they don't know; KEEPS otherwise."""
    if c.phrase.lower().endswith(" of"):  # "unaware of X": X is so
        return HIDES if c.what else KEEPS
    if not c.what:
        return HIDES if _FACT_BEFORE.search(c.phrase) else KEEPS
    if _QUESTION.match(c.what):
        return KEEPS
    return HIDES if _STATEMENT.match(c.what) else KEEPS


def who_from_sentence(c: Candidate) -> tuple[tuple[str, ...], bool]:
    """``(names, party)``: who the sentence itself says does not know, or nobody."""
    before = c.before.rstrip(" ") + " "
    if _PARTY_BEFORE.search(before):
        return (), True
    for rx in (_BEFORE, _SUBJECT):
        m = rx.search(before)
        if m:
            names = tuple(x for x in m.group(1).split(" and ") if x not in _NOT_NAMES)
            if names:
                return names, False
    return (), False


def _word(form: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(form)}(?!\w)", text) is not None


def load_knowledge(path: Path, campaign: str, corpus: Corpus) -> dict[str, tuple[str, ...] | str]:
    """The GM's ``who`` rulings for ``campaign``: ``{beat_id: names}``, or ``PARTY`` / ``NOBODY``.

    Refuses a beat that is not a candidate, a beat whose sentence hides nothing,
    and a name that appears nowhere in the summaries.
    """
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise KnowledgeError(f"{path}: cannot read ({e.strerror})") from None
    except yaml.YAMLError as e:
        raise KnowledgeError(f"{path}: not valid YAML ({e})") from None
    if not isinstance(raw, dict) or set(raw) - {"version", "campaigns"}:
        raise KnowledgeError(f"{path}: expected a mapping with 'version' and 'campaigns'")
    if raw.get("version") in (1, 2):
        raise KnowledgeError(
            f"{path}: version {raw['version']} asked the GM to sort every beat; version 3 sorts them "
            "from the sentence and takes only 'who' for a beat whose sentence gives a description, "
            "not a name. Write: campaigns: {<campaign>: {who: {<beat id>: [<name>]}}}"
        )
    if raw.get("version") != VERSION:
        raise KnowledgeError(f"{path}: version must be {VERSION}, got {raw.get('version')!r}")
    campaigns = raw.get("campaigns") or {}
    if not isinstance(campaigns, dict):
        raise KnowledgeError(f"{path}: 'campaigns' must be a mapping of campaign -> rulings")
    block = campaigns.get(campaign) or {}
    if not isinstance(block, dict) or set(block) - {"who"}:
        raise KnowledgeError(f"{path}: {campaign!r} must be a mapping with 'who'")
    who = block.get("who") or {}
    if not isinstance(who, dict):
        raise KnowledgeError(f"{path}: {campaign!r} who must be a mapping of beat id -> names")
    found = {c.beat_id: c for c in find(corpus)}
    text = "\n".join(t for it in corpus.items() for _, t in it.lines)
    problems: list[str] = []
    out: dict[str, tuple[str, ...] | str] = {}
    for beat_id, names in who.items():
        beat_id, where = str(beat_id), f"{campaign} {beat_id}"
        if names is None:
            continue
        c = found.get(beat_id)
        if c is None:
            problems.append(f"{where}: not a beat that says someone does not know something")
            continue
        if outcome(c) == KEEPS:
            problems.append(f"{where}: nothing in it is hidden (it says only that someone doesn't know "
                            f"{c.what or 'something'}), so who does not matter")
            continue
        if isinstance(names, str) and names.strip().lower() in (PARTY, NOBODY):
            out[beat_id] = names.strip().lower()
            continue
        if not isinstance(names, list) or not names or not all(isinstance(x, str) and x.strip() for x in names):
            problems.append(f"{where}: who must be a list of names, or the word '{PARTY}' or '{NOBODY}'")
            continue
        names = [x.strip() for x in names]
        missing = [x for x in names if not _word(x, text)]
        if missing:
            problems.append(f"{where}: {', '.join(missing)} appears nowhere in the summaries; check the spelling")
            continue
        out[beat_id] = tuple(dict.fromkeys(names))
    if problems:
        raise KnowledgeError(f"{path}: {len(problems)} problem(s):\n  " + "\n  ".join(problems))
    return out


def resolve(corpus: Corpus, rulings: dict[str, tuple[str, ...] | str] | None = None) -> list[Resolved]:
    """Every candidate beat with its outcome and, for one that hides something, from whom."""
    rulings = rulings or {}
    out: list[Resolved] = []
    for c in find(corpus):
        o = outcome(c)
        if o == KEEPS:
            out.append(Resolved(c, o, (), False, None))
        elif rulings.get(c.beat_id) in (PARTY, NOBODY):
            out.append(Resolved(c, o, (), rulings[c.beat_id] == PARTY, FROM_GM, rulings[c.beat_id] == NOBODY))
        elif c.beat_id in rulings:
            out.append(Resolved(c, o, rulings[c.beat_id], False, FROM_GM))
        else:
            names, party = who_from_sentence(c)
            out.append(Resolved(c, o, names, party, FROM_SENTENCE if names or party else None))
    return out


def names_dossier(name: str, d: Dossier) -> bool:
    """The name is this dossier's subject or a form the dossier itself lists."""
    return name == d.subject or name in d.forms


def hidden_from(resolved: list[Resolved], d: Dossier) -> frozenset[str]:
    """Beat ids that state what this NPC does not know."""
    return frozenset(r.candidate.beat_id for r in resolved
                     if r.outcome == HIDES and any(names_dossier(x, d) for x in r.who))


@dataclass(frozen=True)
class LeakCase:
    who: str
    subject: str | None  # the published dossier the name resolves to, if any
    beat_id: str
    scene_id: str
    chapter: int
    text: str
    source: str


def leak_cases(resolved: list[Resolved], dossiers: list[Dossier]) -> list[LeakCase]:
    """One case per hidden beat and character it is hidden from, in corpus order."""
    out: list[LeakCase] = []
    for r in resolved:
        if r.outcome != HIDES:
            continue
        c = r.candidate
        for who in r.who:
            subj = next((d.subject for d in dossiers if names_dossier(who, d)), None)
            out.append(LeakCase(who, subj, c.beat_id, c.scene_id, c.chapter, c.text, r.source))
    return out


def leak_cases_yaml(campaign: str, cases: list[LeakCase]) -> str:
    """The leak cases as a YAML document a later prototype's checks read."""
    body = {
        "campaign": campaign,
        "cases": [
            {k: v for k, v in (
                ("who", c.who), ("dossier", c.subject), ("from", c.source), ("beat", c.beat_id),
                ("scene", c.scene_id), ("chapter", c.chapter), ("must_not_know", c.text),
            ) if v is not None}
            for c in cases
        ],
    }
    head = (
        "# Leak cases: as of each beat's scene, the character named must not know what it says.\n"
        "# Generated by npc_agent leaks from the summaries and the GM's who rulings; regenerate, do not edit.\n"
    )
    return head + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)
