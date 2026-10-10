"""Six deterministic claim comparisons; this module has no model boundary."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from datetime import date
from pathlib import Path
import re

from pipelines.summary_native.claims.models import (
    CandidateRun, ClaimAnnotation, ClaimFinding, ClaimPredicate, ExtractionRunBinding, SourceRole, SourceSelection,
    validate_annotation_authority,
)
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.models import canonical_bytes
from pipelines.summary_native.authority import NoteRecord, RulingRecord, load_ledger


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


def _endpoint(value: str | None) -> tuple[str, object] | None:
    if value is None:
        return None
    match = _CHAPTER.fullmatch(value)
    if match:
        return "chapter", int(match.group(1))
    try:
        return "date", date.fromisoformat(value)
    except ValueError:
        pass
    if value in {"current", "future", "open"}:
        return "named", value
    return None


def _compatible(left: ClaimAnnotation, right: ClaimAnnotation) -> bool | None:
    if left.subject_id != right.subject_id or left.subject_id is None or left.audience != right.audience:
        return False
    endpoints = tuple(_endpoint(value) for value in (
        left.effective_from, left.effective_until, right.effective_from, right.effective_until
    ))
    if any(value is None for value in endpoints):
        return None
    kinds = {value[0] for value in endpoints if value is not None}
    if len(kinds) != 1:
        return None
    values = tuple(value[1] for value in endpoints if value is not None)
    if kinds == {"named"}:
        return len(set(values)) == 1
    left_from, left_until, right_from, right_until = values
    return not (left_until < right_from or right_until < left_from)


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
    values["semantic_digest"] = canonical_digest(values, exclude_fields=frozenset({"semantic_digest"}))
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
    values["semantic_digest"] = canonical_digest(values, exclude_fields=frozenset({"semantic_digest"}))
    return ClaimFinding.model_validate(values)


def _scope_candidate(left: ClaimAnnotation, right: ClaimAnnotation) -> ClaimFinding:
    if right.occurrence_id < left.occurrence_id:
        left, right = right, left
    reason = "These assertions use unknown or incomparable effective scope endpoints."
    values = dict(
        finding_id=f"finding-semantic-{canonical_digest([left.occurrence_id, right.occurrence_id, reason])[:16]}",
        revision=1, categories=("incompatible_state",),
        annotation_ids=(left.occurrence_id, right.occurrence_id),
        rule_id="semantic-scope", rule_version="1", audience=left.audience,
        effective_horizon="unknown", basis="semantic_candidate", severity="blocking",
        evidence=(left.original_span, right.original_span), rationale=reason,
        next_action="Review and normalize the displayed effective scopes.",
        required_disposition=True, semantic_digest="0" * 64,
    )
    values["semantic_digest"] = canonical_digest(values, exclude_fields=frozenset({"semantic_digest"}))
    return ClaimFinding.model_validate(values)


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
        limitations.add("No semantic mappings were selected; deterministic structured coverage only.")
    incomplete: set[str] = set()
    usable: list[ClaimAnnotation] = []
    candidates: list[ClaimFinding] = []
    for item in ordered:
        if item.origin == "structured_source":
            try:
                validate_annotation_authority(item, active_authority_ids)
            except ValueError:
                limitations.add(f"inactive authority: {item.occurrence_id}")
                incomplete.add(item.occurrence_id)
                continue
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
    by_occurrence = {item.occurrence_id: item for item in usable}
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
            if left.normalized_value == right.normalized_value and left.certainty == right.certainty:
                continue
            pair = sorted((left.occurrence_id, right.occurrence_id))
            certainty_values = {str(left.normalized_value), str(right.normalized_value)}
            certainty_states = {left.certainty, right.certainty}
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
    rule_outcomes = tuple(
        {"rule": name, "state": "blocked" if any(name in item.categories for item in result) else "passed"}
        for name in (
            "direct_contradiction", "stale_superseded", "suspicion_as_fact",
            "audience_leak", "resolved_as_active", "incompatible_state",
        )
    )
    extraction_binding = None if extraction_run is None else bind_extraction_run(selection, extraction_run)
    extraction_complete = extraction_binding.complete if extraction_binding is not None else None
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
