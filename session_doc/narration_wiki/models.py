"""Stable narration-wiki value objects and canonical serialization helpers."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MEASUREMENT_PROFILE = "d4-v1"
STABLE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class NarrationWikiError(Exception):
    """Known refusal whose ``exit_code`` is part of the public CLI contract."""

    exit_code = 70


class UsageError(NarrationWikiError):
    exit_code = 2


class ScopeError(NarrationWikiError):
    exit_code = 3


class StateError(NarrationWikiError):
    exit_code = 4


class ValidationError(NarrationWikiError):
    exit_code = 5


class MutationError(NarrationWikiError):
    exit_code = 6


class IterationState(str, Enum):
    NEW = "new"
    COLLECTED = "collected"
    MEASURED_BEFORE = "measured_before"
    GATE1_REVIEW = "gate1_review"
    READY_FOR_PROPOSAL = "ready_for_proposal"
    PROPOSAL_STAGED = "proposal_staged"
    COMPARISON_APPLIED = "comparison_applied"
    MEASURED_AFTER = "measured_after"
    AWAITING_GATE2 = "awaiting_gate2"
    COMPLETED_ACCEPTED = "completed_accepted"
    COMPLETED_REJECTED = "completed_rejected"


class ProposalState(str, Enum):
    DRAFTED = "drafted"
    STAGED = "staged"
    COMPARISON_APPLIED = "comparison_applied"
    MEASURED_AFTER = "measured_after"
    AWAITING_GATE2 = "awaiting_gate2"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


def require_stable_id(value: str, label: str = "id") -> str:
    value = str(value or "").strip()
    if not STABLE_ID_RE.fullmatch(value):
        raise UsageError(f"{label} must match {STABLE_ID_RE.pattern}")
    return value


def normalize_slug(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")
    if not slug or not SLUG_RE.fullmatch(slug):
        raise ValidationError(f"cannot form a stable slug from {value!r}")
    return slug


def relative_posix(value: str | Path) -> str:
    raw = Path(value).as_posix() if isinstance(value, Path) else str(value).replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or not raw or ".." in path.parts:
        raise ScopeError(f"path must be a contained relative POSIX path: {value}")
    return path.as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical_json(value: Any, *, compact: bool = False) -> str:
    separators = (",", ":") if compact else None
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=None if compact else 2,
        separators=separators,
    ) + ("" if compact else "\n")


def canonical_hash(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


@dataclass(frozen=True)
class GuidanceFile:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        relative_posix(self.path)
        if not SHA256_RE.fullmatch(self.sha256):
            raise ValidationError(f"invalid SHA-256 for guidance path {self.path}")


@dataclass(frozen=True)
class NarrationGuidance:
    rulebook: GuidanceFile | None
    voice_files: Mapping[str, GuidanceFile] = field(default_factory=dict)
    example_files: Mapping[str, tuple[GuidanceFile, ...]] = field(default_factory=dict)
    checker_source: GuidanceFile | None = None
    guidance_sha256: str = ""

    @property
    def authorized_targets(self) -> Mapping[str, tuple[str, ...]]:
        voice = tuple(sorted(item.path for item in self.voice_files.values()))
        examples = tuple(sorted(item.path for values in self.example_files.values() for item in values))
        rulebooks = (self.rulebook.path,) if self.rulebook else ()
        checkers = (self.checker_source.path,) if self.checker_source else ()
        return {"rulebook": rulebooks, "voice": voice, "example": examples, "checker_config": checkers}


@dataclass(frozen=True)
class CampaignScope:
    campaign_root: Path
    campaign_id: str
    session_root: Path
    session_relative: str
    iteration_id: str
    guidance: NarrationGuidance | None = None
    portable_root: Path = field(default_factory=lambda: Path.home() / ".claude" / "narration-wiki")

    @property
    def iteration_root(self) -> Path:
        return self.session_root / "narration_wiki" / self.iteration_id

    @property
    def campaign_wiki_root(self) -> Path:
        return self.campaign_root / "wiki"


@dataclass(frozen=True)
class RecoveryProjection:
    transaction_id: str
    operation: str
    state: str
    next_action: str


@dataclass
class WikiIteration:
    iteration_id: str
    campaign_id: str
    session_relative: str
    corpus_id: str | None = None
    state: str = IterationState.NEW.value
    pattern_counts: dict[str, int] = field(default_factory=lambda: {
        "pending": 0, "accepted": 0, "rejected": 0, "pending_portable_sync": 0
    })
    unresolved_conflict_ids: list[str] = field(default_factory=list)
    active_proposal_id: str | None = None
    recovery: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_stable_id(self.iteration_id, "iteration_id")
        relative_posix(self.session_relative)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class TraceArtifact:
    kind: str
    path: str
    sha256: str
    bytes: int
    narrator: str | None
    layout: str


@dataclass(frozen=True)
class TraceManifest:
    iteration_id: str
    campaign_id: str
    session_relative: str
    layouts: Sequence[str]
    artifacts: Sequence[TraceArtifact]
    missing: Sequence[Mapping[str, str]]
    measurement_corpus: Sequence[str]
    corpus_id: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class BaselineBinding:
    measurement_path: str
    measurement_sha256: str
    corpus_id: str
    guidance_sha256: str
    profile: str = MEASUREMENT_PROFILE


@dataclass(frozen=True)
class MeasurementSnapshot:
    iteration_id: str
    phase: str
    proposal_id: str | None
    corpus_id: str
    guidance: Mapping[str, Any]
    documents: Sequence[Mapping[str, Any]]
    checks: Sequence[Mapping[str, Any]]
    cross_narrator_reuse: Sequence[Mapping[str, Any]]
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class PatternDraft:
    slug: str
    title: str
    problem: str
    root_cause: str
    corrective_strategy: str
    evidence: list[Any] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    proposed_tier: str = "campaign"
    mentions_campaign_identity: bool = False
    status: str = "pending"

    def __post_init__(self) -> None:
        self.slug = normalize_slug(self.slug)
        if not all((self.problem.strip(), self.root_cause.strip(), self.corrective_strategy.strip())):
            raise ValidationError("pattern requires Problem, Root Cause, and Corrective Strategy")
        if self.problem.strip() == self.root_cause.strip():
            raise ValidationError("pattern root cause must be distinct from its problem")


@dataclass(frozen=True)
class SeedConflictDraft:
    conflict_id: str
    campaign_id: str
    rule_key: str
    sources: Sequence[Mapping[str, str]]
    pattern_slugs: Sequence[str]
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class ConflictRuling:
    conflict_id: str
    campaign_id: str
    rule_key: str
    sources: Sequence[Mapping[str, str]]
    resolution: str
    rationale: str
    iteration_id: str
    baseline: BaselineBinding
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class Gate1Ruling:
    subject_id: str
    ruling: str
    tier: str
    named_portable_override: bool
    rationale: str | None
    iteration_id: str
    baseline: BaselineBinding
    conflict_ruling_refs: Sequence[Mapping[str, str]]
    gate: str = "gate1"


@dataclass(frozen=True)
class CanonicalEvidenceBinding:
    source_ref: str
    source_sha256: str
    applies_to_kind: str
    applies_to_key: str


@dataclass
class AtomicProposal:
    proposal_id: str
    iteration_id: str
    pattern_slugs: list[str]
    affected_rule: str
    target_kind: str
    target_path: str
    before_sha256: str
    after_sha256: str
    diff_sha256: str
    proposal_fingerprint: str
    reconsideration: Mapping[str, Any] | None = None
    state: str = ProposalState.STAGED.value
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True)
class ImpactEntry:
    proposal_id: str
    proposal_fingerprint: str
    iteration_id: str
    session_relative: str
    corpus_id: str
    pattern_slugs: Sequence[str]
    affected_rule: str
    target_kind: str
    target_path: str
    before_sha256: str
    after_sha256: str
    diff: str
    before_measurement: Mapping[str, Any]
    after_measurement: Mapping[str, Any]
    ruling: str
    reconsideration: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class CompanionCapabilityManifest:
    source_repository: str
    source_revision: str
    capabilities: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    narration_wiki_contract: int = SCHEMA_VERSION
    guidance_source: str = "campaign-resolved"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CompanionCapabilityManifest":
        required = {
            "schema_version", "source_repository", "source_revision",
            "narration_wiki_contract", "guidance_source", "capabilities",
        }
        if set(value) != required:
            raise ValidationError("capability manifest fields do not match contract version 1")
        capabilities = tuple(value.get("capabilities") or ())
        if (
            value.get("schema_version") != 1
            or value.get("narration_wiki_contract") != 1
            or value.get("guidance_source") != "campaign-resolved"
            or set(capabilities) != {"maintainer", "proposer"}
            or not str(value.get("source_repository", "")).strip()
            or not str(value.get("source_revision", "")).strip()
        ):
            raise ValidationError("incompatible narration-wiki companion capability manifest")
        return cls(
            source_repository=str(value["source_repository"]),
            source_revision=str(value["source_revision"]),
            capabilities=tuple(sorted(capabilities)),
        )


def proposal_fingerprint(
    target_kind: str,
    target_path: str,
    affected_rule: str,
    before_sha256: str,
    after_sha256: str,
) -> str:
    return canonical_hash({
        "affected_rule": affected_rule,
        "after_sha256": after_sha256,
        "before_sha256": before_sha256,
        "target_kind": target_kind,
        "target_path": relative_posix(target_path),
    })
