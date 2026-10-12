"""Regression tests for the #548 review findings against the claims checker.

Each test names the defect it pins. Every one fails on the pre-fix code
(origin/main at the time of the review), so a revert is visible here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipelines.summary_native.authority import (
    AudienceGrant, AuthorityLedger, Classification, EffectiveInterval, NoteRecord, Projection,
    SourceRef, SubjectRef, ledger_bytes,
)
from pipelines.summary_native.claims import cli as claims_cli
from pipelines.summary_native.claims.check import (
    _candidate, _compatible, annotations_from_active_ledger, check_claims,
)
from pipelines.summary_native.claims.extract import extract_candidates
from pipelines.summary_native.claims.imports import import_candidates
from pipelines.summary_native.claims.models import (
    CandidateRun, ChunkOutcome, ClaimAnnotation, ClaimFinding, ClaimPredicate, FindingResolution,
    SourceRole, SourceSelection,
)
from pipelines.summary_native.claims.packets import assemble_packet
from pipelines.summary_native.claims.report import (
    _private_read, evaluate_report, load_current_report, render_markdown, report_freshness,
)
from pipelines.summary_native.claims.review import (
    build_signoff_context, create_claim_review, load_current_resolutions, prepare_finding_disposition,
    validate_signoff_context,
)
from pipelines.summary_native.claims.selection import (
    confirm_selection, mandatory_source_closure, save_confirmed_selection, select_whole_source_chunks,
    validate_selection_against_bundle,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest
from pipelines.summary_native.review.store import append_review_items, history, read_snapshot, save_decisions
from tests.test_summary_native_claims_review import _campaign


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("claims_findings_548_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
RANGE = "docs/summary_native/ch001-003"


# ── shared fixtures ──────────────────────────────────────────────────────────

def _bundle(root: Path, review: str = "claims-selection"):
    return build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id=review,
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )


def _proposed(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = _bundle(root)
    return root, bundle, mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",),
    )


def _confirmed_with_chunks(tmp_path: Path, count: int = 1):
    root, bundle, proposed = _proposed(tmp_path)
    nonempty = [item.source_id for item in proposed.sources if (root / item.path).stat().st_size][:count]
    confirmed = confirm_selection(select_whole_source_chunks(root, proposed, tuple(nonempty)),
                                  reviewer="gm", confirmed_at=NOW)
    save_confirmed_selection(root, confirmed)
    selection_file = tmp_path / "selection.json"
    selection_file.write_bytes(canonical_bytes(confirmed))
    return root, bundle, confirmed, selection_file


def _annotation(selection, occurrence: str, *, predicate=ClaimPredicate.STATUS, value="active",
                certainty="certain", start="chapter-1", end="chapter-3", supersedes=None,
                state="mapping_confirmed", subject="subject-1", source_role=SourceRole.CLAIM):
    source = selection.sources[0]
    return ClaimAnnotation(
        occurrence_id=occurrence, revision=1, source_id=source.source_id, source_path=source.path,
        source_role=source_role, anchor=f"fixture:{occurrence}", start_byte=0, end_byte=4,
        source_sha256=source.sha256, span_sha256="a" * 64, context_sha256="b" * 64,
        original_span=f"evidence {occurrence} = {value}", subject_id=subject, predicate=predicate,
        normalized_value=value, certainty=certainty, effective_from=start, effective_until=end,
        audience="gm", origin="human_candidate", interpretation_state=state,
        mapping_event_id=f"event-{occurrence}" if state == "mapping_confirmed" else None,
        supersedes_occurrence_id=supersedes,
    )


def _note(root: Path, *, record_id="canon-note", classification=Classification.CANON,
          effective=None, value="safe", projections=frozenset({Projection.WORLD_STATE}), **extra):
    note_path = root / "docs/tracking/fixture.txt"
    return NoteRecord(
        kind="note", id=record_id, revision=1, classification=classification,
        subject=SubjectRef(kind="topic", id="lantern-road"), claim_key="status", normalized_value=value,
        effective=effective or EffectiveInterval(through_chapter=3),
        audience=AudienceGrant(grants=frozenset({"gm", "players"})), projections=projections,
        recorded_at=NOW, recorded_by="gm", status="active",
        source=SourceRef(path="docs/tracking/fixture.txt", anchor=f"heading:{record_id}"),
        content_digest=hashlib.sha256(note_path.read_bytes()).hexdigest(), selection_label=record_id, **extra,
    )


def _write_ledger(root: Path, *records) -> None:
    (root / "docs/authority.yaml").write_bytes(ledger_bytes(AuthorityLedger(
        version=2, campaign="promotion-fixture", revision=2, records=list(records), conflicts=[],
    )))


def _cli(argv: list[str], capsys) -> tuple[int, dict]:
    code = claims_cli.run(argv)
    return code, json.loads(capsys.readouterr().out)


# ── 1. --config means config/config.yaml (Principle XII) ─────────────────────

def test_claims_config_is_config_yaml_auto_detected_and_out_root_is_campaign_relative(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defect: claims --config was required, named grounding.yaml, and out_root resolved against config/.

    Every other summary_native subcommand takes config/config.yaml, optional and
    auto-detected; grounding.yaml is read beside it and out_root is campaign-relative.
    """
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    monkeypatch.chdir(root)
    code, output = _cli(["select", "--since", "1", "--until", "3", "--json"], capsys)
    assert code == 0, output
    assert output["data"]["selection"]["out_root"] == "docs/summary_native"
    assert any(item["path"] == "config/grounding.yaml" for item in output["data"]["selection"]["sources"])
    code, refused = _cli(["select", "--config", str(root / "config/grounding.yaml"),
                          "--since", "1", "--until", "3", "--json"], capsys)
    assert code == 2 and refused["code"] == "CLAIMS_CONFIG_INVALID"
    assert "config/config.yaml" in refused["message"]


