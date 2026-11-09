"""Delta lineage record (spec 039 FR-016, research R6/R8).

A delta publication never writes a synthetic full-corpus ``synth`` record (FR-021).  It records, per
required bundle member, either *inherited* (carried unchanged from the baseline generation, with
custody: the baseline path and a digest that must still match) or *produced* (regenerated this run,
with a passing check).  These are NEW pydantic models: they are deliberately not subclasses of
``StrictPromotionModel`` or ``_GateModel`` (R8 / Principle XIII), so no strict model gains a field.
No model call is made here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

SCHEMA_VERSION = 1
KIND = "delta"
_SHA = re.compile(r"^[0-9a-f]{64}$")


class CustodyRef(BaseModel):
    """Where an inherited member's bytes live: a campaign-relative baseline path and its digest."""

    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str


class LineageMember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    mode: Literal["inherited", "produced"]
    sha256: str
    required: bool = True
    custody_ref: CustodyRef | None = None  # inherited
    check_ref: str | None = None  # produced
    check_status: Literal["passed", "failed", "not_run"] | None = None  # produced


class BaselineRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_id: str
    manifest_sha256: str


class RebaseSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter: int
    path: str
    old_sha256: str
    new_sha256: str
    old_snapshot: str
    current_snapshot: str


class RebaseBlock(BaseModel):
    """Spec 040 data-model: present only on a rebase plan's lineage record."""

    model_config = ConfigDict(extra="forbid")
    rebase_id: str
    decisions_ref: str
    decisions_sha256: str
    sources: list[RebaseSource] = Field(default_factory=list)
    repaired_lines: list[str] = Field(default_factory=list)
    held_lines: list[str] = Field(default_factory=list)
    attested_members: list[str] = Field(default_factory=list)
    unchanged_members: list[str] = Field(default_factory=list)


class DeltaLineageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = SCHEMA_VERSION
    kind: Literal["delta"] = KIND
    plan_ref: str
    baseline: BaselineRef
    members: list[LineageMember] = Field(default_factory=list)
    #: Omitted from serialisation and digest when None (research R10), so pre-spec-040 records are byte-stable.
    rebase: RebaseBlock | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_rebase(self, handler):
        data = handler(self)
        if data.get("rebase") is None:
            data.pop("rebase", None)
        return data


def _sha_ok(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def member_problems(member: LineageMember, campaign_dir: Path | None = None) -> list[str]:
    name = member.name
    if member.mode == "inherited":
        custody = member.custody_ref
        if custody is None:
            return [f"{name}: inherited member has no custody reference"]
        if not _sha_ok(custody.sha256) or custody.sha256 != member.sha256:
            return [f"{name}: custody digest does not match the member digest"]
        if campaign_dir is not None:
            path = Path(campaign_dir) / custody.path
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return [f"{name}: baseline custody file is missing ({custody.path})"]
            if actual != custody.sha256:
                return [f"{name}: baseline custody bytes changed ({custody.path})"]
        return []
    if not member.check_ref:
        return [f"{name}: produced member has no check reference"]
    if member.check_status != "passed":
        return [f"{name}: produced member's check is {member.check_status or 'not run'}"]
    if not _sha_ok(member.sha256):
        return [f"{name}: produced member has no valid digest"]
    return []


def delta_record_problems(record: dict[str, Any] | DeltaLineageRecord, campaign_dir: Path | None = None) -> list[str]:
    """Named reasons the record is incomplete; empty means complete."""
    try:
        model = record if isinstance(record, DeltaLineageRecord) else DeltaLineageRecord.model_validate(record)
    except Exception as exc:  # noqa: BLE001 - any shape error is "incomplete"
        return [f"malformed delta record: {str(exc).splitlines()[0]}"]
    problems: list[str] = []
    if not model.members:
        problems.append("delta record has no members")
    if not _sha_ok(model.baseline.manifest_sha256):
        problems.append("baseline manifest digest is not valid")
    for member in model.members:
        if member.required:
            problems.extend(member_problems(member, campaign_dir))
    return problems


def delta_record_complete(record: dict[str, Any] | DeltaLineageRecord, campaign_dir: Path | None = None) -> bool:
    """Every required member is inherited-with-custody or produced-with-passing-check."""
    return not delta_record_problems(record, campaign_dir)


def is_delta_record(record: object) -> bool:
    return isinstance(record, dict) and record.get("kind") == KIND


def save_lineage(record: DeltaLineageRecord, path: Path | str) -> None:
    import os

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)


def load_lineage(path: Path | str) -> DeltaLineageRecord:
    return DeltaLineageRecord.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def custody_dependencies(record: dict[str, Any]) -> list[tuple[str, str]]:
    """``(campaign-relative path, sha256)`` the manifest must bind for a delta record."""
    model = DeltaLineageRecord.model_validate(record)
    return [(m.custody_ref.path, m.custody_ref.sha256) for m in model.members if m.mode == "inherited" and m.custody_ref]
