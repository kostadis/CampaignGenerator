"""``delta plan`` and ``delta sources`` (spec 039, T037/T039).

Neither verb makes a model call.  ``plan`` records an explicit selection (no source means exit 2 and
no file); ``sources`` ingests exactly the selected files and reports measured read counts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from pipelines.summary_native import resolve

from . import baseline as baseline_mod, sources as sources_mod
from .cli import DELTA_HANDLERS
from .errors import EXIT_OK, EXIT_REFUSAL, EXIT_USAGE, DeltaRefusal
from .plan import (
    DELTA_ROOT_REL, EMPTY_SELECTION_MESSAGE, PRODUCTS, ModelChoice, PlanModels, create_plan,
    load_plan, plans_dir, save_plan,
)

DEFAULT_STOP = "plan"


def campaign_root(args: argparse.Namespace) -> Path:
    return Path(args.campaign_dir).absolute() if args.campaign_dir else Path.cwd()


def resolve_model_choice(root: Path, backend: str | None, model: str | None) -> ModelChoice:
    """The plan's backend/model: flag > ``grounding.yaml summary_native.prose`` > the schema's one default.

    This is the mechanism ``summary_native synth`` uses (``resolve.resolve_prose``); the delta family
    declares no default of its own (Principle XII).  A backend that resolves no model refuses.
    """
    path = root / "config" / "grounding.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError) as exc:
        raise DeltaRefusal(f"cannot read {path}: {exc}", EXIT_USAGE) from exc
    section = data.get("summary_native") if isinstance(data, dict) else None
    try:
        prose = resolve.resolve_prose(section if isinstance(section, dict) else {}, backend=backend, model=model)
    except ValueError as exc:
        raise DeltaRefusal(str(exc), EXIT_USAGE) from exc
    if not prose.model:
        raise DeltaRefusal(
            f"no model resolves for backend {prose.backend}; pass --model (or set summary_native.prose in grounding.yaml)",
            EXIT_USAGE)
    return ModelChoice(backend=prose.backend, model=prose.model, effort=prose.effort)


def load_plan_arg(args: argparse.Namespace, root: Path):
    if not getattr(args, "plan", None):
        raise DeltaRefusal("--plan ID is required", EXIT_USAGE)
    return load_plan(plans_dir(root), args.plan)


def emit(args: argparse.Namespace, record: dict, text: str) -> int:
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) if args.json else text)
    return EXIT_OK


def guarded(fn):
    """Catch ``DeltaRefusal`` at the handler edge: message on stderr, JSON error under ``--json``."""
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return fn(args)
        except DeltaRefusal as e:
            if getattr(args, "json", False):
                print(json.dumps({"error": e.message, "exit_code": e.exit_code}))
            print(f"Error: {e.message}", file=sys.stderr)
            return e.exit_code
    wrapper.__name__ = fn.__name__
    return wrapper


def selection_path(root: Path, plan_id: str) -> Path:
    return root / DELTA_ROOT_REL / "sources" / f"{plan_id}.sources.json"


def campaign_identity(root: Path) -> str:
    """The campaign's one canonical identity (``docs/reviews/campaign.json``); never a new store."""
    from pipelines.summary_native.review.store import ReviewStoreError, load_campaign_identity
    try:
        return str(load_campaign_identity(root).campaign_id)
    except ReviewStoreError as exc:
        if str(exc).startswith("REVIEW_CAMPAIGN_MOVED"):
            # FR-022: a moved copy (a worktree) is accepted only through a verified transfer binding;
            # ``bound_identity`` refuses an unbound, tampered or stale copy. The guard itself is untouched.
            from pipelines.summary_native.delta.transfer import bound_identity

            return bound_identity(root)
        raise DeltaRefusal(f"the campaign has no identity yet ({exc}); initialise it with `summary_native review init`",
                           EXIT_REFUSAL) from exc


@guarded
def _plan(args: argparse.Namespace) -> int:
    if not args.source:
        raise DeltaRefusal(EMPTY_SELECTION_MESSAGE, EXIT_USAGE)
    products = tuple(dict.fromkeys(args.product or ()))
    if not products or any(p not in PRODUCTS for p in products):
        raise DeltaRefusal(f"--product is required: one or more of {', '.join(PRODUCTS)}", EXIT_USAGE)
    root = campaign_root(args)
    choice = resolve_model_choice(root, args.backend, args.model)
    ref = None
    if "grounding" in products:
        try:
            ref = baseline_mod.bind(root).ref
        except DeltaRefusal:
            ref = None  # `baseline status` reports why; a plan can still be recorded
    plan = create_plan(
        campaign_identity=campaign_identity(root), products=products,
        stopping_point=args.stop or DEFAULT_STOP,
        source_paths=[Path(s).absolute() for s in args.source], campaign_root=root,
        models=PlanModels(generation=choice, consistency=choice), grounding_baseline_ref=ref)
    path = save_plan(plan, plans_dir(root))
    record = {"plan_id": plan.plan_id, "revision": plan.revision, "path": str(path),
              "products": list(plan.products), "stopping_point": plan.stopping_point.value,
              "sources": [{**s.model_dump(), "path": Path(s.path).relative_to(root).as_posix()} for s in plan.sources],
              "grounding_baseline_ref": plan.grounding_baseline_ref,
              "call_counts": {"model": 0}}
    return emit(args, record, f"plan {plan.plan_id} saved: {path}")


@guarded
def _sources(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    selection = sources_mod.ingest(plan, campaign_root=root)
    path = sources_mod.save_selection(selection, selection_path(root, plan.plan_id))
    report = selection.report
    blocking = report.blocking_count if report is not None else 0
    record = {"plan_id": plan.plan_id, "path": str(path), "read_counts": selection.read_counts,
              "call_counts": {"model": 0}, "entries": [e.model_dump() for e in selection.entries],
              "blocking_findings": blocking}
    counts = selection.read_counts
    text = (f"parsed_new={counts['parsed_new']} parsed_historical={counts['parsed_historical']} "
            f"integrity_only={counts['integrity_only']} (no model calls)")
    code = emit(args, record, text)
    if blocking:
        print(f"Error: {blocking} blocking finding(s) in the selected sources", file=sys.stderr)
        return EXIT_REFUSAL
    return code


DELTA_HANDLERS["plan"] = _plan
DELTA_HANDLERS["sources"] = _sources
