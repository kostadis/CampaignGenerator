"""Offline candidate import with exact packet/span identity binding."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
import yaml

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, TypeAdapter, ValidationError

from pipelines.summary_native.claims.models import ClaimAnnotation, ClaimPredicate, SourceRole
from pipelines.summary_native.claims.packets import SourcePacket
from pipelines.summary_native.claims.models import SourceSelection
from pipelines.summary_native.claims.selection import _read_private_regular, _write_owner_only
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


class CandidateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    occurrence_id: StrictStr = Field(min_length=1)
    chunk_id: StrictStr = Field(min_length=1)
    start_byte: StrictInt = Field(ge=0)
    end_byte: StrictInt = Field(gt=0)
    original_span: StrictStr = Field(min_length=1)
    subject_id: StrictStr | None = None
    subject_kind: Literal["entity", "thread", "topic", "obligation"] | None = None
    predicate: Literal[
        "actor_assignment", "faction_affiliation", "faction_posture", "identity",
        "certainty", "obligation_status", "obligation_amount", "location", "status",
        "temporal_order",
    ] | None = None
    normalized_value: StrictStr | StrictInt | StrictBool | None = None
    certainty: Literal["certain", "probable", "possible", "unknown"] = "unknown"
    audience: StrictStr = Field(min_length=1)
    effective_from: StrictStr | None = None
    effective_until: StrictStr | None = None


PROPOSALS = TypeAdapter(tuple[CandidateProposal, ...])


def _decode(value: bytes | str | dict[str, Any]) -> tuple[CandidateProposal, ...]:
    try:
        raw = json.loads(value) if isinstance(value, (bytes, str)) else value
        if not isinstance(raw, dict) or set(raw) != {"annotations"}:
            raise ValueError("candidate document must contain only annotations")
        proposals = PROPOSALS.validate_python(raw["annotations"])
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise PromotionError(f"invalid candidate output: {exc}", code="CLAIMS_CANDIDATE_INVALID") from exc
    return proposals


def bind_candidates(
    selection: SourceSelection,
    packet: SourcePacket,
    value: bytes | str | dict[str, Any],
    *,
    origin: Literal["human_candidate", "model_candidate"],
    extraction_identity: dict[str, str] | None = None,
    campaign_dir: Path | None = None,
) -> tuple[ClaimAnnotation, ...]:
    """Bind untrusted proposals to exact selected bytes; never grants approval."""
    if selection.confirmed_digest is None or packet.selection_digest != selection.selection_digest:
        raise PromotionError("candidate input is not bound to the confirmed selection", code="CLAIMS_CANDIDATE_INVALID")
    proposals = _decode(value)
    chunks = {item.chunk_id: item for item in packet.chunks}
    selected = {item.chunk_id: item for item in selection.chunks}
    sources = {item.source_id: item for item in selection.sources}
    annotations: list[ClaimAnnotation] = []
    seen: set[str] = set()
    for proposal in proposals:
        if proposal.occurrence_id in seen:
            raise PromotionError("candidate occurrence ids must be unique", code="CLAIMS_CANDIDATE_INVALID")
        seen.add(proposal.occurrence_id)
        chunk = chunks.get(proposal.chunk_id)
        selected_chunk = selected.get(proposal.chunk_id)
        if chunk is None or selected_chunk is None:
            raise PromotionError("candidate names an unselected chunk", code="CLAIMS_SCOPE_EXPANSION")
        raw = chunk.text.encode("utf-8")
        if proposal.end_byte <= proposal.start_byte or proposal.end_byte > len(raw):
            raise PromotionError("candidate span is outside its selected chunk", code="CLAIMS_EXCERPT_INVALID")
        excerpt = raw[proposal.start_byte:proposal.end_byte]
        try:
            decoded = excerpt.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PromotionError("candidate span splits UTF-8 bytes", code="CLAIMS_EXCERPT_INVALID") from exc
        if decoded != proposal.original_span:
            raise PromotionError("candidate excerpt does not match selected bytes", code="CLAIMS_EXCERPT_INVALID")
        source = sources[chunk.source_id]
        model_fields = extraction_identity or {}
        subject_id, subject_kind, subject_resolved = _resolve_subject(campaign_dir, proposal.subject_id, proposal.subject_kind)
        annotations.append(ClaimAnnotation(
            occurrence_id=proposal.occurrence_id, revision=1,
            source_id=source.source_id, source_path=source.path, source_role=source.role,
            anchor=chunk.locator,
            start_byte=selected_chunk.start_byte + proposal.start_byte,
            end_byte=selected_chunk.start_byte + proposal.end_byte,
            source_sha256=source.sha256, span_sha256=hashlib.sha256(excerpt).hexdigest(),
            context_sha256=chunk.sha256, original_span=decoded,
            subject_id=subject_id, subject_identity_kind=subject_kind,
            subject_identity_resolved=subject_resolved,
            predicate=ClaimPredicate(proposal.predicate) if proposal.predicate else None,
            normalized_value=proposal.normalized_value, certainty=proposal.certainty,
            effective_from=proposal.effective_from, effective_until=proposal.effective_until,
            audience=proposal.audience, authority_record_ids=source.authority_record_ids,
            origin=origin, interpretation_state="candidate",
            extraction_run_id=model_fields.get("extraction_run_id"),
            prompt_digest=model_fields.get("prompt_digest"),
            model_id=model_fields.get("model_id"), input_digest=model_fields.get("input_digest"),
        ))
    return tuple(annotations)


def _resolve_subject(
    campaign_dir: Path | None, value: str | None,
    kind: Literal["entity", "thread", "topic", "obligation"] | None,
) -> tuple[str | None, str | None, bool]:
    if value is None:
        return None, kind, False
    if kind in {"topic", "obligation"}:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value):
            return value, kind, True
        return None, kind, False
    if campaign_dir is None:
        return None, kind, False
    root = Path(campaign_dir).resolve()
    matches: list[tuple[str, str]] = []
    entity_path = root / "docs/entity_registry.yaml"
    if kind in {None, "entity"} and entity_path.is_file():
        raw = yaml.safe_load(_read_private_regular(root, Path("docs/entity_registry.yaml"), code="CLAIMS_CANDIDATE_INVALID")) or {}
        for entry in raw.get("entities", []):
            canonical = entry.get("id") or entry.get("name")
            names = [canonical, entry.get("name"), *(entry.get("aliases") or [])]
            if canonical and any(isinstance(name, str) and name.casefold() == value.casefold() for name in names):
                matches.append((str(canonical), "entity"))
    thread_path = root / "docs/thread_registry.yaml"
    if kind in {None, "thread"} and thread_path.is_file():
        raw = yaml.safe_load(_read_private_regular(root, Path("docs/thread_registry.yaml"), code="CLAIMS_CANDIDATE_INVALID")) or {}
        for entry in raw.get("threads", []):
            canonical = entry.get("id")
            names = [canonical, entry.get("title"), *(entry.get("aliases") or [])]
            if canonical and any(isinstance(name, str) and name.casefold() == value.casefold() for name in names):
                matches.append((str(canonical), "thread"))
    unique = sorted(set(matches))
    return (*unique[0], True) if len(unique) == 1 else (None, kind, False)


def import_candidates(
    campaign_dir: Path,
    selection: SourceSelection,
    packet: SourcePacket,
    value: bytes | str | dict[str, Any],
) -> Path:
    annotations = bind_candidates(selection, packet, value, origin="human_candidate", campaign_dir=campaign_dir)
    identity = canonical_digest({
        "selection_digest": selection.selection_digest,
        "packet_digest": packet.packet_digest,
        "annotations": annotations,
    })
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    path = Path(campaign_dir).resolve() / selection.out_root / range_dir / "state/promotion/claims/imports" / f"{identity}.json"
    payload = canonical_bytes({
        "schema_version": 1, "import_id": identity,
        "selection_digest": selection.selection_digest, "packet_digest": packet.packet_digest,
        "origin": "human_candidate", "approved": False, "annotations": annotations,
    })
    _write_owner_only(
        Path(campaign_dir).resolve(), path, payload,
        conflict_code="CLAIMS_CANDIDATE_CONFLICT",
    )
    return path
