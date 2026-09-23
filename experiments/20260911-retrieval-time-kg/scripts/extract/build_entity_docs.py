#!/usr/bin/env python3
"""One document per (session, section, entity) from the NPCs/Locations/Items sections.

WHY: the abandonment of Droop sat in a single 18,987-char chunk covering 13 NPCs
at once. Its embedding represented all of them, so a "what happened to Droop"
query ranked the 2.3KB scene doc (which has only the fainting) far above it.
The consequence was invisible to retrieval while the beat was not.

Scene docs already cover the ## Scenes section. This covers the sections that
carry OUTCOMES -- who ended up where, what state they are in, what was taken.

Deterministic. No LLM.
"""
import json, re
from pathlib import Path

SRC = Path("/home/kostadis/cognee-local/obelisk_full.json")
OUT = Path("/home/kostadis/cognee-local/entity_docs")
OUT.mkdir(exist_ok=True)
for old in OUT.glob("*.md"):
    old.unlink()

SECTIONS = ("NPCs", "Locations", "Items")
sessions = json.loads(SRC.read_text())
NS = len(sessions)


def split_entries(body: str):
    """### Title  ->  (title, body) in document order."""
    out, title, buf = [], None, []
    for ln in (body or "").splitlines():
        m = re.match(r"^###\s+(?!#)(.*)$", ln)
        if m:
            if title is not None:
                out.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1).strip(), []
        elif title is not None:
            buf.append(ln)
    if title is not None:
        out.append((title, "\n".join(buf).strip()))
    return out


def canon(title: str) -> str:
    """Normalised key for linking the same entity across sessions."""
    t = re.sub(r"\*\(.*?\)\*", "", title)          # drop *(Chapter 7 — carried forward)*
    t = re.sub(r"[*_`]", "", t)
    t = re.sub(r"\(.*?\)", "", t)                   # drop (Glasstaff)
    t = t.strip().lower()
    t = re.sub(r"^the\s+", "", t)
    return re.sub(r"[^a-z0-9 ]", "", t).strip()


# pass 1: collect every entry, keyed for cross-session linking
entries = []           # (session, section, title, body, key)
for s in sessions:
    for sec in SECTIONS:
        for title, body in split_entries(s["sections"].get(sec)):
            entries.append((s, sec, title, body, canon(title)))

appearances = {}
for s, sec, title, body, key in entries:
    appearances.setdefault(key, []).append(s["order"])
for k in appearances:
    appearances[k] = sorted(set(appearances[k]))

# pass 2: write one document per entry
count = 0
for s, sec, title, body, key in entries:
    ch = f"Chapter {s['chapter']}" if s["chapter"] else s["title"]
    when = f", played {s['date']}" if s["date"] else ""
    seen = appearances[key]
    prev = [o for o in seen if o < s["order"]]
    nxt = [o for o in seen if o > s["order"]]

    L = [f"# {title} — {ch}, session {s['order']} of {NS}",
         "",
         "## Position in the campaign",
         f"- This is the **{sec}** entry for **{title}** as recorded in "
         f"**session {s['order']} of {NS}** ({ch}{when}).",
         f"- Source: `summaries/{s['dir']}/{s['file']}`, section `## {sec}`.",
         f"- Entries under this exact name appear in sessions: "
         f"{', '.join(str(o) for o in seen)}."]
    L.append(f"- Previous entry under this name: **session {prev[-1]}**."
             if prev else "- This is the **first** entry under this name.")
    L.append(f"- Next entry under this name: **session {nxt[0]}**."
             if nxt else "- This is the **most recent** entry under this name. "
                         "Nothing later is recorded.")
    L += ["", f"## What the record says about {title} in this session", "",
          body or "(no detail recorded)"]

    slug = re.sub(r"[^A-Za-z0-9]+", "_", title)[:52].strip("_")
    (OUT / f"s{s['order']:02d}_{sec.lower()}_{slug}.md").write_text(
        "\n".join(L) + "\n", encoding="utf-8")
    count += 1

sz = sum(p.stat().st_size for p in OUT.glob("*.md"))
print(f"wrote {count} entity docs, {sz/1024:.1f} KB (avg {sz//count} B) -> {OUT}")
multi = {k: v for k, v in appearances.items() if len(v) > 1}
print(f"entities appearing in >1 session: {len(multi)}")
for k in sorted(multi, key=lambda k: -len(multi[k]))[:8]:
    print(f"   {k:<28} sessions {multi[k]}")
