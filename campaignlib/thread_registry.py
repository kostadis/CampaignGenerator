"""The thread registry's read side: identity matching and validation (spec 034 T002).

Moved out of ``pipelines/grounding/thread_registry.py`` so a pipeline that only needs to *read*
the GM's registry (``pipelines/summary_native``) does not import a CLI module. The CLI re-imports
every name here; there is one definition of each.

Identity is exact: a title or alias matches a name when their ``norm_title`` keys are equal.
Never similarity. No model call.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

STATUSES = ("open", "dormant", "resolved", "abandoned")
CHANGES = ("opened", "advanced", "resolved", "reopened", "abandoned")


def norm_title(title: str) -> str:
    """'Aletra's Boss' -> 'aletras-boss'. Exact-match key; never similarity."""
    t = title.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def group_key(member_ids) -> str:
    """The key of a group proposal: ``g-`` + the first 12 hex of the sha1 of its sorted member ids (spec 034, R5).

    Stable for an identical grouping, so a ruling recorded against it persists across runs. Declared here
    because the proposal step (``summary_native thread-propose``) and the ratify verb (``thread_registry``,
    which names the remainder of a split) must agree on it.
    """
    return "g-" + hashlib.sha1("|".join(sorted(member_ids)).encode("utf-8")).hexdigest()[:12]


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "threads": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("version", 1)
    data.setdefault("threads", [])
    return data


def find_thread(data: dict, thread_id: str) -> dict | None:
    for t in data["threads"]:
        if t.get("id") == thread_id:
            return t
    return None


def match_threads(data: dict, title: str) -> list[dict]:
    """Every thread whose title or alias equals ``title`` after ``norm_title``, in registry order.

    More than one result means the name is ambiguous: callers report it and never pick one.
    """
    key = norm_title(title)
    found: list[dict] = []
    for t in data["threads"]:
        names = [t.get("title", "")] + list(t.get("aliases") or [])
        if any(norm_title(n) == key for n in names if n):
            found.append(t)
    return found


def _note_ids(thread: dict, field: str) -> list[str]:
    raw = thread.get(field)
    return [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []


def excluded_notes(thread: dict) -> list[str]:
    """The note ids the GM ruled are not this thread (``excluded_notes``, #529); ``[]`` when none.

    Written by ``thread_registry ratify --key`` when a group is split: the notes left out of the ratified
    subset. An attachment by name never overrides it. Optional and additive, so an older registry has none.
    """
    return _note_ids(thread, "excluded_notes")


def included_notes(thread: dict) -> list[str]:
    """The note ids pinned to this thread (``included_notes``, #529); ``[]`` when none.

    Written by ``ratify --key`` for a ratified member whose name cannot attach it to the thread by name (the name
    is another thread's, or this ratification did not make it an alias). A pinned id attaches to the thread by id,
    before any name is compared. Optional and additive.
    """
    return _note_ids(thread, "included_notes")


def match_thread(data: dict, title: str) -> dict | None:
    """Exact normalised title/alias match against the registry (the first, when several match)."""
    found = match_threads(data, title)
    return found[0] if found else None


def check_registry(data: dict) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_norms: dict[str, str] = {}
    for t in data["threads"]:
        tid = t.get("id") or ""
        if not tid:
            errors.append(f"thread with no id (title {t.get('title')!r})")
        elif tid in seen_ids:
            errors.append(f"duplicate thread id {tid!r}")
        seen_ids.add(tid)
        if t.get("status") not in STATUSES:
            errors.append(f"{tid}: bad status {t.get('status')!r} "
                          f"(allowed: {', '.join(STATUSES)})")
        if t.get("status") in ("resolved", "abandoned") and not t.get("resolved"):
            errors.append(f"{tid}: status {t['status']} but no `resolved:` chapter")
        for name in [t.get("title", "")] + list(t.get("aliases") or []):
            if not name:
                continue
            key = norm_title(name)
            if key in seen_norms and seen_norms[key] != tid:
                errors.append(f"{tid}: title/alias {name!r} collides with "
                              f"thread {seen_norms[key]!r}")
            seen_norms[key] = tid
        for field in ("excluded_notes", "included_notes"):
            ids = t.get(field)
            if ids is not None and (not isinstance(ids, list) or not all(isinstance(x, str) and x for x in ids)):
                errors.append(f"{tid}: {field} must be a list of note ids ({ids!r})")
        both = sorted(set(excluded_notes(t)) & set(included_notes(t)))
        if both:
            errors.append(f"{tid}: note(s) {', '.join(both)} are both in excluded_notes and included_notes")
        for row in t.get("log") or []:
            if row.get("change") not in CHANGES:
                errors.append(f"{tid}: bad log change {row.get('change')!r}")
            if not isinstance(row.get("chapter"), int) or row["chapter"] < 1:
                errors.append(f"{tid}: log row without a real chapter number "
                              f"({row.get('chapter')!r})")
    return errors
