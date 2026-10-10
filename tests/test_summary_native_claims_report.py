from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipelines.summary_native.claims.check import annotations_from_active_ledger, bind_extraction_run, check_claims
from pipelines.summary_native.claims.models import CandidateRun, ChunkOutcome, ClaimAnnotation, ClaimPredicate, FindingResolution, SourceRole
from pipelines.summary_native.claims.report import (
    _require_current_run_revision, evaluate_report, render_markdown, write_report,
)
from pipelines.summary_native.claims.review import create_claim_review
from pipelines.summary_native.claims.selection import mandatory_source_closure
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.authority import (
    AudienceGrant, AuthorityLedger, Classification, EffectiveInterval, NoteRecord,
    Projection, SourceRef, SubjectRef, ledger_bytes,
)
import hashlib


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("claims_report_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


def _selection(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    return root, mandatory_source_closure(
        root, bundle, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",)
    )


def _annotation(selection, occurrence: str, *, predicate=ClaimPredicate.STATUS, value="active",
                certainty="certain", audience="gm", supersedes=None, state="mapping_confirmed",
                start="chapter-1", end="chapter-3", source_role=SourceRole.CLAIM):
    source = selection.sources[0]
    return ClaimAnnotation(
        occurrence_id=occurrence, revision=1, source_id=source.source_id, source_path=source.path,
        source_role=source_role, anchor=f"fixture:{occurrence}", start_byte=0, end_byte=4,
        source_sha256=source.sha256, span_sha256="a" * 64, context_sha256="b" * 64,
        original_span=f"evidence {occurrence} = {value}", subject_id="subject-1", predicate=predicate,
        normalized_value=value, certainty=certainty, effective_from=start, effective_until=end,
        audience=audience, origin="human_candidate", interpretation_state=state,
        mapping_event_id=f"event-{occurrence}" if state == "mapping_confirmed" else None,
        supersedes_occurrence_id=supersedes,
    )


@pytest.mark.parametrize(
    ("category", "left", "right"),
    [
        ("direct_contradiction", dict(predicate=ClaimPredicate.ACTOR, value="mara"), dict(predicate=ClaimPredicate.ACTOR, value="hale")),
        ("stale_superseded", dict(value="old"), dict(value="new", supersedes="left")),
        ("suspicion_as_fact", dict(predicate=ClaimPredicate.CERTAINTY, value="possible", certainty="possible"), dict(predicate=ClaimPredicate.CERTAINTY, value="certain", certainty="certain")),
        ("resolved_as_active", dict(value="active"), dict(value="resolved")),
        ("incompatible_state", dict(predicate=ClaimPredicate.LOCATION, value="gate"), dict(predicate=ClaimPredicate.LOCATION, value="road")),
    ],
)
def test_paired_rule_families_emit_exact_two_sided_evidence(tmp_path: Path, category, left, right) -> None:
    _root, selection = _selection(tmp_path)
    annotations = (_annotation(selection, "left", **left), _annotation(selection, "right", **right))
    analysis = check_claims(selection, annotations)
    finding = next(item for item in analysis.findings if category in item.categories)
    assert set(finding.annotation_ids) == {"left", "right"}
    assert finding.evidence == (annotations[0].original_span, annotations[1].original_span)


def test_audience_rule_pairs_annotation_with_exact_source_identity(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    annotation = _annotation(selection, "leak", audience="players")
    finding = next(item for item in check_claims(selection, (annotation,)).findings if "audience_leak" in item.categories)
    assert finding.annotation_ids == ("leak",)
    assert finding.source_ids == (selection.sources[0].source_id,)


def test_chapter_endpoints_compare_numerically_for_overlap_and_disjoint_ranges(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    overlap = check_claims(selection, (
        _annotation(selection, "left", value="gate", start="chapter-2", end="chapter-10"),
        _annotation(selection, "right", value="road", start="chapter-9", end="chapter-12"),
    ))
    assert any(item.basis == "mechanical" for item in overlap.findings)
    disjoint = check_claims(selection, (
        _annotation(selection, "left", value="gate", start="chapter-2", end="chapter-9"),
        _annotation(selection, "right", value="road", start="chapter-10", end="chapter-12"),
    ))
    assert not disjoint.findings


def test_mixed_or_unsupported_scope_is_a_visible_semantic_candidate(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    analysis = check_claims(selection, (
        _annotation(selection, "left", start="chapter-2", end="chapter-10"),
        _annotation(selection, "right", start="2026-10-01", end="2026-10-31"),
    ))
    finding = next(item for item in analysis.findings if item.rule_id == "semantic-scope")
    assert finding.annotation_ids == ("left", "right")
    assert finding.evidence == ("evidence left = active", "evidence right = active")


def test_unknown_time_scope_and_non_escalating_suspicion_are_not_mechanical_conflicts(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    unknown_time = (
        _annotation(selection, "a", value="one", start=None, end=None),
        _annotation(selection, "b", value="two", start=None, end=None),
    )
    assert not [item for item in check_claims(selection, unknown_time).findings if item.basis == "mechanical"]
    suspicions = (
        _annotation(selection, "c", predicate=ClaimPredicate.CERTAINTY, value="possible", certainty="possible"),
        _annotation(selection, "d", predicate=ClaimPredicate.CERTAINTY, value="probable", certainty="probable"),
    )
    assert not [item for item in check_claims(selection, suspicions).findings if "suspicion_as_fact" in item.categories]


def test_unreviewed_specific_candidate_stays_visible_while_empty_declared_scope_can_complete(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    candidate = _annotation(selection, "candidate", state="candidate")
    analysis = check_claims(selection, (candidate,))
    assert analysis.complete
    assert analysis.findings[0].basis == "semantic_candidate"
    assert analysis.findings[0].required_disposition
    empty = check_claims(selection, ())
    assert empty.complete and not empty.findings
    assert "No semantic mappings" in empty.coverage_limitations[0]


def test_equal_authority_conflict_blocks_without_selecting_a_winner(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    analysis = check_claims(selection, (
        _annotation(selection, "equal-a", predicate=ClaimPredicate.ACTOR, value="mara"),
        _annotation(selection, "equal-b", predicate=ClaimPredicate.ACTOR, value="hale"),
    ))
    finding = next(item for item in analysis.findings if "direct_contradiction" in item.categories)
    assert finding.decision_event_id is None
    assert finding.required_disposition


def test_preserved_supersession_history_passes_but_stale_draft_assertion_blocks(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    history = (
        _annotation(selection, "old-history", value="owed", source_role=SourceRole.COUNTERPART),
        _annotation(selection, "new-history", value="paid", supersedes="old-history",
                    source_role=SourceRole.COUNTERPART),
    )
    assert not [item for item in check_claims(selection, history).findings
                if "stale_superseded" in item.categories]
    stale_draft = (
        _annotation(selection, "old-draft", value="owed", source_role=SourceRole.CLAIM),
        _annotation(selection, "new-source", value="paid", supersedes="old-draft",
                    source_role=SourceRole.COUNTERPART),
    )
    assert [item for item in check_claims(selection, stale_draft).findings
            if "stale_superseded" in item.categories]


def test_report_keeps_analysis_acyclic_and_writes_immutable_owner_only_twins(tmp_path: Path) -> None:
    root, selection = _selection(tmp_path)
    analysis = check_claims(selection, (_annotation(selection, "candidate", state="candidate"),))
    blocked = evaluate_report(selection, analysis)
    finding_id = analysis.findings[0].finding_id
    resolved = evaluate_report(
        selection, analysis, resolutions=(FindingResolution(
            finding_id=finding_id, disposition="dismiss", rationale="The displayed prose does not assert the proposed meaning.",
            event_id="event-dismiss", decision_revision=1,
        ),)
    )
    assert blocked.analysis_digest == resolved.analysis_digest
    assert blocked.resolution_digest != resolved.resolution_digest
    assert blocked.outcome == "blocked" and resolved.outcome == "complete"
    json_path, markdown_path = write_report(root, resolved)
    assert json_path.stat().st_mode & 0o777 == 0o600
    assert markdown_path.stat().st_mode & 0o777 == 0o600
    assert json_path.parent.stat().st_mode & 0o777 == 0o700
    assert finding_id in markdown_path.read_text()
    assert write_report(root, resolved) == (json_path, markdown_path)


def test_mechanical_finding_cannot_be_waived_as_dismissal_or_uncertainty(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    analysis = check_claims(selection, (
        _annotation(selection, "left", predicate=ClaimPredicate.STATUS, value="active"),
        _annotation(selection, "right", predicate=ClaimPredicate.STATUS, value="resolved"),
    ))
    finding_id = analysis.findings[0].finding_id
    for disposition in ("dismiss", "accept_uncertainty"):
        with pytest.raises(ValueError, match="mechanical.*findings"):
            evaluate_report(selection, analysis, resolutions=(FindingResolution(
                finding_id=finding_id, disposition=disposition, rationale="Attempted waiver.",
                event_id="event-waiver", decision_revision=1,
            ),))


def test_gm_confirmed_finding_cannot_be_waived_and_confirmed_incorrect_stays_blocked(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    mechanical = check_claims(selection, (
        _annotation(selection, "left", value="active"),
        _annotation(selection, "right", value="resolved"),
    ))
    finding = mechanical.findings[0].model_copy(update={"basis": "gm_confirmed"})
    analysis = mechanical.__class__(**{**mechanical.__dict__, "findings": (finding,)})
    for disposition in ("dismiss", "accept_uncertainty"):
        with pytest.raises(ValueError, match="GM-confirmed"):
            evaluate_report(selection, analysis, resolutions=(FindingResolution(
                finding_id=finding.finding_id, disposition=disposition, rationale="Attempted waiver.",
                event_id="event-waiver", decision_revision=1,
            ),))
    report = evaluate_report(selection, analysis, resolutions=(FindingResolution(
        finding_id=finding.finding_id, disposition="confirm_incorrect", rationale="Source repair required.",
        event_id="event-confirm", decision_revision=2,
    ),))
    assert report.outcome == "blocked"
    markdown = render_markdown(report)
    assert "Resolution rationale: Source repair required." in markdown
    assert "Decision event: event-confirm" in markdown
    assert "Decision revision: 2" in markdown


def test_failed_declared_extraction_is_incomplete_not_coverage_only(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    analysis = check_claims(selection, (), extraction_run=_run(selection, "failed-run", complete=False))
    report = evaluate_report(selection, analysis)
    assert report.outcome == "incomplete"


def test_extraction_completion_and_authority_revision_change_analysis_and_report_identity(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    base = check_claims(selection, ())
    failed = check_claims(selection, (), extraction_run=_run(selection, "failed-run", complete=False))
    authority_changed = check_claims(selection, (), active_authority_ids=frozenset({"authority-r2"}))
    assert len({base.analysis_digest, failed.analysis_digest, authority_changed.analysis_digest}) == 3
    assert len({evaluate_report(selection, item).report_id for item in (base, failed, authority_changed)}) == 3


def _run(selection, run_id: str, *, complete: bool = True) -> CandidateRun:
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    outcome = ChunkOutcome(chunk_id="chunk-1", outcome="completed" if complete else "failed")
    return CandidateRun(
        run_id=run_id, revision=1, selection_digest=selection.selection_digest,
        packet_digest="a" * 64, backend="fixture", model="fixture", prompt_digest="b" * 64,
        rule_digest="c" * 64, chunk_ids=("chunk-1",), outcomes=(outcome,),
        created_at=now, completed_at=now if complete else None,
        failure_detail=None if complete else "failed",
    )


def test_distinct_completed_extraction_runs_change_analysis_and_report_identity(tmp_path: Path) -> None:
    _root, selection = _selection(tmp_path)
    first = check_claims(selection, (), extraction_run=_run(selection, "run-one"))
    second = check_claims(selection, (), extraction_run=_run(selection, "run-two"))
    assert first.extraction_complete is second.extraction_complete is True
    assert first.extraction_run.run_digest != second.extraction_run.run_digest
    assert first.analysis_digest != second.analysis_digest
    assert evaluate_report(selection, first).report_id != evaluate_report(selection, second).report_id
    wrong = _run(selection, "wrong").model_copy(update={"selection_digest": "f" * 64})
    with pytest.raises(ValueError, match="another source selection"):
        bind_extraction_run(selection, wrong)


def test_later_failed_extraction_revision_stales_prior_report_binding(tmp_path: Path) -> None:
    run_root = tmp_path / "runs/extract-same"
    (run_root / "rev-0001").mkdir(parents=True)
    _require_current_run_revision(run_root, 1)
    # A forced retry is the current declared revision even when it failed; an
    # older successful report cannot silently remain eligible.
    (run_root / "rev-0002").mkdir()
    with pytest.raises(PromotionError, match="current declared revision") as caught:
        _require_current_run_revision(run_root, 1)
    assert caught.value.code == "CLAIMS_REPORT_STALE"


def test_active_structured_authority_is_checked_without_candidate_reentry(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="another-review",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    source_path = root / "docs/tracking/fixture.txt"
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    records = []
    for record_id, value in (("actor-mara", "mara"), ("actor-hale", "hale")):
        records.append(NoteRecord(
            kind="note", id=record_id, revision=1, classification=Classification.CANON,
            subject=SubjectRef(kind="topic", id="earthstone-recovery"),
            claim_key=ClaimPredicate.ACTOR.value, normalized_value=value,
            effective=EffectiveInterval(from_chapter=1, through_chapter=3),
            audience=AudienceGrant(grants=frozenset({"gm"})),
            projections=frozenset({Projection.WORLD_STATE}), recorded_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
            recorded_by="gm", status="active",
            source=SourceRef(path="docs/tracking/fixture.txt", anchor=f"record:{record_id}"),
            content_digest=digest, selection_label=record_id,
        ))
    (root / "docs/authority.yaml").write_bytes(ledger_bytes(AuthorityLedger(
        version=2, campaign="promotion-fixture", revision=2, records=records, conflicts=[]
    )))
    selection = mandatory_source_closure(root, bundle, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",))
    annotations = annotations_from_active_ledger(root, selection)
    assert len(annotations) == 2
    active = {key: value for item in annotations for key, value in item.authority_record_digests.items()}
    analysis = check_claims(selection, annotations, active_authority_ids=active)
    assert any("direct_contradiction" in item.categories for item in analysis.findings)
    create_claim_review(
        root, "active-ledger-review", annotations=annotations, findings=analysis.findings,
        created_by="test", rule_versions=(("claims", "1"),),
    )
    from pipelines.summary_native.review.store import read_snapshot
    _manifest, custody, items = read_snapshot(root, "active-ledger-review")
    assert {item.path for item in custody.sources} == {"docs/authority.yaml"}
    assert all(item.evidence[0].missing_reason.startswith("Meaning is projected") for item in items)