# ── 2. a ruling stops settling when the meaning it ruled on changes ──────────

def _dismissed_review(tmp_path: Path):
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    data = (root / "summaries/001.md").read_bytes(); span = b"Exact claim evidence."
    original = ClaimAnnotation(
        occurrence_id="occ-1", revision=1, source_id="claim-source", source_path="summaries/001.md",
        source_role=SourceRole.CLAIM, anchor="bytes:0-21", start_byte=0, end_byte=len(span),
        source_sha256=hashlib.sha256(data).hexdigest(), span_sha256=hashlib.sha256(span).hexdigest(),
        context_sha256=hashlib.sha256(data).hexdigest(), original_span=span.decode(), subject_id="sridar",
        predicate=ClaimPredicate.CERTAINTY, normalized_value="possible", certainty="possible", audience="gm",
        origin="human_candidate", interpretation_state="candidate",
    )
    return root, original


def _dismiss(root: Path, review: str, finding: ClaimFinding) -> None:
    manifest, _custody, items = read_snapshot(root, review)
    item = next(value for value in items if value.item_id == f"finding-{finding.finding_id}")
    prepared = prepare_finding_disposition(item, alternative="dismiss", evidence=("displayed",),
                                           rationale="Only a suspicion; the draft is fine.",
                                           expected_decision_revision=0)
    append_review_items(root, review, expected_generation=manifest.generation, items=(prepared,), sources=())
    manifest, _custody, items = read_snapshot(root, review)
    item = next(value for value in items if value.item_id == f"finding-{finding.finding_id}")
    save_decisions(root, review, {
        "version": 1, "request_id": "dismiss-1", "review_generation": manifest.generation, "reviewer": "GM",
        "decisions": [{"item_id": item.item_id, "item_revision": item.revision, "review_digest": item.review_digest,
                       "expected_decision_revision": 0, "verdict": "approve", "disposition": "accept_no_change",
                       "note": "dismissed"}],
    })


