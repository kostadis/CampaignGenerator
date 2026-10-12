"""The presence review page: one self-contained HTML file, generated from code.

``npc_agent review`` writes the page with everything it shows embedded as JSON:
each NPC's candidates and signals, and the text of every item in the chapters
the NPCs span (so a span can reach scenes that never name the NPC). The page
template is ``review/presence_review.html``; this module only fills it.

The page never decides presence. It shows the evidence, lets the GM rule items
and spans under the same rules as :mod:`pipelines.npc_agent.rulings`, and saves
a version-2 ruling file (as JSON, which is valid YAML) that ``npc_agent
horizon --rulings`` reads as it stands.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.npc_agent.corpus import Corpus
from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent.presence import Candidate
from pipelines.npc_agent.rulings import VERSION

TEMPLATE = Path(__file__).resolve().parent / "review" / "presence_review.html"
DATA_SLOT = "/*__NPC_AGENT_DATA__*/null"
#: Bumped when the bundle's shape changes; the page refuses a bundle it does not know.
BUNDLE_VERSION = 1


def bundle(corpus: Corpus, pairs: list[tuple[Dossier, list[Candidate]]], source: str) -> dict:
    """The JSON the page renders from. Byte-deterministic for the same inputs."""
    firsts = [min(c.item.chapter for c in cands) for _, cands in pairs if cands]
    lasts = [max(c.item.chapter for c in cands) for _, cands in pairs if cands]
    lo, hi = (min(firsts), max(lasts)) if firsts else (0, -1)
    chapters, items = [], {}
    for ch in corpus.chapters:
        if not lo <= ch.chapter <= hi:
            continue
        chapters.append(
            {"n": ch.chapter, "title": ch.title or f"Chapter {ch.chapter}", "file": ch.source_file,
             "items": [it.item_id for it in ch.items]}
        )
        for it in ch.items:
            items[it.item_id] = {"k": it.kind, "c": it.chapter, "t": it.title, "x": it.text,
                                 "l": it.line}
    npcs = [
        {
            "subject": d.subject,
            "stem": d.stem,
            "forms": list(d.forms),
            "first": min((c.item.chapter for c in cands), default=None),
            "last": max((c.item.chapter for c in cands), default=None),
            "candidates": {c.item.item_id: list(c.signals) for c in cands},
        }
        for d, cands in pairs
    ]
    return {"bundle": BUNDLE_VERSION, "rulings_version": VERSION, "source": source,
            "chapters": chapters, "items": items, "npcs": npcs}


def render_page(data: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_SLOT) != 1:
        raise RuntimeError(f"{TEMPLATE}: expected exactly one data slot")
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # A summary line containing "</script" must not close the data block early.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_SLOT, payload)
