"""Spec 040 US1 (T018): inspect, prepare, repair, hold, propose and decide on the synthetic rebase fixture.

The fixture is the real publish path (``tests/_rebase_fixture.py``); nothing about claims, review bindings or
promotion is mocked.  A model call anywhere but ``rebase propose`` is a failure: after the fixture is built the
model entry points are replaced by a counter that raises.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipelines.summary_native import cli
from pipelines.summary_native.delta import (
    custody_store, grounding_check, grounding_edits, rebase, rebase_impact, rebase_propose,
)
from tests import _rebase_fixture as rf


class Boom:
    """Counts every model call and raises: the tests that must make none install this."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("a model call was made")


def forbid_models(monkeypatch) -> Boom:
    boom = Boom()
    import campaignlib
    for module in (campaignlib, grounding_edits, grounding_check, rebase_propose):
        for name in ("stream_api", "call_api", "make_client", "client_from_args"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, boom)
    return boom


def run(capsys, root, *argv, expect=0):
    code = cli.main(["delta", *argv, "--campaign-dir", str(root), "--json"])
    out = capsys.readouterr()
    assert code == expect, (code, out.out, out.err)
    return json.loads(out.out) if out.out.strip() else {}


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.relative_to(root).parts}


def prepare(capsys, fx, chapters, *extra, expect=0):
    argv = ["rebase", "prepare"]
    for c in chapters:
        argv += ["--source", str(fx.paths[c])]
    return run(capsys, fx.root, *argv, *extra, expect=expect)


@pytest.fixture
def fx(tmp_path, capsys, monkeypatch):
    return rf.build(tmp_path, capsys, monkeypatch)


# --------------------------------------------------------------------------- inspect

def test_inspect_lists_exactly_the_corrected_chapters_and_writes_nothing(fx, capsys, monkeypatch):
    boom = forbid_models(monkeypatch)
    before = tree(fx.root)
    out = run(capsys, fx.root, "rebase", "inspect")
    assert out["ok"] is True and out["code"] == "OK"
    report = out["data"]
    assert [e["chapter"] for e in report["stale"]] == [2, 3, 4, 5]  # SC-008
    assert report["checked"] == 5 and report["integrity_reads"] == 5 and report["call_counts"]["model"] == 0
    for e in report["stale"]:
        assert e["expected_sha256"] == fx.old_sha[e["chapter"]] and e["actual_sha256"] == fx.new_sha[e["chapter"]]
        providers = {p["provider"]: p["available"] for p in e["old_bytes"]}
        assert providers["git"] is True and providers["snapshot"] is False  # nothing is stored until prepare
    # the pin is attributed to the generation of the delta chain that recorded it, not the newest directory
    pinned = {e["chapter"]: e["pinned_by"] for e in report["stale"]}
    assert pinned[2] == pinned[3] == "legacy-fixture" and pinned[4] != pinned[5] != "legacy-fixture"
    assert report["generation_ref"].startswith(pinned[5])
    assert tree(fx.root) == before  # no file written, none changed
    assert boom.calls == 0


def test_inspect_reports_the_plans_baseline(fx, capsys):
    report = run(capsys, fx.root, "rebase", "inspect", "--plan", fx.pending_plan_id)["data"]
    assert report["plan_ref"] == fx.pending_plan_id and report["plan_baseline_is_active"] is True


def test_selection_rules_and_an_unselected_stale_source_stays_reported(fx, capsys):
    run(capsys, fx.root, "rebase", "prepare", expect=2)  # no --source: exit 2, no default to "all"
    err = run(capsys, fx.root, "rebase", "prepare", "--source", str(fx.paths[1]), expect=2)
    assert err["code"] == "REBASE_NOTHING_TO_REBASE"  # ch1 matches its pin
    prepare(capsys, fx, [5])
    after = run(capsys, fx.root, "rebase", "inspect")["data"]
    assert [e["chapter"] for e in after["stale"]] == [2, 3, 4, 5]  # selecting ch5 does not hide 2-4
    assert {p["provider"]: p["available"] for p in after["stale"][3]["old_bytes"]}["snapshot"] is True


# --------------------------------------------------------------------------- prepare

