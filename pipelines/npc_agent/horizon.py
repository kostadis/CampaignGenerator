"""An NPC's knowledge horizon at a chapter: the events they were in, and their state.

Built from authored structure and the GM's answers, nothing else:

- **Events** (scenes, ``NNN.SS``, in authored order) the GM answered *physically
  present*, each with its beats: what this NPC could have witnessed.
- Events that name the NPC answered *mentioned* (about them, while elsewhere) or
  *neither* (a wrong match or a scene too thin to say), and those still
  unanswered, listed apart so nothing is guessed.
- **The GM's notes on them**: their latest ``## NPCs`` entry up to the chapter,
  and every event naming them after it (snapshots lag: a quarter of Phandalin's
  cast have a latest snapshot older than their latest mention, event-ordinal
  proposal section 2.3). These are written from the GM's side of the screen
  ("does not yet know that the party killed her son"), so they are the GM's
  record *about* the NPC, never the NPC's knowledge.

Within an event answered *physically present*, a beat the GM listed as
``not_perceived`` is left out of what the NPC could know: the same summary that
records Sylvira at 067.03 also says, in that scene, what she does not know.
A beat whose sentence states what this NPC does not know (:mod:`knowledge`) is
left out the same way, wherever they were present.

``render_horizon(h, for_agent=True)`` gives only what the NPC could know, the
part an agent may be shown; everything else is for the GM.

The horizon is a floor, not a mind. It does not claim what the NPC was told, or
that they saw a whole scene. Nothing after the chapter is shown, not even a count:
it is what an NPC agent will be given, and a later chapter number tells it the
future.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

from dataclasses import dataclass

from pipelines.npc_agent.corpus import Item, beats
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
    not_perceived: frozenset[str]  # every beat left out, from either source
    hidden_by_note: frozenset[str]  # of those, the ones a knowledge note hides
    #: beats shown that hide something from someone nobody has named yet
    unresolved: frozenset[str]
    #: events after ``chapter``. Kept for the caller, never rendered.
    later: int


def build_horizon(
    dossier: Dossier,
    events: list[Candidate],
    rulings: dict[str, tuple[str, str]],
    chapter: int,
    items: dict[str, Item] | None = None,
    snapshots: list[Candidate] | None = None,
    not_perceived: frozenset[str] = frozenset(),
    hidden: frozenset[str] = frozenset(),
    unresolved: frozenset[str] = frozenset(),
) -> Horizon:
    """``events`` are the scenes naming the NPC; ``rulings`` is :func:`rulings.effective`.

    ``items`` (every corpus item by id, in corpus order) lets an answer on a scene
    that does not name the NPC (a span, or one marked by hand) take effect: it
    enters as an event with no signals. ``absent`` scenes are left out.
    ``hidden`` is :func:`knowledge.hidden_from`: beats of any scene; only those of
    a present event change what is shown.
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
    # Only beats of events shown can be left out of them; a count of any others
    # would be wrong, and a later one would hint at the future.
    seen = {b.beat_id for c in by[PRESENT] for b in beats(c.item)}
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
        not_perceived=(frozenset(not_perceived) | frozenset(hidden)) & seen,
        hidden_by_note=frozenset(hidden) & seen,
        unresolved=frozenset(unresolved) & seen,
        later=len(every) - len(upto),
    )


def _cite(it: Item) -> str:
    return f"[ch {it.chapter:03d} / {it.item_id}] {it.source_file}:{it.line}"


def _quote(text: str) -> str:
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def _perceived(c: Candidate, h: Horizon) -> list[str]:
    """The event's heading and the beats this NPC took in; left-out beats are counted, not shown."""
    out = [c.item.lines[0][1], ""]
    left_out = 0
    for b in beats(c.item):
        if b.beat_id in h.not_perceived:
            left_out += 1
            continue
        out += [b.text, ""]
    if left_out:
        out.append(f"({left_out} beat(s) of this scene left out: not perceived by {h.subject})")
    return out


def _headline(c: Candidate, h: Horizon) -> str:
    """The text of the scene's first ``####`` headline, without the marker; "" if it has none.

    A headline is a beat (``b01``), so one left out as not perceived is left out
    of the recap too.
    """
    for b in beats(c.item):
        if b.text.startswith("#### "):
            return "" if b.beat_id in h.not_perceived else b.text.splitlines()[0][len("#### "):].strip()
    return ""


def _recap(c: Candidate, h: Horizon) -> str:
    """One line for an event that does not name the NPC: its title, then its headline."""
    it = c.item
    cite = f"[ch {it.chapter:03d} / {it.item_id}]"
    head, title = _headline(c, h), it.title or ""
    return f"- {cite} {title}: {head}" if head and title else f"- {cite} {head or title}".rstrip()


