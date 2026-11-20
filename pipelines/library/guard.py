"""Refuse to use a palace path that resolves into a live palace (FR-001)."""

from __future__ import annotations

from pathlib import Path

from pipelines.library import PalaceRefused

WING = "wing_dmsguild"


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def require_library_palace(palace: Path, home: Path | None = None) -> Path:
    home = Path(home) if home is not None else Path.home()
    path = Path(palace).expanduser().resolve()
    for root in ((home / ".mempalace").resolve(), (home / "src" / "campaigns").resolve()):
        if _under(path, root):
            raise PalaceRefused(
                f"library.palace {palace} resolves to {path}, inside live location {root}; "
                "refusing. Set library.palace in ~/.config/hypostasis/hypostasis.yaml to an "
                "isolated path."
            )
    return path
