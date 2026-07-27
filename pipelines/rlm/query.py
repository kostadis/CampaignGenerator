#!/usr/bin/env python3
"""Search session summaries for a specific event, NPC, or topic.

Useful when campaign_state.md is missing something and you want to verify
whether it happened and what the outcome was.

Scans the summaries in chunks, extracts anything relevant to your query,
then synthesizes the hits into a direct answer.

Usage:
  query summaries.md "Did the party clear Gnomengarde?"
  query summaries.md "What happened with Grundar at Icespire Hold?"
  query summaries.md "Has the Kraken Society arc score ever increased?"
  query summaries.md "What does the party know about the planar distortion?"

  # Just show raw hits without synthesizing
  query summaries.md "Xalvosh" --hits-only

  # Save the answer to a file
  query summaries.md "What is the current state of Neverwinter?" -o notes.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    add_backend_args,
    build_batch_request,
    chunk_text,
    client_from_args,
    run_batch,
    run_single_batch,
    stream_api,
    DEFAULT_MODEL,
)

FILTER_SYSTEM = """\
You are searching D&D session notes for information relevant to a specific query.

Query: {query}

Instructions:
- If this passage contains ANYTHING relevant to the query, extract all relevant \
sentences or paragraphs. Include context (who, when, where, outcome).
- Be inclusive: if there is any chance it is relevant, include it.
- If this passage contains nothing relevant to the query, output exactly: NONE

Output only the extracted text or NONE. No preamble.
"""

SYNTHESIZE_SYSTEM = """\
You are answering a specific question about a D&D campaign based on relevant \
passages extracted from session notes.

Question: {query}

Synthesize the provided extracts into a complete, direct answer:
- What happened (chronologically if there are multiple events)
- Who was involved
- Outcome and any lasting consequences
- What remains unresolved, if anything

