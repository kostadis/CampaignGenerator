#!/usr/bin/env python3
"""Event-ordinal KG over the Phandalin summaries — prototype / measurement pass.

Adapted from experiments/20260911-retrieval-time-kg/scripts/kg/event_kg.py.
Differences, all deliberate:
  * identity comes from docs/entity_registry.yaml (typed, GM-reviewed, carries
    rejected_aliases) rather than the flat aliases.json
  * snapshot keys are resolved through the alias map  -- STATE_GENERATION_METHOD 8.2, known bug
  * chapter number is a separate field from the ordinal -- 8.7
  * date is stored raw + classified, never used for ordering -- 8.6
Read-only against the repo; writes only to this scratch dir.
"""
import re, json, sqlite3, sys
from pathlib import Path
from collections import defaultdict

SRC  = Path("/home/kostadis/phandalin/Phandalin/docs/summaries")
REG  = Path("/home/kostadis/phandalin/Phandalin/docs/entity_registry.yaml")
OUT  = Path(__file__).parent
DB   = OUT / "phandalin_kg.sqlite3"
DB.unlink(missing_ok=True)
db = sqlite3.connect(DB)
db.executescript("""
CREATE TABLE sessions (sess TEXT PRIMARY KEY, ord INTEGER, chapter INTEGER,
                       title TEXT, date_raw TEXT, date_kind TEXT,
                       written INTEGER, first_ev INTEGER, last_ev INTEGER);
CREATE TABLE events   (ev INTEGER PRIMARY KEY, sess TEXT, scene_idx INTEGER,
                       title TEXT, summary TEXT, line INTEGER);
CREATE TABLE beats    (ev INTEGER, beat_idx INTEGER, text TEXT);
CREATE TABLE mentions (ev INTEGER, entity TEXT);
CREATE TABLE snapshots(entity TEXT, raw_head TEXT, sess TEXT, as_of_ev INTEGER,
                       section TEXT, text TEXT, chars INTEGER);
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

def canon_head(t):
    return re.sub(r"\s*[*(].*$", "", t).strip()

def classify_date(d):
    if not d: return "missing"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", d): return "iso"
    if re.search(r"\d{1,2}(st|nd|rd|th),", d): return "us-long"
    if "Taraskh" in d or re.search(r"\b1[45]\d{2}\b", d): return "in-world"
    return "other"

# ---------------------------------------------------------------- parse corpus
files = sorted(SRC.glob("*.md"), key=lambda p: (int(p.name[:3]), p.name[3:4]))
ev, parsed = 0, []
for order, f in enumerate(files, 1):
    sess = re.match(r"(\d{3}[a-z]?)", f.name).group(1)
    text = f.read_text(encoding="utf-8")
    h1   = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), sess)
    ch   = re.match(r"Chapter\s+(\d+)", h1)
    chapter = int(ch.group(1)) if ch else None
    title   = h1.split(":", 1)[1].strip() if ":" in h1 else h1
    dm   = re.search(r"^Date:\s*(.+)$", text, re.M)
    date_raw = dm.group(1).strip() if dm else None
    secs = sections(text)
    # line numbers for citation
    lineno = {ln.strip(): i+1 for i, ln in enumerate(text.splitlines())}
    first = ev + 1
    for idx, (st, sbody) in enumerate(entries(secs.get("Scenes")), 1):
        ev += 1
        lines = sbody.splitlines()
        summ  = next((l[5:].strip() for l in lines if l.startswith("#### ")), "")
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                   (ev, sess, idx, st, summ, lineno.get("### " + st, 0)))
        for b, bl in enumerate([l.strip()[2:] for l in lines if l.strip().startswith("- ")], 1):
            db.execute("INSERT INTO beats VALUES (?,?,?)", (ev, b, bl))
    last = ev if ev >= first else None
    db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
               (sess, order, chapter, title, date_raw, classify_date(date_raw),
                int(bool(secs.get("Scenes"))), first if last else None, last))
    parsed.append((sess, secs, last, f.name))

# ------------------------------------------------------- identity from registry
raw = REG.read_text(encoding="utf-8")
surface, etype = {}, {}
cur = None
for ln in raw.splitlines():
    if ln.startswith("- name: "):
        cur = ln[len("- name: "):].strip().strip('"\'')
        surface[cur] = {cur}
    elif cur and ln.startswith("  type: "):
        etype[cur] = ln[len("  type: "):].strip()
    elif cur and re.match(r"^  - ", ln) and "aliases" not in ln:
        a = ln[4:].strip().strip('"\'')
        if a: surface[cur].add(a)
    elif ln.startswith("distinct:") or ln.startswith("rejected_aliases:"):
        cur = None
# entity registry `aliases:` lists are the only "  - " lines under a name block,
# but note/type continuation lines can wrap; drop anything that looks like prose
for c in list(surface):
    surface[c] = {s for s in surface[c] if len(s) <= 60 and not s.endswith(",")}

# headings that have no registry entry keep themselves as their own entity
npc_heads = {canon_head(t) for _, secs, _, _ in parsed
             for sec in ("NPCs", "Locations", "Items")
             for t, _ in entries(secs.get(sec))} - {""}
known = {s.lower() for forms in surface.values() for s in forms}
unregistered = {h for h in npc_heads if h.lower() not in known}
for h in unregistered:
    surface.setdefault(h, {h})
    etype.setdefault(h, "unregistered")

# surface form -> canonical, longest first
form2canon = {}
for c, forms in surface.items():
    for f in forms:
        if len(f) > 2:
            form2canon.setdefault(f, c)
ordered = sorted(form2canon, key=len, reverse=True)
BIG = re.compile(r"\b(" + "|".join(re.escape(f) for f in ordered) + r")\b")

# -------------------------------------------------------------------- mentions
beats_by_ev = defaultdict(list)
for e, t in db.execute("SELECT ev, text FROM beats"):
    beats_by_ev[e].append(t)
for (e, t, s) in db.execute("SELECT ev, title, summary FROM events").fetchall():
    body = " ".join([t, s] + beats_by_ev[e])
    hits = {form2canon[m] for m in BIG.findall(body)}
    for c in hits:
        db.execute("INSERT INTO mentions VALUES (?,?)", (e, c))

# ------------------------------------------------------------------- snapshots
drift = defaultdict(set)
for sess, secs, last, fname in parsed:
    if last is None: continue
    for section in ("NPCs", "Locations", "Items"):
        for t, body in entries(secs.get(section)):
            head = canon_head(t)
            resolved = form2canon.get(head, head)          # 8.2 fix
            drift[resolved].add(head)
            db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)",
                       (resolved, head, sess, last, section, body, len(body)))
db.commit()

q = lambda s: db.execute(s).fetchone()[0]
print("=" * 66)
print("BUILD")
print("=" * 66)
for tbl in ("sessions", "events", "beats", "mentions", "snapshots"):
    print(f"  {tbl:<12}{q('SELECT COUNT(*) FROM '+tbl):>7}")
print(f"  entities    {len(surface):>7}   (registry {len(surface)-len(unregistered)}, "
      f"unregistered heads {len(unregistered)})")
print(f"  written     {q('SELECT COUNT(*) FROM sessions WHERE written=1'):>7} of "
      f"{q('SELECT COUNT(*) FROM sessions')}")
json.dump({"unregistered": sorted(unregistered)}, open(OUT/"unregistered.json","w"), indent=1)
