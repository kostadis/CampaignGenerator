"""The code check on a model's thread groupings, and the proposals file they are merged into (spec 034, R5).

``summary_native thread-propose`` asks a model to group the unattached thread notes. What the model
returns is a suggestion and nothing more: this module decides what survives, so no grouping reaches the GM
that names a note that is not there, claims a note twice, or continues a thread the registry does not have.
A note the model leaves out (or that the check takes out) is never lost: it is offered as a single-note
proposal. Deterministic, no model call; guarded by ``tests/test_summary_native_no_llm.py``.

A proposal is a *group entry* in the proposals file::

    key: g-<12 hex>      # campaignlib.thread_registry.group_key of the sorted member ids
    kind: new | continues | single
    title: ...           # new and single: a suggestion the GM edits
    thread: <id>         # continues only
    members: [{id, chapter, tag, name, text, cite}]
    status: pending | ratified | rejected | deferred
    source: summary_native ch002-070 run <run id>

Group entries sit beside the ensemble harvest's name-keyed entries (``norm``); neither shape touches the
other. This module never reads or writes the thread registry itself beyond the loaded document it is given.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from campaignlib.thread_registry import group_key
from campaignlib.util import atomic_write_text
from pipelines.summary_native import notes, schema

#: A report line that records something removed from a proposal. ``thread-propose`` counts them.
DROPPED = "dropped"
#: A report line that records something kept but changed.
NOTE = "note"
#: Group statuses the GM has ruled; a ruling is preserved by key.
RULED = ("ratified", "rejected", "deferred")
#: What a model may propose; ``single`` is code's.
MODEL_KINDS = ("new", "continues")

PROPOSALS_NOTE = (
    "Proposals, not canon. Name-keyed entries (`norm`) come from the ensemble harvest; group entries (`key`, "
    "`g-...`) come from `summary_native thread-propose`. A GM ruling is preserved across re-proposes. Ratify on "
    "the Threads page (/grounding/threads) or with the thread_registry verbs."
)

_PREFIX_RE = re.compile(r"^-\s*\[[A-Z]+\]\s*\*\*.+?\*\*\s*[—–:-]*\s*")
_FENCE_RE = re.compile(r"^```[A-Za-z]*\s*(.*?)\s*```$", re.S)


class ThreadJsonError(ValueError):
    """The model's output is not the JSON object the proposal prompt asks for."""


# ── Notes as members ────────────────────────────────────────────────────────


def note_name(n: notes.Note) -> str:
    return (n.subject or "").strip()


def note_body(n: notes.Note) -> str:
    """The note without its tag, its bold name and its citations: the statement itself."""
    text = _PREFIX_RE.sub("", n.text.strip(), count=1)
    text = schema.STATE_CITE_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def note_cite(n: notes.Note) -> str:
    """The citation bracket(s) of the note, once each, in text order."""
    return " ".join(dict.fromkeys(b for b, _, _ in notes.cites(n.text)))


def member_of(n: notes.Note) -> dict:
    return {
        "id": n.note_id, "chapter": n.first_chapter, "tag": n.tag or "", "name": note_name(n),
        "text": note_body(n), "cite": note_cite(n),
    }


# ── Parsing ─────────────────────────────────────────────────────────────────


def parse_groups(raw) -> list:
    """The ``groups`` list of the model's output (text, or an already parsed object).

    A single markdown fence round the object is tolerated; nothing else is repaired. Raises
    ``ThreadJsonError`` for text that is not a JSON object with a ``groups`` list.
    """
    obj = raw
    if isinstance(raw, str):
        text = raw.strip()
        m = _FENCE_RE.match(text)
        if m:
            text = m.group(1)
        try:
            obj = json.loads(text)
        except ValueError as e:
            raise ThreadJsonError(f"not valid JSON ({e})") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("groups"), list):
        raise ThreadJsonError('not a JSON object with a "groups" list')
    return obj["groups"]


# ── What the model is offered ───────────────────────────────────────────────


def group_entries(prior: Sequence | None) -> list[dict]:
    """The group entries of a proposals list (name-keyed ensemble entries are not ours)."""
    return [p for p in prior or () if isinstance(p, dict) and p.get("key")]


