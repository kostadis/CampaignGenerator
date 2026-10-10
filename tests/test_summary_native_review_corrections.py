"""T037 correction routing, freshness, and mutation-boundary contracts."""

from __future__ import annotations

import hashlib
import importlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    ReviewDecisionRecord,
    RulingRecord,
    load_ledger,
)
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review.models import (
    ReviewItem,
    ReviewManifest,
    SourceCorrectionProposal,
    SourceCorrectionReceipt,
    SourceCustodyGeneration,
)
from pipelines.summary_native.review.store import (
    create_review,
    initialize_campaign,
    save_decisions,
)


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _corrections_module():
    try:
        return importlib.import_module("pipelines.summary_native.review.corrections")
    except ModuleNotFoundError:
        pytest.fail("implement pipelines.summary_native.review.corrections", pytrace=False)


def _value(record, name):
    return getattr(record, name) if hasattr(record, name) else record[name]


def _build_correction_campaign(
    tmp_path: Path,
    *,
    include_ruling: bool = True,
    source_relative: str = "docs/summaries/001-source-error.md",
) -> tuple[Path, tuple[ReviewItem, ReviewItem]]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n")

    files = {
        source_relative: (
            "# Chapter 1\n\n## Scenes\n\n### 001.01 Vault\n"
            "<!-- anchor: vault-source -->\n"
            "The third simulacrum guarded the vault.\n"
        ).encode(),
        "docs/npcs/draft/source-error.md": (
            "# Source Error\n\nThe third simulacrum guarded the vault.\n"
        ).encode(),
        "docs/summaries/002-draft-error.md": (
            "# Chapter 2\n\n## Scenes\n\n### 002.01 Vault\n"
            "<!-- anchor: vault-draft -->\n"
            "The second simulacrum guarded the vault.\n"
        ).encode(),
        "docs/npcs/draft/draft-error.md": (
            "# Draft Error\n\nThe third simulacrum guarded the vault.\n"
        ).encode(),
    }
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    records = []
    if include_ruling:
        records.append(RulingRecord.model_validate({
            "id": "source-error-ruling",
            "kind": "ruling",
            "revision": 1,
            "classification": "RULED",
            "subject": {"kind": "topic", "id": "source-error"},
            "effective": {"from_chapter": 1, "through_chapter": 1},
            "audience": {"grants": ["gm"]},
            "projections": ["world_state"],
            "status": "draft",
            "recorded_at": NOW,
            "recorded_by": "GM",
            "source": {
                "path": source_relative,
                "anchor": "vault-source",
                "before_sha256": hashlib.sha256(
                    files[source_relative]
                ).hexdigest(),
                "before_span_sha256": hashlib.sha256(b"third simulacrum").hexdigest(),
            },
            "rejected_claim": "third simulacrum",
            "replacement_fact": "second simulacrum",
        }))
    initialize_ledger(
        root,
        AuthorityLedger(
            version=2,
            campaign="correction-fixture",
            revision=1,
            records=records,
        ),
        actor="test",
    )
    identity = initialize_campaign(root)

    definitions = (
        {
            "item_id": "source-error",
            "source_id": "source-summary",
            "source_path": source_relative,
            "draft_id": "source-draft",
            "draft_path": "docs/npcs/draft/source-error.md",
            "anchor": "vault-source",
            "claim": "The third simulacrum guarded the vault.",
            "evidence": "The third simulacrum guarded the vault.",
            "source_status": "incorrect",
            "draft_status": "derived_from_source",
            "expected_target": "source",
        },
        {
            "item_id": "draft-error",
            "source_id": "correct-summary",
            "source_path": "docs/summaries/002-draft-error.md",
            "draft_id": "wrong-draft",
            "draft_path": "docs/npcs/draft/draft-error.md",
            "anchor": "vault-draft",
            "claim": "The third simulacrum guarded the vault.",
            "evidence": "The second simulacrum guarded the vault.",
            "source_status": "correct",
            "draft_status": "incorrect",
            "expected_target": "draft",
        },
    )
    items: list[ReviewItem] = []
    for number, definition in enumerate(definitions, 1):
        evidence = definition["evidence"]
        source_bytes = files[definition["source_path"]]
        draft_bytes = files[definition["draft_path"]]
        items.append(ReviewItem(
            item_id=definition["item_id"],
            revision=1,
            campaign_id=identity.campaign_id,
            review_id="npc-review",
            domain="npc_finding",
            subject_ref={"subject_id": UUID(int=100 + number), "kind": "claim"},
            occurrence_id=UUID(int=200 + number),
            locator={"source_path": definition["draft_path"], "anchor": "vault-claim"},
            claim_text=definition["claim"],
            evidence=({
                "source_id": definition["source_id"],
                "source_path": definition["source_path"],
                "anchor": definition["anchor"],
                "exact_excerpt": evidence,
                "selected_span_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
                "citation_resolved": True,
                "support": "candidate_issue",
            },),
            diagnostics=({
                "diagnostic_id": f"correction-route-{number}",
                "legacy_code": "semantic-correction",
                "message": "The reviewed correction must target the erroneous layer.",
                "blocking": False,
            },),
            categories={"unsupported_or_contradicted"},
            severity="needs_judgment",
            assignment_basis="gm_confirmed",
            rationale="The source and generated draft have been compared directly.",
            proposed_action={
                "action": "correct_reviewed_layer",
                "details": {
                    **definition,
                    "rejected_claim": "third simulacrum",
                    "replacement_fact": "second simulacrum",
                    "authority_ruling_id": "source-error-ruling",
                },
            },
            scope={"kind": "evidence", "value": definition["anchor"]},
            rule_versions=({"rule_id": "correction-routing", "version": "1"},),
            input_bindings=(
                {
                    "source_id": definition["source_id"],
                    "path": definition["source_path"],
                    "custody_sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "semantic_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
                },
                {
                    "source_id": definition["draft_id"],
                    "path": definition["draft_path"],
                    "custody_sha256": hashlib.sha256(draft_bytes).hexdigest(),
                    "semantic_sha256": hashlib.sha256(definition["claim"].encode()).hexdigest(),
                },
            ),
        ))

    custody = SourceCustodyGeneration(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        generation=1,
        recorded_at=NOW,
        sources=tuple({
            "source_id": source_id,
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        } for source_id, relative, data in (
            ("source-summary", source_relative, files[source_relative]),
            ("source-draft", "docs/npcs/draft/source-error.md", files["docs/npcs/draft/source-error.md"]),
            ("correct-summary", "docs/summaries/002-draft-error.md", files["docs/summaries/002-draft-error.md"]),
            ("wrong-draft", "docs/npcs/draft/draft-error.md", files["docs/npcs/draft/draft-error.md"]),
        )),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id,
        review_id="npc-review",
        kind="npc_verification",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=({"kind": "subject", "id": "correction-fixture"},),
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
        rule_versions=({"rule_id": "correction-routing", "version": "1"},),
    )
    create_review(root, manifest, custody, items)
    return root, (items[0], items[1])


