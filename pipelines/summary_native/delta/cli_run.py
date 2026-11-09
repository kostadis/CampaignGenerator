"""``delta run status``, ``delta run resume`` and ``delta receipt`` (spec 039 T073, US4).

``status`` is read-only.  ``resume`` continues from the last durable stage and reports the model calls
it made (zero for compatible completed work).  ``receipt`` writes the completion receipt from run state.
Exit codes: resume 0 complete / 4 partial or awaiting review / 5 recovery required / 3 stale.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys

from . import receipt as receipt_mod, run as run_mod
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, emit, guarded, load_plan_arg
from .errors import EXIT_OK, EXIT_USAGE, DeltaRefusal


def _state(root, plan):
    path = run_mod.run_path(root, plan.plan_id)
    return run_mod.load_run(path) if path.is_file() else None


@guarded
def _status(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    state = _state(root, plan) or run_mod.RunState(run_id=f"run-{plan.plan_id}", plan_ref=f"{plan.plan_id}-r{plan.revision}")
    amb = run_mod.ambiguous_members(root, plan.plan_id) + run_mod.ambiguous_activation(root, plan)
    derived = run_mod.derive_status(state, plan, ambiguous=len(amb))
    state.status = derived
    record = {"plan_id": plan.plan_id, "status": derived.value,
              "started": run_mod.run_path(root, plan.plan_id).is_file(),
              "stages": [{"name": s.name, "status": s.status.value} for s in state.stages],
              "members": [m.model_dump(mode="json") for m in state.members],
              "required_stages": run_mod.required_stages(plan),
              "recovery_required": amb, "call_counts": {"model": state.counts.model_calls},
              "next_action": run_mod._next_action(state, plan, amb)}
    text = "\n".join([f"{plan.plan_id}: {derived.value}"]
                     + [f"  {s['name']}: {s['status']}" for s in record["stages"]]
                     + [f"  {m['subject']}: {m['outcome']}" for m in record["members"]]
                     + [f"next: {record['next_action']}"])
    return emit(args, record, text)


@guarded
def _resume(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    # advance narrates nothing, but the drafting engine prints progress; keep --json stdout clean
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
        report = run_mod.advance(root, plan, force=bool(args.force))
    record = report.to_dict()
    text = "\n".join([f"{plan.plan_id}: {report.status.value} (model calls this run: {report.calls_this_run})"]
                     + [f"  {s.name}: {s.status}{' (reused)' if s.reused else ''}" for s in report.stages]
                     + [f"next: {report.next_action}"])
    emit(args, record, text)
    return report.exit_code


@guarded
def _receipt(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    if plan.kind == "rebase":  # a rebase is applied by `grounding apply`, so there is no run state to read
        path = receipt_mod.write_rebase_receipt(root, plan)
    else:
        state = _state(root, plan)
        if state is None:
            raise DeltaRefusal(f"plan {plan.plan_id} has no run yet; run `delta run resume` first", EXIT_USAGE)
        path = receipt_mod.write_receipt(root, plan, state)
    rec = receipt_mod.load_receipt(path)
    return emit(args, {"path": str(path), "receipt": rec.model_dump(mode="json")},
                f"receipt written: {path}")


DELTA_HANDLERS["run status"] = _status
DELTA_HANDLERS["run resume"] = _resume
DELTA_HANDLERS["receipt"] = _receipt
