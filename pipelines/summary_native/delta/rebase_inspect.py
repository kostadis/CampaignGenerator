"""Chain-aware stale-pin report for the active grounding generation (spec 040, T010).

``inspect`` binds the baseline from the ACTIVE generation (the managed ``current`` link, never the newest
directory), walks the custody rows that generation holds through its delta lineage, hashes the bytes each
row pins against what is on disk now, and, for every row that differs, probes which old-byte providers could
supply the pinned bytes.  It reports every stale pin, not the first one (``CLAIMS_SOURCE_STALE`` stops at the
first).

Read-only by construction: nothing is written, the git probe is read-only, and no model is called.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from . import baseline as baseline_mod, custody_store
from .errors import EXIT_REFUSAL, DeltaRefusal
from .plan import load_plan, plans_dir

MISSING = "missing"


class OldByteProvider(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    available: bool
    detail: str


class StaleCustodyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int
    path: str
    expected_sha256: str
    actual_sha256: str  # a digest, or "missing"
    pinned_by: str  # the generation in the chain whose records recorded the pin
    old_bytes: list[OldByteProvider] = Field(default_factory=list)


class StaleCustodyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_ref: str
    plan_ref: str | None = None
    plan_baseline_ref: str | None = None
    plan_baseline_is_active: bool | None = None
    checked: int
    stale: list[StaleCustodyEntry]
    integrity_reads: int


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect(root: Path | str, plan_id: str | None = None,
            explicit_old: Mapping[int, Path | str] | None = None) -> StaleCustodyReport:
    """Every pinned source of the active generation whose current bytes differ from its pin."""
    root = Path(root).absolute()
    baseline = baseline_mod.bind(root)
    manifest = baseline_mod._read_manifest(root, baseline.generation_id)
    rows = baseline_mod._custody_rows_pinned_by(root, manifest)
    stale: list[StaleCustodyEntry] = []
    reads = 0
    for chapter in sorted(rows):
        rel, expected, pinned_by = rows[chapter]
        try:
            actual = _sha((root / rel).read_bytes())
            reads += 1
        except OSError:
            actual = MISSING
        if actual == expected:
            continue
        stale.append(StaleCustodyEntry(
            chapter=chapter, path=rel, expected_sha256=expected, actual_sha256=actual, pinned_by=pinned_by,
            old_bytes=[OldByteProvider(**p) for p in custody_store.probe(
                root, rel, expected, (explicit_old or {}).get(chapter))]))
    report = StaleCustodyReport(generation_ref=baseline.ref, checked=len(rows), stale=stale, integrity_reads=reads)
    if plan_id:
        try:
            plan = load_plan(plans_dir(root), plan_id)
        except DeltaRefusal as exc:
            raise DeltaRefusal(f"cannot inspect against plan {plan_id}: {exc.message}", EXIT_REFUSAL) from exc
        report.plan_ref = plan.plan_id
        report.plan_baseline_ref = plan.grounding_baseline_ref
        report.plan_baseline_is_active = plan.grounding_baseline_ref == baseline.ref
    return report


def render(report: StaleCustodyReport) -> str:
    lines = [f"generation {report.generation_ref}: {report.checked} pinned source(s), "
             f"{len(report.stale)} stale, {report.integrity_reads} integrity read(s), no model calls"]
    for e in report.stale:
        have = ", ".join(f"{p.provider}={'yes' if p.available else 'no'}" for p in e.old_bytes)
        lines.append(f"  ch {e.chapter:03d} {e.path}\n    pinned {e.expected_sha256} (by {e.pinned_by})\n"
                     f"    actual {e.actual_sha256}\n    old bytes: {have}")
    if report.plan_ref:
        lines.append(f"plan {report.plan_ref}: baseline {report.plan_baseline_ref} "
                     + ("is the active generation" if report.plan_baseline_is_active else "is NOT the active generation"))
    if report.stale:
        lines.append("next: summary_native delta rebase prepare --source PATH (one per chapter you mean to rebase)")
    return "\n".join(lines)
