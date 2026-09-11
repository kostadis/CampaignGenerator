#!/usr/bin/env python3
"""Deterministic, fully-cited delta: what happened AFTER the state docs' cutoff.

world_state.md  = "Canon current as of Chapter 8"
campaign_state.md = "DRAFT (through Chapter 8)"
...but sessions 10 and 11 are played and recorded.

Pure code. Every line traces to session/scene/beat. This is the reviewable
input a synthesis pass should run against -- not a replacement for it.
"""
import json
from pathlib import Path

SRC = Path("/home/kostadis/cognee-local/obelisk_events.json")
OUT = Path("/home/kostadis/cognee-local/state_delta_ch9plus.md")
CUTOFF_ORDER = 9          # sessions 1..9 are covered (9 == the Ch.8 doc)

S = json.loads(SRC.read_text())
after = [s for s in S if s["order"] > CUTOFF_ORDER]

L = ["# State delta — sessions after the Chapter 8 cutoff", "",
     "> Deterministically generated from `obelisk_events.json` (the authored",
     "> `## Scenes` spine of each session summary). No LLM. Every beat is cited",
     "> `[session N · scene M · beat K]` and appears in authored order.", "",
     f"> Covers {len(after)} sessions not reflected in `docs/world_state.md`",
     "> (\"canon current as of Chapter 8\") or `docs/campaign_state.md`", ""]

gbase = sum(len(s["scenes"]) for s in S if s["order"] <= CUTOFF_ORDER)
g = gbase
for s in after:
    ch = f"Chapter {s['chapter']}" if s["chapter"] else s["title"]
    when = f" — played {s['date']}" if s["date"] else ""
    L += ["---", "", f"## {ch}{when}",
          f"*Session {s['order']} of {len(S)} · source `summaries/{s['dir']}/{s['file']}`*", ""]
    for sc in s["scenes"]:
        g += 1
        L += [f"### Scene {sc['index']} — {sc['title']}  *(campaign event {g})*", ""]
        if sc["description"]:
            L += [f"{sc['description']}", ""]
        for k, b in enumerate(sc["beats"], 1):
            L.append(f"- {b}  `[s{s['order']:02d}·sc{sc['index']}·b{k}]`")
        L.append("")

OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
nb = sum(len(sc["beats"]) for s in after for sc in s["scenes"])
print(f"sessions after cutoff: {[s['order'] for s in after]}")
print(f"scenes: {sum(len(s['scenes']) for s in after)}  beats: {nb}")
print(f"wrote {OUT}  ({OUT.stat().st_size/1024:.1f} KB)")
