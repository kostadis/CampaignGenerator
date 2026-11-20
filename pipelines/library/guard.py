"""Refuse to use a palace path that resolves into a live palace (FR-001)."""

from __future__ import annotations

from pathlib import Path

from pipelines.library import PalaceRefused

WING = "wing_dmsguild"


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _refuse_live(value, label: str, home: Path | None, fix: str) -> Path:
    home = Path(home) if home is not None else Path.home()
    path = Path(value).expanduser().resolve()
    for root in ((home / ".mempalace").resolve(), (home / "src" / "campaigns").resolve()):
        if _under(path, root):
            raise PalaceRefused(
                f"{label} {value} resolves to {path}, inside live location {root}; "
                f"refusing. {fix}"
            )
    return path


def require_library_palace(palace: Path, home: Path | None = None) -> Path:
    return _refuse_live(
        palace, "library.palace", home,
        "Set library.palace in ~/.config/hypostasis/hypostasis.yaml to an isolated path.",
    )


def require_isolated_dir(path: Path, label: str, home: Path | None = None) -> Path:
    """Same live-location refusal for work_dir / cache_dir (build rmtree's under them)."""
    return _refuse_live(
        path, label, home,
        f"Set {label} in ~/.config/hypostasis/hypostasis.yaml to an isolated path.",
    )
