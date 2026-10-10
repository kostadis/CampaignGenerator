from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from campaignlib.review_config import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_GRANT_EXPIRY_SECONDS,
    DEFAULT_MAX_BATCH_DECISIONS,
    DEFAULT_MAX_NOTE_CHARS,
    DEFAULT_MAX_PAGE_ITEMS,
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_MAX_RESPONSE_BYTES,
    ReviewConfig,
    ReviewConfigError,
    load_review_config,
    resolve_campaign_scope,
)
from pipelines.summary_native.review.models import (
    ApplicationState,
    AssignmentBasis,
    DecisionDisposition,
    DecisionEvent,
    DispositionState,
    FindingCategory,
    FreshnessState,
    ItemReference,
    ReviewItem,
    ReviewManifest,
    ReviewModelError,
    ReviewState,
    RunMember,
    RunOutcome,
    SelectionMember,
    Severity,
    SourceCustodyGeneration,
    SourceCustodyRef,
    SourceFile,
    VerificationState,
    Verdict,
    canonical_bytes,
    canonical_digest,
    parse_json_strict,
)


CAMPAIGN_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_CAMPAIGN_ID = UUID("00000000-0000-4000-8000-000000000002")
SUBJECT_ID = UUID("10000000-0000-4000-8000-000000000001")
OCCURRENCE_ID = UUID("20000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 9, 12, 30, tzinfo=timezone.utc)


def _item(
    *,
    item_id: str = "item-1",
    subject_id: UUID = SUBJECT_ID,
    occurrence_id: UUID = OCCURRENCE_ID,
    custody_sha256: str = "f" * 64,
    semantic_sha256: str = "a" * 64,
    display_line: int = 14,
) -> ReviewItem:
    return ReviewItem(
        item_id=item_id,
        revision=1,
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        domain="npc_finding",
        subject_ref={
            "subject_id": subject_id,
            "kind": "entity",
            "registry_name": "Sister Garaele",
            "registry_type": "npc",
            "registry_snapshot_sha256": "b" * 64,
        },
        occurrence_id=occurrence_id,
        locator={
            "source_path": "docs/npcs/summary_native/sister-garaele.md",
            "anchor": "history",
            "display_line": display_line,
        },
        claim_text="  She said ‘Wait!’ — exactly.  \n",
        evidence=(
            {
                "source_id": "summary-54",
                "source_path": "summaries/054/session-summary.md",
                "anchor": "scene-054-02",
                "exact_excerpt": "  She said ‘Wait!’ — exactly.  \n",
                "selected_span_sha256": "c" * 64,
                "citation_resolved": True,
                "support": "unassessed",
            },
        ),
        diagnostics=(
            {
                "diagnostic_id": "quote-check",
                "legacy_code": "quote-not-found",
                "message": "Quoted span requires review",
                "blocking": True,
            },
        ),
        categories={FindingCategory.UNSUPPORTED_OR_CONTRADICTED},
        severity=Severity.BLOCKING,
        assignment_basis=AssignmentBasis.MECHANICAL,
        rationale="The exactness claim has not passed.",
        proposed_action={"action": "review_no_change_or_correct", "details": {}},
        scope={"kind": "evidence", "value": "scene-054-02"},
        rule_versions=(
            {"rule_id": "claimed-verbatim", "version": "1", "sha256": "d" * 64},
        ),
        input_bindings=(
            {
                "source_id": "summary-54",
                "path": "summaries/054/session-summary.md",
                "custody_sha256": custody_sha256,
                "semantic_sha256": semantic_sha256,
            },
        ),
    )


def _item_reference(item: ReviewItem, *, campaign_id: UUID = CAMPAIGN_ID) -> ItemReference:
    assert item.review_digest is not None
    return ItemReference(
        campaign_id=campaign_id,
        review_id=item.review_id,
        item_id=item.item_id,
        revision=item.revision,
        review_digest=item.review_digest,
    )


def _manifest(*items: ItemReference) -> ReviewManifest:
    return ReviewManifest(
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        kind="npc_verification",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=({"kind": "subject", "id": "sister-garaele"},),
        items=items,
        source_manifest={
            "campaign_id": CAMPAIGN_ID,
            "review_id": "review-1",
            "generation": 1,
            "digest": "e" * 64,
        },
        rule_versions=({"rule_id": "claimed-verbatim", "version": "1"},),
    )


def _decision(
    *,
    verdict: Verdict = Verdict.APPROVE,
    disposition: DecisionDisposition = DecisionDisposition.ACCEPT_NO_CHANGE,
    authority_record_id: str | None = "review-decision-1",
    proposal_id: str | None = None,
    proposal_digest: str | None = None,
) -> DecisionEvent:
    item = _item()
    assert item.review_digest is not None
    return DecisionEvent(
        event_id="event-1",
        request_id="request-1",
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        item_id="item-1",
        item_revision=1,
        review_digest=item.review_digest,
        expected_decision_revision=0,
        decision_revision=1,
        verdict=verdict,
        disposition=disposition,
        note="  preserve my note exactly  \n",
        reviewer="GM",
        recorded_at=NOW,
        authority_record_id=authority_record_id,
        proposal_id=proposal_id,
        proposal_digest=proposal_digest,
    )


def test_review_config_is_strict_and_owns_security_limits(tmp_path: Path):
    config = ReviewConfig()
    assert config.grant_expiry_seconds == DEFAULT_GRANT_EXPIRY_SECONDS == 86_400
    assert config.max_request_bytes == DEFAULT_MAX_REQUEST_BYTES == 1_048_576
    assert config.max_note_chars == DEFAULT_MAX_NOTE_CHARS == 16_384
    assert config.max_batch_decisions == DEFAULT_MAX_BATCH_DECISIONS == 100
    assert config.max_page_items == DEFAULT_MAX_PAGE_ITEMS == 50
    assert config.max_response_bytes == DEFAULT_MAX_RESPONSE_BYTES == 8_388_608
    assert config.command_timeout_seconds == DEFAULT_COMMAND_TIMEOUT_SECONDS == 30
    assert config.bind_host is None and config.origin is None

    path = tmp_path / "review.yaml"
    path.write_text("max_page_items: 25\nunknown_limit: 9\n", encoding="utf-8")
    with pytest.raises(ReviewConfigError, match="unknown_limit"):
        load_review_config(path)


def test_review_config_requires_a_complete_private_endpoint():
    with pytest.raises(ValidationError, match="configured together"):
        ReviewConfig(bind_host="127.0.0.1")
    with pytest.raises(ValidationError, match="wildcard"):
        ReviewConfig(bind_host="0.0.0.0", origin="http://127.0.0.1:8766")
    with pytest.raises(ValidationError, match="private"):
        ReviewConfig(bind_host="8.8.8.8", origin="http://8.8.8.8:8766")
    assert ReviewConfig(
        bind_host="100.64.0.10", origin="https://review.tailnet.ts.net"
    ).origin == "https://review.tailnet.ts.net"


def test_campaign_and_config_resolution_rejects_contradictory_roots(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "config").mkdir(parents=True)
        (root / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")

    assert resolve_campaign_scope(campaign_dir=first) == (first.resolve(), None)
    assert resolve_campaign_scope(config=first / "config" / "config.yaml") == (
        first.resolve(),
        (first / "config" / "config.yaml").resolve(),
    )
    with pytest.raises(ReviewConfigError, match="different campaigns"):
        resolve_campaign_scope(
            config=first / "config" / "config.yaml", campaign_dir=second
        )


def test_strict_json_refuses_duplicate_keys_and_nonfinite_numbers():
    with pytest.raises(ReviewModelError, match="duplicate JSON key 'item_id'"):
        parse_json_strict('{"item_id":"one","nested":{"item_id":"two","item_id":"three"}}')
    with pytest.raises(ReviewModelError, match="nonfinite"):
        parse_json_strict('{"score":NaN}')
    with pytest.raises(ReviewModelError, match="nonfinite"):
        canonical_bytes({"score": float("inf")})


def test_models_refuse_unknown_fields_and_unsupported_versions():
    item = _item()
    payload = item.model_dump(mode="python")
    payload["version"] = 2
    with pytest.raises(ValidationError, match="version"):
        ReviewItem.model_validate(payload)

    payload = item.model_dump(mode="python")
    payload["browser_only_state"] = "saved"
    with pytest.raises(ValidationError, match="browser_only_state"):
        ReviewItem.model_validate(payload)


def test_manifest_refuses_duplicate_ids_and_cross_campaign_references():
    item = _item()
    reference = _item_reference(item)
    with pytest.raises(ValidationError, match="duplicate review item id"):
        _manifest(reference, reference)
    with pytest.raises(ValidationError, match="another campaign"):
        _manifest(_item_reference(item, campaign_id=OTHER_CAMPAIGN_ID))

    payload = _manifest(reference).model_dump(mode="python")
    payload["selection"] = [
        {"kind": "subject", "id": "same"},
        {"kind": "subject", "id": "same"},
    ]
    with pytest.raises(ValidationError, match="duplicate selection id"):
        ReviewManifest.model_validate(payload)


def test_source_custody_generation_refuses_duplicate_paths_and_hashes_full_files():
    source = SourceFile(
        source_id="summary-54",
        path="summaries/054/session-summary.md",
        sha256="a" * 64,
        size=123,
    )
    generation = SourceCustodyGeneration(
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        generation=1,
        recorded_at=NOW,
        sources=(source,),
    )
    assert generation.custody_digest == canonical_digest(
        generation, exclude_fields=frozenset({"custody_digest"})
    )
    changed = SourceCustodyGeneration(
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        generation=1,
        recorded_at=NOW,
        sources=(source.model_copy(update={"sha256": "b" * 64}),),
    )
    assert generation.custody_digest != changed.custody_digest

    with pytest.raises(ValidationError, match="duplicate source path"):
        SourceCustodyGeneration(
            campaign_id=CAMPAIGN_ID,
            review_id="review-1",
            generation=1,
            recorded_at=NOW,
            sources=(source, source.model_copy(update={"source_id": "summary-copy"})),
        )


def test_exact_claim_evidence_and_note_text_are_never_normalized():
    item = _item()
    assert item.claim_text == "  She said ‘Wait!’ — exactly.  \n"
    assert item.evidence[0].exact_excerpt == "  She said ‘Wait!’ — exactly.  \n"
    decision = _decision()
    assert decision.note == "  preserve my note exactly  \n"
    encoded = canonical_bytes({"z": "é", "a": item.claim_text})
    assert encoded == (
        '{"a":"  She said ‘Wait!’ — exactly.  \\n","z":"é"}'.encode("utf-8")
    )
    assert not encoded.endswith(b"\n")


def test_semantic_digest_ignores_display_and_full_file_custody_only():
    first = _item(display_line=14, custody_sha256="1" * 64)
    second = _item(display_line=999, custody_sha256="2" * 64)
    assert first.review_digest == second.review_digest
    assert canonical_digest(first) != canonical_digest(second)


def test_same_text_is_isolated_by_subject_and_occurrence_identity():
    first = _item()
    another_subject = _item(
        item_id="item-2",
        subject_id=UUID("10000000-0000-4000-8000-000000000002"),
    )
    another_occurrence = _item(
        item_id="item-3",
        occurrence_id=UUID("20000000-0000-4000-8000-000000000002"),
    )
    assert len(
        {first.review_digest, another_subject.review_digest, another_occurrence.review_digest}
    ) == 3


def test_review_digest_refuses_tampering():
    payload = _item().model_dump(mode="python")
    payload["review_digest"] = "0" * 64
    with pytest.raises(ValidationError, match="does not match"):
        ReviewItem.model_validate(payload)


def test_verdicts_have_distinct_meanings():
    assert _decision().disposition is DecisionDisposition.ACCEPT_NO_CHANGE
    assert _decision(
        verdict=Verdict.REJECT,
        disposition=DecisionDisposition.REJECT_ACTION,
        authority_record_id=None,
    ).verdict is Verdict.REJECT
    assert _decision(
        disposition=DecisionDisposition.DISTINCT,
    ).disposition is DecisionDisposition.DISTINCT

    with pytest.raises(ValidationError, match="reject cannot mean merge"):
        _decision(
            verdict=Verdict.REJECT,
            disposition=DecisionDisposition.MERGE,
            authority_record_id=None,
            proposal_id="merge-1",
            proposal_digest="a" * 64,
        )
    with pytest.raises(ValidationError, match="requires an exact proposal"):
        _decision(disposition=DecisionDisposition.MERGE)


def test_state_axes_are_independent_and_settled_has_a_precise_meaning():
    state = ReviewState(
        disposition=DispositionState.APPROVED,
        freshness=FreshnessState.STALE,
        verification=VerificationState.FAILED_MECHANICAL,
        application=ApplicationState.COMMITTED,
    )
    assert not state.settled
    assert state.disposition is DispositionState.APPROVED
    assert state.verification is VerificationState.FAILED_MECHANICAL
    assert state.application is ApplicationState.COMMITTED
    assert ReviewState(disposition="approved", freshness="current").settled


def test_selection_members_refuse_cross_campaign_and_duplicate_checks():
    item = _item()
    assert item.review_digest is not None
    member = SelectionMember(
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        item_id="item-1",
        item_revision=1,
        review_digest=item.review_digest,
        check_ids=("citation",),
        dependency_hashes={"summary": "a" * 64},
    )
    payload = member.model_dump(mode="python")
    payload["check_ids"] = ("citation", "citation")
    with pytest.raises(ValidationError, match="duplicate check id"):
        SelectionMember.model_validate(payload)


def test_run_member_does_not_turn_failure_or_interruption_into_pass():
    assert RunMember(
        item_id="item-1",
        item_revision=1,
        check_id="citation",
        outcome=RunOutcome.COMPLETED,
        result_digest="a" * 64,
    ).outcome is RunOutcome.COMPLETED
    with pytest.raises(ValidationError, match="completed member requires"):
        RunMember(
            item_id="item-1",
            item_revision=1,
            check_id="citation",
            outcome=RunOutcome.COMPLETED,
        )
    interrupted = RunMember(
        item_id="item-1",
        item_revision=1,
        check_id="citation",
        outcome=RunOutcome.UNPROCESSED,
        message="worker stopped before this check",
    )
    assert interrupted.outcome is RunOutcome.UNPROCESSED


def test_records_are_immutable():
    item = _item()
    with pytest.raises(ValidationError, match="frozen"):
        item.claim_text = "changed"  # type: ignore[misc]


def test_source_manifest_reference_keeps_campaign_and_review_binding():
    reference = SourceCustodyRef(
        campaign_id=CAMPAIGN_ID,
        review_id="review-1",
        generation=1,
        digest="a" * 64,
    )
    assert reference.campaign_id == CAMPAIGN_ID
    assert reference.review_id == "review-1"
