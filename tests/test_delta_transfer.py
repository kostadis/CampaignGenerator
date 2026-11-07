"""spec 039 T078: a verified worktree/artifact transfer keeps canonical identity (FR-022, Story 5 #2).

The moved-campaign guard and campaign.json are never touched; a separate binding record carries the proof.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest

from pipelines.summary_native import cli as sn_cli
from pipelines.summary_native.delta import plan as dplan
from pipelines.summary_native.delta import transfer
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, DeltaRefusal
from pipelines.summary_native.review import store
from tests._delta_us2 import M, copy_fixture


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _canonical(tmp_path: Path) -> Path:
    root = copy_fixture(tmp_path)
    ident = root / "docs" / "reviews" / "campaign.json"
    ident.parent.mkdir(parents=True, exist_ok=True)
    ident.write_text(json.dumps({"version": 1, "campaign_id": str(uuid.uuid4()),
                                 "canonical_root": str(root.resolve())}), encoding="utf-8")
    p = dplan.create_plan(campaign_identity=json.loads(ident.read_text())["campaign_id"], products=["npc"],
                          stopping_point="plan", models=M,
                          source_paths=[root / "docs" / "summaries" / "003-the-new-fire.md"])
    dplan.save_plan(p, dplan.plans_dir(root))
    return root


def _worktree(canonical: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "worktree"
    shutil.copytree(canonical, wt)
    return wt


def test_verified_bind_preserves_identity_without_editing_guard_or_identity(tmp_path):
    canon = _canonical(tmp_path)
    wt = _worktree(canon, tmp_path)
    guard_src = Path(store.__file__)
    before = (_sha(wt / "docs/reviews/campaign.json"), _sha(canon / "docs/reviews/campaign.json"), _sha(guard_src))
    # the existing guard refuses the copy, and keeps refusing it after binding
    with pytest.raises(store.ReviewStoreError, match="REVIEW_CAMPAIGN_MOVED"):
        store.load_campaign_identity(wt)
    path = transfer.bind(canon, wt)
    assert path.parent == wt.resolve() / "docs/summaries/delta/transfer" and path.name == "binding-1.json"
    cid = json.loads((canon / "docs/reviews/campaign.json").read_text())["campaign_id"]
    assert transfer.bound_identity(wt) == cid
    after = (_sha(wt / "docs/reviews/campaign.json"), _sha(canon / "docs/reviews/campaign.json"), _sha(guard_src))
    assert before == after
    with pytest.raises(store.ReviewStoreError, match="REVIEW_CAMPAIGN_MOVED"):
        store.load_campaign_identity(wt)
    assert transfer.bind(canon, wt) == path  # idempotent


def test_plan_made_in_canonical_is_accepted_in_bound_copy_only(tmp_path):
    canon = _canonical(tmp_path)
    wt = _worktree(canon, tmp_path)
    plan_id = next(dplan.plans_dir(canon).glob("*.json")).stem.rsplit("-r", 1)[0]
    loaded = dplan.load_plan(dplan.plans_dir(wt), plan_id)
    with pytest.raises(DeltaRefusal) as unbound:
        transfer.bound_identity(wt)
    assert unbound.value.exit_code == EXIT_REFUSAL
    transfer.bind(canon, wt)
    assert transfer.bound_identity(wt) == loaded.campaign_identity


def test_unverified_transfers_refuse(tmp_path):
    canon = _canonical(tmp_path)
    # different campaign id
    other = tmp_path / "other"
    shutil.copytree(canon, other)
    (other / "docs/reviews/campaign.json").write_text(json.dumps(
        {"version": 1, "campaign_id": str(uuid.uuid4()), "canonical_root": str(canon.resolve())}))
    with pytest.raises(DeltaRefusal, match="unverified transfer") as e:
        transfer.bind(canon, other)
    assert e.value.exit_code == EXIT_REFUSAL and not (other / transfer.TRANSFER_REL).exists()
    # missing identity
    missing = tmp_path / "missing"
    shutil.copytree(canon, missing)
    (missing / "docs/reviews/campaign.json").unlink()
    with pytest.raises(DeltaRefusal, match="no campaign identity"):
        transfer.verify(canon, missing)
    # plan carrying another campaign identity
    wt = _worktree(canon, tmp_path)
    pf = next(dplan.plans_dir(wt).glob("*.json"))
    rec = json.loads(pf.read_text())
    rec["campaign_identity"] = "someone-else"
    pf.write_text(json.dumps(rec))
    with pytest.raises(DeltaRefusal, match="different campaign identity"):
        transfer.verify(canon, wt)
    # a "canonical" that is itself a copy
    with pytest.raises(DeltaRefusal, match="not the canonical"):
        transfer.verify(wt, canon)


def test_tampered_or_stale_binding_refuses(tmp_path):
    canon = _canonical(tmp_path)
    wt = _worktree(canon, tmp_path)
    path = transfer.bind(canon, wt)
    good = path.read_text()
    rec = json.loads(good)
    rec["campaign_id"] = str(uuid.uuid4())
    path.write_text(json.dumps(rec))
    with pytest.raises(DeltaRefusal, match="altered") as e:
        transfer.bound_identity(wt)
    assert e.value.exit_code == EXIT_REFUSAL
    path.write_text(good)
    assert transfer.bound_identity(wt)
    ident = wt / "docs/reviews/campaign.json"
    ident.write_text(ident.read_text() + "\n")
    with pytest.raises(DeltaRefusal) as e2:
        transfer.bound_identity(wt)
    assert e2.value.exit_code == EXIT_STALE


def test_cli_verify_and_bind(tmp_path, capsys):
    canon = _canonical(tmp_path)
    wt = _worktree(canon, tmp_path)
    base = ["delta", "transfer"]
    assert sn_cli.main(base + ["verify", "--campaign-dir", str(wt), "--canonical", str(canon), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    assert sn_cli.main(base + ["bind", "--campaign-dir", str(wt), "--canonical", str(canon), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["bound"] is True
    assert sn_cli.main(base + ["bind", "--campaign-dir", str(wt), "--json"]) == 2
    capsys.readouterr()
    (wt / "docs/reviews/campaign.json").unlink()
    assert sn_cli.main(base + ["verify", "--campaign-dir", str(wt), "--canonical", str(canon), "--json"]) == 1


def test_bound_worktree_can_plan_and_an_unbound_copy_is_refused(tmp_path, capsys):
    canon = _canonical(tmp_path)
    wt = _worktree(canon, tmp_path)
    src = str(wt / "docs" / "summaries" / "003-the-new-fire.md")
    argv = ["delta", "plan", "--campaign-dir", str(wt), "--product", "npc", "--source", src, "--json"]
    # unbound moved copy: refused by the transfer check, with the existing guard untouched
    assert sn_cli.main(argv) == EXIT_REFUSAL
    capsys.readouterr()
    assert not any((wt / "docs/summaries/delta/plans").glob("*-r2.json"))
    transfer.bind(canon, wt)
    assert sn_cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    cid = json.loads((canon / "docs/reviews/campaign.json").read_text())["campaign_id"]
    assert dplan.load_plan(dplan.plans_dir(wt), out["plan_id"]).campaign_identity == cid
    with pytest.raises(store.ReviewStoreError, match="REVIEW_CAMPAIGN_MOVED"):
        store.load_campaign_identity(wt)
