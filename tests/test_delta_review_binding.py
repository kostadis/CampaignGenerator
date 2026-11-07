"""T057: a review binding covers exact hashes; any change makes it stale; scopes never substitute (FR-017, FR-020)."""

from __future__ import annotations

import hashlib
import json

import pytest

from pipelines.summary_native.delta import grounding_publish as gp, review_binding as rb
from pipelines.summary_native.delta.cli_plan import selection_path
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, DeltaRefusal
from pipelines.summary_native.delta.lineage import (
    BaselineRef, CustodyRef, DeltaLineageRecord, LineageMember, save_lineage)
from pipelines.summary_native.delta.plan import create_plan, plan_digest, plans_dir, revise, save_plan

MODELS = {"generation": {"backend": "anthropic", "model": "m"},
          "consistency": {"backend": "dgx", "model": "q", "effort": "low"}}
SHA = "b" * 64


@pytest.fixture
def world(tmp_path):
    src = tmp_path / "docs/summaries/003-x.md"
    src.parent.mkdir(parents=True)
    src.write_text("c3")
    plan = create_plan(campaign_identity="camp", products=["grounding"], stopping_point="apply",
                       source_paths=[src], models=MODELS)
    save_plan(plan, plans_dir(tmp_path))
    base = gp.grounding_dir(tmp_path, plan.plan_id)
    (base / "candidates").mkdir(parents=True)
    (base / "candidates/world_state.md").write_text("world v2\n")
    old = tmp_path / "docs/summaries/ch001-002/party.md"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"party v1\n")
    d = hashlib.sha256(b"party v1\n").hexdigest()
    ws = hashlib.sha256(b"world v2\n").hexdigest()
    (tmp_path / "c.json").write_text(json.dumps({"candidate_sha256": {"world_state": ws}}))
    lineage = DeltaLineageRecord(plan_ref=plan.plan_id, baseline=BaselineRef(generation_id="g1", manifest_sha256=SHA), members=[
        LineageMember(name="party", mode="inherited", sha256=d, custody_ref=CustodyRef(path="docs/summaries/ch001-002/party.md", sha256=d)),
        LineageMember(name="world_state", mode="produced", sha256=ws, check_ref="c.json", check_status="passed")])
    save_lineage(lineage, base / gp.LINEAGE_FILE)
    return tmp_path, plan, base


def _bind(root, plan, scope="publication", decision="approve"):
    b = rb.make_binding(root, plan, "grounding", scope,
                        decisions=[rb.BoundDecision(id="doc", level="document", decision=decision, reviewer="GM")])
    rb.save_binding(root, b)
    return b


def test_binding_hashes_are_the_exact_current_hashes(world):
    root, plan, base = world
    b = _bind(root, plan)
    assert b.plan_sha256 == plan_digest(plan)
    assert b.rules_sha256 == rb.rules_digest(root)
    now = rb.current_hashes(root, plan, "grounding")
    assert {f: getattr(b, f) for f in rb.HASH_FIELDS} == now
    assert rb.is_stale(b, now) == []
    assert all(len(getattr(b, f)) == 64 for f in rb.HASH_FIELDS)


@pytest.mark.parametrize("which", ["candidate", "plan", "evidence", "rules"])
def test_a_change_to_any_bound_hash_makes_the_binding_stale_and_names_it(world, which):
    root, plan, base = world
    b = _bind(root, plan)
    current_plan = plan
    if which == "candidate":
        (base / "candidates/world_state.md").write_text("world v2 edited\n")
    elif which == "plan":
        current_plan = revise(plan, stopping_point="preview")
    elif which == "evidence":
        p = selection_path(root, plan.plan_id)
        p.parent.mkdir(parents=True)
        p.write_text("{}")
    else:
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs/entity_registry.yaml").write_text("entities: []\n")
    reasons = rb.is_stale(b, rb.current_hashes(root, current_plan, "grounding"))
    assert len(reasons) == 1 and reasons[0].startswith(which)


def test_fresh_binding_passes_the_gate_and_returns_it(world):
    root, plan, _ = world
    _bind(root, plan)
    assert rb.require_fresh(root, plan, "grounding").approval_scope == "publication"


def test_no_binding_leaves_the_existing_gates_alone_unless_required(world):
    root, plan, _ = world
    assert rb.require_fresh(root, plan, "grounding") is None
    with pytest.raises(DeltaRefusal) as err:
        rb.require_fresh(root, plan, "grounding", required=True)
    assert err.value.exit_code == EXIT_REFUSAL


