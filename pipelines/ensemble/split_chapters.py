#!/usr/bin/env python3
"""Split a single bible/master document into per-chapter files.

Splits on top-level headings matching `# Chapter N` (or a custom prefix),
writes each chapter to `<output-dir>/chapter_NN_<slug>.md`, and skips writes
where the destination is byte-identical to what would be written.

Usage:
  python split_chapters.py bible.md --output-dir docs/chapters
  python split_chapters.py bible.md --output-dir docs/chapters --prefix "# Chapter "
  python split_chapters.py bible.md --output-dir docs/chapters --dry-run
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path


CHAPTER_RE_TEMPLATE = r"(?mi)^{prefix}\s*([\d.]+)[^\n]*$"


def split(text: str, prefix: str) -> list[tuple[str, str, str]]:
    """Return [(source_number, heading_line, body_with_heading), ...].

    Anything before the first chapter heading is dropped. Source numbers may
    be decimals (e.g. "18.05") and are kept verbatim for slug stripping; the
    final chapter number is assigned by encounter order in main().
    """
    pattern = re.compile(CHAPTER_RE_TEMPLATE.format(prefix=re.escape(prefix)))
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    chunks: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip() + "\n"
        chunks.append((m.group(1), m.group(0).strip(), body))
    return chunks


def slugify(heading: str, prefix: str) -> str:
    """Turn `# Chapter 3: Stealing Weapons` into `stealing_weapons`.

    Strips the prefix and any leading number (including decimals like 18.05).
    """
    tail = re.sub(rf"^{re.escape(prefix)}\s*[\d.]+[:\-\s]*", "", heading, flags=re.IGNORECASE)
    tail = tail.strip().lower()
    # Transliterate accents to ASCII (Faerûn → faerun, Entémoch → entemoch) so
    # the canonical accented spelling can live in the heading without turning
    # into underscores in the filename.
    tail = unicodedata.normalize("NFKD", tail).encode("ascii", "ignore").decode("ascii")
    tail = re.sub(r"[^a-z0-9]+", "_", tail).strip("_")
    return tail or "untitled"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Source markdown file")
    parser.add_argument("--output-dir", type=Path, required=True, help="Destination directory for chapter files")
    parser.add_argument("--prefix", default="# Chapter ", help="Heading prefix to split on (default: '# Chapter ')")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without touching disk")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    text = args.input.read_text(encoding="utf-8")
    chunks = split(text, args.prefix)
    if not chunks:
        print(f"error: no headings matching {args.prefix!r} found in {args.input}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for index, (source_number, heading, body) in enumerate(chunks, start=1):
        slug = slugify(heading, args.prefix)
        dest = args.output_dir / f"chapter_{index:02d}_{slug}.md"
        if dest.exists() and dest.read_text(encoding="utf-8") == body:
            skipped += 1
            continue
        if args.dry_run:
            print(f"would write {dest} ({len(body):,} chars)")
        else:
            dest.write_text(body, encoding="utf-8")
            print(f"wrote {dest} ({len(body):,} chars)")
        written += 1

    verb = "would write" if args.dry_run else "wrote"
    print(f"\n{verb} {written} file(s); {skipped} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
