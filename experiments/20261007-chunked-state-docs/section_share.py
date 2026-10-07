"""Share of each run's map output spent per section (chars), and the useful (non-audit) rate."""
import glob
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipelines.summary_native import npc_check  # noqa: E402

WALL = {"run1": 1240 + 671, "run2": 4333, "run3": 1833}  # map wall seconds as logged at run time
for run in sys.argv[1:]:
    tot, by = 0, {}
    for f in glob.glob(f"{run}/map/*.out.md"):
        text = Path(f).read_text(encoding="utf-8")
        tot += len(text)
        for h, (_, lines) in npc_check.parse_sections(text).items():
            by[h] = by.get(h, 0) + len("\n".join(lines))
    audit = by.get("## Audit", 0)
    useful = tot - audit
    print(f"{run}: total {tot/1000:.0f}K, audit {audit/1000:.0f}K ({100*audit/tot:.0f}%), "
          f"non-audit {useful/1000:.0f}K -> {useful/WALL[run]/4:.0f} useful tok/s over {WALL[run]}s map wall")
