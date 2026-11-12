"""Quickstart steps 2-5 through the real CLI: plan, sources, baseline, propose/decide/check."""

from __future__ import annotations

import hashlib
import json

import pytest

from pipelines.summary_native import cli
from pipelines.summary_native.delta import grounding_check, grounding_edits
from tests.support.delta_grounding_fixture import (
    add_new_chapter, edit_live_document, history_digests, make_grounding_campaign, published_path,
)


def run(capsys, root, *argv, expect=0):
    code = cli.main(["delta", *argv, "--campaign-dir", str(root), "--json"])
    out = capsys.readouterr()
    assert code == expect, (out.out, out.err)
    return json.loads(out.out)


@pytest.fixture
def campaign(tmp_path):
    root = make_grounding_campaign(tmp_path)
    return root, add_new_chapter(root)


def make_plan(capsys, root, source):
    return run(capsys, root, "plan", "--source", str(source), "--product", "grounding", "--stop", "prepare")


def test_plan_sources_and_empty_refusal(campaign, capsys):
    root, source = campaign
    code = cli.main(["delta", "plan", "--product", "grounding", "--campaign-dir", str(root), "--json"])
    err = capsys.readouterr()
    assert code == 2 and "no sources selected" in err.err and "no sources selected" in err.out
    assert not (root / "docs/summaries/delta").exists()  # no plan file written

    plan = make_plan(capsys, root, source)
    assert plan["stopping_point"] == "prepare" and plan["products"] == ["grounding"]
    assert plan["grounding_baseline_ref"].startswith("legacy-fixture@")
    assert (root / "docs/summaries/delta/plans" / f"{plan['plan_id']}-r1.json").is_file()

    sources = run(capsys, root, "sources", "--plan", plan["plan_id"])
    assert sources["read_counts"]["parsed_new"] == 1
    assert sources["read_counts"]["parsed_historical"] == 0
    assert sources["call_counts"]["model"] == 0
    assert (root / "docs/summaries/delta/sources" / f"{plan['plan_id']}.sources.json").is_file()


def test_baseline_status_drift_and_adopt(campaign, capsys):
    root, source = campaign
    plan = make_plan(capsys, root, source)
    status = run(capsys, root, "baseline", "status", "--plan", plan["plan_id"])
    assert status["status"] == "valid" and len(status["documents"]) == 4
    assert all(d["origin_sha256"] == d["live_sha256"] for d in status["documents"])

    edit_live_document(root, "world_state")
    status = run(capsys, root, "baseline", "status", "--plan", plan["plan_id"])
    assert status["status"] == "unadopted" and status["usable"] is False
    hunks = status["unresolved_hunks"]
    assert hunks == ["world_state#1", "world_state#2"]

    history = history_digests(root)
    # refuses while a hunk is unresolved (exit 1), then adopts
    code = cli.main(["delta", "baseline", "adopt", "--resolve", "world_state#1=accept",
                     "--campaign-dir", str(root)])
    assert code == 1
    capsys.readouterr()
    adopted = run(capsys, root, "baseline", "adopt", "--resolve", "world_state#1=accept",
                  "--resolve", "world_state#2=reject")
    assert adopted["revision"] == 1 and len(adopted["drift"]) == 2
    assert history_digests(root) == history
    assert run(capsys, root, "baseline", "status")["status"] == "adopted"


