"""Strict, campaign-local authority ledger primitives.

The ledger is deliberately a separate store from the older correction stores.
It records review decisions and their history; it never overlays an unchanged
summary.  Source changes are handled by :mod:`authority_apply`.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from campaignlib.util import atomic_write_bytes

SCHEMA_VERSION = 1
POLICY_VERSION = 1
_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
DOCUMENT_ANCHOR = "__document__"


class AuthorityError(ValueError):
    """A deliberate refusal with a stable authority error code."""

    def __init__(self, message: str, code: str = "AUTH_VALIDATION"):
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Classification(str, Enum):
    RULED = "RULED"
    CANON = "CANON"
    TABLE = "TABLE"
    PREP = "PREP"
    OVERLAY = "OVERLAY"
    OPEN = "OPEN"


class Projection(str, Enum):
    WORLD_STATE = "world_state"
    CAMPAIGN_STATE = "campaign_state"
    PARTY = "party"
    PLANNING = "planning"


class SubjectRef(StrictModel):
    kind: Literal["entity", "thread", "topic"]
    id: str = Field(min_length=1)


class EffectiveInterval(StrictModel):
    from_chapter: int | None = Field(default=None, ge=0)
    through_chapter: int | None = Field(default=None, ge=0)
    horizon: Literal["future", "open"] | None = None

    @model_validator(mode="after")
    def _valid_interval(self):
        if self.horizon is not None and (self.from_chapter is not None or self.through_chapter is not None):
            raise ValueError("effective horizon cannot be combined with chapter bounds")
        if self.from_chapter is None and self.through_chapter is None and self.horizon is None:
            raise ValueError("effective needs chapter bounds or a horizon")
        if self.from_chapter is not None and self.through_chapter is not None and self.through_chapter < self.from_chapter:
            raise ValueError("effective through_chapter is before from_chapter")
        return self

    def overlaps(self, other: "EffectiveInterval") -> bool:
        if self.horizon or other.horizon:
            return self.horizon == other.horizon
        return not ((self.through_chapter is not None and other.from_chapter is not None and self.through_chapter < other.from_chapter) or (other.through_chapter is not None and self.from_chapter is not None and other.through_chapter < self.from_chapter))


class AudienceGrant(StrictModel):
    grants: frozenset[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _known_grants(self):
        for grant in self.grants:
            if grant not in {"gm", "players", "characters"} and not (grant.startswith("character:") and len(grant) > len("character:")):
                raise ValueError(f"invalid audience grant {grant!r}")
        return self

    def allows(self, target: str) -> bool:
        # GM review sees every declared record; a non-GM target needs its own
        # exact grant.  In particular players never entails characters.
        return target == "gm" or target in self.grants or (target.startswith("character:") and "characters" in self.grants)


class SourceRef(StrictModel):
    path: str = Field(min_length=1)
    resolved_path: str | None = None
    anchor: str = Field(min_length=1)
    before_sha256: str | None = None
    before_span_sha256: str | None = None

    @model_validator(mode="after")
    def _hashes(self):
        for name in ("before_sha256", "before_span_sha256"):
            value = getattr(self, name)
            if value is not None and not _SHA.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
        return self


class BaseRecord(StrictModel):
    id: str
    revision: int = Field(ge=1)
    classification: Classification
    subject: SubjectRef
    claim_key: str | None = None
    normalized_value: str | int | float | bool | None = None
    effective: EffectiveInterval
    audience: AudienceGrant
    projections: frozenset[Projection] = Field(min_length=1)
    recorded_at: datetime
    recorded_by: str = Field(min_length=1)
    supersedes: str | None = None

    @model_validator(mode="after")
    def _identity(self):
        if not _SLUG.fullmatch(self.id):
            raise ValueError("record id must be a stable lowercase slug")
        if (self.claim_key is None) != (self.normalized_value is None):
            raise ValueError("claim_key and normalized_value must appear together")
        return self


class RulingRecord(BaseRecord):
    kind: Literal["ruling"]
    status: Literal["draft", "proposed", "applied", "withdrawal_requested", "reversal_proposed", "withdrawn", "superseded"]
    source: SourceRef
    rejected_claim: str = Field(min_length=1)
    replacement_fact: str = Field(min_length=1)
    proposal_id: str | None = None
    applied_receipt: str | None = None
    withdrawal_reason: str | None = None

    @model_validator(mode="after")
    def _ruling_state(self):
        if self.classification is not Classification.RULED:
            raise ValueError("ruling classification must be RULED")
        if self.source.anchor == DOCUMENT_ANCHOR:
            raise ValueError("__document__ is reserved for read-only support records")
        if self.status != "draft" and not self.proposal_id:
            raise ValueError("ruling status requires proposal_id")
        if self.status in {"applied", "withdrawal_requested", "reversal_proposed", "withdrawn", "superseded"} and not self.applied_receipt:
            raise ValueError("applied ruling state requires applied_receipt")
        if self.status == "withdrawal_requested" and not self.withdrawal_reason:
            raise ValueError("withdrawal_requested requires withdrawal_reason")
        return self


class NoteRecord(BaseRecord):
    kind: Literal["note"]
    status: Literal["active", "superseded", "retired"]
    source: SourceRef
    content_digest: str
    planning_date: str | None = None
    selection_label: str = Field(min_length=1)

    @model_validator(mode="after")
    def _note(self):
        if self.classification is Classification.RULED:
            raise ValueError("note classification cannot be RULED")
        if not _SHA.fullmatch(self.content_digest):
            raise ValueError("content_digest must be a lowercase SHA-256")
        if self.classification in {Classification.PREP, Classification.OVERLAY} and not self.planning_date:
            raise ValueError("PREP and OVERLAY notes require planning_date")
        return self


AuthorityRecord = Annotated[RulingRecord | NoteRecord, Field(discriminator="kind")]


class ConflictFinding(StrictModel):
    id: str
    record_ids: frozenset[str] = Field(min_length=2)
    basis: Literal["structured_value", "source_anchor", "human_identified", "prose_candidate"]
    overlap: EffectiveInterval | None = None
    projections: frozenset[Projection] = Field(min_length=1)
    status: Literal["open", "resolved", "dismissed"] = "open"
    resolution_record: str | None = None
    # A disposition applies to the exact records that were reviewed.  Keeping
    # both revisions and canonical metadata digests prevents a later edit from
    # silently inheriting a resolution for an earlier claim/scope.
    record_revisions: dict[str, int] = Field(default_factory=dict)
    record_digests: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _conflict(self):
        if not _SLUG.fullmatch(self.id):
            raise ValueError("conflict id must be a stable lowercase slug")
        if self.basis in {"structured_value", "source_anchor"} and self.overlap is None:
            raise ValueError("deterministic conflict requires overlap")
        if self.status == "resolved" and not self.resolution_record:
            raise ValueError("resolved conflict requires resolution_record")
        if bool(self.record_revisions) != bool(self.record_digests):
            raise ValueError("conflict record revisions and digests must appear together")
        if self.record_revisions:
            if set(self.record_revisions) != set(self.record_ids) or set(self.record_digests) != set(self.record_ids):
                raise ValueError("conflict bindings must name exactly the compared records")
            if any(revision < 1 for revision in self.record_revisions.values()):
                raise ValueError("conflict record revisions must be positive")
            if any(not _SHA.fullmatch(digest) for digest in self.record_digests.values()):
                raise ValueError("conflict record digests must be lowercase SHA-256")
        return self


class AuthorityLedger(StrictModel):
    version: Literal[SCHEMA_VERSION]
    campaign: str = Field(min_length=1)
    revision: int = Field(ge=1)
    records: list[AuthorityRecord] = Field(default_factory=list)
    conflicts: list[ConflictFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _relations(self):
        ids = [r.id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate authority record id")
        conflict_ids = [c.id for c in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("duplicate conflict id")
        by_id = {r.id: r for r in self.records}
        for record in self.records:
            if record.supersedes:
                prior = by_id.get(record.supersedes)
                if prior is None:
                    raise ValueError(f"{record.id}: supersedes unknown record {record.supersedes}")
                if (
                    prior.subject != record.subject
                    or prior.claim_key != record.claim_key
                    or not prior.effective.overlaps(record.effective)
                    or not (prior.projections & record.projections)
                ):
                    raise ValueError(f"{record.id}: supersedes must name the same overlapping claim")
        for record in self.records:
            seen: set[str] = set()
            cursor = record
            while cursor.supersedes:
                if cursor.id in seen:
                    raise ValueError("supersession cycle")
                seen.add(cursor.id)
                cursor = by_id[cursor.supersedes]
        for conflict in self.conflicts:
            unknown = conflict.record_ids - set(by_id)
            if unknown:
                raise ValueError(f"{conflict.id}: unknown records {sorted(unknown)}")
            if conflict.resolution_record:
                resolution = by_id.get(conflict.resolution_record)
                if not isinstance(resolution, RulingRecord):
                    raise ValueError(f"{conflict.id}: resolution_record must name a ruling record")
        return self


def canonicalize(value):
    """Make all unordered structures stable across PYTHONHASHSEED values.

    Lists preserve their meaningful order (records and history are ordered);
    set-like containers become a deterministically ordered JSON-safe list.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, BaseModel):
        # Do not call model_dump first: Pydantic turns a frozenset into a list
        # there, losing the fact that its iteration order is non-semantic.
        return {
            name: canonicalize(getattr(value, name))
            for name in value.__class__.model_fields
            if getattr(value, name) is not None
        }
    if isinstance(value, dict):
        return {str(key): canonicalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((canonicalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), default=str))
    if isinstance(value, tuple):
        return [canonicalize(item) for item in value]
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def canonical_bytes(value: BaseModel | dict) -> bytes:
    return (json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ledger_path(campaign_dir: Path) -> Path:
    return Path(campaign_dir) / "docs" / "authority.yaml"


class _NoDuplicatesLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise AuthorityError(f"duplicate YAML key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_NoDuplicatesLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_ledger(campaign_dir: Path, *, required: bool = True, expected_campaign: str | None = None) -> AuthorityLedger | None:
    path = ledger_path(campaign_dir)
    if not path.is_file():
        if required:
            raise AuthorityError(f"authority ledger is not initialized; run `summary_native authority init --campaign-dir {campaign_dir}`")
        return None
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_NoDuplicatesLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise AuthorityError(f"invalid authority ledger {path}: {exc}") from exc
    try:
        ledger = AuthorityLedger.model_validate(raw)
    except Exception as exc:
        raise AuthorityError(f"invalid authority ledger {path}: {exc}") from exc
    if expected_campaign and ledger.campaign != expected_campaign:
        raise AuthorityError(f"ledger campaign {ledger.campaign!r} does not match {expected_campaign!r}")
    return ledger


def ledger_digest(campaign_dir: Path) -> str:
    path = ledger_path(campaign_dir)
    if not path.is_file():
        raise AuthorityError("authority ledger is not initialized")
    return sha256_bytes(path.read_bytes())


def write_ledger(campaign_dir: Path, ledger: AuthorityLedger) -> str:
    """Write strict YAML with stable ordering; callers hold the authority writer lock."""
    path = ledger_path(campaign_dir)
    data = ledger_bytes(ledger)
    atomic_write_bytes(path, data)
    return sha256_bytes(data)


def ledger_bytes(ledger: AuthorityLedger) -> bytes:
    return yaml.safe_dump(canonicalize(ledger), sort_keys=False, allow_unicode=True).encode("utf-8")


def new_ledger(campaign: str) -> AuthorityLedger:
    return AuthorityLedger(version=SCHEMA_VERSION, campaign=campaign, revision=1)


def validate_record_identity(campaign_dir: Path, record: AuthorityRecord) -> None:
    """Validate exact subject and named-character identities against disk registries.

    Topics intentionally have no registry requirement.  This function is used
    by input construction and CLI validation, where a missing registry is a
    refusal rather than permission to guess.
    """
    from campaignlib.players_config import load_players_config
    from campaignlib.registry import load_registry as load_entity_registry
    from campaignlib.thread_registry import load_registry as load_thread_registry

    root = Path(campaign_dir)
    if record.subject.kind == "entity":
        path = root / "docs" / "entity_registry.yaml"
        try:
            entity_ids = {entity.name for entity in load_entity_registry(path).entities} if path.is_file() else set()
        except (OSError, ValueError) as exc:
            raise AuthorityError(f"invalid entity identity registry {path}: {exc}") from exc
        if record.subject.id not in entity_ids:
            raise AuthorityError(f"unknown entity identity {record.subject.id!r} in docs/entity_registry.yaml")
    elif record.subject.kind == "thread":
        path = root / "docs" / "thread_registry.yaml"
        try:
            threads = load_thread_registry(path).get("threads", [])
            thread_ids = {thread["id"] for thread in threads if isinstance(thread, dict) and isinstance(thread.get("id"), str)}
        except (OSError, ValueError, TypeError) as exc:
            raise AuthorityError(f"invalid thread identity registry {path}: {exc}") from exc
        if record.subject.id not in thread_ids:
            raise AuthorityError(f"unknown thread identity {record.subject.id!r} in docs/thread_registry.yaml")
    for grant in record.audience.grants:
        if grant.startswith("character:"):
            character_id = grant.removeprefix("character:")
            path = root / "config" / "players.yaml"
            try:
                characters = {character for player in load_players_config(path).players for character in player.plays}
            except (OSError, ValueError) as exc:
                raise AuthorityError(f"invalid character identity registry {path}: {exc}") from exc
            if character_id not in characters:
                raise AuthorityError(f"unknown character identity {character_id!r} in config/players.yaml")


def validate_audience_target(campaign_dir: Path, audience: str) -> None:
    """Validate the requested view, including named-character membership."""
    if audience in {"gm", "players", "characters"}:
        return
    if not audience.startswith("character:") or not audience.removeprefix("character:"):
        raise AuthorityError(f"invalid audience target {audience!r}")
    from campaignlib.players_config import load_players_config
    try:
        players = load_players_config(Path(campaign_dir) / "config" / "players.yaml")
        characters = {character for player in players.players for character in player.plays}
    except (OSError, ValueError) as exc:
        raise AuthorityError("cannot validate requested character audience") from exc
    if audience.removeprefix("character:") not in characters:
        raise AuthorityError("unknown character audience target")


def record_metadata_digest(record: AuthorityRecord) -> str:
    return sha256_bytes(canonical_bytes(record))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _record_bindings(records: dict[str, AuthorityRecord], record_ids: frozenset[str]) -> tuple[dict[str, int], dict[str, str]]:
    """Return stable binding data for the exact compared record revisions."""
    ordered = sorted(record_ids)
    return (
        {identifier: records[identifier].revision for identifier in ordered},
        {identifier: record_metadata_digest(records[identifier]) for identifier in ordered},
    )


def _conflict_id(
    basis: str,
    left: str,
    right: str,
    *,
    record_revisions: dict[str, int],
    record_digests: dict[str, str],
) -> str:
    fingerprint = sha256_bytes(canonical_bytes({
        "record_revisions": record_revisions,
        "record_digests": record_digests,
    }))[:16]
    identifier = f"{basis.replace('_', '-')}-{left}-{right}-{fingerprint}"
    if len(identifier) <= 96:
        return identifier
    # Long, valid record IDs must not collapse two findings to one truncated
    # identifier.  Keep the type visible and add a stable collision suffix.
    return f"{identifier[:79]}-{sha256_bytes(identifier.encode())[:16]}"


def _intersection(left: EffectiveInterval, right: EffectiveInterval) -> EffectiveInterval:
    """Return the precise common bounded interval after ``overlaps`` succeeds."""
    if left.horizon or right.horizon:
        # ``EffectiveInterval.overlaps`` only admits identical horizons.
        return left
    lower_bounds = [bound for bound in (left.from_chapter, right.from_chapter) if bound is not None]
    upper_bounds = [bound for bound in (left.through_chapter, right.through_chapter) if bound is not None]
    return EffectiveInterval(
        from_chapter=max(lower_bounds) if lower_bounds else None,
        through_chapter=min(upper_bounds) if upper_bounds else None,
    )


def _source_identity(record: AuthorityRecord) -> tuple[str, str]:
    """Use the normalized path where a source adapter recorded one."""
    return (record.source.resolved_path or record.source.path, record.source.anchor)


def _incompatible_anchor_claim(left: AuthorityRecord, right: AuthorityRecord) -> bool:
    """Only competing source corrections produce an exact-anchor verdict.

    Several audience-scoped notes may cite the same public section.  That
    shared evidence is not a contradiction.  Deterministic anchor conflicts
    are reserved for two applied source corrections that replace the same
    reviewed claim with different truth.
    """
    if not isinstance(left, RulingRecord) or not isinstance(right, RulingRecord):
        return False
    if left.claim_key and left.claim_key == right.claim_key:
        return left.replacement_fact != right.replacement_fact
    return (
        left.rejected_claim == right.rejected_claim
        and left.replacement_fact != right.replacement_fact
    )


def _detect_automatic_conflicts(ledger: AuthorityLedger) -> list[ConflictFinding]:
    """Find deterministic conflicts without reading timestamps or file ordering."""
    active = [record for record in ledger.records if getattr(record, "status", None) in {"active", "applied"}]
    by_id = {record.id: record for record in ledger.records}
    found: list[ConflictFinding] = []
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if not left.effective.overlaps(right.effective) or not (left.projections & right.projections):
                continue
            if left.supersedes == right.id or right.supersedes == left.id:
                continue
            ids = frozenset({left.id, right.id})
            record_revisions, record_digests = _record_bindings(by_id, ids)
            overlap = _intersection(left.effective, right.effective)
            if (left.subject == right.subject and left.claim_key and left.claim_key == right.claim_key
                    and left.normalized_value != right.normalized_value
                    and _establishes_structured_truth(left) and _establishes_structured_truth(right)):
                found.append(ConflictFinding(
                    id=_conflict_id("structured_value", *sorted(ids), record_revisions=record_revisions, record_digests=record_digests),
                    record_ids=ids, basis="structured_value", overlap=overlap,
                    projections=left.projections & right.projections,
                    record_revisions=record_revisions, record_digests=record_digests,
                ))
            if _source_identity(left) == _source_identity(right) and _incompatible_anchor_claim(left, right):
                found.append(ConflictFinding(
                    id=_conflict_id("source_anchor", *sorted(ids), record_revisions=record_revisions, record_digests=record_digests),
                    record_ids=ids, basis="source_anchor", overlap=overlap,
                    projections=left.projections & right.projections,
                    record_revisions=record_revisions, record_digests=record_digests,
                ))
    return sorted(found, key=lambda item: item.id)


def _establishes_structured_truth(record: AuthorityRecord) -> bool:
    """Limit automatic values to established evidence and applied decisions."""
    return (
        record.classification in {Classification.CANON, Classification.TABLE, Classification.OVERLAY}
        or isinstance(record, RulingRecord)
    )


def detect_conflicts(ledger: AuthorityLedger) -> list[ConflictFinding]:
    """Return current automatic findings plus durable human dispositions.

    A disposition is keyed by a stable finding ID.  Rechecking therefore never
    turns a human-resolved or dismissed conflict back into an open verdict, and
    automatic detection still never assigns a recency winner.
    """
    stored = {conflict.id: conflict for conflict in ledger.conflicts}
    automatic = _detect_automatic_conflicts(ledger)
    automatic_ids = {conflict.id for conflict in automatic}
    retained = [
        conflict for conflict in ledger.conflicts
        # Retain completed deterministic findings for history.  A former open
        # finding is stale after its compared records change and must not block
        # the new comparison.  Human findings remain deliberate GM evidence.
        if conflict.id not in automatic_ids
        and (conflict.status != "open" or conflict.basis in {"human_identified", "prose_candidate"})
    ]
    return sorted(
        [stored.get(conflict.id, conflict) for conflict in automatic] + retained,
        key=lambda item: item.id,
    )


def human_conflict_candidate(identifier: str, record_ids: set[str] | frozenset[str]) -> ConflictFinding:
    """Record human-noted prose tension without assigning it a truth verdict."""
    return ConflictFinding(id=identifier, record_ids=frozenset(record_ids), basis="prose_candidate",
                           projections=frozenset({Projection.WORLD_STATE}))


def record_human_conflict(
    ledger: AuthorityLedger,
    *,
    conflict_id: str,
    record_ids: set[str] | frozenset[str],
    basis: Literal["human_identified", "prose_candidate"] = "human_identified",
    projections: frozenset[Projection] | set[Projection] | None = None,
) -> AuthorityLedger:
    """Append a human finding without attempting semantic contradiction logic.

    The returned ledger is a new immutable Pydantic value.  Callers persist it
    through the authority transaction/event path, retaining the previous ledger
    bytes as conflict history.
    """
    records_by_id = {record.id: record for record in ledger.records}
    requested = frozenset(record_ids)
    if len(requested) < 2:
        raise AuthorityError("a conflict needs at least two records")
    unknown = requested - set(records_by_id)
    if unknown:
        raise AuthorityError(f"unknown conflict records {sorted(unknown)}")
    if conflict_id in {conflict.id for conflict in ledger.conflicts}:
        raise AuthorityError(f"conflict {conflict_id!r} already exists")
    shared = set.intersection(*(set(records_by_id[identifier].projections) for identifier in requested))
    effective_projections = frozenset(projections) if projections is not None else frozenset(shared)
    if not effective_projections:
        raise AuthorityError("human conflict records have no shared affected projection")
    if not effective_projections.issubset(shared):
        raise AuthorityError("human conflict projections must be shared by every record")
    record_revisions, record_digests = _record_bindings(records_by_id, requested)
    finding = ConflictFinding(
        id=conflict_id,
        record_ids=requested,
        basis=basis,
        projections=effective_projections,
        record_revisions=record_revisions,
        record_digests=record_digests,
    )
    return AuthorityLedger(
        version=ledger.version,
        campaign=ledger.campaign,
        revision=ledger.revision + 1,
        records=ledger.records,
        conflicts=[*ledger.conflicts, finding],
    )


def _find_conflict(ledger: AuthorityLedger, conflict_id: str) -> tuple[ConflictFinding, bool]:
    """Find a persisted finding or a current deterministic finding to persist."""
    for index, conflict in enumerate(ledger.conflicts):
        if conflict.id == conflict_id:
            return conflict, True
    for conflict in _detect_automatic_conflicts(ledger):
        if conflict.id == conflict_id:
            return conflict, False
    raise AuthorityError(f"unknown conflict {conflict_id!r}")


def _replace_conflict(
    ledger: AuthorityLedger,
    finding: ConflictFinding,
    *,
    was_persisted: bool,
) -> AuthorityLedger:
    conflicts = (
        [finding if item.id == finding.id else item for item in ledger.conflicts]
        if was_persisted
        else [*ledger.conflicts, finding]
    )
    return AuthorityLedger(
        version=ledger.version,
        campaign=ledger.campaign,
        revision=ledger.revision + 1,
        records=ledger.records,
        conflicts=conflicts,
    )


def resolve_conflict(
    ledger: AuthorityLedger,
    conflict_id: str,
    *,
    resolution_record: str,
    expected_revision: int,
) -> AuthorityLedger:
    """Persist one explicit human resolution against the reviewed ledger revision."""
    if expected_revision != ledger.revision:
        raise AuthorityError("AUTH_STALE: authority ledger changed; review the conflict again", "AUTH_STALE")
    conflict, was_persisted = _find_conflict(ledger, conflict_id)
    if conflict.status != "open":
        raise AuthorityError(f"AUTH_STALE: conflict {conflict_id!r} is already {conflict.status}", "AUTH_STALE")
    resolution = next((record for record in ledger.records if record.id == resolution_record), None)
    if not isinstance(resolution, RulingRecord) or resolution.status != "applied":
        raise AuthorityError(f"unknown resolution record {resolution_record!r}")
    if not (resolution.projections & conflict.projections):
        raise AuthorityError("resolution record does not affect the conflicted projections")
    return _replace_conflict(
        ledger,
        conflict.model_copy(update={"status": "resolved", "resolution_record": resolution_record}),
        was_persisted=was_persisted,
    )


def dismiss_conflict(
    ledger: AuthorityLedger,
    conflict_id: str,
    *,
    expected_revision: int,
) -> AuthorityLedger:
    """Persist the GM's explicit decision that an open finding needs no ruling."""
    if expected_revision != ledger.revision:
        raise AuthorityError("AUTH_STALE: authority ledger changed; review the conflict again", "AUTH_STALE")
    conflict, was_persisted = _find_conflict(ledger, conflict_id)
    if conflict.status != "open":
        raise AuthorityError(f"AUTH_STALE: conflict {conflict_id!r} is already {conflict.status}", "AUTH_STALE")
    return _replace_conflict(
        ledger,
        conflict.model_copy(update={"status": "dismissed"}),
        was_persisted=was_persisted,
    )


def detect_structured_conflicts(records: list[AuthorityRecord]) -> list[tuple[str, str]]:
    """Backward-compatible pair view for older validation callers."""
    ledger = AuthorityLedger(version=1, campaign="memory", revision=1, records=records)
    return [tuple(sorted(conflict.record_ids)) for conflict in detect_conflicts(ledger)
            if conflict.basis == "structured_value"]