def render_horizon(h: Horizon, for_agent: bool = False, compact: bool = False) -> str:
    """The horizon for the GM, or (``for_agent``) only what the NPC could know.

    ``compact`` is for an NPC whose horizon is most of the campaign (a companion
    at chapter 47 attended ~278 scenes, ~170k words). An event that names the
    NPC (``signals``) is still given in full, with its perceived beats; every
    other present event (a span scene that does not name them) is one line, its
    title and headline. Not-perceived and hidden beats are dropped as always,
    and so is a headline left out of a one-line recap.
    """
    head = [f"# What {h.subject} could know, as of chapter {h.chapter}", ""]
    if not for_agent:
        head = [
            f"# Knowledge horizon — {h.subject}, as of chapter {h.chapter}",
            "",
            "Part 1 is what this NPC could know: the events the GM answered *physically present*, in",
            "order, with the beats they took in" + (
                " (scenes that do not name them: a one-line recap)." if compact else "."
            ) + " Part 2 is for the GM only. Nothing after chapter",
            f"{h.chapter} is shown.",
            "",
            f"- First named: chapter {h.first_seen if h.first_seen is not None else '—'}",
            f"- Last named by chapter {h.chapter}: "
            f"{h.last_seen_by_chapter if h.last_seen_by_chapter is not None else '—'}",
            f"- Events physically present: {len(h.witnessed)} · mentioned: {len(h.mentioned)} · "
            f"neither or unsure: {len(h.neither)} · unanswered: {len(h.unruled)}",
            f"- Beats left out as not perceived: {len(h.not_perceived)}",
        ]
        if h.unresolved:
            head += [
                "",
                f"**{len(h.unresolved)} beat(s) shown say someone doesn't know something, and nobody has said "
                f"who** ({', '.join(sorted(h.unresolved))}). If it is {h.subject}, they leak. Rule who in the "
                "knowledge file.",
            ]
        if h.unruled:
            head += [
                "",
                f"**{len(h.unruled)} event(s) are unanswered**, so this horizon is incomplete. "
                "Answer them before relying on it.",
            ]
        head += ["", f"## Part 1 — what {h.subject} could know", ""]
    out = list(head)
    if compact:
        out += [f"Scenes that do not name {h.subject} are given by their one-line recap.", ""]
    if not h.witnessed:
        out.append("_(no event answered \u201cphysically present\u201d)_")
    recaps: list[str] = []

    def flush_recaps() -> None:
        if recaps:
            out.extend(recaps + [""])
            recaps.clear()

    for c in h.witnessed:
        if compact and not c.signals:
            recaps.append(_recap(c, h))
            continue
        flush_recaps()
        tags = [t for t, on in (("not named in the scene", not c.signals),
                                ("by span", c.item.item_id in h.by_span)) if on]
        cite = f"[ch {c.item.chapter:03d} / {c.item.item_id}]" if for_agent else _cite(c.item)
        out += [f"### {cite}" + (f" — {', '.join(tags)}" if tags and not for_agent else ""), ""]
        out += [_quote("\n".join(_perceived(c, h)).strip("\n")), ""]
    flush_recaps()
    if for_agent:
        return "\n".join(out).rstrip() + "\n"

    out += ["", "## Part 2 — for the GM only (never give this to an agent)", ""]
    out += [f"### The GM's notes on {h.subject} (their entries; the GM's record, not their knowledge)", ""]
    if h.snapshot is None:
        out.append("_(no entry for this NPC up to this chapter)_")
    else:
        out += [f"Latest entry: {_cite(h.snapshot)}", "", _quote(h.snapshot.text), ""]
        if h.since_snapshot:
            out.append("Events naming them since that entry (the entry may be out of date):")
            out += [f"- {_cite(c.item)} — {c.item.title}" for c in h.since_snapshot]
        else:
            out.append("No event names them after that entry.")
    if h.not_perceived:
        out += ["", "### Beats left out as not perceived", ""]
        for c in h.witnessed:
            for b in beats(c.item):
                if b.beat_id in h.not_perceived:
                    why = " (the summary says they don't know this)" if b.beat_id in h.hidden_by_note else ""
                    out.append(f"- {b.beat_id}{why} — {b.text.splitlines()[0][:160]}")
    for title, group in (
        ("Events that mention them (named, not physically there)", h.mentioned),
        ("Neither present nor mentioned, or unsure (left out; possible linking errors)", h.neither),
        ("Unanswered", h.unruled),
    ):
        out += ["", f"### {title}", ""]
        if not group:
            out.append("_(none)_")
        for c in group:
            how = " (by default)" if c.item.item_id in h.by_default else ""
            out.append(f"- {_cite(c.item)}{how} — {c.item.title}")
    return "\n".join(out).rstrip() + "\n"
