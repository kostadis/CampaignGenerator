"""audit: the tracking audit as its own step (spec 033 US6, FR-026/FR-027, research R11).

This is the judge step (a model step, with ``extract`` and ``synth``) and it reaches a model only
through ``campaignlib`` (``client_from_args``, ``stream_api``). Code does the scoping on both
sides of the call (``audit_select``): it picks each item's candidate chapters before, and it accepts
SUPPORTED only for a citation inside those chapters and a verbatim span after. The model sees one
item and those chapters, never the tracking list and never anything else (Principle II).

Items are dispatched through ``extract``'s shared queue (``_run_pool``): ``--parallel`` worker
threads per endpoint, every endpoint preflighted before the first call. Verdicts are cached per
item by a key over the prompts, backend, model and ``max_tokens``; a cached answer is re-checked
by the current code, so a change to the check applies without a new call.

Layout, under ``<range_dir>/state/``::

    audit/items.json   numbered items, candidate chapters, cache keys, input digests (freshness)
    audit/audit.json   a verdict per item, with the model's answer (the cache)
    audit/audit.md     the verdicts as ``synth campaign_state`` renders them
    runs/<stamp>/      record.json and, per item, ``audit.<id>.user.md`` / ``.out.md``
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text
from pipelines.summary_native import audit_select, context, corpus, extract, freshness, notes, npc_forms, schema, state_sections, synth, validate
from pipelines.summary_native.freshness import check_fresh
from pipelines.summary_native.resolve import ExtractSettings

EXIT_REFUSED = synth.EXIT_REFUSED
EXIT_INCOMPLETE = synth.EXIT_INCOMPLETE
EXIT_MODEL_FAILED = synth.EXIT_MODEL_FAILED
EXIT_BLOCKING = synth.EXIT_BLOCKING

SYSTEM_PROMPT = "state.audit.system.md"
ITEMS_FILE = "items.json"
AUDIT_FILE = "audit.json"
AUDIT_MD = "audit.md"


def load_system() -> str:
    return (context.PROMPT_DIR / SYSTEM_PROMPT).read_text(encoding="utf-8")


def build_user(item: audit_select.Item, chapters: list) -> str:
    """The user prompt for one item: the item as a claim to check, then only its candidate chapters,
    verbatim. No other item and no other chapter (FR-026)."""
    return (
        f"TRACKING ITEM (a claim to check, not evidence): [{item.id}] {item.text}\n\n"
        f"CANDIDATE CHAPTERS (the only evidence): {', '.join(f'{c.number:03d}' for c in chapters)}\n\n"
        "EVIDENCE (the GM-reviewed session summaries for these chapters, verbatim):\n"
        + "".join(notes.chapter_block(c) for c in chapters)
    )


def render_part(client, system: str, user: str, model: str | None, max_tokens: int) -> str:
    """The one model call in this module. Silent: the caller prints one progress line per item."""
    return stream_api(client, system, user, model, max_tokens=max_tokens, silent=True)


def cache_key(*, system: str, user: str, backend: str, model: str | None, max_tokens: int) -> str:
    sha = lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest()  # noqa: E731
    payload = {"system_sha": sha(system), "user_sha": sha(user), "backend": backend, "model": model,
               "max_tokens": max_tokens}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


# ── Plans and outcomes ──────────────────────────────────────────────────────


@dataclass
class _Plan:
    item: audit_select.Item
    candidates: list  # notes.Chapter, in chapter order
    user: str
    key: str


@dataclass
class _Outcome:
    status: str  # "judged" | "cached" | "no-candidates" | "failed" | "pending"
    secs: float = 0.0
    endpoint: str = ""
    answer: str | None = None
    verdict: audit_select.Verdict | None = None
    error: str | None = None


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    atomic_write_text(path, text)


def _judge_one(client, plan: _Plan, system: str, args, run_dir: Path, endpoint: str) -> _Outcome:
    """One item: the call (retried once), the prompt and answer on disk, the code check."""
    error = None
    for attempt in (1, 2):
        t0 = time.monotonic()
        try:
            raw = render_part(client, system, plan.user, args.model, args.max_tokens)
            break
        except Exception as e:  # noqa: BLE001 - any backend error is a failed item
            error = f"{type(e).__name__}: {e}"
            if attempt == 2:
                return _Outcome("failed", time.monotonic() - t0, endpoint, error=error)
    secs = time.monotonic() - t0
    atomic_write_text(run_dir / f"audit.{plan.item.id}.out.md", raw)
    verdict = audit_select.check_verdict(raw, {c.number: c for c in plan.candidates})
    return _Outcome("judged", secs, endpoint, raw, verdict)


def _previous(range_dir: Path) -> dict[str, dict]:
    """``{cache key: verdict record}`` from the last ``audit.json`` (judged items only)."""
    try:
        data = json.loads((freshness.audit_dir(range_dir) / AUDIT_FILE).read_text(encoding="utf-8"))
        records = data["verdicts"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    return {r["cache_key"]: r for r in records
            if isinstance(r, dict) and r.get("cache_key") and r.get("answer") is not None}


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


# ── The run ─────────────────────────────────────────────────────────────────


def run_audit(
    args,
    *,
    root: Path,
    range_dir: Path,
    report: validate.ValidationReport,
    summaries_dir: Path,
    registry_path: Path | None,
    players_path: Path | None,
    settings: ExtractSettings,
    track_files: list[Path],
    candidates_n: int,
    now=None,
) -> int:
    now = now or synth._utcnow
    if report.blocking_count:
        print(report.to_markdown(), end="")
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return EXIT_BLOCKING
    if not track_files:
        return _refuse("no track files: pass --track-file FILE, or set grounding.yaml campaign_state.track_files")
    for p in track_files:
        if not p.is_file():
            return _refuse(f"track file {p}: no such file")
    try:
        corpus_manifest = corpus.load_manifest(range_dir, require_complete=True)
    except corpus.CorpusError as e:
        return _refuse(f"{e}; run `summary_native build`")
    stale = check_fresh(report, range_dir, root, corpus_manifest, registry_path)
    if stale:
        return _refuse(stale)

    since, until = int(corpus_manifest["range"]["since"]), int(corpus_manifest["range"]["until"])
    chapters = notes.load_chapters(summaries_dir, since, until)
    if not chapters:
        return _refuse(f"no summaries for chapters {since}-{until} in {summaries_dir}")
    by_number = {c.number: c for c in chapters}

    backend = resolve_cli_model(args, legacy_default=None).backend
    endpoints = list(dict.fromkeys(getattr(args, "endpoints", None) or []))
    parallel = getattr(args, "parallel", None) or 1
    if endpoints and backend != "dgx":
        return _refuse(f"--endpoints applies to --backend dgx only, not {backend}")
    if endpoints and getattr(args, "endpoint", None):
        return _refuse("give --endpoint or --endpoints, not both")
    if parallel < 1:
        return _refuse(f"--parallel must be at least 1, got {parallel}")
    if candidates_n < 1:
        return _refuse(f"--candidates must be at least 1, got {candidates_n}")
    try:
        forms, _, _ = state_sections.load_identity(registry_path, players_path)
        items = audit_select.load_items(track_files)
    except (ValueError, OSError) as e:
        return _refuse(f"cannot read the entity registry, players.yaml or a track file: {e}")
    if not items:
        return _refuse("the track files hold no items (lines starting with `- `)")
    wordlist, _ = npc_forms.load_wordlist()

    system = load_system()
    plans: list[_Plan] = []
    for it in items:
        nums = audit_select.candidate_chapters(it.text, chapters, forms, wordlist, candidates_n)
        cands = [by_number[n] for n in nums]
        user = build_user(it, cands) if cands else ""
        key = cache_key(system=system, user=user or it.text, backend=backend, model=args.model,
                        max_tokens=args.max_tokens)
        plans.append(_Plan(it, cands, user, key))

    started = now()
    run_dir = synth._new_run_dir(Path(range_dir) / schema.STATE_DIR / "runs", started.strftime("%Y%m%dT%H%M%SZ"))
    atomic_write_text(run_dir / "audit.system.md", system)
    for p in plans:
        if p.candidates:
            atomic_write_text(run_dir / f"audit.{p.item.id}.user.md", p.user)

    if endpoints:
        targets = endpoints
    elif getattr(args, "endpoint", None) and backend == "dgx":
        targets = [args.endpoint]
    else:
        targets = []
    labels = [extract.short(t) for t in targets] or [backend]
    track_facts = freshness.track_files_facts(track_files)
    record = {
        "step": "audit",
        "run_id": run_dir.name,
        "range": {"since": since, "until": until},
        "backend": backend,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "candidates": candidates_n,
        "endpoints": labels,
        "parallel": parallel,
        "dump_only": bool(args.dump_only),
        "force": bool(args.force),
        "inputs": {
            **freshness.notes_manifest_facts(range_dir, registry_path, players_path),
            "track_files_sha256": track_facts,
            "wordlist_sha256": npc_forms.load_wordlist()[1],
        },
        "system_sha256": corpus.sha256_file(context.PROMPT_DIR / SYSTEM_PROMPT),
        "items": [],
        "exit_code": None,
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
    }

    def save_record(code: int) -> None:
        record["exit_code"] = code
        record["finished"] = now().isoformat(timespec="seconds")
        atomic_write_text(run_dir / "record.json", _dumps(record))

    previous = {} if args.force else _previous(range_dir)
    outcomes: dict[str, _Outcome] = {}
    todo: list[_Plan] = []
    for p in plans:
        if not p.candidates:
            outcomes[p.item.id] = _Outcome("no-candidates", verdict=audit_select.no_candidates())
        elif p.key in previous:
            ans = previous[p.key]["answer"]
            outcomes[p.item.id] = _Outcome(
                "cached", answer=ans, verdict=audit_select.check_verdict(ans, {c.number: c for c in p.candidates}))
        else:
            outcomes[p.item.id] = _Outcome("pending")
            todo.append(p)

    if args.dump_only:
        _finish(range_dir, plans, outcomes, args, backend, candidates_n, track_facts, record, write=False)
        save_record(0)
        print(f"[--dump-only: {len(todo)} prompts written to {schema.display_path(run_dir, root)}; no model call]")
        return 0

    n_total = len(plans)
    if todo:
        def stop(msg: str) -> int:
            record["error"] = msg
            _finish(range_dir, plans, outcomes, args, backend, candidates_n, track_facts, record, write=False)
            save_record(EXIT_REFUSED)
            return _refuse(msg)

        if targets:
            problem = extract.preflight(targets, args.model)
            if problem:
                return stop(problem.replace("no chunk was sent", "no item was sent"))
        try:
            if targets:
                clients = {extract.short(t): client_from_args(args, endpoint=t) for t in targets}
            else:
                clients = {labels[0]: client_from_args(args)}
        except SystemExit as e:  # client_from_args fails fast with SystemExit(message)
            return stop(str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})")
        except (ValueError, RuntimeError, ImportError) as e:
            return stop(str(e))
        done = 0
        for label, p, o in extract._run_pool(
            todo, lambda c, plan, ep: _judge_one(c, plan, system, args, run_dir, ep), clients, parallel
        ):
            outcomes[p.item.id] = o
            done += 1
            if o.status == "failed":
                print(f"item {p.item.id} ({done}/{len(todo)}) @{label} FAILED after one retry: {o.error}",
                      file=sys.stderr, flush=True)
            else:
                print(f"item {p.item.id} ({done}/{len(todo)}) @{label} {o.secs:.0f}s {o.verdict.verdict}"
                      + (f" ({o.verdict.reason})" if o.verdict.reason else ""), flush=True)

    data = _finish(range_dir, plans, outcomes, args, backend, candidates_n, track_facts, record, write=True)
    c = data["counts"]
    print(audit_select.summary_line(c))
    failed = [p.item.id for p in plans if outcomes[p.item.id].status == "failed"]
    n_cached = sum(1 for o in outcomes.values() if o.status == "cached")
    n_new = sum(1 for o in outcomes.values() if o.status == "judged")
    print(f"{n_new} judged, {n_cached} cached, {c['no_candidates']} without candidates; "
          f"see {schema.display_path(freshness.audit_dir(range_dir) / AUDIT_MD, root)}")
    if c["unverified"]:
        print(f"{c['unverified']} SHOWN answer(s) not accepted and counted NOT FOUND: the citation was outside the "
              f"candidate chapters, or the span was not verbatim (each item says which in {AUDIT_MD})")
    code = 0
    if failed:
        if not n_new and not n_cached and len(failed) == len(todo):
            print("Error: no item could be judged: the backend could not be reached or rejected every call "
                  f"(see {schema.display_path(run_dir / 'record.json', root)})", file=sys.stderr)
            code = EXIT_MODEL_FAILED
        else:
            print(f"Error: {len(failed)} item(s) failed after one retry: {', '.join(failed)}. "
                  f"Run the same command again to judge only those", file=sys.stderr)
            code = EXIT_INCOMPLETE
    save_record(code)
    return code


def _finish(range_dir, plans, outcomes, args, backend, candidates_n, track_facts, record, *, write: bool) -> dict:
    """Fill the record's item list and, when ``write``, ``items.json``, ``audit.json`` and ``audit.md``.
    Returns the ``audit.json`` content."""
    verdicts, rec_items, item_rows = [], [], []
    for p in plans:
        o = outcomes[p.item.id]
        nums = [c.number for c in p.candidates]
        item_rows.append({"id": p.item.id, "file": p.item.file, "text": p.item.text,
                          "candidate_chapters": nums, "cache_key": p.key})
        if o.verdict is not None:
            v = o.verdict.to_dict()
        else:
            v = audit_select.Verdict(audit_select.NOT_JUDGED).to_dict()
        row = {"id": p.item.id, "file": p.item.file, "text": p.item.text, "candidates": nums,
               "cache_key": p.key, **v}
        if o.answer is not None:
            row["answer"] = o.answer
        verdicts.append(row)
        rec = {"id": p.item.id, "candidates": nums, "cache_key": p.key, "status": o.status,
               "secs": round(o.secs, 1), "endpoint": o.endpoint, "verdict": v["verdict"]}
        if o.error:
            rec["error"] = o.error
        rec_items.append(rec)
    record["items"] = rec_items
    data = {"kind": "audit", "schema": 1, "range": record["range"], "counts": audit_select.counts_of(verdicts),
            "verdicts": verdicts}
    if write:
        ad = freshness.audit_dir(range_dir)
        ad.mkdir(parents=True, exist_ok=True)
        items = {
            "kind": "audit_items", "schema": 1, "range": record["range"],
            "track_files_sha256": track_facts,
            "notes_manifest_sha256": freshness.sha_file(freshness.notes_dir(range_dir) / freshness.NOTES_MANIFEST),
            "candidates": candidates_n, "backend": backend, "model": args.model,
            "max_tokens": args.max_tokens, "system_sha256": record["system_sha256"],
            "wordlist_sha256": record["inputs"]["wordlist_sha256"],
            "items": item_rows,
        }
        _write_if_changed(ad / ITEMS_FILE, _dumps(items))
        _write_if_changed(ad / AUDIT_FILE, _dumps(data))
        _write_if_changed(ad / AUDIT_MD, "# Tracking audit\n\n" + audit_select.render_audit_md(data))
    return data
