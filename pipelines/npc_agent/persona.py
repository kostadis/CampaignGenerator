"""Who the NPC is, as of chapter N: her own ``## NPCs`` entries, cut to sentences about her.

An NPC's entries are written from the GM's side of the screen, so one entry
mixes three things: who she is, what others observed of her, and secrets she
does not have ("She is also Moziqodo's mother and does not yet know that the
party killed her son"). Handing the whole entry to an agent playing her leaks
the third and blurs the first two.

**The rule is grammatical, fixed, and applied to each sentence in this order**
(first match wins; nothing is judged by meaning):

=============  =================================================  ================
reason         test                                               result
=============  =================================================  ================
``hidden``     a not-knowing phrase (:data:`knowledge.PATTERN`,   dropped
               outside quoted speech) whose sentence states what
               is not known (:func:`knowledge.outcome` is HIDES).
               Inside her own entry a pronoun subject is her, so
               no check of *who* is made
``reported``   "She was heard / seen / reported ..." or her name  dropped
               followed by the same: others' observation of her
``first``      the first sentence of an entry: it describes her   kept
``self``       starts with She, Her, Herself or a form of her     kept
               name (word-bounded)
``other``      everything else                                    dropped
=============  =================================================  ================

Nothing is silently lost: :func:`render_persona_report` lists every dropped
sentence with its reason for the GM. The agent's text
(:func:`render_persona`) carries kept sentences only, labelled by the chapter
they were written at, and nothing written after the freeze chapter.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipelines.npc_agent import knowledge
from pipelines.npc_agent.corpus import Item
from pipelines.npc_agent.dossier import Dossier

REASON_HIDDEN = "says what she doesn't know"
REASON_REPORTED = "a report of her, not her"
REASON_FIRST = "describes her"
REASON_SELF = "she is the subject"
REASON_OTHER = "about someone else"

_OPEN = "“\""
_CLOSE = "”\""
_END = ".!?"
_REPORT_VERB = r"(?:heard|seen|observed|reported|said|rumored|rumoured|spotted)"
_ADVERB = r"(?:allegedly|reportedly|later|also|apparently)"


@dataclass(frozen=True)
class Sentence:
    entry_id: str  # e.g. "061.e06"
    chapter: int
    text: str
    kept: bool
    reason: str  # one of the REASON_* constants


def _body(text: str) -> str:
    """An entry's text without its ``### Name`` heading line or list markers."""
    lines = text.split("\n")
    if lines and lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    return "\n".join(re.sub(r"^\s*[-*]\s+", "", ln) for ln in lines)


def split_sentences(text: str) -> list[str]:
    """Sentences of ``text``; a ``.!?`` ends one only when whitespace and a capital (or the end) follow.

    Nothing inside quoted speech (curly or straight) ends a sentence, but a quote that closes right after
    its own ``.!?`` and is followed by a capital does, and the
    entry's heading line is not part of it. Newlines collapse to spaces.
    """
    t = re.sub(r"\s+", " ", _body(text)).strip()
    out: list[str] = []
    start, in_quote, i = 0, False, 0
    while i < len(t):
        ch = t[i]
        closes = (ch == "”" and in_quote) or (ch == '"' and in_quote)
        if ch == "“":
            in_quote = True
        elif ch == "”":
            in_quote = False
        elif ch == '"':
            in_quote = not in_quote
        if closes and t[i - 1] in _END and i + 1 < len(t) and t[i + 1] == " " and (
                i + 2 >= len(t) or t[i + 2].isupper() or t[i + 2] in _OPEN):
            # a quote that ends on its own terminator ends the sentence: '"Go." She left.'
            out.append(t[start:i + 1].strip())
            start, i = i + 1, i + 1
            continue
        if ch in _END and not in_quote:
            j = i + 1
            while j < len(t) and t[j] in "”\")*_":
                j += 1
            if j >= len(t) or (t[j] == " " and (j + 1 >= len(t) or t[j + 1].isupper() or t[j + 1] in "“\"")):
                s = t[start:j].strip()
                if s:
                    out.append(s)
                start, i = j, j
                continue
        i += 1
    tail = t[start:].strip()
    if tail:
        out.append(tail)
    return out


def _forms_rx(d: Dossier) -> str:
    forms = sorted({d.subject, *d.forms}, key=lambda f: (-len(f), f))
    return "|".join(re.escape(f) for f in forms)


def _hidden(entry: Item, sentence: str) -> bool:
    u = knowledge._unquoted(sentence)
    m = knowledge.PATTERN.search(u)
    if not m:
        return False
    cand = knowledge.Candidate(
        beat_id=entry.item_id, scene_id=entry.item_id, chapter=entry.chapter,
        source_file=entry.source_file, line=entry.line, phrase=sentence[m.start():m.end()],
        text=sentence, scene_title=entry.title or "", before=u[:m.start()],
        what=knowledge._what(sentence[m.end():], u[m.end():]),
    )
    return knowledge.outcome(cand) == knowledge.HIDES


def persona(entries: list[Item], dossier: Dossier, chapter: int) -> list[Sentence]:
    """Every sentence of the NPC's own entries up to ``chapter``, kept or dropped with its reason."""
    forms = _forms_rx(dossier)
    reported = re.compile(
        rf"^(?:She|{forms})(?!\w)\s+(?:was|is|were)\s+(?:{_ADVERB}\s+)?{_REPORT_VERB}\b")
    subject = re.compile(rf"^(?:She|Her|Herself|{forms})(?!\w)")
    out: list[Sentence] = []
    for it in entries:
        if it.chapter > chapter:
            continue
        for k, s in enumerate(split_sentences(it.text)):
            if _hidden(it, s):
                kept, reason = False, REASON_HIDDEN
            elif reported.match(s):
                kept, reason = False, REASON_REPORTED
            elif k == 0:
                kept, reason = True, REASON_FIRST
            elif subject.match(s):
                kept, reason = True, REASON_SELF
            else:
                kept, reason = False, REASON_OTHER
            out.append(Sentence(it.item_id, it.chapter, s, kept, reason))
    return out


def _by_entry(sentences: list[Sentence]) -> list[tuple[str, int, list[Sentence]]]:
    groups: list[tuple[str, int, list[Sentence]]] = []
    for s in sentences:
        if not groups or groups[-1][0] != s.entry_id:
            groups.append((s.entry_id, s.chapter, []))
        groups[-1][2].append(s)
    return groups


def render_persona(sentences: list[Sentence], subject: str, chapter: int) -> str:
    """Kept sentences only, by entry, labelled ``[ch NNN]``; what the agent is given."""
    out = [f"# Who {subject} is, as of chapter {chapter}", ""]
    for _, ch, ss in _by_entry([s for s in sentences if s.kept and s.chapter <= chapter]):
        out.append(f"[ch {ch:03d}] " + " ".join(s.text for s in ss))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def render_persona_report(sentences: list[Sentence], subject: str, chapter: int) -> str:
    """For the GM: every sentence, kept and dropped, each dropped one with its reason."""
    n_kept = sum(1 for s in sentences if s.kept)
    out = [f"# Persona report — {subject}, as of chapter {chapter}", "",
           f"{n_kept} sentence(s) kept, {len(sentences) - n_kept} dropped. The rule is grammatical and "
           "fixed (see persona.py); nothing is judged by meaning.", ""]
    for entry_id, ch, ss in _by_entry(sentences):
        out.append(f"## {entry_id} (ch {ch:03d})")
        for s in ss:
            out.append(f"- KEPT ({s.reason}): {s.text}" if s.kept else f"- DROPPED ({s.reason}): {s.text}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"
