#!/usr/bin/env python3
"""Search session summaries for a specific event, NPC, or topic.

Useful when campaign_state.md is missing something and you want to verify
whether it happened and what the outcome was.

Scans the summaries in chunks, extracts anything relevant to your query,
then synthesizes the hits into a direct answer.

Usage:
  python query.py summaries.md "Did the party clear Gnomengarde?"
  python query.py summaries.md "What happened with Grundar at Icespire Hold?"
  python query.py summaries.md "Has the Kraken Society arc score ever increased?"
  python query.py summaries.md "What does the party know about the planar distortion?"

  # Just show raw hits without synthesizing
  python query.py summaries.md "Xalvosh" --hits-only

  # Save the answer to a file
  python query.py summaries.md "What is the current state of Neverwinter?" -o notes.md
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, stream_api

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


def chunk_text(text: str, chunk_size: int) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end >= len(text):
            chunks.append(text[start:])
            break
        boundary = text.rfind("\n\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = text.rfind("\n", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end
        chunks.append(text[start:boundary])
        start = boundary
    return [c.strip() for c in chunks if c.strip()]


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search session summaries for a specific event, NPC, or topic."
    )
    parser.add_argument("input", metavar="SUMMARIES",
                        help="Session summaries file to search")
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
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    args = parser.parse_args()

    summaries_path = Path(args.input).expanduser()
    if not summaries_path.exists():
        print(f"Error: file not found: {summaries_path}", file=sys.stderr)
        sys.exit(1)

    text = summaries_path.read_text(encoding="utf-8")
    client = make_client()

    print(f"\n[Query: \"{args.query}\"]")
    print(f"[{len(text):,} chars | chunk size: {args.chunk_size:,} | model: {args.model}]")
    print("=" * 60)

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
    answer = run_synthesize(client, hits, args.query, args.model)
    print("=" * 60)

    if args.output:
        out = Path(args.output).expanduser()
        out.write_text(f"# Query: {args.query}\n\n{answer.strip()}\n", encoding="utf-8")
        print(f"\nAnswer saved to: {args.output}")


if __name__ == "__main__":
    main()
