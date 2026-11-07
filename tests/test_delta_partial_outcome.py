"""T068 / Story 4 acceptance 4-5, FR-019: partial outcomes, dependency holds, recovery and replay.

* a held NPC keeps its old publication;
* a held member that a grounding publication requires blocks that publication;
* a mixed result is ``partial``, never ``complete``;
* an identical completed replay performs no content write.
"""

from __future__ import annotations

import json

from _delta_run_support import (RANGE, copy_fixture, install_fake, make_apply_plan, resume, sign_stems, status)
from pipelines.summary_native.delta import grounding_publish as gp, run as run_mod
from pipelines.summary_native.delta.run import MemberOutcome, RunState, RunStatus, derive_status
from tests.support.delta_faults import tree_snapshot

TOBIN = {"npc_tobin_fenwick": "Tobin Fenwick"}


def test_held_npc_keeps_its_old_publication_and_the_run_is_partial(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    install_fake(monkeypatch)
    old_bytes = (root / "docs/npcs/brannoc-ironvein.md").read_bytes()
    old_log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())["brannoc-ironvein"]
    resume(capsys, root, plan)
    sign_stems(root, capsys, TOBIN)  # Brannoc is never signed
    rc, rec, _ = resume(capsys, root, plan)
    assert rc == 4 and rec["status"] == "partial"
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    outcomes = {m.subject: m.outcome for m in state.members}
    assert outcomes["Brannoc Ironvein"] is MemberOutcome.held and outcomes["Tobin Fenwick"] is MemberOutcome.published
    assert (root / "docs/npcs/brannoc-ironvein.md").read_bytes() == old_bytes
    assert json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())["brannoc-ironvein"] == old_log
    assert (root / "docs/npcs/tobin-fenwick.md").exists()
    assert not run_mod.receipt_path(root, plan.plan_id).exists()  # a completion receipt only on completion
    assert status(capsys, root, plan)["status"] == "partial"

    # the receipt verb still reports the truth: one held subject, one new
    rc = __import__("pipelines.summary_native.cli", fromlist=["main"]).main(
        ["delta", "receipt", "--campaign-dir", str(root), "--plan", plan.plan_id, "--json"])
    receipt = json.loads(capsys.readouterr().out)["receipt"]
    assert rc == 0 and receipt["held"] == ["Brannoc Ironvein"] and receipt["new"] == ["Tobin Fenwick"]
    assert "http" not in json.dumps(receipt) and "token" not in json.dumps(receipt).lower()

    # the GM signs Brannoc later; the next resume finishes only what is left
    sign_stems(root, capsys, {"npc_brannoc_ironvein": "Brannoc Ironvein"})
    tobin_before = (root / "docs/npcs/tobin-fenwick.md").stat().st_mtime_ns
    rc, rec, _ = resume(capsys, root, plan)
    assert rc == 0 and rec["status"] == "complete"
    assert (root / "docs/npcs/tobin-fenwick.md").stat().st_mtime_ns == tobin_before  # not re-published


def test_a_required_held_dependency_blocks_grounding_publication(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root, products=("npc", "grounding"))
    install_fake(monkeypatch)
    (run_mod.plan_dir(root, plan.plan_id)).mkdir(parents=True, exist_ok=True)
    run_mod.requires_path(root, plan.plan_id).write_text(json.dumps({"subjects": ["Brannoc Ironvein"]}))
    applied = []

    def fake_apply(plan_, sha, *, campaign_dir, publisher=None):
        applied.append(sha)
        return {}

    monkeypatch.setattr(gp, "apply", fake_apply)
    resume(capsys, root, plan)
    sign_stems(root, capsys, TOBIN)  # Tobin published; Brannoc (required by grounding) held
    pv = gp.grounding_dir(root, plan.plan_id) / gp.PREVIEW_FILE
    pv.parent.mkdir(parents=True, exist_ok=True)
    pv.write_text(json.dumps({"preview_sha256": "a" * 64}))
    rc, rec, _ = resume(capsys, root, plan)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    g = next(m for m in state.members if m.subject == "grounding")
    assert g.outcome is MemberOutcome.held and "Brannoc Ironvein" in (g.reason or "")
    assert applied == [] and rc == 4 and rec["status"] == "partial"

    sign_stems(root, capsys, {"npc_brannoc_ironvein": "Brannoc Ironvein"})
    rc, rec, err = resume(capsys, root, plan)
    assert applied == ["a" * 64] and rc == 0 and rec["status"] == "complete", (rec, err)


def test_identical_completed_replay_writes_nothing(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    fake = install_fake(monkeypatch)
    resume(capsys, root, plan)
    sign_stems(root, capsys)
    assert resume(capsys, root, plan)[0] == 0
    before = tree_snapshot(root, "docs")
    calls = len(fake.prompts)
    rc, rec, _ = resume(capsys, root, plan)
    assert rc == 0 and rec["status"] == "complete" and rec["call_counts"]["model"] == 0
    assert set(rec["reused_stages"]) == {"census", "draft", "verify", "publish", "receipt"}
    assert tree_snapshot(root, "docs") == before  # same bytes and same mtimes: no content write
    assert len(fake.prompts) == calls


def _state(**stages):
    s = RunState(run_id="r", plan_ref="p")
    for name, st in stages.items():
        run_mod.start_stage(s, name, "d")
        run_mod.finish_stage(s, name, ok=st)
    return s


def test_status_derivation_rules(tmp_path):
    from pipelines.summary_native.delta import plan as dplan
    from _delta_us2 import M
    (tmp_path / "003-x.md").write_text("x")
    p = dplan.create_plan(campaign_identity="c", products=["npc"], stopping_point="apply",
                          source_paths=[tmp_path / "003-x.md"], models=M)
    s = _state(census=True, draft=True, verify=True, publish=True)
    s.members = [run_mod.Member(subject="a", outcome="published"), run_mod.Member(subject="b", outcome="held")]
    assert derive_status(s, p) is RunStatus.partial
    assert derive_status(s, p, ambiguous=1) is RunStatus.recovery_required
    s.members[1].outcome = MemberOutcome.published
    assert derive_status(s, p) is RunStatus.complete
    assert derive_status(s, p, stale=True) is RunStatus.stale
    s.members = [run_mod.Member(subject="b", outcome="held")]
    assert derive_status(s, p) is RunStatus.awaiting_review
    assert derive_status(_state(census=True, draft=False), p) is RunStatus.failed
    assert derive_status(_state(census=True), p) is RunStatus.running
