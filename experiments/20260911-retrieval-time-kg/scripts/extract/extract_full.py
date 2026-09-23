#!/usr/bin/env python3
"""Extract ALL sections of every session summary, in play order. Pure code."""
import json, re
from pathlib import Path

ROOT = Path("/home/kostadis/obelisk/obelisk/summaries")
SECTIONS = ("Summary", "Memorable Moments", "Scenes", "NPCs", "Locations", "Items", "Spells")
DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
CH_RE = re.compile(r"chapter\s+(\d+)", re.I)

def split_sections(text):
    out, cur, buf = {}, None, []
    for ln in text.splitlines():
        m = re.match(r"^##\s+(?!#)(.*)$", ln)
        if m:
            if cur: out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(ln)
    if cur: out[cur] = "\n".join(buf).strip()
    return out

files = sorted({p for pat in ("session_summary.md","session-summary.md") for p in ROOT.rglob(pat)},
               key=lambda p: p.parent.name)
sessions = []
for i, p in enumerate(files, 1):
    txt = p.read_text(encoding="utf-8", errors="replace")
    title = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.startswith("# ")), p.parent.name)
    m = DATE_RE.search(p.parent.name) or DATE_RE.search(title)
    cm = CH_RE.search(title) or CH_RE.search(p.parent.name)
    secs = split_sections(txt)
    sessions.append({
        "order": i, "dir": p.parent.name, "file": p.name, "title": title,
        "chapter": int(cm.group(1)) if cm else None,
        "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None,
        "sections": {k: secs.get(k, "") for k in SECTIONS},
    })

out = Path("/home/kostadis/cognee-local/obelisk_full.json")
out.write_text(json.dumps(sessions, indent=2, ensure_ascii=False))

# also emit per-section digests for reading
D = Path("/home/kostadis/cognee-local/digests"); D.mkdir(exist_ok=True)
for sec in ("Summary", "NPCs", "Locations", "Items"):
    L = []
    for s in sessions:
        ch = f"Chapter {s['chapter']}" if s['chapter'] else s['title']
        L += [f"\n{'='*78}", f"SESSION {s['order']:02d} — {ch}"
              + (f" (played {s['date']})" if s['date'] else "") + f"  [{s['dir']}]",
              "="*78, s["sections"][sec] or "(empty)"]
    (D / f"{sec.lower()}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"  {sec:<10} -> digests/{sec.lower()}.md  ({(D/f'{sec.lower()}.md').stat().st_size/1024:.1f} KB)")
print(f"\n{len(sessions)} sessions -> {out}")
