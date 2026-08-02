#!/usr/bin/env python3
"""Propose, review and apply a chapter<->scene boundary map.

`event_spine` keys rows on ``(chapter, scene, seq)``. ``scene`` is the
``scene_index`` stamped at extraction time by ``chunk_by_scenes``, which is
header-driven — so a chapter with no scene headings has no usable scene key.
Early-campaign chapters are organised by in-world date with POV names beneath,
or carry no ``##`` at all.

A derived ``session-summary.md`` has a scene list, but its prose is a heavy
compression of the chapter (26% of the word count on the Phandalin corpus).
Extracting from it to obtain a scene key trades three quarters of the source
text for that key.

This tool takes neither. It uses the summary's scenes **only as a boundary
map** — titles and positions — and writes a derived copy of the *chapter* with
those scene headings injected. Extraction then reads the full prose and still
gets a real per-scene ``scene_index``.

**Deterministic — no model call.** Anchoring is rare-token cluster matching
with a monotonic constraint (``campaignlib.scene_anchor``).

**It proposes; it does not decide.** A boundary is a scope decision: put it in
the wrong place and events are misattributed between adjacent scenes. So
``propose`` writes YAML with ``approved: false`` and, for every scene, the
prose found at the anchor. ``apply`` ignores any chapter not marked approved.

Usage:

    scene_map propose --summaries-dir summaries/haiku
    #   review docs/ensemble/scene_map.yaml, set approved: true per chapter
    scene_map apply --out docs/chapters_scened
    #   then extract from the derived chapters:
    ensemble_batch --chapters 'docs/chapters_scened/chapter_*.md' --source chapter
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from campaignlib.scene_anchor import Anchor, anchor_scenes, inject_scene_headings
from campaignlib.textproc import chunk_by_scenes

DEFAULT_MAP = "docs/ensemble/scene_map.yaml"
DEFAULT_CHAPTERS = "docs/chapters/chapter_*.md"
DEFAULT_SUMMARIES = "summaries/haiku"
# A scene shorter than this is almost never real — it means two anchors landed
# on top of each other and the earlier scene was squeezed out. Flagged, not
# dropped: the GM decides whether to merge, re-title, or leave it.
SHORT_SPAN = 400


def _chapter_index(name: str) -> int | None:
    m = re.search(r"chapter_(\d+)", name)
    return int(m.group(1)) if m else None


def _scenes_of(summary_path: Path) -> tuple[list[str], list[str]]:
    """(scene bodies, scene titles) from a summary's ## Scenes section."""
    text = summary_path.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^##\s+Scenes\b.*?(?=^##\s+(?!#)|\Z)", text)
    if not m:
        return [], []
    parts = re.split(r"(?m)^(?=###\s)", m.group(0))[1:]
    return parts, [p.splitlines()[0].lstrip("#").strip() for p in parts]


def _pairs(campaign: Path, chapters_glob: str, summaries_dir: str):
    chapters, dupes = {}, set()
    for f in sorted(campaign.glob(chapters_glob)):
        i = _chapter_index(f.name)
        if i is None:
            continue
        if i in chapters:
            dupes.add(i)
        chapters[i] = f
    summaries = {}
    for d in sorted((campaign / summaries_dir).glob("*/")):
        m = re.match(r"0*(\d+)", d.name)
        p = d / "session-summary.md"
        if m and p.exists():
            summaries.setdefault(int(m.group(1)), []).append(p)
    return chapters, summaries, dupes


