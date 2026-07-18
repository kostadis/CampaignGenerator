#!/usr/bin/env python3
"""Pass 1 — consistency check standalone CLI.

Reads a session recap + campaign context docs (+ optional session summary),
runs Pass 1, writes ``consistency_report.md`` (or wherever ``--out`` says).

This is the Phase-4 split of what used to be Pass 1 inside session_doc.py.
See docs/design/SessionDocRefactor.md.
"""

import argparse
import sys
from pathlib import Path

from campaignlib import (
    DEFAULT_MODEL,
    add_backend_args,
    client_from_args,
    load_agent_prompt,
    stream_api,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a consistency check on a session recap and write "
                    "a report flagging factual errors / contradictions."
    )
    parser.add_argument("recap", metavar="FILE",
                        help="Session recap markdown (typically session-summary.md)")
    parser.add_argument("--context", nargs="+", action="extend", required=True, metavar="FILE",
                        help="Campaign context files (campaign_state.md, world_state.md, party.md)")
    parser.add_argument("--session-summary", metavar="FILE",
                        help="Optional synthesised VTT session summary — included in the "
                             "consistency prompt as an authoritative event log.")
    parser.add_argument("--out", metavar="FILE", default="consistency_report.md",
                        help="Where to write the report (default: consistency_report.md "
                             "in the current directory).")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    add_backend_args(parser)
    parser.add_argument("--fast", action="store_true",
                        help="Use Haiku (~4x cheaper, faster).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.fast:
        args.model = "claude-haiku-4-5-20251001"

    recap_path = Path(args.recap).expanduser()
    if not recap_path.exists():
        print(f"Error: recap not found: {recap_path}", file=sys.stderr)
        sys.exit(1)
    recap = recap_path.read_text(encoding="utf-8")

    context_parts: list[str] = []
    for c in args.context:
        cp = Path(c).expanduser()
        if not cp.exists():
            print(f"Error: --context file not found: {cp}", file=sys.stderr)
            sys.exit(1)
        context_parts.append(cp.read_text(encoding="utf-8"))

    parts = [f"## Session Recap\n\n{recap.strip()}"]
    if args.session_summary:
        sp = Path(args.session_summary).expanduser()
        if not sp.exists():
            print(f"Error: --session-summary not found: {sp}", file=sys.stderr)
            sys.exit(1)
        parts.append(
            "## This Session — VTT Summary (authoritative event log)\n\n"
            + sp.read_text(encoding="utf-8").strip()
        )
    parts.append(
        "## Campaign Context\n\n" + "\n\n---\n\n".join(context_parts)
    )

    client = client_from_args(args)
    system = load_agent_prompt("session_doc/consistency")

    print(f"[sd_consistency: Pass 1 | model: {args.model} | "
          f"{len(context_parts)} context file(s)]")
    print("=" * 60)
    report = stream_api(client, system, "\n\n---\n\n".join(parts),
                        args.model, silent=True, verbose=args.verbose)
    print("=" * 60)

    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    issues = report.count("**Location**")
    if issues:
        print(f"  Found {issues} potential issue(s).")
        for line in report.splitlines():
            if line.startswith("- **Issue**") or line.startswith("**Issue**"):
                print(f"    {line.strip()}")
    else:
        print("  No issues found.")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
