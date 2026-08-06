"""Corpus enumeration: which files a campaign's manifest block puts in scope.

**Phase-2 scope note.** Only the enumerator lives here so far. Scanner selection
(`rg` vs. the stdlib fallback), the pinned rg flag set, and excerpt extraction
land at T039+ — after the GM review gate at T031. What is here now exists
because `provenance check` cannot validate a manifest without knowing which
files that manifest actually covers.

It is deliberately *one* function rather than one for `check` and one for
search. The exclude-glob suppression count is a number both of them report
(FR-012), and `check` validating a different file set from the one search reads
would make that number a lie in exactly the direction nobody would notice.

## `.gitignore` gets no vote

The walk consults version-control state nowhere. 230 real files in the live
workspace are `.gitignore`d — 213 of them Phandalin NPC sidecars, all
working-reference tier — and they are all on disk, all true, and all
searchable. What is or is not committed is a version-control concern; the
manifest's ``exclude`` list is the single scope authority (research D17).

## The suppression counter is per-glob, on purpose

A single total would be dominated by the built-in defaults (`.git/**`,
`node_modules/**`), which is precisely how a GM-added glob that quietly narrows
every future search would hide. Attributing each suppressed file to the glob
that removed it keeps the one number that matters visible next to the noise.

Files are extension-filtered *before* exclude attribution, so the counter reports
searchable files removed rather than several thousand git objects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .tiers import compile_glob


@dataclass(frozen=True)
class FileSet:
    """Every searchable file under one campaign root, and what was left out."""

    paths: tuple[str, ...]
    """Campaign-relative POSIX paths, sorted. Sorted because rg is multithreaded
    and its file order is not stable; every ordering guarantee downstream is
    built on a total order established here."""

    excluded: Mapping[str, int]
    """Exclude glob -> count of searchable files it removed. Every declared glob
    is a key, including the ones that removed nothing — a glob with a zero is
    how a GM sees that a pattern is not doing what they thought."""

    unreadable: tuple[str, ...] = ()
    """Directories the walk could not read. Reported, never swallowed."""

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())


def enumerate_files(campaign, campaign_root: str | Path) -> FileSet:
    """Walk one campaign root, applying ``search_extensions`` then ``exclude``.

    ``campaign`` is a manifest ``Campaign`` (only ``.search_extensions`` and
    ``.exclude`` are touched, so a stub works in tests).

    Symlinked directories are not followed: a cycle would hang the walk, and a
    symlink out of the campaign root would silently pull another game's files
    into a search that named exactly one campaign (FR-008).
    """
    root = Path(campaign_root)
    exts = {e.lower() for e in getattr(campaign, "search_extensions", ())}
    globs = tuple(getattr(campaign, "exclude", ()))
    excluded: dict[str, int] = {g: 0 for g in globs}
    unreadable: list[str] = []
    paths: list[str] = []

    def _onerror(exc: OSError) -> None:
        unreadable.append(str(getattr(exc, "filename", exc)))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for filename in filenames:
            rel = filename if rel_dir == "." else f"{rel_dir}/{filename}"
            if exts and Path(filename).suffix.lower() not in exts:
                continue
            hit = next((g for g in globs if compile_glob(g).search(rel)), None)
            if hit is not None:
                excluded[hit] += 1
                continue
            paths.append(rel)

    return FileSet(tuple(sorted(paths)), excluded, tuple(sorted(unreadable)))
