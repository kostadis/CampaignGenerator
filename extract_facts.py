#!/usr/bin/env python3
"""Extract a flat JSON list of campaign facts from a session summary using a local LLM.

Reads a long campaign-related text (session summary, canonical timeline, etc.),
chunks it, calls a local OpenAI-compatible endpoint (default: vllm-chat on the
DGX Spark) per chunk with a JSON-emitting prompt, and writes a single
``facts.json`` array.

Stops at JSON — no synthesize pass. The human reviews ``facts.json`` and
decides what to do with it downstream (per the LLM Pipeline Design Rule:
extract → human reviews → render later).

Each fact looks like::

    {
      "type": "npc" | "faction" | "event" | "location" | "thread",
      "subject": "<entity name or short label>",
      "fact":    "<one self-contained sentence>",
      "source_quote": "<verbatim snippet from input, or empty string>"
    }

Per-chunk JSON files are cached so a partial run can be resumed (re-run with
the same ``--extract-dir`` to skip already-extracted chunks). If a chunk's
output won't parse as JSON the raw text is saved alongside as ``*.raw.txt``
and the script exits nonzero — fix the file by hand and re-run. Sequentially
(the default) that exit is immediate; with ``--parallel N`` the other in-flight
chunks finish and cache first, so the re-run resumes from the fix alone.

``--parallel N`` keeps N chunk requests in flight at once. vLLM
continuous-batches concurrent sequences, so aggregate throughput scales
near-linearly up to the server's ``--max-num-seqs`` (4 on the Sparks).

Usage::

    python extract_facts.py summaries.md --output facts.json
    python extract_facts.py summaries.md --output facts.json --chunk-size 20000
    DGX_ENDPOINT=http://192.168.1.147:8001/v1 \\
      DGX_MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 \\
      python extract_facts.py summaries.md --output facts.json
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from campaignlib import (
    load_agent_prompt,
    make_client,
    prepare_chunks,
    stream_api,
)

DEFAULT_ENDPOINT = "http://192.168.1.147:8001/v1"
DEFAULT_MODEL = "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"

ALLOWED_TYPES = {"npc", "faction", "event", "location", "object", "monster", "thread", "date"}


def _salvage_objects(text: str) -> list[dict]:
    """Scan text for balanced { ... } blocks and parse each independently.

    Used when the whole-array parse fails because of a single malformed object
    (typical local-model failures: unescaped quotes inside a string, ellipsis-
    stitched source quotes, trailing commas). String-aware brace counting so
    we don't get confused by `{` or `}` inside string values.
    """
    objects: list[dict] = []
    depth = 0
    start: int | None = None
    in_string = False
    escape = False
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                snippet = text[start : i + 1]
                try:
                    obj = json.loads(snippet)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    objects.append(obj)
                start = None
    return objects


_FIELD_LINE = re.compile(r'^(\s*"[a-z_]+"\s*:\s*")(.*)(",?\s*)$')


def _repair_unescaped_quotes(text: str) -> str:
    """Escape bare quotes inside single-line ``"field": "value"`` pairs.

    The commonest local-model JSON fault: dialogue copied verbatim into a
    string value without escaping its quotation marks. One bare quote flips
    string-parity for everything after it, so even ``_salvage_objects``'s
    string-aware scan desyncs and recovers nothing. Line-based repair works
    because the models emit pretty-printed one-field-per-line output; lines
    that don't match the pattern pass through untouched.
    """
    fixed = []
    for line in text.splitlines():
        m = _FIELD_LINE.match(line)
        if m and '"' in m.group(2):
            body = m.group(2).replace('\\"', '"').replace('"', '\\"')
            line = m.group(1) + body + m.group(3)
        fixed.append(line)
    return "\n".join(fixed)


def parse_facts_block(raw: str) -> list[dict]:
    """Extract a JSON facts array from a model response. Tolerant of fences/preamble.

    Local models sometimes wrap JSON in ```json fences, prepend a short
    explanation, or emit a single malformed object inside an otherwise valid
    array. We strip fences, try a direct parse, then retry with bare quotes
    escaped, then fall back to grabbing the first ``[...]`` block, then fall
    back to per-object salvage.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        repaired = _repair_unescaped_quotes(text)
        if repaired != text:
            try:
                data = json.loads(repaired)
            except json.JSONDecodeError:
                text = repaired  # still better odds for the fallbacks below
            else:
                print("  WARN: parsed after escaping bare quotes in string "
                      "values", file=sys.stderr)
                if not isinstance(data, list):
                    raise ValueError(
                        f"expected JSON array at top level, "
                        f"got {type(data).__name__}"
                    )
                return data
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                salvaged = _salvage_objects(match.group(0))
                if not salvaged:
                    raise ValueError(
                        "could not parse JSON array and per-object salvage "
                        "recovered nothing"
                    )
                print(
                    f"  WARN: whole-array parse failed; salvaged "
                    f"{len(salvaged)} object(s) individually",
                    file=sys.stderr,
                )
                return salvaged
        else:
            salvaged = _salvage_objects(text)
            if not salvaged:
                raise ValueError("no JSON array found in model output")
            print(
                f"  WARN: no top-level array; salvaged {len(salvaged)} "
                f"object(s) individually",
                file=sys.stderr,
            )
            return salvaged
    if not isinstance(data, list):
        raise ValueError(
            f"expected JSON array at top level, got {type(data).__name__}"
        )
    return data


def validate_fact(fact: dict, idx: int) -> list[str]:
    problems: list[str] = []
    if not isinstance(fact, dict):
        return [f"fact[{idx}]: not a JSON object"]
    for k in ("type", "subject", "fact", "source_quote"):
        if k not in fact:
            problems.append(f"fact[{idx}]: missing key {k!r}")
    t = fact.get("type")
    if t is not None and t not in ALLOWED_TYPES:
        problems.append(f"fact[{idx}]: unknown type {t!r}")
    return problems


def verify_quotes(facts: list[dict], chunk: str) -> None:
    """Stamp each fact with ``quote_verified``: is source_quote genuinely a
    verbatim span of the chunk it was extracted from?

    The extract prompts demand character-for-character substrings, which makes
    this mechanically checkable — and a fabricated fact almost always carries
    a fabricated or `...`-stitched quote, so the flag doubles as a free
    hallucination detector. Score, don't filter: nothing is dropped, the flag
    just lets human review sort unverified facts to the top. Empty quotes
    count as unverified. Whitespace-normalized fallback so a reflowed line
    break doesn't fail an otherwise verbatim quote.
    """
    chunk_norm = " ".join(chunk.split())
    for f in facts:
        if not isinstance(f, dict):
            continue
        q = f.get("source_quote") or ""
        f["quote_verified"] = bool(q) and (
            q in chunk or " ".join(q.split()) in chunk_norm
        )


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via tmp + os.replace so a kill mid-write never leaves a torn file.

    The ensemble's speculative re-execution runs a duplicate of the same unit
    in another process sharing this cache dir, and terminates the loser — the
    PID suffix keeps the tmp names from colliding, and the rename makes the
    loser's death harmless (last writer wins, both wrote the same chunk).
    """
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_cached(out_file: Path) -> list | None:
    """Parsed facts from a per-chunk cache file, or None if missing or corrupt.

    A torn file (a copy killed mid-write before writes were atomic) counts as
    a miss and gets regenerated, instead of crashing every resume until a
    human deletes it.
    """
    try:
        return json.loads(out_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def extract_one_chunk(call_fn, chunk: str, out_file: Path) -> tuple[list | None, str | None]:
    """Extract one chunk via `call_fn(chunk) -> raw text`. Returns (facts, error).

    On success the facts are cached atomically at `out_file`; on a parse
    failure the raw model output is saved alongside as ``*.raw.txt`` for
    hand-fixing and (None, error) is returned.
    """
    raw = call_fn(chunk)
    try:
        facts = parse_facts_block(raw)
    except (ValueError, json.JSONDecodeError) as e:
        bad = out_file.with_suffix(".raw.txt")
        _atomic_write_text(bad, raw)
        return None, f"{e} (raw output saved to {bad.name})"
    verify_quotes(facts, chunk)
    _atomic_write_text(out_file, json.dumps(facts, indent=2))
    return facts, None


def run_parallel(chunks: list, extract_dir: Path, call_fn,
                 parallel: int) -> tuple[dict[int, list], list[tuple[int, str]]]:
    """Run cache-miss chunks through `call_fn` with up to `parallel` in flight.

    Returns ({chunk_index: facts}, [(chunk_index, error)]); indexes are
    1-based to match the ``facts_NNN.json`` cache names. A failed chunk does
    NOT cancel the others — everything that can finish caches, so a re-run
    after a hand-fix resumes instantly.
    """
    results: dict[int, list] = {}
    failures: list[tuple[int, str]] = []
    misses: list[tuple[int, str, Path]] = []
    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"facts_{i:03d}.json"
        cached = _load_cached(out_file)
        if cached is not None:
            print(f"  [{i}/{len(chunks)}] Reusing cached: {out_file.name}")
            verify_quotes(cached, chunk)  # stamp caches/hand-fixes that predate the flag
            results[i] = cached
        else:
            misses.append((i, chunk, out_file))
    if not misses:
        return results, failures

    def _work(i: int, chunk: str, out_file: Path):
        # A speculative sibling process may have cached this chunk since the
        # scan above — one stat beats a duplicate multi-minute API call.
        cached = _load_cached(out_file)
        if cached is not None:
            verify_quotes(cached, chunk)
            return i, cached, None, True
        facts, err = extract_one_chunk(call_fn, chunk, out_file)
        return i, facts, err, False

    done = 0
    executor = ThreadPoolExecutor(max_workers=min(parallel, len(misses)))
    try:
        futures = [executor.submit(_work, i, c, f) for i, c, f in misses]
        for fut in as_completed(futures):
            i, facts, err, was_cached = fut.result()
            done += 1
            if err is not None:
                failures.append((i, err))
                print(f"  [FAIL {done}/{len(misses)}] chunk {i:03d}: {err}",
                      file=sys.stderr)
            else:
                results[i] = facts
                tag = "cached" if was_cached else "done  "
                print(f"  [{tag} {done}/{len(misses)}] chunk {i:03d}: "
                      f"{len(facts)} fact(s)")
    except KeyboardInterrupt:
        # Without this, the concurrent.futures atexit hook joins the worker
        # threads and Ctrl+C appears to hang until every in-flight stream
        # finishes. Atomic cache writes make a hard exit safe.
        executor.shutdown(wait=False, cancel_futures=True)
        sys.stdout.flush()
        print("\nInterrupted — completed chunks are cached; re-run to resume.",
              file=sys.stderr)
        sys.stderr.flush()
        os._exit(130)
    executor.shutdown(wait=True)
    failures.sort()
    return results, failures


def _positive_int(s: str) -> int:
    v = int(s)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a flat JSON list of campaign facts from a session "
            "summary using a local LLM. Stops at JSON — no synthesize."
        )
    )
    parser.add_argument("input", help="Input text file (session summary, canonical timeline, ...)")
    parser.add_argument("--output", "-o", required=True, metavar="FILE",
                        help="Where to write the merged facts.json array")
    parser.add_argument("--chunk-size", type=int, default=30000, metavar="CHARS",
                        help="Max characters per chunk (default: 30000). Local models "
                             "have tighter effective context windows than Claude, so "
                             "this defaults smaller than distill.py.")
    parser.add_argument("--split-chapters", metavar="PREFIX",
                        help="Split at lines starting with PREFIX (e.g. '# Chapter') "
                             "instead of by character count")
    parser.add_argument("--extract-dir", metavar="DIR", default=None,
                        help="Where to save per-chunk JSON files "
                             "(default: <output_dir>/fact_extractions/). Existing "
                             "files are reused so partial runs can resume.")
    parser.add_argument("--dgx-endpoint",
                        default=os.environ.get("DGX_ENDPOINT", DEFAULT_ENDPOINT),
                        help=f"OpenAI-compatible endpoint "
                             f"(default: $DGX_ENDPOINT or {DEFAULT_ENDPOINT})")
    parser.add_argument("--model",
                        default=os.environ.get("DGX_MODEL", DEFAULT_MODEL),
                        help=f"Model id to send to the endpoint "
                             f"(default: $DGX_MODEL or {DEFAULT_MODEL}). "
                             f"Probe `curl http://<host>:8001/v1/models` if "
                             f"the default returns 400 — vllm-chat gets swapped.")
    parser.add_argument("--max-tokens", type=int, default=16000,
                        help="max_tokens per chunk call (default: 16000). Generous "
                             "because reasoning models burn budget before any output.")
    parser.add_argument("--agent", default="extract_facts",
                        help="Agent prompt name to load from config/agents/ "
                             "(default: extract_facts). Use a different name to "
                             "run a different lens, e.g. extract_facts_sweep.")
    parser.add_argument("--parallel", type=_positive_int, default=1, metavar="N",
                        help="Concurrent in-flight chunk requests against the "
                             "endpoint (default 1 = sequential with streamed "
                             "token output). vLLM continuous-batches, so "
                             "matching the server's batch budget multiplies "
                             "aggregate throughput — the Sparks serve "
                             "--max-num-seqs 4, so 4 saturates a box.")
    args = parser.parse_args()

    extract_system = load_agent_prompt(args.agent)

    output = Path(args.output).expanduser().resolve()
    extract_dir = (
        Path(args.extract_dir).expanduser().resolve()
        if args.extract_dir
        else output.parent / "fact_extractions"
    )

    text = Path(args.input).expanduser().read_text(encoding="utf-8")
    if not text.strip():
        print(f"Error: input file is empty: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[Extract facts | {len(text):,} chars | "
          f"endpoint: {args.dgx_endpoint} | model: {args.model}]")
    print("=" * 60)

    client = make_client(endpoint=args.dgx_endpoint, model_override=args.model)
    chunks, label = prepare_chunks(text, args.chunk_size, args.split_chapters)
    extract_dir.mkdir(parents=True, exist_ok=True)

    all_facts: list[dict] = []
    problems_total: list[str] = []

    if args.parallel > 1:
        def call_fn(chunk: str) -> str:
            return stream_api(client, extract_system, chunk, args.model,
                              max_tokens=args.max_tokens, silent=True)

        print(f"  [parallel] up to {args.parallel} chunk(s) in flight")
        results, failures = run_parallel(chunks, extract_dir, call_fn,
                                         args.parallel)
        if failures:
            # The ensemble dispatcher surfaces only the LAST 3 stderr lines of
            # a failed unit — keep the actionable payload in them.
            names = ", ".join(f"facts_{i:03d}.json" for i, _ in failures)
            print(f"\n{len(failures)} of {len(chunks)} chunk(s) failed to "
                  f"parse; the rest are cached.", file=sys.stderr)
            print(f"  Raw outputs saved as *.raw.txt in {extract_dir}",
                  file=sys.stderr)
            print(f"  Fix by hand into {names} and re-run to resume.",
                  file=sys.stderr)
            sys.exit(1)
        facts_by_chunk = [results[i] for i in range(1, len(chunks) + 1)]
    else:
        facts_by_chunk = []
        for i, chunk in enumerate(chunks, 1):
            out_file = extract_dir / f"facts_{i:03d}.json"
            facts = _load_cached(out_file)
            if facts is not None:
                print(f"  [{i}/{len(chunks)}] Reusing cached: {out_file.name}")
                verify_quotes(facts, chunk)
            else:
                print(f"  [{i}/{len(chunks)}] Extracting from {label} "
                      f"({len(chunk):,} chars)...")
                print("  " + "─" * 56)
                raw = stream_api(
                    client, extract_system, chunk, args.model,
                    max_tokens=args.max_tokens,
                )
                print("  " + "─" * 56)
                try:
                    facts = parse_facts_block(raw)
                except (ValueError, json.JSONDecodeError) as e:
                    bad = out_file.with_suffix(".raw.txt")
                    bad.write_text(raw, encoding="utf-8")
                    print(f"  ERROR: could not parse JSON from chunk {i}: {e}",
                          file=sys.stderr)
                    print(f"  Raw output saved to: {bad}", file=sys.stderr)
                    print(f"  Fix by hand into {out_file} and re-run to continue.",
                          file=sys.stderr)
                    sys.exit(1)
                verify_quotes(facts, chunk)
                _atomic_write_text(out_file, json.dumps(facts, indent=2))
                print(f"  Saved: {out_file.name} ({len(facts)} fact(s))\n")
            facts_by_chunk.append(facts)

    for i, facts in enumerate(facts_by_chunk, 1):
        for j, f in enumerate(facts):
            for p in validate_fact(f, j):
                problems_total.append(f"chunk {i}: {p}")
        all_facts.extend(facts)

    if problems_total:
        print("\nValidation warnings:")
        for p in problems_total:
            print(f"  {p}")

    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(output, json.dumps(all_facts, indent=2) + "\n")

    counts: dict[str, int] = {}
    for f in all_facts:
        counts[f.get("type", "?")] = counts.get(f.get("type", "?"), 0) + 1

    verified = sum(1 for f in all_facts
                   if isinstance(f, dict) and f.get("quote_verified"))

    print("\n" + "=" * 60)
    print(f"Wrote {len(all_facts)} fact(s) to {output}")
    if counts:
        print("By type: " + ", ".join(f"{t}={n}" for t, n in sorted(counts.items())))
    if all_facts:
        print(f"Quotes verified: {verified}/{len(all_facts)} "
              f"({len(all_facts) - verified} unverified — review those first)")
    print(f"Per-chunk extractions in: {extract_dir}")


if __name__ == "__main__":
    main()