def _member_ids(entry: Mapping) -> list[str]:
    return [m.get("id") for m in entry.get("members") or () if isinstance(m, Mapping) and m.get("id")]


def excluded_ids(prior: Sequence | None) -> tuple[set[str], set[str]]:
    """``(rejected, deferred)``: member ids of the groups the GM rejected, and of those they deferred."""
    rejected: set[str] = set()
    deferred: set[str] = set()
    for p in group_entries(prior):
        if p.get("status") == "rejected":
            rejected.update(_member_ids(p))
        elif p.get("status") == "deferred":
            deferred.update(_member_ids(p))
    return rejected, deferred


def ratified_ids(prior: Sequence | None) -> set[str]:
    """Member ids of the groups the GM ratified."""
    return {i for p in group_entries(prior) if p.get("status") == "ratified" for i in _member_ids(p)}


def offered(unattached: Sequence[notes.Note], prior: Sequence | None) -> list[notes.Note]:
    """The unattached notes a model may group: not the members of a rejected, a deferred or a ratified group.

    A ratified member that is *unattached* lost its alias after the ratification (see :func:`detached`); it is
    offered again as a single-note proposal by code, not regrouped by the model.
    """
    rejected, deferred = excluded_ids(prior)
    ratified = ratified_ids(prior)
    return [n for n in unattached if n.note_id not in rejected | deferred | ratified]


# ── The check ───────────────────────────────────────────────────────────────