@pytest.mark.parametrize("change", [
    {"normalized_value": "certain"}, {"certainty": "certain"},
    {"predicate": ClaimPredicate.FACTION}, {"subject_id": "other-subject"},
])
def test_dismissal_stops_settling_when_the_candidate_meaning_changes(tmp_path: Path, change) -> None:
    """Defect: a GM dismissal kept settling a semantic candidate after its subject/predicate/value/certainty changed.

    The finding id and semantic digest ignored the interpretation, and review
    retention compared only that digest, so the old ruling silently applied to a
    new meaning. US3 scenario 6: the old ruling stays in history but stops settling.
    """
    root, original = _dismissed_review(tmp_path)
    reason = "This exact prose meaning has not been reviewed."
    first = _candidate(original, reason)
    create_claim_review(root, "rv", annotations=(original,), findings=(first,), created_by="t",
                        rule_versions=(("claims", "1"),))
    _dismiss(root, "rv", first)
    assert [item.disposition for item in load_current_resolutions(root, "rv", (first,))] == ["dismiss"]

    changed = original.model_copy(update=change)
    second = _candidate(changed, reason)
    assert second.semantic_digest != first.semantic_digest
    create_claim_review(root, "rv", annotations=(changed,), findings=(second,), created_by="t",
                        rule_versions=(("claims", "1"),))
    assert load_current_resolutions(root, "rv", (second,)) == ()
    _manifest, _custody, items = read_snapshot(root, "rv")
    finding_item = next(item for item in items if item.item_id == f"finding-{second.finding_id}")
    assert finding_item.proposed_action.action == "resolve_claim_finding"
    assert any(event.get("kind") != "withdrawal" and event.get("item_id") == finding_item.item_id
               for event in history(root, "rv")), "the old ruling must remain in history"


def test_review_retention_compares_the_displayed_interpretations(tmp_path: Path) -> None:
    """Defect: create_claim_review retained a prior dismissal while annotation_interpretations changed.

    Even when a finding's own digest is unchanged, a different displayed meaning
    must earn a new unresolved revision rather than inherit the dismissal.
    """
    root, original = _dismissed_review(tmp_path)
    fixed = ClaimFinding(
        finding_id="pinned", revision=1, categories=("suspicion_as_fact",), annotation_ids=("occ-1",),
        rule_id="semantic-mapping", rule_version="1", audience="gm", effective_horizon="unknown",
        basis="semantic_candidate", severity="blocking", evidence=(original.original_span,),
        rationale="Review the meaning.", next_action="Judge it.", required_disposition=True,
        semantic_digest=hashlib.sha256(b"pinned").hexdigest(),
    )
    create_claim_review(root, "rv", annotations=(original,), findings=(fixed,), created_by="t",
                        rule_versions=(("claims", "1"),))
    _dismiss(root, "rv", fixed)
    assert load_current_resolutions(root, "rv", (fixed,))
    changed = original.model_copy(update={"normalized_value": "certain", "certainty": "certain"})
    create_claim_review(root, "rv", annotations=(changed,), findings=(fixed,), created_by="t",
                        rule_versions=(("claims", "1"),))
    assert load_current_resolutions(root, "rv", (fixed,)) == ()


# ── 3. effective scope uses #546's overlap rule ──────────────────────────────

def test_half_open_structured_authority_overlaps_a_bounded_draft_range(tmp_path: Path) -> None:
    """Defect: a structured record "through chapter 3" (no start) was incomparable to a ch1-3 draft.

    The record's absent bound is unbounded under #546's half-open interval, so the
    pair overlaps and a value conflict is mechanical, not a semantic-scope candidate.
    """
    root, _bundle_value, _proposed_value = _proposed(tmp_path)
    _write_ledger(root, _note(root, effective=EffectiveInterval(through_chapter=3)))
    selection = mandatory_source_closure(root, _bundle(root), effective_horizon="through-chapter-3",
                                         audience="gm", rule_versions=("claims/1",))
    (structured,) = annotations_from_active_ledger(root, selection)
    draft = _annotation(selection, "draft", value="unsafe", subject="lantern-road")
    authority = {key: value for source in selection.sources for key, value in source.authority_record_digests.items()}
    analysis = check_claims(selection, (structured, draft), active_authority_ids=authority)
    assert [(item.rule_id, item.basis) for item in analysis.findings] == [("state-compatibility", "mechanical")]


@pytest.mark.parametrize(("left", "right", "expected"), [
    (("open", "open"), ("future", "future"), EffectiveInterval(horizon="open").overlaps(EffectiveInterval(horizon="future"))),
    (("open", "open"), ("chapter-1", "chapter-3"), True),
    (("future", "future"), ("chapter-1", "chapter-3"), False),
    (("future", "future"), ("chapter-4", "open"), True),
    (("chapter-1", "chapter-3"), ("chapter-4", "chapter-6"), False),
    (("chapter-1", "chapter-3"), ("chapter-3", "chapter-6"), True),
])
def test_scope_comparison_agrees_with_the_authority_overlap_rule(tmp_path: Path, left, right, expected) -> None:
    """Defect: claims compared scope with its own rule; `open` vs `future` dropped the pair as non-overlapping.

    Projection onto EffectiveInterval reuses #546's ``overlaps`` so the checker
    and the authority ledger agree on when two assertions claim the same time.
    """
    _root, _bundle_value, selection = _proposed(tmp_path)
    a = _annotation(selection, "a", start=left[0], end=left[1], predicate=ClaimPredicate.LOCATION, value="gate")
    b = _annotation(selection, "b", start=right[0], end=right[1], predicate=ClaimPredicate.LOCATION, value="road")
    assert _compatible(a, b) is expected
    found = bool([item for item in check_claims(selection, (a, b)).findings if item.rule_id == "state-compatibility"])
    assert found is expected


