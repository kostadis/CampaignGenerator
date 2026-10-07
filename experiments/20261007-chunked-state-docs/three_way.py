"""Print baseline / qwen / deepseek side by side from the two comparison.json files."""
import json
import sys

q = json.load(open(sys.argv[1]))
d = json.load(open(sys.argv[2]))
keys = ["chars", "bullets", "scene_coverage_pct", "chapters_cited", "registry_entities_named",
        "quoted_spans_verbatim", "quoted_spans", "bracket_citation_parts_invalid"]
for doc in ("world_state", "campaign_state"):
    print(f"\n{doc:<34}{'opus 1-shot':>12}{'qwen chunk':>12}{'dsk chunk':>12}")
    for k in keys:
        print(f"  {k:<32}{q[doc]['baseline'][k]!s:>12}{q[doc]['chunked'][k]!s:>12}{d[doc]['chunked'][k]!s:>12}")
    secs = list(d[doc]["chunked"]["sections"])
    for h in secs:
        b = q[doc]["baseline"]["sections"].get(h, {})
        print(f"    {h[3:][:30]:<30}{b.get('chars', '-')!s:>12}{q[doc]['chunked']['sections'][h]['chars']!s:>12}"
              f"{d[doc]['chunked']['sections'][h]['chars']!s:>12}"
              + (f"   rows {b.get('table_rows')}/{q[doc]['chunked']['sections'][h]['table_rows']}/{d[doc]['chunked']['sections'][h]['table_rows']}"
                 if d[doc]['chunked']['sections'][h]['table_rows'] else ""))
print("\ntimeline file  qwen:", {k: q['timeline_file'][k] for k in ('chars', 'bullets', 'scene_coverage_with_world_state_pct')},
      "\n               dsk: ", {k: d['timeline_file'][k] for k in ('chars', 'bullets', 'scene_coverage_with_world_state_pct')})
for name, x in (("qwen", q), ("dsk", d)):
    a = x["audit"]
    print(f"audit {name}: vs opus agree {a['agree']}/{a['matched_items']}; supported {a['chunked']['SUPPORTED']} (opus {a['baseline']['SUPPORTED']}); "
          f"opus-yes/{name}-no {len(a['baseline_supported_chunked_not'])}, {name}-yes/opus-no {len(a['chunked_supported_baseline_not'])}")
