#!/usr/bin/env python3
"""Thread registry: the authored store for narrative threads (#213 Phase 3).

Closes issue #154. Until now threads existed only as a per-run render of
free-text-keyed `thread` facts (`docs/ensemble/threads.md`): no identity
("Aletra's boss" and "Aletra's mysterious boss" were two threads), no
lifecycle, every entry stamped `[ch00]`. This tool gives threads the same
treatment entities got in `docs/entity_registry.yaml`:

- **`docs/thread_registry.yaml`** — the authored store. Thread identity,
  status, and every log row enter ONLY through GM ratification (the
  validated verbs below, or the thread-triage skill driving them). Statuses,
  per the GM ruling on the #213 anchor: ``open | dormant | resolved |
  abandoned`` — open-vs-dormant is the split planning renders care about.
  Arc scores are NOT threads (separate GM-owned trackers); a thread may
  carry an optional ``tracker:`` link to one.
- **`propose`** — deterministic, no LLM. The extraction lenses already emit
  `thread`-typed facts with quotes; this harvests them per chapter, groups
  by normalised title, matches against the registry by exact normalised
  title/alias (never similarity — that is what aliasing decisions are for),
  and writes ``docs/ensemble/thread_proposals.yaml`` with everything
  ``status: pending``. GM rulings are preserved across re-proposes —
  ``rejected``/``deferred`` are a one-way door; a ``ratified`` candidate is
  re-offered when LATER chapters mention it, so accepting a thread at ch41
  cannot hide ch50-60 of it (research D17b).

  **Proposals ARE read downstream**, contrary to what this docstring and the
  file's own preamble used to claim: ``SPECS["planning"]`` declares
  ``Section("emerging", source="thread_proposals")``, so the planning
  document renders the pending queue and every ruling marks that section
  stale via ``inputs_sha``.
- **`render`** — projects the registry into markdown for the grounding
  docs. Chapters come from ratified log rows (real integers from the
  Phase-0 canonical numbering), so the `[ch00]` class cannot occur; one
  thread per id, so the duplicate-thread class cannot occur.

Two surfaces, deliberately separated (GM direction, 2026-07-31):

- **Canon** — the registry + `propose`/verbs/`render`. Deterministic, zero
  model calls, GM-gated. Everything above.
- **Speculation** — `speculate`, the one LLM pass, and the one place in
  this toolchain where the model seeing connections that may not exist is
  the assignment: it free-associates over the registry + harvested
  evidence and writes idea material to `notes/` (the staging area — per
  the workspace rule, nothing enters canon from notes without the GM).
  Inspiration surface only; no pipeline reads it.

Nothing here decides thread identity.

Usage (from inside a campaign dir):

  thread_registry.py propose --corpus 'docs/ensemble/per_chapter/*/merged.json'
  thread_registry.py add --id carver-march --title "The Carver's march" --opened 30
  thread_registry.py log --id carver-march --chapter 40 --change advanced \\
      --summary "..." --quote "..."
  thread_registry.py set-status --id carver-march --status resolved --chapter 46
  thread_registry.py render --output docs/ensemble/threads_registry.md
  thread_registry.py check
"""
import argparse
import glob
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from campaignlib.util import atomic_write_text

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib.constants import config_path
from campaignlib.projection_config import (
    PROJECTION_CONFIG_FILENAME,
    load_projection_config,
)

STATUSES = ("open", "dormant", "resolved", "abandoned")
CHANGES = ("opened", "advanced", "resolved", "reopened", "abandoned")

CHAP = re.compile(r"(?:chapter|session|ch|gen-ch)[_-]?0*(\d+)", re.I)


def chapter_of(path: str) -> int | None:
    for seg in reversed(Path(path).parts):
        m = CHAP.search(seg)
        if m:
            return int(m.group(1))
    return None


def norm_title(title: str) -> str:
    """'Aletra's Boss' -> 'aletras-boss'. Exact-match key; never similarity."""
    t = title.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


# ── registry io ──────────────────────────────────────────────────────────

def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "threads": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("version", 1)
    data.setdefault("threads", [])
    return data


def save_registry(path: Path, data: dict) -> None:
    # Atomic (research D12). The web surface turns hand-typed invocations into
    # rapid button presses; a torn canon file is not an acceptable failure mode.
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False,
                                           allow_unicode=True))


def find_thread(data: dict, thread_id: str) -> dict | None:
    for t in data["threads"]:
        if t.get("id") == thread_id:
            return t
    return None


