"""Counterexamples for stale inputs, identity, and evidence scope. No live APIs."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from relationship_index import Index, digest

NAMES = ("world_state", "campaign_state", "party", "planning")
BUNDLE = "notes/grounding_delta/ch001"


def put(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    value = data if isinstance(data, bytes) else (json.dumps(data, sort_keys=True) + "\n").encode()
    target.write_bytes(value)
    return digest(value)


@pytest.fixture
def fixture(tmp_path):
    workspace = tmp_path / "workspace"
    campaign = workspace / "game"
    put(workspace, "provenance.yaml", {"version": 1, "campaigns": {
        "game": {"root": "game", "tiers": {"authoritative": ["summaries/*.md", "docs/entity_registry.yaml"],
                    "working_reference": ["docs/*.md"], "staging": ["notes/**"], "search_accelerator": []},
                 "identity": {"registry": "docs/entity_registry.yaml"}},
        "other": {"root": "other", "tiers": {"authoritative": [], "search_accelerator": [],
                    "working_reference": [], "staging": []}, "identity": {"registry": "docs/entity_registry.yaml"}}
    }})
    for root in (campaign, workspace / "other"):
        put(root, "docs/entity_registry.yaml", {"version": 1, "entities": [
            {"name": "Alpha", "type": "npc", "aliases": ["First"]},
            {"name": "Alphabeta", "type": "npc", "aliases": []}],
            "distinct": [["Alpha", "Alphabeta"]], "rejected_aliases": []})
    sha = put(campaign, "summaries/one.md", b"Reviewed source\n")
    put(campaign, f"{BUNDLE}/inputs/source.md", b"Reviewed source\n")
    source = {"path": "summaries/one.md", "snapshot": f"{BUNDLE}/inputs/source.md", "sha256": sha}
    members = []
    mapping = {}
    candidates = {}
    applied = []
    hashes = {}
    for name in NAMES:
        old = f"baseline {name}\n".encode()
        new = f"candidate {name}\n".encode()
        before = put(campaign, f"{BUNDLE}/baseline/{name}.md", old)
        put(campaign, f"old/{name}.md", old)
        after = put(campaign, f"{BUNDLE}/drafts/{name}.md", new)
        put(campaign, f"docs/{name}.md", new)
        draft = f"{BUNDLE}/drafts/{name}.md"
        member = {"document": name, "live_path": f"docs/{name}.md", "approved_candidate_path": draft,
                  "candidate_sha256": after, "backup": f"{BUNDLE}/baseline/{name}.md",
                  "baseline_sha256": before, "retained_origin": f"old/{name}.md", "retained_origin_sha256": before}
        members.append(member)
        mapping[name] = {"draft_path": draft, "draft_sha256": after, "baseline_sha256": before}
        candidates[name] = {"path": draft, "sha256": after}
        hashes[name] = after
        applied.append({"document": name, "live_path": member["live_path"], "approved_origin": draft,
                        "approved_after_sha256": after, "before_sha256": before})
    review = "test-review"
    plan = {"review_id": review, "source": source, "members": members, "extra_inputs": {}}
    choices = {"reviewId": review, "savedAt": "2026-11-03 01:00 UTC", "decisions": {n: "approve" for n in NAMES},
               "discuss": [], "unmarked": []}
    items = {"reviewId": review, "items": [{"id": n} for n in NAMES]}
    receipt = {"review_id": review, "members": applied}
    for path, obj, field in [("application_plan.json", plan, "application_plan_sha256"),
                             ("decisions.json", choices, "decision_sha256"),
                             ("review_items.json", items, "review_items_sha256"),
                             ("review_mapping.json", mapping, "mapping_sha256")]:
        receipt[field] = put(campaign, f"{BUNDLE}/{path}", obj)
    put(campaign, f"{BUNDLE}/application_manifest.json", receipt)
    put(campaign, f"{BUNDLE}/manifest.json", {"review_id": review, "source": source, "candidates": candidates})
    for path in ("runs/consistency.record.json", "runs/final_consistency.record.json"):
        put(campaign, f"{BUNDLE}/{path}", {"overall": "pass", "candidate_sha256": hashes})
    put(campaign, f"{BUNDLE}/final_consistency.json", {"overall": "pass"})
    return workspace, campaign


def build(tmp_path, workspace, label="index"):
    graph = Index(tmp_path / f"{label}.sqlite3", workspace)
    graph.import_registry("game")
    result = graph.import_bundle("game", BUNDLE)
    graph.finish()
    return graph, result


def target_documents(result, kind):
    return {n["properties"]["document"] for n in result["affected"] if n["kind"] == kind}


def test_source_impacts_all_but_candidate_is_local(tmp_path, fixture):
    graph, result = build(tmp_path, fixture[0])
    assert all(m["reuse_status"] == "current" for m in result["members"])
    assert target_documents(graph.impact("game", "summaries/one.md"), "approval_binding") == set(NAMES)
    assert target_documents(graph.impact("game", f"{BUNDLE}/drafts/party.md"), "approval_binding") == {"party"}


def test_changed_source_keeps_historical_approval_but_blocks_fresh_reuse(tmp_path, fixture):
    put(fixture[1], "summaries/one.md", b"Corrected source\n")
    _, result = build(tmp_path, fixture[0])
    assert all(m["binding_valid"] and m["reuse_status"] == "stale_source" for m in result["members"])


@pytest.mark.parametrize("target", ["decisions.json", "review_items.json", "review_mapping.json", "application_plan.json"])
def test_changed_review_metadata_cannot_reuse_approval(tmp_path, fixture, target):
    path = fixture[1] / BUNDLE / target
    path.write_bytes(path.read_bytes() + b"\n")
    _, result = build(tmp_path, fixture[0])
    assert all(not m["binding_valid"] for m in result["members"])
    assert all(any("receipt binding mismatch" in s for s in m["errors"]) for m in result["members"])


def test_candidate_tampering_affects_only_its_binding(tmp_path, fixture):
    put(fixture[1], f"{BUNDLE}/drafts/party.md", b"Tampered\n")
    _, result = build(tmp_path, fixture[0])
    assert {m["document"] for m in result["members"] if not m["binding_valid"]} == {"party"}


def test_missing_snapshot_is_invalid_not_empty_success(tmp_path, fixture):
    (fixture[1] / BUNDLE / "inputs/source.md").unlink()
    _, result = build(tmp_path, fixture[0])
    assert all(not m["binding_valid"] for m in result["members"])


def test_overwritten_live_file_does_not_revoke_old_approval(tmp_path, fixture):
    put(fixture[1], "docs/party.md", b"Later approved version\n")
    _, result = build(tmp_path, fixture[0])
    party = next(m for m in result["members"] if m["document"] == "party")
    assert party["binding_valid"] and not party["live_matches_this_version"]


def test_unknown_dependency_is_coverage_gap(tmp_path, fixture):
    graph, _ = build(tmp_path, fixture[0])
    assert graph.impact("game", "undeclared.md")["status"] == "not_covered"
    assert not target_documents(graph.impact("game", "docs/entity_registry.yaml"), "approval_binding")


def test_identity_exact_guards_and_campaign_separation(tmp_path, fixture):
    graph, _ = build(tmp_path, fixture[0])
    graph.import_registry("other")
    assert graph.resolve("game", "FIRST")["entities"][0]["properties"]["name"] == "Alpha"
    assert graph.resolve("game", "Alph")["status"] == "not_found"
    assert graph.resolve("unknown", "First")["status"] == "no_store"
    assert graph.resolve("game", "First")["entities"][0]["id"] != graph.resolve("other", "First")["entities"][0]["id"]
    assert graph.resolve("game", "Alpha")["entities"][0]["id"] != graph.resolve("game", "Alphabeta")["entities"][0]["id"]
    assert graph.db.execute("SELECT count(*) FROM nodes WHERE kind='identity_guard'").fetchone()[0] == 2
    left = graph.resolve("game", "Alpha")["entities"][0]["id"]
    right = graph.resolve("other", "Alpha")["entities"][0]["id"]
    record = graph.db.execute("SELECT id FROM nodes WHERE campaign='game' AND kind='artifact' AND path='docs/entity_registry.yaml'").fetchone()[0]
    with pytest.raises(ValueError, match="cross-campaign"):
        graph.edge(left, right, "same_as", record, "entities/0")


def test_rebuild_and_traces_are_deterministic(tmp_path, fixture):
    first, _ = build(tmp_path, fixture[0], "one")
    second, _ = build(tmp_path, fixture[0], "two")
    assert first.graph_digest() == second.graph_digest()
    for node in first.impact("game", "summaries/one.md")["affected"]:
        assert node["trace"]
        for hop in node["trace"]:
            assert first.get(hop["evidence"]["record"])["kind"] == "artifact"
            assert hop["evidence"]["field"]


def test_cross_campaign_path_and_symlink_escape_refused(tmp_path, fixture):
    graph, _ = build(tmp_path, fixture[0])
    for path in ("../other/docs/entity_registry.yaml", "/etc/passwd"):
        with pytest.raises(ValueError):
            graph.artifact("game", path)
    (fixture[1] / "escaped").symlink_to(fixture[0] / "other", target_is_directory=True)
    with pytest.raises(ValueError):
        graph.artifact("game", "escaped/docs/entity_registry.yaml")


def test_source_reads_and_query_are_read_only(tmp_path, fixture):
    before = {str(p): digest(p.read_bytes()) for p in fixture[0].rglob("*") if p.is_file()}
    graph, _ = build(tmp_path, fixture[0])
    graph.db.close()
    readonly = Index(tmp_path / "index.sqlite3")
    with pytest.raises(Exception, match="readonly"):
        readonly.db.execute("DELETE FROM nodes")
    after = {str(p): digest(p.read_bytes()) for p in fixture[0].rglob("*") if p.is_file()}
    assert before == after


def test_output_inside_source_workspace_refused(tmp_path, fixture):
    with pytest.raises(ValueError, match="outside"):
        Index(fixture[0] / "output.sqlite3", fixture[0])


def test_concurrent_input_change_blocks_commit(tmp_path, fixture):
    graph = Index(tmp_path / "racing.sqlite3", fixture[0])
    graph.import_bundle("game", BUNDLE)
    put(fixture[1], "summaries/one.md", b"Changed during build\n")
    with pytest.raises(ValueError, match="changed before index commit"):
        graph.finish()


def test_empty_registry_is_a_store_with_no_match(tmp_path, fixture):
    put(fixture[1], "docs/entity_registry.yaml", {"version": 1, "entities": []})
    graph, _ = build(tmp_path, fixture[0])
    assert graph.resolve("game", "First")["status"] == "not_found"
