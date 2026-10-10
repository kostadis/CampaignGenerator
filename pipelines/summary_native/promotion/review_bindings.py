"""Exact v2 document sign-off validation for promotion."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pipelines.summary_native.authority import ReviewDecisionRecord, load_ledger, sha256_bytes
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import (
    BundleSelection,
    DocumentSignoffBinding,
    GateOutcome,
    GroundingDocument,
    Sha256,
    SignoffSet,
)
from pipelines.summary_native.promotion.gates import check_signoffs
from pipelines.summary_native.review.models import DecisionEvent, canonical_bytes, canonical_digest
from pipelines.summary_native.review.store import read_snapshot, history


class _V2Context(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    support_digest: Sha256
    authority_digest: Sha256
    authority_record_ids: list[str] = Field(default_factory=list)
    audience_digest: Sha256
    rule_digest: Sha256


def _item_v2(item: object) -> bool:
    versions = getattr(item, "rule_versions", ())
    return any(
        getattr(value, "rule_id", None) == "grounding-bundle-signoff"
        and getattr(value, "version", None) == "2"
        for value in versions
    )


def load_signoff_bindings(
    campaign_dir: Path, bundle: BundleSelection, *,
    analysis_digest: str | None = None, resolution_digest: str | None = None,
    _already_locked: bool = False,
) -> SignoffSet:
    """Load four current v2 sign-offs and verify their accepted audit records."""
    root = Path(campaign_dir).resolve()
    manifest, _custody, items = read_snapshot(
        root, bundle.review_id, _already_locked=_already_locked,
    )
    if str(manifest.campaign_id) != bundle.campaign_id:
        raise PromotionError("review belongs to another campaign", code="PROMOTION_REVIEW_FOREIGN")
    events = history(root, bundle.review_id, _already_locked=_already_locked)
    ledger = load_ledger(root)
    accepted = {
        record.id: record
        for record in ledger.records
        if isinstance(record, ReviewDecisionRecord) and record.status == "accepted"
    }
    current: dict[str, dict | None] = {}
    for event in events:
        item_id = event.get("item_id")
        prior = current.get(item_id) if isinstance(item_id, str) else None
        if isinstance(item_id, str) and int(event.get("decision_revision", 0)) >= int(
            prior.get("decision_revision", 0) if isinstance(prior, dict) else 0
        ):
            current[item_id] = None if event.get("kind") == "withdrawal" else event

    expected = {member.document_id: member for member in bundle.documents}
    support_digest = canonical_digest(
        [
            item.model_dump(mode="json")
            for item in sorted(
                (bundle.timeline, *bundle.references, *bundle.retained_records, *bundle.dependencies),
                key=lambda value: value.path,
            )
        ]
    )
    audience_digest = canonical_digest({"audience": bundle.audience})
    rule_digest = canonical_digest({"rule_versions": sorted(bundle.rule_versions)})
    authority_by_id = {record.id: record for record in ledger.records}
    bindings: list[DocumentSignoffBinding] = []
    for item in items:
        details = item.proposed_action.details
        if item.proposed_action.action != "signoff_document" or not isinstance(details, dict):
            continue
        try:
            document = GroundingDocument(details["document_id"])
        except (KeyError, ValueError):
            continue
        if document not in expected or not _item_v2(item):
            continue
        member = expected[document]
        if details.get("document_sha256") != member.sha256:
            raise PromotionError(f"stale document sign-off item: {document.value}", code="PROMOTION_SIGNOFF_STALE")
        raw_context = details.get("signoff_context")
        new_context = None
        try:
            from pipelines.summary_native.claims.review import validate_signoff_context
            candidate_context = validate_signoff_context(dict(raw_context))
            if "signoff_context_digest" in candidate_context:
                new_context = candidate_context
        except (TypeError, ValueError, PromotionError):
            new_context = None
        if new_context is not None:
            if analysis_digest is None or resolution_digest is None:
                raise PromotionError("claims report context is required for sign-off", code="PROMOTION_SIGNOFF_STALE")
            signed_rules = tuple(f"{rule}/{version}" for rule, version in new_context["rule_versions"])
            if (
                new_context["analysis_digest"] != analysis_digest
                or new_context["resolution_digest"] != resolution_digest
                or new_context["support_digest"] != support_digest
                or new_context["audience"] != bundle.audience
                or tuple(sorted(signed_rules)) != tuple(sorted(bundle.rule_versions))
            ):
                raise PromotionError(
                    f"signed claims, support, audience, or rules changed: {document.value}",
                    code="PROMOTION_SIGNOFF_STALE",
                )
            context = None
        else:
            context = _V2Context.model_validate(raw_context)
        selected_authority = []
        for record_id in context.authority_record_ids if context is not None else ():
            record_value = authority_by_id.get(record_id)
            if record_value is None:
                raise PromotionError("signed authority context is missing", code="PROMOTION_SIGNOFF_STALE")
            selected_authority.append(record_value.model_dump(mode="json"))
        current_authority_digest = canonical_digest(selected_authority)
        if context is not None and (
            context.support_digest != support_digest
            or context.authority_digest != current_authority_digest
            or context.audience_digest != audience_digest
            or context.rule_digest != rule_digest
        ):
            raise PromotionError(
                f"signed support, authority, audience, or rules changed: {document.value}",
                code="PROMOTION_SIGNOFF_STALE",
            )
        raw_event = current.get(item.item_id)
        if raw_event is None:
            continue
        event = DecisionEvent.model_validate(raw_event)
        if event.verdict.value != "approve" or event.disposition.value != "document_signoff":
            continue
        record = accepted.get(event.authority_record_id or "")
        if (
            record is None
            or record.campaign_id != manifest.campaign_id
            or record.review_id != bundle.review_id
            or record.item_id != item.item_id
            or record.item_revision != item.revision
            or record.event_id != event.event_id
            or record.decision_revision != event.decision_revision
            or record.review_digest != item.review_digest
            or record.event_digest != sha256_bytes(canonical_bytes(event))
            or record.disposition != "document_signoff"
            or record.domain != "grounding_document"
        ):
            raise PromotionError(
                f"accepted audit record is missing or stale: {document.value}",
                code="PROMOTION_SIGNOFF_AUDIT_INVALID",
            )
        bindings.append(
            DocumentSignoffBinding(
                document_id=document,
                document_sha256=member.sha256,
                review_id=bundle.review_id,
                item_id=item.item_id,
                item_revision=item.revision,
                review_digest=item.review_digest,
                decision_event_id=event.event_id,
                decision_revision=event.decision_revision,
                accepted_audit_record_id=record.id,
                support_digest=(context.support_digest if context is not None else new_context["support_digest"]),
                authority_digest=(context.authority_digest if context is not None else canonical_digest([])),
                authority_record_ids=tuple(context.authority_record_ids) if context is not None else (),
                audience_digest=(context.audience_digest if context is not None else audience_digest),
                rule_digest=(context.rule_digest if context is not None else rule_digest),
                analysis_digest=new_context["analysis_digest"] if new_context is not None else None,
                resolution_digest=new_context["resolution_digest"] if new_context is not None else None,
                signoff_context_digest=new_context["signoff_context_digest"] if new_context is not None else None,
            )
        )
    try:
        return SignoffSet(bindings=tuple(bindings))
    except ValueError as exc:
        raise PromotionError(
            "four distinct current grounding-bundle-signoff/2 decisions are required",
            code="PROMOTION_SIGNOFF_REQUIRED",
        ) from exc


def validate_signoff_bindings(bundle: BundleSelection, signoffs: SignoffSet | None) -> GateOutcome:
    """Validate supplied typed bindings; storage loading is added with US3 producers."""
    return check_signoffs(bundle, signoffs)