def check_groups(
    raw,
    unattached: Sequence[notes.Note],
    registry: dict | None,
    prior: Sequence | None,
    *,
    attached: Mapping[str, str] | None = None,
) -> tuple[list[dict], list[str]]:
    """Check a model's grouping of ``unattached`` and return ``(groups, report_lines)``.

    ``raw`` is the model's output as text or as a parsed ``{"groups": [...]}``; ``registry`` the loaded
    thread registry; ``prior`` the proposals already in the file (rulings decide what is offered);
    ``attached`` an optional ``{note id: thread id}`` so a removed member can be reported as attached.

    In order, each of these is removed and reported:

    * a group of an unknown kind, or whose members are not a list of ids;
    * a ``continues`` group whose thread is not in the registry;
    * a member that is not an offered, unattached checked note (unknown, attached, or excluded by a ruling,
      a ratified group's members included: those are :func:`detached` and offered on their own);
    * a member claimed by two groups, which leaves **both**;
    * a group left with no members.

    A group left with exactly one member becomes ``single``. Every unattached note in no valid group becomes
    a ``single`` proposal, the members of rejected groups included (re-offered one by one) and those of
    deferred groups excluded (they live in the deferred entry). Output is in chapter order, members too.
    """
    ordered = sorted(unattached, key=lambda n: n.first_chapter)  # stable
    position = {n.note_id: i for i, n in enumerate(ordered)}
    by_id = {n.note_id: n for n in ordered}
    rejected, deferred = excluded_ids(prior)
    ratified = ratified_ids(prior)
    # A ratified single's key is the key of the same note offered again, and a key must name one entry.
    taken = {p["key"] for p in group_entries(prior) if p.get("status") == "ratified"}
    can_group = {n.note_id for n in offered(ordered, prior)}
    registry_ids = {t.get("id") for t in (registry or {}).get("threads") or ()}
    attached = attached or {}
    lines: list[str] = []

    try:
        raw_groups = parse_groups(raw)
    except ThreadJsonError as e:
        raw_groups = []
        lines.append(f"{DROPPED} the model's output: {e}; every offered note becomes a single-note proposal")

    valid: list[dict] = []
    for i, g in enumerate(raw_groups, 1):
        label = f"group {i}"
        if not isinstance(g, dict):
            lines.append(f"{DROPPED} {label}: not an object")
            continue
        kind = g.get("kind")
        title = str(g.get("title") or "").strip()
        if title:
            label += f" ({title})"
        if kind not in MODEL_KINDS:
            lines.append(f"{DROPPED} {label}: unknown kind {kind!r} (allowed: {', '.join(MODEL_KINDS)})")
            continue
        members = g.get("members")
        if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
            lines.append(f"{DROPPED} {label}: members is not a list of note ids")
            continue
        thread = None
        if kind == "continues":
            thread = g.get("thread")
            if thread not in registry_ids:
                lines.append(f"{DROPPED} {label}: continues thread {thread!r}, which is not in the registry")
                continue
        kept: list[str] = []
        for mid in dict.fromkeys(members):  # a repeated id counts once
            if mid in can_group:
                kept.append(mid)
            elif mid in rejected:
                lines.append(f"{DROPPED} {label} member {mid}: it was in a group the GM rejected, so it was not offered")
            elif mid in deferred:
                lines.append(f"{DROPPED} {label} member {mid}: it is in a group the GM deferred, so it was not offered")
            elif mid in ratified:
                lines.append(f"{DROPPED} {label} member {mid}: it is in a ratified group but no longer attached "
                             "(alias removed?), so it was not offered to the model; it is offered on its own")
            elif mid in attached:
                lines.append(f"{DROPPED} {label} member {mid}: already attached to thread {attached[mid]!r}")
            else:
                lines.append(f"{DROPPED} {label} member {mid}: not an unattached checked thread note of this run")
        if not kept:
            lines.append(f"{DROPPED} {label}: no valid members left")
            continue
        valid.append({"index": i, "label": label, "kind": kind, "title": title, "thread": thread, "ids": kept})

    claims: dict[str, list[int]] = {}
    for v in valid:
        for mid in v["ids"]:
            claims.setdefault(mid, []).append(v["index"])
    for mid, groups_claiming in sorted(claims.items(), key=lambda kv: position[kv[0]]):
        if len(groups_claiming) > 1:
            lines.append(
                f"{DROPPED} member {mid}: claimed by groups {' and '.join(str(g) for g in groups_claiming)}; "
                "removed from both and offered on its own"
            )
    doubled = {mid for mid, gs in claims.items() if len(gs) > 1}

    groups: list[dict] = []
    used: set[str] = set()
    for v in valid:
        ids = sorted((m for m in v["ids"] if m not in doubled), key=position.__getitem__)
        if not ids:
            lines.append(f"{DROPPED} {v['label']}: no members left once the double-claimed notes were removed")
            continue
        used.update(ids)
        members = [member_of(by_id[m]) for m in ids]
        if len(ids) == 1:
            if v["ids"] == ids:
                lines.append(f"{NOTE} {v['label']}: one member, so it is a single-note proposal")
            groups.append(_single(members[0], v["title"]))
            continue
        entry = {"key": group_key(ids), "kind": v["kind"]}
        if v["kind"] == "new":
            entry["title"] = v["title"] or members[0]["name"] or members[0]["text"][:60]
        else:
            entry["thread"] = v["thread"]
        entry["members"] = members
        groups.append(entry)

    for n in ordered:
        if n.note_id in used or n.note_id in deferred:
            continue
        groups.append(_single(member_of(n), "", taken))

    groups.sort(key=lambda g: (position[g["members"][0]["id"]], g["key"]))
    return groups, lines


def _single(member: dict, title: str, taken=()) -> dict:
    """A single-note proposal; its key is ``group_key([id])`` unless ``taken`` already holds that key."""
    key, n = group_key([member["id"]]), 1
    while key in taken:
        key, n = group_key([member["id"], f"re-offered-{n}"]), n + 1
    return {
        "key": key, "kind": "single",
        "title": title or member.get("name") or (member.get("text") or "")[:60] or member["id"], "members": [member],
    }


def stale_ratified(prior: Sequence | None, note_ids: set[str], since: int, until: int) -> list[str]:
    """Report lines for ratified groups whose members (chapters in ``since``..``until``) no longer exist.

    Re-extraction that changes a note's text changes its id (research R6). The ratified thread's aliases
    still attach any note that repeats a name, so this is a notice, not a fault.
    """
    out: list[str] = []
    for p in group_entries(prior):
        if p.get("status") != "ratified":
            continue
        gone = [
            m["id"] for m in p.get("members") or ()
            if isinstance(m, Mapping) and m.get("id") and isinstance(m.get("chapter"), int)
            and since <= m["chapter"] <= until and m["id"] not in note_ids
        ]
        if gone:
            out.append(
                f"stale: ratified group {p['key']} ({p.get('title') or p.get('ruled_thread') or 'untitled'}): "
                f"member(s) {', '.join(gone)} no longer exist after re-extraction; the thread's aliases still "
                "attach any note that repeats a name"
            )
    return out


