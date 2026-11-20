"""Refuse to use a palace path that resolves into a live palace (FR-001, #668).

Live set: the mempalace config dir ($MEMPALACE_CONFIG_DIR, else ~/.mempalace),
every palace registered in its config.json (read through the Principle V seam,
``mempalace_client.known_palaces``), the hypostasis ``paths.mempalace`` and
~/src/campaigns. A candidate is refused if it equals, is inside, or is an
ancestor of any of them. A palace dir that already exists, is non-empty and
carries no ``.library-palace`` marker is refused too (an unregistered live
palace, e.g. a campaign palace outside ~/.mempalace).
"""

from __future__ import annotations

import os
from pathlib import Path

from pipelines.library import PalaceRefused
from pipelines.rlm.mempalace_client import known_palaces

WING = "wing_dmsguild"
MARKER = ".library-palace"


def _live_set(home, environ, extra_live) -> list[tuple[Path, str]]:
    home = Path(home) if home is not None else Path.home()
    cfg_dir = environ.get("MEMPALACE_CONFIG_DIR")
    cfg_dir = Path(cfg_dir).expanduser() if cfg_dir else home / ".mempalace"
    live = [(cfg_dir.resolve(), "mempalace config dir")]
    live += [(p.resolve(), "registered mempalace palace") for p in known_palaces(cfg_dir, environ)]
    for x in extra_live or ():
        live.append((Path(x).expanduser().resolve(), "hypostasis paths.mempalace"))
    live.append(((home / "src" / "campaigns").resolve(), "campaigns directory"))
    return live


def _relation(path: Path, live: Path) -> str | None:
    if path == live:
        return "equal to"
    if live in path.parents:
        return "inside"
    if path in live.parents:
        return "an ancestor of"
    return None


def _refuse_live(value, label, home, fix, environ, extra_live) -> Path:
    path = Path(value).expanduser().resolve()
    for root, what in _live_set(home, environ, extra_live):
        rel = _relation(path, root)
        if rel:
            raise PalaceRefused(
                f"{label} {value} resolves to {path}, which is {rel} live {what} {root}; "
                f"refusing. {fix}"
            )
    return path


def require_library_palace(
    palace: Path, home: Path | None = None, environ=os.environ, extra_live=()
) -> Path:
    fix = "Set library.palace in ~/.config/hypostasis/hypostasis.yaml to an isolated path."
    path = _refuse_live(palace, "library.palace", home, fix, environ, extra_live)
    if path.is_dir() and any(path.iterdir()) and not (path / MARKER).exists():
        raise PalaceRefused(
            f"library.palace {palace} resolves to {path}, an unmarked existing palace "
            f"(non-empty, no {MARKER} marker); refusing. {fix} If it really is the library "
            f"palace, create the marker file {path / MARKER} yourself."
        )
    return path


def mark_library_palace(palace: Path) -> None:
    """Write the marker (call only after require_library_palace accepted the path)."""
    Path(palace).mkdir(parents=True, exist_ok=True)
    (Path(palace) / MARKER).write_text("library palace (hypostasis); safe to rebuild\n")


def require_isolated_dir(
    path: Path, label: str, home: Path | None = None, environ=os.environ, extra_live=()
) -> Path:
    """Same live-location refusal for work_dir / cache_dir (no marker rule)."""
    return _refuse_live(
        path, label, home,
        f"Set {label} in ~/.config/hypostasis/hypostasis.yaml to an isolated path.",
        environ, extra_live,
    )
