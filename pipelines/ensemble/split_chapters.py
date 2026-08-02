#!/usr/bin/env python3
"""Split a single bible/master document into per-chapter files.

Splits on top-level headings matching `# Chapter N` (or a custom prefix),
writes each chapter to `<output-dir>/chapter_NN_<slug>.md`, and skips writes
where the destination is byte-identical to what would be written.

Chapter identity (issue #213, Phase 0): the positional index NN in the
filename is the canonical chapter number. Each heading may be followed by an
identity marker written at bible-append time:

    # Chapter 46 Universal Basic Treasure
    <!-- chapter: 46 | session: 20260706 -->

The marker is consumed (not copied into the split file) and lands as YAML
frontmatter at the head of the chapter file, alongside `chapter:` and
`title:` derived from the heading:

    ---
    chapter: 46
    session: '20260706'
    title: Universal Basic Treasure
    ---
    # Chapter 46 Universal Basic Treasure

The split fails loudly — writing nothing — when a heading's own number or a
marker's `chapter:` disagrees with the positional index. Disagreement is the
historical silent-drift bug (bible "Chapter N" = filename N+1); after the
one-time `renumber_chapters.py` fix it is always an error, never a
convention. `--no-check` exists only for legacy bibles with decimal
interstitial numbering (e.g. "Chapter 18.05"), where positional identity
never held; it also disables frontmatter emission, since a frontmatter
`chapter:` that contradicts the heading would be a second drifting counter.

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

import yaml


CHAPTER_RE_TEMPLATE = r"(?mi)^{prefix}\s*([\d.]+)[^\n]*$"
MARKER_RE = re.compile(
    r"^\s*<!--\s*chapter:\s*(\d+)\s*(?:\|\s*session:\s*(\d{8})\s*)?-->\s*$"
)


def split(text: str, prefix: str) -> list[tuple[str, str, str, dict]]:
    """Return [(source_number, heading_line, body_with_heading, marker), ...].

    Anything before the first chapter heading is dropped. Source numbers may
    be decimals (e.g. "18.05") and are kept verbatim for slug stripping; the
    final chapter number is assigned by encounter order in main().

    `marker` is {} or {"chapter": int, "session": str|None} parsed from an
    identity comment on the first non-blank line after the heading. The
    marker line is removed from the returned body — it is carried metadata,
    not chapter content, and lands as frontmatter instead.
    """
    pattern = re.compile(CHAPTER_RE_TEMPLATE.format(prefix=re.escape(prefix)))
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    chunks: list[tuple[str, str, str, dict]] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip() + "\n"
        marker: dict = {}
        lines = body.split("\n")
        for j in range(1, len(lines)):
            if not lines[j].strip():
                continue
            mm = MARKER_RE.match(lines[j])
            if mm:
                marker = {"chapter": int(mm.group(1)), "session": mm.group(2)}
                del lines[j]
                body = "\n".join(lines)
                if not body.endswith("\n"):
                    body += "\n"
            break
        chunks.append((m.group(1), m.group(0).strip(), body, marker))
    return chunks


def heading_title(heading: str, prefix: str) -> str:
    """Turn `# Chapter 3: Stealing Weapons` into `Stealing Weapons`.

    Separator stripping includes en/em dashes (`# Chapter 41 — Title`) —
    keep in sync with renumber_chapters.fix_chapter_file's title strip.
    """
    tail = re.sub(rf"^{re.escape(prefix)}\s*[\d.]+[:\s\-–—]*", "", heading, flags=re.IGNORECASE)
    return tail.strip()


def slugify(heading: str, prefix: str) -> str:
    """Turn `# Chapter 3: Stealing Weapons` into `stealing_weapons`.

    Strips the prefix and any leading number (including decimals like 18.05).
    """
    tail = heading_title(heading, prefix).lower()
    # Transliterate accents to ASCII (Faerûn → faerun, Entémoch → entemoch) so
    # the canonical accented spelling can live in the heading without turning
    # into underscores in the filename.
    tail = unicodedata.normalize("NFKD", tail).encode("ascii", "ignore").decode("ascii")
    tail = re.sub(r"[^a-z0-9]+", "_", tail).strip("_")
    return tail or "untitled"


def frontmatter_block(index: int, title: str, session: str | None) -> str:
    meta: dict = {"chapter": index}
    if session:
        meta["session"] = session
    if title:
        meta["title"] = title
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True,
                            default_flow_style=False).strip()
    return f"---\n{dumped}\n---\n"


def check_identity(chunks: list[tuple[str, str, str, dict]]) -> list[str]:
    """Return one error string per chunk whose counters disagree with its position."""
    errors: list[str] = []
    for index, (source_number, heading, _body, marker) in enumerate(chunks, start=1):
        try:
            heading_num = int(source_number)
        except ValueError:
            errors.append(
                f"position {index}: heading number {source_number!r} is not an "
                f"integer ({heading!r}) — positional identity cannot hold; "
                f"use --no-check for legacy decimal-numbered bibles"
            )
            continue
        if heading_num != index:
            errors.append(
                f"position {index}: heading says Chapter {heading_num} ({heading!r})"
            )
        if marker and marker["chapter"] != index:
            errors.append(
                f"position {index}: identity marker says chapter {marker['chapter']}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Source markdown file")
    parser.add_argument("--output-dir", type=Path, required=True, help="Destination directory for chapter files")
    parser.add_argument("--prefix", default="# Chapter ", help="Heading prefix to split on (default: '# Chapter ')")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be written without touching disk")
    parser.add_argument("--no-check", action="store_true",
                        help="Skip the heading==position identity check and frontmatter "
                             "emission (legacy bibles with decimal chapter numbers only)")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    text = args.input.read_text(encoding="utf-8")
    chunks = split(text, args.prefix)
    if not chunks:
        print(f"error: no headings matching {args.prefix!r} found in {args.input}", file=sys.stderr)
        return 1

    if not args.no_check:
        errors = check_identity(chunks)
        if errors:
            print(
                "error: chapter numbering disagrees with file position — refusing to "
                "split (nothing written).\n"
                "The positional index is the canonical chapter number (issue #213); "
                "fix the bible headings first:\n"
                "  python pipelines/ensemble/renumber_chapters.py --bible "
                f"{args.input} --chapters-dir {args.output_dir}\n",
                file=sys.stderr,
            )
            for e in errors:
                print(f"  {e}", file=sys.stderr)
            return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for index, (source_number, heading, body, marker) in enumerate(chunks, start=1):
        slug = slugify(heading, args.prefix)
        dest = args.output_dir / f"chapter_{index:02d}_{slug}.md"
        if args.no_check:
            content = body
        else:
            content = frontmatter_block(
                index, heading_title(heading, args.prefix), marker.get("session")
            ) + body
        if dest.exists() and dest.read_text(encoding="utf-8") == content:
            skipped += 1
            continue
        if args.dry_run:
            print(f"would write {dest} ({len(content):,} chars)")
        else:
            dest.write_text(content, encoding="utf-8")
            print(f"wrote {dest} ({len(content):,} chars)")
        written += 1

    verb = "would write" if args.dry_run else "wrote"
    print(f"\n{verb} {written} file(s); {skipped} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
