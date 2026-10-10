"""Deterministic packet assembly with no model dependency."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from pipelines.summary_native.claims.models import AuthorityClass, SourceSelection
from pipelines.summary_native.claims.selection import _read_private_regular, _write_owner_only
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import OpaqueId, RelativePath, Sha256, StrictPromotionModel
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


class PacketChunk(StrictPromotionModel):
    chunk_id: OpaqueId
    source_id: OpaqueId
    path: RelativePath
    locator: str
    source_audience: str
    authority_class: AuthorityClass
    applicability: str
    target_audience: str
    effective_horizon: str
    text: str
    sha256: Sha256


class SourcePacket(StrictPromotionModel):
    schema_version: int = Field(default=1, frozen=True)
    selection_digest: Sha256
    chunks: tuple[PacketChunk, ...]
    incomplete_inputs: tuple[str, ...] = ()
    packet_digest: Sha256


def assemble_packet(campaign_dir: Path, selection: SourceSelection) -> SourcePacket:
    if selection.confirmed_digest is None:
        raise PromotionError("packet requires a confirmed selection", code="CLAIMS_SELECTION_UNCONFIRMED")
    root = Path(campaign_dir).resolve()
    by_id = {item.source_id: item for item in selection.sources}
    chunks: list[PacketChunk] = []
    incomplete: list[str] = []
    for selected in selection.chunks:
        source = by_id[selected.source_id]
        path = root / source.path
        try:
            data = _read_private_regular(root, Path(source.path), code="CLAIMS_PACKET_INVALID")
        except PromotionError as exc:
            if exc.code == "CLAIMS_PATH_INVALID": raise
            incomplete.append(selected.chunk_id)
            continue
        except OSError:
            incomplete.append(selected.chunk_id)
            continue
        if hashlib.sha256(data).hexdigest() != source.sha256 or selected.end_byte > len(data):
            incomplete.append(selected.chunk_id)
            continue
        excerpt = data[selected.start_byte:selected.end_byte]
        if hashlib.sha256(excerpt).hexdigest() != selected.sha256:
            incomplete.append(selected.chunk_id)
            continue
        try:
            text = excerpt.decode("utf-8")
        except UnicodeDecodeError:
            incomplete.append(selected.chunk_id)
            continue
        chunks.append(PacketChunk(
            chunk_id=selected.chunk_id, source_id=source.source_id, path=source.path,
            locator=selected.locator, source_audience=source.source_audience,
            authority_class=source.authority_class, applicability=source.applicability,
            target_audience=selection.audience,
            effective_horizon=selection.effective_horizon, text=text, sha256=selected.sha256,
        ))
    values = dict(selection_digest=selection.selection_digest, chunks=tuple(chunks),
                  incomplete_inputs=tuple(incomplete), packet_digest="0" * 64)
    provisional = SourcePacket.model_construct(**values)
    values["packet_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"packet_digest"}))
    return SourcePacket.model_validate(values)


def save_packet(campaign_dir: Path, selection: SourceSelection, packet: SourcePacket) -> Path:
    if packet.selection_digest != selection.selection_digest:
        raise PromotionError("packet belongs to another selection", code="CLAIMS_PACKET_INVALID")
    range_dir = f"ch{selection.range_since:03d}-{selection.range_until:03d}"
    path = (
        Path(campaign_dir).resolve() / selection.out_root / range_dir
        / "state/promotion/claims/packets" / f"{packet.packet_digest}.json"
    )
    data = canonical_bytes(packet)
    _write_owner_only(Path(campaign_dir).resolve(), path, data, conflict_code="CLAIMS_PACKET_CONFLICT")
    return path