@pytest.mark.parametrize("have", rb.APPROVAL_SCOPES)
@pytest.mark.parametrize("need", rb.APPROVAL_SCOPES)
def test_an_approval_of_one_scope_never_satisfies_another(world, have, need):
    root, plan, _ = world
    b = _bind(root, plan, scope=have)
    if have == need:
        assert rb.require_scope(b, need) is b
        assert rb.require_fresh(root, plan, "grounding", scope=need, required=True)
        return
    with pytest.raises(DeltaRefusal):
        rb.require_scope(b, need)
    # looked up under the other scope there is simply nothing
    assert rb.load_binding(root, plan.plan_id, "grounding", need) is None
    with pytest.raises(DeltaRefusal):
        rb.require_fresh(root, plan, "grounding", scope=need, required=True)


def test_a_binding_file_copied_under_another_scope_is_refused(world):
    root, plan, _ = world
    _bind(root, plan, scope="draft")
    src = rb.binding_path(root, plan.plan_id, "grounding", "draft")
    dst = rb.binding_path(root, plan.plan_id, "grounding", "publication")
    dst.write_bytes(src.read_bytes())
    with pytest.raises(DeltaRefusal):
        rb.load_binding(root, plan.plan_id, "grounding", "publication")


@pytest.mark.parametrize("decision,word", [("unset", "no saved decision"), ("discuss", "Discuss"), ("reject", "rejected")])
def test_a_non_approve_decision_blocks_with_exit_1(world, decision, word):
    root, plan, _ = world
    _bind(root, plan, decision=decision)
    with pytest.raises(DeltaRefusal) as err:
        rb.require_fresh(root, plan, "grounding")
    assert err.value.exit_code == EXIT_REFUSAL and word in err.value.message


def test_a_binding_with_no_decisions_blocks(world):
    root, plan, _ = world
    rb.save_binding(root, rb.make_binding(root, plan, "grounding", "publication"))
    with pytest.raises(DeltaRefusal):
        rb.require_fresh(root, plan, "grounding")


def test_record_decision_requires_a_value_and_a_reviewer_and_bumps_the_revision(world):
    root, plan, _ = world
    b = rb.make_binding(root, plan, "grounding", "publication")
    with pytest.raises(DeltaRefusal):
        rb.record_decision(root, b, "doc", "maybe", reviewer="GM")
    with pytest.raises(DeltaRefusal):
        rb.record_decision(root, b, "doc", "approve", reviewer=" ")
    b2 = rb.record_decision(root, b, "doc", "approve", reviewer="GM", level="document")
    assert b2.decision_revision == b.decision_revision + 1 and rb.blockers(b2) == []


def test_apply_refuses_exit_3_when_a_bound_hash_moved_after_review(world):
    """SC-005: sign-off, then change one bound input before apply."""
    root, plan, base = world
    _bind(root, plan)
    c, l, r = gp.load_inputs(root, plan.plan_id)
    sha = gp.preview(plan, c, l, r, campaign_dir=root).preview_sha256
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs/entity_registry.yaml").write_text("entities: []\n")  # a rule moved; the preview hash did not
    called = []
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, sha, campaign_dir=root, publisher=lambda *a: called.append(1) or {})
    assert err.value.exit_code == EXIT_STALE == 3 and "rules" in err.value.message and not called


def test_apply_proceeds_when_the_review_is_fresh_and_approved(world):
    root, plan, _ = world
    _bind(root, plan)
    c, l, r = gp.load_inputs(root, plan.plan_id)
    sha = gp.preview(plan, c, l, r, campaign_dir=root).preview_sha256
    assert gp.apply(plan, sha, campaign_dir=root, publisher=lambda *a: {"ok": 1}) == {"ok": 1}


def test_apply_refuses_a_discuss_decision(world):
    root, plan, _ = world
    _bind(root, plan, decision="discuss")
    c, l, r = gp.load_inputs(root, plan.plan_id)
    sha = gp.preview(plan, c, l, r, campaign_dir=root).preview_sha256
    called = []
    with pytest.raises(DeltaRefusal) as err:
        gp.apply(plan, sha, campaign_dir=root, publisher=lambda *a: called.append(1) or {})
    assert err.value.exit_code == EXIT_REFUSAL and not called
