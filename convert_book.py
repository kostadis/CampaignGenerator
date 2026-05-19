"""
convert_book.py — thin wrapper around pdf-translators' pdf_to_5etools_v2.

Runs the conversion, then prints the exact fivetools_ingest.py command
to run next. Does **not** auto-ingest — the plan mandates an explicit
user review in adventure_editor / toc_editor before the JSON lands in
MemPalace.

Usage:
    python convert_book.py /mnt/g/path/to/book.pdf
    python convert_book.py book.pdf --pdf-translators ~/src/pdf-translators
    python convert_book.py book.pdf --book-id 7421     # forwarded to ingest hint
    python convert_book.py book.pdf --extra-args --marker --pages 1-20

Exit codes:
    0 — conversion succeeded; review + ingest hint printed
    non-zero — pdf-translators returned an error
"""

from __future__ import annotations

import argparse
import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


_DEFAULT_PDF_TRANSLATORS = Path.home() / "src" / "mytools" / "pdf-translators"
_DEFAULT_CONVERTER_SCRIPT = "pdf_to_5etools_v2.py"


def _resolve_converter(pdf_translators: Path, script: str) -> Path:
    path = pdf_translators / script
    if not path.is_file():
        raise SystemExit(
            f"convert_book: converter not found at {path}. "
            "Pass --pdf-translators with the correct checkout path."
        )
    return path


def _default_output_json(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".json")


def run_conversion(
    pdf_path: Path,
    *,
    pdf_translators: Path,
    converter_script: str = _DEFAULT_CONVERTER_SCRIPT,
    extra_args: list[str] | None = None,
    python: str = sys.executable,
) -> subprocess.CompletedProcess:
    """Invoke pdf_to_5etools_v2.py in a subprocess, streaming stdout/stderr.

    Returns the completed-process object so callers can inspect the
    return code. Does not raise on non-zero exit — the CLI main
    translates that into a user-visible error.
    """
    converter = _resolve_converter(pdf_translators, converter_script)
    cmd = [python, str(converter), str(pdf_path)]
    if extra_args:
        cmd.extend(extra_args)
    logger.info("convert_book: running %s", " ".join(shlex.quote(c) for c in cmd))
    return subprocess.run(cmd, cwd=str(pdf_translators), check=False)


def format_ingest_hint(
    json_path: Path,
    *,
    book_id: int | None = None,
    ingest_script: str = "fivetools_ingest.py",
    python: str = sys.executable,
) -> str:
    """Render the exact shell command the user should run next."""
    parts = [shlex.quote(python), ingest_script, shlex.quote(str(json_path))]
    if book_id is not None:
        parts += ["--book-id", str(book_id)]
    return " ".join(parts)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("pdf_path", type=Path, help="Path to the PDF to convert.")
    parser.add_argument(
        "--pdf-translators",
        type=Path,
        default=_DEFAULT_PDF_TRANSLATORS,
        help=f"Path to pdf-translators checkout (default {_DEFAULT_PDF_TRANSLATORS}).",
    )
    parser.add_argument(
        "--converter-script",
        default=_DEFAULT_CONVERTER_SCRIPT,
        help="Override the script name (default pdf_to_5etools_v2.py).",
    )
    parser.add_argument(
        "--book-id",
        type=int,
        default=None,
        help="rpg_library.db book id — included in the ingest hint.",
    )
    parser.add_argument(
        "--extra-args",
        nargs=argparse.REMAINDER,
        help="Extra flags passed through to the converter.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pdf_path = args.pdf_path
    if not pdf_path.is_file():
        raise SystemExit(f"convert_book: {pdf_path} is not a file")

    completed = run_conversion(
        pdf_path,
        pdf_translators=args.pdf_translators,
        converter_script=args.converter_script,
        extra_args=args.extra_args,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"convert_book: pdf_to_5etools_v2.py exited with "
            f"status {completed.returncode}"
        )

    json_path = _default_output_json(pdf_path)
    if not json_path.exists():
        logger.warning(
            "convert_book: converter finished but expected output %s not found",
            json_path,
        )
    hint = format_ingest_hint(json_path, book_id=args.book_id)
    print()
    print("── Conversion complete ──────────────────────────────────────")
    print(f"JSON output: {json_path}")
    print()
    print("Next steps:")
    print("  1. Review in adventure_editor / toc_editor / monster_editor")
    print("  2. When happy, run:")
    print(f"       {hint}")
    print()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
