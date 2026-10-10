"""Strict persisted and computed records for grounding-bundle promotion."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from pipelines.summary_native.review.models import canonical_digest


SCHEMA_VERSION = 1
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _sha(value: str) -> str:
    if not _SHA.fullmatch(value):
        raise ValueError("must be a lowercase SHA-256")
    return value


def _opaque(value: str) -> str:
    if not _ID.fullmatch(value) or ".." in value:
        raise ValueError("must be an opaque identifier")
    return value


def _relative(value: str) -> str:
    if not value or value == "." or "\\" in value or "\x00" in value:
        raise ValueError("must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("must be a canonical contained relative path")
    return value


Sha256 = Annotated[str, AfterValidator(_sha)]
OpaqueId = Annotated[str, AfterValidator(_opaque)]
RelativePath = Annotated[str, AfterValidator(_relative)]


class StrictPromotionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, strict=True)


class GroundingDocument(str, Enum):
    WORLD_STATE = "world_state"
    CAMPAIGN_STATE = "campaign_state"
    PARTY = "party"
    PLANNING = "planning"


class RangeSelection(StrictPromotionModel):
    since: int = Field(ge=0)
    until: int = Field(ge=0)
    out_root: RelativePath

    @model_validator(mode="after")
    def ordered(self) -> "RangeSelection":
        if self.until < self.since:
            raise ValueError("until must be greater than or equal to since")
        return self


class ContentIdentity(StrictPromotionModel):
    path: RelativePath
    sha256: Sha256
    size: int = Field(ge=0)


class DocumentMember(ContentIdentity):
    document_id: GroundingDocument


class PathIdentity(StrictPromotionModel):
    path: RelativePath
    kind: Literal["absent", "file", "directory", "symlink"]
    sha256: Sha256 | None = None
    target: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> "PathIdentity":
        if self.kind == "symlink":
            if not self.target or self.sha256 is not None:
                raise ValueError("symlink identity requires only its raw target")
        elif self.target is not None:
            raise ValueError("only symlink identity may carry a target")
        elif self.kind == "absent" and self.sha256 is not None:
            raise ValueError("absent identity cannot carry a digest")
        elif self.kind in {"file", "directory"} and self.sha256 is None:
            raise ValueError("present identity requires a digest")
        return self


class BundleSelection(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    campaign_id: OpaqueId
    selected_range: RangeSelection
    documents: tuple[DocumentMember, ...]
    timeline: ContentIdentity
    references: tuple[ContentIdentity, ...]
    retained_records: tuple[ContentIdentity, ...]
    dependencies: tuple[ContentIdentity, ...]
    config_identity: ContentIdentity
    alias_identities: tuple[PathIdentity, ...]
    audience: Literal["gm"] = "gm"
    review_id: OpaqueId
    rule_versions: tuple[str, ...]

    @model_validator(mode="after")
    def complete(self) -> "BundleSelection":
        expected = set(GroundingDocument)
        actual = [item.document_id for item in self.documents]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("bundle requires exactly one of each grounding document")
        paths = [item.path for item in self.documents]
        paths += [self.timeline.path]
        paths += [item.path for item in self.references]
        paths += [item.path for item in self.retained_records]
        if len(paths) != len(set(paths)):
            raise ValueError("bundle paths must be unique")
        folded = [path.casefold() for path in paths]
        if len(folded) != len(set(folded)):
            raise ValueError("bundle paths collide by case")
        expected_aliases = {
            "docs/world_state.md", "docs/campaign_state.md", "docs/party.md",
            "docs/planning.md", "docs/canon_events_timeline.md", "docs/reference",
        }
        if {item.path for item in self.alias_identities} != expected_aliases:
            raise ValueError("bundle requires the exact six managed alias identities")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self)


class GateOutcome(StrictPromotionModel):
    gate: OpaqueId
    state: Literal["passed", "blocked", "incomplete", "not_available"]
    code: str | None = None
    message: str
    relevant_digest: Sha256 | None = None


class DocumentSignoffBinding(StrictPromotionModel):
    document_id: GroundingDocument
    document_sha256: Sha256
    review_id: OpaqueId
    item_id: OpaqueId
    item_revision: int = Field(ge=1)
    review_digest: Sha256
    decision_event_id: OpaqueId
    decision_revision: int = Field(ge=1)
    accepted_audit_record_id: OpaqueId
    support_digest: Sha256
    authority_digest: Sha256
    authority_record_ids: tuple[OpaqueId, ...] = ()
    audience_digest: Sha256
    rule_digest: Sha256
    analysis_digest: Sha256 | None = None
    resolution_digest: Sha256 | None = None
    signoff_context_digest: Sha256 | None = None
    rule_id: Literal["grounding-bundle-signoff/2"] = "grounding-bundle-signoff/2"


class SignoffSet(StrictPromotionModel):
    bindings: tuple[DocumentSignoffBinding, ...]

    @model_validator(mode="after")
    def complete(self) -> "SignoffSet":
        documents = [binding.document_id for binding in self.bindings]
        if len(documents) != 4 or set(documents) != set(GroundingDocument):
            raise ValueError("four distinct current document sign-offs are required")
        return self

    @property
    def digest(self) -> str:
        return canonical_digest(self)


class PathChange(StrictPromotionModel):
    path: RelativePath
    kind: Literal["add", "replace", "remove", "unchanged", "type_change"]
    before_sha256: Sha256 | None = None
    after_sha256: Sha256 | None = None
    before_type: Literal["file", "directory", "symlink", "absent"]
    after_type: Literal["file", "directory", "symlink", "absent"]
    unified_diff: str | None = None
    binary: bool = False


class PromotionPreview(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    campaign_id: OpaqueId
    bundle_digest: Sha256
    report_analysis_digest: Sha256 | None = None
    report_resolution_digest: Sha256 | None = None
    signoff_context_digest: Sha256 | None = None
    expected_generation_id: OpaqueId | None = None
    expected_activation_id: OpaqueId | None = None
    live_digest: Sha256 | None = None
    destination_edited_since_publication: bool | None = None
    changes: tuple[PathChange, ...]
    gates: tuple[GateOutcome, ...]
    eligible: bool
    refusal_codes: tuple[str, ...]
    preview_sha256: Sha256

    @classmethod
    def with_digest(cls, **values: object) -> "PromotionPreview":
        provisional = dict(values)
        provisional["preview_sha256"] = "0" * 64
        value = cls.model_validate(provisional)
        digest = canonical_digest(value, exclude_fields=frozenset({"preview_sha256"}))
        provisional["preview_sha256"] = digest
        return cls.model_validate(provisional)


class GenerationKind(str, Enum):
    PUBLISHED = "published"
    LEGACY_ADOPTION = "legacy_adoption"


class RetainedRecordBinding(StrictPromotionModel):
    document_path: RelativePath
    embedded_locator: RelativePath
    anchor: str = Field(min_length=1)
    original_base: RelativePath
    retained_path: RelativePath
    sha256: Sha256


class GenerationManifest(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    generation_id: OpaqueId
    operation_id: OpaqueId
    campaign_id: OpaqueId
    selected_range: RangeSelection | None = None
    kind: GenerationKind
    members: tuple[ContentIdentity, ...]
    retained_records: tuple[RetainedRecordBinding, ...]
    external_dependencies: tuple[ContentIdentity, ...]
    published_path: RelativePath
    live_path: RelativePath
    bundle_digest: Sha256 | None = None
    analysis_digest: Sha256 | None = None
    parent_activation_id: OpaqueId | None = None
    created_at: datetime
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def utc(self) -> "GenerationManifest":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timezone.utc.utcoffset(self.created_at):
            raise ValueError("created_at must be UTC")
        return self


class AttemptState(str, Enum):
    PREPARED = "prepared"
    STAGED = "staged"
    ACTIVATION_PENDING = "activation_pending"
    COMMITTED = "committed"
    ABORTED = "aborted"
    COMMIT_UNKNOWN = "commit_unknown"
    INTERVENTION_REQUIRED = "intervention_required"


class OperationIntent(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    operation_id: OpaqueId
    request_id: OpaqueId
    campaign_id: OpaqueId
    preview_sha256: Sha256
    bundle_digest: Sha256
    expected_generation_id: OpaqueId | None = None
    expected_activation_id: OpaqueId | None = None
    expected_live_digest: Sha256 | None = None
    generation_id: OpaqueId
    created_at: datetime

    @model_validator(mode="after")
    def utc(self) -> "OperationIntent":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timezone.utc.utcoffset(self.created_at):
            raise ValueError("created_at must be UTC")
        return self


class OperationState(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    operation_id: OpaqueId
    state: AttemptState
    intent_sha256: Sha256
    generation_manifest_sha256: Sha256 | None = None
    receipt_candidate_sha256: Sha256 | None = None
    activation_id: OpaqueId | None = None
    detail: str | None = None


class PublicationReceiptCandidate(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    receipt_id: OpaqueId
    operation_id: OpaqueId
    request_id: OpaqueId
    campaign_id: OpaqueId
    generation_id: OpaqueId
    generation_manifest_sha256: Sha256
    preview_sha256: Sha256
    bundle_digest: Sha256
    previous_snapshot_sha256: Sha256 | None = None
    review_event_ids: tuple[OpaqueId, ...]
    gates: tuple[GateOutcome, ...]
    prepared_at: datetime
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def valid(self) -> "PublicationReceiptCandidate":
        if self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() != timezone.utc.utcoffset(self.prepared_at):
            raise ValueError("prepared_at must be UTC")
        expected = canonical_digest(self, exclude_fields=frozenset({"receipt_sha256"}))
        if self.receipt_sha256 != expected:
            raise ValueError("receipt_sha256 does not match receipt candidate")
        return self


class BaselineKind(str, Enum):
    ACTIVATION = "activation"
    LEGACY_BASELINE = "legacy_baseline"
    ABSENT = "absent"


class ActivationRecord(StrictPromotionModel):
    schema_version: Literal[1] = SCHEMA_VERSION
    activation_id: OpaqueId
    operation_id: OpaqueId
    generation_id: OpaqueId
    manifest_sha256: Sha256
    receipt_candidate_sha256: Sha256 | None = None
    migration_receipt_sha256: Sha256 | None = None
    parent_activation_id: OpaqueId | None = None
    parent_activation_sha256: Sha256 | None = None
    baseline_kind: BaselineKind
    previous_snapshot_sha256: Sha256 | None = None
    actor: str = Field(min_length=1)
    completed_at: datetime
    recovered_at: datetime | None = None
    observed_after: datetime | None = None
    observed_before: datetime | None = None

    @model_validator(mode="after")
    def valid(self) -> "ActivationRecord":
        if (self.parent_activation_id is None) != (self.parent_activation_sha256 is None):
            raise ValueError("parent activation identity and digest must appear together")
        if self.baseline_kind is BaselineKind.LEGACY_BASELINE:
            if self.migration_receipt_sha256 is None or self.receipt_candidate_sha256 is not None:
                raise ValueError("legacy baseline activation requires only a migration receipt")
        elif self.baseline_kind is BaselineKind.ACTIVATION:
            if self.receipt_candidate_sha256 is None or self.migration_receipt_sha256 is not None:
                raise ValueError("publication activation requires only a receipt candidate")
        else:
            raise ValueError("absent baseline has no activation record")
        for name in ("completed_at", "recovered_at", "observed_after", "observed_before"):
            value = getattr(self, name)
            if value is not None and (value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value)):
                raise ValueError(f"{name} must be UTC")
        return self
