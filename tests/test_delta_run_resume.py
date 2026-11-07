"""T066 / SC-006: resume after a fault at every named boundary.

Completed, compatible stages are reused by digest with zero model calls; no approval is created or
duplicated by a resume; a target written before its log is reconciled, never written twice.
Faults are ``BaseException`` crashes (``tests/support/delta_faults.py``); the only fake is the model call.
"""

from __future__ import annotations

import json

import pytest

from _delta_run_support import (RANGE, copy_fixture, install_fake, make_apply_plan, resume, sign_stems, status)
from pipelines.summary_native.delta import run as run_mod
from pipelines.summary_native.delta.receipt import load_receipt
from tests.support.delta_faults import BOUNDARIES, InjectedFault, authority_fingerprint, inject, tree_snapshot

PRE_SIGN = ("evidence_write", "model_output", "verify")
SIGN = ("review_creation", "sign_off")
PUBLISH = ("first_publish", "target_before_log", "log_before_receipt")


def test_every_boundary_is_covered():
    assert set(PRE_SIGN + SIGN + PUBLISH + ("receipt_creation",)) == set(BOUNDARIES)


def fresh(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_apply_plan(root)
    return root, plan, install_fake(monkeypatch)


def crash(capsys, root, plan, boundary):
    with inject(boundary), pytest.raises(InjectedFault):
        resume(capsys, root, plan)
    capsys.readouterr()


def finish(capsys, root, plan):
    rc, rec, err = resume(capsys, root, plan)
    assert rc == 0, (rec, err)
    assert rec["status"] == "complete"
    return rec


def published_count(root):
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    return {s: e["published_sha256"] for s, e in log.items() if s in ("brannoc-ironvein", "tobin-fenwick")}


@pytest.mark.parametrize("boundary", PRE_SIGN)
def test_fault_before_sign_off_reuses_what_completed(tmp_path, monkeypatch, capsys, boundary):
    root, plan, fake = fresh(tmp_path, monkeypatch)
    crash(capsys, root, plan, boundary)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    assert state.status is not run_mod.RunStatus.complete
    done = {s.name for s in state.stages if s.status is run_mod.StageStatus.succeeded}
    assert "census" in done  # completed before every one of these boundaries
    calls_before = len(fake.prompts)

    rc, rec, err = resume(capsys, root, plan)
    assert rc == 4, (rec, err)  # drafted and verified; publication is held for the GM's sign-off
    assert "census" in rec["reused_stages"]
    if boundary == "verify":
        assert "draft" in rec["reused_stages"] and rec["call_counts"]["model"] == 0
        assert len(fake.prompts) == calls_before
    if boundary == "evidence_write":
        assert calls_before == 0
    sign_stems(root, capsys)
    finish(capsys, root, plan)
    assert set(published_count(root)) == {"brannoc-ironvein", "tobin-fenwick"}
    assert len(fake.prompts) <= 3  # never more than one lost answer beyond the two drafts


@pytest.mark.parametrize("boundary", SIGN)
def test_fault_in_review_or_sign_off_creates_no_duplicate_approval(tmp_path, monkeypatch, capsys, boundary):
    root, plan, fake = fresh(tmp_path, monkeypatch)
    rc, rec, _ = resume(capsys, root, plan)
    assert rc == 4 and len(fake.prompts) == 2
    with inject(boundary), pytest.raises(InjectedFault):
        sign_stems(root, capsys)
    capsys.readouterr()
    ledger = authority_fingerprint(root)

    rc, rec, err = resume(capsys, root, plan)
    assert rc == 4 and rec["call_counts"]["model"] == 0, (rec, err)
    assert {"census", "draft", "verify"} <= set(rec["reused_stages"])
    assert authority_fingerprint(root) == ledger  # resume approves nothing
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()

    sign_stems(root, capsys)  # the GM's real sign-off, once
    finish(capsys, root, plan)
    assert len(fake.prompts) == 2


@pytest.mark.parametrize("boundary", PUBLISH + ("receipt_creation",))
def test_fault_during_publication_is_reconciled_not_repeated(tmp_path, monkeypatch, capsys, boundary):
    root, plan, fake = fresh(tmp_path, monkeypatch)
    assert resume(capsys, root, plan)[0] == 4
    sign_stems(root, capsys)
    ledger = authority_fingerprint(root)
    crash(capsys, root, plan, boundary)
    assert authority_fingerprint(root) == ledger
    brannoc = root / "docs/npcs/brannoc-ironvein.md"
    pre = (brannoc.read_bytes(), brannoc.stat().st_mtime_ns)

    if boundary == "target_before_log":
        # the target holds the new dossier but the log does not know: ambiguous until reconciled
        s = status(capsys, root, plan)
        assert s["status"] == "recovery_required" and s["recovery_required"] == ["brannoc-ironvein"]
        rc, rec, _ = resume(capsys, root, plan)
        assert rc == 0, rec
        assert (brannoc.read_bytes(), brannoc.stat().st_mtime_ns) == pre  # not written a second time
    else:
        rc, rec, err = resume(capsys, root, plan)
        assert rc == 0, (rec, err)
        if boundary != "first_publish":
            assert (brannoc.read_bytes(), brannoc.stat().st_mtime_ns) == pre
    assert rec["status"] == "complete" and rec["call_counts"]["model"] == 0
    assert {"census", "draft", "verify"} <= set(rec["reused_stages"])
    assert authority_fingerprint(root) == ledger  # no second approval, no new ledger entry
    assert set(published_count(root)) == {"brannoc-ironvein", "tobin-fenwick"}
    assert len(fake.prompts) == 2
    receipt = load_receipt(run_mod.receipt_path(root, plan.plan_id))
    assert sorted(receipt.changed + receipt.new) == ["Brannoc Ironvein", "Tobin Fenwick"]
    if boundary in ("target_before_log", "log_before_receipt"):
        assert receipt.recovery_state == "recovered"


def test_a_failed_stage_is_never_recorded_as_success(tmp_path, monkeypatch, capsys):
    root, plan, _ = fresh(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("verifier exploded")

    from pipelines.summary_native.delta import npc_update
    monkeypatch.setattr(npc_update, "verify", boom)
    with pytest.raises(RuntimeError):
        resume(capsys, root, plan)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    stage = {s.name: s for s in state.stages}["verify"]
    assert stage.status is run_mod.StageStatus.failed and stage.artifacts == []
    assert state.status is run_mod.RunStatus.failed


def test_an_output_edited_after_the_stage_completed_is_not_silently_redone(tmp_path, monkeypatch, capsys):
    root, plan, fake = fresh(tmp_path, monkeypatch)
    assert resume(capsys, root, plan)[0] == 4
    draft = root / RANGE / "draft" / "npc_tobin_fenwick.md"
    draft.write_text(draft.read_text() + "\nA hand edit.\n")
    rc, rec, err = resume(capsys, root, plan)
    assert rc == 3 and len(fake.prompts) == 2  # refused; no model was called over the edit
    assert "re-run with --force" in err
