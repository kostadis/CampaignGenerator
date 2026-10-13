"""Split a scene into turns: what was put to the NPC, and what she did next.

The summaries record a scene as bullets in the GM's voice. Some bullets are about
her ("Sylvira sits upright in bed ...") and some are about the party ("Daz asks
whether ..."). A **turn** is the longest run of sentences that are about her; the
sentences between two turns are what the other side did, and are the prompt of the
next one. A replay gives the agent that prompt and compares its answer with the
turn's real text, so the split must not depend on the model or on meaning.

**The rule is grammatical and fixed.** A sentence is *hers* when, after an optional
leading clause ending in a comma, its subject is the NPC: ``She`` / ``she`` or one
of her dossier name forms, then a verb (a lower-case word that is not a conjunction,
preposition or article). Also hers: her possessive ("Her copper-red skin ...",
"Sylvira's ...") and a subject she shares ("She and Janussi instead discussed ..."),
since in a scene she is in, both are her account of herself. The first real split of
061.05 broke four of her answers on exactly these.
A leading clause is accepted only when it opens with a subordinator, adverb or
preposition from :data:`LEAD_WORDS`, or an ``-ed`` / ``-ing`` word ("Asked who ...,",
"Regarding Kalan,", "On reflection, however,", "Instead,"): that keeps a run-on such
as "Daz shows her the list, Sylvira laughs" from being read as hers. The clause
belongs to the prompt; the rest of the sentence is her answer.

Sentences come from every beat after the ``####`` headline, cut by
:func:`persona.split_sentences`; ``>`` quote lines stay attached to the sentence
before them. Sentences after her last turn are not a turn (she has no answer to
compare), and a turn that opens the scene has an empty prompt.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent import persona
from pipelines.npc_agent.corpus import Item
from pipelines.npc_agent.dossier import Dossier

LEAD_WORDS = frozenset((
    "when whenever while after before as if once since because although though unless until whereas "
    "instead regarding on in at upon with without despite given following during throughout "
    "then later still however meanwhile finally eventually also now first next afterward afterwards "
    "rather otherwise again ultimately initially eventually presumably").split())
#: Words that cannot be the verb after a subject ("She and Janussi ...").
NOT_VERBS = frozenset("and or but nor the a an to of in on at by for with from as than that who whom whose which".split())


@dataclass(frozen=True)
class Turn:
    prompt: str  # what the others did since her previous turn, plus her sentences' leading clauses
    actual: str  # her real text: the hers sentences, minus their leading clauses
    beat_ids: tuple[str, ...]  # the beats the actual text came from


def _join(parts: list[str]) -> str:
    return " ".join(p for p in parts if p)


def _sentences(beat_text: str) -> list[str]:
    """A beat's sentences; a run of ``>`` lines is attached to the sentence before it."""
    out: list[str] = []
    text_lines: list[str] = []
    quote_lines: list[str] = []

    def flush_text() -> None:
        if text_lines:
            out.extend(persona.split_sentences("\n".join(text_lines)))
            text_lines.clear()

    def flush_quote() -> None:
        if quote_lines:
            quote = "\n".join(quote_lines)
            if out:
                out[-1] = out[-1] + "\n" + quote
            else:
                out.append(quote)
            quote_lines.clear()

    for line in beat_text.split("\n"):
        s = line.strip()
        if s.startswith(">"):
            flush_text()
            quote_lines.append(s)
        elif s:
            flush_quote()
            text_lines.append(line)
        else:
            flush_text()
            flush_quote()
    flush_text()
    flush_quote()
    return out


def _commas(s: str) -> list[int]:
    """Indexes of commas outside quoted speech."""
    out, in_quote = [], False
    for i, ch in enumerate(s):
        if ch == "“":
            in_quote = True
        elif ch == "”":
            in_quote = False
        elif ch == '"':
            in_quote = not in_quote
        elif ch == "," and not in_quote:
            out.append(i)
    return out


def _lead_ok(clause: str) -> bool:
    words = re.findall(r"[A-Za-z]+", clause)
    if not words:
        return False
    w = words[0].lower()
    return w in LEAD_WORDS or (len(w) > 4 and (w.endswith("ed") or w.endswith("ing")))


def _subject_rx(d: Dossier) -> re.Pattern:
    forms = sorted({d.subject, *d.forms}, key=lambda f: (-len(f), f))
    alt = "|".join(re.escape(f) for f in forms)
    return re.compile(rf"(?:She|she|{alt})(?!\w)\s+([a-z][a-z’'-]*)")


def _about_her_rx(d: Dossier) -> re.Pattern:
    """Her possessive, or a subject she shares: "Her son ...", "Sylvira's ...", "She and Janussi ..."."""
    forms = sorted({d.subject, *d.forms}, key=lambda f: (-len(f), f))
    alt = "|".join(re.escape(f) for f in forms)
    return re.compile(rf"(?:(?:Her|her|(?:{alt})[’']s)\s+[a-z]|(?:She|she|{alt})\s+and\s+[A-Z])")


def hers(sentence: str, rx: re.Pattern, about: re.Pattern | None = None) -> tuple[str, str] | None:
    """``(leading clause, rest)`` when the sentence's subject is the NPC, else ``None``.

    ``rest`` starts with a capital letter; the clause keeps its comma and is ``""`` when there is none.
    """
    def ok(m: re.Match | None) -> bool:
        return m is not None and m.group(1) not in NOT_VERBS

    def about_her(text: str) -> bool:
        return about is not None and about.match(text) is not None

    if ok(rx.match(sentence)) or about_her(sentence):
        return "", sentence
    for i in _commas(sentence):
        rest = sentence[i + 1:].lstrip()
        if (ok(rx.match(rest)) or about_her(rest)) and _lead_ok(sentence[:i]):
            return sentence[:i + 1], rest[:1].upper() + rest[1:]
    return None


def split_turns(scene: Item, dossier: Dossier) -> list[Turn]:
    """The scene's turns, in order; see the module docstring for the rule."""
    rx = _subject_rx(dossier)
    about = _about_her_rx(dossier)
    turns: list[Turn] = []
    pending: list[str] = []  # prompt parts since the previous turn
    run: list[str] = []  # her sentences in the current run
    leads: list[str] = []
    ids: list[str] = []

    def close() -> None:
        if run:
            turns.append(Turn(_join(pending + leads), _join(run), tuple(dict.fromkeys(ids))))
            pending.clear()
            run.clear()
            leads.clear()
            ids.clear()

    for b in corpus_mod.beats(scene):
        if b.text.startswith("#### "):
            continue
        for s in _sentences(b.text):
            h = hers(s, rx, about)
            if h is None:
                close()
                pending.append(s)
            else:
                lead, rest = h
                if lead:
                    leads.append(lead)
                run.append(rest)
                ids.append(b.beat_id)
    close()
    return turns
