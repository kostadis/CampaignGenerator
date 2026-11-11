"""Spec 040 US2 (T026): negative and boundary tests for ``delta rebind`` and the NPC carry rule.

The same real build as ``tests/test_rebase_e2e.py`` (a managed generation through chapter 5, four corrected
summaries, a pending chapter-6 plan with two NPC dossiers published through the run), plus two EXTRA approved
chapter-6 edits made before the rebase: one aimed at the line the rebase REPAIRS and one at the line it HOLDS.
Nothing in claims, review bindings or promotion is mocked.  Tests are ordered; the last ones mutate the plan.
"""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native.delta import baseline as bl, grounding_edits, rebind, review_binding as rb
from pipelines.summary_native.delta.errors import EXIT_STALE, DeltaRefusal
from pipelines.summary_native.delta.plan import ModelChoice, PlanModels, load_plan, plans_dir, revise
from pipelines.summary_native.delta.run import load_run, run_path
from tests import _rebase_fixture as rf
from tests.test_delta_grounding_e2e import run

REPAIRED_LINE = "The company holds four prisoners. [ch 005 / 005.01]"
HELD_LINE = "The far marker beyond the eastern marker still stands. [ch 005 / 005.01]"


class World:
    def __init__(self, fx, cap, rebased, pre) -> None:
        self.fx, self.cap, self.rebased, self.pre = fx, cap, rebased, pre
        self._rebound = None

    def call(self, *argv, expect=0):
        with self.cap.active():
            return run(self.cap, self.fx.root, *argv, expect=expect)

    @property
    def rebound(self) -> dict:
        if self._rebound is None:
            self._rebound = self.call("rebind", "--plan", self.fx.pending_plan_id, "--baseline",
                                      self.rebased.new_generation)["data"]
        return self._rebound


def _target(docs, text):
    raw = docs["world_state"].splitlines(keepends=True)
    n = next(i for i, ln in enumerate(raw, 1) if ln.decode("utf-8").rstrip("\n") == text)
    return grounding_edits.line_target_id("world_state", n, raw[n - 1])


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    cap = rf.Capture()
    with pytest.MonkeyPatch.context() as mp, cap.active():
        fx = rf.build(tmp_path_factory.mktemp("rebase-rebind"), cap, mp, npc=True)
        root, pending = fx.root, fx.pending_plan_id
        plan = load_plan(plans_dir(root), pending)
        docs = bl.baseline_documents(bl.bind(root), root)
        extra = [grounding_edits.make_proposal(
            docs, target_id=_target(docs, text), after_text=after, category="new_information",
            rationale="chapter 6 restates it", support="x", dependent_checks=["citation"])
            for text, after in ((REPAIRED_LINE, REPAIRED_LINE + " Counted again in ch 6. [ch 006 / 006.01]"),
                                (HELD_LINE, HELD_LINE + " Visited in ch 6. [ch 006 / 006.01]"))]
        grounding_edits.append_proposals(root, pending, plan.grounding_baseline_ref, docs, extra)
        for p in extra:
            grounding_edits.decide(root, pending, p.proposal_id, "approve", "ruled by the GM", reviewer="gm")
        # rebinding to the ACTIVE generation, which is the plan's own baseline and so not its child
        not_child = run(cap, root, "rebind", "--plan", pending, "--baseline", fx.generation_id, expect=1)
        a_rebase_plan = None
        rebased = rf.do_rebase(fx, cap)
        a_rebase_plan = run(cap, root, "rebind", "--plan", rebased.plan_id, "--baseline", rebased.new_generation, expect=2)
        yield World(fx, cap, rebased, {"not_child": not_child, "extra": extra, "rebase_plan": a_rebase_plan})


# --------------------------------------------------------------------------- refusals

def test_rebind_to_the_active_generation_that_is_not_a_child_is_refused(world):
    out = world.pre["not_child"]
    assert out["code"] == "REBIND_NOT_CHILD" and "not a child of the plan's baseline" in out["message"]


def test_rebind_to_a_generation_that_is_not_active_is_refused_and_writes_nothing(world):
    fx = world.fx
    before = rf.sha_tree(fx.root, "docs/summaries/delta/plans", f"docs/summaries/delta/grounding/{fx.pending_plan_id}")
    out = world.call("rebind", "--plan", fx.pending_plan_id, "--baseline", fx.generation_id, expect=1)
    assert out["code"] == "REBIND_NOT_CHILD" and "not the active generation" in out["message"]
    out = world.call("rebind", "--plan", fx.pending_plan_id, "--baseline", "generation-does-not-exist", expect=1)
    assert out["code"] == "REBIND_NOT_CHILD"
    assert rf.sha_tree(fx.root, "docs/summaries/delta/plans", f"docs/summaries/delta/grounding/{fx.pending_plan_id}") == before
    assert load_plan(plans_dir(fx.root), fx.pending_plan_id).revision == 1


def test_a_rebase_plan_is_not_rebound_and_a_baseline_is_required(world):
    assert world.pre["rebase_plan"]["ok"] is False and "rebase plan" in world.pre["rebase_plan"]["message"]
    world.call("rebind", "--plan", world.fx.pending_plan_id, expect=2)  # no --baseline: no default


# --------------------------------------------------------------------------- the rebind itself

