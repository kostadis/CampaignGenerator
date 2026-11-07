"""Recover an ambiguous grounding activation by operation identity (spec 039 FR-019, T071).

A delta grounding publication runs through the existing promotion path under a request id
(``publish_request.json`` ``request_id``, default ``delta-<plan_id>``), so its durable operation is
``operation-<request_id>``.  After a crash the operation may be unresolved (prepared, staged,
activation pending, commit unknown).  It is then *inspected* and reconciled with
``promotion.recovery.recover_publication``; ``grounding apply`` is never re-run blindly over it.
No model call is made here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipelines.summary_native.promotion.errors import PromotionError, recover_command
from pipelines.summary_native.promotion.models import AttemptState
from pipelines.summary_native.promotion.publish import UNRESOLVED_STATES, operation_records
from pipelines.summary_native.promotion.recovery import recover_publication

from .grounding_publish import PUBLISH_REQUEST_FILE, grounding_dir
from .plan import DeltaPlan

NONE, COMMITTED, ABORTED, AMBIGUOUS, INTERVENTION = "none", "committed", "aborted", "ambiguous", "intervention_required"


@dataclass(frozen=True)
class ActivationStatus:
    state: str  # none | committed | aborted | ambiguous | intervention_required
    request_id: str
    operation_id: str
    detail: str | None = None
    command: str | None = None  # the exact command that resolves an unresolved operation

    def to_dict(self) -> dict:
        return {"state": self.state, "request_id": self.request_id, "operation_id": self.operation_id,
                "detail": self.detail, "command": self.command}


def request_id_for(campaign_dir: Path | str, plan: DeltaPlan) -> str:
    path = grounding_dir(campaign_dir, plan.plan_id) / PUBLISH_REQUEST_FILE
    if path.is_file():
        try:
            rid = json.loads(path.read_text(encoding="utf-8")).get("request_id")
        except (OSError, ValueError):
            rid = None
        if rid:
            return str(rid)
    return f"delta-{plan.plan_id}"


def inspect(campaign_dir: Path | str, plan: DeltaPlan) -> ActivationStatus:
    """Read-only: what the durable operation bound to this plan's request id says."""
    root = Path(campaign_dir)
    rid = request_id_for(root, plan)
    op_id = f"operation-{rid}"
    for record in operation_records(root):
        bound = record.operation_id == op_id or (record.intent is not None and record.intent.request_id == rid)
        if not bound:
            continue
        if record.problem is not None:
            return ActivationStatus(AMBIGUOUS, rid, record.operation_id, record.problem,
                                    recover_command(record.operation_id))
        state = record.state.state  # type: ignore[union-attr]
        if state is AttemptState.COMMITTED:
            return ActivationStatus(COMMITTED, rid, record.operation_id)
        if state is AttemptState.ABORTED:
            return ActivationStatus(ABORTED, rid, record.operation_id,
                                    "the operation was aborted; the request id is spent, use a new one")
        if state in UNRESOLVED_STATES:
            return ActivationStatus(AMBIGUOUS, rid, record.operation_id, state.value,
                                    recover_command(record.operation_id))
    return ActivationStatus(NONE, rid, op_id)


def recover(campaign_dir: Path | str, plan: DeltaPlan) -> ActivationStatus:
    """Inspect, and when the operation is ambiguous reconcile exactly that operation.

    Returns the status afterwards: ``committed``/``aborted`` once recovery resolved it, or
    ``intervention_required`` when ``recover_publication`` refuses (a person must look).
    """
    status = inspect(campaign_dir, plan)
    if status.state != AMBIGUOUS:
        return status
    try:
        outcome = recover_publication(Path(campaign_dir), status.operation_id)
    except PromotionError as exc:
        return ActivationStatus(INTERVENTION, status.request_id, status.operation_id,
                                f"{getattr(exc, 'code', 'PROMOTION_RECOVERY')}: {exc}", status.command)
    return ActivationStatus(COMMITTED if outcome.get("state") == "committed" else ABORTED,
                            status.request_id, status.operation_id, "recovered")
