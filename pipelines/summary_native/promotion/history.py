"""Immutable activation history and joined publication receipts."""

from __future__ import annotations

import os
import hashlib
from pathlib import Path
from pydantic import TypeAdapter, ValidationError

from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import (
    ActivationRecord, BaselineKind, GenerationManifest, PublicationReceiptCandidate,
    OpaqueId,
)
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


def grounding_dir(campaign_dir: Path) -> Path:
    return Path(campaign_dir).resolve() / "docs/grounding"


def activation_path(campaign_dir: Path, activation_id: str) -> Path:
    try:
        TypeAdapter(OpaqueId).validate_python(activation_id, strict=True)
    except ValidationError as exc:
        raise PromotionError("activation id is invalid", code="PROMOTION_HISTORY_INVALID") from exc
    return grounding_dir(campaign_dir) / "activations" / f"{activation_id}.json"


def receipt_candidate_path(campaign_dir: Path, generation_id: str) -> Path:
    return grounding_dir(campaign_dir) / "generations" / generation_id / "publication-receipt.json"


def _create_immutable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load_activation(campaign_dir: Path, activation_id: str) -> ActivationRecord:
    path = activation_path(campaign_dir, activation_id)
    if path.is_symlink():
        raise PromotionError("activation record is a symlink", code="PROMOTION_HISTORY_INVALID")
    try:
        record = ActivationRecord.model_validate_json(path.read_bytes())
        if record.activation_id != activation_id or path.name != f"{record.activation_id}.json":
            raise ValueError("activation filename and record identity differ")
        return record
    except (OSError, ValueError) as exc:
        raise PromotionError("activation record is missing or invalid", code="PROMOTION_HISTORY_INVALID") from exc


def current_activation(campaign_dir: Path, generation_id: str) -> tuple[ActivationRecord, str]:
    """Return the unique immutable activation for the pinned live generation."""
    directory = grounding_dir(campaign_dir) / "activations"
    matches: list[tuple[ActivationRecord, str]] = []
    if directory.is_dir() and not directory.is_symlink():
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink():
                raise PromotionError("activation history contains a symlink", code="PROMOTION_HISTORY_INVALID")
            try:
                data = path.read_bytes()
                record = ActivationRecord.model_validate_json(data)
            except (OSError, ValueError) as exc:
                raise PromotionError("activation history is invalid", code="PROMOTION_HISTORY_INVALID") from exc
            if record.generation_id == generation_id:
                matches.append((record, hashlib.sha256(data).hexdigest()))
    if len(matches) != 1:
        raise PromotionError(
            "current generation must have exactly one reconciled activation",
            code="PROMOTION_HISTORY_INVALID",
        )
    verify_activation_chain(campaign_dir, matches[0][0].activation_id)
    return matches[0]


