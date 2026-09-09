#!/usr/bin/env python3
"""Export a narrated scene for the gap reviewer — issue #455.

The reviewer is a **static file** the GM saves to their phone once
(`session_doc/review/reviewer.html`). This writes the other half: a versioned
JSON document they paste into it. The page is never regenerated per session,
which is what makes the review usable at work with nothing switched on at home.

Deterministic and free: no model is called, no API key is read, no token is
spent. Reading a narration into blocks and listing the GM's own turns beside
them is a parse, and asking a model which gaps matter is precisely the scope
decision this whole layer exists to keep with the human.

    sd_review export --scene summaries/20260825/narration/session_doc_scene_01_x.md

**One scene per file by default.** A scene is 14–26 KB; a whole session is 82 KB,
which is not something to paste on a touch keyboard. `--all-scenes` opts in.

Exit codes::

    0  wrote the export
    1  refused (no narration, no gaps to review, unreadable extraction)
    2  could not run (bad arguments, missing directory)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from session_doc.review.export import build_export


def _find_extraction(narration: Path, explicit: Path | None) -> Path | None:
    """The scene extraction a narration was written from.

    Matched on the **scene number**, never the title: a session's plan and its
    extraction filenames disagree often enough that name matching would pair the
    wrong source with the wrong scene — the same reasoning the confirmation
    harness records for `20260811 scene 2`, which is "Bullying Through the Loan"
    in the plan and `02_securing_the_loan.md` on disk.
    """
    if explicit is not None:
        return explicit if explicit.is_file() else None
    stem = narration.stem                      # session_doc_scene_NN_slug
    parts = stem.split("_")
    number = next((p for p in parts if p.isdigit()), None)
    if number is None:
        return None
    for candidate in (narration.parent.parent / "scene_extractions_smoothed",
                      narration.parent.parent / "scene_extractions",
                      narration.parent):
        if not candidate.is_dir():
            continue
        hits = sorted(candidate.glob(f"{number}_*.md"))
        if len(hits) == 1:
            return hits[0]
    return None


def _export_one(narration: Path, extraction: Path | None, out: Path,
                *, allow_no_gaps: bool) -> int:
    text = narration.read_text(encoding="utf-8")
    extraction_text = extraction.read_text(encoding="utf-8") if extraction else ""
    export = build_export(narration_path=narration, narration_text=text,
                          extraction_text=extraction_text)

    if export.gap_count == 0 and not allow_no_gaps:
        print(
            f"Refusing: {narration.name} has no gap markers, so there is nothing "
            f"to review.\n"
            f"  A scene with no GM description in it legitimately has none — pass "
            f"--allow-no-gaps to export it anyway.\n"
            f"  If you expected gaps, the narration was rendered without "
            f"--gap-marking.",
            file=sys.stderr,
        )
        return 1

    if extraction is None:
        print(
            f"Warning: no scene extraction found for {narration.name}, so the "
            f"reviewer will have no source GM turns to rule against.\n"
            f"  Pass --extraction to name it. Ruling a gap from memory is the "
            f"thing the foot table exists to prevent.",
            file=sys.stderr,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    # ASCII-only, deliberately. This document's transport is a mobile clipboard
    # by way of whatever renders it, and that channel is not under our control:
    # served as `application/json` with no charset, a phone browser guessed
    # Windows-1252 and every em dash came back as `â€”` — into the anchors, and
    # into any passage the GM had typed. Escaping non-ASCII as \uXXXX parses
    # back to the identical characters and cannot be mangled by a charset guess.
    payload = json.dumps(json.loads(export.model_dump_json()),
                         indent=2, ensure_ascii=True)
    out.write_text(payload + "\n", encoding="utf-8")
    size_kb = len(payload) / 1024
    print(f"  {narration.name} -> {out}  "
          f"({export.gap_count} gaps, {export.gm_turn_count} GM turns, {size_kb:.1f} KB)")
    if size_kb > 60:
        print(f"  Note: {size_kb:.0f} KB is a large paste for a phone. One scene "
              f"per file keeps it in the 14-26 KB range.", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a narrated scene for the gap reviewer (#455).")
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("export", help="write a scene's reviewer JSON")
    ex.add_argument("--scene", required=True, metavar="FILE",
                    help="the narration written by sd_narrate --gap-marking")
    ex.add_argument("--extraction", default=None, metavar="FILE",
                    help="the scene extraction it was written from. Found beside "
                         "the narration by scene number when omitted.")
    ex.add_argument("--out", default=None, metavar="FILE",
                    help="where to write the JSON (default: beside the narration, "
                         "<stem>.review.json)")
    ex.add_argument("--all-scenes", action="store_true",
                    help="export every narration in the directory --scene names. "
                         "A whole session is ~82 KB and is not what gets pasted "
                         "on a phone; this is for archiving, not for review.")
    ex.add_argument("--allow-no-gaps", action="store_true",
                    help="export a scene that has no gap markers.")

    ap = sub.add_parser("apply", help="write a review into <scene>.authored.yaml")
    ap.add_argument("--scene", required=True, metavar="FILE",
                    help="the narration the review was made against")
    ap.add_argument("--from", dest="source", default="-", metavar="FILE",
                    help="the review JSON; '-' (default) reads stdin, so a "
                         "clipboard still works: pbpaste | sd_review apply ...")
    ap.add_argument("--force", action="store_true",
                    help="save even though it would drop prose already on disk. "
                         "That is what a stale tab looks like; mean it.")

    st = sub.add_parser("status", help="what is ruled, written and composed")
    st.add_argument("--dir", required=True, metavar="DIR",
                    help="a narration directory")
    st.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable, for a skill or a script")

    sv = sub.add_parser("serve", help="serve the reviewer and take its saves")
    sv.add_argument("--dir", required=True, metavar="DIR",
                    help="a narration directory")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="0.0.0.0",
                    help="0.0.0.0 by default: the point is to reach it from a "
                         "phone. Unauthenticated — a tailnet or a home LAN.")

    args = parser.parse_args()

    if args.command == "status":
        directory = Path(args.dir).expanduser()
        if not directory.is_dir():
            print(f"Error: not a directory: {directory}", file=sys.stderr)
            sys.exit(2)
        from session_doc.review.serve import narrations
        from session_doc.review.status import scene_status
        rows = [scene_status(n) for n in narrations(directory)]
        if args.as_json:
            print(json.dumps(rows, indent=2))
            return
        if not rows:
            print(f"No narrations in {directory}")
            return
        print(f"{'scene':<42} {'gaps':>5} {'ruled':>6} {'written':>8}  composed")
        for r in rows:
            print(f"{r['scene']:<42} {r['gaps']:>5} {r['ruled']:>6} "
                  f"{r['written']:>8}  {'yes' if r['composed'] else '-'}"
                  + ("   REVIEW STALE" if r["stale"] else ""))
        outstanding = [r for r in rows if r["gaps"] and r["written"] < r["gaps"]]
        print()
        if outstanding:
            print(f"{len(outstanding)} scene(s) not ready to assemble: "
                  + ", ".join(r["scene"] for r in outstanding))
        else:
            print("Every scene is written or cut — assemble --require-composed will pass.")
        return

    if args.command == "serve":
        directory = Path(args.dir).expanduser()
        if not directory.is_dir():
            print(f"Error: not a directory: {directory}", file=sys.stderr)
            sys.exit(2)
        from session_doc.review.serve import serve
        serve(directory, args.port, args.host)
        return

    if args.command == "apply":
        narration = Path(args.scene).expanduser()
        if not narration.is_file():
            print(f"Error: narration not found: {narration}", file=sys.stderr)
            sys.exit(2)
        raw = (sys.stdin.read() if args.source == "-"
               else Path(args.source).expanduser().read_text(encoding="utf-8"))
        from session_doc.authored import AuthoredError
        from session_doc.review.records import (
            SaveRefused, review_to_record, save_record, summarise,
        )
        try:
            record = review_to_record(json.loads(raw))
        except (ValueError, AuthoredError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            written, _ = save_record(narration, record, force=args.force)
        except SaveRefused as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"  {written.name}  ({summarise(record)})")
        return
    scene = Path(args.scene).expanduser()

    if args.all_scenes:
        if not scene.is_dir():
            print(f"Error: --all-scenes needs a directory, not {scene}", file=sys.stderr)
            sys.exit(2)
        narrations = sorted(scene.glob("session_doc_scene_*.md"))
        narrations = [p for p in narrations
                      if not p.name.endswith((".composed.md", ".scrubbed.md"))]
        if not narrations:
            print(f"Error: no narrations in {scene}", file=sys.stderr)
            sys.exit(2)
        rc = 0
        for narration in narrations:
            out = Path(args.out or narration.parent) / f"{narration.stem}.review.json"
            rc |= _export_one(narration, _find_extraction(narration, None), out,
                              allow_no_gaps=True)
        sys.exit(1 if rc else 0)

    if not scene.is_file():
        print(f"Error: narration not found: {scene}", file=sys.stderr)
        sys.exit(2)
    explicit = Path(args.extraction).expanduser() if args.extraction else None
    if explicit is not None and not explicit.is_file():
        print(f"Error: --extraction not found: {explicit}", file=sys.stderr)
        sys.exit(2)
    out = (Path(args.out).expanduser() if args.out
           else scene.with_name(f"{scene.stem}.review.json"))
    sys.exit(_export_one(scene, _find_extraction(scene, explicit), out,
                         allow_no_gaps=args.allow_no_gaps))


if __name__ == "__main__":
    main()