# ── 4. an undeclared or failed extraction never reads as complete ────────────

def test_selected_chunks_with_no_run_and_no_import_are_incomplete(tmp_path: Path) -> None:
    """Defect: chunks selected for extraction with no completed run bound produced a "complete" report.

    A failed or undeclared selected extraction always blocks (data model), and
    the Markdown must not claim every declared input was checked.
    """
    root, _bundle_value, confirmed, _selection_file = _confirmed_with_chunks(tmp_path)
    report = evaluate_report(confirmed, check_claims(confirmed, ()), review_id="r")
    assert report.outcome == "incomplete" and report.extraction_complete is False
    markdown = render_markdown(report)
    assert "All declared deterministic inputs were checked" not in markdown
    assert "Incomplete" in markdown


def test_manual_mappings_disclose_uncovered_prose_even_with_annotations(tmp_path: Path) -> None:
    """Defect: the coverage limitation was disclosed only when there were zero annotations.

    Prose not covered by a completed extraction run is disclosed (and bound into
    each sign-off context) whenever it happens; the report exposes the identities
    the promotion receipt needs.
    """
    root, _bundle_value, confirmed, _selection_file = _confirmed_with_chunks(tmp_path)
    analysis = check_claims(confirmed, (_annotation(confirmed, "one"),))
    assert any("not covered by a completed extraction run" in item for item in analysis.coverage_limitations)
    report = evaluate_report(confirmed, analysis, review_id="r")
    assert report.outcome == "complete"
    assert "All declared deterministic inputs were checked" not in render_markdown(report)
    context = build_signoff_context(
        analysis_digest=report.analysis_digest, resolution_digest=report.resolution_digest,
        support_digest="c" * 64, audience="gm", rule_versions=(("claims", "1"),),
        coverage_limitations=report.coverage_limitations,
    )
    assert validate_signoff_context(context)["coverage_limitations"] == tuple(sorted(report.coverage_limitations))
    exposed = report.model_dump(mode="json")
    assert {"report_id", "analysis_digest", "resolution_digest", "resolutions", "coverage_limitations"} <= set(exposed)


def test_failed_run_markdown_never_claims_full_coverage(tmp_path: Path) -> None:
    """Defect: a failed run's report could render "All declared deterministic inputs were checked"."""
    _root, _bundle_value, selection = _proposed(tmp_path)
    run = CandidateRun(
        run_id="failed-run", revision=1, selection_digest=selection.selection_digest, packet_digest="a" * 64,
        backend="fixture", model="fixture", prompt_digest="b" * 64, rule_digest="c" * 64,
        chunk_ids=("chunk-1",), outcomes=(ChunkOutcome(chunk_id="chunk-1", outcome="failed"),),
        created_at=NOW, failure_detail="failed",
    )
    report = evaluate_report(selection, check_claims(selection, (_annotation(selection, "x"),), extraction_run=run))
    assert report.outcome == "incomplete"
    markdown = render_markdown(report)
    assert "All declared deterministic inputs were checked" not in markdown
    assert "did not complete" in markdown


# ── 5. structured authority in scope does not stale every check ──────────────

