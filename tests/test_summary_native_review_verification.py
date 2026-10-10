"""US2 verification taxonomy, semantic-boundary, and exactness contracts."""

from __future__ import annotations

from uuid import UUID

from pipelines.summary_native import npc_verify
from pipelines.summary_native.npc_verify import Finding, VerificationResult
from pipelines.summary_native.review.models import (
    AssignmentBasis,
    FindingCategory,
    RuleBinding,
    Severity,
    SubjectReference,
    SupportAssessment,
)
from pipelines.summary_native.review.verification import (
    SelectedNpcVerification,
    adapt_selected_verifications,
)


CAMPAIGN_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT = SubjectReference(
    subject_id=UUID("22222222-2222-4222-8222-222222222222"),
    kind="entity",
    registry_name="Fixture NPC",
    registry_type="npc",
    registry_snapshot_sha256="a" * 64,
)


def _selection(
    result: VerificationResult,
    *,
    draft_text: str,
    evidence_text: str,
    rule_versions: tuple[RuleBinding, ...] = (),
) -> SelectedNpcVerification:
    return SelectedNpcVerification(
        selection_id="fixture-npc",
        subject_ref=SUBJECT,
        draft_source_id="fixture-draft",
        draft_path="docs/npcs/fixture-npc.md",
        draft_text=draft_text,
        evidence_source_id="fixture-evidence",
        evidence_path="docs/npcs/evidence/fixture-npc.md",
        evidence_text=evidence_text,
        result=result,
        rule_versions=rule_versions,
    )


def _adapt(selection: SelectedNpcVerification):
    return adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID,
        review_id="verification-contract",
        selected=[selection],
    )


def test_lossless_adapter_retains_every_legacy_code_and_all_seven_categories():
    legacy_failures = [
        Finding(code, line, f"legacy {code}", f"original detail for {code}")
        for line, code in enumerate(npc_verify.FAIL_CODES, 1)
    ]
    legacy_advisories = [
        Finding(npc_verify.TYPOGRAPHY, 8, "curly typography", "quote marks differ"),
        Finding(npc_verify.STATUS_UNSUPPORTED, 9, "third", "ordinal absent from evidence"),
        Finding(npc_verify.PLACEHOLDER, 10, "Speaker", "attribution is a placeholder"),
    ]
    extended = [
        Finding("later-source-supersedes", 11, "old title", "reviewed metadata has a later title"),
        Finding("knowledge-leak", 12, "secret", "audience grants exclude players"),
        Finding("verifier-timeout", 13, "request", "selected checker timed out"),
    ]
    result = VerificationResult(
        verdict=npc_verify.FAIL,
        failures=[*legacy_failures, extended[-1]],
        advisories=[*legacy_advisories, *extended[:-1]],
        counts={
            finding.code: 1
            for finding in [*legacy_failures, *legacy_advisories, *extended]
        },
    )
    lines = [f"draft line {number}" for number in range(1, 14)]

    items = _adapt(_selection(
        result,
        draft_text="\n".join(lines) + "\n",
        evidence_text="fixture evidence does not erase the original diagnostics\n",
    ))

    expected_codes = {
        *npc_verify.FAIL_CODES,
        npc_verify.TYPOGRAPHY,
        npc_verify.STATUS_UNSUPPORTED,
        npc_verify.PLACEHOLDER,
        "later-source-supersedes",
        "knowledge-leak",
        "verifier-timeout",
    }
    by_code = {item.diagnostics[0].legacy_code: item for item in items}
    assert set(by_code) == expected_codes
    assert {
        category for item in items for category in item.categories
    } == set(FindingCategory)
    for finding in [*legacy_failures, *legacy_advisories, *extended]:
        diagnostic = by_code[finding.code].diagnostics[0]
        assert diagnostic.message == finding.detail
        assert diagnostic.details["text"] == finding.text
        assert diagnostic.details["detail"] == finding.detail


def test_valid_citation_is_not_semantic_support_for_false_ordinal_entailment():
    """#506: pointer success cannot certify a second/third claim mismatch."""
    result = VerificationResult(
        verdict=npc_verify.PASS,
        failures=[],
        advisories=[],
        counts={code: 0 for code in (
            *npc_verify.FAIL_CODES,
            npc_verify.TYPOGRAPHY,
            npc_verify.STATUS_UNSUPPORTED,
            npc_verify.PLACEHOLDER,
        )},
        totals={"citations": 1, "citations_valid": 1},
    )
    items = _adapt(_selection(
        result,
        draft_text="The third simulacrum guarded the vault. [ch 054 / 054.01]\n",
        evidence_text="The second simulacrum guarded the vault.\n",
    ))

    assert len(items) == 1
    item = items[0]
    assert item.categories == frozenset({FindingCategory.CITATION_NON_ENTAILMENT})
    assert item.severity is Severity.NEEDS_JUDGMENT
    assert item.assignment_basis is AssignmentBasis.ADVISORY_CANDIDATE
    assert item.evidence[0].citation_resolved is True
    assert item.evidence[0].support is SupportAssessment.UNASSESSED
    assert item.evidence[0].support is not SupportAssessment.GM_SUPPORTED
    assert item.diagnostics[0].blocking is False


def test_typography_only_is_advisory_when_exactness_is_not_declared():
    finding = Finding(
        npc_verify.TYPOGRAPHY,
        1,
        "Don’t follow me.",
        "differs only in quote marks or apostrophes",
    )
    result = VerificationResult(
        verdict=npc_verify.PASS,
        failures=[],
        advisories=[finding],
        counts={npc_verify.TYPOGRAPHY: 1},
    )

    item, = _adapt(_selection(
        result,
        draft_text="Don’t follow me.\n",
        evidence_text="Don't follow me.\n",
    ))

    assert item.categories == frozenset({FindingCategory.TYPOGRAPHY_PRESENTATION})
    assert item.severity is Severity.ADVISORY
    assert item.assignment_basis is AssignmentBasis.MECHANICAL
    assert item.diagnostics[0].blocking is False


def test_claimed_verbatim_typography_difference_remains_mechanically_blocking():
    finding = Finding(
        npc_verify.TYPOGRAPHY,
        1,
        "Don’t follow me.",
        "differs only in quote marks or apostrophes",
    )
    result = VerificationResult(
        verdict=npc_verify.PASS,
        failures=[],
        advisories=[finding],
        counts={npc_verify.TYPOGRAPHY: 1},
    )

    item, = _adapt(_selection(
        result,
        draft_text="Don’t follow me.\n",
        evidence_text="Don't follow me.\n",
        rule_versions=(RuleBinding(rule_id="claimed-verbatim", version="1"),),
    ))

    assert item.categories == frozenset({FindingCategory.TYPOGRAPHY_PRESENTATION})
    assert item.severity is Severity.BLOCKING
    assert item.assignment_basis is AssignmentBasis.MECHANICAL
    assert item.diagnostics[0].blocking is True

