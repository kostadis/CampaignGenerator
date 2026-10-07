"""Deterministic comparison: one-shot Opus drafts vs chunked Spark drafts. No model call.

    python compare.py --campaign DIR --baseline DRAFTS_DIR --chunked RUN_DIR > comparison.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipelines.summary_native import npc_check  # noqa: E402
import chunked_state as cs  # noqa: E402

SCENE_ID_RE = re.compile(r"\b(\d{3}\.\d{2})\b")
CH_RE = re.compile(r"\bch\s*0*(\d{1,3})\b")


def sections(text: str) -> dict[str, str]:
    secs = npc_check.parse_sections(text)
    return {h: npc_check.section_text(secs, h) for h in secs}


def doc_metrics(text: str, scenes: set[str], hay: str, chapters_text: dict[int, str], registry: list[tuple[str, list[str]]]) -> dict:
    secs = sections(text)
    cited_scenes = set(SCENE_ID_RE.findall(text))
    cited_ch = {int(c) for c in CH_RE.findall(text)}
    spans = npc_check.SPAN_RE.findall(text)
    span_ok = sum(1 for s in spans if len(npc_check.strip_quote_marks(s)) < 4 or npc_check._contains(hay, npc_check.strip_quote_marks(s)) is not None)
    # chunked-format citations: every [ch NNN / target] must exist in the corpus
    targets = {n: cs.Chapter(n, Path(""), t) for n, t in chapters_text.items()}
    for ch in targets.values():
        ch.targets = set(cs.SCENE_RE.findall(ch.text)) | {
            v for k, v in cs.SECTION_TARGETS.items() if re.search(rf"^{re.escape(k)}\s*$", ch.text, re.M)}
    parts = cs.cites(text)
    bad_parts = [b for b, c, t in parts if c < 0 or c not in targets or t not in targets[c].targets]
    ents = {n for n, forms in registry if any(re.search(rf"(?<!\w){re.escape(f)}(?!\w)", text) for f in forms)}
    return {
        "chars": len(text),
        "words": len(text.split()),
        "bullets": sum(1 for ln in text.splitlines() if re.match(r"^\s*[-*] ", ln)),
        "sections": {h: {"chars": len(b), "bullets": sum(1 for ln in b.splitlines() if re.match(r"^\s*[-*] ", ln)),
                         "table_rows": max(0, sum(1 for ln in b.splitlines() if ln.startswith("|")) - 2)}
                     for h, b in secs.items()},
        "scene_ids_cited": len(cited_scenes & scenes),
        "scene_ids_cited_not_in_corpus": sorted(cited_scenes - scenes)[:20],
        "scene_coverage_pct": round(100 * len(cited_scenes & scenes) / len(scenes), 1),
        "chapters_cited": len(cited_ch & set(chapters_text)),
        "bracket_citation_parts": len(parts),
        "bracket_citation_parts_invalid": len(bad_parts),
        "quoted_spans": len(spans),
        "quoted_spans_verbatim": span_ok,
        "registry_entities_named": len(ents),
        "_entities": sorted(ents),
    }


def audit_verdicts(text: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'^- "(.+?)" — `(SUPPORTED|NOT FOUND IN SUMMARIES)', text, re.M):
        out[m.group(1)] = "SUPPORTED" if m.group(2) == "SUPPORTED" else "NOT FOUND"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--chunked", type=Path, required=True)
    a = ap.parse_args()
    chapters = cs.load_chapters(a.campaign / "docs" / "summaries", 2, 70)
    chapters_text = {c.number: c.text for c in chapters}
    hay = "\n".join(chapters_text.values())
    scenes = {s for c in chapters for s in cs.SCENE_RE.findall(c.text)}
    reg = yaml.safe_load((a.campaign / "docs" / "entity_registry.yaml").read_text(encoding="utf-8"))
    registry = [(e["name"], [e["name"]] + list(e.get("aliases") or [])) for e in reg["entities"] if len(e["name"]) > 2]
    out = {"corpus": {"chapters": len(chapters), "scenes": len(scenes), "registry_entities": len(registry)}}
    for doc in ("world_state", "campaign_state"):
        base = (a.baseline / f"{doc}.draft.md").read_text(encoding="utf-8")
        chk = (a.chunked / f"{doc}.chunked.md").read_text(encoding="utf-8")
        mb = doc_metrics(base, scenes, hay, chapters_text, registry)
        mc = doc_metrics(chk, scenes, hay, chapters_text, registry)
        eb, ec = set(mb.pop("_entities")), set(mc.pop("_entities"))
        out[doc] = {"baseline": mb, "chunked": mc,
                    "entities_only_in_baseline": sorted(eb - ec), "entities_only_in_chunked_count": len(ec - eb),
                    "entities_only_in_chunked_sample": sorted(ec - eb)[:60]}
        if doc == "campaign_state":
            vb, vc = audit_verdicts(base), audit_verdicts(chk)
            common = set(vb) & set(vc)
            out["audit"] = {
                "baseline": {k: sum(1 for v in vb.values() if v == k) for k in ("SUPPORTED", "NOT FOUND")},
                "chunked": {k: sum(1 for v in vc.values() if v == k) for k in ("SUPPORTED", "NOT FOUND")},
                "matched_items": len(common),
                "agree": sum(1 for k in common if vb[k] == vc[k]),
                "baseline_supported_chunked_not": sorted(k for k in common if vb[k] == "SUPPORTED" and vc[k] != "SUPPORTED"),
                "chunked_supported_baseline_not": sorted(k for k in common if vc[k] == "SUPPORTED" and vb[k] != "SUPPORTED"),
            }
    tl = a.chunked / cs.TIMELINE_FILE
    if tl.is_file():
        tm = doc_metrics(tl.read_text(encoding="utf-8"), scenes, hay, chapters_text, registry)
        tm.pop("_entities")
        tm.pop("sections")
        both = set(SCENE_ID_RE.findall(tl.read_text(encoding="utf-8") + (a.chunked / "world_state.chunked.md").read_text(encoding="utf-8")))
        out["timeline_file"] = {**tm, "scene_coverage_with_world_state_pct": round(100 * len(both & scenes) / len(scenes), 1)}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
