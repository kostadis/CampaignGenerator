#!/usr/bin/env python3
"""Event-ordinal knowledge graph, built deterministically from session summaries.

Time is the EVENT SEQUENCE, not the calendar. Every scene gets a global ordinal
from (filename order, scene position, beat position), so undated sessions sort
correctly and "most recent" is simply the highest ordinal.

Two layers, both copied from human-authored sections, no model in the path:
  events / beats  <- ## Scenes         (what happened, in order)
  snapshots       <- ## NPCs/Locations/Items  (state at the end of each session)
"""
import re, sqlite3
from pathlib import Path

SRC = Path("/home/kostadis/obelisk/obelisk/docs/summaries")
DB = Path("/home/kostadis/cognee-local/event_kg.sqlite3")
DB.unlink(missing_ok=True)
db = sqlite3.connect(DB)
db.executescript("""
CREATE TABLE sessions (sess TEXT PRIMARY KEY, ord INTEGER, title TEXT, date TEXT,
                       written INTEGER, first_ev INTEGER, last_ev INTEGER);
CREATE TABLE events   (ev INTEGER PRIMARY KEY, sess TEXT, scene_idx INTEGER,
                       title TEXT, summary TEXT);
CREATE TABLE beats    (ev INTEGER, beat_idx INTEGER, text TEXT);
CREATE TABLE mentions (ev INTEGER, entity TEXT);
CREATE TABLE snapshots(entity TEXT, sess TEXT, as_of_ev INTEGER, section TEXT, text TEXT);
""")

def sections(text):
    out, cur, buf = {}, None, []
    for ln in text.splitlines():
        m = re.match(r"^##\s+(?!#)(.*)$", ln)
        if m:
            if cur: out[cur] = "\n".join(buf)
            cur, buf = m.group(1).strip(), []
        elif cur is not None:
            buf.append(ln)
    if cur: out[cur] = "\n".join(buf)
    return out

def entries(body):
    out, t, buf = [], None, []
    for ln in (body or "").splitlines():
        m = re.match(r"^###\s+(?!#)(.*)$", ln)
        if m:
            if t: out.append((t, "\n".join(buf).strip()))
            t, buf = m.group(1).strip(), []
        elif t: buf.append(ln)
    if t: out.append((t, "\n".join(buf).strip()))
    return out

def canon(t):   # "Wick *(Chapter 7 — carried forward)*" -> "Wick"
    return re.sub(r"\s*[*(].*$", "", t).strip()

files = sorted(SRC.glob("*.md"), key=lambda p: (int(p.name[:3]), p.name[3:4]))
ev, parsed = 0, []
for order, f in enumerate(files, 1):
    sess = re.match(r"(\d{3}[a-z]?)", f.name).group(1)
    text = f.read_text(encoding="utf-8")
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), sess)
    date = (re.search(r"^Date: (\S+)", text, re.M) or [None, None])[1]
    secs = sections(text)
    first = ev + 1
    for idx, (st, sbody) in enumerate(entries(secs.get("Scenes")), 1):
        ev += 1
        lines = sbody.splitlines()
        summ = next((l[5:].strip() for l in lines if l.startswith("#### ")), "")
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (ev, sess, idx, st, summ))
        for b, bl in enumerate([l.strip()[2:] for l in lines if l.strip().startswith("- ")], 1):
            db.execute("INSERT INTO beats VALUES (?,?,?)", (ev, b, bl))
    last = ev if ev >= first else None
    written = int(bool(secs.get("Scenes")))
    db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
               (sess, order, title, date, written, first if last else None, last))
    parsed.append((sess, secs, last))

# canonical entities + surface forms come from the campaign's REVIEWED alias file.
# Deciding which names refer to the same entity is the one precision decision in
# this design; it is made by the GM in aliases.json, never inferred here.
import json
ALIASES = json.load(open("/home/kostadis/obelisk/obelisk/docs/aliases.json"))
npc_heads = {canon(t) for _, secs, _ in parsed for t, _ in entries(secs.get("NPCs"))} - {""}
surface = {}                                   # canonical -> [surface forms]
for c, forms in ALIASES.items():
    surface[c] = sorted({c, *forms}, key=len, reverse=True)
for h in npc_heads:                            # NPCs with no alias entry keep their heading
    if not any(h == c or h in forms for c, forms in surface.items()):
        surface[h] = [h]
entities = sorted(surface)

# mentions: attribute any surface form to its canonical entity
for (e, t, s) in db.execute("SELECT ev, title, summary FROM events").fetchall():
    body = " ".join([t, s] + [r[0] for r in db.execute("SELECT text FROM beats WHERE ev=?", (e,))])
    for c, forms in surface.items():
        if any(len(f) > 2 and re.search(r"\b" + re.escape(f) + r"\b", body) for f in forms):
            db.execute("INSERT INTO mentions VALUES (?,?)", (e, c))

# snapshots: each session's entry = state as of that session's last event
for sess, secs, last in parsed:
    if last is None: continue
    for section in ("NPCs", "Locations", "Items"):
        for t, body in entries(secs.get(section)):
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (canon(t), sess, last, section, body))
db.commit()

for tbl in ("sessions", "events", "beats", "mentions", "snapshots"):
    print(f"  {tbl:<10} {db.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]:>5}")
print(f"  entities   {len(entities):>5}")
print(f"\n-> {DB}")
