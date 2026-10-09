"""extract: the map step of the chunked grounding documents (spec 033 T017, FR-001..FR-006).

This is the model step of extraction (with ``synth`` and ``audit``), and it reaches a model only
through ``campaignlib`` (``client_from_args``, ``stream_api``), exactly as ``synth`` does. It reads
the full reviewed summaries for the range in groups of whole chapters, has a model write notes in a
fixed grammar, and hands every output to ``notes.check_chunk``. Nothing a model wrote is used until
code has checked it (Principle II), and no audit list is ever sent (FR-027).

Layout, under ``<range_dir>/state/notes/``::

    chunkNN.{aaa-bbb}.user.md       the exact prompt sent (Principle VIII)
    chunkNN.{aaa-bbb}.out.md        the raw model output, verbatim
    chunkNN.{aaa-bbb}.checked.json  kept notes and drops after the code check, with the cache key
    drops.md                        every dropped note with its reason; outlier chunks flagged
    manifest.json                   what ``synth`` and the freshness check read

and one ``state/runs/<stamp>/record.json`` per run. The manifest holds nothing that varies between
runs (no timing, no endpoint), so a fully cached run rewrites it byte-for-byte.

Chunks are dispatched by :func:`_run_pool`: one shared queue, ``--parallel`` worker threads per
endpoint, so a slow box takes fewer chunks instead of stalling the tail. Every endpoint is
preflighted against ``/v1/models`` before any call (FR-023), and each chunk's record names the
endpoint that served it.
"""

from __future__ import annotations

import json
import hashlib
import queue
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from campaignlib import client_from_args, stream_api
from campaignlib.api.client import resolve_cli_model
from campaignlib.util import atomic_write_text
from pipelines.summary_native import context, corpus, freshness, notes, npc_chunked, schema, synth, validate
from pipelines.summary_native.freshness import check_fresh
from pipelines.summary_native.resolve import ExtractSettings

EXIT_REFUSED = synth.EXIT_REFUSED
EXIT_INCOMPLETE = synth.EXIT_INCOMPLETE
EXIT_MODEL_FAILED = synth.EXIT_MODEL_FAILED
EXIT_BLOCKING = synth.EXIT_BLOCKING

SYSTEM_PROMPT = "state.extract.system.md"
_CHUNK_FILE_RE = re.compile(r"^chunk\d{2,}\.\d{3}-\d{3}\.(?:user\.md|out\.md|checked\.json)$")


def load_system() -> str:
    return (context.PROMPT_DIR / SYSTEM_PROMPT).read_text(encoding="utf-8")


def build_user(chunk, *, evidence_header: str | None = None) -> str:
    """The user prompt for one chunk: its chapters verbatim, then the outline. Nothing else: no
    tracking-file items, no audit questions (FR-027)."""
    return (
        f"CHAPTERS IN THIS CHUNK: {npc_chunked.chunk_range(chunk)}\n\n"
        + (evidence_header or "EVIDENCE (the GM-reviewed session summaries for these chapters, verbatim):") + "\n"
        + "".join(notes.chapter_block(c) for c in chunk)
        + "\n\nOUTLINE: write exactly these `##` sections, in this order, and nothing else at that level:\n\n"
        + "\n".join(schema.STATE_MAP_SECTIONS)
        + "\n"
    )


def render_part(client, system: str, user: str, model: str | None, max_tokens: int) -> str:
    """The one model call in this module. Silent: the caller prints one progress line per chunk."""
    return stream_api(client, system, user, model, max_tokens=max_tokens, silent=True)


def short(endpoint: str) -> str:
    return re.sub(r"^https?://|/v1/?$", "", endpoint)


# ── Plans and outcomes ──────────────────────────────────────────────────────


@dataclass
class _Plan:
    index: int
    chunk: list
    chapters: str  # "002-003"
    system: str
    user: str
    key: str
    stem: str

    @property
    def numbers(self) -> list[int]:
        return [c.number for c in self.chunk]

    @property
    def chars(self) -> int:
        return sum(len(c.text) for c in self.chunk)


@dataclass
class _Outcome:
    status: str  # "extracted" | "cached" | "failed" | "pending"
    secs: float = 0.0
    endpoint: str = ""
    checked: notes.CheckedChunk | None = None
    error: str | None = None
    missing: list[str] = field(default_factory=list)  # outline sections the output never wrote (#515)


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    atomic_write_text(path, text)


