"""T029/T030 scoped NPC checks and deterministic semantic candidates."""

from __future__ import annotations

from uuid import UUID

import pytest

from pipelines.summary_native import npc_verify
from pipelines.summary_native.review.models import (
    AssignmentBasis,
    FindingCategory,
    Severity,
    SubjectReference,
)
from pipelines.summary_native.review.verification import (
    ExplicitEvidenceMetadata,
    SelectedNpcVerification,
    adapt_selected_verifications,
    run_selected_npc_checks,
)


CAMPAIGN_ID = UUID("11111111-1111-4111-8111-111111111111")
SUBJECT = SubjectReference(
    subject_id=UUID("22222222-2222-4222-8222-222222222222"),
    kind="entity",
    registry_name="The Warden",
    registry_type="npc",
    registry_snapshot_sha256="a" * 64,
)
CORPUS = npc_verify.CorpusIndex(
    chapters=frozenset({2}),
    scenes=frozenset({"002.01"}),
)
EVIDENCE = """---
subject: The Warden
---

## Chapter 002

### Entry — The Warden
- Source: summary.md (line 2)

The first gate remained open.

### Scene 002.01 — The Sealed Vault (mentioned)
- Source: summary.md (line 8)

The second simulacrum guarded 2 seals. The Warden remained alive.
"""
DRAFT = """## History with the Party

- The second simulacrum guarded 2 seals. [ch 002 / 002.01] [manual 1]

## Last Observed State

The Warden remained alive. [ch 002 / 002.01]

## Notable Quotes

"The first gate remained open." [ch 002 / entry]
"""


def _empty_result() -> npc_verify.VerificationResult:
    return npc_verify.VerificationResult(
        verdict=npc_verify.PASS,
        failures=[],
        advisories=[],
        counts={},
    )


def _selection(
    draft_text: str,
    *,
    evidence_text: str = EVIDENCE,
    metadata: tuple[ExplicitEvidenceMetadata, ...] = (),
) -> SelectedNpcVerification:
    return SelectedNpcVerification(
        selection_id="warden",
        subject_ref=SUBJECT,
        draft_source_id="warden-draft",
        draft_path="docs/npcs/draft/warden.md",
        draft_text=draft_text,
        evidence_source_id="warden-evidence",
        evidence_path="docs/npcs/evidence/warden.md",
        evidence_text=evidence_text,
        result=_empty_result(),
        explicit_evidence_metadata=metadata,
    )


def _adapt(selection: SelectedNpcVerification):
    return adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID,
        review_id="scoped-verification",
        selected=[selection],
    )


def test_complete_aggregator_is_exactly_the_five_scoped_checks():
    aggregate = npc_verify.verify(DRAFT, EVIDENCE, CORPUS, "", ["Keep the seal count."])
    explicitly_scoped = npc_verify.verify_scoped(
        DRAFT,
        EVIDENCE,
        CORPUS,
        "",
        ["Keep the seal count."],
        npc_verify.CHECK_IDS,
    )

    assert aggregate.to_dict() == explicitly_scoped.to_dict()
    assert aggregate.totals == {
        "citations": 3,
        "citations_valid": 3,
        "quotes": 0,
        "quotes_by_source": {},
        "quoted_spans": 1,
        "history_bullets": 1,
        "manual_edits": 1,
    }


def test_selected_runner_invokes_only_literal_check_ids(monkeypatch: pytest.MonkeyPatch):
    called: list[str] = []

    def instrument(name, original):
        def run(context):
            called.append(name)
            return original(context)
        return run

    originals = {
        check_id: checker
        for check_id, checker in npc_verify.scoped_checkers().items()
    }
    monkeypatch.setattr(
        npc_verify,
        "check_citations",
        instrument(npc_verify.CITATION_CHECK, originals[npc_verify.CITATION_CHECK]),
    )
    monkeypatch.setattr(
        npc_verify,
        "check_status_words",
        instrument(npc_verify.STATUS_CHECK, originals[npc_verify.STATUS_CHECK]),
    )
    for attribute in ("check_quotes", "check_history", "check_manual"):
        monkeypatch.setattr(
            npc_verify,
            attribute,
            lambda _context, name=attribute: pytest.fail(f"unselected checker ran: {name}"),
        )

    result = run_selected_npc_checks(
        _selection(DRAFT),
        corpus_index=CORPUS,
        summaries_text="",
        manual=["Keep the seal count."],
        check_ids=(npc_verify.CITATION_CHECK, npc_verify.STATUS_CHECK),
    )

    assert called == [npc_verify.CITATION_CHECK, npc_verify.STATUS_CHECK]
    assert set(result.totals) == {"citations", "citations_valid"}
    assert result.manual == []


