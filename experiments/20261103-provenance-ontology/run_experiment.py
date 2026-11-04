"""Reproducible, bounded real-record experiment; no model or network calls."""
import argparse
import difflib
import json
from pathlib import Path
import time

from relationship_index import Index, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(args.workspace.resolve()):
        parser.error("output must be outside campaign workspace")
    args.out.mkdir(parents=True, exist_ok=False)
    bundles = ["notes/grounding_delta/ch059", "notes/grounding_delta/ch060"]
    start = time.perf_counter()
    graph = Index(args.out / "relationships.sqlite3", args.workspace)
    registry = graph.import_registry(args.campaign)
    results = [graph.import_bundle(args.campaign, bundle) for bundle in bundles]
    stats = graph.finish()
    build_seconds = time.perf_counter() - start
    repeated = Index(args.out / "rebuild.sqlite3", args.workspace)
    repeated.import_registry(args.campaign)
    for bundle in reversed(bundles):
        repeated.import_bundle(args.campaign, bundle)
    repeat_stats = repeated.finish()
    cases = []
    all_names = {"world_state", "campaign_state", "party", "planning"}

    def check(name, condition, actual):
        cases.append({"name": name, "passed": bool(condition), "observed": actual})

    def approvals(path, bundle):
        impact = graph.impact(args.campaign, path)
        return {n["properties"]["document"] for n in impact["affected"]
                if n["kind"] == "approval_binding" and n["properties"]["bundle"] == bundle}

    plans = [json.loads(graph.read(args.campaign, f"{b}/application_plan.json")) for b in bundles]
    source59, source60 = (p["source"]["path"] for p in plans)
    check("all eight historical approval/application bindings validate",
          all(m["binding_valid"] for b in results for m in b["members"]),
          sum(m["binding_valid"] for b in results for m in b["members"]))
    check("current summary change reaches all four Chapter 60 approvals",
          approvals(source60, bundles[1]) == all_names, sorted(approvals(source60, bundles[1])))
    check("older summary change propagates through retained origins into Chapter 60",
          approvals(source59, bundles[1]) == all_names, sorted(approvals(source59, bundles[1])))
    candidate_path = f"{bundles[1]}/drafts/party.md"
    check("party candidate change stays within party approval",
          approvals(candidate_path, bundles[1]) == {"party"}, sorted(approvals(candidate_path, bundles[1])))
    check("saved-decision change reaches all four Chapter 60 approvals",
          approvals(f"{bundles[1]}/decisions.json", bundles[1]) == all_names,
          sorted(approvals(f"{bundles[1]}/decisions.json", bundles[1])))
    check("unknown path reports missing coverage",
          graph.impact(args.campaign, "not-indexed.md")["status"] == "not_covered", "not_covered")
    alias = graph.resolve(args.campaign, "Bimble")
    check("approved short name resolves exactly", alias["status"] == "resolved",
          [n["properties"]["name"] for n in alias["entities"]])
    check("similar spelling does not acquire identity",
          graph.resolve(args.campaign, "Bimbl")["status"] == "not_found", "not_found")
    registry_path = graph.manifest.campaigns[args.campaign].identity.registry
    check("registry does not invent unrecorded grounding dependency",
          not approvals(registry_path, bundles[1]),
          {"approval_links": sorted(approvals(registry_path, bundles[1])),
           "answer": "unanswerable: no registry digest dependency in these bundle records"})
    check("rebuild independent of bundle import order", stats["graph_sha256"] == repeat_stats["graph_sha256"],
          {"first": stats["graph_sha256"], "reversed_import": repeat_stats["graph_sha256"]})
    mismatches = []
    for key, sha in stats["files_read"].items():
        root = args.workspace / graph.manifest.campaigns[key.split('/')[0]].root
        path = key.split('/', 1)[1]
        if digest((root / path).read_bytes()) != sha:
            mismatches.append(key)
    check("all read campaign files unchanged after experiment", not mismatches, mismatches)
    examples = []
    for source, target_bundle in [(source59, bundles[1]), (candidate_path, bundles[1])]:
        targets = graph.impact(args.campaign, source)["affected"]
        target = next(n for n in targets if n["kind"] == "approval_binding" and
                      n["properties"]["bundle"] == target_bundle and n["properties"]["document"] == "party")
        chain = []
        for hop in target["trace"]:
            record = graph.get(hop["evidence"]["record"])
            a, b = graph.get(hop["src"]), graph.get(hop["dst"])
            chain.append({"from": a["path"] or a["kind"] + ":" + a["properties"].get("document", ""),
                          "to": b["path"] or b["kind"] + ":" + b["properties"].get("document", ""),
                          "relationship": hop["predicate"], "evidence_path": record["path"],
                          "evidence_sha256": record["sha256"], "json_pointer": hop["evidence"]["field"]})
        examples.append({"question": f"What depends on {source}?", "example_trace": chain})
    drift = []
    for plan in plans:
        source = plan["source"]
        original = graph.read(args.campaign, source["snapshot"])
        current = graph.read(args.campaign, source["path"])
        changes = [(tag, j-i, y-x) for tag, i, j, x, y in
                   difflib.SequenceMatcher(None, original.splitlines(), current.splitlines(), autojunk=False).get_opcodes()
                   if tag != "equal"]
        drift.append({"path": source["path"], "approved_source_sha256": source["sha256"],
                      "current_source_sha256": digest(current), "bytes_changed": original != current,
                      "line_change_groups": changes,
                      "interpretation": "byte drift only; no semantic judgment or automatic invalidation write"})
    # A literal search sees direct metadata references, but has no dependency join.
    literal_matches = [key for key in stats["files_read"] if key.endswith(".json") and
                       source59.encode() in graph.read(*key.split('/', 1))]
    result = {"experiment": "declared-dependency graph, not NVIDIA runtime benchmark",
              "source_workspace": str(args.workspace.resolve()), "campaign": args.campaign,
              "scope": bundles, "registry": registry, "bundle_status": results,
              "measurements": {"build_seconds": build_seconds,
                               "sqlite_bytes": (args.out / "relationships.sqlite3").stat().st_size,
                               "nodes": stats["nodes"], "edges": stats["edges"],
                               "files_read": len(stats["files_read"]),
                               "graph_sha256": stats["graph_sha256"]},
              "classification_manifest_sha256": stats["classification_manifest_sha256"],
              "cases": cases, "passed": all(c["passed"] for c in cases),
              "source_drift": drift,
              "literal_baseline": {"query": source59, "direct_json_matches": literal_matches,
                                   "limitation": "literal matches do not traverse later baseline dependencies"},
              "limitations": ["Only the two explicitly selected legacy grounding bundles and one registry are covered.",
                              "Impact means requires reconsideration; it does not prove a semantic contradiction.",
                              "No story relation extraction, character audience inference, or automated canon changes.",
                              "Registry dependencies and generation/check tool-version bindings are absent from these records.",
                              "Legacy record checks verify internal bindings, not signed authorship, native authority or semantic correctness.",
                              "Auto Ontology was not installed or benchmarked; this tests whether a semantic projection is useful first."]}
    for filename, value in [("report.json", result), ("examples.json", examples),
                            ("input_hashes.json", stats["files_read"])]:
        (args.out / filename).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    repeated.db.close()
    (args.out / "rebuild.sqlite3").unlink()
    print(json.dumps({"passed": result["passed"], "cases": len(cases), **result["measurements"],
                      "bundle_status": results}, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
