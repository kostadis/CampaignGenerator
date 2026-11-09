"""Spec 040 US2 (T025): the production blocker, resolved end to end at the CLI through the REAL gates.

One module-scoped build (the synthetic git-initialised campaign with an active generation through chapter 5, four
corrected summaries, and a pending chapter-6 plan with TWO NPC dossiers already published through the run) is
driven through: inspect, prepare, GM repairs and holds, decide, ``grounding check``, ``grounding preview`` (stages
the gap-labelled range), the real ``claims select/review/check``, the exact four-document signoffs, ``review
handoff`` and ``grounding apply``; then the pending plan is rebound and finished with ``delta run resume``.

Claims selection, review bindings and promotion are never mocked.  The only stand-ins are at the model seam: the
NPC drafting call during the fixture build, the grounding consistency reviewer, and the grounding edit proposer.
The tests are ordered: the last ones mutate the pending plan.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.summary_native.delta import (
    baseline as bl, custody_store, grounding_check, grounding_edits, npc_update, rebind, review_binding as rb,
)
from pipelines.summary_native.delta.plan import load_plan, plans_dir
from pipelines.summary_native.delta.receipt import RebaseReceipt, load_receipt
from pipelines.summary_native.delta.run import receipt_path
from pipelines.summary_native.promotion.errors import PromotionError
from tests import _rebase_fixture as rf
from tests.test_delta_grounding_e2e import anchor, run
from tests.test_rebase_fixture import _select_pending


class World:
    def __init__(self, fx, rebased, cap, mp, blocked) -> None:
        self.fx, self.rebased, self.cap, self.mp, self.blocked = fx, rebased, cap, mp, blocked

    def call(self, *argv, expect=0):
        with self.cap.active():
            return run(self.cap, self.fx.root, *argv, expect=expect)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    cap = rf.Capture()
    with pytest.MonkeyPatch.context() as mp:
        with cap.active():
            fx = rf.build(tmp_path_factory.mktemp("rebase-e2e"), cap, mp, npc=True)
            inspected = run(cap, fx.root, "rebase", "inspect")["data"]
            try:
                _select_pending(fx)
                blocked = None
            except PromotionError as exc:
                blocked = (exc.code, str(exc))
            receipts_before = rf.pending_receipts(fx)
            rebased = rf.do_rebase(fx, cap)
        rebased.inspected_before = inspected
        rebased.receipts_before = receipts_before
        yield World(fx, rebased, cap, mp, blocked)


# --------------------------------------------------------------------------- before

def test_the_fixture_is_blocked_before_the_rebase(world):
    assert world.blocked is not None and world.blocked[0] == "CLAIMS_SOURCE_STALE"
    assert "run: summary_native delta rebase inspect" in world.blocked[1]
    assert [e["chapter"] for e in world.rebased.inspected_before["stale"]] == [2, 3, 4, 5]
    assert len(world.fx.npc_members) == 2 and len(world.rebased.receipts_before) == 2  # real receipts on disk


# --------------------------------------------------------------------------- the rebase

def test_the_rebase_publishes_a_child_generation_through_the_real_gates(world):
    fx, rbd = world.fx, world.rebased
    assert rbd.checked["passed"] is True and rbd.checked["call_counts"]["model"] == 0  # no consistency model
    assert rbd.applied["applied"] is True
    assert rbd.new_generation != fx.generation_id
    root = fx.root
    active = bl.bind(root)
    assert active.generation_id == rbd.new_generation
    parent = bl._delta_parent(root, bl._read_manifest(root, active.generation_id))
    assert parent is not None and parent.generation_id == fx.generation_id  # the old generation is the lineage parent
    lineage = rebind._lineage_of(root, bl._read_manifest(root, active.generation_id))
    block = lineage["rebase"]
    assert block["rebase_id"] == rbd.rebase_id and lineage["kind"] == "delta"
    assert [s["chapter"] for s in block["sources"]] == [2, 3, 4, 5]
    for s in block["sources"]:
        assert s["old_sha256"] == fx.old_sha[s["chapter"]] and s["new_sha256"] == fx.new_sha[s["chapter"]]
        assert custody_store.get(root, s["old_sha256"]) is not None  # the old bytes are snapshotted
        assert s["old_snapshot"].endswith(s["old_sha256"]) and s["current_snapshot"].endswith(s["new_sha256"])
    assert len(block["held_lines"]) == 1451 and len(block["repaired_lines"]) == 3  # 1 chapter-5 hold + 1450 planning
    assert block["attested_members"] and block["decisions_sha256"]


def test_history_is_byte_identical_after_the_rebase(world):  # SC-004
    before, after = world.rebased.history_before, world.rebased.history_after
    assert before and all(after.get(path) == digest for path, digest in before.items()), \
        [p for p, d in before.items() if after.get(p) != d]
    for chapter in world.fx.corrected:  # authored summaries were never written
        path = world.fx.paths[chapter]
        assert rf.sha(path.read_bytes()) == world.fx.new_sha[chapter]
    assert rf.git(world.fx.root, "status", "--porcelain", ":(glob)docs/summaries/*.md") == ""


def test_the_candidate_applies_only_approved_repairs_and_holds(world):
    fx, rbd = world.fx, world.rebased
    root = fx.root
    old = bl.baseline_documents(bl.bind(root), root)  # the documents of the NEW active generation
    after = old["world_state"].decode("utf-8")
    assert "for a fee of 40 gold" in after and "The company holds three prisoners." in after
    assert "The company holds four prisoners." not in after
    marker = f"⚠ held: superseded by correction to ch 005 — see rebase {rbd.rebase_id}"
    assert after.count(marker) == 1  # the held line stays, one marker follows it
    assert "The far marker stands." not in after.replace("The far marker beyond the eastern marker still stands.", "")
    planning = old["planning"].decode("utf-8")
    assert planning.count("⚠ held: superseded by correction to ch 003") == 1450  # the bulk hold, line by line


def test_bulk_hold_lists_every_line_and_touches_only_that_entry(world):
    hold = world.rebased.hold
    assert hold["count"] == 1450 == len(hold["held_lines"]) and hold["entry"] == "3/003.01"
    assert hold["reviewer"] == "gm" and hold["reason"]
    record = json.loads((world.fx.root / hold["record"]).read_text())
    assert record["held_lines"] == hold["held_lines"]
    proposals = grounding_edits.load_proposals(world.fx.root, world.rebased.plan_id)
    entries = {p.target_id: p for p in proposals.proposals}
    docs = {l["line_id"]: l for l in world.rebased.review["affected_lines"]}
    assert {docs[i]["entry"] for i in hold["held_lines"]} == {"003.01"} and {docs[i]["chapter"] for i in hold["held_lines"]} == {3}
    assert {docs[i]["document"] for i in hold["held_lines"]} == {"planning"}
    assert len(entries) == 1450 + 4


def test_the_new_generation_pins_selected_chapters_and_parents_elsewhere(world):
    fx, root = world.fx, world.fx.root
    manifest = bl._read_manifest(root, bl.bind(root).generation_id)
    rows = bl._custody_rows(root, manifest)
    for chapter in (2, 3, 4, 5):
        assert rows[chapter] == (fx.paths[chapter].relative_to(root).as_posix(), fx.new_sha[chapter])
    assert rows[1] == (fx.paths[1].relative_to(root).as_posix(), fx.old_sha[1])  # inherited from the parent chain
    stale = world.call("rebase", "inspect")["data"]
    assert stale["stale"] == [] and stale["checked"] == 5  # the blocker is gone
    range_dir = root / "docs/summary_native/ch002-005"
    staged = json.loads((range_dir / "manifest.json").read_text())
    assert staged["kind"] == "custody_rebase" and staged["range"] == {"since": 2, "until": 5, "gaps": []}
    assert {f["chapter"]: f["sha256"] for f in staged["files"]} == {c: fx.new_sha[c] for c in (2, 3, 4, 5)}


def test_the_rebase_receipt_reports_what_was_and_was_not_read(world):  # SC-007
    out = world.call("receipt", "--plan", world.rebased.plan_id)
    path = receipt_path(world.fx.root, world.rebased.plan_id)
    receipt = load_receipt(path)
    assert isinstance(receipt, RebaseReceipt) and out["receipt"]["rebase_id"] == world.rebased.rebase_id
    assert receipt.model_calls == 0 and receipt.call_counts["model"] == 0
    assert receipt.parsed_historical == {"selected": [2, 3, 4, 5], "unselected": []}  # no unselected chapter was parsed
    assert receipt.integrity_reads == 5 and receipt.unselected_stale_remaining == []
    assert receipt.model_input_sources == {"affected_lines": [], "entry_diffs": []}  # no model ever saw a source
    assert receipt.cached_evidence_reused == 0 and receipt.followup_consumers == []
    assert receipt.new_generation_ref.startswith(world.rebased.new_generation)
    assert receipt.parent_generation_ref.startswith(world.fx.generation_id)
    assert [r["chapter"] for r in receipt.sources_and_decisions] == [2, 3, 4, 5]
    assert all(r["decision"] == "adopt-with-repairs" and r["rebased"] for r in receipt.sources_and_decisions)


# --------------------------------------------------------------------------- resume (mutates the pending plan)

def consistency_standin(world, calls):
    """A deterministic reviewer at the model seam: it flags the old prisoner count wherever a changed line repeats it."""
    def fake(client, system, user, model, **kw):
        calls.append(1)
        changed = user.split("## Changed lines", 1)[1] if "## Changed lines" in user else ""
        found = [ln for ln in changed.splitlines() if "four prisoners" in ln.lower()]
        return json.dumps({"findings": [{"document": "world_state", "line": 1,
                                         "detail": f"the corrected chapter 5 holds three prisoners, but: {found[0]}"}]
                           if found else []})
    world.mp.setattr(grounding_check, "stream_api", fake)
    world.mp.setattr(grounding_check, "make_client", lambda **k: object())


def test_rebind_resume_and_publish_the_pending_chapter(world):
    fx, root, rbd = world.fx, world.fx.root, world.rebased
    pending = fx.pending_plan_id
    old_plan = load_plan(plans_dir(root), pending)
    receipts = rf.pending_receipts(fx)
    assert receipts == rbd.receipts_before and len(receipts) == 2
    published = []
    real_publish = npc_update.publish
    world.mp.setattr(npc_update, "publish", lambda *a, **k: published.append(a) or real_publish(*a, **k))
    drafted: list[int] = []  # the NPC drafting model: it must not be called again either
    from pipelines.summary_native import npc_draft
    world.mp.setattr(npc_draft, "stream_api", lambda *a, **k: drafted.append(1) or (_ for _ in ()).throw(
        AssertionError("an NPC was re-drafted during resume")))

    with world.cap.active():
        data = rf.rrun(world.cap, root, "rebind", "--plan", pending, "--baseline", rbd.new_generation)
    assert data["written"] is True and data["from_revision"] == 1 and data["to_revision"] == 2
    assert data["new_baseline_ref"] == bl.bind(root).ref and data["rebase_id"] == rbd.rebase_id
    assert data["reapplied_edits"] and data["stale_edits"] == []  # the approved ch6 edit still has its exact before bytes
    assert {"candidates/world_state.md"} <= {Path(p).relative_to(Path(p).parents[1]).as_posix() for p in data["invalidated"]
                                              if "candidates" in p}
    assert any(p.endswith("preview.json") for p in data["invalidated"]) and any(p.endswith("lineage.json") for p in data["invalidated"])
    assert all((root / p).exists() for p in data["invalidated"])  # nothing was deleted
    plan2 = load_plan(plans_dir(root), pending)
    assert plan2.revision == 2 and plan2.grounding_baseline_ref == bl.bind(root).ref and plan2.plan_id == old_plan.plan_id
    # NPC bindings stay fresh and the receipts are untouched
    assert {c["scope"] for c in data["npc_carried"]} == {"publication"}
    assert rb.require_fresh(root, plan2, "npc", members=fx.npc_slugs, required=True) is not None
    assert rf.pending_receipts(fx) == receipts
    # the grounding artifacts bound to the old plan digest are refused until they are rebuilt: the old preview
    # cannot be applied to the rebound plan (exit 1, no publication binding for it yet)
    from pipelines.summary_native.delta import grounding_publish as gp
    old_preview = json.loads((gp.grounding_dir(root, pending) / gp.PREVIEW_FILE).read_text())["preview_sha256"]
    assert "review binding" in world.call("grounding", "apply", "--plan", pending, "--preview-sha", old_preview, expect=1)["error"]
    assert bl.bind(root).generation_id == rbd.new_generation  # and nothing was published by the attempt

    # the ch6 candidate is rebuilt on the new baseline and the consistency pass FLAGS the old prisoner count
    calls: list[int] = []
    consistency_standin(world, calls)
    checked = world.call("grounding", "check", "--plan", pending)
    assert calls == [1] and checked["approval"] is None
    flagged = [f for f in checked["findings"] if f["code"] == "CONSISTENCY_MODEL"]
    assert flagged and "three prisoners" in flagged[0]["detail"] and flagged[0]["severity"] == "advisory"
    candidate = (gp.grounding_dir(root, pending) / "candidates/world_state.md").read_text(encoding="utf-8")
    assert "Four prisoners were marched" in candidate and "The company holds three prisoners." in candidate

    # the GM repairs it: a new proposal for the anchor, approved, and the flag clears
    target, line = anchor(root)

    def fake_propose(client, system, user, model, **kw):
        return json.dumps({"proposals": [{
            "target_id": target.target_id, "category": "new_information", "support": rf.SUPPORT_6,
            "after_text": line + "\nThe prisoners were marched to the far marker. [ch 006 / 006.01]",
            "rationale": "the count is no longer asserted here; chapter 5 holds it"}]})
    world.mp.setattr(grounding_edits, "stream_api", fake_propose)
    world.mp.setattr(grounding_edits, "make_client", lambda **k: object())
    proposed = world.call("grounding", "propose", "--plan", pending)
    world.call("grounding", "decide", proposed["proposals"][0]["proposal_id"], "--plan", pending,
               "--decision", "approve", "--reviewer", "gm")
    rechecked = world.call("grounding", "check", "--plan", pending)
    assert rechecked["passed"] is True and not [f for f in rechecked["findings"] if f["code"] == "CONSISTENCY_MODEL"]

    # stage, real claims, signoffs, the grounding handoff only (the NPC binding is NOT re-made), then resume
    with world.cap.active():
        rf.claims_and_signoffs(world.cap, root, pending, since=6, until=6, review_id="pending-review", apply=False)
    resumed = world.call("run", "resume", "--plan", pending, expect=0)
    assert resumed["status"] == "complete", resumed
    assert published == [] and drafted == []  # NPC publish and NPC draft call counts are 0 during resume
    assert rf.pending_receipts(fx) == receipts  # and the receipts are byte-identical
    active = bl.bind(root)
    assert active.generation_id not in (fx.generation_id, rbd.new_generation)
    parent = bl._delta_parent(root, bl._read_manifest(root, active.generation_id))
    assert parent.generation_id == rbd.new_generation
    live = (root / "docs/world_state.md").read_text(encoding="utf-8")
    assert "The prisoners were marched to the far marker. [ch 006 / 006.01]" in live
    assert "The company holds three prisoners." in live and "The company holds four prisoners." not in live
    assert len(list((root / "docs/grounding/generations").iterdir())) == 5
    assert world.call("rebase", "inspect")["data"]["stale"] == []


# --------------------------------------------------------------------------- gap-labelled staging (T020)

def test_a_non_contiguous_selection_stages_a_range_that_names_its_gaps(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch, pending_ch6=False)
    root = fx.root
    out = run(capsys, root, "rebase", "prepare", "--source", str(fx.paths[2]), "--source", str(fx.paths[4]))["data"]
    pid = out["plan_id"]
    review = run(capsys, root, "rebase", "show", "--plan", pid)["data"]
    for line in review["affected_lines"]:
        made = run(capsys, root, "rebase", "repair", "--plan", pid, "--line", line["line_id"], "--text",
                   f"Corrected. [ch {line['chapter']:03d} / {line['entry']}]", "--reason", "corrected",
                   "--reviewer", "gm")["data"]
        run(capsys, root, "grounding", "decide", made["proposal_id"], "--plan", pid, "--decision", "approve",
            "--reviewer", "gm")
    argv = ["rebase", "decide", "--plan", pid, "--reviewer", "gm", "--reason", "read by the GM",
            "--source-decision", "2=adopt-with-repairs", "--source-decision", "4=adopt-with-repairs"]
    for m in review["unknown_members"]:
        argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
    run(capsys, root, *argv)
    assert run(capsys, root, "grounding", "check", "--plan", pid)["passed"] is True
    staged = run(capsys, root, "grounding", "preview", "--plan", pid)["staged"]
    assert staged["range"] == "ch002-004"
    manifest = json.loads((root / "docs/summary_native/ch002-004/manifest.json").read_text())
    assert manifest["kind"] == "custody_rebase" and manifest["range"] == {"since": 2, "until": 4, "gaps": [3]}
    assert {f["chapter"]: f["sha256"] for f in manifest["files"]} == {2: fx.new_sha[2], 4: fx.new_sha[4]}  # selected only
    # an unselected stale chapter is still stale, and the claims gate says so rather than being talked round
    assert [e["chapter"] for e in run(capsys, root, "rebase", "inspect")["data"]["stale"]] == [2, 3, 4, 5]
