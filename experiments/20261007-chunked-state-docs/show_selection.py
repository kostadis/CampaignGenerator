"""Print an npc-draft selection.json: who is in, why, and what was excluded."""
import json
import sys
from collections import Counter

d = json.load(open(sys.argv[1]))
print(len(d["included"]), "included:")
print(", ".join(f"{i['subject']} ({i['reason']})" for i in d["included"]))
print("excluded:", dict(Counter(e["reason"] for e in d["excluded"])))
