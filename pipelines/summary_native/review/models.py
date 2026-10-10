"""Strict, versioned records for the shared campaign review workflow.

The models in this module are storage contracts.  They are immutable, reject
unknown fields, keep exact human/source text unchanged, and use one canonical
JSON representation for content addressing.  Review semantic digests are
deliberately narrower than source custody hashes: changing unrelated bytes in
a containing file does not silently change what the GM reviewed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from base64 import b64decode
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


SCHEMA_VERSION = 1
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ReviewModelError(ValueError):
    """A stable boundary error for malformed serialized review data."""


def _nonblank_exact(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _opaque_id(value: str) -> str:
    if not _ID_RE.fullmatch(value) or ".." in value:
        raise ValueError("must be an opaque identifier, not a path")
    return value


def _sha256(value: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise ValueError("must be a lowercase SHA-256")
    return value


def _relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise ValueError("must be a canonical relative path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path traversal is not allowed")
    return value


NonBlankText = Annotated[str, AfterValidator(_nonblank_exact)]
OpaqueId = Annotated[str, AfterValidator(_opaque_id)]
Sha256 = Annotated[str, AfterValidator(_sha256)]
RelativePath = Annotated[str, AfterValidator(_relative_path)]


def _ensure_json_value(value: Any, location: str = "value") -> None:
    """Reject values canonical JSON cannot represent safely."""

    if value is None or isinstance(value, (str, bool, int, Enum, UUID, datetime)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{location} contains a nonfinite number")
        return
    if isinstance(value, BaseModel):
        for name in value.__class__.model_fields:
            _ensure_json_value(getattr(value, name), f"{location}.{name}")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{location} contains a non-string object key")
            _ensure_json_value(item, f"{location}.{key}")
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            _ensure_json_value(item, f"{location}[{index}]")
        return
    raise ValueError(f"{location} contains unsupported value {type(value).__name__}")


def _utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError(f"{field_name} must be a UTC timestamp")


class StrictReviewModel(BaseModel):
    """Base for persisted records: strict shape, immutable value."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    @model_validator(mode="after")
    def _json_boundary(self):
        _ensure_json_value(self)
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, datetime):
                _utc(value, name)
        return self


