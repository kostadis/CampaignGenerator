"""Prototype 5 helpers: where things stand at the freeze, and reading the agent's moves.

The forward turn asks the agent, once, what she does between sessions. Its reply
is meant to be JSON, ``[{"move": ..., "why": ...}]``, but a model's reply is not
trusted to be: :func:`parse_moves` reads it leniently (a code fence, text around
the array, a bare string, a single object) and, when nothing can be read, keeps
the raw text as one move rather than losing it. The GM scores what she gets.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent.corpus import Corpus


@dataclass(frozen=True)
class Move:
    move: str
    why: str


def parse_moves(raw: str) -> tuple[list[Move], bool]:
    """``(moves, parsed)``; ``parsed`` is False when the raw text was kept as one move."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(text)
    lo, hi = text.find("["), text.rfind("]")
    if 0 <= lo < hi:
        candidates.append(text[lo:hi + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except ValueError:
            continue
        if isinstance(data, dict):
            inner = next((v for v in data.values() if isinstance(v, list)), None)
            data = inner if inner is not None and "move" not in data else [data]
        if not isinstance(data, list):
            continue
        moves = []
        for it in data:
            if isinstance(it, str) and it.strip():
                moves.append(Move(it.strip(), ""))
            elif isinstance(it, dict) and isinstance(it.get("move"), str) and it["move"].strip():
                why = it.get("why")
                moves.append(Move(it["move"].strip(), why.strip() if isinstance(why, str) else ""))
        if moves:
            return moves, True
    return [Move(text, "")], False


def standing(corpus: Corpus, chapter: int, attended: bool) -> str:
    """The ``## Summary`` paragraphs of ``chapter``, only if she attended an event in it."""
    if not attended:
        return ""
    paras = [it.text for it in corpus.items() if it.kind == corpus_mod.PROSE and it.chapter == chapter]
    return "\n\n".join(paras)