def test_an_overlapping_chapter_6_edit_becomes_stale_and_an_independent_one_is_reapplied(world):
    data = world.rebound
    repaired, held = world.pre["extra"]
    assert set(data["stale_edits"]) == {repaired.proposal_id, held.proposal_id}
    assert "before bytes are not in the new baseline" in data["stale_edit_reasons"][repaired.proposal_id]
    assert "held or repaired" in data["stale_edit_reasons"][held.proposal_id]
    assert len(data["reapplied_edits"]) == 1  # the anchor edit that was already approved
    root, pending = world.fx.root, world.fx.pending_plan_id
    proposals = grounding_edits.load_proposals(root, pending)
    assert proposals.baseline_ref == data["new_baseline_ref"]
    assert [p.proposal_id for p in proposals.proposals] == data["reapplied_edits"]
    decisions = grounding_edits.current_decisions(root, pending, proposals)
    assert {d.decision for d in decisions.values()} == {"approve"}  # the earlier approval travels with it
    assert decisions[data["reapplied_edits"][0]].reviewer == "fixture-gm"
    docs = bl.baseline_documents(bl.bind(root), root)
    rebuilt = grounding_edits.reconstruct_for_plan(root, pending, docs)["world_state"].decode("utf-8")
    assert "Counted again in ch 6" not in rebuilt and "Visited in ch 6" not in rebuilt  # a stale edit is never applied


def test_the_rebind_records_what_it_did_and_deletes_nothing(world):
    data, root, pending = world.rebound, world.fx.root, world.fx.pending_plan_id
    record = json.loads((root / "docs/summaries/delta/plans" / f"rebind-{pending}-r2.json").read_text())
    assert {k: record[k] for k in ("plan_id", "from_revision", "to_revision", "new_baseline_ref")} == {
        k: data[k] for k in ("plan_id", "from_revision", "to_revision", "new_baseline_ref")}
    assert record["old_baseline_ref"].startswith(world.fx.generation_id)
    names = [p.rsplit("/", 1)[-1] for p in record["invalidated"]]
    assert {"world_state.md", "lineage.json", "preview.json"} <= set(names)  # no grounding binding existed yet
    assert any(n.startswith("check-r") for n in names)
    assert all((root / p).exists() for p in record["invalidated"])  # recorded, never deleted
    # a run of the old revision follows the plan, because the run refuses a plan that changed under it
    assert record["run_state_rebound_from"] == f"{pending}-r1"
    assert load_run(run_path(root, pending)).plan_ref == f"{pending}-r2"


def test_an_identical_rebind_is_a_no_op(world):
    first = world.rebound
    root, pending = world.fx.root, world.fx.pending_plan_id
    watched = ("docs/summaries/delta/plans", f"docs/summaries/delta/grounding/{pending}", f"docs/summaries/delta/{pending}")
    before = rf.sha_tree(root, *watched)
    again = world.call("rebind", "--plan", pending, "--baseline", world.rebased.new_generation)["data"]
    assert again["written"] is False and again["to_revision"] == first["to_revision"] == 2
    assert {k: v for k, v in again.items() if k not in ("written", "call_counts")} == \
        {k: v for k, v in first.items() if k not in ("written", "call_counts")}
    assert rf.sha_tree(root, *watched) == before
    assert load_plan(plans_dir(root), pending).revision == 2


# --------------------------------------------------------------------------- the NPC carry rule (T024)

def test_the_npc_binding_is_carried_only_through_the_rebind_record(world):
    world.rebound
    root, pending, slugs = world.fx.root, world.fx.pending_plan_id, world.fx.npc_slugs
    plan2 = load_plan(plans_dir(root), pending)
    binding = rb.load_binding(root, pending, "npc", "publication")
    assert binding.plan_sha256 != rb.plan_digest(plan2)  # the digest did move...
    assert rb.require_fresh(root, plan2, "npc", members=slugs, required=True) is not None  # ...and it is still fresh
    assert rb.npc_binding_carried(root, plan2, binding) is True
    # a plan-digest mismatch with NO rebind record behind it is stale: forge the old digest
    forged = binding.model_copy(update={"plan_sha256": "0" * 64})
    assert rb.npc_binding_carried(root, plan2, forged) is False
    # a rebind that moves only the grounding baseline again would still be carried
    only_baseline = revise(plan2, grounding_baseline_ref="generation-x@" + "1" * 64)
    assert rb.npc_projection_sha256(only_baseline) == rb.npc_projection_sha256(plan2)


@pytest.mark.parametrize("change", ["npc_baselines", "model", "products", "sources"])
def test_an_npc_relevant_plan_change_after_the_rebind_stales_the_binding(world, change):
    world.rebound
    root, pending, slugs = world.fx.root, world.fx.pending_plan_id, world.fx.npc_slugs
    plan2 = load_plan(plans_dir(root), pending)
    if change == "npc_baselines":
        changed = revise(plan2, npc_baselines={"corporal-tamsin": "0" * 64})
    elif change == "model":
        other = ModelChoice(backend=plan2.models.generation.backend, model="some-other-model")
        changed = revise(plan2, models=PlanModels(generation=other, consistency=plan2.models.consistency))
    elif change == "products":
        changed = revise(plan2, products=("npc",))
    else:
        src = plan2.sources[0].model_copy(update={"sha256": "2" * 64})
        changed = revise(plan2, sources=(src,))
    assert rb.npc_projection_sha256(changed) != rb.npc_projection_sha256(plan2)
    with pytest.raises(DeltaRefusal) as err:
        rb.require_fresh(root, changed, "npc", members=slugs, required=True)
    assert err.value.exit_code == EXIT_STALE and "plan changed since review" in err.value.message
