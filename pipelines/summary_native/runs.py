"""The one place a stage creates its run directory.

Every summary_native stage records a run under ``<state>/runs/<stamp>``. The
stamp is second-resolution, so two runs starting in the same second must not
share a directory (the second would overwrite the first's record and prompts).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

RUN_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def run_stamp(started: datetime) -> str:
    return started.strftime(RUN_STAMP_FORMAT)


def new_run_dir(runs_root: Path, stamp: str) -> Path:
    """Create ``runs_root/<stamp>[-k]`` atomically — a directory no earlier run owns.

    The caller records ``run_dir.name`` as its ``run_id``, never ``stamp``.
    """
    runs_root.mkdir(parents=True, exist_ok=True)
    k = 0
    while True:
        d = runs_root / (stamp if k == 0 else f"{stamp}-{k}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            k += 1
