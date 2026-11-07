"""T022: stable targets, host-side validation, byte-preserving reconstruction, checks (SC-002)."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native.delta import grounding_check as gc, grounding_edits as ge
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_USAGE, DeltaRefusal

WORLD = (
    "# World State\r\n"
    "\r\n"
    "## Factions\r\n"
    "The Lantern Guild buys blades. [ch 001 / 001.01]\r\n"
    "\r\n"
    "## Threads\n"
    "The forge is cold. [ch 002 / entry]\n"
    "| Thread | Status |\n"
    "|---|---|\n"
    "| Forge | cold |\n"
    "\n"
    "## Threads\n"
    "Second repeated heading body, no trailing newline"
).encode()
PARTY = b"# Party\n\nRuck is a smith.\nSister Ines keeps the ledger.\n"
DOCS = {"world_state": WORLD, "party": PARTY}
SOURCES = {"003.md": "Brannoc lit the forge at last. He restarts the forge.\nTobin offered coal."}


def tid(doc, n):
    return next(t.target_id for t in ge.assign_targets(DOCS) if t.document == doc and t.start == n)


def prop(doc, n, after, *, category="superseded_state", support="Brannoc lit the forge at last."):
    return ge.make_proposal(DOCS, target_id=tid(doc, n), after_text=after, category=category,
                            rationale="the forge restarted", support=support)


def test_target_ids_are_stable_and_content_addressed():
    first = [t.target_id for t in ge.assign_targets(DOCS)]
    assert first == [t.target_id for t in ge.assign_targets(dict(reversed(list(DOCS.items()))))]
    assert tid("party", 3).startswith("party:L3:") and len(set(first)) == len(first)
    changed = dict(DOCS, party=PARTY.replace(b"Ruck is a smith.", b"Ruck is a mason."))
    assert tid("party", 3) != next(t.target_id for t in ge.assign_targets(changed)
                                   if t.document == "party" and t.start == 3)
    assert ge.resolve_target(changed, tid("party", 3)) is None  # an id minted for another baseline


def test_before_digest_is_host_computed():
    p = prop("party", 3, "Ruck is a mason.\n")
    import hashlib
    assert p.before_sha256 == hashlib.sha256(b"Ruck is a smith.\n").hexdigest()
    assert "before" not in ge.SYSTEM_PROMPT.split("Reply with")[1].lower()


def test_validation_rejects_unknown_duplicate_overlapping_and_stale():
    good = prop("party", 3, "Ruck is a mason.\n")
    ge.validate_proposals(DOCS, [good])
    unknown = good.model_copy(update={"target_id": "party:L99:deadbeef"})
    dup = good.model_copy(update={"proposal_id": "p-other", "after_text": "x\n"})
    stale = good.model_copy(update={"before_sha256": "0" * 64})
    rng = ge.Proposal(**{**good.model_dump(), "proposal_id": "p-r",
                         "target_id": f"party:L3-L4:{tid('party', 3).rsplit(':', 1)[1]}",
                         "before_sha256": ge.resolve_target(
                             DOCS, f"party:L3-L4:{tid('party', 3).rsplit(':', 1)[1]}").sha256})
    other = prop("party", 4, "Ines keeps the book.\n")
    for bad, word in ((unknown, "unknown target"), (dup, "duplicate target"), (stale, "stale before_sha256")):
        with pytest.raises(DeltaRefusal, match=word) as exc:
            ge.validate_proposals(DOCS, [good, bad] if bad is not stale else [stale])
        assert exc.value.exit_code == EXIT_REFUSAL
    with pytest.raises(DeltaRefusal, match="overlapping target"):
        ge.validate_proposals(DOCS, [rng, other])
    ge.validate_proposals(DOCS, [good, other])  # adjacent, not overlapping


def test_empty_proposal_set_needs_justification():
    with pytest.raises(DeltaRefusal, match="explicit justification"):
        ge.validate_proposals(DOCS, [])
    ge.validate_proposals(DOCS, [], empty_justification="the sources only restate known facts")


def test_support_must_be_an_exact_selected_source_span():
    p = prop("party", 3, "x\n", support="not in any source")
    with pytest.raises(DeltaRefusal, match="exact span"):
        ge.validate_proposals(DOCS, [p], source_texts=SOURCES)
    ge.validate_proposals(DOCS, [prop("party", 3, "x\n")], source_texts=SOURCES)


def test_reconstruction_applies_only_approved_and_keeps_untouched_bytes():
    a = prop("party", 3, "Ruck is a mason.\n")
    b = prop("world_state", 4, "The Lantern Guild buys blades and plate. [ch 001 / 001.01]")  # CRLF line, no ending
    c = prop("world_state", 7, "The forge is lit. [ch 002 / entry]")
    decisions = {a.proposal_id: ge.DecisionEntry(decision="approve"),
                 b.proposal_id: ge.DecisionEntry(decision="approve"),
                 c.proposal_id: ge.DecisionEntry(decision="reject")}
    out = ge.reconstruct(DOCS, [a, b, c], decisions)
    assert out["party"] == b"# Party\n\nRuck is a mason.\nSister Ines keeps the ledger.\n"
    assert out["world_state"] == WORLD.replace(
        b"The Lantern Guild buys blades. [ch 001 / 001.01]\r\n",
        b"The Lantern Guild buys blades and plate. [ch 001 / 001.01]\r\n")  # CRLF ending restored
    # every untouched line is byte-identical, including the final line with no newline
    old, new = WORLD.splitlines(keepends=True), out["world_state"].splitlines(keepends=True)
    assert [x for i, x in enumerate(old) if i != 3] == [x for i, x in enumerate(new) if i != 3]
    assert new[-1] == b"Second repeated heading body, no trailing newline"
    assert out["party"].splitlines(keepends=True)[3] == PARTY.splitlines(keepends=True)[3]


def test_unset_or_discuss_blocks_reconstruction_and_names_the_proposals():
    a = prop("party", 3, "Ruck is a mason.\n")
    b = prop("party", 4, "Ines keeps the book.\n")
    with pytest.raises(DeltaRefusal, match=a.proposal_id) as exc:
        ge.reconstruct(DOCS, [a, b], {b.proposal_id: ge.DecisionEntry(decision="approve")})
    assert exc.value.exit_code == EXIT_REFUSAL
    with pytest.raises(DeltaRefusal, match=b.proposal_id):
        ge.reconstruct(DOCS, [a, b], {a.proposal_id: ge.DecisionEntry(decision="approve"),
                                      b.proposal_id: ge.DecisionEntry(decision="discuss")})


def test_stale_baseline_blocks_reconstruction():
    a = prop("party", 3, "Ruck is a mason.\n")
    moved = dict(DOCS, party=PARTY.replace(b"Ruck is a smith.", b"Ruck is a cook."))
    with pytest.raises(DeltaRefusal, match="unknown target|stale"):
        ge.reconstruct(moved, [a], {a.proposal_id: ge.DecisionEntry(decision="approve")})


def test_decisions_are_revisioned_and_validated(tmp_path):
    a = prop("party", 3, "Ruck is a mason.\n")
    saved = ge.save_proposals(tmp_path, ge.ProposalSet(plan_id="plan-x", baseline_ref="g@s", proposals=[a]))
    assert saved.revision == 1 and saved.status == "draft"
    with pytest.raises(DeltaRefusal) as exc:
        ge.decide(tmp_path, "plan-x", a.proposal_id, "maybe", reviewer="gm")
    assert exc.value.exit_code == EXIT_USAGE
    with pytest.raises(DeltaRefusal, match="no such proposal"):
        ge.decide(tmp_path, "plan-x", "p-nope", "approve", reviewer="gm")
    d1 = ge.decide(tmp_path, "plan-x", a.proposal_id, "discuss", "ask the GM", reviewer="gm")
    d2 = ge.decide(tmp_path, "plan-x", a.proposal_id, "approve", reviewer="gm")
    assert (d1.revision, d2.revision) == (1, 2)
    d = ge.edits_dir(tmp_path, "plan-x")
    assert json.loads((d / "decisions-r1.json").read_text())["decisions"][a.proposal_id]["decision"] == "discuss"
    out = ge.reconstruct_for_plan(tmp_path, "plan-x", DOCS)
    assert b"Ruck is a mason." in out["party"]
    # a re-propose is a new revision and starts undecided
    ge.save_proposals(tmp_path, ge.ProposalSet(plan_id="plan-x", baseline_ref="g@s", proposals=[a]))
    with pytest.raises(DeltaRefusal, match=a.proposal_id):
        ge.reconstruct_for_plan(tmp_path, "plan-x", DOCS)


def test_propose_edits_uses_campaignlib_and_returns_drafts_only(monkeypatch):
    seen = {}
    good_t = tid("party", 3)

    def fake_stream(client, system, user, model, **kw):
        seen.update(system=system, user=user, model=model)
        return "```json\n" + json.dumps({"proposals": [
            {"target_id": good_t, "after_text": "Ruck is a mason.", "category": "superseded_state",
             "rationale": "r", "support": "Brannoc lit the forge at last."},
            {"target_id": good_t, "after_text": "dup", "category": "new_information",
             "rationale": "r", "support": "Tobin offered coal."},
            {"target_id": "party:L99:deadbeef", "after_text": "x", "category": "new_information",
             "rationale": "r", "support": "Tobin offered coal."},
            {"target_id": tid("party", 4), "after_text": "y", "category": "new_information",
             "rationale": "r", "support": "invented span"},
        ]}) + "\n```"
    monkeypatch.setattr(ge, "stream_api", fake_stream)
    result = ge.propose_edits(DOCS, SOURCES, plan_id="plan-x", baseline_ref="g@s", backend="anthropic",
                              model="m", client=object())
    assert seen["model"] == "m" and good_t in seen["user"] and "Brannoc lit the forge" in seen["user"]
    assert "CANARY" not in seen["user"]
    assert [p.target_id for p in result.proposals] == [good_t] and result.status == "draft"
    assert result.proposals[0].after_text == "Ruck is a mason."
    reasons = " | ".join(r.reason for r in result.rejected)
    assert "duplicate target" in reasons and "unknown target" in reasons and "exact span" in reasons
    assert DOCS["party"] == PARTY  # nothing applied


def test_propose_edits_refuses_garbage_and_unjustified_empty(monkeypatch):
    monkeypatch.setattr(ge, "stream_api", lambda *a, **k: "not json")
    with pytest.raises(DeltaRefusal, match="not valid JSON"):
        ge.propose_edits(DOCS, SOURCES, plan_id="p", baseline_ref="r", model="m", client=object())
    monkeypatch.setattr(ge, "stream_api", lambda *a, **k: json.dumps({"proposals": []}))
    with pytest.raises(DeltaRefusal, match="no usable edits"):
        ge.propose_edits(DOCS, SOURCES, plan_id="p", baseline_ref="r", model="m", client=object())
    monkeypatch.setattr(ge, "stream_api", lambda *a, **k: json.dumps(
        {"proposals": [], "empty_justification": "nothing new"}))
    empty = ge.propose_edits(DOCS, SOURCES, plan_id="p", baseline_ref="r", model="m", client=object())
    assert empty.proposals == [] and empty.empty_justification == "nothing new"


# --------------------------------------------------------------------------- checks

def test_a_deleted_repeated_heading_is_caught_by_counting():
    # "## Threads" appears twice in WORLD; deleting one leaves the heading present as a set member.
    edited = WORLD.replace(b"## Threads\nSecond repeated", b"Second repeated")
    assert set(gc.headings(edited)) == set(gc.headings(WORLD))  # a set comparison would pass it
    report = gc.check_documents({"world_state": WORLD}, {"world_state": edited})
    lost = [f for f in report.findings if f.code == gc.HEADING_LOST]
    assert len(lost) == 1 and "Threads" in lost[0].detail and not report.passed
    assert gc.check_documents({"world_state": WORLD}, {"world_state": WORLD}).passed


def test_added_heading_is_information_not_a_block():
    report = gc.check_documents({"party": PARTY}, {"party": PARTY + b"## New\nx\n"})
    assert report.passed and [f.code for f in report.findings] == [gc.HEADING_ADDED]


def test_table_width_checks_rows_and_baseline():
    ragged = WORLD.replace(b"| Forge | cold |", b"| Forge | cold | extra |")
    report = gc.check_documents({"world_state": WORLD}, {"world_state": ragged})
    assert [f.code for f in report.blocking] == [gc.TABLE_WIDTH]
    widened = WORLD.replace(b"| Thread | Status |", b"| Thread | Status | Note |").replace(
        b"|---|---|", b"|---|---|---|").replace(b"| Forge | cold |", b"| Forge | cold | - |")
    report = gc.check_documents({"world_state": WORLD}, {"world_state": widened})
    assert any("baseline had 2" in f.detail for f in report.blocking)


def test_citations_must_resolve_to_baseline_or_selected_sources():
    base = {"world_state": WORLD}
    new_targets = gc.new_targets_for_sources({3: "### 003.01 The New Fire\n"})
    assert (3, "003.01") in new_targets and (3, "entry") in new_targets
    cand = WORLD + b"\nNew fact. [ch 003 / 003.01]\nInherited. [ch 001 / 001.01]\nBogus. [ch 003 / 003.09]\nFar. [ch 074 / entry]\n"
    report = gc.check_documents(base, {"world_state": cand}, new_targets=new_targets)
    bad = sorted(f.detail.split("]")[0] for f in report.blocking if f.code == gc.CITATION_UNRESOLVED)
    assert bad == ["[ch 003 / 003.09", "[ch 074 / entry"]


def test_consistency_call_returns_findings_and_never_approves(monkeypatch):
    changed = {"party": PARTY.replace(b"smith", b"mason")}
    monkeypatch.setattr(gc, "stream_api", lambda *a, **k: json.dumps(
        {"findings": [{"document": "party", "line": 3, "detail": "Ruck's trade conflicts with ch 2"}]}))
    findings = gc.propose_consistency_findings({"party": PARTY}, changed, SOURCES, model="m", client=object())
    assert [(f.code, f.severity) for f in findings] == [(gc.CONSISTENCY, "advisory")]
    report = gc.CheckReport(findings=findings)
    assert report.approval is None and report.passed  # advisory findings are not approvals or blocks
    monkeypatch.setattr(gc, "stream_api", lambda *a, **k: pytest.fail("no call when nothing changed"))
    assert gc.propose_consistency_findings({"party": PARTY}, {"party": PARTY}, SOURCES, model="m") == []
    monkeypatch.setattr(gc, "stream_api", lambda *a, **k: "garbage")
    with pytest.raises(DeltaRefusal):
        gc.propose_consistency_findings({"party": PARTY}, changed, SOURCES, model="m", client=object())
