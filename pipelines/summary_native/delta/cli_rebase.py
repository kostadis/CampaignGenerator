"""Handlers for ``delta rebase ...`` and ``delta rebind`` (spec 040).

``--json`` output is ``{ok, code, message, data}`` on stdout for success and refusal alike, so a caller reads
one shape; the exit code is the process's (contracts/cli.md).  No model call is made in this module: the one
drafting call is :mod:`.rebase_propose`, reached only by ``rebase propose``.  ``rebind`` stays a stub until
the story that implements it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import rebase, rebase_inspect, rebase_propose
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, load_plan_arg, resolve_model_choice
from .errors import EXIT_OK, EXIT_RECOVERY, EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from .plan import PlanModels

REBASE_LEAVES = (
    "rebase inspect", "rebase prepare", "rebase show", "rebase propose", "rebase repair", "rebase decide",
    "rebind",
)
_CODE = re.compile(r"^([A-Z][A-Z0-9_]+):")
_GENERIC = {EXIT_REFUSAL: "REFUSED", EXIT_USAGE: "USAGE", EXIT_STALE: "STALE", EXIT_RECOVERY: "RECOVERY"}


def _out(args: argparse.Namespace, data: dict, message: str) -> int:
    if args.json:
        print(json.dumps({"ok": True, "code": "OK", "message": message, "data": data},
                         indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(message)
    return EXIT_OK


def _guarded(fn):
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return fn(args)
        except DeltaRefusal as e:
            m = _CODE.match(e.message)
            code = m.group(1) if m else _GENERIC.get(e.exit_code, "REFUSED")
            if args.json:
                print(json.dumps({"ok": False, "code": code, "message": e.message,
                                  "data": {"exit_code": e.exit_code}}, indent=2, sort_keys=True, ensure_ascii=False))
            print(f"Error: {e.message}", file=sys.stderr)
            return e.exit_code
    wrapper.__name__ = fn.__name__
    return wrapper


def _pairs(values: list[str] | None, flag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in values or ():
        key, sep, value = item.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise DeltaRefusal(f"bad {flag} {item!r}; expected KEY=VALUE", EXIT_USAGE)
        if key.strip() in out:
            raise DeltaRefusal(f"{flag} names {key.strip()!r} twice", EXIT_USAGE)
        out[key.strip()] = value.strip()
    return out


def _stub(args: argparse.Namespace) -> int:
    print(f"Error: summary_native delta {args.delta_leaf}: not implemented yet (spec 040)", file=sys.stderr)
    return EXIT_USAGE


@_guarded
def _inspect(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    report = rebase_inspect.inspect(root, args.plan)
    data = {**report.model_dump(mode="json"), "call_counts": {"model": 0}}
    return _out(args, data, rebase_inspect.render(report))


@_guarded
def _prepare(args: argparse.Namespace) -> int:
    if not args.source:
        raise DeltaRefusal("no sources selected; a rebase does not default to every stale chapter.", EXIT_USAGE)
    root = campaign_root(args)
    old_bytes: dict[int, Path] = {}
    for chapter, path in _pairs(args.old_bytes, "--old-bytes").items():
        try:
            old_bytes[int(chapter)] = Path(path)
        except ValueError as exc:
            raise DeltaRefusal(f"bad --old-bytes chapter {chapter!r}; expected CHAPTER=PATH", EXIT_USAGE) from exc
    choice = resolve_model_choice(root, None, None)
    record = rebase.prepare(root, [Path(s).absolute() for s in args.source],
                            models=PlanModels(generation=choice, consistency=choice),
                            old_bytes=old_bytes, for_plan=args.for_plan)
    impact = record["impact"]
    verb = "prepared" if record["created"] else "already prepared (no change)"
    return _out(args, record, f"rebase {record['rebase_id']} {verb}: plan {record['plan_id']}; "
                f"{impact['affected_lines']} affected line(s), {len(impact['unknown_members'])} unknown-impact "
                f"member(s). Next: `delta rebase show --plan {record['plan_id']}`")


@_guarded
def _show(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    data = rebase.show(root, plan.plan_id)
    return _out(args, data, Path(root, data["review"]).read_text(encoding="utf-8"))


@_guarded
def _propose(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    backend = args.backend or plan.models.generation.backend
    model = args.model or plan.models.generation.model
    data = rebase_propose.propose(root, plan.plan_id, backend=backend, model=model)
    return _out(args, data, f"{len(data['proposals'])} draft repair(s), {len(data['rejected'])} rejected; none "
                "approved. Decide each with `delta grounding decide`.")


@_guarded
def _repair(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    if args.text is None:
        raise DeltaRefusal("--text is required to record a repair", EXIT_USAGE)
    data = rebase.repair_add(root, plan.plan_id, args.line or "", args.text, args.reason or "",
                             args.reviewer or "")
    return _out(args, data, f"repair {data['proposal_id']} recorded as a draft for {data['line_id']}. "
                f"Next: {data['next']}")


@_guarded
def _decide(args: argparse.Namespace) -> int:
    root = campaign_root(args)
    plan = load_plan_arg(args, root)
    if not args.reviewer or not args.reviewer.strip():
        raise DeltaRefusal("--reviewer is required to record a rebase decision; there is no default reviewer",
                           EXIT_USAGE)
    if not args.source_decision:
        raise DeltaRefusal("--source-decision CH=DECISION is required, one per selected chapter", EXIT_USAGE)
    data = rebase.decide(root, plan.plan_id, reviewer=args.reviewer,
                         source_decisions=_pairs(args.source_decision, "--source-decision"),
                         member_decisions=_pairs(args.member_decision, "--member-decision"), reason=args.reason)
    verb = f"recorded as r{data['revision']}" if data.get("written") else "unchanged (identical to the latest)"
    return _out(args, data, f"decisions {verb} by {data['reviewer']}")


for _leaf, _fn in (("rebase inspect", _inspect), ("rebase prepare", _prepare), ("rebase show", _show),
                   ("rebase propose", _propose), ("rebase repair", _repair), ("rebase decide", _decide)):
    DELTA_HANDLERS[_leaf] = _fn
DELTA_HANDLERS.setdefault("rebind", _stub)
