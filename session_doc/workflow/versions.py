"""Preserve narration bytes and generation evidence before any replacement."""
from pathlib import Path
import uuid

from campaignlib.util import atomic_write_bytes, atomic_write_json
from .storage import digest, now


def version_path(path: Path, sha256: str) -> Path:
    return path.parent / ".versions" / path.name / sha256


def preserve_narration(path: Path, metadata: dict | None = None):
    if not path.exists():
        return None
    raw = path.read_bytes()
    snapshot = version_path(path, digest(raw))
    if not snapshot.exists():
        atomic_write_bytes(snapshot, raw)
    elif snapshot.read_bytes() != raw:
        raise ValueError("historical narration evidence was modified")
    for sidecar in (path.with_suffix(".knobs.json"), path.with_suffix(".generation.json")):
        if sidecar.exists():
            raw_sidecar = sidecar.read_bytes()
            atomic_write_bytes(snapshot.parent / f"{snapshot.name}-{sidecar.suffixes[-2][1:]}-{digest(raw_sidecar)}.json", raw_sidecar)
    if metadata is not None:
        atomic_write_json(snapshot.parent / f"{snapshot.name}-generation-{uuid.uuid4().hex}.json", {"schema_version": 1, "sha256": snapshot.name, "at": now(), **metadata})
    return snapshot


def write_narration(path: Path, text: str, metadata: dict):
    preserve_narration(path)
    raw = text.encode("utf-8")
    snapshot = version_path(path, digest(raw))
    atomic_write_bytes(snapshot, raw)
    atomic_write_json(snapshot.parent / f"{snapshot.name}-generation-{uuid.uuid4().hex}.json", {"schema_version": 1, "sha256": snapshot.name, "at": now(), **metadata})
    atomic_write_bytes(path, raw)


def historical_bytes(path: Path, sha256: str) -> bytes:
    """Resolve an existing hash reference; never substitute a different version."""
    if path.is_file() and digest(path.read_bytes()) == sha256:
        return path.read_bytes()
    snapshot = version_path(path, sha256)
    raw = snapshot.read_bytes()
    if digest(raw) != sha256:
        raise ValueError("historical narration evidence hash mismatch")
    return raw
