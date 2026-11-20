"""MemPalace env wiring from the host's hypostasis.yaml (single authority)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

DEFAULT_PATH = Path("~/.config/hypostasis/hypostasis.yaml")


def hypostasis_env(path: Path = DEFAULT_PATH, environ=os.environ) -> dict:
    """Copy of ``environ`` with every MEMPALACE_* key from the yaml ``env:``
    mapping filled in where not already set."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise RuntimeError(f"hypostasis config not found: {p}")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    env = cfg.get("env") or {}
    if "MEMPALACE_BACKEND" not in env:
        raise RuntimeError(f"{p} has no env.MEMPALACE_BACKEND; refusing to use a default backend")
    out = dict(environ)
    for k, v in env.items():
        if str(k).startswith("MEMPALACE_") and k not in out:
            out[k] = str(v)
    return out
