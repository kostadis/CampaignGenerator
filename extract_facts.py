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
and the script exits — fix the file by hand and re-run.

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


def parse_facts_block(raw: str) -> list[dict]:
    """Extract a JSON facts array from a model response. Tolerant of fences/preamble.

    Local models sometimes wrap JSON in ```json fences, prepend a short
    explanation, or emit a single malformed object inside an otherwise valid
    array. We strip fences, try a direct parse, then fall back to grabbing the
    first ``[...]`` block, then fall back to per-object salvage.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
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

    for i, chunk in enumerate(chunks, 1):
        out_file = extract_dir / f"facts_{i:03d}.json"
        if out_file.exists():
            print(f"  [{i}/{len(chunks)}] Reusing cached: {out_file.name}")
            facts = json.loads(out_file.read_text(encoding="utf-8"))
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
            out_file.write_text(json.dumps(facts, indent=2), encoding="utf-8")
            print(f"  Saved: {out_file.name} ({len(facts)} fact(s))\n")

        for j, f in enumerate(facts):
            for p in validate_fact(f, j):
                problems_total.append(f"chunk {i}: {p}")
        all_facts.extend(facts)

    if problems_total:
        print("\nValidation warnings:")
        for p in problems_total:
            print(f"  {p}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(all_facts, indent=2) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for f in all_facts:
        counts[f.get("type", "?")] = counts.get(f.get("type", "?"), 0) + 1

    print("\n" + "=" * 60)
    print(f"Wrote {len(all_facts)} fact(s) to {output}")
    if counts:
        print("By type: " + ", ".join(f"{t}={n}" for t, n in sorted(counts.items())))
    print(f"Per-chunk extractions in: {extract_dir}")


if __name__ == "__main__":
    main()