def _range_cache(range_dir: Path) -> dict[str, list[Path]]:
    """Index raw extractions in sibling ranges by content key, including pre-existing builds.

    The configured output root belongs to this campaign. No global cache or directory outside
    that root is searched. The raw response is always checked again against the current chunk.
    """
    found: dict[str, list[Path]] = {}
    for path in sorted(Path(range_dir).parent.glob("ch*-*/state/notes/*.checked.json")):
        if path.parent == freshness.notes_dir(range_dir):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = data.get("cache_key") if isinstance(data, dict) else None
        if isinstance(key, str):
            found.setdefault(key, []).append(path)
    return found


def _read_cached(nd: Path, plan: _Plan, shared: dict[str, list[Path]] | None = None) -> notes.CheckedChunk | None:
    """Reuse an exact content-key match, re-checking raw output with today's checker.

    Prefer this range. A sibling hit is copied into this range's notes so it is self-contained;
    source files and their checked results are never rewritten.

    A raw output that lacks an outline section (written before that was a failure) is never used:
    every source is tried, and if none is complete the local one is returned with ``missing`` set and
    nothing is written, for the caller to report. A sibling's incomplete output is only skipped.
    """
    local = nd / f"{plan.stem}.checked.json"
    incomplete = None
    for path in [local, *(shared or {}).get(plan.key, [])]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("cache_key") != plan.key:
                continue
            raw_path = path.with_name(path.name.removesuffix(".checked.json") + ".out.md")
            raw = raw_path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        cc = notes.check_chunk(raw, plan.chunk, plan.chapters)
        if cc.missing:
            if path == local:
                incomplete = cc
            continue
        _write_if_changed(nd / f"{plan.stem}.out.md", raw)
        _write_checked(nd, plan, cc)
        return cc
    return incomplete


def _write_checked(nd: Path, plan: _Plan, cc: notes.CheckedChunk) -> None:
    _write_if_changed(nd / f"{plan.stem}.checked.json", _dumps({**cc.to_dict(), "cache_key": plan.key}))


def _extract_one(client, plan: _Plan, nd: Path, args, endpoint: str) -> _Outcome:
    """One chunk: the call, the raw output on disk, the code check, the checked file.

    The call is retried once, and an output that lacks an outline section counts as a failed call
    (#515): retried once, then a failed chunk with no ``checked.json``. The raw output stays on disk."""
    missing: list[str] = []
    for attempt in (1, 2):
        t0 = time.monotonic()
        try:
            raw = render_part(client, plan.system, plan.user, args.model, args.max_tokens)
        except Exception as e:  # noqa: BLE001 - any backend error is a failed chunk
            if attempt == 2:
                if missing:  # attempt 1 wrote an incomplete out.md; do not leave a result paired with it
                    (nd / f"{plan.stem}.checked.json").unlink(missing_ok=True)
                return _Outcome("failed", time.monotonic() - t0, endpoint, None, f"{type(e).__name__}: {e}", missing)
            continue
        secs = time.monotonic() - t0
        atomic_write_text(nd / f"{plan.stem}.out.md", raw)
        cc = notes.check_chunk(raw, plan.chunk, plan.chapters)
        if cc.missing:
            missing = cc.missing
            if attempt == 2:
                (nd / f"{plan.stem}.checked.json").unlink(missing_ok=True)  # never leave an older result standing
                return _Outcome("failed", secs, endpoint, None, _missing_error(cc.missing), cc.missing)
            continue
        _write_checked(nd, plan, cc)
        return _Outcome("extracted", secs, endpoint, cc)
    raise AssertionError("unreachable")  # pragma: no cover


def _missing_error(missing: list[str]) -> str:
    return "output missing outline section(s) " + ", ".join(missing)


