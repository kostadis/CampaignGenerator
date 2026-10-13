"""The presence review page: one self-contained HTML file, generated from code.

``npc_agent review`` writes the page with everything it shows embedded as JSON:
each NPC's candidates and signals, and the text of every item in the chapters
the NPCs span (so a span can reach scenes that never name the NPC). The page
template is ``review/presence_review.html``; this module only fills it.

The page never decides presence. It shows the evidence, lets the GM rule items
and spans under the same rules as :mod:`pipelines.npc_agent.rulings`, and saves
a version-3 ruling file (as JSON, which is valid YAML) that ``npc_agent
horizon --rulings`` reads as it stands.

A second view, Knowledge notes, shows every beat :func:`knowledge.find` turns up
(one or more campaigns), and saves a knowledge ruling file that ``npc_agent
horizon --knowledge`` and ``npc_agent leaks`` read.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.npc_agent import corpus as corpus_mod
from pipelines.npc_agent.corpus import Corpus
from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent import knowledge, presence
from pipelines.npc_agent.presence import Candidate
from pipelines.npc_agent.rulings import VERSION

TEMPLATE = Path(__file__).resolve().parent / "review" / "presence_review.html"
DATA_SLOT = "/*__NPC_AGENT_DATA__*/null"
#: Bumped when the bundle's shape changes; the page refuses a bundle it does not know.
BUNDLE_VERSION = 4


def knowledge_campaign(campaign: str, corpus: Corpus, dossiers: list[Dossier]) -> dict:
    """One campaign's knowledge candidates, each with its scene for context."""
    scenes = {it.item_id: it for it in corpus.items() if it.kind == corpus_mod.SCENE}
    titles = {ch.chapter: ch.title or f"Chapter {ch.chapter}" for ch in corpus.chapters}
    cards = []
    for k in knowledge.find(corpus):
        names, party = knowledge.suggest(k, dossiers)
        cards.append({"id": k.beat_id, "s": k.scene_id, "c": k.chapter, "ct": titles[k.chapter], "st": k.scene_title,
                      "f": k.source_file, "l": k.line, "ph": k.phrase, "x": k.text, "sx": scenes[k.scene_id].text,
                      "sg": list(names), "sp": party, "w": k.what})
    return {"campaign": campaign, "subjects": sorted(d.subject for d in dossiers), "cards": cards}


def bundle(corpus: Corpus, pairs: list[tuple[Dossier, list[Candidate]]], source: str,
           knowledge_campaigns: list[dict] | None = None) -> dict:
    """The JSON the page renders from. Byte-deterministic for the same inputs.

    ``pairs`` gives each NPC with every mention (:func:`presence.mentions`). Only the
    events among them are answered; their state entries and context are shown.
    """
    firsts = [min(c.item.chapter for c in ms) for _, ms in pairs if ms]
    lasts = [max(c.item.chapter for c in ms) for _, ms in pairs if ms]
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
            if it.kind == corpus_mod.SCENE:
                items[it.item_id]["b"] = [[b.beat_id, b.text] for b in corpus_mod.beats(it)]
    npcs = [
        {
            "subject": d.subject,
            "stem": d.stem,
            "forms": list(d.forms),
            "first": min((c.item.chapter for c in ms), default=None),
            "last": max((c.item.chapter for c in ms), default=None),
            "candidates": {c.item.item_id: list(c.signals) for c in presence.events(ms)},
            "snapshots": [c.item.item_id for c in presence.snapshots(ms)],
            "context": [c.item.item_id for c in presence.context(ms)],
        }
        for d, ms in pairs
    ]
    return {"bundle": BUNDLE_VERSION, "rulings_version": VERSION, "source": source,
            "chapters": chapters, "items": items, "npcs": npcs,
            "knowledge": {"version": knowledge.VERSION, "campaigns": knowledge_campaigns or []}}


def render_page(data: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(DATA_SLOT) != 1:
        raise RuntimeError(f"{TEMPLATE}: expected exactly one data slot")
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # A summary line containing "</script" must not close the data block early.
    payload = payload.replace("</", "<\\/")
    return template.replace(DATA_SLOT, payload)
