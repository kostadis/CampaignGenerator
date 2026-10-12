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
    # An explicit supersession relation the GM reviews with the mapping; it
    # must name another occurrence bound to the same confirmed selection.
    supersedes_occurrence_id: StrictStr | None = Field(default=None, min_length=1)


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
    known_occurrence_ids: frozenset[str] = frozenset(),
) -> tuple[ClaimAnnotation, ...]:
    """Bind untrusted proposals to exact selected bytes; never grants approval.

    ``known_occurrence_ids`` are occurrences already bound to this selection; a
    proposal's ``supersedes_occurrence_id`` must name one of them or another
    proposal in the same document, never itself.
    """
    if selection.confirmed_digest is None or packet.selection_digest != selection.selection_digest:
        raise PromotionError("candidate input is not bound to the confirmed selection", code="CLAIMS_CANDIDATE_INVALID")
    proposals = _decode(value)
    proposal_ids = {item.occurrence_id for item in proposals}
    for proposal in proposals:
        target = proposal.supersedes_occurrence_id
        if target is not None and (
            target == proposal.occurrence_id or target not in proposal_ids | set(known_occurrence_ids)
        ):
            raise PromotionError(
                f"candidate {proposal.occurrence_id} supersedes an occurrence outside this selection: {target}",
                code="CLAIMS_CANDIDATE_INVALID",
            )
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
            supersedes_occurrence_id=proposal.supersedes_occurrence_id,
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


def _bound_occurrence_ids(campaign_dir: Path, selection: SourceSelection) -> frozenset[str]:
    """Occurrences already bound to this exact selection: imports, runs and active authority."""
    from pipelines.summary_native.claims.check import annotations_from_active_ledger
    from pipelines.summary_native.claims.models import CandidateRun

    root = Path(campaign_dir).resolve()
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    base = Path(selection.out_root) / range_dir / "state/promotion/claims"
    found = {item.occurrence_id for item in annotations_from_active_ledger(root, selection)}
    for path in sorted((root / base).glob("imports/*.json")):
        relative = path.relative_to(root)
        raw = json.loads(_read_private_regular(root, relative, code="CLAIMS_CANDIDATE_INVALID"))
        if isinstance(raw, dict) and raw.get("selection_digest") == selection.selection_digest:
            found.update(str(row.get("occurrence_id")) for row in raw.get("annotations", []) if isinstance(row, dict))
    for run_path in sorted((root / base).glob("runs/*/rev-*/run.json")):
        run = CandidateRun.model_validate_json(
            _read_private_regular(root, run_path.relative_to(root), code="CLAIMS_CANDIDATE_INVALID")
        )
        if run.selection_digest == selection.selection_digest:
            found.update(run.candidate_annotation_ids)
    return frozenset(found)


def import_candidates(
    campaign_dir: Path,
    selection: SourceSelection,
    packet: SourcePacket,
    value: bytes | str | dict[str, Any],
) -> Path:
    declares_supersession = any(item.supersedes_occurrence_id for item in _decode(value))
    annotations = bind_candidates(
        selection, packet, value, origin="human_candidate", campaign_dir=campaign_dir,
        known_occurrence_ids=(
            _bound_occurrence_ids(campaign_dir, selection) if declares_supersession else frozenset()
        ),
    )
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
