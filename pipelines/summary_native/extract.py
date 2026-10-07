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

Chunks are dispatched by :func:`_run_pool`. It takes ``{endpoint label: client}`` and a worker
count per endpoint so a shared queue over several endpoints (T042) replaces its body and nothing
else.
"""

from __future__ import annotations

import json
import re
import sys
import time
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


def build_user(chunk) -> str:
    """The user prompt for one chunk: its chapters verbatim, then the outline. Nothing else: no
    tracking-file items, no audit questions (FR-027)."""
    return (
        f"CHAPTERS IN THIS CHUNK: {npc_chunked.chunk_range(chunk)}\n\n"
        "EVIDENCE (the GM-reviewed session summaries for these chapters, verbatim):\n"
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


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text(encoding="utf-8") == text:
            return
    except OSError:
        pass
    atomic_write_text(path, text)


def _read_cached(nd: Path, plan: _Plan) -> notes.CheckedChunk | None:
    """The checked result of an earlier extraction of exactly this chunk (same cache key), re-checked
    from the raw output so a change to the check applies without a new model call."""
    try:
        data = json.loads((nd / f"{plan.stem}.checked.json").read_text(encoding="utf-8"))
        raw = (nd / f"{plan.stem}.out.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("cache_key") != plan.key:
        return None
    cc = notes.check_chunk(raw, plan.chunk, plan.chapters)
    _write_checked(nd, plan, cc)
    return cc


def _write_checked(nd: Path, plan: _Plan, cc: notes.CheckedChunk) -> None:
    _write_if_changed(nd / f"{plan.stem}.checked.json", _dumps({**cc.to_dict(), "cache_key": plan.key}))


def _extract_one(client, plan: _Plan, nd: Path, args, endpoint: str) -> _Outcome:
    """One chunk: the call (retried once), the raw output on disk, the code check, the checked file."""
    error = None
    for attempt in (1, 2):
        t0 = time.monotonic()
        try:
            raw = render_part(client, plan.system, plan.user, args.model, args.max_tokens)
            break
        except Exception as e:  # noqa: BLE001 - any backend error is a failed chunk
            error = f"{type(e).__name__}: {e}"
            if attempt == 2:
                return _Outcome("failed", time.monotonic() - t0, endpoint, None, error)
    secs = time.monotonic() - t0
    atomic_write_text(nd / f"{plan.stem}.out.md", raw)
    cc = notes.check_chunk(raw, plan.chunk, plan.chapters)
    _write_checked(nd, plan, cc)
    return _Outcome("extracted", secs, endpoint, cc)


def _run_pool(todo: list[_Plan], work, clients: dict[str, object], per_endpoint: int = 1):
    """Yield ``(endpoint label, plan, outcome)`` as each chunk finishes.

    ``clients`` maps an endpoint label to its client; ``per_endpoint`` is the number of concurrent
    calls each may carry. Today there is one client and the chunks run in order. The multi-endpoint
    shared queue (T042) replaces this body; ``work(client, plan, endpoint)`` and the callers stay.
    """
    (label, client), = clients.items()
    for plan in todo:
        yield label, plan, work(client, plan, label)


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
    if report.blocking_count:
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

    system = load_system()
    backend = resolve_cli_model(args, legacy_default=None).backend
    chunk_chars, max_tokens = settings.chunk_chars, args.max_tokens
    plans: list[_Plan] = []
    for k, chunk in enumerate(npc_chunked.make_chunks(chapters, chunk_chars), 1):
        rng = npc_chunked.chunk_range(chunk)
        user = build_user(chunk)
        key = notes.cache_key(
            system=system, user=user, backend=backend, model=args.model, max_tokens=max_tokens, chunk_chars=chunk_chars
        )
        plans.append(_Plan(k, chunk, rng, system, user, key, notes.chunk_stem(k, rng)))

    nd = freshness.notes_dir(range_dir)
    nd.mkdir(parents=True, exist_ok=True)
    for p in plans:
        _write_if_changed(nd / f"{p.stem}.user.md", p.user)

    started = now()
    run_dir = synth._new_run_dir(Path(range_dir) / schema.STATE_DIR / "runs", started.strftime("%Y%m%dT%H%M%SZ"))
    endpoint_label = short(args.endpoint) if getattr(args, "endpoint", None) and backend == "dgx" else backend
    facts = freshness.notes_manifest_facts(range_dir, registry_path, players_path)
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
        "endpoints": [endpoint_label],
        "parallel": 1,
        "dump_only": bool(args.dump_only),
        "force": bool(args.force),
        "inputs": {
            **facts,
            "summaries": [{"chapter": c.number, "file": c.path.name, "sha256": corpus.sha256_file(c.path)} for c in chapters],
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

    outcomes: dict[int, _Outcome] = {}
    todo: list[_Plan] = []
    for p in plans:
        cc = None if args.force else _read_cached(nd, p)
        if cc is not None:
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

    if args.dump_only:
        _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
        save_record(0)
        print(f"[--dump-only: {n_total} prompts written to {schema.display_path(nd, root)}; no model call]")
        return 0

    if todo:
        try:
            client = client_from_args(args)
        except SystemExit as e:  # client_from_args fails fast with SystemExit(message)
            msg = str(e.code) if isinstance(e.code, str) else f"backend setup failed (exit {e.code})"
            record["error"] = msg
            _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
            save_record(EXIT_REFUSED)
            return _refuse(msg)
        except (ValueError, RuntimeError, ImportError) as e:
            record["error"] = str(e)
            _finish(nd, plans, outcomes, args, backend, settings, absent, facts, since, until, record)
            save_record(EXIT_REFUSED)
            return _refuse(str(e))
        for label, p, o in _run_pool(
            todo, lambda c, plan, ep: _extract_one(c, plan, nd, args, ep), {endpoint_label: client}, 1
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
        names = ", ".join(p.chapters for p in failed)
        if not n_new and not n_cached:
            print(
                f"Error: no chunk could be extracted: the backend could not be reached or rejected every call "
                f"(see {schema.display_path(run_dir / 'record.json', root)})",
                file=sys.stderr,
            )
            code = EXIT_MODEL_FAILED
        else:
            print(
                f"Error: {len(failed)} chunk(s) failed after one retry: {names}. The notes are incomplete; "
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
        **facts,
        "chunks": entries,
    }
    keep = {f"{p.stem}.{ext}" for p in plans for ext in ("user.md", "out.md", "checked.json")}
    for f in nd.iterdir():
        if _CHUNK_FILE_RE.match(f.name) and f.name not in keep:
            f.unlink()
    _write_if_changed(nd / "drops.md", notes.render_drops_md(results))
    _write_if_changed(nd / freshness.NOTES_MANIFEST, _dumps(manifest))
    return results