def detached(prior: Sequence | None, unattached: Sequence[notes.Note]) -> list[dict]:
    """Ratified members that exist in this run's notes but attach to no thread: ``[{note, groups}]``.

    Ratifying adds every member's name as an alias, so such a member was attached once and lost its alias
    since (removed by hand or by ``thread_registry alias``). Only a note of this run can be judged: its
    attachment is known. A member outside the run's range (or gone from disk) is left alone here.
    """
    holders: dict[str, list[dict]] = {}
    for p in group_entries(prior):
        if p.get("status") == "ratified":
            for i in _member_ids(p):
                holders.setdefault(i, []).append(p)
    return [{"note": n, "groups": holders[n.note_id]}
            for n in sorted(unattached, key=lambda n: n.first_chapter) if n.note_id in holders]


def detached_lines(prior: Sequence | None, found: Sequence[dict]) -> list[str]:
    """One report line per :func:`detached` note, saying what became of it in ``prior`` (the current file)."""
    out = []
    for d in found:
        n = d["note"]
        was = " and ".join(
            f"{p['key']} ({p.get('title') or p.get('ruled_thread') or 'untitled'}"
            + (f" → thread {p['ruled_thread']}" if p.get("ruled_thread") else "") + ")"
            for p in d["groups"])
        holding = [p for p in group_entries(prior) if p.get("status") != "ratified" and n.note_id in _member_ids(p)]
        pending = next((p for p in holding if p.get("status", "pending") == "pending"), None)
        if pending:
            fate = f"offered again as pending proposal {pending['key']}"
        elif holding:
            fate = f"its proposal {holding[0]['key']} is {holding[0].get('status')}, so it is not offered again"
        else:
            fate = "run `summary_native thread-propose` to offer it again"
        out.append(f"ch {n.first_chapter} {n.note_id} ({note_name(n) or 'no name'}): ratified but no longer attached "
                   f"(alias removed?) — a member of ratified group {was}; {fate}")
    return out


def now_attached_lines(prior: Sequence | None, attached: Mapping[str, str], titles: Mapping[str, str]) -> list[str]:
    """Report lines for pending proposals every note of which now attaches to a ratified thread.

    The merge drops such a proposal (its notes are in the run and attached); this says so. ``attached`` is
    ``{note id: thread id}`` for this run's notes.
    """
    out = []
    for p in group_entries(prior):
        ids = _member_ids(p)
        if p.get("status", "pending") == "pending" and ids and all(i in attached for i in ids):
            names = ", ".join(sorted({titles.get(attached[i]) or attached[i] for i in ids}))
            out.append(f"pending proposal {p['key']} ({p.get('title') or p.get('thread') or 'untitled'}): now attached "
                       f"to {names}; dropped from the queue")
    return out


# ── The proposals file ──────────────────────────────────────────────────────


def _load(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"{path}: not valid YAML ({e})") from None
    if doc is None:
        return {}
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a mapping with a `proposals` list")
    return doc


def load_proposals(path: Path) -> list:
    """Every entry of the proposals file, name-keyed and group entries alike; ``[]`` when absent.

    Raises ``ValueError`` for a file that is not YAML.
    """
    return list(_load(path).get("proposals") or [])


