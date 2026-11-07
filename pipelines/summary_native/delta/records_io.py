"""Tiny atomic JSON record helpers shared by the US2 record modules (census, associations, attest)."""

from __future__ import annotations

import json
from pathlib import Path

from campaignlib.util import atomic_write_text


def write_json(path: Path | str, record: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def read_json(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
