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
    # The graph-less check shares one custody generation, so it stales both: the defect being fixed.
    assert not world.legacy(world.A)


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
