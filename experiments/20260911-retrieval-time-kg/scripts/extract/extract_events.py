#!/usr/bin/env python3
"""Deterministically extract the AUTHORED ordered event spine from session summaries.

No LLM. The ordering is already in the documents:
    ## Scenes -> ### <scene title> -> #### <description> -> ordered '-' beats

Emits chapter -> scene(index) -> beat(index), a total order across the campaign.
"""
import json, re, sys
from pathlib import Path

ROOT = Path("/home/kostadis/obelisk/obelisk/summaries")
DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
CH_RE = re.compile(r"chapter\s+(\d+)", re.I)


def parse(path: Path, order: int):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    title = next((l.lstrip("# ").strip() for l in lines if l.startswith("# ")), path.parent.name)

    m = DATE_RE.search(path.parent.name) or DATE_RE.search(title)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    cm = CH_RE.search(title) or CH_RE.search(path.parent.name)
    chapter = int(cm.group(1)) if cm else None

    scenes, cur, in_scenes = [], None, False
    for ln in lines:
        if re.match(r"^##\s+Scenes\s*$", ln, re.I):
            in_scenes = True; continue
        if in_scenes and re.match(r"^##\s+(?!#)", ln):   # next top-level section ends Scenes
            break
        if not in_scenes:
            continue
        if ln.startswith("### "):
            cur = {"index": len(scenes) + 1, "title": ln[4:].strip(), "description": "", "beats": []}
            scenes.append(cur); continue
        if cur is None:
            continue
        if ln.startswith("#### "):
            cur["description"] = ln[5:].strip()
        elif ln.strip().startswith("- "):
            cur["beats"].append(ln.strip()[2:].strip())

    return {"order": order, "dir": path.parent.name, "file": path.name, "title": title,
            "chapter": chapter, "date": date, "scenes": scenes}


def main():
    files = sorted(
        {p for pat in ("session_summary.md", "session-summary.md") for p in ROOT.rglob(pat)},
        key=lambda p: p.parent.name,
    )
    sessions = [parse(p, i + 1) for i, p in enumerate(files)]
    out = Path("/home/kostadis/cognee-local/obelisk_events.json")
    out.write_text(json.dumps(sessions, indent=2, ensure_ascii=False))

    ts = tb = 0
    print(f"{'ord':>3} {'dir':<22} {'ch':>3} {'date':<11} {'scenes':>6} {'beats':>6}  title")
    for s in sessions:
        nb = sum(len(x["beats"]) for x in s["scenes"])
        ts += len(s["scenes"]); tb += nb
        print(f"{s['order']:>3} {s['dir']:<22} {str(s['chapter']):>3} {str(s['date']):<11} "
              f"{len(s['scenes']):>6} {nb:>6}  {s['title'][:44]}")
    print(f"\nTOTAL: {len(sessions)} sessions, {ts} scenes, {tb} beats -> {out}")


main()
