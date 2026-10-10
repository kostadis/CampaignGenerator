from __future__ import annotations

from uuid import UUID

import pytest

from pipelines.summary_native.npc_verify import Finding, VerificationResult
from pipelines.summary_native.review.models import (
    AssignmentBasis,
    FindingCategory,
    Severity,
    SubjectReference,
)
from pipelines.summary_native.review.verification import (
    SelectedNpcVerification,
    VerificationAdapterError,
    adapt_selected_verifications,
)


CAMPAIGN_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT = SubjectReference(
    subject_id=UUID("22222222-2222-4222-8222-222222222222"),
    kind="entity",
    registry_name="Sister Garaele",
    registry_type="npc",
    registry_snapshot_sha256="a" * 64,
)


def _selection(*, selection_id: str = "sister-garaele") -> SelectedNpcVerification:
    failures = [
        Finding("invalid", 1, "[054.99]", "not in the in-range corpus"),
        Finding("citation-mismatch", 2, '"third simulacrum"', "quote belongs to another cited entry"),
        Finding("not-found", 3, '"invented claim"', "not verbatim in evidence"),
        Finding("later-source-supersedes", 4, "old title", "reviewed metadata names a later fact"),
        Finding("knowledge-leak", 5, "secret identity", "players are not granted this evidence"),
        Finding("verifier-timeout", 0, "verification request", "checker timed out before completion"),
    ]
    advisories = [
        Finding("typography-normalised", 6, '“third simulacrum”', "quote marks differ"),
        Finding("status-claim-unsupported", 7, "She was killed.", '"killed" appears nowhere in evidence'),
    ]
    return SelectedNpcVerification(
        selection_id=selection_id,
        subject_ref=SUBJECT,
        draft_source_id=f"draft-{selection_id}",
        draft_path=f"docs/npcs/{selection_id}.md",
        draft_text=(
            "History cites [054.99].\n"
            "She described the \"third simulacrum\".\n"
            "She made an invented claim.\n"
            "Her old title remained.\n"
            "Her secret identity was exposed.\n"
            "She said “third simulacrum”.\n"
            "She was killed.\n"
        ),
        evidence_source_id=f"evidence-{selection_id}",
        evidence_path=f"docs/npcs/evidence/{selection_id}.md",
        evidence_text='The witness described the "third simulacrum" and her old title.\n',
        result=VerificationResult(
            verdict="fail",
            failures=failures,
            advisories=advisories,
            counts={finding.code: 1 for finding in [*failures, *advisories]},
        ),
    )


def test_adapter_preserves_every_diagnostic_and_maps_all_seven_categories():
    items = adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID,
        review_id="npc-review",
        selected=[_selection()],
    )

    assert len(items) == 8
    assert {item.diagnostics[0].legacy_code for item in items} == {
        "invalid", "citation-mismatch", "not-found", "later-source-supersedes",
        "knowledge-leak", "verifier-timeout", "typography-normalised",
        "status-claim-unsupported",
    }
    assert {category for item in items for category in item.categories} == set(FindingCategory)

    mismatch = next(item for item in items if item.diagnostics[0].legacy_code == "citation-mismatch")
    assert mismatch.claim_text == 'She described the "third simulacrum".'
    assert mismatch.diagnostics[0].message == "quote belongs to another cited entry"
    assert mismatch.diagnostics[0].details == {
        "detail": "quote belongs to another cited entry",
        "line": 2,
        "text": '"third simulacrum"',
        "verdict": "fail",
    }
    assert mismatch.diagnostics[0].blocking is True
    assert mismatch.severity is Severity.BLOCKING
    assert mismatch.assignment_basis is AssignmentBasis.MECHANICAL
    assert {category.value for category in mismatch.categories} == {
        "missing_source_or_pointer", "citation_non_entailment",
    }
    assert mismatch.evidence[0].exact_excerpt == '"third simulacrum"'
    assert mismatch.evidence[0].source_path == "docs/npcs/evidence/sister-garaele.md"

    missing = next(item for item in items if item.diagnostics[0].legacy_code == "not-found")
    assert missing.evidence[0].exact_excerpt is None
    assert "not verbatim in evidence" in missing.evidence[0].missing_reason

    timeout = next(item for item in items if item.diagnostics[0].legacy_code == "verifier-timeout")
    assert timeout.claim_text is None
    assert timeout.failure_context == "verification request — checker timed out before completion"

    typography = next(item for item in items if item.diagnostics[0].legacy_code == "typography-normalised")
    assert typography.severity is Severity.ADVISORY
    assert typography.assignment_basis is AssignmentBasis.MECHANICAL
    status = next(item for item in items if item.diagnostics[0].legacy_code == "status-claim-unsupported")
    assert status.severity is Severity.NEEDS_JUDGMENT
    assert status.assignment_basis is AssignmentBasis.ADVISORY_CANDIDATE


def test_adapter_requires_explicit_nonempty_unique_selection_and_never_broadens_it():
    with pytest.raises(VerificationAdapterError, match="explicit nonempty"):
        adapt_selected_verifications(campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[])
    with pytest.raises(VerificationAdapterError, match="duplicate selection"):
        adapt_selected_verifications(
            campaign_id=CAMPAIGN_ID,
            review_id="npc-review",
            selected=[_selection(), _selection()],
        )

    one = _selection(selection_id="one")
    two = _selection(selection_id="two")
    only_one = adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[one],
    )
    both = adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[one, two],
    )
    assert len(only_one) == 8
    assert len(both) == 16
    assert all(item.locator.source_path == "docs/npcs/one.md" for item in only_one)


def test_adapter_is_deterministic_and_refuses_a_result_that_cannot_bind_exact_draft_text():
    selection = _selection()
    first = adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[selection],
    )
    second = adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[selection],
    )
    assert [item.model_dump(mode="json") for item in first] == [item.model_dump(mode="json") for item in second]

    malformed = SelectedNpcVerification(
        **{**selection.__dict__, "result": VerificationResult(
            verdict="fail",
            failures=[Finding("invalid", 99, "bad", "outside draft")],
            advisories=[], counts={"invalid": 1},
        )},
    )
    with pytest.raises(VerificationAdapterError, match="outside the exact draft"):
        adapt_selected_verifications(
            campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[malformed],
        )
