"""Attach checked thread notes to the GM's ratified threads (spec 034, research R4). No model call.

Thread identity is the GM's thread registry. A thread note attaches to the one ratified thread whose
title or alias equals the note's bold name after ``campaignlib.thread_registry.norm_title``; equality of
that key is the whole rule, never similarity. A name that two threads claim is **ambiguous**: reported,
and the note stays unattached.

Two optional registry fields rule on a note by id, and both are checked before any name (#529):

1. ``included_notes``: the note is pinned to that thread. It attaches there by id, and a pinned note never also
   attaches elsewhere by name (a pin on two threads leaves it ambiguous).
2. ``excluded_notes`` (note ids the GM split off when ratifying a group): the thread is not a candidate for the
   note, whatever its name. The note may still attach to another thread that claims the name; if only the
   excluding thread does, it stays unattached and is offered again, and the report lists it as held out.
3. Otherwise, the name rule above.

Whether an attached thread is open is code's decision too (FR-009a). A registry status the GM set to
``dormant``, ``resolved`` or ``abandoned`` wins; a status of ``open`` (the default) defers to the latest
attached note, open meaning its tag is ``OPENED`` or ``ADVANCED``. A build describes the campaign as of its last
chapter, so a thread the GM resolved or abandoned *after* that chapter (the registry's ``resolved:``) is decided
as if its status were ``open`` (GM ruling, #530); one with no recorded chapter stays closed. The latest note is the one with the
highest ``first_chapter``, and the last extracted among equals, so Active Plots orders by it.

Guarded by ``tests/test_summary_native_no_llm.py``. The registry is read here and written nowhere in this
package: only ``thread_registry``'s verbs write it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from campaignlib.thread_registry import excluded_notes, included_notes, match_threads, norm_title
from campaignlib.util import atomic_write_text
from pipelines.summary_native import notes, schema

#: The ``attach.json`` value of a note whose name two threads claim.
AMBIGUOUS = "ambiguous"
THREADS_DIR = "threads"
ATTACH_FILE = "attach.json"
#: A latest-note tag that keeps a thread whose registry status is ``open`` open.
OPEN_TAGS = ("OPENED", "ADVANCED")


def threads_dir(range_dir: Path) -> Path:
    """``<range>/state/threads``: the attach map, the proposal prompts and their report."""
    return Path(range_dir) / schema.STATE_DIR / THREADS_DIR


@dataclass
class ThreadState:
    """One ratified thread that has at least one attached note in the range."""

    id: str
    title: str
    #: The registry status as the GM set it (``open`` when absent).
    status: str
    #: Attached notes, in chapter order.
    notes: list[notes.Note]
    #: The attached note with the highest ``first_chapter`` (the last extracted among equals).
    latest: notes.Note
    open: bool
    dormant: bool
    #: Why ``open`` is what it is, in words, for ``threads_report.md``.
    why: str
    #: The thread's position in the registry; breaks ties between equally recent threads.
    order: int = 0


@dataclass
class Attachment:
    #: Every thread note of the range: duplicates removed, in chapter order.
    notes: list[notes.Note]
    #: note id -> the thread id it attached to, ``AMBIGUOUS``, or ``None``.
    by_note: dict[str, str | None]
    #: A name as first written -> the ids of the threads that all claim it.
    ambiguous: dict[str, list[str]]
    #: Threads with notes in the range, in registry order.
    threads: dict[str, ThreadState]
    #: Notes no thread claims (including the ambiguous ones), in chapter order.
    unattached: list[notes.Note]
    #: note id -> the threads whose name matches it but that exclude it (only notes left unattached).
    held_out: dict[str, list[str]] = field(default_factory=dict)

    def _by_recency(self, pick) -> list[ThreadState]:
        found = [s for s in self.threads.values() if pick(s)]
        return sorted(found, key=lambda s: (-s.latest.first_chapter, s.order))

    @property
    def open_threads(self) -> list[ThreadState]:
        """Open ratified threads with notes in the range, newest activity first (Active Plots order)."""
        return self._by_recency(lambda s: s.open)

    @property
    def dormant_threads(self) -> list[ThreadState]:
        """Threads the GM set to ``dormant``, newest activity first (the dormant block)."""
        return self._by_recency(lambda s: s.dormant)

    @property
    def closed_threads(self) -> list[ThreadState]:
        """Resolved or abandoned threads, by status (set at or before the range's last chapter) or by the latest note,
        newest activity first."""
        return self._by_recency(lambda s: not s.open and not s.dormant)


def thread_notes(results: Sequence[notes.CheckedChunk]) -> list[notes.Note]:
    """Every kept thread note, duplicates removed, stably sorted by the chapter of its first citation."""
    seen: set[str] = set()
    out: list[notes.Note] = []
    for r in results:
        for n in r.notes:
            if n.kind != "thread" or n.note_id in seen:
                continue
            seen.add(n.note_id)
            out.append(n)
    return sorted(out, key=lambda n: n.first_chapter)


def _chapter(value) -> int | None:
    """The chapter a registry ``resolved:`` field records, or ``None`` when it is not a real chapter number."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decide(status: str, latest: notes.Note, resolved=None, until: int | None = None) -> tuple[bool, bool, str]:
    """``(open, dormant, why)`` for a thread with this registry status and latest attached note.

    ``resolved`` is the chapter the registry records for a ``resolved`` or ``abandoned`` status and ``until`` the
    last chapter of the build. A build describes the campaign as of ``until``, so a thread the GM closed *after*
    it is decided as if its status were ``open`` (the latest note's tag). Without ``until`` or without a recorded
    chapter, a closed status is closed.
    """
    if status == "dormant":
        return False, True, "the GM set it dormant"
    after = ""
    if status in ("resolved", "abandoned"):
        chapter = _chapter(resolved)
        if chapter is None or until is None:
            return False, False, f"the GM set it {status}" + ("" if chapter is None else f" at ch {chapter}")
        if chapter <= until:
            return False, False, f"the GM set it {status} at ch {chapter}"
        after = f"the GM set it {status} at ch {chapter}, after this range (ch {until})"
    where = f"its latest note (ch {latest.first_chapter}) is {latest.tag}"
    if latest.tag in OPEN_TAGS:
        return True, False, f"{after}: open here, {where}" if after else where
    return False, False, f"{after}, so only its notes decide: {where}" if after else where


def attach(results: Sequence[notes.CheckedChunk], registry: dict | None, until: int | None = None) -> Attachment:
    """Attach the thread notes of ``results`` to the threads of ``registry`` (a loaded registry document).

    An empty, absent (``None``) or thread-less registry attaches nothing: every note is unattached. ``until`` is
    the last chapter of the build; a thread the GM resolved or abandoned after it is open in this range (see
    ``_decide``). A caller with no range leaves it ``None`` and keeps the status as the GM set it.
    """
    registry_threads = list((registry or {}).get("threads") or [])
    data = {"threads": registry_threads}
    index = {t.get("id"): i for i, t in enumerate(registry_threads)}
    all_notes = thread_notes(results)

    pins: dict[str, list[dict]] = {}
    for t in registry_threads:
        for nid in included_notes(t):
            if nid not in excluded_notes(t):  # check_registry rejects both on one thread; the exclusion wins
                pins.setdefault(nid, []).append(t)

    by_note: dict[str, str | None] = {}
    ambiguous: dict[str, list[str]] = {}
    held_out: dict[str, list[str]] = {}
    shown: dict[str, str] = {}  # norm key -> the name as first written
    attached: dict[str, list[notes.Note]] = {}
    for n in all_notes:
        by_note[n.note_id] = None
        if n.note_id in pins:
            found, label, key = pins[n.note_id], n.subject or n.note_id, n.note_id
        else:
            if not n.subject or not norm_title(n.subject):
                continue
            # The GM's "this note is not this thread" beats name identity (#529).
            matched = match_threads(data, n.subject)
            found = [t for t in matched if n.note_id not in excluded_notes(t)]
            if not found and matched:
                held_out[n.note_id] = [t.get("id") for t in matched]
            label, key = n.subject, norm_title(n.subject)
        if len(found) == 1:
            tid = found[0].get("id")
            by_note[n.note_id] = tid
            attached.setdefault(tid, []).append(n)
        elif len(found) > 1:
            by_note[n.note_id] = AMBIGUOUS
            ambiguous[shown.setdefault(key, label)] = [t.get("id") for t in found]

    threads: dict[str, ThreadState] = {}
    for t in registry_threads:
        tid = t.get("id")
        ns = attached.get(tid)
        if not ns:
            continue
        latest = ns[0]
        for n in ns:
            if n.first_chapter >= latest.first_chapter:
                latest = n  # ``>=``: among equals the last extracted wins
        status = t.get("status") or "open"
        is_open, is_dormant, why = _decide(status, latest, t.get("resolved"), until)
        threads[tid] = ThreadState(
            id=tid, title=t.get("title") or tid, status=status, notes=ns, latest=latest,
            open=is_open, dormant=is_dormant, why=why, order=index.get(tid, 0),
        )
    unattached = [n for n in all_notes if by_note[n.note_id] in (None, AMBIGUOUS)]
    return Attachment(all_notes, by_note, ambiguous, threads, unattached, held_out)


# ── Outputs ─────────────────────────────────────────────────────────────────


def _range_of(rng) -> tuple[int, int]:
    if isinstance(rng, str):  # "ch002-004"
        digits = rng.removeprefix("ch").split("-")
        return int(digits[0]), int(digits[1])
    since, until = rng
    return int(since), int(until)


def attach_json(att: Attachment, rng) -> dict:
    """``attach.json``'s content: code's per-run map, deterministic (no timestamp, no absolute path)."""
    since, until = _range_of(rng)
    return {
        "kind": "thread_attach",
        "schema": 1,
        "range": {"since": since, "until": until},
        "counts": {
            "notes": len(att.notes),
            "attached": sum(1 for v in att.by_note.values() if v not in (None, AMBIGUOUS)),
            "ambiguous": sum(1 for v in att.by_note.values() if v == AMBIGUOUS),
            "unattached": len(att.unattached),
            "threads": len(att.threads),
        },
        "notes": dict(sorted(att.by_note.items())),
        "ambiguous": {k: v for k, v in sorted(att.ambiguous.items())},
        "threads": {
            tid: {
                "status": s.status, "open": s.open, "dormant": s.dormant, "latest": s.latest.note_id,
                "notes": [n.note_id for n in s.notes],
            }
            for tid, s in sorted(att.threads.items())
        },
    }


def write_attach(range_dir: Path, att: Attachment, rng) -> Path:
    """Write ``state/threads/attach.json`` and return its path."""
    path = threads_dir(range_dir) / ATTACH_FILE
    atomic_write_text(path, json.dumps(attach_json(att, rng), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def held_out_lines(att: Attachment) -> list[str]:
    """One line per unattached note whose name matches a thread that excludes it (a split's ruling at work)."""
    by_id = {n.note_id: n for n in att.notes}
    return [
        f"ch {by_id[nid].first_chapter} {nid} ({by_id[nid].subject}): its name matches thread "
        f"{', '.join(tids)}, which excludes it (split off); unattached"
        for nid, tids in sorted(att.held_out.items(), key=lambda kv: (by_id[kv[0]].first_chapter, kv[0]))]


def threads_report_md(att: Attachment, rng, detached: Sequence[str] = (), excluded: Sequence[str] = ()) -> str:
    """``threads_report.md``: the ratified threads with notes in the range (open or not, and why), the
    names two threads claim, the ratified proposal members no thread claims any more (``detached``: lines
    from ``thread_check.detached_lines``), the split-off notes an exclusion holds out of a thread that are in no
    range's notes any more, and pinned ones likewise (``excluded``: ``thread_check.ruling_stale_lines``), the notes
    a thread's exclusion holds out by name, and how many notes no thread claims. Deterministic."""
    since, until = _range_of(rng)
    lines = [
        "# Threads report", "",
        f"Thread notes of ch{since:03d}-{until:03d} attached to the GM's ratified threads by exact title or alias.",
        f"{len(att.notes)} thread notes: {len(att.notes) - len(att.unattached)} attached to {len(att.threads)} "
        f"ratified threads, {len(att.unattached)} unattached.",
        "", "## Ratified threads with notes in this range", "",
    ]
    if not att.threads:
        lines.append(schema.NO_RATIFIED_THREADS)
    for s in sorted(att.threads.values(), key=lambda s: (-s.latest.first_chapter, s.order)):
        state = "open" if s.open else "dormant" if s.dormant else "closed"
        lines.append(
            f"- **{s.title}** (`{s.id}`): {state} — {s.why}; {len(s.notes)} note(s), latest ch {s.latest.first_chapter}")
    lines += ["", "## Ambiguous names (claimed by more than one thread, left unattached)", ""]
    if att.ambiguous:
        lines += [f"- {name}: {', '.join(f'`{t}`' for t in ids)}" for name, ids in sorted(att.ambiguous.items())]
    else:
        lines.append("- (none)")
    lines += ["", "## Ratified but no longer attached (alias removed?)", ""]
    lines += [f"- {ln}" for ln in detached] or ["- (none)"]
    lines += ["", f"## {schema.STALE_RULINGS_HEADING}", ""]
    lines += [f"- {ln}" for ln in excluded] or ["- (none)"]
    lines += ["", f"## {schema.HELD_OUT_HEADING}", ""]
    lines += [f"- {ln}" for ln in held_out_lines(att)] or ["- (none)"]
    lines += ["", "## Unattached", "", f"{len(att.unattached)} unattached thread note(s).", ""]
    return "\n".join(lines)
