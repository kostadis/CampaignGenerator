"""Authority-file reader: ``library:`` block of hypostasis.yaml (FR-017).

Read-only. There are no defaults of our own; a missing piece is NotConfigured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipelines.library import NotConfigured
from pipelines.library.guard import require_library_palace

DEFAULT_PATH = Path("~/.config/hypostasis/hypostasis.yaml")
_FORMS = ("product_types", "book_ids", "all_converted")


@dataclass
class Selection:
    product_types: list[str] | None = None
    book_ids: list[int] | None = None
    all_converted: bool = False


@dataclass
class LibraryConfig:
    palace: Path
    source_root: Path
    work_dir: Path
    cache_dir: Path
    selection: Selection
    rpg_library_db: Path
    exclude_book_ids: list[int] = field(default_factory=list)
    env: dict = field(default_factory=dict)  # environ + yaml env:, never overriding


def _path(v) -> Path:
    return Path(str(v)).expanduser()


def _selection(raw) -> Selection:
    fix = "set exactly one of product_types / book_ids / all_converted under library.selection"
    if not isinstance(raw, dict):
        raise NotConfigured(f"library.selection is missing; {fix}")
    present = [
        k for k in _FORMS
        if raw.get(k) not in (None, False, [], "")
    ]
    if not present:
        raise NotConfigured(f"library.selection is empty; {fix}")
    if len(present) > 1:
        raise NotConfigured(
            f"library.selection uses more than one form ({', '.join(present)}); {fix}"
        )
    form = present[0]
    if form == "all_converted":
        if raw[form] is not True:
            raise NotConfigured(f"library.selection.all_converted must be true; {fix}")
        return Selection(all_converted=True)
    if not isinstance(raw[form], list):
        raise NotConfigured(f"library.selection.{form} must be a list; {fix}")
    if form == "book_ids":
        return Selection(book_ids=[int(x) for x in raw[form]])
    return Selection(product_types=[str(x) for x in raw[form]])


def load_library_config(
    path: Path = DEFAULT_PATH, environ=os.environ, home: Path | None = None
) -> LibraryConfig:
    p = _path(path)
    if not p.is_file():
        raise NotConfigured(f"hypostasis config not found: {p}; run hypostasis setup")
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    lib = cfg.get("library")
    if not isinstance(lib, dict):
        raise NotConfigured(f"{p} has no library: block; add one (see contracts/authority-config.md)")
    for key in ("palace", "work_dir", "source_root"):
        if not lib.get(key):
            raise NotConfigured(f"{p} library.{key} is not set")
    if not cfg.get("rpg_library_db"):
        raise NotConfigured(f"{p} has no top-level rpg_library_db key")
    selection = _selection(lib.get("selection"))

    yenv = cfg.get("env") or {}
    if "MEMPALACE_BACKEND" not in yenv and "MEMPALACE_BACKEND" not in environ:
        raise NotConfigured(
            f"{p} has no env.MEMPALACE_BACKEND; refusing to use a default backend"
        )
    env = dict(environ)
    for k, v in yenv.items():
        if str(k).startswith("MEMPALACE_") and k not in env:
            env[k] = str(v)

    work = _path(lib["work_dir"])
    return LibraryConfig(
        palace=require_library_palace(_path(lib["palace"]), home),
        source_root=_path(lib["source_root"]),
        work_dir=work,
        cache_dir=_path(lib["cache_dir"]) if lib.get("cache_dir") else work / "cache",
        selection=selection,
        rpg_library_db=_path(cfg["rpg_library_db"]),
        exclude_book_ids=[int(x) for x in (lib.get("exclude_book_ids") or [])],
        env=env,
    )
