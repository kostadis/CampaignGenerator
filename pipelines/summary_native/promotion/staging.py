"""Same-filesystem staging for one immutable grounding generation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pipelines.summary_native.promotion.diff import proposed_bytes
from pipelines.summary_native.promotion.errors import PromotionError, PromotionPathError
from pipelines.summary_native.promotion.gates import check_copied_bundle
from pipelines.summary_native.promotion.models import (
    BundleSelection,
    ContentIdentity,
    GenerationKind,
    GenerationManifest,
    RetainedRecordBinding,
)
from pipelines.summary_native.review.models import canonical_bytes, canonical_digest


_RECORD = re.compile(r"record:\s*([^ |]+)")


def _sync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_tree(directory: Path, members: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    for relative, data in sorted(members.items()):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        _sync_file(path)
    for item in sorted((value for value in directory.rglob("*") if value.is_dir()), reverse=True):
        _sync_dir(item)
    _sync_dir(directory)


def stage_generation(
    campaign_dir: Path,
    bundle: BundleSelection,
    *,
    operation_id: str,
    generation_id: str,
    kind: GenerationKind = GenerationKind.PUBLISHED,
    parent_activation_id: str | None = None,
    created_at: datetime | None = None,
) -> tuple[Path, GenerationManifest]:
    """Copy reviewed bytes twice and validate both copies before activation."""
    root = Path(campaign_dir).resolve()
    grounding = root / "docs/grounding"
    if grounding.is_symlink() or grounding.stat().st_dev != root.stat().st_dev:
        raise PromotionPathError("grounding staging must share the campaign filesystem")
    stage = grounding / ".staging" / operation_id / generation_id
    if stage.exists() or stage.is_symlink():
        raise PromotionError("staging generation already exists", code="PROMOTION_OPERATION_CONFLICT")
    members = proposed_bytes(root, bundle)
    try:
        _write_tree(stage / "published", members)
        _write_tree(stage / "live", members)
        retained_dir = stage / "metadata/records"
        retained_dir.mkdir(parents=True)
        retained: list[RetainedRecordBinding] = []
        records = {item.path: item for item in bundle.retained_records}
        for document in bundle.documents:
            text = (root / document.path).read_text(encoding="utf-8")
            match = _RECORD.search(text)
            if match is None:
                raise PromotionError("draft lost its run-record locator", code="PROMOTION_DEPENDENCY_STALE")
            original = (root / document.path).parent.parent / match.group(1)
            relative_original = original.resolve().relative_to(root).as_posix()
            identity = records.get(relative_original)
            if identity is None or hashlib.sha256(original.read_bytes()).hexdigest() != identity.sha256:
                raise PromotionError("retained run record changed", code="PROMOTION_DEPENDENCY_STALE")
            retained_path = retained_dir / f"{document.document_id.value}.json"
            retained_path.write_bytes(original.read_bytes())
            _sync_file(retained_path)
            retained.append(
                RetainedRecordBinding(
                    document_path=f"{document.document_id.value}.md",
                    embedded_locator=match.group(1),
                    anchor="summary_native-draft-header",
                    original_base=Path(document.path).parent.parent.as_posix(),
                    retained_path=retained_path.relative_to(stage).as_posix(),
                    sha256=identity.sha256,
                )
            )
        _sync_dir(retained_dir)
        for output in (stage / "published", stage / "live"):
            gate = check_copied_bundle(root, bundle, output)[0]
            if gate.state != "passed":
                raise PromotionError(gate.message, code=gate.code or "PROMOTION_COPIED_BUNDLE_INVALID")
        output_members = tuple(
            ContentIdentity(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
            for path, data in sorted(members.items())
        )
        values = dict(
            generation_id=generation_id,
            operation_id=operation_id,
            campaign_id=bundle.campaign_id,
            selected_range=bundle.selected_range,
            kind=kind,
            members=output_members,
            retained_records=tuple(retained),
            external_dependencies=bundle.dependencies,
            published_path=f"docs/grounding/generations/{generation_id}/published",
            live_path=f"docs/grounding/generations/{generation_id}/live",
            bundle_digest=bundle.digest,
            analysis_digest=None,
            parent_activation_id=parent_activation_id,
            created_at=created_at or datetime.now(timezone.utc),
            manifest_sha256="0" * 64,
        )
        provisional = GenerationManifest.model_validate(values)
        values["manifest_sha256"] = canonical_digest(
            provisional, exclude_fields=frozenset({"manifest_sha256"})
        )
        manifest = GenerationManifest.model_validate(values)
        manifest_path = stage / "manifest.json"
        manifest_path.write_bytes(canonical_bytes(manifest))
        _sync_file(manifest_path)
        _sync_dir(stage)
        return stage, manifest
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
