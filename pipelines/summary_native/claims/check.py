"""Six deterministic claim comparisons; this module has no model boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

from pipelines.summary_native.claims.models import (
    CandidateRun, ClaimAnnotation, ClaimFinding, ClaimPredicate, ExtractionRunBinding, SourceRole, SourceSelection,
    validate_annotation_authority,
)
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.models import canonical_bytes
from pipelines.summary_native.authority import EffectiveInterval, NoteRecord, RulingRecord, load_ledger


@dataclass(frozen=True)
class CheckAnalysis:
    annotations: tuple[ClaimAnnotation, ...]
    findings: tuple[ClaimFinding, ...]
    coverage_limitations: tuple[str, ...]
    rule_outcomes: tuple[dict[str, str], ...]
    mapping_set_digest: str
    analysis_digest: str
    complete: bool
    extraction_complete: bool | None
    extraction_run: ExtractionRunBinding | None
    authority_record_ids: tuple[str, ...]


def _applicable(annotation: ClaimAnnotation) -> bool:
    return annotation.origin == "structured_source" or annotation.interpretation_state == "mapping_confirmed"


def annotations_from_active_ledger(campaign_dir: Path, selection: SourceSelection) -> tuple[ClaimAnnotation, ...]:
    """Project supported active structured records without semantic extraction."""
    ledger = load_ledger(campaign_dir, required=False)
    if ledger is None:
        return ()
    source_by_record = {
        record_id: source for source in selection.sources for record_id in source.authority_record_ids
    }
    supported = {item.value: item for item in ClaimPredicate}
    result: list[ClaimAnnotation] = []
    for record in ledger.records:
        active = (isinstance(record, NoteRecord) and record.status == "active") or (
            isinstance(record, RulingRecord) and record.status in {"applied", "withdrawal_requested", "reversal_proposed"}
        )
        source = source_by_record.get(record.id)
        predicate = supported.get(record.claim_key or "")
        if (
            not active or source is None or source.applicability != "fact_authority"
            or predicate is None or record.normalized_value is None
        ):
            continue
        payload = canonical_bytes(record)
        digest = hashlib.sha256(payload).hexdigest()
        if source.authority_record_digests.get(record.id) != digest:
            raise ValueError(f"authority selection binding is stale for {record.id}")
        effective_from = (
            f"chapter-{record.effective.from_chapter:06d}" if record.effective.from_chapter is not None
            else record.effective.horizon
        )
        effective_until = (
            f"chapter-{record.effective.through_chapter:06d}" if record.effective.through_chapter is not None
            else record.effective.horizon
        )
        result.append(ClaimAnnotation(
            occurrence_id=f"authority-{record.id}-r{record.revision}", revision=record.revision,
            source_id=source.source_id, source_path=source.path, source_role=SourceRole.AUTHORITY,
            evidence_kind="authority_record", anchor=source.anchor, source_sha256=source.sha256,
            span_sha256=digest, context_sha256=source.context_sha256,
            original_span=f"{record.claim_key} = {record.normalized_value!r}", subject_id=record.subject.id,
            subject_identity_kind=record.subject.kind, subject_identity_resolved=True,
            predicate=predicate, normalized_value=record.normalized_value, certainty="certain",
            effective_from=effective_from, effective_until=effective_until,
            audience=selection.audience, authority_record_ids=(record.id,),
            authority_record_digests={record.id: digest}, origin="structured_source",
            interpretation_state="candidate", supersedes_occurrence_id=(
                f"authority-{record.supersedes}-r{next((item.revision for item in ledger.records if item.id == record.supersedes), 1)}"
                if record.supersedes else None
            ),
        ))
    return tuple(sorted(result, key=lambda item: item.occurrence_id))


_CHAPTER = re.compile(r"chapter-(\d+)\Z", re.IGNORECASE)
_HORIZONS = frozenset({"open", "future"})
_UNKNOWN = object()


def _bound(value: str | None, *, structured: bool) -> object:
    """One interval endpoint: a chapter, ``None`` for unbounded, or unknown."""
    if value is None:
        # A structured record's absent bound is unbounded (#546 half-open
        # interval); a candidate's absent value is simply unknown.
        return None if structured else _UNKNOWN
    if value == "open":
        return None
    match = _CHAPTER.fullmatch(value)
    return int(match.group(1)) if match else _UNKNOWN


def effective_interval(annotation: ClaimAnnotation) -> EffectiveInterval | None:
    """Project an assertion's scope onto #546's ``EffectiveInterval``, or None if incomparable.

    Comparison then uses ``EffectiveInterval.overlaps``, the one overlap rule
    for authority conflicts, supersession and precedence, rather than a second
    implementation. Dates and other vocabularies are incomparable here.
    """
    start, until = annotation.effective_from, annotation.effective_until
    if start == until and start in _HORIZONS:
        return EffectiveInterval(horizon=start)
    if "future" in (start, until):
        return None
    # A single ``open`` endpoint leaves that side of a chapter range unbounded.
    structured = annotation.origin == "structured_source"
    low, high = _bound(start, structured=structured), _bound(until, structured=structured)
    if low is _UNKNOWN or high is _UNKNOWN:
        return None
    if low is None and high is None:
        return EffectiveInterval(horizon="open")
    try:
        return EffectiveInterval(from_chapter=low, through_chapter=high)
    except ValueError:
        return None


def _compatible(left: ClaimAnnotation, right: ClaimAnnotation) -> bool | None:
    if left.subject_id != right.subject_id or left.subject_id is None or left.audience != right.audience:
        return False
    left_interval, right_interval = effective_interval(left), effective_interval(right)
    if left_interval is None or right_interval is None:
        return None
    return left_interval.overlaps(right_interval)


def _interpretation(annotation: ClaimAnnotation) -> dict:
    """The displayed meaning a finding (and any ruling on it) is about."""
    return {
        "occurrence_id": annotation.occurrence_id, "revision": annotation.revision,
        "span_sha256": annotation.span_sha256,
        "subject_kind": annotation.subject_identity_kind, "subject_id": annotation.subject_id,
        "subject_identity_resolved": annotation.subject_identity_resolved,
        "predicate": annotation.predicate, "normalized_value": annotation.normalized_value,
        "certainty": annotation.certainty, "effective_from": annotation.effective_from,
        "effective_until": annotation.effective_until, "audience": annotation.audience,
        "authority_record_digests": annotation.authority_record_digests,
        "supersedes_occurrence_id": annotation.supersedes_occurrence_id,
    }


def _semantic_digest(values: dict, annotations: tuple[ClaimAnnotation, ...]) -> str:
    """Bind the finding payload and the exact meanings compared.

    A changed subject, predicate, value, certainty, scope, audience or evidence
    yields a different digest, so a ruling on the old meaning stays in history
    but no longer settles the finding (US3 scenario 6).
    """
    payload = {key: value for key, value in values.items() if key != "semantic_digest"}
    payload["interpretations"] = [_interpretation(item) for item in annotations]
    return canonical_digest(payload)


def _finding(
    category: str, left: ClaimAnnotation, *, right: ClaimAnnotation | None = None,
    source_id: str | None = None, source_evidence: str | None = None,
    rationale: str, rule: str,
) -> ClaimFinding:
    if right is not None and right.occurrence_id < left.occurrence_id:
        left, right = right, left
    annotation_ids = (left.occurrence_id,) + ((right.occurrence_id,) if right else ())
    source_ids = (source_id,) if source_id else ()
    right_evidence = right.original_span if right else (source_evidence or source_id or "missing counterpart")
    values = dict(
        finding_id=f"finding-{category}-{canonical_digest([*annotation_ids, *source_ids, rule])[:16]}",
        revision=1, categories=(category,), annotation_ids=annotation_ids, source_ids=source_ids,
        rule_id=rule, rule_version="1", audience=left.audience,
        effective_horizon=left.effective_until or left.effective_from or "unspecified",
        basis="mechanical", severity="blocking", evidence=(left.original_span, right_evidence),
        rationale=rationale, next_action="Correct or adjudicate the paired evidence, then regenerate and review.",
        required_disposition=True, semantic_digest="0" * 64,
    )
    values["semantic_digest"] = _semantic_digest(values, (left,) + ((right,) if right else ()))
    return ClaimFinding.model_validate(values)


def _candidate(item: ClaimAnnotation, reason: str) -> ClaimFinding:
    values = dict(
        finding_id=f"finding-semantic-{canonical_digest([item.occurrence_id, reason])[:16]}",
        revision=1, categories=("incompatible_state",), annotation_ids=(item.occurrence_id,),
        rule_id="semantic-mapping", rule_version="1", audience=item.audience,
        effective_horizon=item.effective_until or item.effective_from or "unknown",
        basis="semantic_candidate", severity="blocking", evidence=(item.original_span,),
        rationale=reason, next_action="Review the displayed source span and its proposed meaning.",
        required_disposition=True, semantic_digest="0" * 64,
    )
    values["semantic_digest"] = _semantic_digest(values, (item,))
    return ClaimFinding.model_validate(values)


def _pair_candidate(
    left: ClaimAnnotation, right: ClaimAnnotation, *, category: str, rule: str,
    reason: str, next_action: str, horizon: str = "unknown",
) -> ClaimFinding:
    """A two-sided candidate for GM judgment; dismissable, never mechanical."""
    if right.occurrence_id < left.occurrence_id:
        left, right = right, left
    values = dict(
        finding_id=f"finding-semantic-{canonical_digest([left.occurrence_id, right.occurrence_id, reason])[:16]}",
        revision=1, categories=(category,),
        annotation_ids=(left.occurrence_id, right.occurrence_id),
        rule_id=rule, rule_version="1", audience=left.audience,
        effective_horizon=horizon, basis="semantic_candidate", severity="blocking",
        evidence=(left.original_span, right.original_span), rationale=reason,
        next_action=next_action, required_disposition=True, semantic_digest="0" * 64,
    )
    values["semantic_digest"] = _semantic_digest(values, (left, right))
    return ClaimFinding.model_validate(values)


def _scope_candidate(left: ClaimAnnotation, right: ClaimAnnotation) -> ClaimFinding:
    return _pair_candidate(
        left, right, category="incompatible_state", rule="semantic-scope",
        reason="These assertions use unknown or incomparable effective scope endpoints.",
        next_action="Review and normalize the displayed effective scopes.",
    )


def bind_extraction_run(selection: SourceSelection, run: CandidateRun) -> ExtractionRunBinding:
    """Validate and reduce an immutable candidate run to its analysis identity."""
    if run.selection_digest != selection.selection_digest:
        raise ValueError("candidate run belongs to another source selection")
    return ExtractionRunBinding(
        run_id=run.run_id, revision=run.revision, run_digest=canonical_digest(run),
        selection_digest=run.selection_digest, packet_digest=run.packet_digest,
        outcome_digest=canonical_digest([item.model_dump(mode="json") for item in run.outcomes]),
        complete=run.completed_at is not None,
    )


NO_MAPPINGS_LIMITATION = "No semantic mappings were selected; deterministic structured coverage only."
NO_CHUNKS_LIMITATION = (
    "No prose chunks were selected for extraction; the meaning of the selected documents' prose "
    "is outside mechanical coverage except for reviewed mappings."
)


def _uncovered_limitation(chunk_ids: list[str]) -> str:
    return (
        f"{len(chunk_ids)} selected prose chunk(s) were not covered by a completed extraction run "
        f"({', '.join(chunk_ids)}); only manually imported mappings were reviewed for them, so their "
        "unnormalized meaning is outside mechanical coverage."
    )


def check_claims(
    selection: SourceSelection,
    annotations: tuple[ClaimAnnotation, ...],
    *,
    active_authority_ids: frozenset[str] | dict[str, str] = frozenset(),
    extraction_run: CandidateRun | None = None,
) -> CheckAnalysis:
    """Compare only explicit, currently applicable meanings in stable order."""
    ordered = tuple(sorted(annotations, key=lambda item: (item.occurrence_id, item.revision)))
    model_annotations = tuple(item for item in ordered if item.origin == "model_candidate")
    if extraction_run is None and model_annotations:
        raise ValueError("model candidates require their immutable extraction run")
    if extraction_run is not None:
        expected_ids = tuple(extraction_run.candidate_annotation_ids)
        actual_ids = tuple(item.occurrence_id for item in model_annotations)
        if set(actual_ids) != set(expected_ids) or len(actual_ids) != len(expected_ids):
            raise ValueError("candidate run and annotation membership differ")
        for item in model_annotations:
            if (
                item.extraction_run_id != extraction_run.run_id
                or item.prompt_digest != extraction_run.prompt_digest
                or item.model_id != f"{extraction_run.backend}:{extraction_run.model}"
            ):
                raise ValueError("model candidate extraction identity differs")
    limitations: set[str] = set()
    if not ordered:
        limitations.add(NO_MAPPINGS_LIMITATION)
    extraction_binding = None if extraction_run is None else bind_extraction_run(selection, extraction_run)
    extraction_complete = extraction_binding.complete if extraction_binding is not None else None
    # Coverage of the selected prose. A failed declared run is incomplete and
    # is never renamed a limitation; selected chunks with neither a completed
    # run nor a manual import are an undeclared extraction and also incomplete.
    selected_chunks = [item.chunk_id for item in selection.chunks]
    covered = set(extraction_run.chunk_ids) if extraction_complete else set()
    uncovered = [chunk_id for chunk_id in selected_chunks if chunk_id not in covered]
    manual = any(item.origin == "human_candidate" for item in ordered)
    if not selected_chunks:
        limitations.add(NO_CHUNKS_LIMITATION)
    elif uncovered and extraction_complete is not False:
        if manual:
            limitations.add(_uncovered_limitation(uncovered))
        else:
            extraction_complete = False
    incomplete: set[str] = set()
    usable: list[ClaimAnnotation] = []
    candidates: list[ClaimFinding] = []
    present = {item.occurrence_id for item in ordered}
    for item in ordered:
        if item.origin == "structured_source":
            try:
                validate_annotation_authority(item, active_authority_ids)
            except ValueError:
                limitations.add(f"inactive authority: {item.occurrence_id}")
                incomplete.add(item.occurrence_id)
                continue
        elif item.supersedes_occurrence_id is not None and item.supersedes_occurrence_id not in present:
            # A retired structured record legitimately leaves its successor's
            # target absent; a reviewed prose supersession must name evidence
            # that is actually in this check.
            limitations.add(
                f"supersession target missing: {item.occurrence_id} supersedes {item.supersedes_occurrence_id}"
            )
            incomplete.add(item.occurrence_id)
        if not _applicable(item):
            candidates.append(_candidate(item, "This exact prose meaning has not been reviewed."))
            continue
        if (not item.subject_identity_resolved or item.subject_id is None
                or item.predicate is None or item.normalized_value is None):
            candidates.append(_candidate(item, "The reviewed source still has an unknown subject, predicate, or value."))
            continue
        usable.append(item)

    findings: dict[tuple[str, str, str], ClaimFinding] = {
        ("semantic_candidate", item.finding_id, ""): item for item in candidates
    }
    source_by_id = {item.source_id: item for item in selection.sources}

    # Audience leaks compare the interpreted assertion to its exact source audience.
    for item in usable:
        source = source_by_id.get(item.source_id)
        if source and source.source_audience == "gm" and item.audience != "gm":
            found = _finding(
                "audience_leak", item, source_id=source.source_id,
                source_evidence=f"{source.path} [{source.anchor}] audience={source.source_audience}",
                rationale="GM-only source material is asserted for a broader audience.", rule="audience-boundary",
            )
            findings[("audience_leak", item.occurrence_id, source.source_id)] = found

    supersession_evaluated = False
    for index, left in enumerate(usable):
        for right in usable[index + 1:]:
            overlap = _compatible(left, right)
            if overlap is None and left.subject_id == right.subject_id and left.audience == right.audience:
                found = _scope_candidate(left, right)
                findings[("semantic_scope", left.occurrence_id, right.occurrence_id)] = found
                continue
            if not overlap:
                continue
            if left.supersedes_occurrence_id == right.occurrence_id or right.supersedes_occurrence_id == left.occurrence_id:
                supersession_evaluated = True
                newer, older = (left, right) if left.supersedes_occurrence_id == right.occurrence_id else (right, left)
                # Preserved source history may legitimately contain both the
                # old and replacement facts.  It blocks only when the bundle's
                # asserted draft still presents the superseded meaning.
                if older.source_role is SourceRole.CLAIM:
                    found = _finding(
                        "stale_superseded", newer, right=older,
                        rationale="The asserted draft still presents a meaning replaced by an explicit reviewed supersession.",
                        rule="explicit-supersession",
                    )
                    findings[("stale_superseded", *sorted((left.occurrence_id, right.occurrence_id)))] = found
                continue
            if left.predicate != right.predicate:
                continue
            pair = sorted((left.occurrence_id, right.occurrence_id))
            certainty_states = {left.certainty, right.certainty}
            if left.normalized_value == right.normalized_value:
                # Same value: an unknown certainty on either side is no
                # conflict, and differing hedges are not a contradiction.
                if len(certainty_states) == 1 or "unknown" in certainty_states:
                    continue
                if "certain" in certainty_states and certainty_states & {"possible", "probable"}:
                    found = _pair_candidate(
                        left, right, category="suspicion_as_fact", rule="certainty-escalation",
                        reason="The same value is asserted as certain on one side and as a suspicion on the other.",
                        next_action="Judge whether the certain assertion overstates the displayed suspicion.",
                        horizon=left.effective_until or left.effective_from or "unknown",
                    )
                    findings[("suspicion_as_fact", *pair)] = found
                continue
            certainty_values = {str(left.normalized_value), str(right.normalized_value)}
            if left.predicate is ClaimPredicate.CERTAINTY and (
                "certain" in certainty_values and bool(certainty_values & {"possible", "probable"})
                or "certain" in certainty_states and bool(certainty_states & {"possible", "probable"})
            ):
                category, rule, rationale = (
                    "suspicion_as_fact", "certainty-escalation",
                    "A scoped suspicion and a certain assertion are not equivalent.",
                )
            elif left.predicate is ClaimPredicate.STATUS and {str(left.normalized_value), str(right.normalized_value)} == {"active", "resolved"}:
                category, rule, rationale = (
                    "resolved_as_active", "resolved-status",
                    "The same scoped item is both resolved and active.",
                )
            elif left.predicate is ClaimPredicate.ACTOR:
                category, rule, rationale = (
                    "direct_contradiction", "actor-identity",
                    "Two applicable assertions assign incompatible actors.",
                )
            else:
                category, rule, rationale = (
                    "incompatible_state", "state-compatibility",
                    "Two applicable assertions give incompatible ownership, debt, location, faction, or status values.",
                )
            found = _finding(category, left, right=right, rationale=rationale, rule=rule)
            findings[(category, *pair)] = found

    result = tuple(sorted(findings.values(), key=lambda item: item.finding_id))
    mapping_digest = canonical_digest([
        item.model_dump(mode="json") for item in usable if item.interpretation_state == "mapping_confirmed"
    ])

    def _rule_state(name: str) -> str:
        if any(name in item.categories for item in result):
            return "blocked"
        # Explicit supersession can only be evaluated over a declared,
        # comparable relation; with none it did not run, so never "passed".
        if name == "stale_superseded" and not supersession_evaluated:
            return "not_evaluated"
        return "passed"

    rule_outcomes = tuple(
        {"rule": name, "state": _rule_state(name)}
        for name in (
            "direct_contradiction", "stale_superseded", "suspicion_as_fact",
            "audience_leak", "resolved_as_active", "incompatible_state",
        )
    )
    analysis_values = {
        "source_selection_digest": selection.selection_digest,
        "mapping_set_digest": mapping_digest,
        # Retain every declared input annotation so a later promotion gate can
        # reconstruct candidates and mappings from current review state.  The
        # usable subset alone is insufficient to reproduce semantic-candidate
        # findings.
        "annotations": [item.model_dump(mode="json") for item in ordered],
        "findings": [item.model_dump(mode="json") for item in result],
        "coverage_limitations": sorted(limitations),
        "rule_outcomes": rule_outcomes,
        "extraction_complete": extraction_complete,
        "extraction_run": extraction_binding.model_dump(mode="json") if extraction_binding else None,
        "authority_records": (
            dict(sorted(active_authority_ids.items()))
            if isinstance(active_authority_ids, dict) else sorted(active_authority_ids)
        ),
    }
    return CheckAnalysis(
        annotations=ordered, findings=result, coverage_limitations=tuple(sorted(limitations)),
        rule_outcomes=rule_outcomes, mapping_set_digest=mapping_digest,
        analysis_digest=canonical_digest(analysis_values), complete=not incomplete,
        extraction_complete=extraction_complete, extraction_run=extraction_binding,
        authority_record_ids=tuple(sorted(active_authority_ids)),
    )
