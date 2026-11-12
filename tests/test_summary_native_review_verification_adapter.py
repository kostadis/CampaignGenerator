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
            "In Chapter 036 the witness waited. [ch 003 / entry]\n"
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

    assert len(items) == 9
    assert {item.diagnostics[0].legacy_code for item in items} == {
        "invalid", "citation-mismatch", "not-found", "later-source-supersedes",
        "knowledge-leak", "verifier-timeout", "typography-normalised",
        "status-claim-unsupported", "noise-label",
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
    assert len(only_one) == 9
    assert len(both) == 18
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


# ---- spec 041 US1/US2: classified noise and per-sentence number checks ------------------------

from pipelines.summary_native import noise as noise_mod, npc_check


def _noise_selection(draft: str, evidence: str) -> SelectedNpcVerification:
    base = _selection()
    return SelectedNpcVerification(**{**base.__dict__,
        "draft_text": draft, "evidence_text": evidence,
        "result": VerificationResult(verdict="pass", failures=[], advisories=[], counts={})})


def _scenes(**by_scene: str) -> str:
    out = ["## Chapter 085", ""]
    for scene, body in by_scene.items():
        out += [f"### Scene {scene.replace('s', '085.', 1)} - t", "- Source: s.md (line 1)", "", body, ""]
    return "\n".join(out)


EV = _scenes(s07="The fleet of 200 ships gathers. Blasius paid 5 gp. A thousand giants... 1,000 giants wait.",
             s08="Only 12 remained.", s09="The second giant fell.")


def _adapt_one(draft: str, evidence: str = EV):
    return adapt_selected_verifications(
        campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[_noise_selection(draft, evidence)])


def _by_code(items):
    out: dict = {}
    for item in items:
        out.setdefault(item.diagnostics[0].legacy_code, []).append(item)
    return out


def _assert_noise_shape(item, cls):
    assert len(item.diagnostics) == 1
    assert item.diagnostics[0].legacy_code == f"noise-{cls}"
    assert item.categories == frozenset({FindingCategory.CLASSIFIED_NOISE})
    assert item.severity is Severity.ADVISORY
    assert item.diagnostics[0].blocking is False
    assert item.proposed_action.action == "review_classified_noise"
    assert item.proposed_action.details["legacy_code"] == f"noise-{cls}"


def test_chapter_label_is_noise_not_a_number_finding():
    codes = _by_code(_adapt_one("In Chapter 036, Blasius warns the party. [ch 085 / 085.07]\n"))
    assert set(codes) == {"noise-label"}
    _assert_noise_shape(codes["noise-label"][0], "label")
    assert codes["noise-label"][0].diagnostics[0].details["token"] == "036"


def test_spelled_number_matches_digits_and_is_classified():
    codes = _by_code(_adapt_one("Blasius paid five gold pieces. [ch 085 / 085.07]\n"))
    assert set(codes) == {"noise-spelled-number"}
    _assert_noise_shape(codes["noise-spelled-number"][0], "spelled-number")


def test_a_thousand_matches_comma_grouped_evidence():
    codes = _by_code(_adapt_one("About a thousand giants wait. [ch 085 / 085.07]\n"))
    assert set(codes) <= {"noise-spelled-number"}
    assert "number-inconsistency" not in codes


def test_unsupported_grouped_number_is_one_finding_with_the_token():
    codes = _by_code(_adapt_one("The vault held 5,000 gold. [ch 085 / 085.08]\n"))
    assert set(codes) == {"number-inconsistency"}
    d = codes["number-inconsistency"][0].diagnostics[0]
    assert d.details["tokens"] == ["5,000"]
    assert d.details["check"] == "number"
    assert d.details["cited_scenes"] == ["ch 085 / 085.08"]


def test_idiom_is_noise():
    codes = _by_code(_adapt_one("For the first time, he spoke. [ch 085 / 085.08]\n"))
    assert set(codes) == {"noise-idiom"}
    _assert_noise_shape(codes["noise-idiom"][0], "idiom")


def test_genuine_ordinal_is_still_a_finding():
    codes = _by_code(_adapt_one("The third giant to fall was Blasius. [ch 085 / 085.09]\n"))
    assert set(codes) == {"ordinal-inconsistency"}


def test_draft_bare_one_is_not_examined():
    assert _adapt_one("No one knew where one of them went. [ch 085 / 085.08]\n") == ()


def test_uncited_sentence_examines_nothing():
    assert _adapt_one("The vault held 5,000 gold.\n") == ()


def test_other_citation_when_number_is_in_one_of_two_cited_scenes():
    items = _adapt_one("Hekaton's fleet of 200 ships gathers. [ch 085 / 085.07] [ch 085 / 085.08]\n")
    codes = _by_code(items)
    assert set(codes) == {"noise-other-citation"}
    d = codes["noise-other-citation"][0].diagnostics[0]
    assert d.details["resolved_by"] == "ch 085 / 085.07"
    assert d.message == '"200" is in ch 085 / 085.07, which this sentence also cites'
    assert codes["noise-other-citation"][0].evidence[0].exact_excerpt.startswith("The fleet of 200")


def test_unsupported_in_every_cited_scene_names_token_and_both_scenes():
    items = _adapt_one("A fleet of 200 and 40 ships. [ch 085 / 085.07] [ch 085 / 085.08]\n")
    codes = _by_code(items)
    finding, = codes["number-inconsistency"]
    d = finding.diagnostics[0]
    assert d.details["tokens"] == ["40"]
    assert d.details["cited_scenes"] == ["ch 085 / 085.07", "ch 085 / 085.08"]
    assert d.message == (
        'draft says "40"; no scene this sentence cites contains it '
        "(cited: ch 085 / 085.07, ch 085 / 085.08)")
    assert [i.diagnostics[0].details["token"] for i in codes["noise-other-citation"]] == ["200"]


def test_each_finding_carries_only_its_own_sentence():
    draft = ("Alpha had 77 men. [ch 085 / 085.08] Beta had 88 men. [ch 085 / 085.08] "
             "Gamma had 12 men. [ch 085 / 085.08]\n")
    findings = _by_code(_adapt_one(draft))["number-inconsistency"]
    assert sorted(f.diagnostics[0].details["sentence"] for f in findings) == [
        "Alpha had 77 men. [ch 085 / 085.08]", "Beta had 88 men. [ch 085 / 085.08]"]
    assert all(f.claim_text == draft.rstrip("\n") for f in findings)


def test_multiple_unsupported_tokens_in_a_sentence_are_one_finding():
    findings = _by_code(_adapt_one("He had 77 men and 88 horses. [ch 085 / 085.08]\n"))["number-inconsistency"]
    assert len(findings) == 1
    assert findings[0].diagnostics[0].details["tokens"] == ["77", "88"]


def test_accounting_partitions_examined_tokens():
    draft = ("In Chapter 036 a fleet of 200 and 40 ships gathers. [ch 085 / 085.07] [ch 085 / 085.08]\n"
             "Blasius paid five gp for the first time. [ch 085 / 085.07]\n"
             "Only 12 remained. [ch 085 / 085.08]\n")
    analysis = noise_mod.analyse_numbers(
        draft, npc_check.EvidenceIndex.of(npc_check.split_chapters(EV)))
    acc = analysis.accounting
    acc.check()
    assert acc.examined == acc.supported + sum(acc.noise.values()) + acc.findings
    assert acc.findings == 1
    assert acc.supported == 1
    assert acc.noise["label"] == 1 and acc.noise["other-citation"] == 1
    assert acc.noise["spelled-number"] == 1 and acc.noise["idiom"] == 1


def test_same_citation_inconsistency_ignores_labels():
    draft = ("In Chapter 5 the gate held. [ch 085 / 085.08]\n"
             "In Chapter 6 the gate held. [ch 085 / 085.08]\n")
    assert "same-citation-inconsistency" not in _by_code(_adapt_one(draft))


# ---- spec 041 US3: status noise and status finding details (T023) ----------------------------

def _status_selection(draft, noise_records=(), advisories=()):
    base = _noise_selection(draft, EV)
    return SelectedNpcVerification(**{**base.__dict__, "result": VerificationResult(
        verdict="pass", failures=[], advisories=list(advisories), counts={}, noise=tuple(noise_records))})


def _adapt_sel(sel):
    return adapt_selected_verifications(campaign_id=CAMPAIGN_ID, review_id="npc-review", selected=[sel])


def test_status_noise_in_the_result_becomes_noise_items():
    draft = "He departed. [ch 085 / 085.07]\nNo further status (alive) is established. [ch 085 / 085.07]\n"
    recs = (
        noise_mod.NoiseRecord("status", "synonym", 1, "departed", "He departed. [ch 085 / 085.07]",
                              ("ch 085 / 085.07",), "leaves"),
        noise_mod.NoiseRecord("status", "negated-status", 2, "alive",
                              "No further status (alive) is established. [ch 085 / 085.07]",
                              ("ch 085 / 085.07",), "No further status (alive) is established"),
    )
    codes = _by_code(_adapt_sel(_status_selection(draft, recs)))
    assert set(codes) == {"noise-synonym", "noise-negated-status"}
    for cls, rec in (("synonym", recs[0]), ("negated-status", recs[1])):
        item, = codes[f"noise-{cls}"]
        _assert_noise_shape(item, cls)
        d = item.diagnostics[0].details
        assert d["check"] == "status" and d["token"] == rec.token and d["sentence"] == rec.sentence
        assert list(d["cited_scenes"]) == ["ch 085 / 085.07"] and d["resolved_by"] == rec.resolved_by


def test_status_finding_details_are_structured():
    draft = "Belg was captured. [ch 085 / 085.07]\n"
    f = Finding("status-claim-unsupported", 1, "Belg was captured. [ch 085 / 085.07]",
                'draft says "captured"; neither it nor a listed synonym appears in the evidence '
                "(sentence cites: ch 085 / 085.07)")
    item, = _adapt_sel(_status_selection(draft, advisories=[f]))
    d = item.diagnostics[0].details
    assert d["check"] == "status" and list(d["tokens"]) == ["captured"]
    assert d["sentence"] == f.text and list(d["cited_scenes"]) == ["ch 085 / 085.07"]


def test_number_noise_in_the_result_is_not_duplicated_by_the_adapter():
    draft = "In Chapter 036 the witness waited. [ch 085 / 085.07]\n"
    rec = noise_mod.NoiseRecord("number", "label", 1, "036", draft.strip(), ("ch 085 / 085.07",), "")
    without = _adapt_sel(_status_selection(draft))
    with_rec = _adapt_sel(_status_selection(draft, (rec,)))
    assert [i.diagnostics[0].legacy_code for i in with_rec] == [i.diagnostics[0].legacy_code for i in without]
    assert len(with_rec) == len(without) == 1
