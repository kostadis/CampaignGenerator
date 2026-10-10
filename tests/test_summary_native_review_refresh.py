"""T028 contracts for audited custody refresh and conservative staleness."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review.models import (
    ReviewItem,
    ReviewManifest,
    RuleBinding,
    SourceCustodyGeneration,
)
from pipelines.summary_native.review import store
from pipelines.summary_native.review.store import (
    create_review,
    initialize_campaign,
    read_snapshot,
    review_status,
    save_decisions,
)
from pipelines.summary_native.review.cli import _show_review


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
RELEVANT = "The second simulacrum guarded the vault."


@pytest.fixture
def refresh_campaign(tmp_path: Path) -> tuple[Path, ReviewItem]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n")
    primary_bytes = (
        "# Relevant dossier\n\n"
        f"{RELEVANT}\n\n"
        "Unrelated travel notes remain below.\n"
    ).encode()
    other_bytes = b"# Another NPC\n\nThis dossier is unrelated.\n"
    primary = root / "summaries" / "001" / "session-summary.md"
    other = root / "docs" / "npcs" / "unrelated.md"
    primary.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    primary.write_bytes(primary_bytes)
    other.write_bytes(other_bytes)

    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="refresh-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(root)
    item = ReviewItem(
        item_id="item-1",
        revision=1,
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        domain="npc_finding",
        subject_ref={"subject_id": UUID(int=101), "kind": "claim"},
        occurrence_id=UUID(int=201),
        locator={"source_path": "docs/npcs/generated.md", "anchor": "claim-1"},
        claim_text="The second simulacrum guarded the vault.",
        evidence=({
            "source_id": "summary-1",
            "source_path": "summaries/001/session-summary.md",
            "anchor": "vault",
            "exact_excerpt": RELEVANT,
            "selected_span_sha256": hashlib.sha256(RELEVANT.encode()).hexdigest(),
            "citation_resolved": True,
        },),
        diagnostics=({
            "diagnostic_id": "ordinal-check",
            "legacy_code": "ordinal-non-entailment",
            "message": "The ordinal was reviewed by the GM.",
            "blocking": False,
        },),
        categories={"citation_non_entailment"},
        severity="needs_judgment",
        assignment_basis="advisory_candidate",
        rationale="The exact claim and evidence require semantic judgment.",
        proposed_action={"action": "accept_no_change_or_correct"},
        scope={"kind": "evidence", "value": "vault"},
        rule_versions=({"rule_id": "ordinal-check", "version": "1"},),
        input_bindings=({
            "source_id": "summary-1",
            "path": "summaries/001/session-summary.md",
            "custody_sha256": hashlib.sha256(primary_bytes).hexdigest(),
            "semantic_sha256": hashlib.sha256(RELEVANT.encode()).hexdigest(),
        },),
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
                "sha256": hashlib.sha256(primary_bytes).hexdigest(),
                "size": len(primary_bytes),
            },
            {
                "source_id": "unrelated-dossier",
                "path": "docs/npcs/unrelated.md",
                "sha256": hashlib.sha256(other_bytes).hexdigest(),
                "size": len(other_bytes),
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
        selection=({"kind": "subject", "id": "fixture-npc"},),
        items=({
            "campaign_id": identity.campaign_id,
            "review_id": "npc-review",
            "item_id": item.item_id,
            "revision": item.revision,
            "review_digest": item.review_digest,
        },),
        source_manifest={
            "campaign_id": identity.campaign_id,
            "review_id": "npc-review",
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "ordinal-check", "version": "1"},),
    )
    create_review(root, manifest, custody, [item])
    save_decisions(root, "npc-review", {
        "version": 1,
        "request_id": "approve-before-refresh",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": 0,
            "verdict": "approve",
            "disposition": "accept_no_change",
            "note": "The source supports second, not third.",
        }],
    })
    return root, item


def _refresh(root: Path, **kwargs):
    refresh = getattr(store, "refresh_review", None)
    assert callable(refresh), "implement store.refresh_review"
    expected_generation = kwargs.pop("expected_generation", 1)
    return refresh(root, "npc-review", expected_generation=expected_generation, **kwargs)


@pytest.mark.parametrize("changed_path", [
    "summaries/001/session-summary.md",
    "docs/npcs/unrelated.md",
])
def test_refresh_preserves_approval_for_unrelated_byte_changes_with_audited_rebind(
    refresh_campaign, changed_path: str,
):
    root, item = refresh_campaign
    item_path = root / "docs" / "reviews" / "npc-review" / "items" / item.item_id / "1.json"
    before_item = item_path.read_bytes()
    decision_path, = (root / "docs" / "reviews" / "npc-review" / "events").glob("decision-*.json")
    before_decision = decision_path.read_bytes()
    changed = root / changed_path
    changed.write_text(changed.read_text() + "\nAn unrelated paragraph was added.\n")
    changed_sha256 = hashlib.sha256(changed.read_bytes()).hexdigest()

    result = _refresh(root)

    assert result["generation"] == 2
    assert result["preserved_item_ids"] == [item.item_id]
    assert result["stale_item_ids"] == []
    manifest, custody, refreshed_items = read_snapshot(root, "npc-review")
    assert manifest.generation == custody.generation == 2
    assert refreshed_items[0].revision == item.revision
    assert refreshed_items[0].review_digest == item.review_digest
    assert item_path.read_bytes() == before_item
    assert decision_path.read_bytes() == before_decision
    custody_by_path = {source.path: source for source in custody.sources}
    assert custody_by_path[changed_path].sha256 == changed_sha256
    assert review_status(root, "npc-review")["counts"]["approved"] == 1

    event_path = (
        root / "docs" / "reviews" / "npc-review" / "events"
        / f"{result['rebind_event_id']}.json"
    )
    event = json.loads(event_path.read_bytes())
    assert event["from_generation"] == 1
    assert event["to_generation"] == 2
    assert event["preserved_item_ids"] == [item.item_id]
    assert event["stale_item_ids"] == []


def test_refresh_marks_approval_stale_when_relevant_evidence_changes(refresh_campaign):
    root, item = refresh_campaign
    source = root / "summaries" / "001" / "session-summary.md"
    source.write_text(source.read_text().replace(RELEVANT, "The third simulacrum guarded the vault."))

    result = _refresh(root)

    assert result["preserved_item_ids"] == []
    assert result["stale_item_ids"] == [item.item_id]
    status = review_status(root, "npc-review")["counts"]
    assert status["approved"] == 0
    assert status["stale"] == 1
    manifest, _, refreshed = read_snapshot(root, "npc-review")
    assert manifest.generation == 2 and refreshed[0].revision == 2
    queue = _show_review(root, "npc-review", item_id=None, cursor=None, limit=None)
    assert queue["counts"]["approved"] == 0 and queue["counts"]["stale"] == 1
    assert queue["counts"]["settled"] == 0
    detail = _show_review(root, "npc-review", item_id=item.item_id, cursor=None, limit=None)
    assert detail["freshness"] == "stale" and detail["revision"] == 2


def test_refresh_never_resurrects_an_already_stale_approval(refresh_campaign):
    root, item = refresh_campaign
    changed_rules = ({"rule_id": "ordinal-check", "version": "2"},)
    first = _refresh(root, current_rule_versions=changed_rules)
    assert first["stale_item_ids"] == [item.item_id]

    second = _refresh(root, expected_generation=2)

    assert second["stale_item_ids"] == [item.item_id]
    assert review_status(root, "npc-review")["counts"]["stale"] == 1


def test_refresh_stales_when_structural_heading_changes_around_same_excerpt(refresh_campaign):
    root, item = refresh_campaign
    source = root / "summaries" / "001" / "session-summary.md"
    source.write_text(source.read_text().replace("# Relevant dossier", "# Different subject"))

    result = _refresh(root)

    assert result["stale_item_ids"] == [item.item_id]


def test_refresh_stales_when_same_excerpt_gains_changed_paragraph_context(refresh_campaign):
    root, item = refresh_campaign
    source = root / "summaries" / "001" / "session-summary.md"
    source.write_text(source.read_text().replace(RELEVANT, f"This was a false rumor: {RELEVANT}"))

    result = _refresh(root)

    assert result["stale_item_ids"] == [item.item_id]
    event = json.loads((
        root / "docs" / "reviews" / "npc-review" / "events"
        / f"{result['rebind_event_id']}.json"
    ).read_bytes())
    assert event["stale_item_ids"] == [item.item_id]


def test_refresh_marks_approval_stale_when_checking_rule_changes(refresh_campaign):
    root, item = refresh_campaign

    result = _refresh(
        root,
        current_rule_versions=(RuleBinding(rule_id="ordinal-check", version="2"),),
    )

    assert result["generation"] == 2
    assert result["preserved_item_ids"] == []
    assert result["stale_item_ids"] == [item.item_id]
    status = review_status(root, "npc-review")["counts"]
    assert status["approved"] == 0
    assert status["stale"] == 1