def merge_proposals(
    path: Path, groups: Sequence[dict], source: str, scope_ids=None, known_ids=None,
) -> dict:
    """Merge ``groups`` into the proposals file at ``path`` and write it atomically.

    * name-keyed (``norm``) entries and every ruled group entry (by ``key``) are kept exactly as they are;
    * a pending group entry is replaced when it shares a note with this run (``scope_ids``, default the
      members of ``groups``): the run regenerates its notes' proposals;
    * a member of a replaced group that lies outside this run's scope (an earlier run covered a wider range)
      is never orphaned: unless another entry already holds it, it is kept as a pending ``single`` proposal
      that keeps the group's ``source``;
    * ``known_ids`` is every thread-note id of every range's checked notes (``None``: not known, nothing is
      judged gone). An id is per extraction, so only an id in *no* range's notes names a note that no longer
      exists: such a member of a replaced group is dropped and reported in full (``gone``), so it can be
      recovered from the report; a pending entry none of whose members is in any range's notes is **kept
      untouched** and reported (``stale``) — the GM re-extracts that range or rejects the entry;
    * a new group whose key is already a ruled entry is not added again (the ruling stands);
    * every other new group is added ``pending`` with ``source``.

    Returns counts: ``pending`` (group entries pending after the merge), ``added``, ``replaced``, ``ruled``;
    ``kept_out_of_range`` (one ``{key, title, members}`` per replaced group that left members as singles) and
    ``gone`` (one ``{key, title, members}`` per replaced group, ``members`` the dropped member dicts in full)
    and ``stale`` (one ``{key, title, ids}`` per kept pending entry no member of which is in any range's notes).
    """
    doc = _load(path)
    existing = list(doc.get("proposals") or [])
    scope = set(scope_ids or ()) | {m["id"] for g in groups for m in g["members"]}
    ruled_keys = {
        p["key"] for p in existing if isinstance(p, dict) and p.get("key") and p.get("status") in RULED
    }
    living = None if known_ids is None else set(known_ids) | scope
    replaced_at: dict[int, dict] = {}
    stale_at: dict[int, dict] = {}
    for i, p in enumerate(existing):
        if isinstance(p, dict) and p.get("key") and p.get("status", "pending") == "pending":
            ids = _member_ids(p)
            if scope & set(ids):
                replaced_at[i] = p
            elif living is not None and ids and not living & set(ids):
                stale_at[i] = p
    kept = [p for i, p in enumerate(existing) if i not in replaced_at]
    added = [{**g, "status": "pending", "source": source} for g in groups if g["key"] not in ruled_keys]
    held = {i for e in [*kept, *added] if isinstance(e, dict) and e.get("key") for i in _member_ids(e)}

    # The singles take the place of the group they came from, so a second identical run is a fixed point.
    saved_at: dict[int, list[dict]] = {}
    kept_report: list[dict] = []
    gone_report: list[dict] = []
    for idx, p in replaced_at.items():
        title = p.get("title") or p.get("thread") or p["key"]
        saved: list[dict] = []
        gone: list[dict] = []
        for m in p.get("members") or ():
            if not isinstance(m, Mapping) or not m.get("id") or m["id"] in scope or m["id"] in held:
                continue
            if living is not None and m["id"] not in living:
                gone.append(dict(m))
                continue
            held.add(m["id"])
            saved.append(m)
        if saved:
            saved_at[idx] = [
                {**_single(dict(m), ""), "status": "pending", "source": p.get("source") or source} for m in saved]
            kept_report.append({"key": p["key"], "title": title, "members": saved})
        if gone:
            gone_report.append({"key": p["key"], "title": title, "members": gone})
    stale_report = [
        {"key": p["key"], "title": p.get("title") or p.get("thread") or p["key"], "ids": _member_ids(p)}
        for p in stale_at.values()]
    merged: list = []
    for i, p in enumerate(existing):
        if i in replaced_at:
            merged.extend(saved_at.get(i, ()))
        else:
            merged.append(p)
    merged.extend(added)
    out = dict(doc) if doc else {"note": PROPOSALS_NOTE}
    out["proposals"] = merged
    atomic_write_text(path, yaml.safe_dump(out, sort_keys=False, allow_unicode=True, width=100))
    return {
        "pending": sum(1 for p in merged if isinstance(p, dict) and p.get("key") and p.get("status", "pending") == "pending"),
        "added": len(added),
        "replaced": len(replaced_at),
        "ruled": len(ruled_keys),
        "kept_out_of_range": kept_report,
        "gone": gone_report,
        "stale": stale_report,
    }
