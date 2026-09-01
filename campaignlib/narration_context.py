"""Read-only resolution of one campaign's authoritative narration guidance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from session_doc.narration_wiki.models import (
    GuidanceFile,
    NarrationGuidance,
    ScopeError,
    canonical_hash,
    sha256_file,
)


def _configured_path(campaign_root: Path, value: Any, label: str) -> Path | None:
    if value is None or not str(value).strip():
        return None
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = campaign_root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(campaign_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ScopeError(f"configured {label} is missing or outside the campaign: {value}") from exc
    if not resolved.is_file() and label == "rulebook":
        raise ScopeError(f"configured {label} is not a regular file: {value}")
    return resolved


def _guidance_file(campaign_root: Path, path: Path) -> GuidanceFile:
    return GuidanceFile(path=path.relative_to(campaign_root).as_posix(), sha256=sha256_file(path))


def _markdown_files(directory: Path | None) -> list[Path]:
    if directory is None:
        return []
    if not directory.is_dir():
        raise ScopeError(f"configured guidance directory is not a directory: {directory}")
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix.casefold() == ".md"),
        key=lambda item: item.name.casefold(),
    )


def resolve_narration_guidance(
    campaign_root: str | Path,
    *,
    config_path: str | Path | None = None,
    paths: Any | None = None,
    require_rulebook: bool = False,
) -> NarrationGuidance:
    """Resolve only explicitly configured rulebook, voice, and example paths.

    No directory is created and no conventional/legacy location is probed.
    ``paths`` may be an existing EditorPaths/Pydantic model, allowing the
    session-editor service and CLI to share this exact resolver.
    """
    campaign = Path(campaign_root).expanduser().resolve(strict=True)
    if paths is None:
        selected = Path(config_path) if config_path else campaign / "config" / "session_doc.yaml"
        if not selected.is_absolute():
            selected = campaign / selected
        if selected.is_file():
            loaded = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
            paths = loaded.get("paths", {}) if isinstance(loaded, dict) else {}
        else:
            paths = {}
    if hasattr(paths, "model_dump"):
        paths = paths.model_dump(mode="json")
    if not isinstance(paths, dict):
        raise ScopeError("session editor paths configuration must be an object")

    rulebook_path = _configured_path(campaign, paths.get("genre_file"), "rulebook")
    if require_rulebook and rulebook_path is None:
        raise ScopeError("this operation requires configured paths.genre_file")
    voice_dir = _configured_path(campaign, paths.get("voice_dir"), "voice directory")
    examples_dir = _configured_path(campaign, paths.get("examples_dir"), "examples directory")
    voice_files = {
        path.stem: _guidance_file(campaign, path)
        for path in _markdown_files(voice_dir)
        if path.name != "_genre.md"
    }
    example_files: dict[str, tuple[GuidanceFile, ...]] = {}
    for path in _markdown_files(examples_dir):
        narrator = path.stem.split(".", 1)[0]
        example_files.setdefault(narrator, ())
        example_files[narrator] = (*example_files[narrator], _guidance_file(campaign, path))
    rulebook = _guidance_file(campaign, rulebook_path) if rulebook_path else None
    rows = []
    if rulebook:
        rows.append({"kind": "rulebook", "path": rulebook.path, "sha256": rulebook.sha256})
        rows.append({"kind": "checker_config", "path": rulebook.path, "sha256": rulebook.sha256})
    rows.extend({"kind": "voice", "narrator": key, "path": item.path, "sha256": item.sha256}
                for key, item in sorted(voice_files.items()))
    rows.extend({"kind": "example", "narrator": key, "path": item.path, "sha256": item.sha256}
                for key, values in sorted(example_files.items()) for item in values)
    return NarrationGuidance(
        rulebook=rulebook,
        voice_files=voice_files,
        example_files=example_files,
        checker_source=rulebook,
        guidance_sha256=canonical_hash(rows),
    )


__all__ = ["NarrationGuidance", "resolve_narration_guidance"]
