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
from pipelines.npc_agent.rulings import FROM_DEFAULT, FROM_SPAN, MENTIONED, PRESENT


@dataclass(frozen=True)
class Horizon:
    subject: str
    chapter: int
    first_seen: int | None  # first candidate chapter <= ``chapter``; None when none
    last_seen_by_chapter: int | None  # last candidate chapter <= ``chapter``
    witnessed: tuple[Candidate, ...]
    mentioned: tuple[Candidate, ...]
    unruled: tuple[Candidate, ...]
    #: item ids whose ruling came from a span rather than an item ruling
    by_span: frozenset[str]
    #: item ids ruled only by the NPC's default
    by_default: frozenset[str]
    #: candidates after ``chapter``. Kept for the caller, never rendered: the
    #: horizon is what an NPC agent will be shown, and a count of later items, or
    #: a first chapter after this one, tells it the future.
    later: int


def build_horizon(
    dossier: Dossier,
    cands: list[Candidate],
    rulings: dict[str, tuple[str, str]],
    chapter: int,
    items: dict[str, Item] | None = None,
) -> Horizon:
    """``rulings`` is :func:`rulings.effective`'s output: ``{item_id: (value, source)}``.

    ``items`` (every corpus item by id, in corpus order) lets a ruling on an item
    that does not name the NPC (a span, or a scene ruled one by one) take effect:
    it enters as a candidate with no signals. ``absent`` items are left out.
    """
    items = items or {}
    named = {c.item.item_id for c in cands}
    unnamed = [
        Candidate(item=items[i], signals=(), forms_matched=(), match_lines=())
        for i, (v, _) in rulings.items()
        if i not in named and i in items and v == PRESENT
    ]
    order = {i: n for n, i in enumerate(items)}
    every = sorted(cands + unnamed, key=lambda c: (c.item.chapter, order.get(c.item.item_id, 0)))
    upto = [c for c in every if c.item.chapter <= chapter]
    by = {PRESENT: [], MENTIONED: [], None: []}
    for c in upto:
        value = rulings.get(c.item.item_id, (None, None))[0]
        by[value if value in by else None].append(c)
    chapters = [c.item.chapter for c in upto if c.signals]
    return Horizon(
        subject=dossier.subject,
        chapter=chapter,
        first_seen=min(chapters, default=None),
        last_seen_by_chapter=max(chapters, default=None),
        witnessed=tuple(by[PRESENT]),
        mentioned=tuple(by[MENTIONED]),
        unruled=tuple(by[None]),
        by_span=frozenset(i for i, (_, src) in rulings.items() if src == FROM_SPAN),
        by_default=frozenset(i for i, (_, src) in rulings.items() if src == FROM_DEFAULT),
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
        "A floor, not a mind: the scenes the GM has said this NPC was physically present in, up to and including",
        f"chapter {h.chapter}. Nothing after it is shown. Unanswered passages are listed, never guessed.",
        "",
        f"- First named: chapter {h.first_seen if h.first_seen is not None else '—'}",
        f"- Last named by chapter {h.chapter}: "
        f"{h.last_seen_by_chapter if h.last_seen_by_chapter is not None else '—'}",
        f"- Physically present: {len(h.witnessed)} · mentioned: {len(h.mentioned)} · "
        f"unanswered: {len(h.unruled)}",
    ]
    if h.unruled:
        out += [
            "",
            f"**{len(h.unruled)} passage(s) are unanswered**, so this horizon is incomplete. "
            "Answer them before relying on it.",
        ]

    out += ["", "## Physically present (what this NPC could have witnessed)", ""]
    if not h.witnessed:
        out.append("_(none answered \u201cphysically present\u201d)_")
    for c in h.witnessed:
        tags = [t for t, on in (("not named in the text", not c.signals),
                                ("by span", c.item.item_id in h.by_span)) if on]
        head = f"### {_cite(c)}" + (f" — {', '.join(tags)}" if tags else "")
        out += [head, "", _quote(c.item.text), ""]

    for title, group in (
        ("Mentioned (named, not physically there)", h.mentioned),
        ("Unanswered", h.unruled),
    ):
        out += ["", f"## {title}", ""]
        if not group:
            out.append("_(none)_")
        for c in group:
            label = c.item.title or c.item.text.splitlines()[0][:90]
            how = " (by default)" if c.item.item_id in h.by_default else ""
            out.append(f"- {_cite(c)}{how} — {c.item.kind}, {_signals(c)} — {label}")
    return "\n".join(out).rstrip() + "\n"
