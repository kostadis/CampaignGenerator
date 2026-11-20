"""On-disk library state: built? embedder match? (FR-007)."""

from __future__ import annotations

import json
from pathlib import Path

from pipelines.library import EmbedderMismatch, NotBuilt
from pipelines.library.config import LibraryConfig

NOT_BUILT_FIX = (
    "run `library build` (hypostasis setup builds it when no library exists)"
)


def rendered_root(config: LibraryConfig) -> Path:
    return Path(config.work_dir) / "rendered"


def read_stamp(config: LibraryConfig) -> dict | None:
    p = Path(config.work_dir) / "embedder.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def require_built(config: LibraryConfig) -> dict:
    """Return the embedder stamp, or raise NotBuilt."""
    stamp = read_stamp(config)
    if stamp is None or not (rendered_root(config) / "sections.json").is_file():
        raise NotBuilt(f"the library at {config.work_dir} has not been built; {NOT_BUILT_FIX}")
    return stamp


def _current(config: LibraryConfig) -> dict:
    e = config.env
    return {
        "backend": e.get("MEMPALACE_BACKEND"),
        "provider": e.get("MEMPALACE_EMBEDDING_PROVIDER"),
        "model": e.get("MEMPALACE_EMBEDDING_MODEL"),
    }


def embedder_matches(config: LibraryConfig, stamp: dict) -> bool:
    cur = _current(config)
    return all(stamp.get(k) == cur[k] for k in cur)


def require_embedder_match(config: LibraryConfig, stamp: dict) -> None:
    if not embedder_matches(config, stamp):
        cur = _current(config)
        raise EmbedderMismatch(
            f"the library was built with {stamp.get('backend')}/{stamp.get('provider')}/"
            f"{stamp.get('model')} but the current config uses "
            f"{cur['backend']}/{cur['provider']}/{cur['model']}; searching would return "
            "garbage. Restore the embedder in hypostasis.yaml env: or rebuild with "
            "`library build`."
        )
