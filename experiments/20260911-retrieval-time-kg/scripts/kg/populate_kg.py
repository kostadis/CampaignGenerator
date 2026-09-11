#!/usr/bin/env python3
"""Populate the ISOLATED palace's KG from the session summaries. No LLM.

Tier A (mechanical): for each session file, for each tracked name that appears in
it, one triple  (name) -appears_in-> (session NNN), valid_from = that file's Date:
line. Undated sessions get valid_from=None -- NOT an invented date.

Tier B (cited): a few state changes with validity windows, to exercise
invalidate() and the `current` flag. Each is tied to a verbatim source line.
"""
import re
from pathlib import Path
from mempalace.knowledge_graph import KnowledgeGraph

PALACE = "/home/kostadis/cognee-local/mempalace-exp/palace"
SRC = Path("/home/kostadis/cognee-local/mempalace-exp/source")
NAMES = ["Gundren", "Sildar", "Glasstaff", "Iarno", "Droop", "Ruxithid", "Hamun Kost",
         "Harbin Wester", "Halia Thornton", "Ssarnak", "Nosk", "Black Spider", "Zenvon"]

kg = KnowledgeGraph(palace_path=PALACE)
assert PALACE in kg.db_path if hasattr(kg, "db_path") else True

dates, n = {}, 0
for f in sorted(SRC.glob("*.md")):
    sess = re.match(r"(\d{3}[a-z]?)", f.name).group(1)
    text = f.read_text(encoding="utf-8")
    m = re.search(r"^Date: (\d{4}-\d{2}-\d{2})", text, re.M)
    dates[sess] = m.group(1) if m else None
    for name in NAMES:
        if re.search(re.escape(name), text, re.I):
            kg.add_triple(name, "appears_in", f"session {sess}", valid_from=dates[sess],
                          source_file=f.name, adapter_name="deterministic-scan")
            n += 1

# Tier B — state changes. (subject, pred, obj, valid_from, ended, source)
STATES = [
  ("Glasstaff", "located_at", "Tresendar Manor", "2026-07-03", "2026-07-16",
   "005: Rondar places him at Tresendar; 006: escaped using teleportation"),
  ("Glasstaff", "status", "at large", "2026-07-16", None,
   "006: 'He escaped using movement and teleportation'"),
  ("Droop", "status", "left behind fainted in the barracks", "2026-08-02", None,
   "008: 'The party left him behind during the retreat'"),
  ("Party", "located_at", "Phandalin", "2026-08-02", "2026-08-21",
   "008: returned to the Stonehill Inn; 010: departs for Old Owl Well"),
  ("Party", "located_at", "Old Owl Well", "2026-09-05", None,
   "011: 'dinner with Hamun Kost'"),
  ("Party", "level", "3", "2026-08-02", "2026-09-05", "008: 'reaching 3rd level'"),
  ("Party", "level", "4", "2026-09-05", None, "011: 'advancement to level 4'"),
]
for s, p, o, vf, ended, src in STATES:
    kg.add_triple(s, p, o, valid_from=vf, source_file=src, adapter_name="cited-state")
    if ended:
        kg.invalidate(s, p, o, ended=ended)
    n += 1

print(f"triples written: {n}")
print(f"undated sessions (valid_from=None): {[k for k,v in dates.items() if v is None]}")
print("stats:", kg.stats())
