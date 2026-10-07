"""List the non-verbatim quoted spans in a document, with the closest summary text for each."""
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipelines.summary_native import npc_check  # noqa: E402
import chunked_state as cs  # noqa: E402

chapters = cs.load_chapters(Path(sys.argv[1]) / "docs" / "summaries", 2, 70)
hay = "\n".join(c.text for c in chapters)
folded = npc_check.fold_typography(hay).casefold()
text = Path(sys.argv[2]).read_text(encoding="utf-8")
for span in npc_check.SPAN_RE.findall(text):
    inner = npc_check.strip_quote_marks(span)
    if len(inner) < 4 or npc_check._contains(hay, inner) is not None:
        continue
    key = npc_check.fold_typography(inner).casefold()
    kind = "case/typography only" if key in folded else "not in summaries"
    near = ""
    words = key.split()
    if kind != "case/typography only" and len(words) >= 2:
        anchor = folded.find(" ".join(words[:2]))
        if anchor >= 0:
            near = hay[anchor:anchor + len(inner) + 20].replace("\n", " ")
    print(f"- [{kind}] {span[:110]}" + (f"\n    nearest: {near[:130]}" if near else ""))