def test_prepare_snapshots_verify_summaries_untouched_and_impact_is_flagged(fx, capsys, monkeypatch):
    boom = forbid_models(monkeypatch)
    before = tree(fx.root)
    out = prepare(capsys, fx, [2, 3, 4, 5])["data"]
    assert out["created"] is True and out["call_counts"]["model"] == 0 and boom.calls == 0
    after = tree(fx.root)
    for c in fx.corrected:  # authored summaries are byte-identical
        assert after[fx.paths[c].relative_to(fx.root).as_posix()] == fx.new_sha[c]
    assert all(after[k] == before[k] for k in before)  # nothing pre-existing changed (generations included)
    for src in out["sources"]:
        old = custody_store.get(fx.root, src["old_sha256"])
        new = custody_store.get(fx.root, src["new_sha256"])
        assert hashlib.sha256(old).hexdigest() == fx.old_sha[src["chapter"]]
        assert hashlib.sha256(new).hexdigest() == fx.new_sha[src["chapter"]]
        assert src["old_bytes_provider"] == "git"
    plan_id = out["plan_id"]
    plan = json.loads((fx.root / "docs/summaries/delta/plans" / f"{plan_id}-r1.json").read_text())
    assert plan["kind"] == "rebase" and plan["rebase_id"] == out["rebase_id"] and plan["products"] == ["grounding"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    assert {l["chapter"] for l in review["affected_lines"]} == {2, 3, 4, 5}
    ws = {l["chapter"] for l in review["affected_lines"] if l["document"] == "world_state"}
    assert ws == {2, 4, 5}
    unknown = {m["member"]: m["reason"] for m in review["unknown_members"]}
    assert unknown["canon_events_timeline.md"] == "no_citations"  # never guessed at: it is flagged unknown
    assert unknown["reference/npcs.md"] == "cites_selected"
    text = (fx.root / review["review"]).read_text()
    assert "## Unknown-impact members" in text and "```diff" in text
    # idempotent: identical inputs are a no-op returning the same ids and writing nothing
    snapshot = tree(fx.root)
    again = prepare(capsys, fx, [5, 4, 3, 2])["data"]
    assert again["created"] is False and again["rebase_id"] == out["rebase_id"] and again["plan_id"] == plan_id
    assert tree(fx.root) == snapshot


def test_prepare_with_for_plan_adds_the_pending_candidates_to_the_impact(fx, capsys):
    out = prepare(capsys, fx, [5], "--for-plan", fx.pending_plan_id)["data"]
    assert out["created"] is True
    review = run(capsys, fx.root, "rebase", "show", "--plan", out["plan_id"])["data"]
    assert {l["origin"] for l in review["affected_lines"]} == {"baseline"}  # ch6 candidate cites only ch6
    run(capsys, fx.root, "rebase", "prepare", "--source", str(fx.paths[5]), "--for-plan", "plan-nope", expect=2)


# --------------------------------------------------------------------------- decide, repair, hold

def affected(review, chapter, document="world_state"):
    return [l for l in review["affected_lines"] if l["chapter"] == chapter and l["document"] == document]


def repair(capsys, fx, plan_id, line, text):
    return run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--line", line["line_id"], "--text", text,
               "--reason", "the corrected chapter says otherwise", "--reviewer", "gm-test")["data"]