def test_propose_decide_check_end_to_end(campaign, capsys, monkeypatch):
    root, source = campaign
    plan = make_plan(capsys, root, source)
    pid = plan["plan_id"]
    target = next(t for t in grounding_edits.assign_targets(
        {"world_state": published_path(root, "world_state").read_bytes()})
        if "Reviewed fixture prose" in published_path(root, "world_state").read_text().splitlines()[t.start - 1]
        or "Existing reviewed live edit" in published_path(root, "world_state").read_text().splitlines()[t.start - 1])
    calls = []

    def fake_stream(client, system, user, model, **kw):
        calls.append(system[:30])
        if system.startswith("You propose"):
            return json.dumps({"proposals": [{
                "target_id": target.target_id, "after_text": "The Lantern Road is open to the eastern marker. [ch 004 / 004.01]",
                "category": "new_information", "rationale": "ch4 confirms the road",
                "support": "Warden Hale confirmed the Lantern Road is open past the eastern marker"}]})
        return json.dumps({"findings": []})

    monkeypatch.setattr(grounding_edits, "stream_api", fake_stream)
    monkeypatch.setattr(grounding_check, "stream_api", fake_stream)
    monkeypatch.setattr(grounding_edits, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(grounding_check, "client_from_args", lambda *a, **k: object())

    proposed = run(capsys, root, "grounding", "propose", "--plan", pid, "--backend", "anthropic", "--model", "m")
    assert proposed["status"] == "draft" and proposed["applied"] == 0 and len(proposed["proposals"]) == 1
    proposal_id = proposed["proposals"][0]["proposal_id"]
    assert proposed["proposals"][0]["before_sha256"] == target.sha256

    # undecided blocks the check (exit 1) and the live documents are untouched
    code = cli.main(["delta", "grounding", "check", "--plan", pid, "--campaign-dir", str(root), "--json"])
    assert code == 1 and proposal_id in capsys.readouterr().err

    decided = run(capsys, root, "grounding", "decide", proposal_id, "--plan", pid, "--decision", "approve",
                  "--reviewer", "gm")
    assert decided["decisions"][proposal_id]["decision"] == "approve"
    assert decided["decisions"][proposal_id]["reviewer"] == "gm"   # recorded in the decision file
    # a decision without a reviewer is refused (exit 2); there is no login-name default
    assert cli.main(["delta", "grounding", "decide", proposal_id, "--plan", pid, "--decision", "approve",
                     "--campaign-dir", str(root), "--json"]) == 2
    capsys.readouterr()
    # --plan may be omitted when exactly one plan owns the proposal
    run(capsys, root, "grounding", "decide", proposal_id, "--decision", "approve", "--reviewer", "gm")

    checked = run(capsys, root, "grounding", "check", "--plan", pid)
    assert checked["passed"] is True and checked["approval"] is None and checked["call_counts"]["model"] == 1
    assert calls[-1].startswith("You review")

    # untouched baseline bytes are identical after reconstruction
    from pipelines.summary_native.delta import baseline as bl
    docs = bl.baseline_documents(bl.bind(root), root)
    out = grounding_edits.reconstruct_for_plan(root, pid, docs)
    changed = [n for n in out if out[n] != docs[n]]
    assert changed == ["world_state"]
    old, new = docs["world_state"].splitlines(keepends=True), out["world_state"].splitlines(keepends=True)
    assert len(old) == len(new)
    assert [i for i, (a, b) in enumerate(zip(old, new)) if a != b] == [target.start - 1]
    assert checked["candidate_sha256"]["world_state"] == hashlib.sha256(out["world_state"]).hexdigest()


def test_stale_and_duplicate_proposals_are_rejected_through_the_cli_path(campaign, capsys, monkeypatch):
    root, source = campaign
    plan = make_plan(capsys, root, source)
    from pipelines.summary_native.delta import baseline as bl
    docs = bl.baseline_documents(bl.bind(root), root)
    t = grounding_edits.assign_targets(docs)[0]
    support = "Warden Hale confirmed the Lantern Road is open"
    item = {"target_id": t.target_id, "after_text": "x", "category": "new_information",
            "rationale": "r", "support": support}
    monkeypatch.setattr(grounding_edits, "stream_api",
                        lambda *a, **k: json.dumps({"proposals": [item, dict(item, after_text="y")]}))
    monkeypatch.setattr(grounding_edits, "client_from_args", lambda *a, **k: object())
    proposed = run(capsys, root, "grounding", "propose", "--plan", plan["plan_id"], "--model", "m")
    assert len(proposed["proposals"]) == 1
    assert [r["reason"] for r in proposed["rejected"]] == [f"duplicate target {t.target_id}"]

    saved = grounding_edits.load_proposals(root, plan["plan_id"])
    stale = saved.proposals[0].model_copy(update={"before_sha256": "0" * 64})
    with pytest.raises(Exception, match="stale before_sha256"):
        grounding_edits.validate_proposals(docs, [stale])
