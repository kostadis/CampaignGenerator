#!/usr/bin/env python3
"""Five-pass ensemble fact extractor (generation half of the pipeline).

Runs ``extract_facts.py`` once per lens, fanned across endpoints with
caching/speculation/timeouts, and writes each pass's facts plus a
``manifest.json``. The dispatcher keeps one unit per endpoint; within a unit,
``--chunk-parallel`` (default 4, matching the Sparks' vLLM ``--max-num-seqs``)
keeps that many chunk requests in flight, so vLLM's continuous batching is
actually fed. Merging is a SEPARATE step — see ``ensemble_merge.py``,
which consumes the manifest — so a generation can be re-merged (subject merge,
nomic-embedding merge, different thresholds) without re-extracting. The
``ensemble.py`` driver runs both halves.

Passes:

1. ``small``       — generalist prompt at 6,000-char chunks. Catches action
                     granularity (per-attack, per-spell, per-line-of-dialogue
                     detail) that larger chunks blur.
2. ``large``       — generalist prompt at 15,000-char chunks. Catches scene
                     setup, room descriptions, and cross-paragraph relations
                     that small chunks fragment.
3. ``sweep``       — sweep prompt at 15,000-char chunks. Exhaustive
                     proper-noun, object, and monster enumeration that the
                     generalist deprioritizes (Vof Klownits, Sava game,
                     Tongue of Madness, referenced-but-absent NPCs).
4. ``temporal``    — temporal/numeric anchor prompt at 15,000-char chunks.
                     Catches dates, counts, durations, distances, and
                     values that other passes drop ("5th day of 2nd Tenday
                     of Taraskh 1493", "100 feet above the cavern floor",
                     "eight days away via the Darklake").
5. ``interiority`` — character-interiority prompt at 15,000-char chunks.
                     Catches thoughts, feelings, memories, refusals, and
                     mutterings that action-focused passes skip ("Sarith
                     experiences bouts of madness", "Daz refused to wear
                     armor", "Grygum recalled the Giants").

Each pass writes its own ``facts_NNN.json`` cache under
``<workdir>/cache/<pass_name>/`` and a per-pass ``<name>.json`` of facts.
Re-runs reuse cached chunks, so resuming (or fixing one bad chunk) is cheap.
``manifest.json`` maps each pass to its output file + source document, and is
the handoff to ``ensemble_merge.py``.

Run plans (``--plan``): instead of the built-in 5-lens plan against a single
input, an extract-plan YAML can declare arbitrary passes, each reading its own
``document`` — e.g. the 5 lenses against ``session-summary.md`` plus an extra
``interiority`` pass against ``gm-assist-doc.md`` (6 passes total). The plan
holds passes + documents only; merge settings live in a separate merge-config
YAML consumed by ``ensemble_merge.py``. See ``--plan`` in ``--help``.

Usage:

    python ensemble_extract.py session.md --workdir runs/session_001/
    python ensemble_merge.py --workdir runs/session_001/ --config merge.yaml

Re-run safely — caches make it cheap.
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

EXTRACT_SCRIPT = Path(__file__).resolve().parent / "extract_facts.py"


def build_extract_cmd(input_path: Path, pass_spec: dict, output_path: Path,
                      extract_dir: Path, endpoint: str | None,
                      model: str | None, chunk_parallel: int = 1) -> list[str]:
    """Build the extract_facts.py command line for one unit. Pure function —
    all the subprocess/bookkeeping mutation lives in run_unit."""
    cmd = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        str(input_path),
        "--output", str(output_path),
        "--extract-dir", str(extract_dir),
        "--chunk-size", str(pass_spec["chunk_size"]),
        "--agent", pass_spec["agent"],
        "--parallel", str(chunk_parallel),
    ]
    if endpoint:
        cmd += ["--dgx-endpoint", endpoint]
    if model:
        cmd += ["--model", model]
    if pass_spec.get("annotate_pov"):
        cmd += ["--annotate-pov"]
    return cmd

PASSES = [
    {"name": "small",       "chunk_size": 6000,  "agent": "extract_facts"},
    {"name": "large",       "chunk_size": 15000, "agent": "extract_facts"},
    {"name": "sweep",       "chunk_size": 15000, "agent": "extract_facts_sweep"},
    {"name": "temporal",    "chunk_size": 15000, "agent": "extract_facts_temporal"},
    {"name": "interiority", "chunk_size": 15000, "agent": "extract_facts_interiority"},
]


def run_unit(
    input_path: Path, pass_spec: dict, k: int, samples: int, workdir: Path,
    endpoint: str | None, model: str | None,
    register_proc=None, is_cancelled=None, timeout: float | None = None,
    chunk_parallel: int = 1,
) -> tuple[str, list[dict] | None, str | None, bool]:
    """Run ONE (lens, sample) unit on `endpoint`.

    Returns (key, facts, error, timed_out). `key` is f"{lens}#{k}". On success
    `error` is None; on failure `facts` is None and `error` describes it.
    `timed_out` is True only when the subprocess exceeded `timeout` and was
    killed — the dispatcher re-queues those (a degraded endpoint usually
    recovers on a fresh connection) rather than failing the whole run.

    A completed, parseable unit output is reused verbatim, so an
    interrupted/resumed run skips finished units instantly. Each sample has its
    own cache dir so a resume does not collapse the samples into one identical
    cached result.

    `register_proc(proc)`, if given, is called with the live `Popen` the moment
    the subprocess starts, so the dispatcher can terminate a losing speculative
    copy. `is_cancelled()`, if given, is polled just before launch — if the unit
    has already been won by another endpoint we skip spawning entirely.
    """
    name = pass_spec["name"]
    single = samples == 1
    output_path = workdir / (f"{name}.json" if single else f"{name}.s{k}.json")
    extract_dir = workdir / "cache" / (name if single else f"{name}/s{k}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    key = f"{name}#{k}"
    label = name if single else f"{name} s{k}"

    if output_path.exists():
        try:
            facts = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"  [cached] {label:20s} {len(facts):>3} facts")
            return key, facts, None, False
        except json.JSONDecodeError:
            pass  # corrupt/partial — regenerate below

    cmd = build_extract_cmd(input_path, pass_spec, output_path, extract_dir,
                            endpoint, model, chunk_parallel)

    where = endpoint or "default endpoint"
    if is_cancelled and is_cancelled():
        return key, None, f"pass {name!r} sample {k}: cancelled before launch", False
    print(f"  [start ] {label:20s} -> {where}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if register_proc:
        register_proc(proc)
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The endpoint is dribbling tokens or wedged. Kill this copy and tell
        # the dispatcher to re-queue the unit — do NOT let it block forever.
        proc.kill()
        try:
            proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        return key, None, (
            f"pass {name!r} sample {k} on {where} exceeded {timeout:.0f}s "
            f"wall-clock and was killed"
        ), True
    if proc.returncode != 0:
        # A non-zero exit is either a genuine failure (bad chunk) or a
        # speculative loser that the dispatcher terminated. The dispatcher
        # drops the error if the unit is already settled, so we report both
        # the same way here.
        tail = "\n    ".join((stderr or "").strip().splitlines()[-3:])
        return key, None, (
            f"pass {name!r} sample {k} on {where} failed (exit "
            f"{proc.returncode}); fix the failing chunk in {extract_dir} "
            f"and re-run.\n    {tail}"
        ), False
    try:
        facts = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return key, None, f"pass {name!r} sample {k}: cannot read {output_path}: {e}", False
    print(f"  [done  ] {label:20s} {len(facts):>3} facts  ({where})")
    return key, facts, None, False


def pick_straggler(inflight: dict, settled: set, now: float,
                   min_age: float, max_copies: int) -> str | None:
    """Return the key of the longest-running in-flight unit eligible for a
    speculative duplicate, or None.

    Eligible = not yet settled, currently running on fewer than `max_copies`
    endpoints, and running for at least `min_age` seconds (so freshly-started
    units are never needlessly duplicated). Picking the OLDEST eligible unit
    targets the actual tail straggler. Pure function — all mutation of the
    in-flight bookkeeping happens in the caller under the lock.
    """
    cands = [
        (info["start"], key)
        for key, info in inflight.items()
        if key not in settled
        and info["copies"] < max_copies
        and (now - info["start"]) >= min_age
    ]
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the ensemble extraction plan (GENERATION only): the built-in "
            "5 lenses (small/large/sweep/temporal/interiority) or a --plan, "
            "optionally with self-consistency samples, fanned across multiple "
            "endpoints concurrently. Writes per-pass facts + manifest.json; "
            "merge the result separately with ensemble_merge.py."
        )
    )
    parser.add_argument("input", nargs="?",
                        help="Default input text file (session summary, chapter, "
                             "...). Optional when --plan gives every pass its own "
                             "'document'; otherwise required.")
    parser.add_argument("--workdir", "-w", required=True, metavar="DIR",
                        help="Working directory for per-pass outputs and caches.")
    parser.add_argument("--plan", metavar="YAML",
                        help="Extract-plan YAML that overrides the built-in "
                             "5-lens plan. Shape: a 'passes' list where each pass "
                             "has name/agent/chunk_size and may name its own "
                             "'document' (so e.g. 5 lenses on the summary + an "
                             "interiority pass on the gm-assist doc); an optional "
                             "top-level 'document' is the default for passes that "
                             "omit one. Merge settings are NOT here — they live "
                             "in a separate merge-config YAML for ensemble_merge.py. "
                             "Relative document paths resolve against the plan "
                             "file's directory.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Resolve and print the plan (passes, per-pass "
                             "documents) without extracting.")
    parser.add_argument("--skip", action="append", default=[], metavar="NAME",
                        help="Skip a named pass (can repeat). Useful when "
                             "iterating on prompt fixes for one lens. Applies to "
                             "built-in and --plan pass names alike.")
    parser.add_argument("--samples", type=int, default=1, metavar="N",
                        help="Self-consistency: run each pass N times and union "
                             "the results (default 1). Extraction is "
                             "nondeterministic (no fixed temperature/seed), so "
                             "re-sampling recovers facts a single run misses. The "
                             "merge step records 'n_samples' per fact — a "
                             "confidence signal for human review; nothing is "
                             "auto-filtered.")
    parser.add_argument("--endpoints", nargs="+", metavar="URL",
                        help="One or more OpenAI-compatible endpoints to fan the "
                             "work across CONCURRENTLY (one in-flight unit per "
                             "endpoint, work-stealing from a shared queue for "
                             "balance). Example: --endpoints "
                             "http://192.168.1.147:8001/v1 "
                             "http://192.168.1.69:8001/v1 runs the ensemble across "
                             "both DGX Sparks. Default: a single endpoint from "
                             "$DGX_ENDPOINT (else extract_facts.py's built-in "
                             "default). All endpoints MUST serve the same --model.")
    parser.add_argument("--model", default=None, metavar="ID",
                        help="Model id sent to every endpoint (default: $DGX_MODEL, "
                             "else extract_facts.py's default). All endpoints must "
                             "serve this same model id, since the merge treats "
                             "their facts uniformly.")
    parser.add_argument("--chunk-parallel", type=int, default=4, metavar="N",
                        help="In-flight chunk requests per endpoint, forwarded "
                             "to each extract_facts.py as --parallel (default "
                             "4). The dispatcher runs one unit per endpoint, so "
                             "this IS the per-Spark concurrency; the Sparks "
                             "serve vLLM --max-num-seqs 4, so 4 saturates a box "
                             "without server-side queueing. Use 1 for the old "
                             "sequential behaviour.")
    parser.add_argument("--pass-parallel", type=int, default=None, metavar="N",
                        help="Number of passes to run concurrently (default: "
                             "one per endpoint). Set higher than the endpoint "
                             "count to parallelise passes on a single endpoint — "
                             "e.g. --pass-parallel 5 runs all five passes of a "
                             "chapter simultaneously, each sending --chunk-parallel "
                             "chunks to the same vLLM server.")
    parser.add_argument("--speculative", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Speculative re-execution / straggler mitigation "
                             "(default ON, needs 2+ endpoints). When the work "
                             "queue drains but a unit is still running on a slow "
                             "endpoint, a free endpoint re-runs that straggler and "
                             "the run takes whichever copy finishes first (the "
                             "loser is terminated). Stops the tail of a run waiting "
                             "1h+ on one starved Spark. Use --no-speculative for "
                             "attended runs where you may grab a Spark mid-job and "
                             "prefer to just wait the unit out.")
    parser.add_argument("--spec-min-age", type=float, default=60.0, metavar="SEC",
                        help="Only speculatively duplicate a unit that has already "
                             "been running this many seconds (default 60). Guards "
                             "against duplicating units that are merely normal-slow, "
                             "not stalled.")
    parser.add_argument("--unit-timeout", type=float, default=600.0, metavar="SEC",
                        help="Per-unit wall-clock cap (default 600). A unit whose "
                             "subprocess exceeds this is killed and re-queued — a "
                             "degraded endpoint that dribbles tokens toward "
                             "max_tokens usually recovers on a fresh connection, "
                             "and a re-queued unit can land on the healthy box. "
                             "After --unit-retries timeouts the unit fails the run. "
                             "0 disables the cap (unbounded — the old behaviour). "
                             "With --chunk-parallel 4 healthy units finish ~4x "
                             "sooner; ~300 is reasonable for attended runs.")
    parser.add_argument("--unit-retries", type=int, default=3, metavar="N",
                        help="Max times a single unit may time out and be re-queued "
                             "before it fails the run (default 3).")
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # The positional input is the DEFAULT document; each pass may override it.
    default_input = Path(args.input).expanduser().resolve() if args.input else None

    # ── Resolve the pass list ────────────────────────────────────────────────
    # No --plan  → the built-in 5-lens PASSES, all reading `default_input`.
    # With --plan → passes come from YAML, each optionally naming its own
    # `document` (e.g. 5 lenses on the summary + interiority on the gm-assist
    # doc). A top-level plan `document:` is the default for passes without one;
    # relative document paths resolve against the plan file's directory.
    if args.plan:
        import yaml
        plan_path = Path(args.plan).expanduser().resolve()
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        plan_dir = plan_path.parent
        plan_default_doc = plan.get("document")

        def _resolve_doc(doc: str) -> Path:
            p = Path(doc).expanduser()
            return (p if p.is_absolute() else plan_dir / p).resolve()

        raw_passes = plan.get("passes") or []
        if not raw_passes:
            print(f"Error: plan {plan_path} defines no 'passes'.", file=sys.stderr)
            sys.exit(1)
        active_passes = []
        for i, p in enumerate(raw_passes):
            name = p.get("name")
            if not name:
                print(f"Error: plan pass #{i + 1} has no 'name'.", file=sys.stderr)
                sys.exit(1)
            doc = p.get("document", plan_default_doc)
            if doc is not None:
                ip = _resolve_doc(doc)
            elif default_input is not None:
                ip = default_input
            else:
                print(f"Error: plan pass {name!r} sets no 'document' and no "
                      f"positional input was given to fall back on.",
                      file=sys.stderr)
                sys.exit(1)
            active_passes.append({
                "name": name,
                "agent": p.get("agent", "extract_facts"),
                "chunk_size": int(p.get("chunk_size", 15000)),
                "annotate_pov": bool(p.get("annotate_pov", False)),
                "input_path": ip,
            })
    else:
        if default_input is None:
            print("Error: an input file is required (positional) unless --plan "
                  "supplies per-pass documents.", file=sys.stderr)
            sys.exit(1)
        active_passes = [{**p, "input_path": default_input} for p in PASSES]

    # --skip applies by name to built-in and plan passes alike.
    active_passes = [p for p in active_passes if p["name"] not in args.skip]
    if not active_passes:
        print("Error: no passes selected (all skipped).", file=sys.stderr)
        sys.exit(1)

    # Pass names key the per-pass output files / cache dirs — must be unique.
    names = [p["name"] for p in active_passes]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(f"Error: duplicate pass name(s): {', '.join(dupes)}. Names must be "
              f"unique (they key the output files).", file=sys.stderr)
        sys.exit(1)

    # Every pass's document must exist.
    for p in active_passes:
        if not p["input_path"].exists():
            print(f"Error: input not found for pass {p['name']!r}: "
                  f"{p['input_path']}", file=sys.stderr)
            sys.exit(1)

    # ── Header ───────────────────────────────────────────────────────────────
    print(f"Workdir:  {workdir}")
    docs = {p["input_path"] for p in active_passes}
    if len(docs) == 1:
        print(f"Input:    {next(iter(docs))}")
        print(f"Passes:   {', '.join(p['name'] for p in active_passes)}")
    else:
        print("Passes (per-document):")
        for p in active_passes:
            print(f"  {p['name']:24s} <- {p['input_path']}")
    if args.skip:
        print(f"Skipped:  {', '.join(args.skip)}")
    if args.samples > 1:
        print(f"Samples:  {args.samples} per pass (self-consistency union)")

    # Resolve the endpoint pool. One endpoint → the old sequential behaviour;
    # several → units fan out concurrently (one in-flight unit per endpoint,
    # pulled work-stealing from a shared queue, so a faster/free box grabs the
    # next unit instead of idling). [None] means "no explicit endpoint" — each
    # extract_facts.py falls back to $DGX_ENDPOINT or its own default.
    endpoints = args.endpoints if args.endpoints else [os.environ.get("DGX_ENDPOINT")]
    model = args.model or os.environ.get("DGX_MODEL")

    units = [(p, k) for p in active_passes for k in range(1, args.samples + 1)]
    print(f"Endpoints: {', '.join(e or 'default' for e in endpoints)}")
    print(f"Units:    {len(units)} ({len(active_passes)} passes x {args.samples} "
          f"sample(s)) across {len(endpoints)} endpoint(s)")
    print(f"Chunk-parallel: {args.chunk_parallel} per endpoint")
    print("=" * 70)
    if args.dry_run:
        print("[dry-run] plan resolved; no extraction performed.")
        return

    MAX_COPIES = 2          # original + at most one speculative duplicate
    POLL = 2.0              # seconds a free worker waits before re-checking
    unit_timeout = args.unit_timeout if args.unit_timeout > 0 else None
    speculative = args.speculative and len(endpoints) > 1
    if args.speculative and len(endpoints) > 1:
        print(f"Speculative re-execution: ON (min-age {args.spec_min_age:.0f}s)")
    elif args.speculative:
        print("Speculative re-execution: off (needs 2+ endpoints)")
    else:
        print("Speculative re-execution: disabled (--no-speculative)")
    if unit_timeout:
        print(f"Per-unit timeout: {unit_timeout:.0f}s "
              f"(re-queue up to {args.unit_retries}x on timeout)")
    else:
        print("Per-unit timeout: disabled (unbounded)")

    total = len(units)
    work = queue.Queue()
    for u in units:
        work.put(u)
    results: dict[str, list[dict]] = {}
    errors_by_key: dict[str, list[str]] = {}
    settled: set[str] = set()        # keys with a successful result
    failed: set[str] = set()         # keys with a real (non-loser) error, not settled
    cancelled: set[str] = set()      # keys won elsewhere — losers skip/abort
    timeouts: dict[str, int] = {}    # key -> how many times it has timed out
    inflight: dict[str, dict] = {}   # key -> {start, copies, procs, unit}
    lock = threading.Lock()

    def next_task(endpoint: str | None):
        """Decide what a now-free `endpoint` should do, under the lock.

        Returns ("run", pass_spec, k, key, is_spec) | ("wait",) | ("stop",).
        Fresh queued work always wins; only once the queue is empty do we
        consider a speculative duplicate of the tail straggler.
        """
        with lock:
            try:
                pass_spec, k = work.get_nowait()
                key = f"{pass_spec['name']}#{k}"
                info = inflight.get(key)
                if info is not None:
                    # A re-queued (previously timed-out) unit whose earlier copy
                    # may still be winding down — add a copy, keep the older
                    # start so it stays straggler-eligible.
                    info["copies"] += 1
                else:
                    inflight[key] = {"start": time.time(), "copies": 1,
                                     "procs": set(), "unit": (pass_spec, k)}
                return ("run", pass_spec, k, key, False)
            except queue.Empty:
                pass
            if not speculative:
                return ("stop",)                 # old behaviour: free worker exits
            if len(settled) + len(failed) >= total:
                return ("stop",)
            key = pick_straggler(inflight, settled, time.time(),
                                 args.spec_min_age, MAX_COPIES)
            if key is not None:
                info = inflight[key]
                info["copies"] += 1
                pass_spec, k = info["unit"]
                return ("run", pass_spec, k, key, True)
            return ("wait",)                     # nothing to do yet — not done

    def worker(endpoint: str | None) -> None:
        while True:
            action = next_task(endpoint)
            if action[0] == "stop":
                return
            if action[0] == "wait":
                time.sleep(POLL)
                continue
            _, pass_spec, k, key, is_spec = action
            if is_spec:
                with lock:
                    age = time.time() - inflight[key]["start"] if key in inflight else 0
                print(f"  [spec  ] re-run straggler {key:18s} -> "
                      f"{endpoint or 'default'} (age {age:.0f}s)")

            myproc: dict = {"p": None}

            def register(p, _key=key):
                myproc["p"] = p
                with lock:
                    info = inflight.get(_key)
                    if info is not None:
                        info["procs"].add(p)

            try:
                _, facts, err, timed_out = run_unit(
                    pass_spec["input_path"], pass_spec, k, args.samples, workdir, endpoint, model,
                    register_proc=register, is_cancelled=lambda _key=key: _key in cancelled,
                    timeout=unit_timeout, chunk_parallel=args.chunk_parallel)
            except Exception as e:  # a worker must never die silently
                facts, err, timed_out = None, repr(e), False

            with lock:
                info = inflight.get(key)
                p = myproc["p"]
                if info is not None:
                    if p is not None:
                        info["procs"].discard(p)
                    info["copies"] -= 1
                    if info["copies"] <= 0 and not info["procs"]:
                        inflight.pop(key, None)
                if timed_out and key not in settled:
                    # A degraded endpoint, not a bad chunk. Re-queue the unit up
                    # to --unit-retries times; only then does it fail the run.
                    timeouts[key] = timeouts.get(key, 0) + 1
                    if timeouts[key] <= args.unit_retries:
                        print(f"  [retry ] {key:18s} timed out "
                              f"({timeouts[key]}/{args.unit_retries}) — re-queued")
                        work.put((pass_spec, k))
                    else:
                        errors_by_key.setdefault(key, []).append(err)
                        failed.add(key)
                elif err:
                    if key not in settled:       # a settled key's error = killed loser
                        errors_by_key.setdefault(key, []).append(err)
                        failed.add(key)
                elif key not in settled:
                    results[key] = facts
                    settled.add(key)
                    failed.discard(key)
                    cancelled.add(key)           # tell any other copy it has lost
                    if info is not None:         # terminate the straggler we just beat
                        for loser in list(info["procs"]):
                            try:
                                loser.terminate()
                            except Exception:
                                pass

    t0 = time.time()
    n_workers = args.pass_parallel if args.pass_parallel is not None else len(endpoints)
    threads = [threading.Thread(target=worker, args=(endpoints[i % len(endpoints)],), daemon=True)
               for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    real_errors = [e for key in failed if key not in settled
                   for e in errors_by_key.get(key, [])]
    if real_errors:
        print(f"\n{len(real_errors)} unit(s) failed:", file=sys.stderr)
        for e in real_errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nExtraction wall-clock: {elapsed:.0f}s across {len(endpoints)} endpoint(s)")

    # Write the handoff manifest the merge step (ensemble_merge.py) consumes.
    # Per-pass *.json already exist on disk (run_unit -> extract_facts --output);
    # we record the mapping (provenance key, file, document) only. File naming
    # mirrors run_unit: single sample -> {name}.json, multi -> {name}.s{k}.json.
    single = args.samples == 1
    manifest = {
        "version": 1,
        "samples": args.samples,
        "default_input": str(default_input) if default_input else None,
        "passes": [],
    }
    for p in active_passes:
        outs = []
        for k in range(1, args.samples + 1):
            key = f"{p['name']}#{k}"
            fname = f"{p['name']}.json" if single else f"{p['name']}.s{k}.json"
            outs.append({"key": key, "file": fname,
                         "n_facts": len(results.get(key, []))})
        manifest["passes"].append({
            "name": p["name"], "agent": p["agent"],
            "chunk_size": p["chunk_size"], "document": str(p["input_path"]),
            "outputs": outs,
        })
    manifest_path = workdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    counts_by_lens: dict[str, int] = {}
    for key, facts in results.items():
        lens = key.split("#")[0]
        counts_by_lens[lens] = counts_by_lens.get(lens, 0) + len(facts)

    print("\n" + "=" * 70)
    print(f"Per-lens facts (raw, summed over samples): {counts_by_lens}")
    print(f"Passes generated: {len(active_passes)}  (samples: {args.samples})")
    print(f"\nManifest: {manifest_path}")
    print(f"Next: python ensemble_merge.py --workdir {workdir} "
          f"[--config merge.yaml | --method subject|embed]")


if __name__ == "__main__":
    main()
