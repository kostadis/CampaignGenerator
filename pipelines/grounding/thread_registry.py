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
  ``status: pending``. GM rulings (`ratified`/`rejected`/`deferred`) are
  preserved across re-proposes; nothing downstream reads proposals.
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

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_REGISTRY = Path("docs/thread_registry.yaml")
DEFAULT_PROPOSALS = Path("docs/ensemble/thread_proposals.yaml")
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


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


def propose(corpus_globs: list[str], registry_path: Path, out: Path) -> tuple[int, int]:
    registry = load_registry(registry_path)
    prior = load_prior_rulings(out)
    groups = harvest(corpus_globs)

    proposals = []
    pending = 0
    for key in sorted(groups):
        g = groups[key]
        if key in prior:
            proposals.append(prior[key])   # GM rulings are a one-way door
            continue
        matched = match_thread(registry, g["title"])
        # Already-logged chapters on a matched thread are not re-proposed.
        logged = {r.get("chapter") for r in (matched.get("log") or [])} if matched else set()
        fresh_chapters = sorted(c for c in g["chapters"] if c not in logged)
        if matched and not fresh_chapters:
            continue
        proposals.append({
            "norm": key,
            "title": g["title"],
            "all_titles": sorted(g["titles"]),
            "matches": matched.get("id") if matched else None,
            "chapters": sorted(g["chapters"]),
            "status": "pending",
            "evidence": sorted(g["evidence"],
                               key=lambda e: (e.get("chapter") or 0, e["fact"]))[:8],
        })
        pending += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(
        {"note": ("Proposals only — nothing downstream reads this file. A GM "
                  "ruling (ratified/rejected/deferred) is preserved across "
                  "re-proposes; ratification itself happens through "
                  "thread_registry.py verbs or the thread-triage skill."),
         "proposals": proposals},
        sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")
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


# ── cli ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("propose", help="Harvest thread facts into a GM-review proposals file")
    pr.add_argument("--corpus", required=True, nargs="+", metavar="GLOB")
    pr.add_argument("--out", type=Path, default=DEFAULT_PROPOSALS)

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

    ck = sub.add_parser("check", help="Registry invariants (read-only)")  # noqa: F841

    rd = sub.add_parser("render", help="Project the registry to markdown")
    rd.add_argument("--output", type=Path,
                    default=Path("docs/ensemble/threads_registry.md"))

    sp = sub.add_parser(
        "speculate",
        help="LLM brainstorm over registry + evidence -> notes/ (NOT canon)")
    sp.add_argument("--proposals", type=Path, default=DEFAULT_PROPOSALS)
    sp.add_argument("--output", type=Path,
                    default=Path("notes/thread_speculations.md"))
    sp.add_argument("--model", default=None, metavar="ID")
    sp.add_argument("--max-tokens", type=int, default=4096)
    from campaignlib import add_backend_args
    add_backend_args(sp, default_backend="dgx")

    args = ap.parse_args()

    if args.cmd == "propose":
        total, pending = propose(args.corpus, args.registry, args.out)
        print(f"wrote {args.out}: {total} proposal(s), {pending} pending GM review")
        return

    data = load_registry(args.registry)
    if args.cmd == "check":
        errors = check_registry(data)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        print(f"{len(data['threads'])} thread(s); {len(errors)} problem(s)")
        sys.exit(1 if errors else 0)
    if args.cmd == "render":
        n = render(data, args.output)
        print(f"wrote {args.output}: {n} thread(s)")
        return
    if args.cmd == "speculate":
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