def test_check_with_structured_authority_in_scope_is_not_stale(tmp_path: Path, capsys) -> None:
    """Defect: `claims check` always failed CLAIMS_STALE when a structured authority record was in scope.

    It demanded a candidate artifact for mapping items that are projected from the
    ledger by their authority_record_digests, as report.py already skipped.
    """
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    _write_ledger(root, _note(root))
    selection = mandatory_source_closure(root, _bundle(root), effective_horizon="through-chapter-3",
                                         audience="gm", rule_versions=("claims/1",))
    confirmed = confirm_selection(selection, reviewer="gm", confirmed_at=NOW)
    save_confirmed_selection(root, confirmed)
    selection_file = tmp_path / "sel.json"; selection_file.write_bytes(canonical_bytes(confirmed))
    config = str(root / "config/config.yaml")
    assert _cli(["review", "--config", config, "--selection", str(selection_file), "--review", "R1", "--json"], capsys)[0] == 0
    code, checked = _cli(["check", "--config", config, "--selection", str(selection_file), "--review", "R1", "--json"], capsys)
    assert checked["code"] != "CLAIMS_STALE", checked
    assert code in {0, 5}


# ── 6. unresolved scope needs a recorded GM choice ───────────────────────────

def _future_prep(root: Path) -> NoteRecord:
    return _note(root, record_id="future-prep", classification=Classification.PREP,
                 effective=EffectiveInterval(horizon="future"), value="threatened",
                 projections=frozenset({Projection.PLANNING}), planning_date="2026-10-11")


def test_deleting_unresolved_scope_from_the_json_does_not_bypass_the_refusal(tmp_path: Path) -> None:
    """Defect: validate_selection_against_bundle ignored unresolved_scope, so deleting it bypassed the refusal.

    The unresolved set is recomputed from authority; a selection missing an entry,
    or confirmed with an entry that has no recorded resolution, is refused.
    """
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    _write_ledger(root, _future_prep(root))
    bundle = _bundle(root)
    selection = mandatory_source_closure(root, bundle, effective_horizon="through-chapter-3",
                                         audience="gm", rule_versions=("claims/1",))
    assert selection.unresolved_scope
    values = selection.model_dump(mode="python"); values["unresolved_scope"] = (); values["selection_digest"] = "0" * 64
    values["selection_digest"] = canonical_digest(
        SourceSelection.model_construct(**values),
        exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}),
    )
    edited = confirm_selection(SourceSelection.model_validate(values), reviewer="gm", confirmed_at=NOW)
    with pytest.raises(PromotionError) as caught:
        validate_selection_against_bundle(root, edited, bundle)
    assert caught.value.code == "CLAIMS_SCOPE_UNRESOLVED"


def test_resolve_scope_records_the_gm_choice_on_disk_before_confirmation(tmp_path: Path, capsys) -> None:
    """Defect: no command recorded the GM's scope choice, so an ambiguous selection could never be confirmed.

    `claims selection resolve-scope` records reviewer, choice and rationale per
    exact entry into the (still unconfirmed) selection, owner-only on disk; the
    selection then confirms and validates. `not_applicable` keeps the record in the
    mandatory closure as context only.
    """
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    _write_ledger(root, _future_prep(root))
    config = str(root / "config/config.yaml")
    code, selected = _cli(["select", "--config", config, "--since", "1", "--until", "3", "--json"], capsys)
    assert code == 0, selected
    proposed = selected["data"]["selection"]
    (entry,) = proposed["unresolved_scope"]
    proposed_file = tmp_path / "proposed.json"; proposed_file.write_text(json.dumps(proposed))
    code, refused = _cli(["selection", "save", "--config", config, "--input", str(proposed_file),
                          "--reviewer", "GM", "--json"], capsys)
    assert code == 2 and refused["code"] == "CLAIMS_SCOPE_UNRESOLVED"
    code, missing_reviewer = _cli(["selection", "resolve-scope", "--config", config, "--input", str(proposed_file),
                                   "--entry", entry, "--choice", "not_applicable", "--rationale", "Future prep only.",
                                   "--reviewer", " ", "--json"], capsys)
    assert code == 2 and missing_reviewer["code"] == "CLAIMS_SCOPE_INVALID"
    code, resolved = _cli(["selection", "resolve-scope", "--config", config, "--input", str(proposed_file),
                           "--entry", entry, "--choice", "not_applicable", "--rationale", "Future prep only.",
                           "--reviewer", "GM", "--json"], capsys)
    assert code == 0, resolved
    data = resolved["data"]
    assert data["unresolved"] == [] and data["resolved"][0]["entry"] == entry
    assert data["resolved"][0]["resolved_by"] == "GM" and data["resolved"][0]["choice"] == "not_applicable"
    recorded = root / data["path"]
    assert recorded.stat().st_mode & 0o777 == 0o600
    assert SourceSelection.model_validate_json(recorded.read_bytes()).selection_digest == data["selection_digest"]
    prep = next(item for item in data["selection"]["sources"] if item["authority_record_ids"] == ["future-prep"])
    assert prep["applicability"] == "context_only" and prep["required"] is True
    code, saved = _cli(["selection", "save", "--config", config, "--input", str(recorded),
                        "--reviewer", "GM", "--json"], capsys)
    assert code == 0, saved
    persisted = SourceSelection.model_validate_json((root / saved["data"]["path"]).read_bytes())
    assert persisted.scope_resolutions and persisted.scope_resolutions[0].entry == entry


