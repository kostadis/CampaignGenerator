from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.models import ReviewItem, ReviewManifest, SourceCustodyGeneration
from pipelines.summary_native.review.store import ReviewStoreError, create_review, initialize_campaign, read_snapshot


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _campaign(tmp_path: Path, *, version: int = 2) -> Path:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n")
    initialize_ledger(root, AuthorityLedger(version=version, campaign="test", revision=1), actor="test")
    return root


def _records(campaign_id: UUID):
    item = ReviewItem(
        item_id="item-1", revision=1, campaign_id=campaign_id, review_id="review-1", domain="npc_finding",
        subject_ref={"subject_id": UUID("10000000-0000-4000-8000-000000000001"), "kind": "claim"},
        occurrence_id=UUID("20000000-0000-4000-8000-000000000001"),
        locator={"source_path": "summaries/001/session-summary.md", "anchor": "scene-1"}, claim_text="Exact claim",
        evidence=({"source_id":"summary-1", "source_path":"summaries/001/session-summary.md", "anchor":"scene-1", "exact_excerpt":"Exact claim", "selected_span_sha256":"a"*64},),
        diagnostics=({"diagnostic_id":"check-1", "legacy_code":"missing", "message":"Needs review", "blocking":True},),
        categories={"missing_source_or_pointer"}, severity="blocking", assignment_basis="mechanical",
        rationale="The pointer must be checked.", proposed_action={"action":"accept_or_correct"}, scope={"kind":"evidence", "value":"scene-1"},
        rule_versions=({"rule_id":"pointer", "version":"1"},),
        input_bindings=({"source_id":"summary-1", "path":"summaries/001/session-summary.md", "custody_sha256":"b"*64, "semantic_sha256":"c"*64},),
    )
    custody = SourceCustodyGeneration(campaign_id=campaign_id, review_id="review-1", generation=1, recorded_at=NOW, sources=({"source_id":"summary-1", "path":"summaries/001/session-summary.md", "sha256":"b"*64, "size":11},))
    manifest = ReviewManifest(
        campaign_id=campaign_id, review_id="review-1", kind="npc_verification", generation=1, created_at=NOW, created_by="GM",
        selection=({"kind":"subject", "id":"npc-1"},),
        items=({"campaign_id":campaign_id, "review_id":"review-1", "item_id":"item-1", "revision":1, "review_digest":item.review_digest},),
        source_manifest={"campaign_id":campaign_id, "review_id":"review-1", "generation":1, "digest":custody.custody_digest}, rule_versions=({"rule_id":"pointer", "version":"1"},),
    )
    return manifest, custody, item


def test_init_refuses_v1_and_is_idempotent_for_v2(tmp_path: Path):
    legacy = _campaign(tmp_path / "legacy", version=1)
    with pytest.raises(ReviewStoreError, match="MIGRATION_REQUIRED"):
        initialize_campaign(legacy)
    root = _campaign(tmp_path / "current")
    first = initialize_campaign(root)
    assert initialize_campaign(root) == first


def test_review_snapshot_is_immutable_and_coherent(tmp_path: Path):
    root = _campaign(tmp_path)
    identity = initialize_campaign(root)
    manifest, custody, item = _records(identity.campaign_id)
    result = create_review(root, manifest, custody, [item])
    assert result["item_count"] == 1
    loaded_manifest, loaded_custody, loaded_items = read_snapshot(root, "review-1")
    assert loaded_manifest == manifest
    assert loaded_custody == custody
    assert loaded_items == (item,)
    with pytest.raises(Exception, match="already exists"):
        create_review(root, manifest, custody, [item])


def test_cli_init_json_envelope(tmp_path: Path, capsys):
    root = _campaign(tmp_path)
    assert main(["review", "init", "--campaign-dir", str(root), "--json"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["ok"] is True and response["code"] == "REVIEW_INITIALIZED"


def test_store_refuses_symlinked_review_root(tmp_path: Path):
    root = _campaign(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "docs" / "reviews").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReviewStoreError, match="symlink"):
        initialize_campaign(root)


def test_identity_strict_json_and_read_custody_validation(tmp_path: Path):
    root = _campaign(tmp_path)
    identity = initialize_campaign(root)
    identity_path = root / "docs" / "reviews" / "campaign.json"
    identity_path.write_text(
        '{"version":1,"version":1,"campaign_id":"%s","canonical_root":"%s"}\n'
        % (identity.campaign_id, root.resolve())
    )
    with pytest.raises(ReviewStoreError, match="NOT_INITIALIZED"):
        initialize_campaign(root)

    # Restore a valid identity, create a review, then prove copied/corrupted
    # custody data cannot be returned as a coherent snapshot.
    identity_path.write_bytes(identity.bytes())
    manifest, custody, item = _records(identity.campaign_id)
    create_review(root, manifest, custody, [item])
    item_path = root / "docs" / "reviews" / "review-1" / "items" / "item-1" / "1.json"
    raw = json.loads(item_path.read_text())
    raw["input_bindings"][0]["custody_sha256"] = "d" * 64
    # Recompute the semantic digest is unnecessary: custody hashes are
    # deliberately excluded, which is exactly why the store must cross-check.
    item_path.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(ReviewStoreError, match="custody mismatch"):
        read_snapshot(root, "review-1")
