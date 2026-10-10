"""T028 contracts for exact selected-check reruns and durable partial results."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review import verification
from pipelines.summary_native.review.models import (
    ReviewItem,
    ReviewManifest,
    RerunSelection,
    RunOutcome,
    RunReport,
    SourceCustodyGeneration,
    model_from_json,
)
from pipelines.summary_native.review.store import (
    create_review,
    initialize_campaign,
    save_decisions,
)
from pipelines.summary_native.review.verification import VerificationAdapterError


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _item(campaign_id: UUID, number: int, source_sha256: str) -> ReviewItem:
    blocking = number == 1
    return ReviewItem(
        item_id=f"item-{number}",
        revision=1,
        campaign_id=campaign_id,
        review_id="npc-review",
        domain="npc_finding",
        subject_ref={"subject_id": UUID(int=100 + number), "kind": "claim"},
        occurrence_id=UUID(int=200 + number),
        locator={"source_path": "summaries/001/session-summary.md", "anchor": f"scene-{number}"},
        claim_text=f"Exact claim {number}",
        evidence=({
            "source_id": "summary-1",
            "source_path": "summaries/001/session-summary.md",
            "anchor": f"scene-{number}",
            "exact_excerpt": f"Exact evidence {number}",
            "selected_span_sha256": hashlib.sha256(
                f"Exact evidence {number}".encode()
            ).hexdigest(),
            "citation_resolved": True,
        },),
        diagnostics=({
            "diagnostic_id": f"check-{number}",
            "legacy_code": "citation-mismatch",
            "message": "Selected check requires review.",
            "blocking": blocking,
        },),
        categories={"missing_source_or_pointer" if blocking else "citation_non_entailment"},
        severity="blocking" if blocking else "needs_judgment",
        assignment_basis="mechanical" if blocking else "advisory_candidate",
        rationale="Retain the exact selected check result.",
        proposed_action={"action": "rerun_selected_check"},
        scope={"kind": "evidence", "value": f"scene-{number}"},
        rule_versions=({"rule_id": "npc-verify", "version": "1"},),
        input_bindings=({
            "source_id": "summary-1",
            "path": "summaries/001/session-summary.md",
            "custody_sha256": source_sha256,
            "semantic_sha256": hashlib.sha256(
                f"Exact evidence {number}".encode()
            ).hexdigest(),
        },),
    )


@pytest.fixture
def rerun_campaign(tmp_path: Path) -> tuple[Path, tuple[ReviewItem, ...]]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n")
    source = b"Exact evidence 1\nExact evidence 2\nExact evidence 3\n"
    source_path = root / "summaries" / "001" / "session-summary.md"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    source_sha256 = hashlib.sha256(source).hexdigest()
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="rerun-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(root)
    items = tuple(_item(identity.campaign_id, number, source_sha256) for number in (1, 2, 3))
    custody = SourceCustodyGeneration(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        generation=1,
        recorded_at=NOW,
        sources=({
            "source_id": "summary-1",
            "path": "summaries/001/session-summary.md",
            "sha256": source_sha256,
            "size": len(source),
        },),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        kind="npc_verification",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=tuple({"kind": "subject", "id": f"npc-{number}"} for number in (1, 2, 3)),
        items=tuple({
            "campaign_id": identity.campaign_id,
            "review_id": "npc-review",
            "item_id": item.item_id,
            "revision": item.revision,
            "review_digest": item.review_digest,
        } for item in items),
        source_manifest={
            "campaign_id": identity.campaign_id,
            "review_id": "npc-review",
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "npc-verify", "version": "1"},),
    )
    create_review(root, manifest, custody, items)
    save_decisions(root, "npc-review", {
        "version": 1,
        "request_id": "seed-rerun-decisions",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [
            {
                "item_id": items[1].item_id,
                "item_revision": 1,
                "review_digest": items[1].review_digest,
                "expected_decision_revision": 0,
                "verdict": "reject",
                "disposition": "reject_action",
                "note": "Rerun the selected check.",
            },
            {
                "item_id": items[2].item_id,
                "item_revision": 1,
                "review_digest": items[2].review_digest,
                "expected_decision_revision": 0,
                "verdict": "approve",
                "disposition": "accept_no_change",
                "note": "Settled and current.",
            },
        ],
    })
    return root, items


def _preview(root: Path, members: dict[str, tuple[str, ...]], *, mode: str = "unresolved") -> RerunSelection:
    preview = getattr(verification, "preview_rerun", None)
    assert callable(preview), "implement verification.preview_rerun"
    return preview(root, "npc-review", members=members, mode=mode)


def _execute(root: Path, selection: RerunSelection, checkers) -> RunReport:
    execute = getattr(verification, "execute_rerun", None)
    assert callable(execute), "implement verification.execute_rerun"
    return execute(
        root,
        "npc-review",
        selection_sha256=selection.selection_sha256,
        checkers=checkers,
    )


def test_rerun_executes_only_literal_selected_check_ids(rerun_campaign):
    root, _ = rerun_campaign
    selection = _preview(root, {
        "item-1": ("citation",),
        "item-2": ("status-word",),
    })
    called: list[tuple[str, str]] = []

    def checker(check_id):
        def run(item):
            called.append((item.item_id, check_id))
            return {"check_id": check_id, "passed": True}
        return run

    report = _execute(root, selection, {
        "citation": checker("citation"),
        "status-word": checker("status-word"),
        "quote": checker("quote"),
        "whole-dossier": checker("whole-dossier"),
    })

    assert called == [("item-1", "citation"), ("item-2", "status-word")]
    assert [(member.item_id, member.check_id) for member in report.members] == called
    assert all(member.outcome is RunOutcome.COMPLETED for member in report.members)
    persisted = root / "docs" / "reviews" / "npc-review" / "runs" / f"{report.run_id}.json"
    assert model_from_json(RunReport, persisted.read_bytes()) == report


def test_unresolved_preview_refuses_a_current_approved_item(rerun_campaign):
    root, _ = rerun_campaign
    with pytest.raises(VerificationAdapterError, match="approved|unresolved"):
        _preview(root, {"item-3": ("citation",)}, mode="unresolved")


def test_partial_failure_persists_completed_failed_and_unprocessed_members(rerun_campaign):
    root, _ = rerun_campaign
    selection = _preview(root, {
        "item-1": ("citation", "quote"),
        "item-2": ("status-word",),
    })

    def fail(_item):
        raise RuntimeError("bounded checker failed")

    report = _execute(root, selection, {
        "citation": lambda item: {"item_id": item.item_id, "passed": True},
        "quote": fail,
        "status-word": lambda item: {"item_id": item.item_id, "passed": True},
    })

    assert [member.outcome for member in report.members] == [
        RunOutcome.COMPLETED,
        RunOutcome.FAILED,
        RunOutcome.UNPROCESSED,
    ]
    assert "bounded checker failed" in report.members[1].message
    assert report.members[2].message
    persisted = root / "docs" / "reviews" / "npc-review" / "runs" / f"{report.run_id}.json"
    assert model_from_json(RunReport, persisted.read_bytes()) == report
    members = root / "docs" / "reviews" / "npc-review" / "runs" / "members" / selection.selection_sha256
    assert len(tuple(members.glob("*.json"))) == 3


def test_rerun_refuses_changed_live_dependency_bytes(rerun_campaign):
    root, _ = rerun_campaign
    selection = _preview(root, {"item-1": ("citation",)})
    source = root / "summaries" / "001" / "session-summary.md"
    source.write_bytes(source.read_bytes() + b"changed\n")
    with pytest.raises(VerificationAdapterError, match="live dependency"):
        _execute(root, selection, {"citation": lambda item: {"passed": True}})


def test_completed_member_record_is_reused_after_interrupted_transport(rerun_campaign):
    root, _ = rerun_campaign
    selection = _preview(root, {"item-1": ("citation",)})
    first = _execute(root, selection, {"citation": lambda item: {"passed": True}})

    def should_not_run(_item):
        raise AssertionError("completed immutable member must be reused")

    second = _execute(root, selection, {"citation": should_not_run})
    assert second.members == first.members
