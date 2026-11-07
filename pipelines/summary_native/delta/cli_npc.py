"""Handlers for ``delta census``, ``delta associate propose|decide`` and ``delta npc attest`` (T055, US2)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import associations, attest as attest_mod, census as census_mod
from .cli import DELTA_HANDLERS
from .errors import EXIT_OK, EXIT_USAGE, DeltaRefusal
from .plan import load_plan, plans_dir


def _campaign(args) -> Path:
    return Path(args.campaign_dir) if args.campaign_dir else Path.cwd()


def _plan(args, root: Path):
    if not args.plan:
        raise DeltaRefusal("--plan ID is required", EXIT_USAGE)
    return load_plan(plans_dir(root), args.plan)


def _emit(args, record: dict, text: str) -> int:
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) if args.json else text)
    return EXIT_OK


def _guard(fn):
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return fn(args)
        except DeltaRefusal as e:
            if args.json:
                print(json.dumps({"error": e.message, "exit_code": e.exit_code}))
            print(f"Error: {e.message}", file=sys.stderr)
            return e.exit_code
    return wrapper


def _rel(root: Path, path: str) -> str:
    """Campaign-relative when the source is under the root (the form a plan stores), else as given."""
    try:
        return Path(path).absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        return path


@_guard
def _census(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root)
    c, path = census_mod.run_census(root, plan)
    rec = {"plan_id": plan.plan_id, "path": str(path), "dispositions": c.dispositions(),
           "needs_review": sorted(e.subject for e in c.entries if e.needs_review),
           "skipped_player_characters": c.skipped_player_characters,
           "entries": [e.model_dump(mode="json") for e in c.entries]}
    return _emit(args, rec, "\n".join(f"{e.disposition:22} {e.subject}" + ("  (needs review)" if e.needs_review else "")
                                      for e in c.entries))


@_guard
def _associate_propose(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root)
    c = census_mod.load_census(root, plan.plan_id) if census_mod.census_path(root, plan.plan_id).is_file() \
        else census_mod.run_census(root, plan)[0]
    names = [{"name": e.subject, "evidence": [{"scene": s.id, "text": s.text} for s in e.evidence]}
             for e in c.entries if e.disposition == "unresolved"]
    backend = args.backend or plan.models.generation.backend
    model = args.model or plan.models.generation.model
    store = associations.propose(root, plan, names, backend=backend, model=model)
    rec = {"plan_id": plan.plan_id, "path": str(associations.store_path(root, plan.plan_id)),
           "associations": [a.model_dump(mode="json") for a in store.associations],
           "dropped": store.dropped}
    return _emit(args, rec, f"{len(store.associations)} association(s) unresolved/decided, {len(store.dropped)} dropped")


@_guard
def _associate_decide(args) -> int:
    root = _campaign(args)
    if not args.plan:
        raise DeltaRefusal("--plan ID is required", EXIT_USAGE)
    if not (args.reviewer or "").strip():
        raise DeltaRefusal("--reviewer is required to record an association decision; there is no default reviewer",
                           EXIT_USAGE)
    a = associations.decide(root, args.plan, args.id, args.decision, args.reviewer, reason=args.reason)
    return _emit(args, a.model_dump(mode="json"), f"{a.id}: {a.decision} (revision {a.decision_revision})")


@_guard
def _npc_attest(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root) if args.plan else None
    srcs = [{"path": _rel(root, s.path), "sha256": s.sha256} for s in plan.sources] if plan else []
    rec = attest_mod.attest(root, args.subject, reason=args.reason or "", publication_sha256=args.publication,
                            added_sources=srcs, plan_id=plan.plan_id if plan else None)
    return _emit(args, rec.model_dump(mode="json"), f"attested {rec.subject} at {rec.publication_sha256[:12]} ({rec.id})")


DELTA_HANDLERS["census"] = _census
DELTA_HANDLERS["associate propose"] = _associate_propose
DELTA_HANDLERS["associate decide"] = _associate_decide
DELTA_HANDLERS["npc attest"] = _npc_attest