def match_thread(data: dict, title: str) -> dict | None:
    """Exact normalised title/alias match against the registry."""
    key = norm_title(title)
    for t in data["threads"]:
        names = [t.get("title", "")] + list(t.get("aliases") or [])
        if any(norm_title(n) == key for n in names if n):
            return t
    return None


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
        for row in t.get("log") or []:
            if row.get("change") not in CHANGES:
                errors.append(f"{tid}: bad log change {row.get('change')!r}")
            if not isinstance(row.get("chapter"), int) or row["chapter"] < 1:
                errors.append(f"{tid}: log row without a real chapter number "
                              f"({row.get('chapter')!r})")
    return errors


# ── propose (deterministic harvest of thread facts) ──────────────────────

def harvest(corpus_globs: list[str]) -> dict[str, dict]:
    """Group thread-typed facts by normalised title across the corpus."""
    files = sorted({f for g in corpus_globs for f in glob.glob(g)})
    if not files:
        raise SystemExit(f"no files matched: {corpus_globs}")
    groups: dict[str, dict] = {}
    for f in files:
        ch = chapter_of(f)
        for fa in json.loads(Path(f).read_text(encoding="utf-8")):
            if fa.get("type") != "thread":
                continue
            title = (fa.get("subject") or "").strip()
            text = (fa.get("fact") or "").strip()
            if not title or not text:
                continue
            key = norm_title(title)
            g = groups.setdefault(key, {"title": title, "titles": set(),
                                        "chapters": set(), "evidence": []})
            g["titles"].add(title)
            if ch:
                g["chapters"].add(ch)
            ev = {"chapter": ch, "fact": text}
            if fa.get("quote_verified") and fa.get("source_quote"):
                ev["quote"] = fa["source_quote"]
            if fa.get("source"):
                ev["source"] = fa["source"].get("kind")
            g["evidence"].append(ev)
    return groups


