"""Mechanical checks on one document: size, scene coverage, entities, quotes, citations."""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chunked_state as cs  # noqa: E402
from compare import doc_metrics  # noqa: E402

camp, doc = Path(sys.argv[1]), Path(sys.argv[2])
chapters = cs.load_chapters(camp / "docs" / "summaries", 2, 70)
ct = {c.number: c.text for c in chapters}
scenes = {s for c in chapters for s in cs.SCENE_RE.findall(c.text)}
reg = yaml.safe_load((camp / "docs" / "entity_registry.yaml").read_text(encoding="utf-8"))
registry = [(e["name"], [e["name"]] + list(e.get("aliases") or [])) for e in reg["entities"] if len(e["name"]) > 2]
m = doc_metrics(doc.read_text(encoding="utf-8"), scenes, "\n".join(ct.values()), ct, registry)
m.pop("_entities")
m["sections"] = {h: v["chars"] for h, v in m["sections"].items()}
print(json.dumps(m, indent=1))