def _run_pool(todo: list[_Plan], work, clients: dict[str, object], per_endpoint: int = 1):
    """Yield ``(endpoint label, plan, outcome)`` as each chunk finishes.

    ``clients`` maps an endpoint label to its client; ``per_endpoint`` is the number of concurrent
    calls each may carry. One shared queue feeds ``per_endpoint`` worker threads per endpoint; a
    worker pulls the next chunk when it is free, so a slow endpoint simply takes fewer
    (``work(client, plan, endpoint)`` never raises for a failed call: it returns a failed outcome).
    """
    pending: queue.Queue = queue.Queue()
    for plan in todo:
        pending.put(plan)
    done: queue.Queue = queue.Queue()

    def worker(label: str, client) -> None:
        while True:
            try:
                plan = pending.get_nowait()
            except queue.Empty:
                return
            try:
                done.put((label, plan, work(client, plan, label), None))
            except BaseException as e:  # noqa: BLE001 - re-raised in the caller's thread below
                done.put((label, plan, None, e))

    threads = [
        threading.Thread(target=worker, args=(label, client), daemon=True)
        for label, client in clients.items()
        for _ in range(per_endpoint)
    ]
    for t in threads:
        t.start()
    for _ in range(len(todo)):
        label, plan, outcome, err = done.get()
        if err is not None:
            raise err
        yield label, plan, outcome


def _served_models(endpoint: str) -> list[str]:
    """The model ids an OpenAI-compatible endpoint serves (its ``/models``). The test seam."""
    with urllib.request.urlopen(endpoint.rstrip("/") + "/models", timeout=5) as r:
        return [m.get("id") for m in json.load(r).get("data", [])]


def preflight(endpoints: list[str], model: str | None) -> str | None:
    """A refusal message unless every endpoint answers ``/models`` and serves ``model``; checked
    for all of them before the first chunk is sent (FR-023)."""
    for ep in endpoints:
        try:
            ids = _served_models(ep)
        except Exception as e:  # noqa: BLE001 - unreachable, timeout, malformed answer
            return f"endpoint {short(ep)} is not answering ({type(e).__name__}: {e}); no chunk was sent"
        if model and model not in ids:
            return (f"endpoint {short(ep)} serves {ids}, not {model}; every endpoint must serve the same "
                    f"model; no chunk was sent")
    return None


# ── The run ─────────────────────────────────────────────────────────────────


def _refuse(msg: str) -> int:
    print(f"Error: {msg}", file=sys.stderr)
    return EXIT_REFUSED


