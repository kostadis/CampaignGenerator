"""summary_native CLI — stub; subcommands are wired in later tasks."""

from __future__ import annotations

import argparse
import sys

SUBCOMMANDS = ("validate", "build", "synth", "compare")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="summary_native",
        description="Build grounding-doc drafts directly from reviewed session summaries.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in SUBCOMMANDS:
        sub.add_parser(name, help=f"{name} (not implemented yet)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"summary_native {args.command}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
