"""Strict versioned contracts shared by the CLI, editor, and native agents."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

Digest = str


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Evidence(Contract):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot: str
    label: Literal["source", "derived", "generated", "configuration"]


class Generation(Contract):
    backend: str
    model: str
    effort: str | None = None
    producer: str
    command: list[str] = Field(default_factory=list)
    usage: dict[str, int | float | None] = Field(default_factory=dict)


class Rule(Contract):
    authority: Evidence
    reference: str
    scope: str


class Change(Contract):
    source: Evidence
    target: str
    before: str
    after: str


class Finding(Contract):
    id: str
    scene: str | None = None
    evidence: Evidence
    location: str
    description: str
    proposed_action: str
    consequences: dict[Literal["approve", "reject", "discuss"], str]
    rule: Rule | None = None
    change: Change | None = None

    @field_validator("consequences")
    @classmethod
    def all_consequences(cls, value):
        if set(value) != {"approve", "reject", "discuss"} or not all(value.values()):
            raise ValueError("each finding must explain approve, reject, and discuss consequences")
        return value


class Decision(Contract):
    finding_id: str
    finding_sha256: str
    decision: Literal["approve", "reject", "discuss"]
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    at: str
    group: str | None = None


class Check(Contract):
    name: str
    status: Literal["complete", "skipped", "failed"]
    sources: list[Evidence]
    findings: list[Finding] = Field(default_factory=list)
    producer: str
    at: str


class Approval(Contract):
    actor: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    at: str
    binding: str


class Run(Contract):
    id: str
    stage: str
    selection: list[str] = Field(min_length=1)
    inputs: list[Evidence] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(default_factory=list)
    generation: Generation
    outputs: list[Evidence] = Field(default_factory=list)
    status: Literal["pending_agent", "running", "generated", "failed"] = "pending_agent"
    checks: list[Check] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    approval: Approval | None = None
    started_at: str
    completed_at: str | None = None
    failure: str | None = None
    task: dict = Field(default_factory=dict)


class Application(Contract):
    id: str
    run_id: str
    finding_ids: list[str]
    before: dict[str, str | None]
    after: dict[str, Evidence]
    at: str


class Workflow(Contract):
    schema_version: Literal[1] = 1
    session_id: str
    config: str
    revision: int = 0
    runs: list[Run] = Field(default_factory=list)
    applications: list[Application] = Field(default_factory=list)
    selected_versions: dict[str, str] = Field(default_factory=dict)
    notes_selected: list[str] = Field(default_factory=list)
    chapters_selected: list[str] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