def canonicalize(value: Any) -> Any:
    """Convert a record to deterministic JSON-safe values."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        _utc(value, "timestamp")
        return value.isoformat(timespec="microseconds").replace(".000000+00:00", "Z").replace(
            "+00:00", "Z"
        )
    if isinstance(value, BaseModel):
        return {
            name: canonicalize(getattr(value, name))
            for name in value.__class__.model_fields
            if getattr(value, name) is not None
        }
    if isinstance(value, dict):
        return {
            key: canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, (set, frozenset)):
        values = [canonicalize(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if isinstance(value, (tuple, list)):
        return [canonicalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ReviewModelError("canonical JSON cannot contain nonfinite numbers")
    return value


def canonical_bytes(value: Any, *, exclude_fields: frozenset[str] = frozenset()) -> bytes:
    """Serialize canonical UTF-8 JSON with no insignificant whitespace."""

    try:
        _ensure_json_value(value)
        canonical = canonicalize(value)
        if exclude_fields:
            if not isinstance(canonical, dict):
                raise ReviewModelError("fields can be excluded only from a JSON object")
            canonical = {
                key: item for key, item in canonical.items() if key not in exclude_fields
            }
        return json.dumps(
            canonical,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except ReviewModelError:
        raise
    except (TypeError, ValueError) as exc:
        raise ReviewModelError(f"value is not canonical JSON: {exc}") from exc


def canonical_digest(value: Any, *, exclude_fields: frozenset[str] = frozenset()) -> str:
    return hashlib.sha256(canonical_bytes(value, exclude_fields=exclude_fields)).hexdigest()


def parse_json_strict(data: str | bytes) -> Any:
    """Parse UTF-8 JSON while refusing duplicate keys and nonfinite numbers."""

    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewModelError("review JSON must be UTF-8") from exc
    else:
        text = data

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewModelError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ReviewModelError(f"nonfinite JSON number {value!r} is not allowed")

    try:
        return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)
    except ReviewModelError:
        raise
    except json.JSONDecodeError as exc:
        raise ReviewModelError(f"invalid review JSON: {exc.msg}") from exc


ModelT = TypeVar("ModelT", bound=BaseModel)


def model_from_json(model: type[ModelT], data: str | bytes) -> ModelT:
    try:
        return model.model_validate(parse_json_strict(data))
    except ValidationError as exc:
        raise ReviewModelError(str(exc)) from exc


class ReviewKind(str, Enum):
    NPC_VERIFICATION = "npc_verification"
    DUPLICATE_IDENTITY = "duplicate_identity"
    GROUNDING_DOCUMENTS = "grounding_documents"


class ReviewDomain(str, Enum):
    NPC_FINDING = "npc_finding"
    DUPLICATE_IDENTITY = "duplicate_identity"
    GROUNDING_DOCUMENT = "grounding_document"


class Severity(str, Enum):
    BLOCKING = "blocking"
    NEEDS_JUDGMENT = "needs_judgment"
    ADVISORY = "advisory"


class AssignmentBasis(str, Enum):
    MECHANICAL = "mechanical"
    ADVISORY_CANDIDATE = "advisory_candidate"
    GM_CONFIRMED = "gm_confirmed"


class FindingCategory(str, Enum):
    MISSING_SOURCE_OR_POINTER = "missing_source_or_pointer"
    UNSUPPORTED_OR_CONTRADICTED = "unsupported_or_contradicted"
    CITATION_NON_ENTAILMENT = "citation_non_entailment"
    LATER_SOURCE_SUPERSEDES = "later_source_supersedes"
    KNOWLEDGE_LEAK = "knowledge_leak"
    TYPOGRAPHY_PRESENTATION = "typography_presentation"
    VERIFIER_TRANSPORT_PROTOCOL = "verifier_transport_protocol"


class SupportAssessment(str, Enum):
    UNASSESSED = "unassessed"
    CANDIDATE_ISSUE = "candidate_issue"
    GM_SUPPORTED = "gm_supported"
    GM_UNSUPPORTED = "gm_unsupported"


class RuleBinding(StrictReviewModel):
    rule_id: OpaqueId
    version: NonBlankText
    sha256: Sha256 | None = None


class SelectionSubject(StrictReviewModel):
    kind: Literal["source", "subject", "document", "pair"]
    id: OpaqueId


class SourceFile(StrictReviewModel):
    source_id: OpaqueId
    path: RelativePath
    sha256: Sha256
    size: int = Field(ge=0)


class SourceCustodyRef(StrictReviewModel):
    campaign_id: UUID
    review_id: OpaqueId
    generation: int = Field(ge=1)
    digest: Sha256


class SourceCustodyGeneration(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    campaign_id: UUID
    review_id: OpaqueId
    generation: int = Field(ge=1)
    recorded_at: datetime
    previous_generation: int | None = Field(default=None, ge=1)
    sources: tuple[SourceFile, ...] = Field(min_length=1)
    custody_digest: Sha256 | None = None

    @model_validator(mode="after")
    def _generation(self):
        if self.previous_generation is not None and self.previous_generation >= self.generation:
            raise ValueError("previous_generation must be lower than generation")
        ids = [source.source_id for source in self.sources]
        paths = [source.path for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source id")
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate source path")
        expected = canonical_digest(self, exclude_fields=frozenset({"custody_digest"}))
        if self.custody_digest is None:
            object.__setattr__(self, "custody_digest", expected)
        elif self.custody_digest != expected:
            raise ValueError("custody_digest does not match the canonical generation")
        return self


class ItemReference(StrictReviewModel):
    campaign_id: UUID
    review_id: OpaqueId
    item_id: OpaqueId
    revision: int = Field(ge=1)
    review_digest: Sha256


class ReviewManifest(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    campaign_id: UUID
    review_id: OpaqueId
    kind: ReviewKind
    generation: int = Field(ge=1)
    created_at: datetime
    created_by: NonBlankText
    audience: Literal["gm"] = "gm"
    selection: tuple[SelectionSubject, ...] = Field(min_length=1)
    items: tuple[ItemReference, ...]
    source_manifest: SourceCustodyRef
    rule_versions: tuple[RuleBinding, ...]
    history_tip: Sha256 | None = None

    @model_validator(mode="after")
    def _references(self):
        if self.source_manifest.campaign_id != self.campaign_id:
            raise ValueError("source manifest belongs to another campaign")
        if self.source_manifest.review_id != self.review_id:
            raise ValueError("source manifest belongs to another review")
        if self.source_manifest.generation != self.generation:
            raise ValueError("source manifest generation differs from review generation")
        selection_keys = [(entry.kind, entry.id) for entry in self.selection]
        if len(selection_keys) != len(set(selection_keys)):
            raise ValueError("duplicate selection id")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate review item id")
        for item in self.items:
            if item.campaign_id != self.campaign_id:
                raise ValueError(f"{item.item_id}: item belongs to another campaign")
            if item.review_id != self.review_id:
                raise ValueError(f"{item.item_id}: item belongs to another review")
        rule_ids = [rule.rule_id for rule in self.rule_versions]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("duplicate rule id")
        return self


class SubjectReference(StrictReviewModel):
    """Review-local identity, optionally bound to an immutable registry name."""

    subject_id: UUID
    kind: Literal["entity", "document", "claim", "pair"]
    registry_name: NonBlankText | None = None
    registry_type: NonBlankText | None = None
    registry_snapshot_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _registry_binding(self):
        values = (self.registry_name, self.registry_type, self.registry_snapshot_sha256)
        if any(value is not None for value in values) and not all(value is not None for value in values):
            raise ValueError("registry name, type, and snapshot digest must appear together")
        return self


class ItemLocator(StrictReviewModel):
    source_path: RelativePath
    anchor: NonBlankText
    display_line: int | None = Field(default=None, ge=1)


class Evidence(StrictReviewModel):
    source_id: OpaqueId
    source_path: RelativePath
    anchor: NonBlankText
    exact_excerpt: str | None = None
    missing_reason: NonBlankText | None = None
    selected_span_sha256: Sha256 | None = None
    citation_resolved: bool = False
    support: SupportAssessment = SupportAssessment.UNASSESSED

    @model_validator(mode="after")
    def _excerpt_or_missing(self):
        if (self.exact_excerpt is None) == (self.missing_reason is None):
            raise ValueError("evidence requires exactly one of exact_excerpt or missing_reason")
        if self.exact_excerpt is not None:
            if not self.exact_excerpt:
                raise ValueError("exact_excerpt must preserve nonempty source text")
            if self.selected_span_sha256 is None:
                raise ValueError("exact evidence requires selected_span_sha256")
        elif self.selected_span_sha256 is not None:
            raise ValueError("missing evidence cannot have selected_span_sha256")
        if self.support in {SupportAssessment.GM_SUPPORTED, SupportAssessment.GM_UNSUPPORTED}:
            if self.exact_excerpt is None:
                raise ValueError("GM support assessment requires captured evidence")
        return self


class Diagnostic(StrictReviewModel):
    diagnostic_id: OpaqueId
    legacy_code: NonBlankText
    message: NonBlankText
    blocking: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ProposedAction(StrictReviewModel):
    action: NonBlankText
    details: dict[str, Any] = Field(default_factory=dict)


class DecisionScope(StrictReviewModel):
    kind: Literal["global", "chapter", "scene", "location", "document", "evidence"]
    value: NonBlankText | None = None

    @model_validator(mode="after")
    def _scope_value(self):
        if self.kind == "global" and self.value is not None:
            raise ValueError("global scope cannot carry a local value")
        if self.kind != "global" and self.value is None:
            raise ValueError(f"{self.kind} scope requires a value")
        return self


class InputBinding(StrictReviewModel):
    source_id: OpaqueId
    path: RelativePath
    custody_sha256: Sha256
    semantic_sha256: Sha256 | None = None


class ReviewItem(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    item_id: OpaqueId
    revision: int = Field(ge=1)
    campaign_id: UUID
    review_id: OpaqueId
    domain: ReviewDomain
    subject_ref: SubjectReference
    occurrence_id: UUID
    locator: ItemLocator
    claim_text: str | None = None
    failure_context: NonBlankText | None = None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[Diagnostic, ...]
    categories: frozenset[FindingCategory] = Field(min_length=1)
    severity: Severity
    assignment_basis: AssignmentBasis
    rationale: NonBlankText
    proposed_action: ProposedAction
    scope: DecisionScope
    audience: Literal["gm"] = "gm"
    rule_versions: tuple[RuleBinding, ...]
    input_bindings: tuple[InputBinding, ...]
    supersedes_candidate: ItemReference | None = None
    review_digest: Sha256 | None = None

    def semantic_payload(self) -> dict[str, Any]:
        """Return the exact GM-reviewed payload, excluding custody/display data."""

        return {
            "version": self.version,
            "domain": self.domain,
            "subject_ref": self.subject_ref,
            "occurrence_id": self.occurrence_id,
            "claim_text": self.claim_text,
            "failure_context": self.failure_context,
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
            "categories": self.categories,
            "severity": self.severity,
            "assignment_basis": self.assignment_basis,
            "rationale": self.rationale,
            "proposed_action": self.proposed_action,
            "scope": self.scope,
            "audience": self.audience,
            "rule_versions": self.rule_versions,
            "semantic_input_bindings": tuple(
                {
                    "source_id": binding.source_id,
                    "path": binding.path,
                    "semantic_sha256": binding.semantic_sha256,
                }
                for binding in self.input_bindings
                if binding.semantic_sha256 is not None
            ),
        }

    def semantic_digest(self) -> str:
        return canonical_digest(self.semantic_payload())

    @model_validator(mode="after")
    def _semantic_identity(self):
        if (self.claim_text is None) == (self.failure_context is None):
            raise ValueError("item requires exactly one of claim_text or failure_context")
        if self.claim_text is not None and not self.claim_text:
            raise ValueError("claim_text must preserve nonempty exact text")
        diagnostic_ids = [diagnostic.diagnostic_id for diagnostic in self.diagnostics]
        if len(diagnostic_ids) != len(set(diagnostic_ids)):
            raise ValueError("duplicate diagnostic id")
        evidence_keys = [
            (entry.source_id, entry.anchor, entry.selected_span_sha256, entry.missing_reason)
            for entry in self.evidence
        ]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("duplicate evidence entry")
        input_ids = [binding.source_id for binding in self.input_bindings]
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("duplicate input binding")
        rule_ids = [rule.rule_id for rule in self.rule_versions]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("duplicate rule id")
        if self.supersedes_candidate is not None:
            if self.supersedes_candidate.campaign_id != self.campaign_id:
                raise ValueError("supersedes candidate belongs to another campaign")
            if self.supersedes_candidate.review_id != self.review_id:
                raise ValueError("supersedes candidate belongs to another review")
            if self.supersedes_candidate.item_id == self.item_id:
                raise ValueError("item cannot supersede itself")
        expected = self.semantic_digest()
        if self.review_digest is None:
            object.__setattr__(self, "review_digest", expected)
        elif self.review_digest != expected:
            raise ValueError("review_digest does not match the semantic payload")
        return self


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DISCUSS = "discuss"


class DecisionDisposition(str, Enum):
    ACCEPT_NO_CHANGE = "accept_no_change"
    SOURCE_CORRECTION = "source_correction"
    MERGE = "merge"
    DISTINCT = "distinct"
    REJECT_ACTION = "reject_action"
    DEFER = "defer"
    DOCUMENT_SIGNOFF = "document_signoff"


class DecisionEvent(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    event_id: OpaqueId
    request_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    item_id: OpaqueId
    item_revision: int = Field(ge=1)
    review_digest: Sha256
    expected_decision_revision: int = Field(ge=0)
    decision_revision: int = Field(ge=1)
    verdict: Verdict
    disposition: DecisionDisposition
    note: str = ""
    reviewer: NonBlankText
    recorded_at: datetime
    supersedes_event: OpaqueId | None = None
    authority_record_id: OpaqueId | None = None
    proposal_id: OpaqueId | None = None
    proposal_digest: Sha256 | None = None

    @model_validator(mode="after")
    def _decision_meaning(self):
        allowed = {
            Verdict.APPROVE: {
                DecisionDisposition.ACCEPT_NO_CHANGE,
                DecisionDisposition.SOURCE_CORRECTION,
                DecisionDisposition.MERGE,
                DecisionDisposition.DISTINCT,
                DecisionDisposition.DOCUMENT_SIGNOFF,
            },
            Verdict.REJECT: {DecisionDisposition.REJECT_ACTION},
            Verdict.DISCUSS: {DecisionDisposition.DEFER},
        }
        if self.disposition not in allowed[self.verdict]:
            raise ValueError(f"{self.verdict.value} cannot mean {self.disposition.value}")
        if self.decision_revision != self.expected_decision_revision + 1:
            raise ValueError("decision_revision must advance expected_decision_revision by one")
        if (self.expected_decision_revision == 0) != (self.supersedes_event is None):
            raise ValueError("supersedes_event is required exactly when replacing a decision")
        if (self.proposal_id is None) != (self.proposal_digest is None):
            raise ValueError("proposal_id and proposal_digest must appear together")
        if self.disposition in {DecisionDisposition.SOURCE_CORRECTION, DecisionDisposition.MERGE}:
            if self.proposal_id is None:
                raise ValueError(f"{self.disposition.value} approval requires an exact proposal")
        if self.verdict is Verdict.APPROVE and self.authority_record_id is None:
            raise ValueError("approved decisions require an authority record")
        if self.verdict is not Verdict.APPROVE and self.authority_record_id is not None:
            raise ValueError("rejected/discussed decisions are not authority records")
        return self


class DecisionBatch(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    request_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    review_generation: int = Field(ge=1)
    reviewer: NonBlankText
    decisions: tuple[DecisionEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _same_review(self):
        items: list[str] = []
        events: list[str] = []
        for decision in self.decisions:
            if decision.request_id != self.request_id:
                raise ValueError("decision request_id differs from its batch")
            if decision.campaign_id != self.campaign_id:
                raise ValueError("decision belongs to another campaign")
            if decision.review_id != self.review_id:
                raise ValueError("decision belongs to another review")
            if decision.reviewer != self.reviewer:
                raise ValueError("decision reviewer differs from its batch")
            items.append(decision.item_id)
            events.append(decision.event_id)
        if len(items) != len(set(items)):
            raise ValueError("duplicate item in decision batch")
        if len(events) != len(set(events)):
            raise ValueError("duplicate event id in decision batch")
        return self


class DispositionState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISCUSSED = "discussed"


class FreshnessState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    SUPERSEDED = "superseded"


class VerificationState(str, Enum):
    UNCHECKED = "unchecked"
    PASSED_MECHANICAL = "passed_mechanical"
    FAILED_MECHANICAL = "failed_mechanical"
    NEEDS_JUDGMENT = "needs_judgment"


class ApplicationState(str, Enum):
    NONE = "none"
    PROPOSED = "proposed"
    PREPARED = "prepared"
    WRITING = "writing"
    COMMITTED = "committed"
    ATTENTION_REQUIRED = "attention_required"


class ReviewState(StrictReviewModel):
    disposition: DispositionState = DispositionState.PENDING
    freshness: FreshnessState = FreshnessState.CURRENT
    verification: VerificationState = VerificationState.UNCHECKED
    application: ApplicationState = ApplicationState.NONE

    @property
    def settled(self) -> bool:
        return self.disposition is DispositionState.APPROVED and self.freshness is FreshnessState.CURRENT


class ClientSaveState(str, Enum):
    PENDING_SAVE = "pending_save"
    SAVE_FAILED = "save_failed"


class SelectionMember(StrictReviewModel):
    campaign_id: UUID
    review_id: OpaqueId
    item_id: OpaqueId
    item_revision: int = Field(ge=1)
    review_digest: Sha256
    check_ids: tuple[OpaqueId, ...] = Field(min_length=1)
    dependency_hashes: dict[str, Sha256]

    @model_validator(mode="after")
    def _unique_checks(self):
        if len(self.check_ids) != len(set(self.check_ids)):
            raise ValueError("duplicate check id")
        return self


class RerunSelection(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    selection_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    review_generation: int = Field(ge=1)
    mode: Literal["unresolved", "selected"]
    created_at: datetime
    members: tuple[SelectionMember, ...] = Field(min_length=1)
    selection_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _selection(self):
        item_ids: list[str] = []
        for member in self.members:
            if member.campaign_id != self.campaign_id:
                raise ValueError("selection member belongs to another campaign")
            if member.review_id != self.review_id:
                raise ValueError("selection member belongs to another review")
            item_ids.append(member.item_id)
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate selection member")
        expected = canonical_digest(self, exclude_fields=frozenset({"selection_sha256"}))
        if self.selection_sha256 is None:
            object.__setattr__(self, "selection_sha256", expected)
        elif self.selection_sha256 != expected:
            raise ValueError("selection_sha256 does not match selection")
        return self


class RunOutcome(str, Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    FAILED = "failed"
    UNPROCESSED = "unprocessed"


class RunMember(StrictReviewModel):
    item_id: OpaqueId
    item_revision: int = Field(ge=1)
    check_id: OpaqueId
    outcome: RunOutcome
    result_digest: Sha256 | None = None
    message: NonBlankText | None = None

    @model_validator(mode="after")
    def _result(self):
        if self.outcome is RunOutcome.COMPLETED and self.result_digest is None:
            raise ValueError("completed member requires result_digest")
        if self.outcome is not RunOutcome.COMPLETED and self.message is None:
            raise ValueError(f"{self.outcome.value} member requires a message")
        return self


class RunReport(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    run_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    selection_id: OpaqueId
    selection_sha256: Sha256
    started_at: datetime
    finished_at: datetime | None = None
    members: tuple[RunMember, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _run(self):
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at is before started_at")
        keys = [(member.item_id, member.check_id) for member in self.members]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate run member")
        if self.finished_at is not None and any(
            member.outcome is RunOutcome.UNPROCESSED for member in self.members
        ):
            # A finished interrupted run may retain unprocessed members; the
            # state is truthful and deliberately allowed.
            pass
        return self


class AccessAction(str, Enum):
    READ_REVIEW = "read_review"
    SAVE_DECISION = "save_decision"


class AccessGrant(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    grant_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    token_sha256: Sha256
    allowed_actions: frozenset[AccessAction] = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def _lifecycle(self):
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must be after issue time")
        if self.revoked != (self.revoked_at is not None):
            raise ValueError("revoked and revoked_at must change together")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("revoked_at is before issued_at")
        return self


class DecisionBinding(StrictReviewModel):
    event_id: OpaqueId | None = None
    item_id: OpaqueId
    item_revision: int = Field(ge=1)
    review_digest: Sha256
    decision_revision: int = Field(ge=0)


class TargetOperation(str, Enum):
    CREATE = "create"
    REPLACE = "replace"
    DELETE = "delete"


class ProposalTarget(StrictReviewModel):
    path: RelativePath
    operation: TargetOperation
    before_exists: bool
    before_sha256: Sha256 | None = None
    before_bytes_b64: str | None = None
    after_exists: bool
    after_sha256: Sha256 | None = None
    after_bytes_b64: str | None = None

    @model_validator(mode="after")
    def _operation_contract(self):
        for prefix in ("before", "after"):
            exists = getattr(self, f"{prefix}_exists")
            digest = getattr(self, f"{prefix}_sha256")
            encoded = getattr(self, f"{prefix}_bytes_b64")
            if exists != (digest is not None and encoded is not None):
                raise ValueError(f"{prefix} hash/bytes must appear exactly when target exists")
            if encoded is not None:
                try:
                    content = b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise ValueError(f"{prefix}_bytes_b64 is not canonical base64") from exc
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError(f"{prefix}_sha256 does not match bytes")
        expected = {
            TargetOperation.CREATE: (False, True),
            TargetOperation.REPLACE: (True, True),
            TargetOperation.DELETE: (True, False),
        }[self.operation]
        if (self.before_exists, self.after_exists) != expected:
            raise ValueError(f"{self.operation.value} has contradictory existence states")
        return self


class BaseProposal(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    kind: str
    proposal_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    custody: SourceCustodyRef
    decision_bindings: tuple[DecisionBinding, ...] = Field(min_length=1)
    applicable: bool
    blocked_reasons: tuple[NonBlankText, ...] = ()
    targets: tuple[ProposalTarget, ...] = ()
    affected_paths: tuple[RelativePath, ...] = ()
    inspected_paths: tuple[RelativePath, ...] = ()
    collisions: tuple[NonBlankText, ...] = ()
    registry_sha256: Sha256 | None = None
    ledger_sha256: Sha256
    generative_rebuilds: tuple[RelativePath, ...] = ()
    created_at: datetime
    proposal_digest: Sha256 | None = None

    @model_validator(mode="after")
    def _proposal(self):
        if self.custody.campaign_id != self.campaign_id or self.custody.review_id != self.review_id:
            raise ValueError("proposal custody belongs to another campaign or review")
        if self.applicable:
            if self.blocked_reasons or not self.targets:
                raise ValueError("applicable proposal requires targets and no blocked reasons")
        elif not self.blocked_reasons or self.targets:
            raise ValueError("blocked proposal requires reasons and zero mutation targets")
        target_paths = [target.path for target in self.targets]
        if len(target_paths) != len(set(target_paths)):
            raise ValueError("duplicate proposal target")
        for paths, label in (
            (self.affected_paths, "affected path"),
            (self.inspected_paths, "inspected path"),
            (self.generative_rebuilds, "generative rebuild"),
        ):
            if len(paths) != len(set(paths)):
                raise ValueError(f"duplicate {label}")
        if not set(self.affected_paths).issubset(self.inspected_paths):
            raise ValueError("affected paths must be included in inspected paths")
        expected = canonical_digest(self, exclude_fields=frozenset({"proposal_digest"}))
        if self.proposal_digest is None:
            object.__setattr__(self, "proposal_digest", expected)
        elif self.proposal_digest != expected:
            raise ValueError("proposal_digest does not match proposal")
        return self


class SourceCorrectionProposal(BaseProposal):
    kind: Literal["source_correction"] = "source_correction"
    authority_ruling_id: OpaqueId


class IdentityProposal(BaseProposal):
    kind: Literal["identity_merge"] = "identity_merge"
    survivor_subject_id: UUID
    loser_subject_id: UUID
    canonical_registry_name: NonBlankText
    retained_aliases: tuple[NonBlankText, ...]
    scope: DecisionScope

    @model_validator(mode="after")
    def _identity(self):
        if self.survivor_subject_id == self.loser_subject_id:
            raise ValueError("identity proposal needs two distinct review-local subjects")
        if len(self.retained_aliases) != len(set(self.retained_aliases)):
            raise ValueError("duplicate retained alias")
        if self.applicable and self.scope.kind != "global":
            raise ValueError("only global identity proposals are applicable")
        return self


class DocumentPromotionProposal(BaseProposal):
    kind: Literal["document_promotion"] = "document_promotion"
    document_item_id: OpaqueId
    document_sha256: Sha256
    destination: RelativePath
    dependency_hashes: dict[RelativePath, Sha256]


TypedProposal = Annotated[
    SourceCorrectionProposal | IdentityProposal | DocumentPromotionProposal,
    Field(discriminator="kind"),
]
Proposal = TypedProposal


class BaseReceipt(StrictReviewModel):
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    kind: str
    receipt_id: OpaqueId
    campaign_id: UUID
    review_id: OpaqueId
    proposal_id: OpaqueId
    proposal_digest: Sha256
    decision_event_ids: tuple[OpaqueId, ...] = Field(min_length=1)
    changed_paths: tuple[RelativePath, ...]
    before_hashes: dict[RelativePath, Sha256 | None]
    after_hashes: dict[RelativePath, Sha256 | None]
    authority_record_ids: tuple[OpaqueId, ...] = Field(min_length=1)
    ledger_sha256: Sha256
    remaining_review_work: tuple[NonBlankText, ...] = ()
    committed_at: datetime
    receipt_digest: Sha256 | None = None

    @model_validator(mode="after")
    def _receipt(self):
        if len(self.changed_paths) != len(set(self.changed_paths)):
            raise ValueError("duplicate changed path")
        changed = set(self.changed_paths)
        if set(self.before_hashes) != changed or set(self.after_hashes) != changed:
            raise ValueError("receipt hashes must name exactly the changed paths")
        expected = canonical_digest(self, exclude_fields=frozenset({"receipt_digest"}))
        if self.receipt_digest is None:
            object.__setattr__(self, "receipt_digest", expected)
        elif self.receipt_digest != expected:
            raise ValueError("receipt_digest does not match receipt")
        return self


class SourceCorrectionReceipt(BaseReceipt):
    kind: Literal["source_correction"] = "source_correction"
    authority_ruling_id: OpaqueId


class IdentityReceipt(BaseReceipt):
    kind: Literal["identity_merge"] = "identity_merge"
    survivor_subject_id: UUID
    loser_subject_id: UUID
    canonical_registry_name: NonBlankText


class DocumentPromotionReceipt(BaseReceipt):
    kind: Literal["document_promotion"] = "document_promotion"
    document_item_id: OpaqueId
    published_sha256: Sha256


TypedReceipt = Annotated[
    SourceCorrectionReceipt | IdentityReceipt | DocumentPromotionReceipt,
    Field(discriminator="kind"),
]
Receipt = TypedReceipt


# Concise public aliases used by storage and CLI code.
Manifest = ReviewManifest
Decision = DecisionEvent
Grant = AccessGrant
Selection = RerunSelection
