"""Spec 040 code-review fixes: one regression test per verified finding (see the commit message).

Everything but the unit tests runs on the real synthetic fixture (``tests/_rebase_fixture.py``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipelines.summary_native import cli
from pipelines.summary_native.delta import grounding_edits, rebase, rebase_impact
from pipelines.summary_native.delta.errors import DeltaRefusal
from tests import _rebase_fixture as rf
from tests.test_rebase_us1 import affected, forbid_models, prepare, repair, run


@pytest.fixture
def fx(tmp_path, capsys, monkeypatch):
    return rf.build(tmp_path, capsys, monkeypatch)


def decide_argv(plan_id, review, *pairs):
    argv = ["rebase", "decide", "--plan", plan_id, "--reviewer", "gm", "--reason", "read by the GM"]
    for p in pairs:
        argv += ["--source-decision", p]
    for m in review["unknown_members"]:
        argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
    return argv


# --------------------------------------------------------------------------- finding 1

def test_a_line_citing_two_corrected_chapters_is_affected_for_each_of_them():
    old3 = b"# Chapter 3\n\n## Scenes\n\n### 003.01 A\n\nold three\n"
    old5 = b"# Chapter 5\n\n## Scenes\n\n### 005.01 B\n\nold five\n"
    sources = {c: rebase_impact.SourceImpact(
        chapter=c, path=f"p{c}", old_sha256="0" * 64, new_sha256="1" * 64,
        entries=rebase_impact.diff_entries(old, old.replace(b"old", b"new")), diff_ref="d")
        for c, old in ((3, old3), (5, old5))}
    line = b"Both hold. [ch 003 / 003.01] [ch 005 / 005.01]\n"
    found = list(rebase_impact._scan_document("world_state", line, sources, "baseline"))
    assert sorted(l.chapter for l in found) == [3, 5] and len({l.line_id for l in found}) == 1
    impact = rebase_impact.ImpactSet(sources=list(sources.values()), affected_lines=found, affected_annotations=[],
                                     unknown_members=[], followup_consumers=[])
    state = SimpleNamespace(impact=impact)
    with pytest.raises(DeltaRefusal, match="REBASE_SEMANTIC_CHANGE"):  # ch5 is not excused by ch3's reject
        rebase.check_rulings(state, {3: "reject", 5: "adopt-unaffected"}, set())


def test_single_chapter_lines_keep_one_record(fx, capsys):
    review = run(capsys, fx.root, "rebase", "show", "--plan",
                 prepare(capsys, fx, [5])["data"]["plan_id"])["data"]
    ids = [l["line_id"] for l in review["affected_lines"]]
    assert len(ids) == len(set(ids))  # the multi-record shape only appears for multi-chapter citations


# --------------------------------------------------------------------------- findings 2 and 3

def test_a_repair_on_a_rejected_chapter_is_refused_and_a_rejected_repair_can_be_replaced(fx, capsys, monkeypatch):
    forbid_models(monkeypatch)
    plan_id = prepare(capsys, fx, [4, 5])["data"]["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    line = affected(review, 5)[0]
    first = repair(capsys, fx, plan_id, line, "The company holds three prisoners. [ch 005 / 005.01]")
    run(capsys, fx.root, "grounding", "decide", first["proposal_id"], "--plan", plan_id, "--decision", "approve",
        "--reviewer", "gm")
    run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--hold-entry", "4/004.01", "--reviewer", "gm",
        "--reason", "held")
    # ch5 rejected while one of its lines carries an APPROVED repair: refused, not silently dropped
    refused = run(capsys, fx.root, *decide_argv(plan_id, review, "4=adopt-with-repairs", "5=reject"), expect=1)
    assert refused["code"] == "REBASE_REJECTED_REPAIR" and line["line_id"] in refused["message"]
    # the GM withdraws that repair (reject), and the decision is then recorded
    run(capsys, fx.root, "grounding", "decide", first["proposal_id"], "--plan", plan_id, "--decision", "reject",
        "--reviewer", "gm")
    assert run(capsys, fx.root, *decide_argv(plan_id, review, "4=adopt-with-repairs", "5=reject"))["data"]["written"]
    # finding 3: after the rejection a NEW repair for the same line is allowed (it supersedes the rejected one) ...
    again = repair(capsys, fx, plan_id, line, "The company now holds three prisoners. [ch 005 / 005.01]")
    live = grounding_edits.load_proposals(fx.root, plan_id).proposals
    assert [p.proposal_id for p in live if p.target_id == again["target_id"]] == [again["proposal_id"]]
    # ... and a LIVE (undecided) proposal still makes a further one a duplicate
    dup = run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--line", line["line_id"], "--text", "x. [ch 005 / 005.01]",
              "--reason", "x", "--reviewer", "gm", expect=1)
    assert "duplicate target" in dup["message"]


def test_hold_entry_holds_a_line_whose_only_proposal_was_rejected(fx, capsys, monkeypatch):
    forbid_models(monkeypatch)
    plan_id = prepare(capsys, fx, [5])["data"]["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    line = affected(review, 5)[0]
    first = repair(capsys, fx, plan_id, line, "The company holds three prisoners. [ch 005 / 005.01]")
    run(capsys, fx.root, "grounding", "decide", first["proposal_id"], "--plan", plan_id, "--decision", "reject",
        "--reviewer", "gm")
    held = run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--hold-entry", "5/005.01", "--reviewer", "gm",
               "--reason", "entry corrected")["data"]
    assert line["line_id"] in held["held_lines"] and not held["skipped_already_proposed"]
    states = {l["line_id"]: l["state"] for l in run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]["affected_lines"]}
    assert states[line["line_id"]] == "held"


# --------------------------------------------------------------------------- finding 7

def test_a_rejected_chapter_whose_cited_scene_was_removed_does_not_block_the_check(fx, capsys, monkeypatch):
    forbid_models(monkeypatch)
    ch5 = fx.paths[5]
    ch5.write_text(ch5.read_text(encoding="utf-8").replace("### 005.01 The Far Marker", "### 005.09 The Far Marker"),
                   encoding="utf-8")
    plan_id = prepare(capsys, fx, [4, 5])["data"]["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    assert any(l["reason"] == "removed" for l in affected(review, 5))
    run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--hold-entry", "4/004.01", "--reviewer", "gm",
        "--reason", "held")
    run(capsys, fx.root, *decide_argv(plan_id, review, "4=adopt-with-repairs", "5=reject"))
    code = cli.main(["delta", "grounding", "check", "--plan", plan_id, "--campaign-dir", str(fx.root), "--json"])
    out = capsys.readouterr().out
    assert code == 0 and "has no baseline custody" not in out, out[-1500:]
