#!/usr/bin/env python3
"""Turn the extracted event spine into one document per scene.

The ordering is authored, so it is written into each document as an explicit
STATEMENT rather than left for the LLM to infer:
  - absolute position (session N of M, scene X of Y, global scene G of T)
  - the named scene immediately before and after

Deterministic. No LLM.
"""
import json
from pathlib import Path

SRC = Path("/home/kostadis/cognee-local/obelisk_events.json")
OUT = Path("/home/kostadis/cognee-local/scene_docs")
OUT.mkdir(exist_ok=True)
for old in OUT.glob("*.md"):
    old.unlink()

sessions = json.loads(SRC.read_text())
flat = [(s, sc) for s in sessions for sc in s["scenes"]]
total = len(flat)
nsess = len(sessions)

for g, (s, sc) in enumerate(flat, start=1):
    prev = flat[g - 2][1]["title"] if g > 1 else None
    nxt = flat[g][1]["title"] if g < total else None
    prev_s = flat[g - 2][0] if g > 1 else None
    nxt_s = flat[g][0] if g < total else None

    ch = f"Chapter {s['chapter']}" if s["chapter"] else s["title"]
    when = f", played {s['date']}" if s["date"] else ""

    L = [
        f"# {ch} · Scene {sc['index']} — {sc['title']}",
        "",
        "## Position in the campaign",
        f"- This is **scene {sc['index']} of {len(s['scenes'])}** in **session {s['order']} of {nsess}** ({ch}{when}).",
        f"- Globally this is **event {g} of {total}** in the campaign, counted in play order.",
        f"- Source session document: `summaries/{s['dir']}/{s['file']}` (session title: {s['title']}).",
    ]
    if prev:
        w = "the same session" if prev_s is s else f"session {prev_s['order']}"
        L.append(f"- The scene immediately BEFORE this one is **\"{prev}\"** (in {w}).")
    else:
        L.append("- This is the **first scene of the campaign**. Nothing precedes it.")
    if nxt:
        w = "the same session" if nxt_s is s else f"session {nxt_s['order']}"
        L.append(f"- The scene immediately AFTER this one is **\"{nxt}\"** (in {w}).")
    else:
        L.append("- This is the **most recent scene of the campaign**. Nothing follows it yet.")

    L += ["", "## What happens", sc["description"] or "(no summary line)", "",
          "## Beats, in order"]
    L += [f"{i}. {b}" for i, b in enumerate(sc["beats"], 1)] or ["(no beats recorded)"]

    name = f"{g:03d}_s{s['order']:02d}_sc{sc['index']:02d}_" + \
           "".join(c if c.isalnum() else "_" for c in sc["title"])[:48].strip("_") + ".md"
    (OUT / name).write_text("\n".join(L) + "\n", encoding="utf-8")

tot = sum(p.stat().st_size for p in OUT.glob("*.md"))
print(f"wrote {len(list(OUT.glob('*.md')))} scene docs, {tot/1024:.1f} KB -> {OUT}")