def test_decisions_are_refused_until_every_affected_line_is_ruled(fx, capsys, monkeypatch):
    boom = forbid_models(monkeypatch)
    out = prepare(capsys, fx, [2, 3, 4, 5])["data"]
    plan_id = out["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]

    def decide(*pairs, reviewer="gm-test", reason="checked by the GM", expect=0, members=True):
        argv = ["rebase", "decide", "--plan", plan_id]
        if reviewer:
            argv += ["--reviewer", reviewer]
        for p in pairs:
            argv += ["--source-decision", p]
        if members:
            for m in review["unknown_members"]:
                argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
        if reason:
            argv += ["--reason", reason]
        return run(capsys, fx.root, *argv, expect=expect)

    # SC-002: a semantic change cannot be adopted by hash alone
    err = decide("5=adopt-unaffected", "2=adopt-with-repairs", "3=reject", "4=adopt-with-repairs", expect=1)
    assert err["code"] == "REBASE_SEMANTIC_CHANGE" and "world_state#" in err["message"]
    # a missing reviewer is a usage error
    assert decide("5=adopt-with-repairs", reviewer=None, expect=2)["code"] == "USAGE"
    # a reject needs a reason
    assert decide("3=reject", reason=None, expect=2)["ok"] is False
    # affected lines without a repair or hold
    plan_sources = ["2=adopt-with-repairs", "3=reject", "4=adopt-with-repairs", "5=adopt-with-repairs"]
    assert decide(*plan_sources, expect=1)["code"] == "REBASE_UNRULED_IMPACT"
    # --- repairs: GM-authored drafts through the grounding edit model
    first = {c: affected(review, c) for c in (2, 4, 5)}
    p2 = repair(capsys, fx, plan_id, first[2][0], "The company opens the sealed gate for 40 gold. [ch 002 / 002.01]")
    assert p2["origin"] == "gm" and p2["status"] == "draft"
    p4 = repair(capsys, fx, plan_id, first[4][0], "The road is open once Hale tells the company. [ch 004 / 004.01]")
    p5a = repair(capsys, fx, plan_id, first[5][0], "The company holds three prisoners. [ch 005 / 005.01]")
    p5b = repair(capsys, fx, plan_id, first[5][1], "The far marker stands. [ch 005 / 005.01]")
    proposals = grounding_edits.load_proposals(fx.root, plan_id)
    assert len(proposals.proposals) == 4 and all(p.origin == "gm" and p.category == "source_correction"
                                                 for p in proposals.proposals)
    # drafts are not rulings
    assert decide(*plan_sources, expect=1)["code"] == "REBASE_UNRULED_IMPACT"
    for pid in (p2, p4, p5a):
        run(capsys, fx.root, "grounding", "decide", pid["proposal_id"], "--plan", plan_id, "--decision", "approve",
            "--reviewer", "gm-test")
    # a second repair for the same line is refused by the existing duplicate/overlap validation
    dup = run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--line", first[5][0]["line_id"],
              "--text", "Another wording. [ch 005 / 005.01]", "--reason", "x", "--reviewer", "gm-test", expect=1)
    assert "duplicate target" in dup["message"]
    # earlier approvals survived adding a later repair; p5b is still only a draft
    assert decide(*plan_sources, expect=1)["code"] == "REBASE_UNRULED_IMPACT"
    # the hold: the line stays byte-identical and one marker line follows it
    run(capsys, fx.root, "grounding", "decide", p5b["proposal_id"], "--plan", plan_id, "--decision", "hold",
        "--reviewer", "gm-test")
    docs = rebase.baseline_docs(rebase.load_state(fx.root, plan_id))
    built = grounding_edits.reconstruct_for_plan(fx.root, plan_id, docs)["world_state"].decode().splitlines()
    original = docs["world_state"].decode().splitlines()
    held_line = original[first[5][1]["line_no"] - 1]
    marker = f"⚠ held: superseded by correction to ch 005 — see rebase {out['rebase_id']}"
    at = built.index(held_line)
    assert built[at + 1] == marker and built.count(marker) == 1
    assert len([l for l in built if l != marker]) == len(original)
    # now every baseline line is ruled: the decision records, binds the inputs, and is append-only
    done = decide(*plan_sources)["data"]
    assert done["revision"] == 1 and done["written"] is True and done["reviewer"] == "gm-test"
    assert done["bound"]["edits_sha256"] == rebase.edits_sha256(fx.root, plan_id)
    assert done["bound"]["impact_sha256"] == out["impact"]["impact_sha256"]
    assert done["bound"]["snapshots_sha256"] == out["records"]["snapshots_sha256"]
    assert done["bound"]["baseline_ref"] == out["baseline_ref"]
    assert done["sources"]["3"]["decision"] == "reject" and done["sources"]["3"]["reason"]
    assert set(done["unknown_members"]) == {m["member"] for m in review["unknown_members"]}
    assert decide(*plan_sources)["data"]["written"] is False
    files = sorted(p.name for p in (fx.root / out["records"]["directory"]).glob("decisions-r*.json"))
    assert files == ["decisions-r1.json"]
    shown = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    states = [l["state"] for l in shown["affected_lines"] if l["document"] == "world_state"]
    assert sorted(states) == ["approved", "approved", "approved", "held"]
    assert all(m["ruling"]["decision"] == "attested-unaffected" for m in shown["unknown_members"])
    now = tree(fx.root)
    for c in fx.corrected:
        assert now[fx.paths[c].relative_to(fx.root).as_posix()] == fx.new_sha[c]
    assert boom.calls == 0  # no model anywhere in repair/decide/show


