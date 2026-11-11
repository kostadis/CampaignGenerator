"""Spec 040 US3 (T027, T028, SC-005): one stale-boundary test per input a rebase review is bound to.

One module-scoped build runs the whole real chain (prepare, repairs, hold, decide, check, stage, real claims,
signoffs, review handoff) and stops BEFORE ``grounding apply``.  Each test restores that campaign, moves ONE
bound input, and applies.  Every refusal must happen before activation: exit 3, the active generation and every
byte under ``docs/grounding`` unchanged, and a message that names the input that moved.
Claims, review bindings and promotion are never mocked.
"""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native.delta import baseline as bl, grounding_edits, grounding_publish as gp, review_binding as rb
from pipelines.summary_native.delta.rebase import bound_inputs
from pipelines.summary_native.promotion.publish import write_active_layout
from tests import _rebase_fixture as rf
from tests._rebase_apply_world import ApplyWorld, build_template
from tests.test_delta_grounding_e2e import run


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    cap = rf.Capture()
    with pytest.MonkeyPatch.context() as mp:
        yield build_template(tmp_path_factory.mktemp("rebase-stale"), cap, mp)


@pytest.fixture
def w(template: ApplyWorld) -> ApplyWorld:
    return template.reset()


def tree(w: ApplyWorld) -> dict[str, str]:
    return rf.sha_tree(w.root, "docs/grounding")


def refuse(w: ApplyWorld, needle: str, *, code: int = 3, **kw) -> str:
    """Apply, expect the refusal, and prove nothing was activated or written under ``docs/grounding``."""
    before = tree(w)
    out = w.apply(expect=code, **kw)
    assert needle in out["error"], out["error"]
    assert w.active() == w.old_generation and tree(w) == before  # exit before activation: not one byte moved
    return out["error"]


def test_a_fresh_rebase_applies(w):  # the control: the same build, nothing moved
    assert w.apply()["applied"] is True and w.active() != w.old_generation


def test_the_binding_names_every_bound_input(w):
    binding = rb.load_binding(w.root, w.plan_id, "grounding", "publication")
    names = set(binding.member_hashes["rebase"])
    assert {"rebase decisions", "impact record", "custody snapshots", "repair draft"} <= names
    assert {f"selected source ch {c:03d}" for c in (2, 3, 4, 5)} <= {n.split(" (")[0] for n in names}
    assert binding.member_hashes["rebase"] == bound_inputs(w.root, w.plan())


def test_a_selected_source_edited_again_after_approval(w):
    path = w.fx.paths[3]
    path.write_bytes(path.read_bytes() + b"\nA late edit nobody reviewed.\n")
    msg = refuse(w, "REBASE_STALE")
    assert "selected source ch 003" in msg and path.name in msg


def test_another_generation_activated_is_a_conflict(w):
    # someone else's publication won the race: the active pointer names a different generation
    older = sorted(p.name for p in (w.root / "docs/grounding/generations").iterdir() if p.name != w.old_generation)
    assert older, "the fixture has an earlier generation"
    activations = [json.loads(p.read_text()) for p in sorted((w.root / "docs/grounding/activations").glob("*.json"))]
    other = next(a for a in activations if a.get("generation_id") == older[-1])
    older = [older[-1]]
    current = w.root / "docs/grounding/current"
    current.unlink()
    current.symlink_to(f"generations/{older[0]}/live")
    write_active_layout(w.root, older[0], other["activation_id"])  # the same call a real activation makes
    moved = tree(w)
    out = w.apply(expect=3)
    assert "REBASE_STALE" in out["error"] and "active baseline" in out["error"], out["error"]
    assert tree(w) == moved and bl.bind(w.root).generation_id == older[0]  # nothing was activated over it


def test_the_impact_file_edited(w):
    path = w.root / "docs/summaries/delta/rebase" / w.rebased.rebase_id / "impact.json"
    path.write_bytes(path.read_bytes() + b"\n")
    refuse(w, "impact record")


def test_the_repair_draft_edited(w):
    files = sorted(gp.grounding_dir(w.root, w.plan_id).glob("proposals-r*.json"))
    data = json.loads(files[-1].read_text())
    data["proposals"][0]["rationale"] = data["proposals"][0].get("rationale", "") + " (edited by hand)"
    files[-1].write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    refuse(w, "repair draft")


def test_a_repair_decision_changed_after_the_review(w):  # the approval moved
    proposals = grounding_edits.load_proposals(w.root, w.plan_id)
    decided = grounding_edits.current_decisions(w.root, w.plan_id, proposals)
    target = next(pid for pid, d in sorted(decided.items()) if d.decision == "approve")
    with w.cap.active():
        run(w.cap, w.root, "grounding", "decide", target, "--plan", w.plan_id, "--decision", "reject",
            "--reviewer", "gm", "--reason", "changed my mind")
    refuse(w, "repair draft")


def test_the_rebase_decisions_revised(w):
    with w.cap.active():
        review = run(w.cap, w.root, "rebase", "show", "--plan", w.plan_id)["data"]
        argv = ["rebase", "decide", "--plan", w.plan_id, "--reviewer", "gm", "--reason", "read again, differently"]
        for c in (2, 3, 4, 5):
            argv += ["--source-decision", f"{c}=adopt-with-repairs"]
        for m in review["unknown_members"]:
            argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
        assert run(w.cap, w.root, *argv)["data"]["written"] is True
    refuse(w, "rebase decisions")


def test_the_preview_hash_does_not_match(w):
    msg = refuse(w, "preview is stale", preview_sha="0" * 64)
    assert "confirm the new hash" in msg


def test_a_staged_draft_hand_edited_after_the_preview(w):
    draft = w.root / "docs/summary_native/ch002-005/state/drafts/world_state.draft.md"
    draft.write_bytes(draft.read_bytes() + b"\nA hand-written line that was never reviewed.\n")
    refuse(w, "preview is stale")


def test_a_candidate_edited_after_the_review(w):
    cand = gp.grounding_dir(w.root, w.plan_id) / "candidates/world_state.md"
    cand.write_bytes(cand.read_bytes() + b"\nAn unreviewed line.\n")
    refuse(w, "candidate changed since review")


def test_only_a_rebase_plan_binds_the_rebase_inputs(w):
    plan = w.plan()
    assert plan.kind == "rebase"
    delta = plan.model_copy(update={"kind": "delta", "rebase_id": None})
    assert rb._grounding_hashes(w.root, delta)["evidence_sha256"] != rb._grounding_hashes(w.root, plan)["evidence_sha256"]
