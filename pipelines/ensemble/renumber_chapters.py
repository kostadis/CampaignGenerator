#!/usr/bin/env python3
"""One-time chapter renumbering fix (issue #213, Phase 0).

The positional index NN in ``docs/chapters/chapter_NN_<slug>.md`` filenames is
the canonical chapter number — it is the count used at the table and the key
every consumer (ensemble, dossier frontmatter, mempalace, release tags)
already navigates by. Historically the *internal* bible headings drifted from
it (Phandalin: heading = NN-1; OOTA: heading = NN-3), because
``split_chapters.py`` assigns filenames by encounter order while headings keep
whatever number was typed.

This script makes all counters agree, in place, without renaming anything:

1. **Bible** — every ``# Chapter N …`` heading is renumbered to its encounter
   position. Nothing else in the file changes.
2. **Chapter files** — each ``chapter_NN_<slug>.md`` gets its first heading
   renumbered to NN, and YAML frontmatter injected/updated:
   ``chapter: NN``, ``title:`` (from the heading), and ``session:`` — the
   latter **only** from an ``approved: true`` row of ``summary_map.yaml``
   (the chapter↔session join is a GM decision; an unapproved proposal never
   stamps anything).
3. **Drift report** — after normalising both sides (headings fixed,
   frontmatter/markers stripped), bible chunks are compared to their chapter
   files. Divergence means the file was hand-edited after splitting; it is
   reported, never "fixed" — re-splitting would clobber the edits.

Dry-run by default; ``--apply`` writes. Idempotent: a second run reports
nothing to do.

Usage:
  python renumber_chapters.py --bible docs/ensemble/chapters.md \\
      --chapters-dir docs/chapters [--summary-map docs/ensemble/summary_map.yaml] \\
      [--apply]
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

from campaignlib import split_frontmatter

try:  # package import (pytest) vs same-dir script execution
    from pipelines.ensemble.split_chapters import split as split_bible
except ImportError:
    from split_chapters import split as split_bible

HEADING_RE_TEMPLATE = r"(?mi)^({prefix}\s*)([\d.]+)([^\n]*)$"
MARKER_RE = re.compile(
    r"(?m)^\s*<!--\s*chapter:\s*\d+\s*(?:\|\s*session:\s*\d{8}\s*)?-->\s*\n?"
)
FILENAME_RE = re.compile(r"^chapter_(\d+)_.+\.md$")


def heading_pattern(prefix: str) -> re.Pattern:
    return re.compile(HEADING_RE_TEMPLATE.format(prefix=re.escape(prefix)))


def renumber_bible(text: str, prefix: str) -> tuple[str, list[str]]:
    """Return (new_text, change_report). Only heading numbers change."""
    pat = heading_pattern(prefix)
    changes: list[str] = []
    counter = 0

    def repl(m: re.Match) -> str:
        nonlocal counter
        counter += 1
        old = m.group(2)
        if old != str(counter):
            title = m.group(3).strip(" :–—-")
            changes.append(f"  bible heading {old!r} -> {counter}  ({title[:60]})")
        return f"{m.group(1)}{counter}{m.group(3)}"

    return pat.sub(repl, text), changes


def load_approved_sessions(map_path: Path) -> dict[str, str]:
    """Return {chapter filename: YYYYMMDD} for approved summary_map rows only."""
    if not map_path.exists():
        return {}
    try:
        data = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"warning: could not parse {map_path}: {exc} — no sessions stamped",
              file=sys.stderr)
        return {}
    out: dict[str, str] = {}
    for e in data.get("entries") or []:
        if not (isinstance(e, dict) and e.get("approved") is True and e.get("chapter")):
            continue
        date = str(e.get("summary_date") or e.get("summary") or "")
        date = re.sub(r"[^0-9]", "", date)
        if re.fullmatch(r"\d{8}", date):
            out[e["chapter"]] = date
    return out


def fix_chapter_file(path: Path, index: int, prefix: str,
                     session: str | None) -> tuple[str, list[str]]:
    """Return (new_content, change_report) for one chapter file."""
    raw = path.read_text(encoding="utf-8-sig")
    meta, body = split_frontmatter(raw)
    changes: list[str] = []

    pat = heading_pattern(prefix)
    m = pat.search(body)
    title = ""
    if m:
        title = m.group(3).strip(" :–—-")
        if m.group(2) != str(index):
            changes.append(f"  heading {m.group(2)!r} -> {index}")
            body = body[:m.start()] + f"{m.group(1)}{index}{m.group(3)}" + body[m.end():]
    else:
        changes.append(f"  warning: no {prefix!r} heading found — frontmatter only")

    new_meta = dict(meta)
    if new_meta.get("chapter") != index:
        changes.append(f"  frontmatter chapter: {new_meta.get('chapter')!r} -> {index}")
    new_meta["chapter"] = index
    if title and new_meta.get("title") != title:
        changes.append(f"  frontmatter title: -> {title[:60]!r}")
        new_meta["title"] = title
    if session and new_meta.get("session") != session:
        changes.append(f"  frontmatter session: {new_meta.get('session')!r} -> {session}")
        new_meta["session"] = session

    ordered: dict = {}
    for key in ("chapter", "session", "title"):
        if key in new_meta:
            ordered[key] = new_meta.pop(key)
    ordered.update(new_meta)
    dumped = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True,
                            default_flow_style=False).strip()
    content = f"---\n{dumped}\n---\n{body.lstrip()}"
    if not content.endswith("\n"):
        content += "\n"
    return content, changes


def normalise(text: str, prefix: str) -> str:
    """Strip frontmatter/markers and blank the heading number, for drift compare."""
    _, body = split_frontmatter(text)
    body = MARKER_RE.sub("", body)
    body = heading_pattern(prefix).sub(lambda m: f"{m.group(1)}N{m.group(3)}", body, count=1)
    return body.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bible", type=Path, required=True, help="Bible/master document")
    parser.add_argument("--chapters-dir", type=Path, required=True,
                        help="Directory of chapter_NN_<slug>.md split files")
    parser.add_argument("--summary-map", type=Path, default=None,
                        help="summary_map.yaml; only approved rows stamp session dates")
    parser.add_argument("--prefix", default="# Chapter ",
                        help="Heading prefix (default: '# Chapter ')")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default: dry-run report only)")
    args = parser.parse_args()

    if not args.bible.is_file():
        print(f"error: bible not found: {args.bible}", file=sys.stderr)
        return 1
    if not args.chapters_dir.is_dir():
        print(f"error: chapters dir not found: {args.chapters_dir}", file=sys.stderr)
        return 1

    sessions = load_approved_sessions(args.summary_map) if args.summary_map else {}
    if args.summary_map:
        print(f"summary map: {len(sessions)} approved session join(s)")

    # 1. Bible.
    bible_text = args.bible.read_text(encoding="utf-8-sig")
    new_bible, bible_changes = renumber_bible(bible_text, args.prefix)
    n_headings = len(heading_pattern(args.prefix).findall(new_bible))
    print(f"\nbible: {args.bible} — {n_headings} chapter heading(s), "
          f"{len(bible_changes)} renumbered")
    for c in bible_changes:
        print(c)

    # 2. Chapter files.
    files = sorted(p for p in args.chapters_dir.iterdir() if FILENAME_RE.match(p.name))
    if len(files) != n_headings:
        print(f"warning: {len(files)} chapter file(s) vs {n_headings} bible heading(s)")
    file_contents: dict[Path, str] = {}
    n_changed = 0
    print(f"\nchapter files: {len(files)} in {args.chapters_dir}")
    for path in files:
        index = int(FILENAME_RE.match(path.name).group(1))
        content, changes = fix_chapter_file(
            path, index, args.prefix, sessions.get(path.name))
        if path.read_text(encoding="utf-8-sig") != content:
            file_contents[path] = content
            n_changed += 1
            print(f"{path.name}:")
            for c in changes:
                print(c)

    # 3. Drift report (informational — never auto-fixed).
    chunks = split_bible(new_bible, args.prefix)
    drift = []
    by_index = {int(FILENAME_RE.match(p.name).group(1)): p for p in files}
    for i, (_num, _heading, chunk_body, _marker) in enumerate(chunks, start=1):
        path = by_index.get(i)
        if path is None:
            drift.append(f"  position {i}: no chapter file")
            continue
        file_text = file_contents.get(path) or path.read_text(encoding="utf-8-sig")
        if normalise(chunk_body, args.prefix) != normalise(file_text, args.prefix):
            drift.append(f"  {path.name}: content differs from bible chunk "
                         f"(hand-edited after split — kept as-is)")
    print(f"\ndrift: {len(drift)} chapter(s) diverge from the bible")
    for d in drift:
        print(d)

    # Write.
    total = (1 if new_bible != bible_text else 0) + n_changed
    if not args.apply:
        print(f"\ndry-run: {total} file(s) would change "
              f"({len(bible_changes)} bible heading(s), {n_changed} chapter file(s)). "
              f"Re-run with --apply.")
        return 0
    if new_bible != bible_text:
        args.bible.write_text(new_bible, encoding="utf-8")
    for path, content in file_contents.items():
        path.write_text(content, encoding="utf-8")
    print(f"\napplied: {total} file(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
