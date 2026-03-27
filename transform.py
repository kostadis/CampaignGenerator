#!/usr/bin/env python3
"""Transform a NotebookLLM dossier into prep.py input format.

Reads a campaign dossier and uses Claude to extract it into either:
  - A numbered session outline  (default) → paste into: prep.py --session
  - A single session beat       (--single) → paste into: prep.py --beat

Output is printed to stdout and optionally saved with --output.
"""

import argparse
import sys
from pathlib import Path

from campaignlib import make_client, stream_api


OUTLINE_SYSTEM = """\
You are a D&D session prep assistant extracting encounter beats from a campaign dossier.

Output ONLY a numbered list. Each item is a concise 1–2 sentence description of one
encounter or narrative moment to be prepped at the table. Focus on what happens, not
background lore. Do not include headers, explanation, or preamble.

Format:
1. [Scene or encounter description]
2. [Scene or encounter description]
...\
"""

SINGLE_SYSTEM = """\
You are a D&D session prep assistant distilling a campaign dossier into a single beat.

Output ONLY one paragraph describing the core encounter or narrative moment the DM
needs to prep. No headers, no explanation, no preamble.\
"""


def read_input(path: str | None) -> str:
    if path:
        p = Path(path).expanduser()
        if not p.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        return p.read_text(encoding="utf-8")
    print("Paste the dossier content. Press Ctrl+D (Linux/Mac) or Ctrl+Z+Enter (Windows) when done:\n", file=sys.stderr)
    content = sys.stdin.read().strip()
    if not content:
        print("Error: no input provided.", file=sys.stderr)
        sys.exit(1)
    return content


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transform a NotebookLLM dossier into prep.py input format."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to the dossier file. Omit to read from stdin.",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Extract as a single beat instead of a numbered session outline.",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Save output to this file (in addition to printing to stdout).",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model to use (default: claude-sonnet-4-20250514)",
    )
    args = parser.parse_args()

    dossier = read_input(args.input)

    system = SINGLE_SYSTEM if args.single else OUTLINE_SYSTEM
    mode_label = "single beat" if args.single else "session outline"
    print(f"[Transforming dossier → {mode_label}...]\n", file=sys.stderr)

    client = make_client()
    result = stream_api(client, system, dossier, args.model, max_tokens=1024)

    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result + "\n", encoding="utf-8")
        print(f"\nSaved to: {out_path}", file=sys.stderr)

    print(f"\n[Review the output above, then run:]", file=sys.stderr)
    if args.single:
        print(f'  python prep.py --beat "<paste beat here>"', file=sys.stderr)
    else:
        print(f'  python prep.py --session "<paste outline here>"', file=sys.stderr)
        print(f"  — or interactively: python prep.py --session", file=sys.stderr)


if __name__ == "__main__":
    main()
