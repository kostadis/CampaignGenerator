"""Evaluate contextual mention candidates against gold answers held outside queries."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import time

from contextual_identity import ContextIndex, sha
from fixtures import A, B, C, D, make_world, make_cases, missing_location_world, conflicting_location_world


def evaluate(world, cases):
    graph = ContextIndex(world)
    results = []
    for case in cases:
        start = time.perf_counter()
        result = graph.resolve(case["mention"])
        result["elapsed_seconds"] = time.perf_counter() - start
        result["expected_status"] = case["expected_status"]
        result["expected_candidates"] = case["expected_candidates"]
        result["passed"] = (result["status"] == case["expected_status"] and
                            result["candidate_ids"] == case["expected_candidates"])
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    world = make_world()
    cases = make_cases()
    results = evaluate(world, cases)
    variants = [
        ("missing_location", missing_location_world(), {"mention": {"id": "missing_location", "label": "bugbear", "campaign": "game", "at": 5, "scene_location": "d1-l2"}, "expected_status": "ambiguous", "expected_candidates": [A, B]}),
        ("conflicting_location", conflicting_location_world(), {"mention": {"id": "conflicting_location", "label": "bugbear", "campaign": "game", "at": 5, "scene_location": "d1-l1"}, "expected_status": "conflicting_evidence", "expected_candidates": [A]}),
    ]
    variant_results = [evaluate(w, [case])[0] for _, w, case in variants]
    # Same queries and gold, but remove every contextual identity signal.
    stripped = []
    for case in cases:
        copied = deepcopy(case)
        for key in ("scene_location", "referent_locations", "features", "referent_at"):
            copied["mention"].pop(key, None)
        stripped.append(copied)
    name_only = evaluate(world, stripped)
    # Deliberately simple composite-key baseline: snapshot at initial locations.
    # It has no mechanism for movement or two individuals sharing one scope.
    level_name_baseline = {"d1-l1": A, "d1-l2": B, "d1-l3": C, "d2-l1": D}
    baseline_cases = []
    for case in cases:
        if case["mention"]["id"] in ("moving_individual_keeps_id", "two_bugbears_on_level_two"):
            proposed = level_name_baseline.get(case["mention"].get("scene_location"))
            baseline_cases.append({"mention_id": case["mention"]["id"], "proposed": proposed,
                                   "gold_status": case["expected_status"],
                                   "gold_ids": case["expected_candidates"],
                                   "correct": case["expected_status"] == "supported_candidate" and
                                              case["expected_candidates"] == [proposed]})
    report = {
        "experiment": "contextual entity candidates; synthetic, annotated evidence",
        "world_sha256": sha(world), "same_label_instances": 4,
        "cases": len(results) + len(variant_results),
        "passed": all(r["passed"] for r in results + variant_results),
        "context_supported_unique": sum(r["status"] == "supported_candidate" for r in results),
        "name_only_supported_unique": sum(r["status"] == "supported_candidate" for r in name_only),
        "false_unique_proposals": sum(r["proposed_entity_id"] is not None and not r["passed"] for r in results + variant_results),
        "context_ablation": [{"mention_id": r["mention_id"], "status": r["status"],
                              "candidate_ids": r["candidate_ids"]} for r in name_only],
        "level_name_composite_key_baseline": baseline_cases,
        "results": results, "variant_results": variant_results,
        "limitations": [
            "This is not an NVIDIA Auto Ontology runtime benchmark.",
            "Evidence, scene scope, temporal reference and descriptive features are hand-annotated synthetic inputs.",
            "There is no automatic prose-to-context extraction, probabilistic coreference, or novel-entity creation.",
            "Matching known instances is not a proof that an unknown instance cannot exist.",
            "Supported candidates are proposals; no identity/alias becomes canon and no campaign registry is written.",
            "Production registry format still requires globally unique names/aliases; these instances are held in a separate experimental graph.",
        ]}
    for filename, value in (("world.json", world), ("cases.json", cases), ("report.json", report)):
        (args.out / filename).write_text(json.dumps(value, indent=2) + "\n")
    for case in cases:
        if case["mention"]["id"] == "moving_individual_keeps_id":
            (args.out / "example_mention.json").write_text(json.dumps(case["mention"], indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("passed", "cases", "same_label_instances", "context_supported_unique", "name_only_supported_unique", "false_unique_proposals", "level_name_composite_key_baseline")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
