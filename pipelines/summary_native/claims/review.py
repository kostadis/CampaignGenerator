"""Adapters from claim annotations/findings into the shared grounding review."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipelines.summary_native.claims.models import ClaimAnnotation, ClaimFinding, FindingResolution
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.authority import NoteRecord, ReviewDecisionRecord, RulingRecord, load_ledger, sha256_bytes
from pipelines.summary_native.review.models import (
    DecisionEvent, ReviewItem, ReviewManifest, SourceCustodyGeneration, canonical_bytes, canonical_digest,
)
from pipelines.summary_native.review.store import (
    ReviewStoreError, append_review_items, create_review, history, load_campaign_identity, read_review_state,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def mapping_annotation_digest(annotation: ClaimAnnotation) -> str:
    """Bind every displayed interpretation field, excluding later review authority."""
    return canonical_digest({
        "occurrence_id": annotation.occurrence_id, "revision": annotation.revision,
        "source_id": annotation.source_id, "source_path": annotation.source_path,
        "source_role": annotation.source_role, "evidence_kind": annotation.evidence_kind, "anchor": annotation.anchor,
        "start_byte": annotation.start_byte, "end_byte": annotation.end_byte,
        "source_sha256": annotation.source_sha256, "span_sha256": annotation.span_sha256,
        "context_sha256": annotation.context_sha256, "original_span": annotation.original_span,
        "subject_kind": annotation.subject_identity_kind, "subject_id": annotation.subject_id,
        "subject_identity_resolved": annotation.subject_identity_resolved,
        "predicate": annotation.predicate,
        "normalized_value": annotation.normalized_value, "certainty": annotation.certainty,
        "effective_from": annotation.effective_from, "effective_until": annotation.effective_until,
        "audience": annotation.audience, "authority_record_ids": annotation.authority_record_ids,
        "authority_record_digests": annotation.authority_record_digests,
        "origin": annotation.origin, "extraction_run_id": annotation.extraction_run_id,
        "prompt_digest": annotation.prompt_digest, "model_id": annotation.model_id,
        "input_digest": annotation.input_digest, "supersedes_occurrence_id": annotation.supersedes_occurrence_id,
    })


def _evidence(root: Path, annotation: ClaimAnnotation) -> tuple[dict, dict]:
    path = root / annotation.source_path
    data = path.read_bytes()
    if annotation.origin != "structured_source" and _sha(data) != annotation.source_sha256:
        raise PromotionError("claim review source changed", code="CLAIMS_REVIEW_STALE")
    if annotation.origin == "structured_source":
        custody_source_id = f"authority-ledger-{hashlib.sha256(annotation.source_path.encode()).hexdigest()[:16]}"
        records = {record.id: record for record in load_ledger(root).records}
        for record_id, expected in annotation.authority_record_digests.items():
            record = records.get(record_id)
            active = (isinstance(record, NoteRecord) and record.status == "active") or (
                isinstance(record, RulingRecord)
                and record.status in {"applied", "withdrawal_requested", "reversal_proposed"}
            )
            if not active or _sha(canonical_bytes(record)) != expected:
                raise PromotionError("structured authority record changed", code="CLAIMS_REVIEW_STALE")
        evidence = {
            "source_id": custody_source_id, "source_path": annotation.source_path,
            "anchor": annotation.anchor,
            "missing_reason": "Meaning is projected from the exact active authority record digest bound in this item.",
            "citation_resolved": True,
        }
        binding = {
            "source_id": custody_source_id, "path": annotation.source_path,
            "custody_sha256": _sha(data), "semantic_sha256": annotation.context_sha256,
        }
        return evidence, binding
    excerpt = data[annotation.start_byte:annotation.end_byte]
    if excerpt.decode("utf-8") != annotation.original_span or _sha(excerpt) != annotation.span_sha256:
        raise PromotionError("claim review evidence span changed", code="CLAIMS_REVIEW_STALE")
    evidence = {
        "source_id": annotation.source_id, "source_path": annotation.source_path,
        "anchor": annotation.anchor, "exact_excerpt": annotation.original_span,
        "selected_span_sha256": annotation.span_sha256, "citation_resolved": True,
    }
    binding = {
        "source_id": annotation.source_id, "path": annotation.source_path,
        "custody_sha256": annotation.source_sha256,
        "semantic_sha256": annotation.context_sha256,
    }
    return evidence, binding


def create_claim_review(
    campaign_dir: Path,
    review_id: str,
    *,
    annotations: tuple[ClaimAnnotation, ...],
    findings: tuple[ClaimFinding, ...],
    created_by: str,
    rule_versions: tuple[tuple[str, str], ...],
) -> dict:
    """Create stable mapping/finding items with exact source custody."""
    root = Path(campaign_dir).resolve()
    identity = load_campaign_identity(root)
    annotation_by_id = {item.occurrence_id: item for item in annotations}
    items: list[ReviewItem] = []
    custody: dict[str, dict] = {}
    rules = tuple({"rule_id": rule, "version": version} for rule, version in rule_versions)
    for annotation in sorted(annotations, key=lambda item: (item.occurrence_id, item.revision)):
        if annotation.interpretation_state != "candidate":
            continue
        evidence, binding = _evidence(root, annotation)
        data = (root / annotation.source_path).read_bytes()
        custody[binding["path"]] = {
            "source_id": binding["source_id"], "path": annotation.source_path,
            "sha256": binding["custody_sha256"], "size": len(data),
        }
        item_id = f"mapping-{annotation.occurrence_id}"
        items.append(ReviewItem(
            item_id=item_id, revision=annotation.revision, campaign_id=identity.campaign_id,
            review_id=review_id, domain="grounding_document",
            subject_ref={"subject_id": uuid.uuid5(identity.campaign_id, f"claim:{annotation.occurrence_id}"), "kind": "claim"},
            occurrence_id=uuid.uuid5(identity.campaign_id, f"occurrence:{annotation.occurrence_id}"),
            locator={"source_path": annotation.source_path, "anchor": annotation.anchor},
            claim_text=annotation.original_span, evidence=(evidence,),
            diagnostics=({"diagnostic_id": f"mapping-{annotation.occurrence_id}",
                          "legacy_code": "claim-mapping-required",
                          "message": "Confirm the exact interpretation of this selected span.", "blocking": True},),
            categories={"citation_non_entailment"}, severity="needs_judgment",
            assignment_basis="gm_confirmed", rationale="Candidate meanings require GM confirmation.",
            proposed_action={"action": "confirm_claim_mapping", "details": {
                "occurrence_id": annotation.occurrence_id, "annotation_revision": annotation.revision,
                "span_sha256": annotation.span_sha256, "context_sha256": annotation.context_sha256,
                "annotation_digest": mapping_annotation_digest(annotation),
                "subject_kind": annotation.subject_identity_kind,
                "subject_id": annotation.subject_id,
                "subject_identity_resolved": annotation.subject_identity_resolved,
                "predicate": annotation.predicate,
                "normalized_value": annotation.normalized_value,
                "certainty": annotation.certainty,
                "effective_from": annotation.effective_from,
                "effective_until": annotation.effective_until,
                "audience": annotation.audience,
                "authority_record_digests": annotation.authority_record_digests,
            }},
            scope={"kind": "evidence", "value": annotation.occurrence_id},
            rule_versions=rules, input_bindings=(binding,),
        ))
    for finding in sorted(findings, key=lambda item: (item.finding_id, item.revision)):
        linked = [annotation_by_id[value] for value in finding.annotation_ids if value in annotation_by_id]
        if not linked:
            raise PromotionError(
                f"finding {finding.finding_id} has no exact reviewable source locator; retain it as an incomplete report diagnostic",
                code="CLAIMS_REVIEW_EVIDENCE_REQUIRED",
            )
        evidence_rows, evidence_keys, bindings_by_id = [], set(), {}
        for annotation in linked:
            evidence, binding = _evidence(root, annotation)
            evidence_key = canonical_digest(evidence)
            if evidence_key not in evidence_keys:
                evidence_rows.append(evidence); evidence_keys.add(evidence_key)
            bindings_by_id[binding["source_id"]] = binding
            data = (root / annotation.source_path).read_bytes()
            custody[binding["path"]] = {
                "source_id": binding["source_id"], "path": annotation.source_path,
                "sha256": binding["custody_sha256"], "size": len(data),
            }
        items.append(ReviewItem(
            item_id=f"finding-{finding.finding_id}", revision=finding.revision,
            campaign_id=identity.campaign_id, review_id=review_id, domain="grounding_document",
            subject_ref={"subject_id": uuid.uuid5(identity.campaign_id, f"finding:{finding.finding_id}"), "kind": "claim"},
            occurrence_id=uuid.uuid5(identity.campaign_id, f"finding-occurrence:{finding.finding_id}"),
            locator={"source_path": linked[0].source_path if linked else "docs", "anchor": finding.finding_id},
            failure_context=finding.rationale, evidence=tuple(evidence_rows),
            diagnostics=({"diagnostic_id": finding.finding_id, "legacy_code": finding.categories[0],
                          "message": finding.next_action, "blocking": finding.severity == "blocking"},),
            categories={"citation_non_entailment"}, severity="needs_judgment",
            assignment_basis="gm_confirmed", rationale=finding.rationale,
            proposed_action={"action": "resolve_claim_finding", "details": {
                "finding_id": finding.finding_id, "finding_revision": finding.revision,
                "basis": finding.basis, "semantic_digest": finding.semantic_digest,
                "required_disposition": finding.required_disposition,
                "annotation_interpretations": [{
                    "occurrence_id": annotation.occurrence_id,
                    "annotation_digest": mapping_annotation_digest(annotation),
                    "subject_kind": annotation.subject_identity_kind,
                    "subject_id": annotation.subject_id,
                    "subject_identity_resolved": annotation.subject_identity_resolved,
                    "predicate": annotation.predicate,
                    "normalized_value": annotation.normalized_value,
                    "certainty": annotation.certainty,
                    "effective_from": annotation.effective_from,
                    "effective_until": annotation.effective_until,
                    "audience": annotation.audience,
                } for annotation in linked],
            }},
            scope={"kind": "evidence", "value": finding.finding_id},
            rule_versions=rules, input_bindings=tuple(bindings_by_id[key] for key in sorted(bindings_by_id)),
        ))
    if not items:
        raise PromotionError("claim review requires mapping or finding items", code="CLAIMS_REVIEW_EMPTY")
    now = datetime.now(timezone.utc)
    custody_record = SourceCustodyGeneration(
        campaign_id=identity.campaign_id, review_id=review_id, generation=1,
        recorded_at=now, sources=tuple(sorted(custody.values(), key=lambda value: value["source_id"])),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id, review_id=review_id, kind="grounding_documents",
        generation=1, created_at=now, created_by=created_by,
        selection=tuple({"kind": "document", "id": item.item_id} for item in items),
        items=tuple({"campaign_id": identity.campaign_id, "review_id": review_id,
                     "item_id": item.item_id, "revision": item.revision,
                     "review_digest": item.review_digest} for item in items),
        source_manifest={"campaign_id": identity.campaign_id, "review_id": review_id,
                         "generation": 1, "digest": custody_record.custody_digest},
        rule_versions=rules,
    )
    try:
        current_manifest, current_items, _events, _stale = read_review_state(root, review_id)
    except ReviewStoreError:
        return create_review(root, manifest, custody_record, items)
    existing = {item.item_id: item for item in current_items}
    staged = []
    for item in items:
        prior = existing.get(item.item_id)
        if prior is None:
            staged.append(item)
        elif (
            item.proposed_action.action == "resolve_claim_finding"
            and prior.proposed_action.action in {"dismiss_claim_finding", "accept_claim_uncertainty"}
            and all(
                prior.proposed_action.details.get(key) == item.proposed_action.details.get(key)
                for key in ("finding_id", "finding_revision", "basis", "semantic_digest", "required_disposition")
            )
        ):
            # Rechecking an unchanged finding must retain the exact prepared
            # action and its decision. Only a changed finding binding earns a
            # new generic unresolved revision.
            continue
        elif prior.semantic_digest() != item.semantic_digest():
            raw = item.model_dump(mode="python")
            raw.update(revision=prior.revision + 1, review_digest=None)
            staged.append(ReviewItem.model_validate(raw))
    additions = tuple(staged)
    if not additions:
        raise PromotionError("claim review stage adds no current items", code="CLAIMS_REVIEW_EMPTY")
    required_sources = {binding.source_id for item in additions for binding in item.input_bindings}
    return append_review_items(
        root, review_id, expected_generation=current_manifest.generation, items=additions,
        sources=tuple(source for source in custody_record.model_dump(mode="json")["sources"]
                      if source["source_id"] in required_sources),
        rule_versions=rules,
    )


def load_confirmed_annotations(
    campaign_dir: Path, review_id: str, annotations: tuple[ClaimAnnotation, ...],
    *, _already_locked: bool = False,
) -> tuple[ClaimAnnotation, ...]:
    """Materialize mapping-confirmed annotations only from current accepted audit events."""
    root = Path(campaign_dir).resolve()
    _manifest, items, events, stale = read_review_state(
        root, review_id, _already_locked=_already_locked,
    )
    by_item = {item.item_id: item for item in items}
    current: dict[str, dict | None] = {}
    for event in events:
        item_id = event.get("item_id")
        if isinstance(item_id, str):
            prior = current.get(item_id)
            if prior is None or int(event.get("decision_revision", 0)) >= int(prior.get("decision_revision", 0)):
                current[item_id] = None if event.get("kind") == "withdrawal" else event
    accepted = {
        record.event_id: record for record in load_ledger(root).records
        if isinstance(record, ReviewDecisionRecord) and record.status == "accepted"
    }
    result: list[ClaimAnnotation] = []
    for annotation in annotations:
        item_id = f"mapping-{annotation.occurrence_id}"
        item = by_item.get(item_id); raw = current.get(item_id)
        if item is None or raw is None or item_id in stale or item.proposed_action.action != "confirm_claim_mapping":
            continue
        try:
            event = DecisionEvent.model_validate(raw)
        except ValueError:
            continue
        record = accepted.get(event.event_id)
        details = item.proposed_action.details
        if (
            event.verdict.value != "approve" or event.disposition.value != "accept_no_change"
            or event.item_revision != item.revision or event.review_digest != item.review_digest
            or details.get("occurrence_id") != annotation.occurrence_id
            or details.get("annotation_revision") != annotation.revision
            or details.get("span_sha256") != annotation.span_sha256
            or details.get("context_sha256") != annotation.context_sha256
            or details.get("annotation_digest") != mapping_annotation_digest(annotation)
            or record is None or record.item_id != item_id or record.review_id != review_id
            or record.review_digest != item.review_digest or record.event_digest != sha256_bytes(canonical_bytes(event))
        ):
            continue
        result.append(annotation.model_copy(update={
            "interpretation_state": "mapping_confirmed", "review_item_id": item_id,
            "review_item_digest": item.review_digest, "mapping_event_id": event.event_id,
        }))
    return tuple(result)


def load_current_resolutions(
    campaign_dir: Path, review_id: str, findings: tuple[ClaimFinding, ...],
    *, _already_locked: bool = False,
) -> tuple[FindingResolution, ...]:
    """Evaluate current finding decisions from exact prepared review items."""
    root = Path(campaign_dir).resolve()
    _manifest, items, events, stale = read_review_state(
        root, review_id, _already_locked=_already_locked,
    )
    by_item = {item.item_id: item for item in items}
    current: dict[str, dict | None] = {}
    for raw in events:
        item_id = raw.get("item_id")
        if isinstance(item_id, str):
            prior = current.get(item_id)
            if prior is None or int(raw.get("decision_revision", 0)) >= int(prior.get("decision_revision", 0)):
                current[item_id] = None if raw.get("kind") == "withdrawal" else raw
    accepted = {
        record.event_id: record for record in load_ledger(root).records
        if isinstance(record, ReviewDecisionRecord) and record.status == "accepted"
    }
    result: list[FindingResolution] = []
    for finding in findings:
        item_id = f"finding-{finding.finding_id}"
        item = by_item.get(item_id); raw = current.get(item_id)
        if item is None or raw is None or item_id in stale:
            continue
        details = item.proposed_action.details
        if (details.get("finding_id") != finding.finding_id
                or details.get("finding_revision") != finding.revision
                or details.get("semantic_digest") != finding.semantic_digest):
            continue
        try:
            event = DecisionEvent.model_validate(raw)
        except ValueError:
            continue
        if event.item_revision != item.revision or event.review_digest != item.review_digest:
            continue
        action = item.proposed_action.action
        if event.verdict.value == "approve":
            record = accepted.get(event.event_id)
            if (record is None or record.item_id != item_id or record.review_id != review_id
                    or record.review_digest != item.review_digest
                    or record.event_digest != sha256_bytes(canonical_bytes(event))):
                continue
            if action == "dismiss_claim_finding" and event.disposition.value == "accept_no_change":
                disposition = "dismiss"
            elif action == "accept_claim_uncertainty" and event.disposition.value == "accept_no_change":
                disposition = "accept_uncertainty"
            elif action == "prepare_claim_source_correction" and event.disposition.value == "source_correction":
                disposition = "confirm_incorrect"
            else:
                continue
        elif event.verdict.value == "discuss" and event.disposition.value == "defer":
            disposition = "discuss"
        elif event.verdict.value == "reject" and event.disposition.value == "reject_action":
            disposition = "pending"
        else:
            continue
        result.append(FindingResolution(
            finding_id=finding.finding_id, disposition=disposition,
            rationale=item.rationale or event.note or "Reviewed finding decision.",
            event_id=event.event_id, decision_revision=event.decision_revision,
        ))
    return tuple(sorted(result, key=lambda value: value.finding_id))


def prepare_finding_disposition(
    item: ReviewItem,
    *,
    alternative: str,
    evidence: tuple[str, ...],
    rationale: str,
    expected_decision_revision: int,
) -> ReviewItem:
    """Create a new local proposal; a note alone never changes a decision."""
    if item.proposed_action.action not in {"resolve_claim_finding", "dismiss_claim_finding", "accept_claim_uncertainty", "prepare_claim_source_correction"}:
        raise PromotionError("item is not a claim finding", code="CLAIMS_DISPOSITION_INVALID")
    if alternative not in {"dismiss", "accept_uncertainty", "source_correction"} or not evidence or not rationale.strip():
        raise PromotionError("prepared disposition requires an exact alternative, evidence and rationale", code="CLAIMS_DISPOSITION_INVALID")
    basis = item.proposed_action.details.get("basis")
    finding_revision = item.proposed_action.details.get("finding_revision")
    if not isinstance(finding_revision, int) or isinstance(finding_revision, bool) or finding_revision < 1:
        raise PromotionError("claim finding is missing its semantic revision", code="CLAIMS_DISPOSITION_INVALID")
    if basis in {"mechanical", "gm_confirmed"} and alternative != "source_correction":
        raise PromotionError("mechanical or confirmed-false findings require source correction", code="CLAIMS_SOURCE_CORRECTION_REQUIRED")
    action = {
        "dismiss": "dismiss_claim_finding",
        "accept_uncertainty": "accept_claim_uncertainty",
        "source_correction": "prepare_claim_source_correction",
    }[alternative]
    details = dict(item.proposed_action.details)
    details.update({
        "basis": basis, "finding_revision": finding_revision,
        "expected_decision_revision": expected_decision_revision,
        "evidence_digest": canonical_digest(evidence),
        "rationale_digest": canonical_digest({"rationale": rationale.strip()}),
        "requires_regeneration": alternative == "source_correction",
    })
    raw = item.model_dump(mode="python")
    raw.update(revision=item.revision + 1, proposed_action={"action": action, "details": details},
               rationale=rationale.strip(), review_digest=None, supersedes_candidate=None)
    return ReviewItem.model_validate(raw)


def build_signoff_context(
    *, analysis_digest: str, resolution_digest: str, support_digest: str,
    audience: str, rule_versions: tuple[tuple[str, str], ...],
    unresolved_required_findings: tuple[str, ...] = (),
    pending_source_corrections: tuple[str, ...] = (),
) -> dict:
    if unresolved_required_findings or pending_source_corrections:
        raise PromotionError("required claim findings remain unresolved", code="CLAIMS_RESOLUTION_REQUIRED")
    values = {
        "analysis_digest": analysis_digest, "resolution_digest": resolution_digest,
        "support_digest": support_digest, "audience": audience,
        "rule_versions": tuple(sorted(rule_versions)),
        "resolution_complete": True, "source_corrections_applied": True,
    }
    return {**values, "signoff_context_digest": canonical_digest(values)}


def validate_signoff_context(value: dict) -> dict:
    """Validate the closed, acyclic context used by v2 document sign-off."""
    # Immutable reviews created before the claims workflow used either of these
    # two closed context shapes.  Keep them readable/signable; new producers use
    # the digest-bound shape below.
    legacy = {"support_digest", "authority_digest", "authority_record_ids", "audience_digest", "rule_digest"}
    transitional = {"analysis_digest", "resolution_digest", "support_digest", "authority_digest", "audience_digest", "rules_digest"}
    if frozenset(value) in {frozenset(legacy), frozenset(transitional)}:
        digest_keys = set(value) - {"authority_record_ids"}
        if any(not isinstance(value[key], str) or len(value[key]) != 64 for key in digest_keys):
            raise PromotionError("v2 sign-off digest is invalid", code="CLAIMS_SIGNOFF_CONTEXT")
        if "authority_record_ids" in value and not isinstance(value["authority_record_ids"], list):
            raise PromotionError("v2 sign-off authority identities are invalid", code="CLAIMS_SIGNOFF_CONTEXT")
        return dict(value)
    required = {
        "analysis_digest", "resolution_digest", "support_digest", "audience",
        "rule_versions", "resolution_complete", "source_corrections_applied",
        "signoff_context_digest",
    }
    if set(value) != required:
        raise PromotionError("v2 sign-off context is incomplete", code="CLAIMS_SIGNOFF_CONTEXT")
    payload = {key: value[key] for key in required - {"signoff_context_digest"}}
    if not value["resolution_complete"] or not value["source_corrections_applied"]:
        raise PromotionError("required claim resolution is not current", code="CLAIMS_RESOLUTION_REQUIRED")
    for key in ("analysis_digest", "resolution_digest", "support_digest"):
        if not isinstance(value[key], str) or len(value[key]) != 64:
            raise PromotionError("v2 sign-off digest is invalid", code="CLAIMS_SIGNOFF_CONTEXT")
    if not isinstance(value["audience"], str) or not value["audience"]:
        raise PromotionError("v2 sign-off audience is invalid", code="CLAIMS_SIGNOFF_CONTEXT")
    try:
        payload["rule_versions"] = tuple(sorted((str(a), str(b)) for a, b in value["rule_versions"]))
    except (TypeError, ValueError) as exc:
        raise PromotionError("v2 sign-off rules are invalid", code="CLAIMS_SIGNOFF_CONTEXT") from exc
    if value["signoff_context_digest"] != canonical_digest(payload):
        raise PromotionError("v2 sign-off context digest differs", code="CLAIMS_SIGNOFF_CONTEXT")
    return {**payload, "signoff_context_digest": value["signoff_context_digest"]}