def test_number_and_ordinal_candidates_bind_the_exact_claim_and_cited_occurrence():
    draft = """## History with the Party

- The first gate remained open. [ch 002 / entry]
- The third simulacrum guarded 3 seals. [ch 002 / 002.01]
"""
    items = _adapt(_selection(draft))
    by_code = {item.diagnostics[0].legacy_code: item for item in items}

    assert set(by_code) == {"ordinal-inconsistency"}
    mismatch = by_code["ordinal-inconsistency"]
    assert mismatch.locator.display_line == 4
    assert mismatch.claim_text == "- The third simulacrum guarded 3 seals. [ch 002 / 002.01]"
    assert mismatch.evidence[0].exact_excerpt == (
        "The second simulacrum guarded 2 seals. The Warden remained alive."
    )
    assert mismatch.evidence[0].citation_resolved is True
    assert mismatch.categories == frozenset({FindingCategory.CITATION_NON_ENTAILMENT})
    assert mismatch.severity is Severity.NEEDS_JUDGMENT
    assert mismatch.assignment_basis is AssignmentBasis.ADVISORY_CANDIDATE


def test_same_citation_inconsistency_requires_matching_claim_shape_and_occurrence():
    draft = """## History with the Party

- The second simulacrum guarded the vault. [ch 002 / 002.01]
- The third simulacrum guarded the vault. [ch 002 / 002.01]
- The first gate remained open. [ch 002 / entry]
"""
    items = _adapt(_selection(draft))
    by_code = {}
    for item in items:
        by_code.setdefault(item.diagnostics[0].legacy_code, []).append(item)

    assert len(by_code["ordinal-inconsistency"]) == 1
    assert len(by_code["same-citation-inconsistency"]) == 1
    same = by_code["same-citation-inconsistency"][0]
    assert same.locator.display_line == 4
    assert "line 3" in same.diagnostics[0].message
    assert all(item.locator.display_line != 5 for values in by_code.values() for item in values)


def test_numeric_candidate_is_not_satisfied_by_a_number_in_an_unrelated_occurrence():
    draft = """## History with the Party

- The gate had 3 seals. [ch 002 / 002.01]
- The first gate remained open. [ch 002 / entry]
"""
    items = _adapt(_selection(draft))

    numeric, = (
        item for item in items
        if item.diagnostics[0].legacy_code == "number-inconsistency"
    )
    assert numeric.locator.display_line == 3
    assert "2 seals" in numeric.evidence[0].exact_excerpt
    assert all(item.locator.display_line != 4 for item in items)


def test_supersession_and_audience_findings_require_explicit_bound_metadata():
    draft = "Old title remains in the dossier.\nPlayers learn the hidden name.\n"
    unencoded = _adapt(_selection(draft, evidence_text="Old title. Hidden name."))
    assert unencoded == ()

    encoded = _adapt(_selection(
        draft,
        evidence_text="Old title. Hidden name.",
        metadata=(
            ExplicitEvidenceMetadata(
                line=1,
                text="Old title",
                source_id="summary-old",
                superseded_by_source_id="summary-new",
            ),
            ExplicitEvidenceMetadata(
                line=2,
                text="hidden name",
                source_id="gm-note",
                allowed_audiences=frozenset({"gm"}),
                requested_audience="players",
            ),
        ),
    ))
    by_code = {item.diagnostics[0].legacy_code: item for item in encoded}

    supersession = by_code["later-source-supersedes"]
    assert supersession.assignment_basis is AssignmentBasis.MECHANICAL
    assert supersession.severity is Severity.NEEDS_JUDGMENT
    assert supersession.diagnostics[0].blocking is False
    leak = by_code["knowledge-leak"]
    assert leak.assignment_basis is AssignmentBasis.MECHANICAL
    assert leak.severity is Severity.BLOCKING
    assert leak.diagnostics[0].blocking is True
    assert leak.categories == frozenset({FindingCategory.KNOWLEDGE_LEAK})


def test_explicit_metadata_must_name_exact_existing_claim_text():
    selection = _selection(
        "Only this claim exists.\n",
        metadata=(ExplicitEvidenceMetadata(
            line=1,
            text="invented claim",
            source_id="summary-old",
            superseded_by_source_id="summary-new",
        ),),
    )

    with pytest.raises(ValueError, match="not bound to an exact claim"):
        _adapt(selection)
