"""``delta grounding preview`` and ``delta grounding apply`` handlers (spec 039 T037)."""

from __future__ import annotations

import argparse

from pipelines.summary_native.scheduler import atomic_write_record

from . import grounding_publish as gp
from .grounding_candidates import require_check_binding, stage_for_promotion
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, emit, guarded, load_plan_arg
from .errors import EXIT_OK, EXIT_USAGE, DeltaRefusal


@guarded
def _preview(args: argparse.Namespace) -> int:
    campaign = campaign_root(args)
    plan = load_plan_arg(args, campaign)
    gp.load_inputs(campaign, plan.plan_id)  # fail early, with the usage message, before staging
    staged = stage_for_promotion(campaign, plan, review=getattr(args, "review", None),
                                 claims_report=getattr(args, "claims_report", None),
                                 request_id=getattr(args, "request_id", None))
    candidates, lineage, request = gp.load_inputs(campaign, plan.plan_id)
    require_check_binding(campaign, candidates, lineage)
    record = gp.preview(plan, candidates, lineage, request, campaign_dir=campaign)
    atomic_write_record(gp.grounding_dir(campaign, plan.plan_id) / gp.PREVIEW_FILE, record.model_dump(mode="json"))
    emit(args, {**record.model_dump(mode="json"), "staged": staged},
         f"preview {record.preview_sha256} ({'complete' if record.complete else 'INCOMPLETE'})"
         + "".join(f"\n  - {p}" for p in record.problems))
    return EXIT_OK


@guarded
def _apply(args: argparse.Namespace) -> int:
    if not args.preview_sha:
        raise DeltaRefusal("--preview-sha is required; run `delta grounding preview` first", EXIT_USAGE)
    campaign = campaign_root(args)
    plan = load_plan_arg(args, campaign)
    result = gp.apply(plan, args.preview_sha, campaign_dir=campaign)
    return emit(args, {"applied": True, "result": result}, "applied")


DELTA_HANDLERS["grounding preview"] = _preview
DELTA_HANDLERS["grounding apply"] = _apply
