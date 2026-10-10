"""Exact proposed managed-tree differences."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path
from typing import Mapping

from pipelines.summary_native.promotion.models import BundleSelection, PathChange


def proposed_bytes(campaign_dir: Path, bundle: BundleSelection) -> dict[str, bytes]:
    root = Path(campaign_dir)
    result: dict[str, bytes] = {}
    for document in bundle.documents:
        result[f"{document.document_id.value}.md"] = (root / document.path).read_bytes()
    result["canon_events_timeline.md"] = (root / bundle.timeline.path).read_bytes()
    for reference in bundle.references:
        source = root / reference.path
        marker = "/reference/"
        if marker not in reference.path:
            raise ValueError(f"reference is outside reference tree: {reference.path}")
        relative = reference.path.split(marker, 1)[1]
        result[f"reference/{relative}"] = source.read_bytes()
    return result


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
