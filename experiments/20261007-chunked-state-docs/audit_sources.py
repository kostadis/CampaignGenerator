"""How many SUPPORTED audit verdicts rest only on one chunk's evidence (default: the ch 026 runaway)."""
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8").split("## Audit: Tracking Claims")[1]
bad_cite = sys.argv[2] if len(sys.argv) > 2 else "[ch 026 / 026.01]"
only_bad, total = 0, 0
for block in re.split(r"(?m)^(?=- \")", text):
    if "`SUPPORTED`" not in block.split("\n", 1)[0]:
        continue
    total += 1
    ev = [ln for ln in block.splitlines()[1:] if ln.strip().startswith("- ")]
    if ev and all(bad_cite in ln for ln in ev):
        only_bad += 1
print(f"SUPPORTED: {total}; resting only on {bad_cite}: {only_bad}; otherwise: {total - only_bad}")