# ── 7. equal values with different certainty ────────────────────────────────

def test_equal_value_with_unknown_certainty_is_not_a_conflict(tmp_path: Path) -> None:
    """Defect: equal values with certainty "unknown" on one side fell through to mechanical incompatible_state."""
    _root, _bundle_value, selection = _proposed(tmp_path)
    analysis = check_claims(selection, (
        _annotation(selection, "l", predicate=ClaimPredicate.LOCATION, value="gate", certainty="certain"),
        _annotation(selection, "r", predicate=ClaimPredicate.LOCATION, value="gate", certainty="unknown"),
    ))
    assert analysis.findings == ()


def test_equal_value_certain_versus_suspected_is_a_dismissable_suspicion_candidate(tmp_path: Path) -> None:
    """Defect: certain vs possible on a non-certainty predicate was an undismissable mechanical incompatible_state."""
    _root, _bundle_value, selection = _proposed(tmp_path)
    analysis = check_claims(selection, (
        _annotation(selection, "l", predicate=ClaimPredicate.FACTION, value="zhentarim", certainty="certain"),
        _annotation(selection, "r", predicate=ClaimPredicate.FACTION, value="zhentarim", certainty="possible"),
    ))
    (finding,) = analysis.findings
    assert finding.categories == ("suspicion_as_fact",) and finding.basis == "semantic_candidate"
    assert set(finding.annotation_ids) == {"l", "r"}
    report = evaluate_report(selection, analysis, resolutions=(FindingResolution(
        finding_id=finding.finding_id, disposition="dismiss", rationale="Both are suspicions in context.",
        event_id="event-dismiss", decision_revision=1,
    ),))
    assert report.outcome != "blocked"


# ── 8. explicit supersession can actually be declared and evaluated ──────────

def test_stale_rule_is_not_reported_passed_when_it_could_not_run(tmp_path: Path) -> None:
    """Defect: rule_outcomes always said stale_superseded "passed", though no import could declare supersession."""
    _root, _bundle_value, selection = _proposed(tmp_path)
    outcomes = {item["rule"]: item["state"] for item in check_claims(selection, (_annotation(selection, "x"),)).rule_outcomes}
    assert outcomes["stale_superseded"] == "not_evaluated"
    evaluated = check_claims(selection, (
        _annotation(selection, "old", value="owed", source_role=SourceRole.COUNTERPART),
        _annotation(selection, "new", value="paid", supersedes="old", source_role=SourceRole.COUNTERPART),
    ))
    assert {item["rule"]: item["state"] for item in evaluated.rule_outcomes}["stale_superseded"] == "passed"
    dangling = check_claims(selection, (_annotation(selection, "new", supersedes="absent"),))
    assert not dangling.complete


def test_import_carries_a_validated_supersession(tmp_path: Path) -> None:
    """Defect: imports never set supersedes_occurrence_id, so the explicit-supersession rule could never fire."""
    root, _bundle_value, confirmed, _selection_file = _confirmed_with_chunks(tmp_path)
    packet = assemble_packet(root, confirmed); chunk = packet.chunks[0]
    word = chunk.text.encode("utf-8")[:4].decode("utf-8")

    def row(occurrence, **extra):
        return {"occurrence_id": occurrence, "chunk_id": chunk.chunk_id, "start_byte": 0,
                "end_byte": len(word.encode()), "original_span": word, "subject_id": "road",
                "subject_kind": "topic", "predicate": "status", "normalized_value": occurrence,
                "certainty": "certain", "audience": "gm", "effective_from": "chapter-1",
                "effective_until": "chapter-3", **extra}

    path = import_candidates(root, confirmed, packet, {"annotations": [row("old"), row("new", supersedes_occurrence_id="old")]})
    saved = json.loads(path.read_bytes())["annotations"]
    assert {item["occurrence_id"]: item.get("supersedes_occurrence_id") for item in saved} == {"old": None, "new": "old"}
    later = import_candidates(root, confirmed, packet, {"annotations": [row("newest", supersedes_occurrence_id="new")]})
    assert later.is_file()
    with pytest.raises(PromotionError) as caught:
        import_candidates(root, confirmed, packet, {"annotations": [row("orphan", supersedes_occurrence_id="elsewhere")]})
    assert caught.value.code == "CLAIMS_CANDIDATE_INVALID"