def cmd_propose(args) -> int:
    campaign = Path(args.campaign_dir)
    out = campaign / args.out
    chapters, summaries, dupes = _pairs(campaign, args.chapters_glob, args.summaries_dir)
    if dupes:
        print(f"ERROR: duplicate chapter indices {sorted(dupes)} — resolve first",
              file=sys.stderr)
        return 2
    collide = {k: v for k, v in summaries.items() if len(v) > 1}
    if collide:
        print("ERROR: two summary dirs claim one chapter index:", file=sys.stderr)
        for k, v in sorted(collide.items()):
            for p in v:
                print(f"  ch{k}: {p.parent.relative_to(campaign)}", file=sys.stderr)
        return 2

    prev = {}
    if out.exists():
        old = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
        prev = {c["chapter"]: c for c in (old.get("chapters") or []) if c.get("approved")}

    rows, n_scene, n_anch, n_flag = [], 0, 0, 0
    for i in sorted(summaries):
        if i not in chapters:
            continue
        ch = chapters[i]
        if ch.name in prev:                     # approved rows are never recomputed
            rows.append(prev[ch.name])
            continue
        bodies, titles = _scenes_of(summaries[i][0])
        if not bodies:
            continue
        ctext = ch.read_text(encoding="utf-8")
        anchors = anchor_scenes(ctext, bodies, titles)
        placed = [a for a in anchors if a is not None]
        scenes, flags = [], []
        for k, a in enumerate(anchors):
            if a is None:
                scenes.append({"title": titles[k], "offset": None,
                               "note": "unanchored — merges into the previous scene"})
                flags.append(f"{titles[k]!r} unanchored")
                continue
            nxt = next((x.offset for x in placed if x.offset > a.offset), len(ctext))
            span = nxt - a.offset
            row = {"title": a.title, "offset": a.offset, "span": span,
                   "hits": a.hits, "context": a.context}
            if span < SHORT_SPAN:
                row["flag"] = f"span {span} chars — likely a mis-anchor"
                flags.append(f"{a.title!r} span {span}")
            scenes.append(row)
        n_scene += len(anchors)
        n_anch += len(placed)
        n_flag += len(flags)
        derived = inject_scene_headings(ctext, anchors)
        probe = chunk_by_scenes(derived, 6000)
        rows.append({
            "chapter": ch.name, "chapter_index": i,
            "summary": str(summaries[i][0].parent.relative_to(campaign)),
            "approved": False,
            "scenes_proposed": len(placed),
            "chunks_if_applied": len(probe[0]) if probe else 0,
            "review_flags": flags or None,
            "scenes": scenes,
        })

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump({
        "chapters_glob": args.chapters_glob,
        "summaries_dir": args.summaries_dir,
        "stats": {"chapters": len(rows), "scenes": n_scene,
                  "anchored": n_anch, "review_flags": n_flag,
                  "preserved_approved": len(prev)},
        "chapters": rows,
    }, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")

    print(f"{len(rows)} chapters, {n_anch}/{n_scene} scenes anchored, "
          f"{n_flag} flagged for review, {len(prev)} approved rows preserved")
    print(f"-> {out}")
    print("Nothing is applied until a chapter's approved: true is set by hand. "
          "Check every scene's context line: an anchor in the wrong paragraph "
          "misattributes events to the neighbouring scene.")
    return 0


def cmd_apply(args) -> int:
    campaign = Path(args.campaign_dir)
    src = campaign / args.out
    if not src.exists():
        print(f"no map at {src} — run 'scene_map propose' first", file=sys.stderr)
        return 2
    doc = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    chapters, _, _ = _pairs(campaign, args.chapters_glob, args.summaries_dir)
    dest = campaign / args.dest
    dest.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for row in doc.get("chapters") or []:
        if not row.get("approved"):
            skipped += 1
            continue
        ch = chapters.get(row["chapter_index"])
        if ch is None or ch.name != row["chapter"]:
            print(f"  ch{row['chapter_index']}: chapter file changed since propose "
                  f"— re-run propose", file=sys.stderr)
            continue
        ctext = ch.read_text(encoding="utf-8")
        # Rebuild from the approved map, not by re-anchoring: the GM may have
        # hand-corrected an offset, and re-deriving would silently discard it.
        anchors = [
            Anchor(title=s["title"], offset=s["offset"], raw_offset=s["offset"],
                   hits=s.get("hits", 0), context=s.get("context", ""))
            for s in (row.get("scenes") or []) if s.get("offset") is not None
        ]
        derived = inject_scene_headings(ctext, anchors)
        (dest / ch.name).write_text(derived, encoding="utf-8")
        probe = chunk_by_scenes(derived, 6000)
        print(f"  {ch.name[:48]:50s} {len(anchors):>2} scenes -> "
              f"{len(probe[0]) if probe else 0} chunks ({probe[1] if probe else 'none'})")
        written += 1

    print(f"\nwrote {written} derived chapter(s) to {dest}; {skipped} unapproved skipped")
    if written:
        print(f"extract with:\n  ensemble_batch --chapters '{args.dest}/chapter_*.md' "
              f"--source chapter")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--campaign-dir", default=".", metavar="DIR")
    p.add_argument("--chapters-glob", default=DEFAULT_CHAPTERS, metavar="GLOB")
    p.add_argument("--summaries-dir", default=DEFAULT_SUMMARIES, metavar="DIR",
                   help="Root holding <NNN>-<slug>/session-summary.md dirs "
                        f"(default: {DEFAULT_SUMMARIES})")
    p.add_argument("--out", default=DEFAULT_MAP, metavar="FILE",
                   help=f"Boundary map (default: {DEFAULT_MAP})")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose", help="Anchor summary scenes into the chapter prose")
    ap = sub.add_parser("apply", help="Write derived chapters for approved rows")
    ap.add_argument("--dest", default="docs/chapters_scened", metavar="DIR")

    args = p.parse_args(argv)
    if args.cmd == "propose":
        return cmd_propose(args)
    if not hasattr(args, "dest"):
        args.dest = "docs/chapters_scened"
    return cmd_apply(args)


if __name__ == "__main__":
    sys.exit(main())
