"""Strict, digest-bound records for cross-document claim checking."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from pipelines.summary_native.promotion.models import OpaqueId, RelativePath, Sha256, StrictPromotionModel
from pipelines.summary_native.review.models import canonical_digest


class SourceKind(str, Enum):
    DRAFT = "draft"
    SUPPORT = "support"
    RUN_RECORD = "run_record"
    SUMMARY = "summary"
    AUTHORITY = "authority"
    NOTE = "note"


class SourceRole(str, Enum):
    CLAIM = "claim"
    COUNTERPART = "counterpart"
    CONTEXT = "context"
    AUTHORITY = "authority"


class AuthorityClass(str, Enum):
    CANON = "CANON"
    TABLE = "TABLE"
    PREP = "PREP"
    OVERLAY = "OVERLAY"
    OPEN = "OPEN"


class ClaimPredicate(str, Enum):
    ACTOR = "actor_assignment"
    FACTION = "faction_affiliation"
    POSTURE = "faction_posture"
    IDENTITY = "identity"
    CERTAINTY = "certainty"
    OBLIGATION_STATUS = "obligation_status"
    OBLIGATION_AMOUNT = "obligation_amount"
    LOCATION = "location"
    STATUS = "status"
    TEMPORAL_ORDER = "temporal_order"


class SourceEntry(StrictPromotionModel):
    source_id: OpaqueId
    path: RelativePath
    sha256: Sha256
    source_kind: SourceKind
    role: SourceRole
    source_audience: str = Field(min_length=1)
    authority_class: AuthorityClass
    applicability: Literal["fact_authority", "mapping_evidence", "context_only"]
    anchor: str = Field(min_length=1)
    excerpt_sha256: Sha256
    context_sha256: Sha256
    authority_record_ids: tuple[OpaqueId, ...] = ()
    authority_record_digests: dict[OpaqueId, Sha256] = Field(default_factory=dict)
    required: bool = False


class SelectedChunk(StrictPromotionModel):
    chunk_id: OpaqueId
    source_id: OpaqueId
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)
    sha256: Sha256
    locator: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered(self) -> "SelectedChunk":
        if self.end_byte <= self.start_byte:
            raise ValueError("chunk end must follow start")
        return self


class SourceSelection(StrictPromotionModel):
    schema_version: Literal[1] = 1
    campaign_id: OpaqueId
    bundle_digest: Sha256
    out_root: RelativePath
    range_since: int = Field(ge=0)
    range_until: int = Field(ge=0)
    effective_horizon: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    sources: tuple[SourceEntry, ...]
    suggested_sources: tuple[SourceEntry, ...] = ()
    chunks: tuple[SelectedChunk, ...]
    unresolved_scope: tuple[str, ...] = ()
    rule_versions: tuple[str, ...]
    selection_digest: Sha256
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    confirmed_digest: Sha256 | None = None

    @model_validator(mode="after")
    def valid(self) -> "SourceSelection":
        if self.range_until < self.range_since:
            raise ValueError("range_until must be greater than or equal to range_since")
        source_ids = [item.source_id for item in self.sources]
        suggested_ids = [item.source_id for item in self.suggested_sources]
        if len(source_ids + suggested_ids) != len(set(source_ids + suggested_ids)):
            raise ValueError("source ids must be unique")
        if any(chunk.source_id not in source_ids for chunk in self.chunks):
            raise ValueError("each selected chunk must name an explicit source")
        expected = canonical_digest(self, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}))
        if self.selection_digest != expected:
            raise ValueError("selection_digest does not match selected inputs")
        confirmations = (self.confirmed_by, self.confirmed_at, self.confirmed_digest)
        if any(value is not None for value in confirmations) != all(value is not None for value in confirmations):
            raise ValueError("selection confirmation fields must appear together")
        if self.confirmed_at is not None:
            if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() != timezone.utc.utcoffset(self.confirmed_at):
                raise ValueError("confirmed_at must be UTC")
            expected_confirmation = canonical_digest(self, exclude_fields=frozenset({"confirmed_digest"}))
            if self.confirmed_digest != expected_confirmation:
                raise ValueError("confirmed_digest does not match confirmation")
        return self


class ClaimAnnotation(StrictPromotionModel):
    schema_version: Literal[1] = 1
    occurrence_id: OpaqueId
    revision: int = Field(ge=1)
    source_id: OpaqueId
    source_path: RelativePath
    source_role: SourceRole
    evidence_kind: Literal["source_span", "authority_record"] = "source_span"
    anchor: str = Field(min_length=1)
    start_byte: int | None = Field(default=None, ge=0)
    end_byte: int | None = Field(default=None, gt=0)
    source_sha256: Sha256
    span_sha256: Sha256
    context_sha256: Sha256
    original_span: str = Field(min_length=1)
    subject_id: OpaqueId | None = None
    subject_identity_kind: Literal["entity", "thread", "topic", "obligation"] | None = None
    subject_identity_resolved: bool = True
    predicate: ClaimPredicate | None = None
    normalized_value: str | int | bool | None = None
    certainty: Literal["certain", "probable", "possible", "unknown"] = "unknown"
    effective_from: str | None = None
    effective_until: str | None = None
    audience: str
    authority_record_ids: tuple[OpaqueId, ...] = ()
    authority_record_digests: dict[OpaqueId, Sha256] = Field(default_factory=dict)
    origin: Literal["structured_source", "human_candidate", "model_candidate"]
    interpretation_state: Literal["candidate", "mapping_confirmed", "rejected", "discuss"]
    extraction_run_id: OpaqueId | None = None
    prompt_digest: Sha256 | None = None
    model_id: str | None = None
    input_digest: Sha256 | None = None
    review_item_id: OpaqueId | None = None
    review_item_digest: Sha256 | None = None
    mapping_event_id: OpaqueId | None = None
    supersedes_occurrence_id: OpaqueId | None = None

    @model_validator(mode="after")
    def origin_identity(self) -> "ClaimAnnotation":
        if self.evidence_kind == "source_span":
            if self.start_byte is None or self.end_byte is None or self.end_byte <= self.start_byte:
                raise ValueError("source span evidence requires ordered byte offsets")
        elif self.start_byte is not None or self.end_byte is not None:
            raise ValueError("authority record evidence does not use source byte offsets")
        model_fields = (self.extraction_run_id, self.prompt_digest, self.model_id, self.input_digest)
        if self.origin == "model_candidate" and not all(value is not None for value in model_fields):
            raise ValueError("model candidates require exact extraction identity")
        if self.origin != "model_candidate" and any(value is not None for value in model_fields):
            raise ValueError("only model candidates may carry extraction identity")
        if self.interpretation_state == "mapping_confirmed" and not self.mapping_event_id:
            raise ValueError("confirmed mappings require their review event")
        if self.origin == "structured_source" and not self.authority_record_ids:
            raise ValueError("structured source claims require an authority record identity")
        if self.origin == "structured_source" and set(self.authority_record_digests) != set(self.authority_record_ids):
            raise ValueError("structured source claims require exact authority record digests")
        if self.origin != "structured_source" and self.authority_record_digests:
            raise ValueError("candidate mappings cannot claim structured authority digests")
        return self


def validate_annotation_authority(
    annotation: ClaimAnnotation, active_authority: frozenset[str] | dict[str, str]
) -> None:
    """Refuse a structured claim unless every bound authority record is currently active."""
    if annotation.origin != "structured_source":
        return
    if not set(annotation.authority_record_ids) <= set(active_authority):
        raise ValueError("structured claim authority is absent, inactive, or stale")
    if isinstance(active_authority, dict) and annotation.authority_record_digests != {
        record_id: active_authority[record_id] for record_id in annotation.authority_record_ids
    }:
        raise ValueError("structured claim authority payload is stale")


class ChunkOutcome(StrictPromotionModel):
    chunk_id: OpaqueId
    outcome: Literal["pending", "completed", "failed", "invalid_output"]
    candidate_ids: tuple[OpaqueId, ...] = ()
    detail: str | None = None


class CandidateRun(StrictPromotionModel):
    schema_version: Literal[1] = 1
    run_id: OpaqueId
    revision: int = Field(ge=1)
    selection_digest: Sha256
    packet_digest: Sha256
    backend: str
    model: str
    prompt_digest: Sha256
    rule_digest: Sha256
    chunk_ids: tuple[OpaqueId, ...]
    outcomes: tuple[ChunkOutcome, ...]
    candidate_annotation_ids: tuple[OpaqueId, ...] = ()
    finding_ids: tuple[OpaqueId, ...] = ()
    created_at: datetime
    completed_at: datetime | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    failure_detail: str | None = None

    @model_validator(mode="after")
    def complete_identity(self) -> "CandidateRun":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timezone.utc.utcoffset(self.created_at):
            raise ValueError("created_at must be UTC")
        if self.completed_at is not None and (
            self.completed_at.tzinfo is None or self.completed_at.utcoffset() != timezone.utc.utcoffset(self.completed_at)
        ):
            raise ValueError("completed_at must be UTC")
        if tuple(item.chunk_id for item in self.outcomes) != self.chunk_ids:
            raise ValueError("candidate run must expose one ordered outcome per selected chunk")
        if all(item.outcome == "completed" for item in self.outcomes) != (self.completed_at is not None):
            raise ValueError("completed_at is present exactly for a fully completed run")
        return self


class ExtractionRunBinding(StrictPromotionModel):
    """Exact immutable extractor run identity carried into deterministic analysis."""
    run_id: OpaqueId
    revision: int = Field(ge=1)
    run_digest: Sha256
    selection_digest: Sha256
    packet_digest: Sha256
    outcome_digest: Sha256
    complete: bool


class ClaimFinding(StrictPromotionModel):
    schema_version: Literal[1] = 1
    finding_id: OpaqueId
    revision: int = Field(ge=1)
    categories: tuple[Literal["direct_contradiction", "stale_superseded", "suspicion_as_fact", "audience_leak", "resolved_as_active", "incompatible_state"], ...]
    annotation_ids: tuple[OpaqueId, ...]
    source_ids: tuple[OpaqueId, ...] = ()
    missing_counterpart: str | None = None
    rule_id: str
    rule_version: str
    audience: str
    effective_horizon: str
    basis: Literal["mechanical", "semantic_candidate", "gm_confirmed"]
    severity: Literal["blocking", "warning", "informational"]
    evidence: tuple[str, ...]
    rationale: str
    next_action: str
    required_disposition: bool
    decision_event_id: OpaqueId | None = None
    semantic_digest: Sha256

    @model_validator(mode="after")
    def paired_mechanical_evidence(self) -> "ClaimFinding":
        if self.basis == "mechanical" and len(self.annotation_ids) + len(self.source_ids) < 2:
            raise ValueError("mechanical findings require both compared evidence identities")
        if not self.annotation_ids and not self.missing_counterpart:
            raise ValueError("finding requires evidence or an explicit missing counterpart")
        return self


class FindingResolution(StrictPromotionModel):
    finding_id: OpaqueId
    disposition: Literal["dismiss", "accept_uncertainty", "confirm_incorrect", "discuss", "pending"]
    rationale: str = Field(min_length=1)
    event_id: OpaqueId | None = None
    decision_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def decision_binding(self) -> "FindingResolution":
        if (self.event_id is None) != (self.decision_revision is None):
            raise ValueError("resolution event and decision revision must appear together")
        return self


class CheckReport(StrictPromotionModel):
    schema_version: Literal[1] = 1
    report_id: OpaqueId
    review_id: OpaqueId | None = None
    bundle_digest: Sha256
    source_selection_digest: Sha256
    mapping_set_digest: Sha256
    analysis_digest: Sha256
    resolution_digest: Sha256
    annotations: tuple[ClaimAnnotation, ...]
    findings: tuple[ClaimFinding, ...]
    resolutions: tuple[FindingResolution, ...]
    rule_outcomes: tuple[dict[str, str], ...]
    effective_horizon: str
    audience: str
    selected_chunk_ids: tuple[OpaqueId, ...]
    extraction_complete: bool | None = None
    extraction_run: ExtractionRunBinding | None = None
    coverage_limitations: tuple[str, ...]
    review_event_ids: tuple[OpaqueId, ...]
    authority_record_ids: tuple[OpaqueId, ...]
    json_path: RelativePath
    markdown_path: RelativePath
    outcome: Literal["complete", "blocked", "incomplete"]
    report_digest: Sha256


class ClaimDigestChain(StrictPromotionModel):
    """Named acyclic identities; each stage binds only identities to its left."""

    source_selection_digest: Sha256
    mapping_set_digest: Sha256
    analysis_digest: Sha256
    resolution_digest: Sha256
    signoff_context_digest: Sha256
