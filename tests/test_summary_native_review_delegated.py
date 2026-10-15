"""``review carry`` and ``review policy``: delegated decisions, never implicit.

Both commands plan by default and write nothing; only ``--write`` saves, and it
saves through the same ``save_decisions`` path as ``review decide``.  These tests
drive the public CLI against fixture reviews and inspect the disk records.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.models import ReviewItem, ReviewManifest, SourceCustodyGeneration
from pipelines.summary_native.review.store import (
    create_review,
    initialize_campaign,
    retract_decision,
    save_decisions,
)

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
SUMMARY = "summaries/001/session-summary.md"
DRAFT = "docs/npcs/summary_native/ch001-001/draft/npc_jimjar.md"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _item(campaign_id: UUID, review_id: str, item_id: str, *, claim: str = None, code: str = "citation-mismatch",
          codes: tuple[str, ...] = None, action: dict = None, summary_sha: str) -> ReviewItem:
    number = int(hashlib.sha256(item_id.encode()).hexdigest()[:6], 16)
    codes = codes or (code,)
    return ReviewItem(
        item_id=item_id, revision=1, campaign_id=campaign_id, review_id=review_id, domain="npc_finding",
        subject_ref={"subject_id": UUID(int=100 + number), "kind": "claim"},
        occurrence_id=UUID(int=200 + number),
        locator={"source_path": SUMMARY, "anchor": item_id, "display_line": 3},
        claim_text=claim or f"Exact claim {item_id}",
        evidence=({"source_id": "summary-1", "source_path": SUMMARY, "anchor": item_id,
                   "exact_excerpt": "Exact evidence", "selected_span_sha256": _sha(b"Exact evidence")},),
        diagnostics=tuple(
            {"diagnostic_id": f"check-{item_id}-{index}", "legacy_code": value,
             "message": f"Finding {value}.", "blocking": False}
            for index, value in enumerate(codes)
        ),
        categories={"citation_non_entailment"}, severity="needs_judgment", assignment_basis="advisory_candidate",
        rationale="A valid citation does not establish entailment.",
        proposed_action=action or {"action": "accept_no_change_or_correct"},
        scope={"kind": "evidence", "value": item_id},
        rule_versions=({"rule_id": "citation-entailment", "version": "1"},),
        input_bindings=({"source_id": "summary-1", "path": SUMMARY, "custody_sha256": summary_sha, "semantic_sha256": "c" * 64},),
    )


def _signoff(campaign_id: UUID, review_id: str, draft_sha: str, *, summary_sha: str) -> ReviewItem:
    return _item(
        campaign_id, review_id, "npc-signoff-jimjar", claim="Approve exact NPC draft bytes for Jimjar.",
        code="npc-draft-signoff-required", summary_sha=summary_sha,
        action={"action": "signoff_npc_draft", "details": {
            "npc": "Jimjar", "draft_path": DRAFT, "draft_sha256": draft_sha,
            "mechanical_verdict": "pass", "verification_complete": True}},
    )


def _create(root: Path, campaign_id: UUID, review_id: str, items: list[ReviewItem], sources: list[dict]) -> None:
    custody = SourceCustodyGeneration(campaign_id=campaign_id, review_id=review_id, generation=1, recorded_at=NOW,
                                      sources=tuple(sources))
    manifest = ReviewManifest(
        campaign_id=campaign_id, review_id=review_id, kind="npc_verification", generation=1, created_at=NOW,
        created_by="GM", selection=({"kind": "subject", "id": "npc-1"},),
        items=tuple({"campaign_id": campaign_id, "review_id": review_id, "item_id": item.item_id,
                     "revision": item.revision, "review_digest": item.review_digest} for item in items),
        source_manifest={"campaign_id": campaign_id, "review_id": review_id, "generation": 1,
                         "digest": custody.custody_digest},
        rule_versions=({"rule_id": "citation-entailment", "version": "1"},),
    )
    create_review(root, manifest, custody, items)


def _decide(root: Path, review_id: str, item: ReviewItem, verdict: str, disposition: str, *, request: str,
            reviewer: str = "GM") -> dict:
    return save_decisions(root, review_id, {
        "version": 1, "request_id": request, "review_generation": 1, "reviewer": reviewer,
        "decisions": [{"item_id": item.item_id, "item_revision": item.revision, "review_digest": item.review_digest,
                       "expected_decision_revision": 0, "verdict": verdict, "disposition": disposition,
                       "note": "GM reviewed."}],
    })


@pytest.fixture
def campaign(tmp_path: Path):
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")
    (root / "summaries" / "001").mkdir(parents=True)
    summary = b"# Chapter 1\n\nExact evidence\n"
    (root / SUMMARY).write_bytes(summary)
    draft_path = root / DRAFT
    draft_path.parent.mkdir(parents=True)
    draft = b"# Jimjar\n\n- A deep gnome [ch 001 / 001.01]\n"
    draft_path.write_bytes(draft)
    initialize_ledger(root, AuthorityLedger(version=2, campaign="delegated-fixture", revision=1), actor="test")
    identity = initialize_campaign(root)
    return root, identity.campaign_id, _sha(summary), _sha(draft), [
        {"source_id": "summary-1", "path": SUMMARY, "sha256": _sha(summary), "size": len(summary)},
        {"source_id": "draft-1", "path": DRAFT, "sha256": _sha(draft), "size": len(draft)},
    ]


def _run(capsys, argv: list[str]) -> tuple[int, dict]:
    returncode = main(argv)
    out = capsys.readouterr().out
    return returncode, json.loads(out)


def _events(root: Path, review_id: str) -> list[dict]:
    directory = root / "docs" / "reviews" / review_id / "events"
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


@pytest.fixture
def carry_reviews(campaign):
    root, cid, summary_sha, draft_sha, sources = campaign
    old = {
        "same": _item(cid, "old-review", "same", summary_sha=summary_sha),
        "changed": _item(cid, "old-review", "changed", claim="Old wording", summary_sha=summary_sha),
        "discussed": _item(cid, "old-review", "discussed", summary_sha=summary_sha),
        "withdrawn": _item(cid, "old-review", "withdrawn", summary_sha=summary_sha),
        "signoff": _signoff(cid, "old-review", draft_sha, summary_sha=summary_sha),
    }
    _create(root, cid, "old-review", list(old.values()), sources)
    _decide(root, "old-review", old["same"], "approve", "accept_no_change", request="r-same", reviewer="Kostadis")
    _decide(root, "old-review", old["changed"], "approve", "accept_no_change", request="r-changed")
    _decide(root, "old-review", old["discussed"], "discuss", "defer", request="r-discussed")
    withdrawn = _decide(root, "old-review", old["withdrawn"], "approve", "accept_no_change", request="r-withdrawn")
    retract_decision(root, "old-review", event_id=withdrawn["events"][0]["event_id"], expected_revision=1,
                     reason="mistake", reviewer="GM")
    _decide(root, "old-review", old["signoff"], "approve", "document_signoff", request="r-signoff")
    new = [
        _item(cid, "new-review", "same", summary_sha=summary_sha),
        _item(cid, "new-review", "changed", claim="New wording", summary_sha=summary_sha),
        _item(cid, "new-review", "discussed", summary_sha=summary_sha),
        _item(cid, "new-review", "withdrawn", summary_sha=summary_sha),
        _item(cid, "new-review", "brand-new", summary_sha=summary_sha),
        _signoff(cid, "new-review", draft_sha, summary_sha=summary_sha),
    ]
    _create(root, cid, "new-review", new, sources)
    return root


def _carry_argv(root: Path, *extra: str) -> list[str]:
    return ["review", "carry", "new-review", "--from", "old-review", "--campaign-dir", str(root), "--json", *extra]


def test_carry_dry_run_plans_only_unchanged_current_approvals_and_writes_nothing(carry_reviews, capsys):
    root = carry_reviews
    returncode, response = _run(capsys, _carry_argv(root))
    assert returncode == 0 and response["code"] == "REVIEW_CARRY_PLAN"
    data = response["data"]
    assert sorted(data["carried"]) == ["npc-signoff-jimjar", "same"]
    reasons = {entry["item_id"]: entry["reason"] for entry in data["needs_review"]}
    assert set(reasons) == {"changed", "discussed", "withdrawn", "brand-new"}
    assert "changed" in reasons["changed"]
    assert "discuss" in reasons["discussed"]
    assert "no current decision" in reasons["withdrawn"]
    assert "absent" in reasons["brand-new"]
    assert data["write"] is False
    assert _events(root, "new-review") == []


def test_carry_write_saves_through_decide_path_with_attributed_notes(carry_reviews, capsys):
    root = carry_reviews
    returncode, response = _run(capsys, _carry_argv(root, "--write"))
    assert returncode == 0 and response["code"] == "REVIEW_CARRY_SAVED"
    events = {event["item_id"]: event for event in _events(root, "new-review")}
    assert set(events) == {"same", "npc-signoff-jimjar"}
    assert events["same"]["disposition"] == "accept_no_change"
    assert events["npc-signoff-jimjar"]["disposition"] == "document_signoff"
    for event in events.values():
        assert event["verdict"] == "approve" and event["authority_record_id"]
        assert "old-review" in event["note"] and "review carry" in event["note"]
    assert events["same"]["reviewer"] == "Kostadis (carried)"
    assert events["npc-signoff-jimjar"]["reviewer"] == "GM (carried)"

    # A second run finds them already decided and saves nothing more.
    returncode, response = _run(capsys, _carry_argv(root, "--write"))
    assert returncode == 0 and response["data"]["carried"] == []
    assert sorted(response["data"]["already_decided"]) == ["npc-signoff-jimjar", "same"]
    assert len(_events(root, "new-review")) == 2


def test_carry_explicit_reviewer_and_signoff_refused_when_draft_bytes_changed_on_disk(carry_reviews, capsys):
    root = carry_reviews
    (root / DRAFT).write_text("# Jimjar\n\n- edited after review\n", encoding="utf-8")
    returncode, response = _run(capsys, _carry_argv(root, "--reviewer", "GM via assistant"))
    assert returncode == 0
    reasons = {entry["item_id"]: entry["reason"] for entry in response["data"]["needs_review"]}
    assert "REVIEW_NPC_SIGNOFF_STALE" in reasons["npc-signoff-jimjar"]
    assert response["data"]["carried"] == ["same"]


def test_carry_refuses_same_review(carry_reviews, capsys):
    root = carry_reviews
    returncode, response = _run(capsys, ["review", "carry", "new-review", "--from", "new-review",
                                         "--campaign-dir", str(root), "--json"])
    assert returncode != 0 and response["code"] == "REVIEW_CARRY_INVALID"


@pytest.fixture
def policy_review(campaign, tmp_path: Path):
    root, cid, summary_sha, _draft_sha, sources = campaign
    items = [
        _item(cid, "pol-review", "num-1", code="number-inconsistency", summary_sha=summary_sha),
        _item(cid, "pol-review", "num-2", code="number-inconsistency", summary_sha=summary_sha),
        _item(cid, "pol-review", "typo-1", code="typography-normalised", summary_sha=summary_sha),
        _item(cid, "pol-review", "mixed", codes=("number-inconsistency", "typography-normalised"), summary_sha=summary_sha),
        _item(cid, "pol-review", "other", code="not-found", summary_sha=summary_sha),
        _item(cid, "pol-review", "blocked", code="typography-normalised", summary_sha=summary_sha,
              action={"action": "resolve_claim_finding"}),
    ]
    _create(root, cid, "pol-review", items, sources)
    _decide(root, "pol-review", items[1], "discuss", "defer", request="r-num2")
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "number-inconsistency: Checked by hand against the evidence.\n"
        "typography-normalised: Quote matches except for curly/straight marks.\n",
        encoding="utf-8",
    )
    return root, policy


def _policy_argv(root: Path, policy: Path, *extra: str) -> list[str]:
    return ["review", "policy", "pol-review", "--policy", str(policy), "--campaign-dir", str(root), "--json", *extra]


def test_policy_requires_reviewer(policy_review, capsys):
    root, policy = policy_review
    with pytest.raises(SystemExit):
        main(["review", "policy", "pol-review", "--policy", str(policy), "--campaign-dir", str(root)])


def test_policy_dry_run_counts_single_code_items_and_writes_nothing(policy_review, capsys):
    root, policy = policy_review
    before = _events(root, "pol-review")
    returncode, response = _run(capsys, _policy_argv(root, policy, "--reviewer", "GM"))
    assert returncode == 0 and response["code"] == "REVIEW_POLICY_PLAN"
    data = response["data"]
    assert data["approvable"] == ["num-1", "typo-1"]
    assert data["counts_by_code"] == {"number-inconsistency": 1, "typography-normalised": 1}
    assert data["already_decided"] == ["num-2"]
    assert [entry["item_id"] for entry in data["ineligible"]] == ["blocked"]
    assert _events(root, "pol-review") == before


def test_policy_write_saves_attributed_accept_no_change_decisions(policy_review, capsys):
    root, policy = policy_review
    returncode, response = _run(capsys, _policy_argv(root, policy, "--reviewer", "GM (delegated policy)", "--write"))
    assert returncode == 0 and response["code"] == "REVIEW_POLICY_SAVED"
    events = {event["item_id"]: event for event in _events(root, "pol-review") if event["item_id"] in {"num-1", "typo-1"}}
    assert set(events) == {"num-1", "typo-1"}
    for event in events.values():
        assert event["verdict"] == "approve" and event["disposition"] == "accept_no_change"
        assert event["reviewer"] == "GM (delegated policy)"
        assert "review policy" in event["note"] and "policy.yaml sha256:" in event["note"]
    assert "Checked by hand" in events["num-1"]["note"]
    assert "[typography-normalised]" in events["typo-1"]["note"]


def test_policy_write_batches_by_configured_limit(policy_review, capsys):
    root, policy = policy_review
    (root / "config" / "review.yaml").write_text("max_batch_decisions: 1\n", encoding="utf-8")
    returncode, response = _run(capsys, _policy_argv(root, policy, "--reviewer", "GM", "--write"))
    assert returncode == 0 and len(response["data"]["saved"]) == 2
    requests = {event["request_id"] for event in _events(root, "pol-review") if event["item_id"] in {"num-1", "typo-1"}}
    assert len(requests) == 2


def test_policy_rejects_malformed_policy(policy_review, tmp_path: Path, capsys):
    root, _ = policy_review
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just a list\n", encoding="utf-8")
    returncode, response = _run(capsys, _policy_argv(root, bad, "--reviewer", "GM"))
    assert returncode != 0 and response["code"] == "REVIEW_POLICY_INVALID"
