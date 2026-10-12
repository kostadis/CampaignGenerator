"""An NPC's knowledge horizon at a chapter, from the GM's presence ruling.

The horizon is a *floor*, not a model of the NPC's mind. It says what the GM has
ruled the NPC was present for, what is only about them, and what nobody has
ruled on yet — every item cited, nothing after the chapter. It does not claim
what the NPC was told (that needs a disclosure ruling) or that the NPC saw a
whole scene (they may have left). Prototype 3, the leak test, works from it.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from pipelines.npc_agent.corpus import Item
from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent.presence import Candidate
from pipelines.npc_agent.rulings import MENTIONED, PRESENT, UNSURE


@dataclass(frozen=True)
class Horizon:
    subject: str
    chapter: int
    first_seen: int | None  # first candidate chapter <= ``chapter``; None when none
    last_seen_by_chapter: int | None  # last candidate chapter <= ``chapter``
    witnessed: tuple[Candidate, ...]
    mentioned: tuple[Candidate, ...]
    unsure: tuple[Candidate, ...]
    unruled: tuple[Candidate, ...]
    #: candidates after ``chapter``. Kept for the caller, never rendered: the
    #: horizon is what an NPC agent will be shown, and a count of later items, or
    #: a first chapter after this one, tells it the future.
    later: int


def build_horizon(
    dossier: Dossier,
    cands: list[Candidate],
    rulings: dict[str, str],
    chapter: int,
    items: dict[str, Item] | None = None,
) -> Horizon:
    """``items`` (every corpus item by id, in corpus order) lets a ruling on a scene
    that does not name the NPC take effect: it enters as a candidate with no signals.
    """
    items = items or {}
    named = {c.item.item_id for c in cands}
    unnamed = [
        Candidate(item=items[i], signals=(), forms_matched=(), match_lines=())
        for i, v in rulings.items()
        if i not in named and i in items and v in (PRESENT, UNSURE)
    ]
    order = {i: n for n, i in enumerate(items)}
    every = sorted(cands + unnamed, key=lambda c: (c.item.chapter, order.get(c.item.item_id, 0)))
    upto = [c for c in every if c.item.chapter <= chapter]
    by = {PRESENT: [], MENTIONED: [], UNSURE: [], None: []}
    for c in upto:
        by[rulings.get(c.item.item_id)].append(c)
    chapters = [c.item.chapter for c in upto if c.signals]
    return Horizon(
        subject=dossier.subject,
        chapter=chapter,
        first_seen=min(chapters, default=None),
        last_seen_by_chapter=max(chapters, default=None),
        witnessed=tuple(by[PRESENT]),
        mentioned=tuple(by[MENTIONED]),
        unsure=tuple(by[UNSURE]),
        unruled=tuple(by[None]),
        later=len(every) - len(upto),
    )


def _cite(c: Candidate) -> str:
    it = c.item
    return f"[ch {it.chapter:03d} / {it.item_id}] {it.source_file}:{it.line}"


def _signals(c: Candidate) -> str:
    return ", ".join(c.signals) if c.signals else "not named in the text"


def _quote(text: str) -> str:
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def render_horizon(h: Horizon) -> str:
    out = [
        f"# Knowledge horizon — {h.subject}, as of chapter {h.chapter}",
        "",
        "A floor, not a mind: what the GM has ruled this NPC was present for, up to and including",
        f"chapter {h.chapter}. Nothing after it is shown. Unruled items are listed, never guessed.",
        "",
        f"- First named: chapter {h.first_seen if h.first_seen is not None else '—'}",
        f"- Last named by chapter {h.chapter}: "
        f"{h.last_seen_by_chapter if h.last_seen_by_chapter is not None else '—'}",
        f"- Witnessed: {len(h.witnessed)} · mentioned only: {len(h.mentioned)} · "
        f"unsure: {len(h.unsure)} · unruled: {len(h.unruled)}",
    ]
    if h.unruled:
        out += [
            "",
            f"**{len(h.unruled)} candidate(s) are unruled**, so this horizon is incomplete. "
            "Rule them in the presence file before relying on it.",
        ]

    out += ["", "## Witnessed (ruled present)", ""]
    if not h.witnessed:
        out.append("_(none ruled present)_")
    for c in h.witnessed:
        head = f"### {_cite(c)}" + ("" if c.signals else " — not named in the text")
        out += [head, "", _quote(c.item.text), ""]

    for title, group in (
        ("Mentioned only (about the NPC, who was not there)", h.mentioned),
        ("Unsure", h.unsure),
        ("Unruled", h.unruled),
    ):
        out += ["", f"## {title}", ""]
        if not group:
            out.append("_(none)_")
        for c in group:
            label = c.item.title or c.item.text.splitlines()[0][:90]
            out.append(f"- {_cite(c)} — {c.item.kind}, {_signals(c)} — {label}")
    return "\n".join(out).rstrip() + "\n"