@pytest.fixture
def correction_campaign(tmp_path: Path) -> tuple[Path, tuple[ReviewItem, ReviewItem]]:
    return _build_correction_campaign(tmp_path)


def _prepare(root: Path, item_id: str, target_kind: str):
    module = _corrections_module()
    prepare = getattr(module, "prepare_correction", None)
    assert callable(prepare), "implement corrections.prepare_correction"
    return prepare(
        root,
        "npc-review",
        item_id,
        target_kind=target_kind,
        replacement_text="second simulacrum",
        expected_decision_revision=0,
    )


def _apply(root: Path, proposal):
    module = _corrections_module()
    apply = getattr(module, "apply_correction", None)
    assert callable(apply), "implement corrections.apply_correction"
    return apply(
        root,
        "npc-review",
        proposal_id=_value(proposal, "proposal_id"),
        proposal_sha256=_value(proposal, "proposal_digest"),
    )


def _approve(root: Path, item: ReviewItem, proposal: SourceCorrectionProposal, request_id: str) -> None:
    save_decisions(root, "npc-review", {
        "version": 1,
        "request_id": request_id,
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": 0,
            "verdict": "approve",
            "disposition": "source_correction",
            "note": "Apply only the exact reviewed source correction.",
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
        }],
    })


def test_source_and_draft_corrections_are_separate_bounded_previews(correction_campaign):
    root, _ = correction_campaign
    source = _prepare(root, "source-error", "source")
    draft = _prepare(root, "draft-error", "draft")

    assert isinstance(source, SourceCorrectionProposal)
    assert source.kind == "source_correction"
    assert source.authority_ruling_id
    assert source.affected_paths == ("docs/summaries/001-source-error.md",)
    assert "docs/npcs/draft/source-error.md" not in source.affected_paths
    assert _value(draft, "kind") == "draft_correction"
    assert _value(draft, "target_kind") == "draft"
    assert tuple(_value(draft, "affected_paths")) == ("docs/npcs/draft/draft-error.md",)
    assert "docs/summaries/002-draft-error.md" not in _value(draft, "affected_paths")
    ruling = next(record for record in load_ledger(root).records if record.id == "source-error-ruling")
    assert isinstance(ruling, RulingRecord)
    assert ruling.status == "proposed"
    assert ruling.proposal_id
    assert (
        root / "docs/authority/proposals" / ruling.proposal_id / "proposal.json"
    ).is_file()


