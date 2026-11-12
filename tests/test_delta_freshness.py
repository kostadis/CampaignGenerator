"""T044: sign-off freshness is scoped to each item's own dependencies (spec 039 SC-005, N3, FR-014).

Two drafts share one real review (so one custody generation). Changing B's evidence stales B and
not A; changing the shared source stales both; changing a draft needs a new exact-draft sign-off.
The legacy (graph-less) check is shown to stale both on B's evidence change: that is the defect
the dependency graph fixes.
"""

from __future__ import annotations

import pytest

from _delta_npc_support import copy_fixture, census_for, install_fake, make_plan, sign_drafts
from pipelines.summary_native import npc_publish
from pipelines.summary_native.delta import npc_update
from pipelines.summary_native.freshness import DepNode, DependencyGraph


@pytest.fixture
def world(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    out = npc_update.draft(root, plan)
    assert out.exit_code == 0
    rd = out.range_dir
    members = {"npc_brannoc_ironvein": "Brannoc Ironvein", "npc_tobin_fenwick": "Tobin Fenwick"}
    signed = sign_drafts(root, rd, members, capsys)
    graph = npc_update.load_graph(root, plan.plan_id)

    class W:
        pass

    w = W()
    w.root, w.plan, w.rd, w.signed, w.graph = root, plan, rd, signed, graph
    A, B = "npc_brannoc_ironvein", "npc_tobin_fenwick"
    w.A, w.B = A, B

    def current(item):
        draft = rd / "draft" / f"{item}.md"
        return npc_publish._current_draft_signoff(
            root, draft, npc_publish.sha256_text(draft.read_bytes()),
            dependency_graph=graph, graph_item=item,
            current_digests=npc_update.current_digests(root, plan.plan_id, graph))

    def legacy(item):
        draft = rd / "draft" / f"{item}.md"
        return npc_publish._current_draft_signoff(root, draft, npc_publish.sha256_text(draft.read_bytes()))

    w.current, w.legacy = current, legacy
    return w


def test_both_current_before_any_change(world):
    assert world.current(world.A) and world.current(world.B)
    assert world.legacy(world.A) and world.legacy(world.B)


def test_changing_bs_evidence_stales_b_and_not_a(world):
    pack = world.rd / "evidence" / f"{world.B}.md"
    pack.write_text(pack.read_text(encoding="utf-8") + "\nAn added line.\n", encoding="utf-8")
    assert not world.current(world.B)
    assert world.current(world.A)  # the unrelated review-group member is not staled
    # Spec 042: the graph-less check is per-item too (it used to share one custody generation and
    # stale both -- the #633 defect), so B's evidence no longer stales A here either.
    assert world.legacy(world.A) and not world.legacy(world.B)


def test_changing_the_shared_source_stales_both(world):
    src = world.root / "docs" / "summaries" / "003-the-new-fire.md"
    src.write_text(src.read_text(encoding="utf-8") + "\nA later correction.\n", encoding="utf-8")
    assert not world.current(world.A)
    assert not world.current(world.B)


def test_changing_a_draft_requires_a_new_exact_draft_signoff(world):
    draft = world.rd / "draft" / f"{world.A}.md"
    draft.write_text(draft.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert not world.current(world.A)  # the recorded sign-off binds the old draft bytes
    assert world.current(world.B)


def test_item_unknown_to_the_graph_is_not_current(world):
    graph = DependencyGraph()
    draft = world.rd / "draft" / f"{world.A}.md"
    assert not npc_publish._current_draft_signoff(
        world.root, draft, npc_publish.sha256_text(draft.read_bytes()),
        dependency_graph=graph, graph_item=world.A, current_digests={})


def test_recorded_dependencies_are_per_item(world):
    deps_a = {n.key for n in world.graph.dependencies(world.A)}
    deps_b = {n.key for n in world.graph.dependencies(world.B)}
    rel = lambda stem: (world.rd / "evidence" / f"{stem}.md").relative_to(world.root).as_posix()  # noqa: E731
    assert rel(world.A) in deps_a and rel(world.B) not in deps_a
    assert rel(world.B) in deps_b and rel(world.A) not in deps_b
    shared = DepNode("shared_source", "docs/summaries/003-the-new-fire.md")
    assert world.graph.consumers(shared) == {world.A, world.B}


def test_graph_cannot_narrow_below_item_dependencies(world):
    """FR-011 (spec 042): a graph may add dependencies, never remove an item's own."""
    from pipelines.summary_native import review as _r  # noqa: F401
    from pipelines.summary_native.review import custody
    from pipelines.summary_native.review.store import read_snapshot
    from pipelines.summary_native.authority import ReviewDecisionRecord, load_ledger

    root = world.root
    ledger = load_ledger(root, required=False)
    rec = next(r for r in ledger.records if isinstance(r, ReviewDecisionRecord)
               and r.disposition == "document_signoff")
    _m, cust, items = read_snapshot(root, rec.review_id)
    draft_rel = (world.rd / "draft" / f"{world.A}.md").relative_to(root).as_posix()
    item = next(i for i in items if any(b.path == draft_rel for b in i.input_bindings)
                and i.proposed_action.action == "signoff_npc_draft")
    dep = custody.dependency_sets("npc_verification", cust, items, [item.item_id], custody.disk_probe(root))[item.item_id]
    by_id = {s.source_id: s.path for s in cust.sources}
    summaries = [by_id[s] for s in dep.source_ids if by_id[s].startswith("docs/summaries/")]
    assert summaries, "fixture must have a summary dependency"
    target = root / summaries[0]
    # a graph that omits every summary: only the evidence/draft nodes
    narrow = DependencyGraph()
    narrow.add(world.A, DepNode("evidence", "unrelated-key"), "x")
    digests = {DepNode("evidence", "unrelated-key"): "x"}
    draft = world.rd / "draft" / f"{world.A}.md"
    sha = npc_publish.sha256_text(draft.read_bytes())

    def cur(graph, d):
        return npc_publish._current_draft_signoff(root, draft, sha, dependency_graph=graph,
                                                  graph_item=world.A, current_digests=d)
    assert cur(narrow, digests)
    target.write_text(target.read_text(encoding="utf-8") + "\nchanged.\n", encoding="utf-8")
    assert not cur(narrow, digests)
    target.write_text(target.read_text(encoding="utf-8").replace("\nchanged.\n", ""), encoding="utf-8")
    assert cur(narrow, digests)
    # a graph naming an extra custody file: a change to it also holds
    other = (world.rd / "evidence" / f"{world.B}.md").relative_to(root).as_posix()
    assert other in by_id.values() and other not in {by_id[s] for s in dep.source_ids}
    wide = DependencyGraph()
    wide.add(world.A, DepNode("shared_source", other), "x")
    assert cur(wide, {DepNode("shared_source", other): "x"})
    o = root / other
    o.write_text(o.read_text(encoding="utf-8") + "\nchanged.\n", encoding="utf-8")
    assert not cur(wide, {DepNode("shared_source", other): "x"})