def run_extract(
    args,
    *,
    root: Path,
    range_dir: Path,
    report: validate.ValidationReport,
    summaries_dir: Path,
    registry_path: Path | None,
    players_path: Path | None,
    settings: ExtractSettings,
    now=None,
) -> int:
    now = now or synth._utcnow
    audience = getattr(args, "audience", "gm")
    if report.blocking_count:
        if audience != "gm":
            return _refuse("validation is unavailable for this restricted audience")
        print(report.to_markdown(), end="")
        print("validation has blocking problems; fix the summaries, then build --force", file=sys.stderr)
        return EXIT_BLOCKING
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
    present = {c.number for c in chapters}
    absent = [n for n in range(since, until + 1) if n not in present]

    evidence = getattr(args, "authority_evidence", None)
    if audience != "gm":
        if evidence is None or not evidence.sections:
            return _refuse("no complete authorized support exists for this audience")
        # The model receives only independently classified source slices.  Do
        # not retain a neighbouring summary paragraph merely to preserve a
        # chapter-shaped prompt.
        chapters = []
        for _, source, data in evidence.sections:
            source_path = Path(source.split("#", 1)[0])
            match = schema.PREFIX_RE.match(source_path.name)
            # Planning notes are routed independently by their reviewed
            # record/anchor; they must never be given an invented chapter id
            # that could validate a forged summary citation.
            if not match:
                continue
            text = data.decode("utf-8")
            targets = set(re.findall(r"^### (\d{3}\.\d{2})\b", text, re.M))
            h2_targets = {heading: key for heading, key in schema.SECTION_TARGETS.items()}
            targets.update(h2_targets[line[3:]] for line in text.splitlines()
                           if line.startswith("## ") and line[3:] in h2_targets)
            chapters.append(notes.Chapter(int(match.group(1)), source_path, text, targets))
        if not chapters:
            return _refuse("no complete structured-summary support exists for this audience")
    system = load_system()
    backend = resolve_cli_model(args, legacy_default=None).backend
    endpoints = list(dict.fromkeys(getattr(args, "endpoints", None) or []))
    parallel = getattr(args, "parallel", None) or 1
    if endpoints and backend != "dgx":
        return _refuse(f"--endpoints applies to --backend dgx only, not {backend}")
    if endpoints and getattr(args, "endpoint", None):
        return _refuse("give --endpoint or --endpoints, not both")
    if parallel < 1:
        return _refuse(f"--parallel must be at least 1, got {parallel}")
    chunk_chars, max_tokens = settings.chunk_chars, args.max_tokens
    plans: list[_Plan] = []
    for k, chunk in enumerate(npc_chunked.make_chunks(chapters, chunk_chars), 1):
        rng = npc_chunked.chunk_range(chunk)
        user = build_user(chunk, evidence_header=("AUTHORIZED EVIDENCE (verbatim, audience filtered):" if audience != "gm" else None))
        key = notes.cache_key(
            system=system, user=user, backend=backend, model=args.model, max_tokens=max_tokens, chunk_chars=chunk_chars,
            audience=getattr(args, "audience", "gm"),
            filtered_payload_digest=getattr(args, "authority_filtered_payload_digest", None),
            authority_policy_version=getattr(args, "authority_policy_version", None),
            authority_records_digest=getattr(args, "authority_records_digest", None),
            source_digest=getattr(args, "authority_source_digest", None),
            selection_membership_digest=getattr(args, "authority_selection", None),
        )
        plans.append(_Plan(k, chunk, rng, system, user, key, notes.chunk_stem(k, rng)))

    started = now()
    run_dir = synth._new_run_dir(freshness.audience_state_dir(range_dir, audience) / "runs", started.strftime("%Y%m%dT%H%M%SZ"))
    # Non-GM work is staged under its run until the authority manifest is
    # checked again after the final model response.  A source/ledger change
    # must never leave a newly checked chunk in the current audience view.
    published_nd = freshness.notes_dir(range_dir, audience)
    nd = published_nd
    staging = audience != "gm" and getattr(args, "authority_manifest", None) is not None
    if staging:
        nd = run_dir / "notes"
    nd.mkdir(parents=True, exist_ok=True)
    for p in plans:
        _write_if_changed(nd / f"{p.stem}.user.md", p.user)

    if endpoints:
        targets = endpoints
    elif getattr(args, "endpoint", None) and backend == "dgx":
        targets = [args.endpoint]
    else:
        targets = []  # the backend's own resolution (environment, wiring) names the box
    labels = [short(t) for t in targets] or [backend]
    facts = freshness.notes_manifest_facts(range_dir, registry_path, players_path)
    if evidence is not None:
        facts["authority_filtered_payload_sha256"] = evidence.payload_digest
    record = {
        "step": "extract",
        "run_id": run_dir.name,
        "range": {"since": since, "until": until},
        "absent_chapters": absent,
        "backend": backend,
        "model": args.model,
        "effort": getattr(args, "claude_code_effort", None),
        "max_tokens": max_tokens,
        "chunk_chars": chunk_chars,
        "endpoints": labels,
        "parallel": parallel,
        "dump_only": bool(args.dump_only),
        "force": bool(args.force),
        "audience": audience,
        "inputs": {
            **facts,
            "summaries": ([{"chapter": c.number, "sha256": hashlib.sha256(c.text.encode("utf-8")).hexdigest()} for c in chapters]
                          if audience != "gm" else
                          [{"chapter": c.number, "file": c.path.name, "sha256": corpus.sha256_file(c.path)} for c in chapters]),
        },
        "system_sha256": corpus.sha256_file(context.PROMPT_DIR / SYSTEM_PROMPT),
        "chunks": [],
        "exit_code": None,
        "started": started.isoformat(timespec="seconds"),
        "finished": None,
    }

    def save_record(code: int) -> None:
        record["exit_code"] = code
        record["finished"] = now().isoformat(timespec="seconds")
        atomic_write_text(run_dir / "record.json", _dumps(record))

    shared = {} if args.force else _range_cache(range_dir)
    outcomes: dict[int, _Outcome] = {}
    todo: list[_Plan] = []
    incomplete_cached: list[_Plan] = []
    for p in plans:
        cc = None if args.force else _read_cached(published_nd, p, shared)
        if cc is not None and cc.missing:
            # Reported from the raw output with no model call. Its checked file is removed so the next
            # run extracts this chunk alone, as it does a chunk whose call failed.
            (published_nd / f"{p.stem}.checked.json").unlink(missing_ok=True)
            outcomes[p.index] = _Outcome("failed", error=_missing_error(cc.missing), missing=cc.missing)
            incomplete_cached.append(p)
        elif cc is not None:
            outcomes[p.index] = _Outcome("cached", checked=cc)
        else:
            outcomes[p.index] = _Outcome("pending")
            todo.append(p)

    n_total = len(plans)

    def line(p: _Plan, o: _Outcome) -> str:
        c = o.checked
        kept = sum(len(c.kept(k)) for k in notes.KINDS) if c else 0
        stats = f"kept {kept} dropped {len(c.drops) if c else 0}"
        if o.status == "cached":
            return f"chunk {p.index:02d}/{n_total:02d} ch {p.chapters} cached {stats}"
        return f"chunk {p.index:02d}/{n_total:02d} ch {p.chapters} @{o.endpoint} {o.secs:.0f}s {stats}"

    for p in incomplete_cached:
        print(f"chunk {p.index:02d}/{n_total:02d} ch {p.chapters} cached INCOMPLETE: {outcomes[p.index].error}; "
              f"its saved output is not used", file=sys.stderr, flush=True)

    if args.dump_only:
        _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
        code = EXIT_INCOMPLETE if incomplete_cached else 0
        save_record(code)
        print(f"[--dump-only: {n_total} prompts written to {schema.display_path(nd, root)}; no model call]")
        if incomplete_cached:
            print(f"Error: {len(incomplete_cached)} cached chunk(s) are incomplete: "
                  f"{', '.join(p.chapters for p in incomplete_cached)}. Run without --dump-only to extract only those",
                  file=sys.stderr)
        return code

    if todo:
        def stop(msg: str) -> int:
            record["error"] = msg
            _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
            save_record(EXIT_REFUSED)
            return _refuse(msg)

        if targets:
            problem = preflight(targets, args.model)
            if problem:
                return stop(problem)
        try:
            if targets:
                clients = {short(t): client_from_args(args, endpoint=t) for t in targets}
            else:
                clients = {labels[0]: client_from_args(args)}
        except SystemExit as e:  # client_from_args fails fast with SystemExit(message)
            return stop(str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})")
        except (ValueError, RuntimeError, ImportError) as e:
            return stop(str(e))
        for label, p, o in _run_pool(
            todo, lambda c, plan, ep: _extract_one(c, plan, nd, args, ep), clients, parallel
        ):
            outcomes[p.index] = o
            if o.status == "failed":
                print(f"chunk {p.index:02d}/{n_total:02d} ch {p.chapters} @{label} FAILED after one retry: {o.error}",
                      file=sys.stderr, flush=True)
            else:
                print(line(p, o), flush=True)
    for p in plans:
        if outcomes[p.index].status == "cached":
            print(line(p, outcomes[p.index]), flush=True)

    if audience != "gm" and getattr(args, "authority_manifest", None) is not None:
        try:
            from pipelines.summary_native.authority_inputs import audience_snapshot
            _, _, current_manifest = audience_snapshot(root, audience=audience, since=since, until=until)
        except Exception:
            current_manifest = None
        if current_manifest != args.authority_manifest:
            # Prompts and raw model output are derived from a source view that
            # is no longer current.  Remove this attempt's checked artifacts
            # before any state renderer can consume them.
            record["authority_stale"] = True
            save_record(EXIT_REFUSED)
            return _refuse("authority inputs changed during extraction; rerun extract")

    if staging:
        # Publish only the staged files this run created.  Cached chunks
        # already belong to a compatible current manifest and stay in place.
        published_nd.mkdir(parents=True, exist_ok=True)
        for plan in plans:
            if outcomes[plan.index].status != "extracted":
                continue
            for suffix in ("user.md", "out.md", "checked.json"):
                staged = nd / f"{plan.stem}.{suffix}"
                if staged.is_file():
                    atomic_write_text(published_nd / staged.name, staged.read_text(encoding="utf-8"))
        nd = published_nd

    results = _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
    failed = [p for p in plans if outcomes[p.index].status == "failed"]
    n_new = sum(1 for o in outcomes.values() if o.status == "extracted")
    n_cached = sum(1 for o in outcomes.values() if o.status == "cached")
    kept = sum(len(c.notes) for c in results)
    dropped = sum(len(c.drops) for c in results)
    print(f"extracted {len(results)}/{n_total} chunks ({n_new} new, {n_cached} cached); kept {kept}, dropped {dropped}")
    if dropped:
        by: dict[str, int] = {}
        for c in results:
            for r, n in c.counts()["reasons"].items():
                by[r] = by.get(r, 0) + n
        print("drops: " + ", ".join(f"{r} {n}" for r, n in sorted(by.items())) + f" (see {schema.display_path(nd / 'drops.md', root)})")
    outliers = notes.outlier_chunks(results)
    if outliers:
        print("outlier chunks (possible runaway call): " + ", ".join(outliers))
    if absent:
        print(f"note: chapters absent from the range: {', '.join(str(n) for n in absent)}")
    code = 0
    if failed:
        called = [p for p in failed if p not in incomplete_cached]
        names = ", ".join(p.chapters for p in called)
        for p in called:
            if outcomes[p.index].missing:
                print(f"chunk {p.chapters}: {outcomes[p.index].error}", file=sys.stderr)
        # exit 4 means the backend could not be reached; a model that answered, incompletely, reached it
        # (a chunk found incomplete in the cache made no call, so it says nothing about the backend)
        if called and not n_new and not n_cached and not any(outcomes[p.index].missing for p in called):
            print(
                f"Error: no chunk could be extracted: the backend could not be reached or rejected every call "
                f"(see {schema.display_path(run_dir / 'record.json', root)})",
                file=sys.stderr,
            )
            code = EXIT_MODEL_FAILED
        else:
            what = []
            if called:
                what.append(f"{len(called)} chunk(s) failed (a call that failed twice, or an output missing "
                            f"outline sections, retried once): {names}")
            if incomplete_cached:
                what.append(f"{len(incomplete_cached)} cached chunk(s) found incomplete, not called: "
                            + ", ".join(p.chapters for p in incomplete_cached))
            print(
                f"Error: {'; '.join(what)}. The notes are incomplete; "
                f"run the same command again to extract only those",
                file=sys.stderr,
            )
            code = EXIT_INCOMPLETE
    save_record(code)
    return code