def test_source_preview_requires_a_genuine_existing_authority_ruling(tmp_path: Path):
    root, _ = _build_correction_campaign(tmp_path, include_ruling=False)
    module = _corrections_module()
    error = getattr(module, "CorrectionReviewError", Exception)

    with pytest.raises(error, match="REVIEW_AUTHORITY_RULING_REQUIRED"):
        _prepare(root, "source-error", "source")

    assert not (root / "docs/reviews/npc-review/proposals").exists()


def test_source_preview_keeps_the_native_summary_only_target_gate(tmp_path: Path):
    root, _ = _build_correction_campaign(
        tmp_path, source_relative="docs/archive/001-source-error.md"
    )

    with pytest.raises(AuthorityError, match="AUTH_TARGET_NOT_ALLOWED"):
        _prepare(root, "source-error", "source")

    ruling = next(record for record in load_ledger(root).records if record.id == "source-error-ruling")
    assert isinstance(ruling, RulingRecord)
    assert ruling.status == "draft"
    assert not (root / "docs/reviews/npc-review/proposals").exists()


@pytest.mark.parametrize(("item_id", "wrong_target", "code"), [
    ("source-error", "draft", "REVIEW_SOURCE_CORRECTION_REQUIRED"),
    ("draft-error", "source", "REVIEW_DRAFT_CORRECTION_REQUIRED"),
])
def test_inverse_correction_target_is_refused(correction_campaign, item_id, wrong_target, code):
    root, _ = correction_campaign
    module = _corrections_module()
    error = getattr(module, "CorrectionReviewError", Exception)
    with pytest.raises(error, match=code):
        _prepare(root, item_id, wrong_target)


@pytest.mark.parametrize(("item_id", "target_kind", "changed_path"), [
    ("source-error", "source", "docs/summaries/001-source-error.md"),
    ("draft-error", "draft", "docs/npcs/draft/draft-error.md"),
])
def test_correction_preview_refuses_changed_exact_input(
    correction_campaign, item_id, target_kind, changed_path,
):
    root, _ = correction_campaign
    changed = root / changed_path
    changed.write_text(changed.read_text() + "\nChanged after review creation.\n")
    before = changed.read_bytes()
    module = _corrections_module()
    error = getattr(module, "CorrectionReviewError", Exception)
    with pytest.raises(error, match="REVIEW_STALE_CORRECTION_INPUT"):
        _prepare(root, item_id, target_kind)
    assert changed.read_bytes() == before


def test_approving_source_correction_does_not_change_source_or_draft(correction_campaign):
    root, (source_item, _) = correction_campaign
    proposal = _prepare(root, source_item.item_id, "source")
    assert isinstance(proposal, SourceCorrectionProposal)
    source = root / "docs/summaries/001-source-error.md"
    draft = root / "docs/npcs/draft/source-error.md"
    before = (source.read_bytes(), draft.read_bytes())

    _approve(root, source_item, proposal, "approve-without-apply")

    assert (source.read_bytes(), draft.read_bytes()) == before