def test_a_repair_of_an_unknown_line_is_refused_and_needs_a_reviewer(fx, capsys):
    out = prepare(capsys, fx, [5])["data"]
    base = ["rebase", "repair", "--plan", out["plan_id"], "--line", "world_state#000000000000@1",
            "--text", "x", "--reason", "r"]
    assert run(capsys, fx.root, *base, "--reviewer", "gm", expect=2)["code"] == "REBASE_UNKNOWN_LINE"
    assert run(capsys, fx.root, *base, expect=2)["code"] == "USAGE"  # no reviewer


# --------------------------------------------------------------------------- bulk hold by entry

def test_hold_entry_holds_every_affected_line_of_that_entry_explicitly(fx, capsys, monkeypatch):
    boom = forbid_models(monkeypatch)
    out = prepare(capsys, fx, [3, 5])["data"]
    plan_id = out["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    base = ["rebase", "repair", "--plan", plan_id, "--hold-entry", "3/003.01"]
    # reviewer and reason are required, never implicit
    assert run(capsys, fx.root, *base, "--reason", "r", expect=2)["code"] == "USAGE"
    assert run(capsys, fx.root, *base, "--reviewer", "gm", expect=2)["code"] == "USAGE"
    assert run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--hold-entry", "three", "--reason", "r",
               "--reviewer", "gm", expect=2)["ok"] is False
    assert run(capsys, fx.root, *base, "--reason", "r", "--reviewer", "gm", "--line", "x", expect=2)["ok"] is False
    unknown = run(capsys, fx.root, "rebase", "repair", "--plan", plan_id, "--hold-entry", "3/003.99", "--reason", "r",
                  "--reviewer", "gm", expect=2)
    assert unknown["code"] == "REBASE_UNKNOWN_ENTRY" and "3/003.01" in unknown["message"]
    assert grounding_edits.load_decisions(fx.root, plan_id) is None  # every refusal wrote nothing
    wanted = [l["line_id"] for l in review["affected_lines"] if l["chapter"] == 3 and l["entry"] == "003.01"
              and l["origin"] == "baseline"]
    other = [l["line_id"] for l in review["affected_lines"] if l["chapter"] != 3]
    assert len(wanted) == 1450
    # one line was already given a repair draft: it is left alone and reported, not silently held
    first = repair(capsys, fx, plan_id, next(l for l in review["affected_lines"] if l["line_id"] == wanted[0]),
                   "Fixture planning detail, corrected. [ch 003 / 003.01]")
    held = run(capsys, fx.root, *base, "--reason", "entry corrected", "--reviewer", "gm")["data"]
    assert held["count"] == 1449 and held["skipped_already_proposed"] == [wanted[0]]
    assert sorted(held["held_lines"]) == sorted(wanted[1:]) and not set(held["held_lines"]) & set(other)
    proposals = grounding_edits.load_proposals(fx.root, plan_id)
    decisions = grounding_edits.current_decisions(fx.root, plan_id, proposals)
    by_id = {p.proposal_id: p for p in proposals.proposals}
    mine = {pid: d for pid, d in decisions.items() if d.decision == "hold"}
    assert len(mine) == 1449 and all(d.reviewer == "gm" and "entry corrected" in d.reason for d in mine.values())
    assert first["proposal_id"] not in decisions  # the repair draft is still undecided
    assert all(p.hold_marker for pid, p in by_id.items() if pid in mine)
    assert len({d.reason for d in mine.values()}) == 1449  # each decision names its own line
    record = json.loads((fx.root / held["record"]).read_text())
    assert record["held_lines"] == held["held_lines"] and record["reviewer"] == "gm"
    shown = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    states = {l["line_id"]: l["state"] for l in shown["affected_lines"]}
    assert {states[i] for i in held["held_lines"]} == {"held"} and states[wanted[0]] == "unruled"
    assert {states[i] for i in other} == {"unruled"}  # lines of other entries and chapters are untouched
    assert boom.calls == 0