def _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record) -> list[notes.CheckedChunk]:
    """Write the manifest and ``drops.md`` from what is on disk, prune stale chunk files and fill the
    record's chunk list. Returns the checked chunks in order (those that have one)."""
    results, entries, rec_chunks = [], [], []
    for p in plans:
        o = outcomes[p.index]
        cc = o.checked
        status = "checked" if cc is not None else ("failed" if o.status == "failed" else "pending")
        if cc is not None:
            results.append(cc)
        kept = sum(len(cc.kept(k)) for k in notes.KINDS) if cc else 0
        dropped = len(cc.drops) if cc else 0
        entries.append({
            "index": p.index, "chapters": p.chapters, "numbers": p.numbers, "chars": p.chars,
            "cache_key": p.key, "status": status, "kept": kept, "dropped": dropped,
        })
        rec = {"index": p.index, "chapters": p.chapters, "chars": p.chars, "cache_key": p.key,
               "status": o.status, "secs": round(o.secs, 1), "endpoint": o.endpoint, "kept": kept, "dropped": dropped}
        if o.error:
            rec["error"] = o.error
        if o.missing:
            rec["missing_sections"] = o.missing
        rec_chunks.append(rec)
    record["chunks"] = rec_chunks
    complete = all(e["status"] == "checked" for e in entries)
    manifest = {
        "kind": "state_notes",
        "schema": 1,
        "complete": complete,
        "range": {"since": since, "until": until},
        "absent_chapters": absent,
        "backend": backend,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "chunk_chars": settings.chunk_chars,
        "system_sha256": record["system_sha256"],
        "audience": getattr(args, "audience", "gm"),
        **facts,
        "chunks": entries,
    }
    keep = {f"{p.stem}.{ext}" for p in plans for ext in ("user.md", "out.md", "checked.json")}
    for f in nd.iterdir():
        if _CHUNK_FILE_RE.match(f.name) and f.name not in keep:
            f.unlink()
    incomplete = [(p.chapters, outcomes[p.index].missing) for p in plans if outcomes[p.index].missing]
    _write_if_changed(nd / "drops.md", notes.render_drops_md(results, incomplete))
    _write_if_changed(nd / freshness.NOTES_MANIFEST, _dumps(manifest))
    return results