def load_prior_rulings(path: Path) -> dict[str, dict]:
    """{norm: proposal} for every proposal a GM has already ruled on."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {p["norm"]: p for p in data.get("proposals") or []
            if isinstance(p, dict) and p.get("norm")
            and p.get("status") in ("ratified", "rejected", "deferred")}


def propose(corpus_globs: list[str], registry_path: Path, out: Path,
            min_chapters: int = 1, min_evidence: int = 1) -> tuple[int, int]:
    """Harvest -> proposals. `min_chapters`/`min_evidence` default to 1, which
    is today's behaviour: nothing is dropped. They exist so a CLI user can
    narrow a 986-candidate harvest by hand — NOT so the product ships a default
    that hides 97% of it, which would be software making a scope decision
    (research D15). The web surface never sends them; it filters the view and
    states the hidden count instead."""
    registry = load_registry(registry_path)
    prior = load_prior_rulings(out)
    groups = harvest(corpus_globs)

    proposals = []
    pending = 0
    for key in sorted(groups):
        g = groups[key]
        ruled = prior.get(key)
        # A rejection is a one-way door; an acceptance is not (research D17b).
        # `rejected`/`deferred` short-circuit as before. A `ratified` candidate
        # falls THROUGH to the matches/logged filter below, so later chapters of
        # a thread the GM already accepted keep surfacing — without this,
        # ratifying at ch41 hides ch50-60 of that same thread forever and
        # FR-009 is unreachable through the surface.
        if ruled and ruled.get("status") in ("rejected", "deferred"):
            proposals.append(ruled)
            continue
        matched = match_thread(registry, g["title"])
        if matched is None and ruled and ruled.get("ruled_thread"):
            # The ratification's own thread, even if its title was edited away
            # from the harvested one during ratification.
            matched = find_thread(registry, ruled["ruled_thread"])
        # Already-logged chapters on a matched thread are not re-proposed.
        logged = {r.get("chapter") for r in (matched.get("log") or [])} if matched else set()
        fresh_chapters = sorted(c for c in g["chapters"] if c not in logged)
        if matched and not fresh_chapters:
            # Nothing new to offer. If the GM ruled on this candidate, KEEP the
            # ruling in the file rather than dropping the row: the record is
            # what makes the ruling survive (SC-006), and dropping it also
            # loses the `ratified` marker, so a later chapter would re-offer
            # the candidate as brand new carrying its already-logged chapters
            # — inviting duplicate log rows for chapters that are already canon.
            if ruled:
                proposals.append(ruled)
            continue
        if len(g["chapters"]) < min_chapters or len(g["evidence"]) < min_evidence:
            continue
        proposal = {
            "norm": key,
            "title": g["title"],
            "all_titles": sorted(g["titles"]),
            "matches": matched.get("id") if matched else None,
            # A re-offer AFTER ratification carries only the unlogged
            # chapters — the GM already logged the rest, and re-proposing them
            # invites duplicate log rows (FR-009a). An ordinary matched
            # candidate the GM has not ruled on keeps its full span, which is
            # long-standing behaviour and what test_thread_registry.py pins.
            "chapters": (fresh_chapters
                         if (matched and ruled and ruled.get("status") == "ratified")
                         else sorted(g["chapters"])),
            "status": "pending",
            "evidence": sorted(g["evidence"],
                               key=lambda e: (e.get("chapter") or 0, e["fact"]))[:8],
        }
        if ruled and ruled.get("ruled_thread"):
            proposal["ruled_thread"] = ruled["ruled_thread"]
        proposals.append(proposal)
        pending += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, yaml.safe_dump(
        {"note": ("Proposals, not canon — but this file IS read downstream: "
                  "the planning document's `emerging` section renders the "
                  "pending queue, so every ruling marks it stale. A GM ruling "
                  "is preserved across re-proposes (rejected/deferred are a "
                  "one-way door; a ratified candidate returns when later "
                  "chapters mention it). Ratify on the Threads page "
                  "(/grounding/threads) or with the thread_registry verbs."),
         "proposals": proposals},
        sort_keys=False, allow_unicode=True, width=100))
    return len(proposals), pending


# ── verbs (the validated writers the GM's ratification drives) ───────────

def cmd_add(data: dict, args) -> None:
    if find_thread(data, args.id):
        raise SystemExit(f"error: thread id {args.id!r} already exists")
    clash = match_thread(data, args.title)
    if clash:
        raise SystemExit(f"error: title {args.title!r} matches existing thread "
                         f"{clash['id']!r} — use `log`/`alias` on it instead")
    if args.status not in STATUSES:
        raise SystemExit(f"error: bad status {args.status!r}")
    t = {"id": args.id, "title": args.title, "status": args.status,
         "opened": args.opened, "resolved": None,
         "tracker": args.tracker, "aliases": [], "notes": args.notes or "",
         "log": []}
    data["threads"].append(t)


def cmd_log(data: dict, args) -> None:
    t = find_thread(data, args.id)
    if not t:
        raise SystemExit(f"error: no thread {args.id!r}")
    if args.change not in CHANGES:
        raise SystemExit(f"error: bad change {args.change!r}")
    row = {"chapter": args.chapter, "change": args.change,
           "summary": args.summary}
    if args.quote:
        row["quote"] = args.quote
    t.setdefault("log", []).append(row)
    t["log"].sort(key=lambda r: (r.get("chapter", 0), r.get("change", "")))


def cmd_set_status(data: dict, args) -> None:
    t = find_thread(data, args.id)
    if not t:
        raise SystemExit(f"error: no thread {args.id!r}")
    if args.status not in STATUSES:
        raise SystemExit(f"error: bad status {args.status!r}")
    t["status"] = args.status
    if args.status in ("resolved", "abandoned"):
        if not args.chapter:
            raise SystemExit("error: resolving/abandoning needs --chapter")
        t["resolved"] = args.chapter


def cmd_alias(data: dict, args) -> None:
    t = find_thread(data, args.id)
    if not t:
        raise SystemExit(f"error: no thread {args.id!r}")
    clash = match_thread(data, args.alias)
    if clash and clash["id"] != args.id:
        raise SystemExit(f"error: alias {args.alias!r} already matches thread "
                         f"{clash['id']!r}")
    aliases = t.setdefault("aliases", [])
    if args.alias not in aliases:
        aliases.append(args.alias)


# ── speculate (the inspiration surface — LLM, non-canon by design) ───────

def build_speculation_payload(data: dict, proposals_path: Path) -> str:
    """Everything the brainstorm sees: ratified canon + pending evidence."""
    parts = ["=== RATIFIED THREADS (canon) ==="]
    for t in data["threads"]:
        parts.append(f"[{t.get('id')}] {t.get('title')} — status {t.get('status')}"
                     + (f", tracker {t['tracker']}" if t.get("tracker") else ""))
        for row in t.get("log") or []:
            parts.append(f"  ch{row.get('chapter')}: ({row.get('change')}) "
                         f"{row.get('summary')}")
    if not data["threads"]:
        parts.append("(none yet)")
    parts.append("\n=== HARVESTED THREAD EVIDENCE (not canon, pending review) ===")
    if proposals_path.exists():
        pdata = yaml.safe_load(proposals_path.read_text(encoding="utf-8")) or {}
        for p in pdata.get("proposals") or []:
            if p.get("status") == "rejected":
                continue
            parts.append(f"'{p.get('title')}' (ch {p.get('chapters')})")
            for ev in (p.get("evidence") or [])[:3]:
                parts.append(f"  ch{ev.get('chapter')}: {ev.get('fact')}")
    return "\n".join(parts)


def speculate(data: dict, proposals_path: Path, output: Path, args) -> None:
    from campaignlib import client_from_args, load_agent_prompt, stream_api

    system = load_agent_prompt("thread_speculate")
    payload = build_speculation_payload(data, proposals_path)
    client = client_from_args(args)
    text = stream_api(client, system,
                      payload + "\n\nPropose your numbered ideas now.",
                      args.model, max_tokens=args.max_tokens)
    output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Thread speculations — NOT CANON\n\n"
        "_LLM brainstorm over the thread registry + pending evidence "
        "(`thread_registry.py speculate`). Connections here may not exist; "
        "that is the point — this file is idea fuel in the notes staging "
        "area. Nothing enters canon from here without the GM._\n\n"
    )
    output.write_text(header + text.strip() + "\n", encoding="utf-8")


# ── render (the projection the grounding docs consume) ───────────────────

def render(data: dict, output: Path) -> int:
    by_status: dict[str, list[dict]] = defaultdict(list)
    for t in data["threads"]:
        by_status[t.get("status", "open")].append(t)

    lines = [
        "# Threads",
        "",
        "_Projection of `docs/thread_registry.yaml` rendered by "
        "`thread_registry.py` — every thread and every log row is "
        "GM-ratified. Edit the registry through its verbs, never this file._",
        "",
    ]
    for status in STATUSES:
        threads = sorted(by_status.get(status, []), key=lambda t: t.get("id", ""))
        if not threads:
            continue
        lines.append(f"## {status.capitalize()} ({len(threads)})")
        lines.append("")
        for t in threads:
            span = f"opened ch{t.get('opened')}"
            if t.get("resolved"):
                span += f", closed ch{t['resolved']}"
            head = f"### {t.get('title')}  — {span}"
            if t.get("tracker"):
                head += f"  (tracker: {t['tracker']})"
            lines.append(head)
            if t.get("notes"):
                lines.append(f"> {t['notes']}")
            for row in t.get("log") or []:
                lines.append(f"- [ch{row['chapter']:02d}] ({row['change']}) "
                             f"{row['summary']}")
                if row.get("quote"):
                    lines.append(f"  > \"{row['quote']}\"")
            lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(data["threads"])


# ── rulings (the GM's decision, recorded; D18's atomic accept) ───────────

RULINGS = ("ratified", "rejected", "deferred")


def _find_proposal(doc: dict, norm: str) -> dict | None:
    for pr in doc.get("proposals") or []:
        if isinstance(pr, dict) and pr.get("norm") == norm:
            return pr
    return None


def save_proposals(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(doc, sort_keys=False,
                                           allow_unicode=True, width=100))


def append_adjudication(path: Path, proposal: dict, note: str) -> None:
    """Append one discussed candidate to the adjudication bundle.

    Appending, never overwriting: an in-flight conversation must not lose its
    input. The entry carries the candidate's evidence so the file is
    self-sufficient — the whole point is that it can be handed to a
    conversation alone, without re-running the harvest (SC-007).
    """
    if path.exists():
        bundle = json.loads(path.read_text(encoding="utf-8") or "{}")
    else:
        bundle = {"version": 1, "entries": []}
    bundle.setdefault("version", 1)
    bundle.setdefault("entries", [])
    if any(e.get("norm") == proposal.get("norm") for e in bundle["entries"]):
        return   # already deferred once; the record of that is not a lie
    bundle["entries"].append({
        "norm": proposal.get("norm"),
        "title": proposal.get("title"),
        "all_titles": proposal.get("all_titles") or [],
        "chapters": proposal.get("chapters") or [],
        "matches": proposal.get("matches"),
        "note": note or "",
        "evidence": proposal.get("evidence") or [],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")


def cmd_rule(args) -> None:
    if args.status not in RULINGS:
        raise SystemExit(f"error: bad ruling {args.status!r} "
                         f"(allowed: {', '.join(RULINGS)})")
    if not args.proposals.exists():
        raise SystemExit(f"error: no proposals file at {args.proposals} "
                         f"— run propose first")
    doc = load_proposals(args.proposals)
    pr = _find_proposal(doc, args.norm)
    if pr is None:
        raise SystemExit(f"error: no proposal with norm {args.norm!r} "
                         f"— run propose first")
    if args.status == "ratified" and not (args.thread or pr.get("ruled_thread")):
        # Without a thread to point at, the next `propose` cannot tell this
        # apart from an unruled candidate: the short-circuit covers only
        # rejected/deferred, `match_thread` finds nothing, and the row is
        # rewritten as `pending`. The ruling would evaporate, contradicting
        # "GM rulings are preserved across re-proposes" (review finding).
        raise SystemExit(
            "error: --status ratified needs --thread ID (the thread the "
            "ratification produced), or use `ratify` to create it — a "
            "ratification with no thread behind it does not survive the next "
            "propose")
    if args.status == "deferred":
        append_adjudication(args.adjudication, pr, args.note or "")
    pr["status"] = args.status
    if args.note:
        pr["note"] = args.note
    if args.thread:
        pr["ruled_thread"] = args.thread
    save_proposals(args.proposals, doc)


def derive_plan(pr: dict) -> dict:
    """The starting point the GM edits — never what gets written unreviewed.

    `--plan` is required for a write precisely so this derivation cannot become
    an "accept as proposed" button: a thread nobody read the fields of is what
    SC-004 forbids.
    """
    chapters = sorted(c for c in (pr.get("chapters") or []) if isinstance(c, int))
    ev_by_ch: dict[int, dict] = {}
    for ev in pr.get("evidence") or []:
        ch = ev.get("chapter")
        if isinstance(ch, int) and ch not in ev_by_ch:
            ev_by_ch[ch] = ev
    log = []
    for i, ch in enumerate(chapters):
        ev = ev_by_ch.get(ch) or {}
        row = {"chapter": ch,
               "change": "opened" if i == 0 else "advanced",
               "summary": ev.get("fact") or ""}
        if ev.get("quote"):
            row["quote"] = ev["quote"]
        log.append(row)
    return {"id": pr.get("norm"), "title": pr.get("title"),
            "status": "open", "opened": chapters[0] if chapters else None,
            "tracker": None, "notes": "", "log": log}


def cmd_ratify(args) -> None:
    """One call, one write per file, no partial-apply window (GM ruling D18).

    Deliberately NOT `add` + N x `log` + `rule`: that sequence could half-apply
    and forced the route to report a 207 partial state the GM then had to
    interpret. Here the registry is built in memory, validated, and written
    once.
    """
    if not args.proposals.exists():
        raise SystemExit(f"error: no proposals file at {args.proposals} "
                         f"— run propose first")
    doc = load_proposals(args.proposals)
    pr = _find_proposal(doc, args.norm)
    if pr is None:
        raise SystemExit(f"error: no proposal with norm {args.norm!r} "
                         f"— run propose first")

    if args.emit_plan:
        print(json.dumps(derive_plan(pr), indent=2, ensure_ascii=False))
        return
    if not args.plan:
        raise SystemExit("error: ratify needs --plan "
                         "(use --emit-plan to derive a starting point)")

    raw = sys.stdin.read() if str(args.plan) == "-" else Path(args.plan).read_text(encoding="utf-8")
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"error: --plan is not valid JSON ({e})")

    rows = plan.get("log") or []
    if not rows:
        raise SystemExit("error: plan has no log rows — a ratified thread "
                         "records at least the chapter it opened in")
    for i, row in enumerate(rows, 1):
        ch = row.get("chapter")
        if not isinstance(ch, int) or isinstance(ch, bool) or ch < 1:
            raise SystemExit(
                f"error: log row {i} has no chapter — a thread's chapters are "
                f"yours to decide, not the harvest's")
        if row.get("change") not in CHANGES:
            raise SystemExit(f"error: log row {i} has bad change "
                             f"{row.get('change')!r} (allowed: {', '.join(CHANGES)})")

    data = load_registry(args.registry)
    notes_out = []
    matched_id = pr.get("matches") or pr.get("ruled_thread")
    target = find_thread(data, matched_id) if matched_id else None

    if target is not None:
        # FR-009: append to the matched thread; create no second one. The
        # plan's identity fields are ignored ON PURPOSE and the fact is
        # reported rather than swallowed.
        ignored = [k for k in ("id", "title", "opened")
                   if plan.get(k) not in (None, "", target.get(k))]
        if ignored:
            notes_out.append(f"note: proposal matches thread {target['id']!r}; "
                             f"ignoring plan {'/'.join(ignored)}")
    else:
        tid = plan.get("id") or pr.get("norm")
        if find_thread(data, tid):
            raise SystemExit(f"error: thread id {tid!r} already exists")
        clash = match_thread(data, plan.get("title") or pr.get("title") or "")
        if clash:
            raise SystemExit(f"error: title {plan.get('title')!r} matches existing "
                             f"thread {clash['id']!r} — use `log`/`alias` on it instead")
        target = {"id": tid, "title": plan.get("title") or pr.get("title"),
                  "status": plan.get("status") or "open",
                  "opened": plan.get("opened"), "resolved": None,
                  "tracker": plan.get("tracker"), "notes": plan.get("notes") or "",
                  "aliases": [], "log": []}
        data["threads"].append(target)

    # A matched candidate keeps its FULL chapter span in the proposal, so a
    # plan derived from it can carry a chapter the target thread already
    # logged — appending it again duplicates canon, and `check_registry` does
    # not flag a repeated chapter (review finding, 2026-08-27). Skip the exact
    # (chapter, change) pairs that are already present, and SAY so rather than
    # dropping them silently.
    existing = {(r.get("chapter"), r.get("change")) for r in (target.get("log") or [])}
    skipped = []
    for row in rows:
        key = (row["chapter"], row["change"])
        if key in existing:
            skipped.append(f"ch{row['chapter']} ({row['change']})")
            continue
        existing.add(key)
        entry = {"chapter": row["chapter"], "change": row["change"],
                 "summary": row.get("summary") or ""}
        if row.get("quote"):
            entry["quote"] = row["quote"]
        target.setdefault("log", []).append(entry)
    if skipped:
        notes_out.append("note: already logged on "
                         f"{target['id']!r}, not duplicated: {', '.join(skipped)}")
    # Deliberately NOT a refusal when every row was already present. The
    # registry is unchanged, but the RULING is not a no-op: the GM decided
    # this candidate is that thread, and recording it is what stops the
    # candidate coming back forever. The count line says what happened.
    target["log"].sort(key=lambda r: (r.get("chapter", 0), r.get("change", "")))

    errors = check_registry(data)
    if errors:
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        raise SystemExit("error: refusing to save a registry that fails check")

    # Canon first, then the ruling (contracts/cli.md, "the one non-atomic
    # seam, stated rather than hidden"). If the second write fails the thread
    # exists and the candidate stays pending — a readable, recoverable state.
    # The other order risks a proposal marked ratified with no thread behind it.
    save_registry(args.registry, data)
    pr["status"] = "ratified"
    pr["ruled_thread"] = target["id"]
    if args.note:
        pr["note"] = args.note
    save_proposals(args.proposals, doc)
    for n in notes_out:
        print(n)
    appended = len(rows) - len(skipped)
    print(f"ok: ratified {args.norm!r} -> thread {target['id']!r} "
          f"({appended} log row(s) added"
          + (f", {len(skipped)} already present)" if skipped else ")"))


# ── read verbs (machine-readable; the server parses nothing) ─────────────
#
# `get_sections` already established that the server consumes `--json` rather
# than screen-scraping a human table (Constitution VI, FR-023). These exist so
# the web surface has nothing to parse and holds no thread state of its own.


def load_proposals(path: Path) -> dict:
    """The proposals document as written, or an empty one when absent.

    An absent file is a state, not an error: a campaign that has never
    harvested reads as zero proposals, which is what the queue should render
    as "no candidates yet".
    """
    if not path.exists():
        return {"proposals": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"proposals": []}


def proposals_payload(path: Path) -> dict:
    """{"proposals": [...], "counts": {...}} — the FULL set, never filtered.

    No paging, no server-side query, no threshold applied here (FR-028,
    research D16). The 986-candidate OOTA harvest serialises to 484 KB, which
    is nothing for a localhost single-user server — and filtering it here
    would put "which candidates matter" in the server, which is the GM's
    decision, not software's.
    """
    data = load_proposals(path)
    props = [p for p in (data.get("proposals") or []) if isinstance(p, dict)]
    counts: dict[str, int] = {}
    for pr in props:
        st = pr.get("status") or "pending"
        counts[st] = counts.get(st, 0) + 1
    return {"proposals": props, "counts": counts}


# ── cli ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", type=Path, default=None,
                    help="Thread registry store (default: config stores.thread_registry)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("propose", help="Harvest thread facts into a GM-review proposals file")
    pr.add_argument("--corpus", required=True, nargs="+", metavar="GLOB")
    pr.add_argument("--out", type=Path, default=None,
                    help="Proposals file (default: config stores.thread_proposals)")
    pr.add_argument("--min-chapters", type=int, default=1, metavar="N",
                    help="Drop candidates spanning fewer than N chapters "
                         "(default 1 = keep everything)")
    pr.add_argument("--min-evidence", type=int, default=1, metavar="N",
                    help="Drop candidates with fewer than N evidence rows "
                         "(default 1 = keep everything)")

    # `rule` takes exactly one --norm: no --all, no repetition, no glob. FR-007
    # is enforced by the argument shape rather than by convention.
    rl = sub.add_parser("rule", help="Record a GM ruling on ONE proposal")
    rl.add_argument("--norm", required=True, metavar="KEY")
    # No argparse `choices=`: cmd_rule owns the refusal so the message is the
    # one contracts/cli.md pins ("error: bad ruling 'X' (allowed: ...)"), and
    # so the route -- which forwards --status verbatim -- gets that same text
    # back as its 400 detail instead of an argparse usage block (FR-021).
    rl.add_argument("--status", required=True, metavar="RULING")
    rl.add_argument("--note", default=None)
    rl.add_argument("--thread", default=None, metavar="ID")
    rl.add_argument("--proposals", type=Path, default=None)
    rl.add_argument("--adjudication", type=Path, default=None,
                    help="Discuss bundle (default: config stores.thread_adjudication)")

    rt = sub.add_parser("ratify", help="Turn ONE proposal into canon, atomically")
    rt.add_argument("--norm", required=True, metavar="KEY")
    rt.add_argument("--plan", default=None, metavar="FILE",
                    help="Plan JSON, or '-' for stdin. Required for a write.")
    rt.add_argument("--emit-plan", action="store_true",
                    help="Print the derived starting point and write nothing")
    rt.add_argument("--note", default=None)
    rt.add_argument("--proposals", type=Path, default=None)

    ad = sub.add_parser("add", help="Add a thread (GM ratification)")
    ad.add_argument("--id", required=True)
    ad.add_argument("--title", required=True)
    ad.add_argument("--status", default="open")
    ad.add_argument("--opened", type=int, required=True, metavar="CHAPTER")
    ad.add_argument("--tracker", default=None,
                    help="Optional link to a GM arc score (arc scores are NOT threads)")
    ad.add_argument("--notes", default="")

    lg = sub.add_parser("log", help="Ratify a per-chapter transition")
    lg.add_argument("--id", required=True)
    lg.add_argument("--chapter", type=int, required=True)
    lg.add_argument("--change", required=True, choices=CHANGES)
    lg.add_argument("--summary", required=True)
    lg.add_argument("--quote", default=None)

    st = sub.add_parser("set-status", help="Change a thread's lifecycle status")
    st.add_argument("--id", required=True)
    st.add_argument("--status", required=True, choices=STATUSES)
    st.add_argument("--chapter", type=int, default=None)

    al = sub.add_parser("alias", help="Record a title variant as the same thread")
    al.add_argument("--id", required=True)
    al.add_argument("--alias", required=True)

    ck = sub.add_parser("check", help="Registry invariants (read-only)")
    ck.add_argument("--json", action="store_true",
                    help="Emit {threads, problems} as JSON (exit 1 unchanged)")

    ls = sub.add_parser("list", help="The registry, machine-readable (read-only)")
    ls.add_argument("--json", action="store_true", help="Emit JSON")

    pl = sub.add_parser("proposals", help="The proposal queue, machine-readable")
    pl.add_argument("--json", action="store_true", help="Emit JSON")
    pl.add_argument("--proposals", type=Path, default=None,
                    help="Proposals file (default: config stores.thread_proposals)")

    rd = sub.add_parser("render", help="Project the registry to markdown")
    # No config default: this render's own markdown (superseded in practice
    # by grounding_sections.py's inline "threads" section, which reads the
    # registry directly rather than shelling out here) has no declared
    # ProjectionOutput field, and inventing one to hold a single-caller
    # literal would be the opposite of FR-014's discipline. Required instead
    # of a bare path literal (contracts/cli.md doesn't cover this flag).
    rd.add_argument("--output", type=Path, required=True)

    sp = sub.add_parser(
        "speculate",
        help="LLM brainstorm over registry + evidence -> notes/ (NOT canon)")
    sp.add_argument("--proposals", type=Path, default=None,
                    help="Proposals file (default: config stores.thread_proposals)")
    sp.add_argument("--output", type=Path, default=None,
                    help="Speculation output (default: config inputs.speculations)")
    sp.add_argument("--model", default=None, metavar="ID")
    sp.add_argument("--max-tokens", type=int, default=4096)
    from campaignlib import add_backend_args
    from campaignlib.api.client import resolve_cli_model
    add_backend_args(sp, default_backend="dgx")

    args = ap.parse_args()
    if args.cmd == "speculate":
        args.model = resolve_cli_model(
            args, legacy_default=None
        ).effective_model
    # Loaded once, before any work begins (contracts/cli.md's resolution
    # rule) — every None sentinel above resolves from here; an explicit
    # flag always wins.
    cfg = load_projection_config(config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME))
    if args.registry is None:
        args.registry = Path(cfg.stores.thread_registry)

    if args.cmd == "propose":
        if args.out is None:
            args.out = Path(cfg.stores.thread_proposals)
        total, pending = propose(args.corpus, args.registry, args.out,
                                 min_chapters=args.min_chapters,
                                 min_evidence=args.min_evidence)
        print(f"wrote {args.out}: {total} proposal(s), {pending} pending GM review")
        return

    if args.cmd in ("rule", "ratify"):
        if args.proposals is None:
            args.proposals = Path(cfg.stores.thread_proposals)
        if args.cmd == "rule":
            if args.adjudication is None:
                args.adjudication = Path(cfg.stores.thread_adjudication)
            cmd_rule(args)
            print(f"ok: {args.norm} -> {args.status}")
        else:
            cmd_ratify(args)
        return

    if args.cmd == "proposals":
        if args.proposals is None:
            args.proposals = Path(cfg.stores.thread_proposals)
        payload = proposals_payload(args.proposals)
        if args.json:
            print(json.dumps(payload))
        else:
            print(f"{len(payload['proposals'])} proposal(s): "
                  + ", ".join(f"{k} {v}" for k, v in sorted(payload["counts"].items())))
        return

    data = load_registry(args.registry)
    if args.cmd == "list":
        if args.json:
            print(json.dumps({"version": data.get("version", 1),
                              "threads": data["threads"],
                              "count": len(data["threads"])}))
        else:
            for t in data["threads"]:
                print(f"{t.get('id')}\t{t.get('status')}\t{t.get('title')}")
            print(f"{len(data['threads'])} thread(s)")
        return
    if args.cmd == "check":
        errors = check_registry(data)
        if args.json:
            # Data, not a transport error: the caller reads `problems` and
            # renders them. The exit code stays 1 so shell users and CI keep
            # the behaviour they have.
            print(json.dumps({"threads": len(data["threads"]),
                              "problems": errors}))
            sys.exit(1 if errors else 0)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(f"{len(data['threads'])} thread(s); {len(errors)} problem(s)")
        sys.exit(1 if errors else 0)
    if args.cmd == "render":
        n = render(data, args.output)
        print(f"wrote {args.output}: {n} thread(s)")
        return
    if args.cmd == "speculate":
        if args.proposals is None:
            args.proposals = Path(cfg.stores.thread_proposals)
        if args.output is None:
            args.output = Path(cfg.inputs.speculations)
        speculate(data, args.proposals, args.output, args)
        print(f"wrote {args.output} (speculation — NOT canon; notes staging)")
        return

    {"add": cmd_add, "log": cmd_log, "set-status": cmd_set_status,
     "alias": cmd_alias}[args.cmd](data, args)
    errors = check_registry(data)
    if errors:
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        raise SystemExit("error: refusing to save a registry that fails check")
    save_registry(args.registry, data)
    print(f"ok: {args.cmd} -> {args.registry}")


if __name__ == "__main__":
    main()
