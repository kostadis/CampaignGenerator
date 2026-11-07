"""Explicit source ingestion for a delta run (spec 039, T009, research R1).

Only the selected sources are parsed.  Every file touched is recorded with a
role and a read count so SC-001 (one new chapter: ``parsed_new == 1``,
``parsed_historical == 0``) is a measured fact, not an assumption.  The parse
count comes from ``validate.scan``'s ``parse_log`` (one entry per real
``parse_file`` call), never from ``len(sources)``.  No model call is made here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from pipelines.summary_native import scheduler, validate
from .errors import EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import EMPTY_SELECTION_MESSAGE, DeltaPlan

SCHEMA_VERSION = 1
ROLES = ("parsed_new", "parsed_historical", "reused_artifact", "integrity_only", "model_input")


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str
    role: str
    read_count: int = Field(ge=0)


class SourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    entries: list[SourceEntry] = Field(default_factory=list)
    _report: object = PrivateAttr(default=None)

    @property
    def read_counts(self) -> dict[str, int]:
        counts = {r: 0 for r in ROLES}
        for e in self.entries:
            counts[e.role] += e.read_count
        return counts

    @property
    def report(self):
        """The ``ValidationReport`` from the selected-only scan (not serialised)."""
        return self._report

    def add(self, path: Path | str, role: str, *, read_count: int = 1, sha256: str | None = None) -> None:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
        p = Path(path)
        self.entries.append(SourceEntry(
            path=str(p), sha256=sha256 or sha256_file(p), role=role, read_count=read_count))

    def to_record(self) -> dict:
        return {**self.model_dump(mode="json"), "read_counts": self.read_counts}

    @classmethod
    def from_record(cls, record: dict) -> "SourceSelection":
        data = {k: v for k, v in record.items() if k not in ("read_counts", "schema")}
        return cls.model_validate(data)


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ingest(
    plan_or_source_paths: DeltaPlan | Iterable[Path | str],
    *,
    summaries_dir: Path | str | None = None,
    campaign_root: Path | str | None = None,
    integrity_paths: Iterable[Path | str] = (),
) -> SourceSelection:
    """Parse exactly the selected sources; record roles and read counts.

    A ``DeltaPlan`` pins each source's sha256: a mismatch refuses (exit 3, stale).
    ``integrity_paths`` are hashed, never parsed, and counted as ``integrity_only``.
    """
    expected: dict[str, str] = {}
    if isinstance(plan_or_source_paths, DeltaPlan):
        paths = [Path(s.path) for s in plan_or_source_paths.sources]
        expected = {str(Path(s.path)): s.sha256 for s in plan_or_source_paths.sources}
    else:
        paths = [Path(p) for p in plan_or_source_paths]
    if not paths:
        raise DeltaRefusal(EMPTY_SELECTION_MESSAGE, EXIT_USAGE)

    shas: dict[Path, str] = {}
    for p in paths:
        if not p.is_file():
            raise DeltaRefusal(f"source not found: {p}", EXIT_USAGE)
        shas[p] = sha256_file(p)
        want = expected.get(str(p))
        if want is not None and shas[p] != want:
            raise DeltaRefusal(
                f"source changed since the plan was made: {p} (planned {want[:12]}, now {shas[p][:12]}); "
                "re-plan.", EXIT_STALE)

    first = paths[0].resolve()
    sdir = Path(summaries_dir) if summaries_dir is not None else first.parent
    root = Path(campaign_root) if campaign_root is not None else sdir
    log: list[Path] = []
    try:
        report = validate.scan(sdir, root, None, None, sources=paths, parse_log=log)
    except validate.EmptySourceSelection as exc:  # defensive; emptiness refused above
        raise DeltaRefusal(str(exc), EXIT_USAGE) from exc

    selected = {p.resolve() for p in paths}
    sel = SourceSelection()
    sel._report = report
    for p in paths:
        n = sum(1 for q in log if q.resolve() == p.resolve())
        sel.add(p, "parsed_new", read_count=n, sha256=shas[p])
    for q in log:
        if q.resolve() not in selected:
            sel.add(q, "parsed_historical", read_count=1)
    for ip in integrity_paths:
        sel.add(ip, "integrity_only", read_count=1)
    return sel


def save_selection(selection: SourceSelection, path: Path | str) -> Path:
    path = Path(path)
    scheduler.atomic_write_record(path, selection.to_record())
    return path


def load_selection(path: Path | str) -> SourceSelection:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    return SourceSelection.from_record(record)
