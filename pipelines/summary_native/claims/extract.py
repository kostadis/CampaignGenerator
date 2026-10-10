"""Explicit, bounded candidate extraction; the only claims module with a model seam."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import TypeAdapter

from pipelines.summary_native.claims.imports import bind_candidates
from pipelines.summary_native.claims.models import CandidateRun, ClaimAnnotation, ChunkOutcome, SourceSelection
from pipelines.summary_native.claims.packets import SourcePacket
from pipelines.summary_native.claims.selection import _write_owner_only
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


ANNOTATIONS = TypeAdapter(tuple[ClaimAnnotation, ...])
PROMPT_TEMPLATE = (
    "Propose claim interpretations only from the selected packet chunk below. "
    "Return strict JSON with exactly one key, annotations. Byte offsets are relative "
    "to this chunk. Empty annotations is allowed and proves no semantic completeness.\n\n"
    "RULES DIGEST INPUT:\n{rules}\n\n"
    "CHUNK ID: {chunk_id}\nSOURCE: {path}\nLOCATOR: {locator}\nTEXT:\n{text}"
)


@dataclass(frozen=True)
class ExtractionResult:
    run: CandidateRun
    annotations: tuple[ClaimAnnotation, ...]
    path: Path
    cached: bool


def campaign_model_invoker(args, *, system: str, max_tokens: int = 4096):
    """Create the existing campaignlib model seam lazily and only for extract."""
    from campaignlib import client_from_args, stream_api

    client = client_from_args(args)

    def invoke(prompt: str, _chunk) -> str:
        return stream_api(
            client, system, prompt, args.model, max_tokens=max_tokens,
            silent=True, verbose=getattr(args, "verbose", False),
        )

    return invoke


def _prompt(chunk, *, rules: str) -> str:
    return PROMPT_TEMPLATE.format(
        rules=rules, chunk_id=chunk.chunk_id, path=chunk.path,
        locator=chunk.locator, text=chunk.text,
    )


def _load_cached(
    path: Path, *, expected_run_id: str, expected_revision: int,
    selection: SourceSelection, packet: SourcePacket, backend: str, model: str,
    prompt_digest: str, rule_digest: str, input_digest: str,
    selected_chunk_ids: tuple[str, ...],
) -> ExtractionResult:
    try:
        if path.is_symlink() or not path.is_dir():
            raise ValueError("revision is not a real directory")
        run = CandidateRun.model_validate_json((path / "run.json").read_bytes())
        annotations = ANNOTATIONS.validate_json((path / "annotations.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise PromotionError(f"cached extraction revision is malformed: {exc}", code="CLAIMS_EXTRACT_CACHE_INVALID") from exc
    expected = (
        run.run_id == expected_run_id and run.revision == expected_revision
        and run.selection_digest == selection.selection_digest
        and run.packet_digest == packet.packet_digest and run.backend == backend
        and run.model == model and run.prompt_digest == prompt_digest
        and run.rule_digest == rule_digest and run.chunk_ids == selected_chunk_ids
        and tuple(item.chunk_id for item in run.outcomes) == selected_chunk_ids
        and run.candidate_annotation_ids == tuple(item.occurrence_id for item in annotations)
    )
    if not expected:
        raise PromotionError("cached extraction identity does not match request", code="CLAIMS_EXTRACT_CACHE_INVALID")
    by_id = {item.occurrence_id: item for item in annotations}
    if len(by_id) != len(annotations):
        raise PromotionError("cached extraction has duplicate candidate ids", code="CLAIMS_EXTRACT_CACHE_INVALID")
    outcome_ids = tuple(candidate for outcome in run.outcomes for candidate in outcome.candidate_ids)
    if outcome_ids != run.candidate_annotation_ids:
        raise PromotionError("cached extraction outcomes do not bind annotations", code="CLAIMS_EXTRACT_CACHE_INVALID")
    for annotation in annotations:
        owning = [outcome.chunk_id for outcome in run.outcomes if annotation.occurrence_id in outcome.candidate_ids]
        if len(owning) != 1:
            raise PromotionError("cached annotation is not bound to one chunk", code="CLAIMS_EXTRACT_CACHE_INVALID")
        chunk = next(item for item in packet.chunks if item.chunk_id == owning[0])
        selected = next(item for item in selection.chunks if item.chunk_id == owning[0])
        source = next(item for item in selection.sources if item.source_id == chunk.source_id)
        relative_start = annotation.start_byte - selected.start_byte
        relative_end = annotation.end_byte - selected.start_byte
        raw = chunk.text.encode("utf-8")
        try:
            exact_span = raw[relative_start:relative_end].decode("utf-8")
        except (UnicodeDecodeError, IndexError):
            exact_span = ""
        if (
            annotation.extraction_run_id != expected_run_id
            or annotation.prompt_digest != prompt_digest
            or annotation.model_id != f"{backend}:{model}"
            or annotation.input_digest != input_digest
            or annotation.source_id != source.source_id
            or annotation.source_path != source.path
            or annotation.source_sha256 != source.sha256
            or annotation.context_sha256 != chunk.sha256
            or relative_start < 0 or relative_end > len(raw) or relative_end <= relative_start
            or exact_span != annotation.original_span
        ):
            raise PromotionError("cached annotation extraction identity is stale", code="CLAIMS_EXTRACT_CACHE_INVALID")
    complete = all(item.outcome == "completed" for item in run.outcomes)
    completion_is_coherent = (
        run.completed_at is not None and run.failure_detail is None
        if complete
        else run.completed_at is None and run.failure_detail is not None
    )
    if not completion_is_coherent:
        raise PromotionError("cached extraction completion state is inconsistent", code="CLAIMS_EXTRACT_CACHE_INVALID")
    return ExtractionResult(run, annotations, path, True)


def extract_candidates(
    campaign_dir: Path,
    selection: SourceSelection,
    packet: SourcePacket,
    *,
    selected_chunk_ids: tuple[str, ...],
    backend: str,
    model: str,
    prompt_version: str,
    rules: str,
    invoke: Callable[[str, object], str],
    system_prompt: str = "claims candidate extraction",
    output_schema: str = "claims-candidate-v1",
    max_tokens: int = 4096,
    chunk_chars: int = 16000,
    settings: dict[str, object] | None = None,
    force: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> ExtractionResult:
    """Extract independent candidates from exactly the explicitly named chunks."""
    if selection.confirmed_digest is None or packet.selection_digest != selection.selection_digest:
        raise PromotionError("extraction requires a packet for the confirmed selection", code="CLAIMS_EXTRACT_INVALID")
    if not selected_chunk_ids or len(set(selected_chunk_ids)) != len(selected_chunk_ids):
        raise PromotionError("extraction requires unique explicit selected chunks", code="CLAIMS_SCOPE_REQUIRED")
    by_id = {chunk.chunk_id: chunk for chunk in packet.chunks}
    unknown = [chunk_id for chunk_id in selected_chunk_ids if chunk_id not in by_id]
    if unknown:
        raise PromotionError(f"unselected extraction chunks: {', '.join(unknown)}", code="CLAIMS_SCOPE_EXPANSION")
    if max_tokens <= 0 or chunk_chars <= 0:
        raise PromotionError("token and chunk bounds must be positive", code="CLAIMS_EXTRACT_INVALID")
    oversized = [chunk_id for chunk_id in selected_chunk_ids if len(by_id[chunk_id].text) > chunk_chars]
    if oversized:
        raise PromotionError(
            "selected packet chunks exceed configured chunk bound: " + ", ".join(oversized),
            code="CLAIMS_CHUNK_TOO_LARGE",
        )
    extraction_settings = dict(settings or {})
    prompt_digest = canonical_digest({
        "prompt_version": prompt_version, "prompt_template": PROMPT_TEMPLATE,
        "system_prompt": system_prompt, "output_schema": output_schema,
    })
    rule_digest = canonical_digest({"rules": rules})
    input_digest = canonical_digest({
        "selection_digest": selection.selection_digest, "packet_digest": packet.packet_digest,
        "backend": backend, "model": model, "prompt_digest": prompt_digest,
        "rule_digest": rule_digest, "chunk_ids": selected_chunk_ids,
        "max_tokens": max_tokens, "chunk_chars": chunk_chars,
        "settings": extraction_settings,
    })
    run_id = f"extract-{input_digest[:24]}"
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    root = Path(campaign_dir).resolve() / selection.out_root / range_dir / "state/promotion/claims/runs" / run_id
    revisions: list[tuple[int, Path]] = []
    if root.is_dir():
        for candidate in root.iterdir():
            match = re.fullmatch(r"rev-(\d{4})", candidate.name)
            if match is None:
                raise PromotionError("unexpected cached extraction entry", code="CLAIMS_EXTRACT_CACHE_INVALID")
            revisions.append((int(match.group(1)), candidate))
        revisions.sort()
        if [number for number, _path in revisions] != list(range(1, len(revisions) + 1)):
            raise PromotionError("cached extraction revisions are not contiguous", code="CLAIMS_EXTRACT_CACHE_INVALID")
    if revisions and not force:
        number, latest = revisions[-1]
        return _load_cached(
            latest, expected_run_id=run_id, expected_revision=number,
            selection=selection, packet=packet, backend=backend, model=model,
            prompt_digest=prompt_digest, rule_digest=rule_digest,
            input_digest=input_digest, selected_chunk_ids=selected_chunk_ids,
        )
    revision = len(revisions) + 1
    created = now()
    if created.tzinfo is None:
        raise PromotionError("extraction clock must be timezone-aware", code="CLAIMS_EXTRACT_INVALID")
    outcomes: list[ChunkOutcome] = []
    annotations: list[ClaimAnnotation] = []
    for chunk_id in selected_chunk_ids:
        chunk = by_id[chunk_id]
        prompt = _prompt(chunk, rules=rules)
        try:
            response = invoke(prompt, chunk)
        except Exception as exc:  # provider failure is retained as a chunk outcome
            outcomes.append(ChunkOutcome(chunk_id=chunk_id, outcome="failed", detail=str(exc)))
            continue
        try:
            bound = bind_candidates(
                selection, packet, response, origin="model_candidate",
                extraction_identity={
                    "extraction_run_id": run_id, "prompt_digest": prompt_digest,
                    "model_id": f"{backend}:{model}", "input_digest": input_digest,
                },
                campaign_dir=campaign_dir,
            )
            # A response may only describe the chunk that was sent.
            if any(item.source_id != chunk.source_id or not (
                next(s.start_byte for s in selection.chunks if s.chunk_id == chunk_id)
                <= item.start_byte < item.end_byte
                <= next(s.end_byte for s in selection.chunks if s.chunk_id == chunk_id)
            ) for item in bound):
                raise PromotionError("response expanded beyond its selected chunk", code="CLAIMS_SCOPE_EXPANSION")
            annotations.extend(bound)
            outcomes.append(ChunkOutcome(
                chunk_id=chunk_id, outcome="completed",
                candidate_ids=tuple(item.occurrence_id for item in bound),
            ))
        except (PromotionError, ValueError) as exc:
            outcomes.append(ChunkOutcome(chunk_id=chunk_id, outcome="invalid_output", detail=str(exc)))
    duplicate_ids = {
        item.occurrence_id for item in annotations
        if sum(other.occurrence_id == item.occurrence_id for other in annotations) > 1
    }
    if duplicate_ids:
        outcomes = [
            ChunkOutcome(
                chunk_id=item.chunk_id, outcome="invalid_output",
                candidate_ids=item.candidate_ids,
                detail="candidate occurrence ids collide across chunks: " + ", ".join(sorted(duplicate_ids)),
            ) if duplicate_ids.intersection(item.candidate_ids) else item
            for item in outcomes
        ]
    complete = all(item.outcome == "completed" for item in outcomes)
    finished = now()
    run = CandidateRun(
        run_id=run_id, revision=revision, selection_digest=selection.selection_digest,
        packet_digest=packet.packet_digest, backend=backend, model=model,
        prompt_digest=prompt_digest, rule_digest=rule_digest, chunk_ids=selected_chunk_ids,
        outcomes=tuple(outcomes), candidate_annotation_ids=tuple(item.occurrence_id for item in annotations),
        created_at=created, completed_at=finished if complete else None,
        failure_detail=None if complete else "one or more selected chunks failed validation or extraction",
    )
    destination = root / f"rev-{revision:04d}"
    campaign_root = Path(campaign_dir).resolve()
    _write_owner_only(
        campaign_root, destination / "run.json", canonical_bytes(run),
        conflict_code="CLAIMS_EXTRACT_CONFLICT",
    )
    _write_owner_only(
        campaign_root, destination / "annotations.json", canonical_bytes(annotations),
        conflict_code="CLAIMS_EXTRACT_CONFLICT",
    )
    return ExtractionResult(run, tuple(annotations), destination, False)
