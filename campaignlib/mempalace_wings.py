"""Resolve a campaign's mempalace wing names from its ``config.yaml``.

mneme renders the ``mempalace:`` section. A campaign without a declared corpus
gets ``canon_wing`` (a string) and ``index_wings``, or no section at all. A
campaign with a declared corpus (``<campaign>/.mneme/corpus.yaml``) gets
``canon_wings`` (a possibly empty list) and ``index_wings``, and no
``canon_wing``. Every reader that names wings goes through
:func:`resolve_mempalace_wings` so the two shapes are read one way.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import config_path

CORPUS_MARKER = Path(".mneme") / "corpus.yaml"
DEFAULT_CANON_WING = "narrative"


class MempalaceWingsError(Exception):
    """A corpus campaign whose ``mempalace:`` section lacks ``canon_wings``."""


@dataclass(frozen=True)
class MempalaceWings:
    canon_wings: list[str]
    index_wings: list[str]
    is_corpus: bool


def resolve_mempalace_wings(
    mempalace_config: dict | None, campaign_dir: Path | str
) -> MempalaceWings:
    """Pure function of the ``mempalace:`` section and the campaign directory.

    ``canon_wings`` wins when present; else ``canon_wing`` becomes a one-item
    list; else ``["narrative"]``. ``index_wings`` defaults to
    ``["chronicle", <campaign dir name with - as _>]``. Raises
    :class:`MempalaceWingsError` only for a corpus campaign without
    ``canon_wings``; a campaign without a corpus is never refused.
    """
    campaign_dir = Path(campaign_dir)
    cfg = mempalace_config or {}
    is_corpus = (campaign_dir / CORPUS_MARKER).is_file()

    if "canon_wings" in cfg:
        canon = list(cfg["canon_wings"] or [])
    elif is_corpus:
        raise MempalaceWingsError(
            f"{config_path(campaign_dir, 'config.yaml')}: {campaign_dir.name} "
            f"declares a corpus ({campaign_dir / CORPUS_MARKER}) but its "
            "'mempalace:' section has no 'canon_wings' — the face looks "
            "mis-rendered. Re-run `mneme mp refresh` (or bringup) for this campaign."
        )
    elif "canon_wing" in cfg:
        canon = [cfg["canon_wing"]]
    else:
        canon = [DEFAULT_CANON_WING]

    if "index_wings" in cfg:
        index = list(cfg["index_wings"])
    else:
        index = ["chronicle", campaign_dir.name.replace("-", "_")]

    return MempalaceWings(canon_wings=canon, index_wings=index, is_corpus=is_corpus)
