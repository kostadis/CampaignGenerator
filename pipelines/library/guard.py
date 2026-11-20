"""Refuse to run mine/query against anything but the pilot palace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

ENV_VAR = "MEMPALACE_PALACE_PATH"
WING = "wing_dmsguild"


class PalaceGuardError(RuntimeError):
    pass


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def require_pilot_palace(env: Mapping[str, str] = os.environ, home: Path | None = None) -> Path:
    home = Path(home) if home is not None else Path.home()
    raw = env.get(ENV_VAR, "")
    if not raw.strip():
        raise PalaceGuardError(
            f"{ENV_VAR} is not set; refusing to run. Set it to the pilot palace "
            f"(e.g. {home}/rpglib-palace/palace)."
        )
    path = Path(raw).expanduser().resolve()
    live_roots = [(home / ".mempalace").resolve(), (home / "src" / "campaigns").resolve()]
    for root in live_roots:
        if _under(path, root):
            raise PalaceGuardError(
                f"{ENV_VAR}={raw} resolves to {path}, inside live location {root}; refusing."
            )
    return path


def mine_command(render_root: Path, palace: Path) -> list[str]:
    # --direct: the shared daemon could be serving a live palace.
    return ["mempalace", "mine", str(render_root), "--direct", "--wing", WING]
