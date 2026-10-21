"""Prototype 6 helpers: what reached an NPC who was never there (or was there only for some scenes), and reading his reaction.

An absent NPC learns of events only through reports. :func:`reports` renders the
full text of each reported scene (title, headline, beats), in corpus order,
dropping any beat the knowledge rulings hide from him and refusing a scene that
is not in the corpus or lies after the freeze. :func:`parse_reaction` reads the
model's JSON leniently and, when it cannot, keeps the raw text as the reaction
rather than losing it. The GM's answer key is read by the CLI only to be copied
onto the review page; nothing here sees it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent.corpus import Corpus

SCENE_ID = re.compile(r"\d{3}\.\d{2}")


class ReactError(Exception):
    """A reported scene cannot be used; the message is user-facing."""


@dataclass(frozen=True)
class Report:
    scene_id: str
    title: str
    text: str  # what reached him: title, headline and the beats he may know


def reports(corpus: Corpus, reported: list[str] | tuple[str, ...], freeze: int,
            hidden: frozenset[str] = frozenset(), flag: str = "--reported") -> list[Report]:
    """The scenes in corpus order, each with its beats minus ``hidden`` ones; ``flag`` names the option in refusals."""
    wanted = list(dict.fromkeys(reported))
    for sid in wanted:
        if not SCENE_ID.fullmatch(sid):
            raise ReactError(f"{flag} {sid}: expected NNN.SS")
    scenes = {it.item_id: it for it in corpus.items() if it.kind == corpus_mod.SCENE}
    for sid in wanted:
        if sid not in scenes:
            raise ReactError(f"{flag} {sid}: not a scene in the summaries")
        if scenes[sid].chapter > freeze:
            raise ReactError(f"{flag} {sid}: is in chapter {scenes[sid].chapter}, after the freeze chapter {freeze}")
    out = []
    for it in corpus.items():
        if it.kind != corpus_mod.SCENE or it.item_id not in wanted:
            continue
        parts = [f"### {it.title or it.item_id}"]
        for b in corpus_mod.beats(it):
            if b.beat_id in hidden:
                continue
            t = b.text
            parts.append(t[len("#### "):].strip() if t.startswith("#### ") else t)
        out.append(Report(it.item_id, it.title or it.item_id, "\n\n".join(parts)))
    return out


def refuse_overlap(witnessed: list[str] | tuple[str, ...], reported: list[str] | tuple[str, ...]) -> None:
    """A scene is one or the other: she was there, or it was told to her."""
    both = sorted(set(witnessed) & set(reported))
    if both:
        raise ReactError(f"{', '.join(both)}: cannot be both --witnessed and --reported")


def hide_beats(corpus: Corpus, ids: list[str] | tuple[str, ...],
               scenes: list[str] | tuple[str, ...]) -> list[tuple[str, str]]:
    """``(beat_id, text)`` for each ruled-out beat, in the order given; it must be a beat of one of ``scenes``."""
    known = {b.beat_id: b.text for it in corpus.items() if it.item_id in scenes for b in corpus_mod.beats(it)}
    out = []
    for bid in dict.fromkeys(ids):
        if bid not in known:
            raise ReactError(f"--hide-beat {bid}: not a beat of a reported or witnessed scene")
        out.append((bid, known[bid]))
    return out


def render_witnessed(rs: list[Report]) -> str:
    """The "What you witnessed yourself" section body; no scene ids."""
    blocks = [f"Scene {i} of {len(rs)}. You were there.\n\n{r.text}" for i, r in enumerate(rs, 1)]
    return "\n\n---\n\n".join(blocks)


def render_reports(rs: list[Report], via: str) -> str:
    """The "What has reached you" section body; no scene ids, which are the GM's apparatus."""
    blocks = [f"Report {i} of {len(rs)}. Reported to you via {via}; you were not there.\n\n{r.text}"
              for i, r in enumerate(rs, 1)]
    return "\n\n---\n\n".join(blocks)


@dataclass(frozen=True)
class Decision:
    decision: str
    why: str


@dataclass
class Reaction:
    reaction: str = ""
    assessment: str = ""
    decisions: list[Decision] = field(default_factory=list)


def _str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def parse_reaction(raw: str, artifact: bool = False) -> tuple[Reaction, bool]:
    """``(reaction, parsed)``; ``parsed`` is False when the raw text was kept as the reaction.

    With ``artifact`` the keys are ``page`` / ``purpose`` / ``steps[{step, serves}]``, mapped onto
    ``reaction`` / ``assessment`` / ``decisions[{decision, why}]``.
    """
    k_main, k_assess, k_list, k_item, k_why = (("page", "purpose", "steps", "step", "serves") if artifact
                                               else ("reaction", "assessment", "decisions", "decision", "why"))
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(text)
    lo, hi = text.find("{"), text.rfind("}")
    if 0 <= lo < hi:
        candidates.append(text[lo:hi + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except ValueError:
            continue
        if not isinstance(data, dict) or not _str(data.get(k_main)):
            continue
        decs = []
        raw_decs = data.get(k_list)
        for it in raw_decs if isinstance(raw_decs, list) else []:
            if isinstance(it, str) and it.strip():
                decs.append(Decision(it.strip(), ""))
            elif isinstance(it, dict) and _str(it.get(k_item)):
                decs.append(Decision(_str(it[k_item]), _str(it.get(k_why))))
        return Reaction(_str(data[k_main]), _str(data.get(k_assess)), decs), True
    return Reaction(text, "", []), False
