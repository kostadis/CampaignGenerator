"""Handlers for ``delta npc draft|verify|publish`` (spec 039 T055, US2)."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from . import npc_update
from .cli import DELTA_HANDLERS
from .errors import EXIT_OK, EXIT_PARTIAL, EXIT_REFUSAL, EXIT_USAGE, DeltaRefusal
from .plan import load_plan, plans_dir


def _campaign(args) -> Path:
    return Path(args.campaign_dir) if args.campaign_dir else Path.cwd()


def _plan(args, root: Path):
    if not args.plan:
        raise DeltaRefusal("--plan ID is required", EXIT_USAGE)
    return load_plan(plans_dir(root), args.plan)


def _emit(args, record: dict, text: str) -> None:
    print(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) if args.json else text)


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


@_guard
def _npc_draft(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root)
    if getattr(args, "allow_historical_parse", False):
        npc_update.allow_historical_parse(root, "--allow-historical-parse given to `delta npc draft`")
    # run_draft narrates progress on stdout; under --json stdout carries exactly one object.
    with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
        out = npc_update.draft(root, plan, backend=args.backend, model=args.model,
                               audience=getattr(args, "audience", "gm") or "gm", force=args.force)
    rec = {"plan_id": plan.plan_id, "range": npc_update.range_name(out.since, out.until),
           "members": out.members, "verify": out.verify, "read_counts": out.reads, "exit_code": out.exit_code}
    _emit(args, rec, f"drafted {len(out.members)} member(s) in {rec['range']}: "
          + ", ".join(f"{s} ({v['verdict']})" for s, v in out.verify.items()))
    return EXIT_OK if out.exit_code == 0 else out.exit_code


@_guard
def _npc_verify(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root)
    results = npc_update.verify(root, plan)
    rec = {"plan_id": plan.plan_id,
           "verify": {s: {k: r.get(k) for k in ("verdict", "counts", "evidence_kind", "missing_scope", "reason")}
                      for s, r in results.items()}}
    _emit(args, rec, "\n".join(f"{s}: {r.get('verdict')} (sparse evidence)" for s, r in results.items()))
    return EXIT_OK if all(r.get("verdict") == "pass" for r in results.values()) else EXIT_REFUSAL


@_guard
def _npc_publish(args) -> int:
    root = _campaign(args)
    plan = _plan(args, root)
    members = list(args.member or [])
    if not members:
        raise DeltaRefusal("no members selected; name each NPC with --member (there is no 'all')", EXIT_USAGE)
    if not args.preview_sha:
        pv = npc_update.store_preview(root, plan, members)
        _emit(args, {**pv, "published": False},
              f"preview {pv['preview_sha256']} for {len(pv['members'])} member(s); nothing was published (the preview is recorded for `delta run resume`). "
              "Re-run with --preview-sha to publish.")
        return EXIT_OK
    results = npc_update.publish(root, plan, members, args.preview_sha)
    rec = {"plan_id": plan.plan_id,
           "members": [{"subject": r.name, "slug": r.slug, "outcome": r.outcome, "reason": r.reason,
                        "receipt": r.receipt} for r in results]}
    _emit(args, rec, "\n".join(r.line() for r in results))
    done = sum(1 for r in results if r.published)
    if done == len(results):
        return EXIT_OK
    return EXIT_PARTIAL if done else EXIT_REFUSAL


DELTA_HANDLERS["npc draft"] = _npc_draft
DELTA_HANDLERS["npc verify"] = _npc_verify
DELTA_HANDLERS["npc publish"] = _npc_publish
