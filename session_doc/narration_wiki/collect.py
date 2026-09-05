"""Fixed-depth, allowlisted collection of immutable session evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import (
    CampaignScope,
    StateError,
    TraceArtifact,
    TraceManifest,
    ValidationError,
    canonical_hash,
    sha256_bytes,
)
from .paths import contained_path
from .storage import save_iteration, write_json
from .models import WikiIteration


EXPECTED_KINDS = (
    "critique",
    "narration",
    "scene_extraction",
    "gm_assist",
    "source_record",
    "scrub_manifest",
    "generation_settings",
)
TEXT_SUFFIXES = {".md", ".txt"}
DATA_SUFFIXES = {".json", ".yaml", ".yml"}


def _layout_and_kind(relative: Path) -> tuple[str, str] | None:
    lowered = relative.as_posix().casefold()
    name = relative.name.casefold()
    parts = tuple(part.casefold() for part in relative.parts)
    if "narration_wiki" in parts:
        return None
    if "scene_extractions_smoothed" in parts:
        return "extractions-smoothed", "narration" if relative.suffix.casefold() == ".md" else "scene_extraction"
    if "scene_extractions_new" in parts:
        return "extractions-new", "narration" if relative.suffix.casefold() == ".md" else "scene_extraction"
    if "scene_extractions" in parts:
        return "extractions", "narration" if relative.suffix.casefold() == ".md" else "scene_extraction"
    if any(part in {"gm_assist", "gm-assist"} for part in parts):
        return "gm-assist", "gm_assist"
    if any(part in {"gm_assistant", "gm-assistant"} for part in parts):
        return "gm-assistant", "gm_assist"
    if name.startswith("gm_assist") or name.startswith("gm-assist"):
        return "gm-assist-doc", "gm_assist"
    if "critique" in parts[:-1]:
        return "critique-directory", "critique"
    if name.startswith("critique"):
        return "critique-flat", "critique"
    if "scrub" in name and "manifest" in name:
        return "current-configured", "scrub_manifest"
    if "generation" in name and ("setting" in name or "config" in name):
        return "current-configured", "generation_settings"
    if "source" in name and relative.suffix.casefold() in DATA_SUFFIXES:
        return "current-configured", "source_record"
    if "narration" in parts or name.startswith("narration"):
        return "current-configured", "narration"
    return None


def _narrator(relative: Path, kind: str) -> str | None:
    if kind != "narration":
        return None
    stem = relative.stem
    for prefix in ("narration-", "narration_", "scene-", "scene_"):
        if stem.casefold().startswith(prefix):
            stem = stem[len(prefix):]
    parent = relative.parent.name
    if parent.casefold() not in {
        "narration", "scene_extractions", "scene_extractions_new", "scene_extractions_smoothed", "."
    }:
        return parent
    return stem or None


def _candidates(session_root: Path) -> Iterable[Path]:
    # Exactly three directory levels below the selected session are admitted.
    for path in sorted(session_root.rglob("*"), key=lambda item: item.relative_to(session_root).as_posix()):
        relative = path.relative_to(session_root)
        if len(relative.parts) > 4 or not path.is_file():
            continue
        if path.suffix.casefold() not in TEXT_SUFFIXES | DATA_SUFFIXES:
            continue
        yield path


def build_manifest(scope: CampaignScope) -> TraceManifest:
    artifacts: list[TraceArtifact] = []
    layouts: set[str] = set()
    for candidate in _candidates(scope.session_root):
        relative = candidate.relative_to(scope.session_root)
        classified = _layout_and_kind(relative)
        if classified is None:
            continue
        # Resolving the source protects against file and directory links that
        # escape the explicitly selected session.
        contained_path(scope.session_root, relative)
        layout, kind = classified
        raw = candidate.read_bytes()
        # The manifest's top-level layout summary enumerates historical
        # generations; `current-configured` remains an artifact-level label.
        if layout != "current-configured":
            layouts.add(layout)
        artifacts.append(TraceArtifact(
            kind=kind,
            path=relative.as_posix(),
            sha256=sha256_bytes(raw),
            bytes=len(raw),
            narrator=_narrator(relative, kind),
            layout=layout,
        ))
    artifacts.sort(key=lambda row: (row.path, row.kind, row.narrator or ""))
    present = {row.kind for row in artifacts}
    missing = [
        {"kind": kind, "pattern": kind, "reason": "no allowlisted artifact found"}
        for kind in EXPECTED_KINDS if kind not in present
    ]
    corpus_rows = [
        {"path": row.path, "sha256": row.sha256, "narrator": row.narrator}
        for row in artifacts if row.kind == "narration"
    ]
    corpus = [row["path"] for row in corpus_rows]
    return TraceManifest(
        iteration_id=scope.iteration_id,
        campaign_id=scope.campaign_id,
        session_relative=scope.session_relative,
        layouts=sorted(layouts),
        artifacts=artifacts,
        missing=missing,
        measurement_corpus=corpus,
        corpus_id=canonical_hash(corpus_rows),
    )


def collect(scope: CampaignScope) -> dict[str, object]:
    if scope.iteration_root.exists():
        raise StateError(f"iteration {scope.iteration_id} already exists")
    manifest = build_manifest(scope)
    from session_doc.workflow.versions import preserve_narration
    for artifact in manifest.artifacts:
        if artifact.kind == "narration":
            preserve_narration(scope.session_root / artifact.path)
    if not manifest.artifacts:
        raise ValidationError("selected session contains no allowlisted narration evidence")
    write_json(scope.iteration_root / "trace-manifest.json", manifest.to_dict())
    iteration = WikiIteration(
        iteration_id=scope.iteration_id,
        campaign_id=scope.campaign_id,
        session_relative=scope.session_relative,
        corpus_id=manifest.corpus_id,
        state="collected",
    )
    save_iteration(scope, iteration)
    kinds: dict[str, int] = {}
    for artifact in manifest.artifacts:
        kinds[artifact.kind] = kinds.get(artifact.kind, 0) + 1
    path = scope.iteration_root / "trace-manifest.json"
    return {
        "manifest": path.relative_to(scope.session_root).as_posix(),
        "manifest_sha256": sha256_bytes(path.read_bytes()),
        "corpus_id": manifest.corpus_id,
        "present_counts": dict(sorted(kinds.items())),
        "missing": list(manifest.missing),
    }
