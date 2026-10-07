"""Follow-up checks: quote rate outside the audit, invalid citations, NPC table name variants."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipelines.summary_native import npc_check  # noqa: E402
import chunked_state as cs  # noqa: E402

camp, base_dir, run = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
chapters = cs.load_chapters(camp / "docs" / "summaries", 2, 70)
hay = "\n".join(c.text for c in chapters)
allowed = {c.number: c.targets for c in chapters}

for label, path in (("baseline", base_dir / "campaign_state.draft.md"), ("chunked", run / "campaign_state.chunked.md")):
    text = path.read_text(encoding="utf-8").split("## Audit: Tracking Claims")[0]
    spans = [s for s in npc_check.SPAN_RE.findall(text) if len(npc_check.strip_quote_marks(s)) >= 4]
    ok = [s for s in spans if npc_check._contains(hay, npc_check.strip_quote_marks(s)) is not None]
    print(f"campaign_state {label} (audit excluded): {len(ok)}/{len(spans)} quoted spans verbatim")
    for s in spans:
        if s not in ok:
            print("   not found:", s[:110])

print("\nInvalid citations in chunked docs:")
for doc in ("world_state", "campaign_state"):
    for n, line in enumerate((run / f"{doc}.chunked.md").read_text(encoding="utf-8").splitlines(), 1):
        for b, c, t in cs.cites(line):
            if c < 0 or c not in allowed or t not in allowed[c]:
                print(f"  {doc}:{n} {b} :: {line.strip()[:120]}")

print("\nNPC table: rows whose name is a prefix/word-subset of another row (possible same-entity splits):")
table = (run / "campaign_state.chunked.md").read_text(encoding="utf-8").split("## NPC Current States")[1].split("\n## ")[0]
names = [r.split("|")[1].strip() for r in table.splitlines() if r.startswith("| ") and not r.startswith("| NPC")]
for a in names:
    for b in names:
        if a != b and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", b):
            print(f"  {a!r}  ⊂  {b!r}")
