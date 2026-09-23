#!/usr/bin/env python3
"""Compose a narration and its authored record into `.composed.md` — #455.

Deterministic and free: no model is called, no API key is read, no token is
spent. This places prose a human wrote and removes blocks a human cut; nothing
here decides anything.

    sd_compose --scene summaries/20260825/narration/session_doc_scene_01_x.md
    sd_compose --dir  summaries/20260825/narration

**The generated files are never hand-edited.** The narration is the archive, the
`.authored.yaml` is the record, and the `.composed.md` is output — the same rule
`sd_corrections` applies to the tape, for the same reason: an edit nobody wrote
down is an edit nobody can review.

Exit codes::

    0  composed
    1  refused (stale record, invalid record)
    2  could not run (no narration, no record, unreadable input)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from session_doc.authored import AuthoredError, load_record_for, record_path
from session_doc.compose import ComposeError, compose_file, open_gap_ids


def _compose_one(narration: Path, *, force: bool) -> int:
    record = None
    try:
        record = load_record_for(narration)
    except AuthoredError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if record is None:
        print(f"  {narration.name}: no {record_path(narration).name} — nothing to "
              f"compose. Review the scene first (sd_review export).", file=sys.stderr)
        return 2

    out = narration.with_name(narration.stem + ".composed.md")
    if out.exists() and not force:
        print(f"Error: {out.name} already exists. It is generated — delete it or "
              f"pass --force to regenerate.", file=sys.stderr)
        return 2
    try:
        path, composed = compose_file(narration, record)
    except ComposeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path.write_text(composed, encoding="utf-8")

    text = narration.read_text(encoding="utf-8")
    still_open = open_gap_ids(text, record)
    ruled = sum(1 for b in record.blocks if b.disposition)
    written = sum(1 for b in record.blocks if b.disposition in ("authored", "cut"))
    print(f"  {narration.name} -> {path.name}  "
          f"({ruled} ruled, {written} written"
          + (f", {len(still_open)} still open" if still_open else "") + ")")
    if still_open:
        # Not an error. A scene ruled but not yet written is the normal end
        # state of a review done on a phone; assemble's gate is what stops it
        # reaching a chapter.
        print(f"    open gaps: {', '.join(still_open)} — "
              f"assemble --require-composed will refuse until these are written "
              f"or cut.", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compose a narration and its authored record (#455).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scene", metavar="FILE", help="one narration to compose")
    group.add_argument("--dir", metavar="DIR",
                       help="a narration directory; composes every scene that has a record")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing .composed.md")
    args = parser.parse_args()

    if args.scene:
        narration = Path(args.scene).expanduser()
        if not narration.is_file():
            print(f"Error: narration not found: {narration}", file=sys.stderr)
            sys.exit(2)
        sys.exit(_compose_one(narration, force=args.force))

    directory = Path(args.dir).expanduser()
    if not directory.is_dir():
        print(f"Error: not a directory: {directory}", file=sys.stderr)
        sys.exit(2)
    narrations = [p for p in sorted(directory.glob("session_doc_scene_*.md"))
                  if not p.name.endswith((".composed.md", ".scrubbed.md"))]
    if not narrations:
        print(f"Error: no narrations in {directory}", file=sys.stderr)
        sys.exit(2)
    worst = 0
    composed = 0
    for narration in narrations:
        rc = _compose_one(narration, force=args.force)
        if rc == 2 and not record_path(narration).is_file():
            continue          # no record for this scene: not an error in a sweep
        worst = max(worst, rc)
        composed += 1 if rc == 0 else 0
    print(f"\nComposed {composed} scene(s) in {directory}")
    sys.exit(worst)


if __name__ == "__main__":
    main()
