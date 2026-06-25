"""Read mneme-rendered EXTERNAL wiring (``config/wiring.yaml``).

External config — endpoints, service URLs, the DGX model, shared data roots — names
or reaches things *outside* CampaignGenerator, so it is owned by mneme and rendered
into ``config/wiring.yaml`` (do-not-edit, stamped with a source hash). Internal config
(prompts, agents, documents, log_dir) stays hand-edited in ``config.yaml``.

This module is the single accessor for external values. Scripts that previously
hardcoded an endpoint/URL/data-root read it from here instead.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path


def _candidate_paths(explicit: str | os.PathLike | None) -> list[Path]:
    """Where wiring.yaml might be, most-specific first."""
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    env = os.environ.get("MNEME_WIRING")
    if env:
        paths.append(Path(env))
    # rendered into the repo's config/ (CampaignGenerator runs from its source tree)
    paths.append(Path(__file__).resolve().parents[1] / "config" / "wiring.yaml")
    paths.append(Path.cwd() / "config" / "wiring.yaml")
    return paths


@functools.lru_cache(maxsize=8)
def load_wiring(path: str | os.PathLike | None = None) -> dict:
    """Return the external wiring dict, or {} if no rendered wiring.yaml is found."""
    import yaml

    for p in _candidate_paths(path):
        if p.exists():
            data = yaml.safe_load(p.read_text()) or {}
            return data if isinstance(data, dict) else {}
    return {}


def wiring_get(key: str, default=None):
    """Return one external wiring value (or ``default`` if wiring/key is absent)."""
    return load_wiring().get(key, default)


def wiring_path(key: str) -> Path | None:
    """Return an external wiring value as an expanded ``Path``, or None if absent."""
    val = load_wiring().get(key)
    return Path(val).expanduser() if isinstance(val, str) and val else None
