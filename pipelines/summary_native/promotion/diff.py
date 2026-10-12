"""Exact proposed managed-tree differences."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Mapping

from pipelines.summary_native.promotion.errors import PromotionStaleError
from pipelines.summary_native.promotion.models import BundleSelection, ContentIdentity, PathChange


def _sources(bundle: BundleSelection) -> dict[str, ContentIdentity]:
    """Live member path -> the reviewed source identity enumerated in the bundle."""
    result: dict[str, ContentIdentity] = {}
    for document in bundle.documents:
        result[f"{document.document_id.value}.md"] = document
    result["canon_events_timeline.md"] = bundle.timeline
    for reference in bundle.references:
        marker = "/reference/"
        if marker not in reference.path:
            raise ValueError(f"reference is outside reference tree: {reference.path}")
        relative = reference.path.split(marker, 1)[1]
        result[f"reference/{relative}"] = reference
    return result


def reviewed_identities(bundle: BundleSelection) -> dict[str, tuple[str, int]]:
    """Live member path -> the (sha256, size) the reviewer saw and signed."""
    return {path: (item.sha256, item.size) for path, item in _sources(bundle).items()}


def proposed_bytes(campaign_dir: Path, bundle: BundleSelection) -> dict[str, bytes]:
    """Current draft bytes for every member (preview reads; may have drifted)."""
    root = Path(campaign_dir)
    return {path: (root / item.path).read_bytes() for path, item in _sources(bundle).items()}


def reviewed_bytes(campaign_dir: Path, bundle: BundleSelection) -> dict[str, bytes]:
    """Draft bytes, refused unless each is exactly what the bundle enumerated.

    Staging copies these, so a draft saved between preview and staging (even
    one reverted afterwards) can never reach a generation.
    """
    members = proposed_bytes(campaign_dir, bundle)
    expected = reviewed_identities(bundle)
    for path, data in members.items():
        if (hashlib.sha256(data).hexdigest(), len(data)) != expected[path]:
            raise PromotionStaleError(f"{path} changed after the reviewed preview")
    return members


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_diff(before: bytes, after: bytes, path: str) -> str | None:
    try:
        old = before.decode("utf-8").splitlines(keepends=True)
        new = after.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None
    return "".join(difflib.unified_diff(old, new, fromfile=f"live/{path}", tofile=f"candidate/{path}"))


def diff_members(before: Mapping[str, bytes], after: Mapping[str, bytes]) -> tuple[PathChange, ...]:
    changes: list[PathChange] = []
    for path in sorted(set(before) | set(after)):
        old = before.get(path)
        new = after.get(path)
        if old is None:
            kind = "add"
        elif new is None:
            kind = "remove"
        elif old == new:
            kind = "unchanged"
        else:
            kind = "replace"
        rendered = _text_diff(old, new, path) if old is not None and new is not None and old != new else None
        binary = False
        if old is not None and new is not None and old != new:
            try:
                old.decode("utf-8")
                new.decode("utf-8")
            except UnicodeDecodeError:
                binary = True
        changes.append(
            PathChange(
                path=path,
                kind=kind,
                before_sha256=_digest(old) if old is not None else None,
                after_sha256=_digest(new) if new is not None else None,
                before_type="file" if old is not None else "absent",
                after_type="file" if new is not None else "absent",
                unified_diff=rendered,
                binary=binary,
            )
        )
    return tuple(changes)