# ── 9. a model run and manual imports combine in one review ──────────────────

def test_model_run_and_manual_import_combine_in_one_review(tmp_path: Path, capsys) -> None:
    """Defect: a later `review --candidates <import>` bound run None while model items remained.

    check then refused with "model candidates require their immutable extraction
    run". Each mapping item now binds its own run or import.
    """
    root, _bundle_value, confirmed, selection_file = _confirmed_with_chunks(tmp_path)
    packet = assemble_packet(root, confirmed); chunk = packet.chunks[0]
    word = chunk.text.encode("utf-8")[:4].decode("utf-8")

    def proposal(occurrence: str, value: str) -> dict:
        return {"occurrence_id": occurrence, "chunk_id": chunk.chunk_id, "start_byte": 0,
                "end_byte": len(word.encode()), "original_span": word, "subject_id": "road",
                "subject_kind": "topic", "predicate": "status", "normalized_value": value,
                "certainty": "certain", "audience": "gm", "effective_from": "chapter-1",
                "effective_until": "chapter-3"}

    result = extract_candidates(
        root, confirmed, packet, selected_chunk_ids=(chunk.chunk_id,), backend="fake", model="offline",
        prompt_version="claims-v1", rules="claims/1",
        invoke=lambda _prompt, _chunk: json.dumps({"annotations": [proposal("model-1", "active")]}), now=lambda: NOW,
    )
    config = str(root / "config/config.yaml")
    run_dir = result.path.relative_to(root).as_posix()
    assert _cli(["review", "--config", config, "--selection", str(selection_file), "--candidates", run_dir,
                 "--review", "MIX", "--json"], capsys)[0] == 0
    manual = tmp_path / "manual.json"; manual.write_text(json.dumps({"annotations": [proposal("manual-1", "closed")]}))
    code, imported = _cli(["import", "--config", config, "--selection", str(selection_file),
                           "--candidates", str(manual), "--json"], capsys)
    assert code == 0, imported
    assert _cli(["review", "--config", config, "--selection", str(selection_file), "--candidates",
                 imported["data"]["path"], "--review", "MIX", "--json"], capsys)[0] == 0
    code, checked = _cli(["check", "--config", config, "--selection", str(selection_file), "--review", "MIX", "--json"], capsys)
    assert checked["code"] in {"OK", "CLAIMS_INCOMPLETE"}, checked
    report = checked["data"]["report"]
    assert report["extraction_run"]["run_id"] == result.run.run_id
    assert {item["occurrence_id"] for item in report["annotations"]} >= {"model-1", "manual-1"}


# ── 10. report paths are contained before anything is read ───────────────────

def test_check_report_path_cannot_probe_outside_the_checks_directory(tmp_path: Path) -> None:
    """Defect: _report_path checked containment lexically and _private_read followed "..".

    `checks/../../../../x` passed the prefix test, so a supplied --check-report
    could test for (and read) files outside the campaign.
    """
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = _bundle(root, review="R1")
    (tmp_path / "secret.json").write_text("{}")
    escape = "../" * 8
    for name in ("secret.json", "absent.json"):
        with pytest.raises(PromotionError) as caught:
            load_current_report(root, f"{RANGE}/state/promotion/checks/{escape}{name}", bundle)
        assert caught.value.code == "CLAIMS_REPORT_INVALID" and "outside" in str(caught.value)
    with pytest.raises(PromotionError, match="escapes"):
        _private_read(root, root / f"docs/{escape}secret.json")
    with pytest.raises(PromotionError) as caught:
        report_freshness(root, f"{RANGE}/state/promotion/checks/{escape}secret.json", root / "config/config.yaml")
    assert caught.value.code == "CLAIMS_REPORT_INVALID"
