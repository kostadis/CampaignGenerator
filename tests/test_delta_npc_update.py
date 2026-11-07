"""NPC update internals (spec 039 T050, T051, T053, T054): drafting input, sparse verification,
per-member receipts and reconciliation."""

from __future__ import annotations

import json

import pytest

from _delta_npc_support import FakeModel, handoff_only, census_for, copy_fixture, install_fake, make_plan, sign_drafts
from pipelines.summary_native import npc_publish
from pipelines.summary_native.delta import associations as asc
from pipelines.summary_native.delta import npc_update
from pipelines.summary_native.delta.errors import DeltaRefusal
from pipelines.summary_native.delta.evidence import EvidenceSpan, SparseEvidence

BRANNOC = "docs/npcs/summary_native/ch001-003/draft/npc_brannoc_ironvein.md"


@pytest.fixture
def drafted(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    fake = install_fake(monkeypatch)
    out = npc_update.draft(root, plan)
    return root, plan, fake, out


def test_changed_member_keeps_historical_bytes_and_drops_restated_history(drafted):
    root, plan, fake, out = drafted
    prior = (root / "docs/npcs/summary_native/ch001-002/draft/npc_brannoc_ironvein.md").read_text()
    new = (root / BRANNOC).read_text()
    old_history = prior.split("## History with the Party\n", 1)[1].split("\n## ", 1)[0].rstrip("\n")
    old_quotes = prior.split("## Notable Quotes\n", 1)[1].split("\n## ", 1)[0].strip("\n")
    assert old_history in new and old_quotes in new
    assert new.count("Explains why the forge is cold") == 1  # the model restated it; the host dropped it
    state = json.loads((root / "docs/summaries/delta" / plan.plan_id / "npc/members.json").read_text())
    assert any("Explains why the forge is cold" in d for d in state["drops"]["npc_brannoc_ironvein"])


def test_prompt_is_built_from_prior_draft_new_evidence_and_never_the_published_dossier(drafted):
    root, plan, fake, out = drafted
    user = next(u for _s, u in fake.prompts if "subject: Brannoc Ironvein" in u)
    assert "PRIOR DOSSIER" in user and "Gives the party his apprentice's hammer" in user
    assert "Brannoc restarts the forge" in user or "restarts the forge" in user
    published = (root / "docs/npcs/brannoc-ironvein.md").read_text()
    assert "published by summary_native" in published and "published by summary_native" not in user
    assert "## Secrets" not in user


def test_new_member_has_no_prior_and_a_mention_is_not_drafted(drafted):
    root, plan, fake, out = drafted
    user = next(u for _s, u in fake.prompts if "subject: Tobin Fenwick" in u)
    assert "PRIOR DOSSIER" not in user
    assert not any("subject: Envoy Sella Marr" in u for _s, u in fake.prompts)
    assert out.members == ["Brannoc Ironvein", "Tobin Fenwick"]


def test_only_approved_associations_reach_the_prompt(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    quote = "the Lantern Guild would buy every blade the forge could make"
    import campaignlib
    monkeypatch.setattr(campaignlib, "make_client", lambda **k: object())
    reply = json.dumps([
        {"name": "Old Marrow Pike", "canonical_id": "Tobin Fenwick", "scene": "003.02",
         "relationship_support": quote, "scope": "faction offer relay"},
        {"name": "Old Marrow Pike", "canonical_id": "Brannoc Ironvein", "scene": "003.02",
         "relationship_support": "stranger called Old Marrow Pike leaned on the fence", "scope": "REJECTED-SCOPE"}])
    monkeypatch.setattr(campaignlib, "call_api", lambda c, s, u, m, *a, **k: reply)
    store = asc.propose(root, plan, [{"name": "Old Marrow Pike", "evidence": []}], model="m")
    ids = {a.canonical_id: a.id for a in store.associations}
    asc.decide(root, plan.plan_id, ids["Tobin Fenwick"], "approve", "GM")
    asc.decide(root, plan.plan_id, ids["Brannoc Ironvein"], "reject", "GM")
    fake = install_fake(monkeypatch)
    npc_update.draft(root, plan)
    tobin = next(u for _s, u in fake.prompts if "subject: Tobin Fenwick" in u)
    brannoc = next(u for _s, u in fake.prompts if "subject: Brannoc Ironvein" in u)
    assert "APPROVED ASSOCIATIONS" in tobin and "faction offer relay" in tobin
    assert "APPROVED ASSOCIATIONS" not in brannoc and "REJECTED-SCOPE" not in brannoc


def test_verification_is_sparse_and_never_presented_as_full(drafted):
    root, plan, fake, out = drafted
    md = (root / BRANNOC.replace(".md", ".verify.md")).read_text()
    assert "**Verdict: pass**" in md and "SPARSE" in md and "not a full-corpus verification" in md
    rec = json.loads((root / "docs/summaries/delta" / plan.plan_id / "npc/npc_brannoc_ironvein.verify.json").read_text()) \
        if (root / "docs/summaries/delta" / plan.plan_id / "npc/npc_brannoc_ironvein.verify.json").exists() else None
    results = npc_update.verify(root, plan)
    assert results["Brannoc Ironvein"]["evidence_kind"] == "sparse"
    with pytest.raises(DeltaRefusal, match="full evidence required"):
        npc_update.verify_text(root / "docs/npcs/summary_native/ch001-003/draft", "npc_brannoc_ironvein",
                               "Brannoc Ironvein", [], [], "", [], full=True)


def test_a_citation_to_a_target_no_span_supplies_fails(drafted):
    root, plan, fake, out = drafted
    draft = root / BRANNOC
    draft.write_text(draft.read_text().replace("[ch 003 / 003.01]", "[ch 003 / 003.02]", 1), encoding="utf-8")
    res = npc_update.verify(root, plan, subjects=["Brannoc Ironvein"])["Brannoc Ironvein"]
    assert res["verdict"] == "fail" and res["counts"]["invalid"] >= 1  # 003.02 is in no supplied span


def test_no_api_accepts_a_verdict_and_a_handwritten_pass_is_overwritten(drafted):
    root, plan, fake, out = drafted
    with pytest.raises(TypeError):
        npc_update.verify(root, plan, verdict="pass")
    with pytest.raises(TypeError):
        npc_update.verify_text(root, "x", "x", [], [], "", [], verdict="pass")
    draft = root / BRANNOC
    draft.write_text(draft.read_text().replace("[ch 003 / 003.01]", "[ch 003 / 003.09]", 1), encoding="utf-8")
    vmd = draft.with_suffix(".verify.md")
    vmd.write_text("# Verification: X\n\n**Verdict: pass**\n", encoding="utf-8")
    assert npc_publish.read_verdict(draft.parent.parent, "npc_brannoc_ironvein") == "pass"
    npc_update.verify(root, plan)
    assert npc_publish.read_verdict(draft.parent.parent, "npc_brannoc_ironvein") == "fail"


def test_sparse_evidence_targets_are_exactly_the_spans():
    sp = EvidenceSpan(3, "scene", "003.01", "text", "p", "a" * 64, "new")
    assert SparseEvidence([sp]).targets == {(3, "003.01")}  # no (3, "entry") invented from chapter membership


def test_edited_source_after_planning_is_refused_as_stale(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    src = root / "docs/summaries/003-the-new-fire.md"
    src.write_text(src.read_text() + "\nedited\n")
    with pytest.raises(DeltaRefusal) as e:
        npc_update.draft(root, plan)
    assert e.value.exit_code == 3


def test_dump_only_makes_no_model_call(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    fake = install_fake(monkeypatch)
    out = npc_update.draft(root, plan, dump_only=True)
    assert out.exit_code == 0 and fake.prompts == []
    assert list((out.range_dir / "runs").glob("*/*.user.md"))


def test_repair_required_baseline_blocks_drafting(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    f = root / "docs/npcs/brannoc-ironvein.md"
    f.write_text(f.read_text() + "\nhand edit\n")
    with pytest.raises(DeltaRefusal, match="repair_required"):
        npc_update.draft(root, plan)


# ── T054: per-member receipts and reconciliation ────────────────────────────


def _signed_world(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    out = npc_update.draft(root, plan)
    sign_drafts(root, out.range_dir, {"npc_tobin_fenwick": "Tobin Fenwick",
                                      "npc_brannoc_ironvein": "Brannoc Ironvein"}, capsys)
    return root, plan, out


def test_crash_between_target_write_and_log_update_is_reconciled_not_rewritten(tmp_path, monkeypatch, capsys):
    root, plan, out = _signed_world(tmp_path, monkeypatch, capsys)
    members = ["Tobin Fenwick", "Brannoc Ironvein"]
    pv = npc_update.publish_preview(root, plan, members)["preview_sha256"]
    real = npc_publish.write_publish_log
    calls = {"n": 0}

    def crash_on_first(npc_root, log):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(npc_root, log)

    monkeypatch.setattr(npc_publish, "write_publish_log", crash_on_first)
    first = npc_update.publish(root, plan, members, pv)
    by = {r.slug: r for r in first}
    # independent members: the first failed after writing its target, the second still published
    assert by["tobin-fenwick"].outcome == "failed" and by["brannoc-ironvein"].outcome == "published"
    tobin = root / "docs/npcs/tobin-fenwick.md"
    assert tobin.is_file()
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert "tobin-fenwick" not in log or log["tobin-fenwick"]["range"] != "ch001-003"
    written = tobin.read_bytes()
    rd = npc_update.receipts_dir(root, plan.plan_id)
    assert json.loads((rd / "tobin-fenwick.json").read_text())["outcome"] == "failed"

    monkeypatch.setattr(npc_publish, "write_publish_log", real)
    done = npc_publish.reconcile(root, root / "docs/npcs/summary_native/ch001-003", rd)
    assert [(r["slug"], r["outcome"], r["reconciled"]) for r in done] == [("tobin-fenwick", "published", True)]
    assert tobin.read_bytes() == written  # the target was not rewritten
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    assert log["tobin-fenwick"]["range"] == "ch001-003"
    assert json.loads((rd / "tobin-fenwick.json").read_text())["outcome"] == "published"
    assert npc_publish.reconcile(root, root / "docs/npcs/summary_native/ch001-003", rd) == []  # idempotent

    # publishing again changes nothing and still gives each member a receipt
    pv2 = npc_update.publish_preview(root, plan, members)["preview_sha256"]
    again = npc_update.publish(root, plan, members, pv2)
    assert [r.outcome for r in again] == ["published", "published"]
    assert tobin.read_bytes() == written
    assert all(r.receipt and r.receipt["idempotent"] for r in again)


def test_interrupted_before_the_target_write_reconciles_to_failed(tmp_path, monkeypatch, capsys):
    root, plan, out = _signed_world(tmp_path, monkeypatch, capsys)
    rd = npc_update.receipts_dir(root, plan.plan_id)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "tobin-fenwick.intent.json").write_text(json.dumps(
        {"intent_id": "x", "slug": "tobin-fenwick", "published_sha256": "f" * 64, "log_entry": {}}))
    done = npc_publish.reconcile(root, out.range_dir, rd)
    assert done[0]["outcome"] == "failed" and not (root / "docs/npcs/tobin-fenwick.md").exists()


def test_a_held_member_gets_a_held_receipt_with_hashes(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    census_for(root, plan)
    install_fake(monkeypatch)
    out = npc_update.draft(root, plan)
    handoff_only(root, capsys, plan)  # setup: the review binding publication requires; nothing is approved
    pv = npc_update.publish_preview(root, plan, ["Tobin Fenwick"])["preview_sha256"]
    (res,) = npc_update.publish(root, plan, ["Tobin Fenwick"], pv)  # no sign-off was ever recorded
    assert res.outcome == "held" and res.receipt["outcome"] == "held"
    assert res.receipt["draft_sha256"] and res.receipt["body_sha256"]
    assert not (root / "docs/npcs/tobin-fenwick.md").exists()