# --------------------------------------------------------------------------- SC-003

def test_whitespace_only_correction_is_adopted_unaffected_with_zero_model_calls(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch, whitespace_ch1=True)
    boom = forbid_models(monkeypatch)
    inspected = run(capsys, fx.root, "rebase", "inspect")["data"]
    assert [e["chapter"] for e in inspected["stale"]] == [1]
    out = prepare(capsys, fx, [1])["data"]
    assert out["impact"]["affected_lines"] == 0 and out["impact"]["affected_annotations"] == 0
    review = run(capsys, fx.root, "rebase", "show", "--plan", out["plan_id"])["data"]
    assert review["affected_lines"] == [] and review["unknown_members"]  # members still need a ruling
    argv = ["rebase", "decide", "--plan", out["plan_id"], "--reviewer", "gm-test", "--source-decision",
            "1=adopt-unaffected", "--reason", "whitespace only; the GM read the diff"]
    # unknown-impact members block until ruled, even for a clean source
    assert run(capsys, fx.root, *argv, expect=1)["code"] == "REBASE_UNRULED_IMPACT"
    for m in review["unknown_members"]:
        argv += ["--member-decision", f"{m['member']}=attested-unaffected"]
    done = run(capsys, fx.root, *argv)["data"]
    assert done["sources"]["1"]["decision"] == "adopt-unaffected" and boom.calls == 0
    assert run(capsys, fx.root, "rebase", "inspect")["data"]["stale"][0]["chapter"] == 1  # unchanged until applied


# --------------------------------------------------------------------------- propose (the one model call)

def test_propose_sends_only_the_affected_lines_diffs_and_annotations_and_approves_nothing(fx, capsys, monkeypatch):
    out = prepare(capsys, fx, [2, 4, 5])["data"]
    plan_id = out["plan_id"]
    review = run(capsys, fx.root, "rebase", "show", "--plan", plan_id)["data"]
    lines = [l for l in review["affected_lines"] if l["origin"] == "baseline"]
    seen = {"calls": 0, "user": None}

    def fake_stream(client, system, user, model, **kw):
        seen["calls"] += 1
        seen["user"] = user
        return json.dumps({"repairs": [
            {"line_id": lines[0]["line_id"], "after_text": "A drafted line. [ch 002 / 002.01]", "reason": "diff"},
            {"line_id": "world_state#feedfeedfeed@1", "after_text": "x", "reason": "invented id"},
            {"line_id": lines[1]["line_id"], "after_text": "two\nlines", "reason": "bad shape"}]})

    monkeypatch.setattr(rebase_propose, "stream_api", fake_stream)
    monkeypatch.setattr(rebase_propose, "client_from_args", lambda *a, **k: object())
    data = run(capsys, fx.root, "rebase", "propose", "--plan", plan_id)["data"]
    assert seen["calls"] == 1 and data["model_calls"] == 1 and data["call_counts"]["model"] == 1
    assert data["status"] == "draft" and data["approved"] == 0 and len(data["proposals"]) == 1
    assert {r["line_id"] for r in data["rejected"]} == {"world_state#feedfeedfeed@1", lines[1]["line_id"]}
    sources = data["model_input_sources"]
    assert sources["affected_lines"] == [l["line_id"] for l in lines] and sources["entry_diffs"] == [2, 4, 5]
    user = seen["user"]
    assert "fee of 40 gold" in user  # the corrected entry is shown
    assert "Reviewed fixture prose" not in user  # the other document lines are not
    assert "ch 003" not in user  # an unselected chapter is never shown
    record = json.loads((fx.root / out["records"]["directory"] / "propose-r1.json").read_text())
    assert record["model_input_sources"] == sources and record["model_calls"] == 1
    proposals = grounding_edits.load_proposals(fx.root, plan_id)
    assert [p.origin for p in proposals.proposals] == ["model"] and proposals.status == "draft"
    assert grounding_edits.load_decisions(fx.root, plan_id) is None  # nothing approved
    # a line that already has a draft is not offered again
    monkeypatch.setattr(rebase_propose, "stream_api", lambda *a, **k: json.dumps({"repairs": []}))
    again = run(capsys, fx.root, "rebase", "propose", "--plan", plan_id)["data"]
    assert lines[0]["line_id"] not in again["model_input_sources"]["affected_lines"]


