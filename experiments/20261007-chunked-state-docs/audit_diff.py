"""Side-by-side audit disagreements: item, each draft's line, for adjudication against the summaries."""
import json
import re
import sys
from pathlib import Path

base = Path(sys.argv[1]).read_text(encoding="utf-8").split("## Audit: Tracking Claims")[1]
chk = Path(sys.argv[2]).read_text(encoding="utf-8").split("## Audit: Tracking Claims")[1]
cmp_ = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))["audit"]
n = int(sys.argv[4]) if len(sys.argv) > 4 else 8


def entry(text: str, item: str) -> str:
    m = re.search(rf'^- "{re.escape(item)}".*?(?=^- "|^### |\Z)', text, re.M | re.S)
    return " ".join(m.group(0).split())[:600] if m else "(missing)"


for title, key in (("BASELINE SUPPORTED, CHUNKED NOT", "baseline_supported_chunked_not"),
                   ("CHUNKED SUPPORTED, BASELINE NOT", "chunked_supported_baseline_not")):
    items = cmp_[key]
    print(f"\n######## {title} ({len(items)}) — first {n}\n")
    for it in items[:n]:
        print("ITEM:", it)
        print("  baseline:", entry(base, it))
        print("  chunked: ", entry(chk, it))
        print()
