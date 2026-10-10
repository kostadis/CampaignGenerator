"""Contract tests for durable review decisions (T012).

These drive the public CLI and then inspect the disk records.  The assertions
deliberately avoid an in-memory store shortcut: retries, competing revisions,
history and authority integration are properties of the campaign files.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import AuthorityLedger, load_ledger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.models import (
    ReviewItem,
    ReviewManifest,
    SourceCustodyGeneration,
)
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    create_review,
    export_review,
    import_review_bundle,
    initialize_campaign,
)


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _item(campaign_id: UUID, number: int, source_sha256: str) -> ReviewItem:
    return ReviewItem(
        item_id=f"item-{number}",
        revision=1,
        campaign_id=campaign_id,
        review_id="npc-review",
        domain="npc_finding",
        subject_ref={"subject_id": UUID(int=100 + number), "kind": "claim"},
        occurrence_id=UUID(int=200 + number),
        locator={
            "source_path": "summaries/001/session-summary.md",
            "anchor": f"scene-{number}",
        },
        claim_text=f"Exact claim {number}",
        evidence=(
            {
                "source_id": "summary-1",
                "source_path": "summaries/001/session-summary.md",
                "anchor": f"scene-{number}",
                "exact_excerpt": f"Exact evidence {number}",
                "selected_span_sha256": hashlib.sha256(
                    f"Exact evidence {number}".encode("utf-8")
                ).hexdigest(),
            },
        ),
        diagnostics=(
            {
                "diagnostic_id": f"check-{number}",
                "legacy_code": "citation-mismatch",
                "message": "Meaning requires GM review.",
                "blocking": False,
            },
        ),
        categories={"citation_non_entailment"},
        severity="needs_judgment",
        assignment_basis="advisory_candidate",
        rationale="A valid citation does not establish entailment.",
        proposed_action={"action": "accept_no_change_or_correct"},
        scope={"kind": "evidence", "value": f"scene-{number}"},
        rule_versions=({"rule_id": "citation-entailment", "version": "1"},),
        input_bindings=(
            {
                "source_id": "summary-1",
                "path": "summaries/001/session-summary.md",
                "custody_sha256": source_sha256,
                "semantic_sha256": "c" * 64,
            },
        ),
    )


@pytest.fixture
def decision_campaign(tmp_path: Path) -> tuple[Path, tuple[ReviewItem, ...]]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")
    (root / "summaries" / "001").mkdir(parents=True)
    source_bytes = b"# Chapter 1\n\nExact evidence 1\nExact evidence 2\nExact evidence 3\n"
    (root / "summaries" / "001" / "session-summary.md").write_bytes(source_bytes)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="decision-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(root)
    items = tuple(
        _item(identity.campaign_id, number, source_sha256) for number in (1, 2, 3)
    )
    custody = SourceCustodyGeneration(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        generation=1,
        recorded_at=NOW,
        sources=(
            {
                "source_id": "summary-1",
                "path": "summaries/001/session-summary.md",
                "sha256": source_sha256,
                "size": len(source_bytes),
            },
        ),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        kind="npc_verification",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=tuple(
            {"kind": "subject", "id": f"npc-{number}"} for number in (1, 2, 3)
        ),
        items=tuple(
            {
                "campaign_id": identity.campaign_id,
                "review_id": "npc-review",
                "item_id": item.item_id,
                "revision": item.revision,
                "review_digest": item.review_digest,
            }
            for item in items
        ),
        source_manifest={
            "campaign_id": identity.campaign_id,
            "review_id": "npc-review",
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "citation-entailment", "version": "1"},),
    )
    create_review(root, manifest, custody, items)
    return root, items


def _decision(
    item: ReviewItem,
    *,
    verdict: str = "approve",
    disposition: str = "accept_no_change",
    expected_revision: int = 0,
    note: str = "Reviewed against the cited scene.",
) -> dict:
    return {
        "item_id": item.item_id,
        "item_revision": item.revision,
        "review_digest": item.review_digest,
        "expected_decision_revision": expected_revision,
        "verdict": verdict,
        "disposition": disposition,
        "note": note,
    }


def _write_batch(
    path: Path,
    request_id: str,
    decisions: list[dict],
    *,
    reviewer: str = "GM",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "request_id": request_id,
                "review_generation": 1,
                "reviewer": reviewer,
                "decisions": decisions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return path


def _run_json(capsys, argv: list[str]) -> tuple[int, dict]:
    try:
        returncode = main(argv)
    except SystemExit as exc:
        pytest.fail(f"review CLI command is not implemented: exit {exc.code}")
    captured = capsys.readouterr()
    assert captured.out, f"CLI emitted no JSON; stderr={captured.err!r}"
    return returncode, json.loads(captured.out)


def _event_files(root: Path) -> list[Path]:
    return sorted((root / "docs" / "reviews" / "npc-review" / "events").glob("*.json"))


def test_explicit_batch_is_all_or_refuse_and_records_only_accepted_authority(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    batch = _write_batch(
        tmp_path / "batch.json",
        "request-batch-1",
        [
            _decision(items[0]),
            _decision(
                items[1],
                verdict="discuss",
                disposition="defer",
                note="Need to compare the later chapter.",
            ),
        ],
    )
    returncode, response = _run_json(
        capsys,
        [
            "review",
            "decide",
            "npc-review",
            "--decisions",
            str(batch),
            "--campaign-dir",
            str(root),
            "--json",
        ],
    )

    assert returncode == 0 and response["ok"] is True
    events = [json.loads(path.read_text(encoding="utf-8")) for path in _event_files(root)]
    assert [event["item_id"] for event in events] == ["item-1", "item-2"]
    assert events[0]["disposition"] == "accept_no_change"
    assert events[1]["disposition"] == "defer"
    assert events[1]["note"] == "Need to compare the later chapter."
    records = [record for record in load_ledger(root).records if record.kind == "review_decision"]
    assert len(records) == 1
    assert records[0].item_id == "item-1"

    stale_batch = _write_batch(
        tmp_path / "stale-batch.json",
        "request-batch-stale",
        [_decision(items[2]), _decision(items[0], note="stale member")],
    )
    before = [path.read_bytes() for path in _event_files(root)]
    returncode, response = _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(stale_batch), "--campaign-dir", str(root), "--json"],
    )
    assert returncode == 3
    assert response["ok"] is False and "STALE" in response["code"]
    assert [path.read_bytes() for path in _event_files(root)] == before


def test_compare_and_swap_prevents_competing_tabs_from_overwriting(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    first = _write_batch(tmp_path / "first.json", "tab-one", [_decision(items[0])])
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(first), "--campaign-dir", str(root), "--json"],
    )[0] == 0

    competing = _write_batch(
        tmp_path / "competing.json",
        "tab-two",
        [_decision(items[0], verdict="reject", disposition="reject_action", note="Other tab")],
    )
    returncode, response = _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(competing), "--campaign-dir", str(root), "--json"],
    )
    assert returncode == 3
    assert response["code"] == "REVIEW_STALE_DECISION"
    assert len(_event_files(root)) == 1
    assert json.loads(_event_files(root)[0].read_text())["verdict"] == "approve"


def test_lost_response_retry_returns_original_result_without_duplicate_history(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    batch = _write_batch(tmp_path / "retry.json", "lost-response", [_decision(items[0])])
    argv = ["review", "decide", "npc-review", "--decisions", str(batch), "--campaign-dir", str(root), "--json"]
    first_code, first = _run_json(capsys, argv)
    first_events = [path.read_bytes() for path in _event_files(root)]
    ledger_revision = load_ledger(root).revision

    second_code, second = _run_json(capsys, argv)
    assert first_code == second_code == 0
    assert second["data"] == first["data"]
    assert [path.read_bytes() for path in _event_files(root)] == first_events
    assert load_ledger(root).revision == ledger_revision


def test_reused_request_id_with_different_payload_refuses(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    path = _write_batch(tmp_path / "request.json", "same-request", [_decision(items[0])])
    argv = ["review", "decide", "npc-review", "--decisions", str(path), "--campaign-dir", str(root), "--json"]
    assert _run_json(capsys, argv)[0] == 0
    _write_batch(path, "same-request", [_decision(items[0], note="changed payload")])
    returncode, response = _run_json(capsys, argv)
    assert returncode != 0
    assert response["code"] == "REVIEW_REQUEST_ID_CONFLICT"
    assert len(_event_files(root)) == 1


def test_decision_refuses_when_bound_source_custody_has_changed(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    source = root / "summaries" / "001" / "session-summary.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\nChanged after review creation.\n",
        encoding="utf-8",
    )
    batch = _write_batch(
        tmp_path / "stale-source.json",
        "stale-source-custody",
        [_decision(items[0])],
    )
    before_revision = load_ledger(root).revision

    returncode, response = _run_json(
        capsys,
        [
            "review", "decide", "npc-review", "--decisions", str(batch),
            "--campaign-dir", str(root), "--json",
        ],
    )

    assert returncode == 3
    assert response["code"] == "REVIEW_STALE_CUSTODY"
    assert _event_files(root) == []
    assert load_ledger(root).revision == before_revision


def test_history_and_retraction_preserve_audit_and_withdraw_authority(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    batch = _write_batch(tmp_path / "approve.json", "approve-before-retract", [_decision(items[0])])
    _, decided = _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(batch), "--campaign-dir", str(root), "--json"],
    )
    event_id = decided["data"]["events"][0]["event_id"]

    code, history = _run_json(
        capsys,
        ["review", "history", "npc-review", "--item", "item-1", "--campaign-dir", str(root), "--json"],
    )
    assert code == 0
    assert [event["event_id"] for event in history["data"]["events"]] == [event_id]

    code, retracted = _run_json(
        capsys,
        [
            "review", "retract", "npc-review", "--event", event_id,
            "--expected-decision-revision", "1", "--reason", "Evidence needs renewed review",
            "--campaign-dir", str(root), "--json",
        ],
    )
    assert code == 0 and retracted["data"]["inverse_applied"] is False
    code, history = _run_json(
        capsys,
        ["review", "history", "npc-review", "--item", "item-1", "--campaign-dir", str(root), "--json"],
    )
    assert code == 0
    assert len(history["data"]["events"]) == 2
    assert history["data"]["events"][-1]["withdrawal_reason"] == "Evidence needs renewed review"
    record = next(record for record in load_ledger(root).records if record.kind == "review_decision")
    assert record.status == "withdrawn"


def test_accepted_decision_and_authority_record_share_one_recoverable_journal(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    batch = _write_batch(tmp_path / "one-journal.json", "one-journal", [_decision(items[0])])
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(batch), "--campaign-dir", str(root), "--json"],
    )[0] == 0

    journals = []
    for path in (root / "docs" / "authority" / "transactions").glob("*.json"):
        journal = json.loads(path.read_text(encoding="utf-8"))
        targets = {Path(target["path"]).relative_to(root).as_posix() for target in journal["targets"]}
        if any(target.startswith("docs/reviews/npc-review/events/") for target in targets):
            journals.append((journal, targets))
    assert len(journals) == 1
    journal, targets = journals[0]
    assert journal["state"] == "committed"
    assert "docs/authority.yaml" in targets
    assert "docs/authority/events/tip.json" in targets
    assert any(target.startswith("docs/reviews/npc-review/events/") for target in targets)
    assert any(
        target.startswith("docs/authority/events/") and target != "docs/authority/events/tip.json"
        for target in targets
    )


def test_export_import_current_mixed_history_is_an_idempotent_noop(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    first = _write_batch(
        tmp_path / "mixed.json",
        "mixed-reviewers-one",
        [_decision(items[0]), _decision(items[1], verdict="discuss", disposition="defer")],
        reviewer="GM One",
    )
    _, result = _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(first), "--campaign-dir", str(root), "--json"],
    )
    approved_event = result["data"]["events"][0]["event_id"]
    assert _run_json(
        capsys,
        [
            "review", "retract", "npc-review", "--event", approved_event,
            "--expected-decision-revision", "1", "--reason", "Second reviewer requested reconsideration",
            "--campaign-dir", str(root), "--json",
        ],
    )[0] == 0
    replacement = _write_batch(
        tmp_path / "replacement.json",
        "mixed-reviewers-two",
        [_decision(items[0], expected_revision=2, note="Reviewed again by another GM")],
        reviewer="GM Two",
    )
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(replacement), "--campaign-dir", str(root), "--json"],
    )[0] == 0

    exported = export_review(root, "npc-review", ["item-1", "item-2"])
    bundle = root / exported["path"]
    before_events = {path.name: path.read_bytes() for path in _event_files(root)}
    before_ledger = (root / "docs" / "authority.yaml").read_bytes()

    first_import = import_review_bundle(root, bundle, expected_generation=1)
    second_import = import_review_bundle(root, bundle, expected_generation=1)

    assert first_import == second_import
    assert first_import["imported_events"] == 0
    assert {path.name: path.read_bytes() for path in _event_files(root)} == before_events
    assert (root / "docs" / "authority.yaml").read_bytes() == before_ledger


def test_import_old_export_refuses_after_newer_local_decision_without_mutation(
    decision_campaign, tmp_path: Path, capsys
):
    root, items = decision_campaign
    first = _write_batch(tmp_path / "first-export.json", "export-first", [_decision(items[0])])
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(first), "--campaign-dir", str(root), "--json"],
    )[0] == 0
    exported = export_review(root, "npc-review", ["item-1"])
    bundle = root / exported["path"]
    newer = _write_batch(
        tmp_path / "newer.json",
        "newer-local",
        [_decision(items[0], verdict="reject", disposition="reject_action", expected_revision=1, note="New local ruling")],
    )
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(newer), "--campaign-dir", str(root), "--json"],
    )[0] == 0
    before_events = {path.name: path.read_bytes() for path in _event_files(root)}
    before_ledger = (root / "docs" / "authority.yaml").read_bytes()

    with pytest.raises(ReviewStoreError, match="STALE_DECISION"):
        import_review_bundle(root, bundle, expected_generation=1)

    assert {path.name: path.read_bytes() for path in _event_files(root)} == before_events
    assert (root / "docs" / "authority.yaml").read_bytes() == before_ledger