If the extracts only partially answer the question, state what is known and what is unclear.
Be concise. Output only the answer — no preamble, no "based on the extracts" framing.
"""




def run_query(client, text: str, query: str, chunk_size: int, model: str, verbose: bool) -> list[str]:
    chunks = chunk_text(text, chunk_size)
    total = len(chunks)
    hits = []

    system = FILTER_SYSTEM.format(query=query)

    for i, chunk in enumerate(chunks, 1):
        marker = f"[{i}/{total}]"
        if verbose:
            print(f"  {marker} Scanning chunk ({len(chunk):,} chars)...", end=" ", flush=True)

        result = stream_api(client, system, chunk, model, silent=True)
        result = result.strip()

        if result.upper() == "NONE" or not result:
            if verbose:
                print("no match")
        else:
            if verbose:
                print(f"HIT ({len(result):,} chars)")
            hits.append(result)

    return hits


def run_query_batch(client, text: str, query: str, chunk_size: int, model: str) -> list[str]:
    """Batch MAP: submit every chunk as one grouped `run_batch` call instead of
    the serial per-chunk `stream_api` loop `run_query` uses.

    `custom_id` is `chunk_{i:03d}` (1-indexed, matching the chunk's position),
    so results map back to chunk order deterministically — `collect_batch`'s
    dict is keyed by custom_id but NOT guaranteed to preserve submission
    order (results stream back in whatever order the batch API finishes
    them), so this indexes into `results` by chunk position rather than
    iterating the dict.

    If any chunk's batch item did not succeed, prints a
    `FAILED <custom_id>: <status> <error>` line for each failure and exits
    the process (`sys.exit(1)`) — the REDUCE step would otherwise be built on
    an incomplete/wrong-order set of hits. On full success, returns the hits
    in chunk order with the same NONE/empty filtering `run_query` applies.
    """
    chunks = chunk_text(text, chunk_size)
    total = len(chunks)
    system = FILTER_SYSTEM.format(query=query)

    requests = [
        build_batch_request(
            custom_id=f"chunk_{i:03d}",
            system=system,
            user=chunk,
            model=model,
            max_tokens=8096,  # matches stream_api's own default (run_query omits it)
        )
        for i, chunk in enumerate(chunks, 1)
    ]
    print(f"  Submitting {total} chunk(s) as one batch...")
    results = run_batch(client, requests, label="query")

    records = []
    failed: list[str] = []
    for i in range(1, total + 1):
        custom_id = f"chunk_{i:03d}"
        record = results.get(custom_id)
        if record is None:
            record = {"status": "missing", "error": "no result returned", "text": None}
        records.append(record)
        if record["status"] != "succeeded":
            failed.append(custom_id)
            print(f"FAILED {custom_id}: {record['status']} {record.get('error')}",
                  file=sys.stderr)

    if failed:
        sys.exit(1)

    hits: list[str] = []
    for record in records:
        result = (record["text"] or "").strip()
        if result.upper() == "NONE" or not result:
            continue
        hits.append(result)
    return hits


def run_synthesize(client, hits: list[str], query: str, model: str) -> str:
    combined = "\n\n---\n\n".join(
        f"<!-- Extract {i} -->\n{hit}" for i, hit in enumerate(hits, 1)
    )
    system = SYNTHESIZE_SYSTEM.format(query=query)
    print(f"\n  Synthesizing {len(hits)} hit(s)...")
    print("  " + "─" * 56)
    result = stream_api(client, system, combined, model)
    print("  " + "─" * 56)
    return result


def run_synthesize_batch(client, hits: list[str], query: str, model: str) -> str:
    """Batch REDUCE: same prompt assembly as `run_synthesize`, routed through
    `run_single_batch` (one-item Message Batch) instead of live `stream_api`.

    Raises `RuntimeError` if the batch item does not succeed — query.py is a
    single-call reduce with no unit<->file map to report a partial failure
    against, so the caller treats that as fatal.
    """
    combined = "\n\n---\n\n".join(
        f"<!-- Extract {i} -->\n{hit}" for i, hit in enumerate(hits, 1)
    )
    system = SYNTHESIZE_SYSTEM.format(query=query)
    print(f"\n  Synthesizing {len(hits)} hit(s) via batch...")
    print("  " + "─" * 56)
    result = run_single_batch(client, system=system, user=combined, model=model,
                              max_tokens=8096)  # matches stream_api's own default
    print("  " + "─" * 56)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search the canonical timeline (master narrative bible) for a specific event, NPC, or topic."
    )
    parser.add_argument("input", metavar="SUMMARIES",
                        help="Canonical timeline (master narrative bible) to search")
    parser.add_argument("query", metavar="QUERY",
                        help="What to look for (question or topic)")
    parser.add_argument("--hits-only", action="store_true",
                        help="Print raw matching extracts without synthesizing")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Save the answer to a file")
    parser.add_argument("--chunk-size", type=int, default=40000, metavar="CHARS",
                        help="Characters per chunk (default: 40000 — smaller = more precise hits)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-chunk progress")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Claude model to use")
    add_backend_args(parser)
    args = parser.parse_args()

    summaries_path = Path(args.input).expanduser()
    if not summaries_path.exists():
        print(f"Error: file not found: {summaries_path}", file=sys.stderr)
        sys.exit(1)

    text = summaries_path.read_text(encoding="utf-8")
    client = client_from_args(args)

    print(f"\n[Query: \"{args.query}\"]")
    print(f"[{len(text):,} chars | chunk size: {args.chunk_size:,} | model: {args.model}]")
    print("=" * 60)

    if args.batch:
        hits = run_query_batch(client, text, args.query, args.chunk_size, args.model)
    else:
        hits = run_query(client, text, args.query, args.chunk_size, args.model, verbose=args.verbose)

    print(f"\n  {len(hits)} relevant chunk(s) found out of "
          f"{len(chunk_text(text, args.chunk_size))} total.")

    if not hits:
        print("\n  No relevant content found for this query.")
        return

    if args.hits_only:
        print("\n" + "=" * 60)
        for i, hit in enumerate(hits, 1):
            print(f"\n--- Extract {i} ---\n{hit}")
        if args.output:
            combined = "\n\n---\n\n".join(hits)
            Path(args.output).expanduser().write_text(combined.strip() + "\n", encoding="utf-8")
            print(f"\nSaved to: {args.output}")
        return

    print()
    if args.batch:
        try:
            answer = run_synthesize_batch(client, hits, args.query, args.model)
        except RuntimeError as e:
            print(f"Error: synthesis batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        answer = run_synthesize(client, hits, args.query, args.model)
    print("=" * 60)

    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(f"# Query: {args.query}\n\n{answer.strip()}\n", encoding="utf-8")
        print(f"\nAnswer saved to: {args.output}")


if __name__ == "__main__":
    main()