def test_source_apply_uses_exact_reviewed_proposal_and_leaves_draft_unchanged(correction_campaign):
    root, (source_item, _) = correction_campaign
    proposal = _prepare(root, source_item.item_id, "source")
    assert isinstance(proposal, SourceCorrectionProposal)
    _approve(root, source_item, proposal, "approve-and-apply")
    source = root / "docs/summaries/001-source-error.md"
    draft = root / "docs/npcs/draft/source-error.md"
    draft_before = draft.read_bytes()

    receipt = _apply(root, proposal)

    assert isinstance(receipt, SourceCorrectionReceipt)
    assert "The second simulacrum guarded the vault." in source.read_text()
    assert draft.read_bytes() == draft_before
    assert receipt.changed_paths == ("docs/summaries/001-source-error.md",)
    assert receipt.authority_ruling_id == "source-error-ruling"
    ledger = load_ledger(root)
    ruling = next(record for record in ledger.records if record.id == "source-error-ruling")
    decision = next(
        record for record in ledger.records
        if isinstance(record, ReviewDecisionRecord) and record.item_id == source_item.item_id
    )
    assert isinstance(ruling, RulingRecord)
    assert ruling.status == "applied"
    assert ruling.applied_receipt
    assert (root / "docs/authority/receipts" / f"{ruling.applied_receipt}.json").is_file()
    assert decision.receipt is not None
    assert decision.receipt.digest == receipt.receipt_digest
    assert _apply(root, proposal) == receipt


def test_source_apply_refuses_when_exact_input_changes_after_approval(correction_campaign):
    root, (source_item, _) = correction_campaign
    proposal = _prepare(root, source_item.item_id, "source")
    assert isinstance(proposal, SourceCorrectionProposal)
    _approve(root, source_item, proposal, "approve-before-stale")
    source = root / "docs/summaries/001-source-error.md"
    source.write_text(source.read_text() + "\nConcurrent source edit.\n")
    changed = source.read_bytes()
    module = _corrections_module()
    error = getattr(module, "CorrectionReviewError", Exception)

    with pytest.raises(error, match="REVIEW_STALE_CORRECTION_INPUT"):
        _apply(root, proposal)
    assert source.read_bytes() == changed


def test_source_apply_resumes_after_native_proposal_stage(correction_campaign, monkeypatch):
    root, (source_item, _) = correction_campaign
    proposal = _prepare(root, source_item.item_id, "source")
    _approve(root, source_item, proposal, "approve-before-native-stage-stop")
    module = _corrections_module()
    real_apply = module.apply_proposal
    monkeypatch.setattr(module, "apply_proposal", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("stop after native proposal stage")))
    with pytest.raises(RuntimeError, match="native proposal stage"):
        _apply(root, proposal)
    ruling = next(record for record in load_ledger(root).records if record.id == "source-error-ruling")
    assert ruling.status == "proposed"

    monkeypatch.setattr(module, "apply_proposal", real_apply)
    receipt = _apply(root, proposal)
    assert isinstance(receipt, SourceCorrectionReceipt)
    assert "The second simulacrum guarded the vault." in (root / "docs/summaries/001-source-error.md").read_text()


def test_source_apply_refuses_changed_inspected_non_target(correction_campaign):
    root, (source_item, _) = correction_campaign
    proposal = _prepare(root, source_item.item_id, "source")
    _approve(root, source_item, proposal, "approve-before-context-change")
    draft = root / "docs/npcs/draft/source-error.md"
    draft.write_bytes(draft.read_bytes() + b"context changed\n")
    source = root / "docs/summaries/001-source-error.md"
    before = source.read_bytes()
    with pytest.raises(_corrections_module().CorrectionReviewError, match="REVIEW_STALE_CORRECTION_INPUT"):
        _apply(root, proposal)
    assert source.read_bytes() == before