# --------------------------------------------------------------------------- units

def test_entries_are_cut_by_scene_and_section_and_whitespace_marks_only_its_entry():
    old = (b"# Chapter 1\n\n## Scenes\n\n### 001.01 A\n\nText.\n\n## NPCs\n\n### Warden Hale\n\nKeeps it.\n\n"
           b"## Memorable Moments\n\n> q\n")
    new = old.replace(b"Keeps it.\n", b"Keeps it.  \n")
    diff = {e.entry: e.status for e in rebase_impact.diff_entries(old, new)}
    assert diff["npcs"] == diff["warden hale"] == "changed"
    assert diff["001.01"] == diff["moment"] == diff["_header"] == "unchanged"
    moved = {e.entry: e.status for e in rebase_impact.diff_entries(old, old.replace(b"### 001.01 A", b"### 001.09 A"))}
    assert moved["001.01"] == "removed" and moved["001.09"] == "added"


def test_line_ids_are_stable_against_line_number_shifts():
    a = rebase_impact.indexed_lines("world_state", b"x\ny\nx\n")
    b = rebase_impact.indexed_lines("world_state", b"new\nx\ny\nx\n")
    assert [i for i, _n, _l in a] == [i for i, _n, _l in b[1:]] and a[0][0].endswith("@1") and a[2][0].endswith("@2")
    assert rebase_impact.find_line({"world_state": b"new\nx\ny\nx\n"}, a[2][0])[1] == 4


def test_a_hold_needs_a_marker_and_leaves_old_proposals_serialisation_unchanged():
    docs = {"world_state": b"keep me\nother\n"}
    tid = grounding_edits.line_target_id("world_state", 1, b"keep me\n")
    plain = grounding_edits.make_proposal(docs, target_id=tid, after_text="x", category="new_information",
                                          rationale="r", support="s")
    assert set(plain.model_dump(mode="json")) == {"proposal_id", "target_id", "before_sha256", "after_text",
                                                  "category", "rationale", "support", "dependent_checks"}
    held = plain.model_copy(update={"hold_marker": "M"})
    hold = grounding_edits.DecisionEntry(decision="hold", reviewer="r")
    with pytest.raises(Exception, match="cannot be held"):
        grounding_edits.reconstruct(docs, [plain], {plain.proposal_id: hold})
    assert grounding_edits.reconstruct(docs, [held], {held.proposal_id: hold})["world_state"] == b"keep me\nM\nother\n"
    noeol = {"world_state": b"keep me"}
    held2 = grounding_edits.make_proposal(
        noeol, target_id=grounding_edits.line_target_id("world_state", 1, b"keep me"), after_text="x",
        category="source_correction", rationale="r", support="s").model_copy(update={"hold_marker": "M"})
    assert grounding_edits.reconstruct(noeol, [held2], {held2.proposal_id: hold})["world_state"] == b"keep me\nM"


def test_annotations_are_affected_only_where_their_span_meets_a_change(tmp_path):
    old = b"line one\nline two\nline three\n"
    new = b"line one\nline TWO\nline three\n"
    sha = hashlib.sha256(old).hexdigest()
    assert rebase_impact.changed_old_regions(old, new) == [(9, 18)]
    gen = tmp_path / "g"
    (gen / "metadata").mkdir(parents=True)
    records = {"a": {"x": [{"occurrence_id": "hit", "source_sha256": sha, "start_byte": 10, "end_byte": 13},
                           {"occurrence_id": "miss", "source_sha256": sha, "start_byte": 0, "end_byte": 8},
                           {"occurrence_id": "other", "source_sha256": "0" * 64, "start_byte": 10, "end_byte": 13}]}}
    (gen / "metadata/a.json").write_text(json.dumps(records))
    manifest = type("M", (), {"retained_records": [type("R", (), {"retained_path": "metadata/a.json"})()]})()
    found = rebase_impact._annotations(gen, manifest, [rebase_impact.SourceChange(2, "p", old, new)])
    assert [a.annotation_id for a in found] == ["hit"] and found[0].chapter == 2