def verify_generation_evidence(
    campaign_dir: Path, manifest: GenerationManifest, manifest_bytes: bytes,
    receipt: PublicationReceiptCandidate | None = None,
) -> None:
    root = grounding_dir(campaign_dir)
    if manifest.manifest_sha256 != canonical_digest(manifest, exclude_fields=frozenset({"manifest_sha256"})):
        raise PromotionError("generation manifest digest differs", code="PROMOTION_HISTORY_INVALID")
    generation = root / "generations" / manifest.generation_id
    cursor = root
    for part in ("generations", manifest.generation_id):
        cursor /= part
        if cursor.is_symlink():
            raise PromotionError("generation evidence path contains a symlink", code="PROMOTION_HISTORY_INVALID")
    published = generation / "published"
    expected = {item.path: item for item in manifest.members}
    actual: dict[str, tuple[str, int]] = {}
    if published.is_symlink() or not published.is_dir():
        raise PromotionError("published generation is missing", code="PROMOTION_HISTORY_INVALID")
    for path in sorted(published.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise PromotionError("published generation contains unsafe members", code="PROMOTION_HISTORY_INVALID")
        if path.is_file():
            data = path.read_bytes()
            actual[path.relative_to(published).as_posix()] = (hashlib.sha256(data).hexdigest(), len(data))
    if set(actual) != set(expected) or any(actual[path] != (item.sha256, item.size) for path, item in expected.items()):
        raise PromotionError("published generation members differ from manifest", code="PROMOTION_HISTORY_INVALID")
    for binding in manifest.retained_records:
        retained = generation.joinpath(*Path(binding.retained_path).parts)
        cursor = generation
        for part in Path(binding.retained_path).parts:
            cursor /= part
            if cursor.is_symlink():
                raise PromotionError("retained record path contains a symlink", code="PROMOTION_HISTORY_INVALID")
        if retained.is_symlink() or not retained.is_file() or hashlib.sha256(retained.read_bytes()).hexdigest() != binding.sha256:
            raise PromotionError("retained record metadata differs", code="PROMOTION_HISTORY_INVALID")
    if receipt is not None:
        if (receipt.generation_id != manifest.generation_id
                or receipt.generation_manifest_sha256 != manifest.manifest_sha256
                or receipt.bundle_digest != manifest.bundle_digest):
            raise PromotionError("publication receipt does not bind the generation", code="PROMOTION_HISTORY_INVALID")


def verify_activation_chain(campaign_dir: Path, activation_id: str, _seen: set[str] | None = None) -> ActivationRecord:
    seen = set() if _seen is None else _seen
    if activation_id in seen:
        raise PromotionError("activation history contains a cycle", code="PROMOTION_HISTORY_INVALID")
    seen.add(activation_id)
    activation = load_activation(campaign_dir, activation_id)
    generation = grounding_dir(campaign_dir) / "generations" / activation.generation_id
    try:
        manifest_bytes = (generation / "manifest.json").read_bytes()
        manifest = GenerationManifest.model_validate_json(manifest_bytes)
    except (OSError, ValueError) as exc:
        raise PromotionError("generation manifest is missing or invalid", code="PROMOTION_HISTORY_INVALID") from exc
    if hashlib.sha256(manifest_bytes).hexdigest() != activation.manifest_sha256:
        raise PromotionError("activation manifest digest differs", code="PROMOTION_HISTORY_INVALID")
    receipt = None
    if activation.baseline_kind is BaselineKind.ACTIVATION:
        receipt_path = receipt_candidate_path(campaign_dir, activation.generation_id)
        try:
            receipt_bytes = receipt_path.read_bytes()
            receipt = PublicationReceiptCandidate.model_validate_json(receipt_bytes)
        except (OSError, ValueError) as exc:
            raise PromotionError("publication receipt candidate is invalid", code="PROMOTION_HISTORY_INVALID") from exc
        if (hashlib.sha256(receipt_bytes).hexdigest() != activation.receipt_candidate_sha256
                or receipt.operation_id != activation.operation_id):
            raise PromotionError("activation receipt identity differs", code="PROMOTION_HISTORY_INVALID")
    else:
        receipt_path = grounding_dir(campaign_dir) / "migrations" / activation.operation_id / "receipt.json"
        try:
            value = __import__("json").loads(receipt_path.read_text(encoding="utf-8"))
            claimed = value.pop("receipt_sha256")
        except (OSError, ValueError, KeyError) as exc:
            raise PromotionError("migration receipt is missing or invalid", code="PROMOTION_HISTORY_INVALID") from exc
        if claimed != activation.migration_receipt_sha256 or canonical_digest(value) != claimed:
            raise PromotionError("migration receipt identity differs", code="PROMOTION_HISTORY_INVALID")
    verify_generation_evidence(campaign_dir, manifest, manifest_bytes, receipt)
    if activation.parent_activation_id is not None:
        parent_path = activation_path(campaign_dir, activation.parent_activation_id)
        try:
            parent_bytes = parent_path.read_bytes()
        except OSError as exc:
            raise PromotionError("parent activation is missing", code="PROMOTION_HISTORY_INVALID") from exc
        if hashlib.sha256(parent_bytes).hexdigest() != activation.parent_activation_sha256:
            raise PromotionError("parent activation digest differs", code="PROMOTION_HISTORY_INVALID")
        verify_activation_chain(campaign_dir, activation.parent_activation_id, seen)
    return activation


def write_activation(campaign_dir: Path, record: ActivationRecord) -> Path:
    path = activation_path(campaign_dir, record.activation_id)
    data = canonical_bytes(record)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != data:
            raise PromotionError("activation id conflicts with immutable history", code="PROMOTION_HISTORY_CONFLICT")
        return path
    if record.parent_activation_id is not None:
        parent_path = activation_path(campaign_dir, record.parent_activation_id)
        try:
            parent_bytes = parent_path.read_bytes()
        except OSError as exc:
            raise PromotionError("parent activation is missing", code="PROMOTION_HISTORY_INVALID") from exc
        import hashlib

        if hashlib.sha256(parent_bytes).hexdigest() != record.parent_activation_sha256:
            raise PromotionError("parent activation digest differs", code="PROMOTION_HISTORY_INVALID")
    _create_immutable(path, data)
    return path


def joined_receipt(campaign_dir: Path, activation_id: str) -> dict:
    activation = verify_activation_chain(campaign_dir, activation_id)
    if activation.receipt_candidate_sha256 is None:
        return {"activation": activation.model_dump(mode="json"), "publication": None}
    path = receipt_candidate_path(campaign_dir, activation.generation_id)
    try:
        candidate = PublicationReceiptCandidate.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise PromotionError("publication receipt candidate is invalid", code="PROMOTION_HISTORY_INVALID") from exc
    import hashlib

    if hashlib.sha256(path.read_bytes()).hexdigest() != activation.receipt_candidate_sha256:
        raise PromotionError("activation receipt digest differs", code="PROMOTION_HISTORY_INVALID")
    return {
        "activation": activation.model_dump(mode="json"),
        "publication": candidate.model_dump(mode="json"),
    }
