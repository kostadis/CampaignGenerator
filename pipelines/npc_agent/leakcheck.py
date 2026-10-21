"""Flags in an agent's answer for the GM to confirm. Never a verdict.

Two deterministic checks over the answer text, given what the agent was given:

``secret``  a sentence of the answer contains the content words of a leak
            case's "what she does not know" (:class:`knowledge.LeakCase`),
            matched by stem: all of them, or all but one when there are three
            or more, since a paraphrase swaps a word ("the party killed
            Moziqodo" for "the party killed her son"). {party, killed, son}:
            "The party killed Moziqodo" is flagged, "I pray for my son" is not.
            Leaning to over-flag is deliberate: a missed leak is the costly
            error, and the GM dismisses a false flag in one click.
``name``    a capitalised name in the answer that the campaign's summaries use
            but the agent was not given. It says where the name first appears,
            and whether that is after the freeze chapter (``future``).

A third check is for the reverse error, an NPC giving away its *own* secret:

``self``    a sentence of the answer contains one of the terms the GM gave
            with ``--secret-term`` (case-insensitive, word-bounded, a phrase
            matched whole). No stems and no paraphrase: the GM names the
            words that would give it away, so a hit is the word itself.

All are cheap signals that miss paraphrase and over-flag coincidence; the GM
reads the flag and decides. Names the summaries never use are not flagged,
since a made-up name is style, not a leak. No model call (guarded by
``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pipelines.npc_agent import knowledge
from pipelines.npc_agent.corpus import Corpus
from pipelines.npc_agent.persona import split_sentences

KIND_SECRET = "secret"
KIND_NAME = "name"
KIND_SELF = "self"

_STOP = frozenset(
    "that the her his their they she him them about with from have has had was were are this not yet "
    "and but who what which of".split()
)
_CAP = r"[A-Z][\w'’-]*"
#: A name: capitalised words joined by spaces, "of"/"the"/"of the" allowed inside before a capitalised word.
_RUN = re.compile(rf"{_CAP}(?:(?:\s+(?:of the|of|the))?\s+{_CAP})*")
_PRONOUNS = frozenset({"I", "I'm", "I'll", "I've", "I'd", "I’m", "I’ll", "I’ve", "I’d"})
_POSSESSIVE = re.compile(r"['’]s$")


@dataclass(frozen=True)
class Flag:
    kind: str  # KIND_SECRET | KIND_NAME
    sentence: str
    detail: str
    beat_id: str | None = None
    name: str | None = None
    first_chapter: int | None = None
    future: bool = False  # the name first appears in the summaries after the freeze chapter


def _scene_key(scene_id: str) -> tuple[int, int]:
    ch, _, sc = scene_id.partition(".")
    return int(ch), int(sc or 0)


def _content_words(what: str) -> list[str]:
    words = re.findall(r"[a-z]+", what.lower())
    return list(dict.fromkeys(w for w in words if len(w) >= 3 and w not in _STOP))


def _stem(w: str) -> str:
    return w if len(w) < 5 else w[:4]


def _secret_flags(answer_sentences: list[str], cases, corpus: Corpus, chapter: int,
                  target_scene: str | None) -> list[Flag]:
    whats = {c.beat_id: c.what for c in knowledge.find(corpus)}
    out: list[Flag] = []
    for case in cases:
        if target_scene is not None:
            if _scene_key(case.scene_id) > _scene_key(target_scene):
                continue
        elif case.chapter > chapter:
            continue
        what = whats.get(case.beat_id) or case.text
        stems = [_stem(w) for w in _content_words(what)]
        if not stems:
            continue
        for s in answer_sentences:
            tokens = re.findall(r"[a-z]+", s.lower())
            hits = sum(1 for st in stems if any(t.startswith(st) for t in tokens))
            if hits >= (len(stems) - 1 if len(stems) >= 3 else len(stems)):
                out.append(Flag(KIND_SECRET, s, f"states {case.beat_id}: {what}", beat_id=case.beat_id))
    return out


def _word(form: str, text: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(form)}(?![\w])", text) is not None


def _names(sentences: list[str], lower_words: frozenset[str]) -> list[tuple[str, str]]:
    """``(name, sentence)`` for each distinct capitalised name, first occurrence."""
    mid: set[str] = set()
    runs: list[tuple[str, str, bool]] = []  # (run, sentence, at_start)
    for s in sentences:
        for m in _RUN.finditer(s):
            at_start = not s[:m.start()].strip(" “\"'(*_—-")
            runs.append((m.group(0), s, at_start))
            words = m.group(0).split()
            for w in words[1:] if at_start else words:
                mid.add(_POSSESSIVE.sub("", w))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for run, s, at_start in runs:
        words = [_POSSESSIVE.sub("", w) for w in run.split()]
        words = [w for w in words if w not in _PRONOUNS]
        # A capitalised word the summaries also use in lower case is an ordinary
        # word at the head of a sentence or a quotation ("And", "Standing"), not
        # a name. Real run, 2026-10-13: every one of 11 flags was this. A name
        # that is also a common word ("Bow") is missed; the GM reads the answer.
        while words and (words[0].lower() in lower_words or words[0].lower() in _STOP):
            words = words[1:]
        while words and words[0] in ("of", "the", "of the"):
            words = words[1:]
        if not words:
            continue
        name = " ".join(words)
        if name not in seen:
            seen.add(name)
            out.append((name, s))
    return out


def _name_flags(answer_sentences: list[str], given: str, corpus: Corpus, chapter: int) -> list[Flag]:
    texts = [(ch.chapter, "\n".join(t for it in ch.items for _, t in it.lines)) for ch in corpus.chapters]
    lower_words = frozenset(w for _, t in texts for w in re.findall(r"\b[a-z][a-z'’-]*\b", t))
    out: list[Flag] = []
    for name, s in _names(answer_sentences, lower_words):
        first = next((ch for ch, t in texts if _word(name, t)), None)
        if first is None:
            continue  # the campaign never uses it: not a leak
        if _word(name, given) or all(_word(w, given) for w in re.findall(_CAP, name)):
            continue
        out.append(Flag(KIND_NAME, s, f"names {name!r}, not in what she was given; first in the summaries "
                        f"at ch {first:03d}", name=name, first_chapter=first, future=first > chapter))
    return out


def _self_flags(answer_sentences: list[str], terms: list[str]) -> list[Flag]:
    """A flag per sentence and term: the sentence contains the term, whole and word-bounded."""
    out: list[Flag] = []
    for term in dict.fromkeys(t.strip() for t in terms if t and t.strip()):
        rx = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.I)
        for s in answer_sentences:
            if rx.search(s):
                out.append(Flag(KIND_SELF, s, f"gives away his own secret: {term!r}"))
    return out


def check(answer: str, *, given: str, cases: list[knowledge.LeakCase], corpus: Corpus, chapter: int,
          target_scene: str | None = None, secret_terms: list[str] | tuple[str, ...] = ()) -> list[Flag]:
    """Flags for the GM to confirm; ``given`` is the exact text the agent was given.

    ``secret_terms`` are the NPC's own secrets, as words the GM chose.
    """
    sentences = split_sentences(answer)
    return _secret_flags(sentences, cases, corpus, chapter, target_scene) + \
        _name_flags(sentences, given, corpus, chapter) + _self_flags(sentences, list(secret_terms))


def render_flags(flags: list[Flag]) -> str:
    """Markdown for the GM; flags are for confirming, not verdicts."""
    out = ["# Leak check", "", f"{len(flags)} flag(s). Each is for you to confirm; none is a verdict.", ""]
    for kind, title in ((KIND_SECRET, "States something she does not know"),
                        (KIND_NAME, "Names something she was not given"),
                        (KIND_SELF, "Gives away its own secret")):
        fs = [f for f in flags if f.kind == kind]
        if not fs:
            continue
        out.append(f"## {title}")
        for f in fs:
            tag = " (FUTURE: after the freeze chapter)" if f.future else ""
            out.append(f"- {f.detail}{tag}")
            out.append(f"  > {f.sentence}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"
