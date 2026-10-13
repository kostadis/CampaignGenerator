"""An NPC's knowledge horizon at a chapter: the events they were in, and their state.

Built from authored structure and the GM's answers, nothing else:

- **Events** (scenes, ``NNN.SS``, in authored order) the GM answered *physically
  present*, each with its beats: what this NPC could have witnessed.
- Events that name the NPC answered *mentioned* (about them, while elsewhere) or
  *neither* (a wrong match or a scene too thin to say), and those still
  unanswered, listed apart so nothing is guessed.
- **State**: the NPC's latest snapshot (their own ``## NPCs`` entry) up to the
  chapter, and every event naming them after it. Snapshots lag: on Phandalin, a
  quarter of the cast's latest snapshot is older than their latest mention, so
  current state is the latest snapshot plus every mention after it (event-ordinal
  proposal, section 2.3).

The horizon is a floor, not a mind. It does not claim what the NPC was told, or
that they saw a whole scene. Nothing after the chapter is shown, not even a count:
it is what an NPC agent will be given, and a later chapter number tells it the
future.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from pipelines.npc_agent.corpus import Item
from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent.presence import Candidate
from pipelines.npc_agent.rulings import FROM_DEFAULT, FROM_SPAN, MENTIONED, NEITHER, PRESENT


@dataclass(frozen=True)
class Horizon:
    subject: str
    chapter: int
    first_seen: int | None  # first event naming them, up to ``chapter``
    last_seen_by_chapter: int | None  # last event naming them, up to ``chapter``
    witnessed: tuple[Candidate, ...]  # events answered present (named or not)
    mentioned: tuple[Candidate, ...]
    neither: tuple[Candidate, ...]
    unruled: tuple[Candidate, ...]
    snapshot: Item | None  # latest own ``## NPCs`` entry up to ``chapter``
    since_snapshot: tuple[Candidate, ...]  # events naming them after the snapshot's chapter
    by_span: frozenset[str]
    by_default: frozenset[str]
    #: events after ``chapter``. Kept for the caller, never rendered.
    later: int


def build_horizon(
    dossier: Dossier,
    events: list[Candidate],
    rulings: dict[str, tuple[str, str]],
    chapter: int,
    items: dict[str, Item] | None = None,
    snapshots: list[Candidate] | None = None,
) -> Horizon:
    """``events`` are the scenes naming the NPC; ``rulings`` is :func:`rulings.effective`.

    ``items`` (every corpus item by id, in corpus order) lets an answer on a scene
    that does not name the NPC (a span, or one marked by hand) take effect: it
    enters as an event with no signals. ``absent`` scenes are left out.
    """
    items = items or {}
    named = {c.item.item_id for c in events}
    unnamed = [
        Candidate(item=items[i], signals=(), forms_matched=(), match_lines=())
        for i, (v, _) in rulings.items()
        if i not in named and i in items and v == PRESENT
    ]
    order = {i: n for n, i in enumerate(items)}
    every = sorted(events + unnamed, key=lambda c: (c.item.chapter, order.get(c.item.item_id, 0)))
    upto = [c for c in every if c.item.chapter <= chapter]
    by = {PRESENT: [], MENTIONED: [], NEITHER: [], None: []}
    for c in upto:
        value = rulings.get(c.item.item_id, (None, None))[0]
        by[value if value in by else None].append(c)
    chapters = [c.item.chapter for c in upto if c.signals]
    snaps = [s.item for s in (snapshots or []) if s.item.chapter <= chapter]
    snap = snaps[-1] if snaps else None
    since = tuple(c for c in upto if c.signals and snap is not None and c.item.chapter > snap.chapter)
    return Horizon(
        subject=dossier.subject,
        chapter=chapter,
        first_seen=min(chapters, default=None),
        last_seen_by_chapter=max(chapters, default=None),
        witnessed=tuple(by[PRESENT]),
        mentioned=tuple(by[MENTIONED]),
        neither=tuple(by[NEITHER]),
        unruled=tuple(by[None]),
        snapshot=snap,
        since_snapshot=since,
        by_span=frozenset(i for i, (_, src) in rulings.items() if src == FROM_SPAN),
        by_default=frozenset(i for i, (_, src) in rulings.items() if src == FROM_DEFAULT),
        later=len(every) - len(upto),
    )


def _cite(it: Item) -> str:
    return f"[ch {it.chapter:03d} / {it.item_id}] {it.source_file}:{it.line}"


def _quote(text: str) -> str:
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def render_horizon(h: Horizon) -> str:
    out = [
        f"# Knowledge horizon — {h.subject}, as of chapter {h.chapter}",
        "",
        "A floor, not a mind: the events the GM has said this NPC was physically present at, in order,",
        f"up to and including chapter {h.chapter}, and their state. Nothing after it is shown.",
        "",
        f"- First named: chapter {h.first_seen if h.first_seen is not None else '—'}",
        f"- Last named by chapter {h.chapter}: "
        f"{h.last_seen_by_chapter if h.last_seen_by_chapter is not None else '—'}",
        f"- Events physically present: {len(h.witnessed)} · mentioned: {len(h.mentioned)} · "
        f"neither or unsure: {len(h.neither)} · unanswered: {len(h.unruled)}",
    ]
    if h.unruled:
        out += [
            "",
            f"**{len(h.unruled)} event(s) are unanswered**, so this horizon is incomplete. "
            "Answer them before relying on it.",
        ]

    out += ["", "## State", ""]
    if h.snapshot is None:
        out.append("_(no entry for this NPC up to this chapter)_")
    else:
        out += [f"Latest entry: {_cite(h.snapshot)}", "", _quote(h.snapshot.text), ""]
        if h.since_snapshot:
            out.append("Events naming them since that entry (the entry may be out of date):")
            out += [f"- {_cite(c.item)} — {c.item.title}" for c in h.since_snapshot]
        else:
            out.append("No event names them after that entry.")

    out += ["", "## Events physically present (what this NPC could have witnessed)", ""]
    if not h.witnessed:
        out.append("_(none answered “physically present”)_")
    for c in h.witnessed:
        tags = [t for t, on in (("not named in the scene", not c.signals),
                                ("by span", c.item.item_id in h.by_span)) if on]
        out += [f"### {_cite(c.item)}" + (f" — {', '.join(tags)}" if tags else ""), "",
                _quote(c.item.text), ""]

    for title, group in (
        ("Events that mention them (named, not physically there)", h.mentioned),
        ("Neither present nor mentioned, or unsure (left out; possible linking errors)", h.neither),
        ("Unanswered", h.unruled),
    ):
        out += ["", f"## {title}", ""]
        if not group:
            out.append("_(none)_")
        for c in group:
            how = " (by default)" if c.item.item_id in h.by_default else ""
            out.append(f"- {_cite(c.item)}{how} — {c.item.title}")
    return "\n".join(out).rstrip() + "\n"
