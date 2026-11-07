"""``summary_native delta`` — the parser family and the handler seam.

Every leaf shares one flag spelling (Principle XII): ``--campaign-dir``, ``--config``, ``--json``,
``--force`` and a repeatable ``--source`` with no default (Principle X: there is no ``--all`` anywhere
in this family, and an empty selection is a usage error, exit 2).

Handler seam for later tasks: ``DELTA_HANDLERS`` maps a leaf name (``"plan"``, ``"baseline adopt"``,
``"npc publish"`` ...) to ``handler(args) -> int``. A task replaces a stub by assigning
``DELTA_HANDLERS["<leaf>"] = fn`` (in this module, or from its own module imported here). A leaf
with no entry falls back to ``_not_implemented``, which exits 2.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from campaignlib.selection import BACKENDS

PRODUCTS = ("grounding", "npc")
STOP_STAGES = ("plan", "prepare", "propose", "verify", "review", "preview", "apply")
DECISIONS = ("approve", "reject", "discuss")

#: The complete leaf set, as the space-joined path under ``delta``.
LEAVES: tuple[str, ...] = (
    "plan", "sources", "baseline status", "baseline adopt", "census",
    "associate propose", "associate decide",
    "npc draft", "npc verify", "npc attest", "npc publish",
    "grounding propose", "grounding decide", "grounding check", "grounding preview", "grounding apply",
    "run status", "run resume", "receipt",
    "review show", "review handoff", "transfer verify", "transfer bind",
)

DeltaHandler = Callable[[argparse.Namespace], int]
DELTA_HANDLERS: dict[str, DeltaHandler] = {}


def _not_implemented(args: argparse.Namespace) -> int:
    print(f"Error: summary_native delta {args.delta_leaf}: not implemented", file=sys.stderr)
    return 2


def _shared(p: argparse.ArgumentParser) -> None:
    p.add_argument("--campaign-dir", default=None, metavar="DIR", help="campaign root (default: cwd)")
    p.add_argument("--config", default=None, metavar="PATH")
    p.add_argument("--json", action="store_true", help="emit machine-readable output on stdout")
    p.add_argument("--force", action="store_true", help="overwrite only what is already there")
    p.add_argument("--source", action="append", default=None, metavar="PATH",
                   help="a source to include; repeatable, never defaulted (an empty selection is an error)")


def _plan_id(p: argparse.ArgumentParser) -> None:
    p.add_argument("--plan", default=None, metavar="ID")


def _model(p: argparse.ArgumentParser) -> None:
    _plan_id(p)
    p.add_argument("--backend", choices=BACKENDS, default=None)
    p.add_argument("--model", default=None)


def _decide(p: argparse.ArgumentParser, positional: str) -> None:
    p.add_argument(positional, metavar=positional.upper())
    p.add_argument("--decision", choices=DECISIONS, required=True)  # no default: there is no default approval
    p.add_argument("--reason", default=None)


def _extras(leaf: str, p: argparse.ArgumentParser) -> None:
    if leaf == "plan":
        p.add_argument("--product", action="append", choices=PRODUCTS, default=None)
        p.add_argument("--stop", choices=STOP_STAGES, default=None)
        p.add_argument("--backend", choices=BACKENDS, default=None)
        p.add_argument("--model", default=None)
    elif leaf == "baseline adopt":
        _plan_id(p)
        p.add_argument("--resolve", action="append", default=None, metavar="HUNK=accept|reject")
    elif leaf in ("associate propose", "npc draft", "grounding propose", "grounding check"):
        _model(p)
        if leaf == "npc draft":
            p.add_argument("--audience", choices=("gm", "player"), default="gm",
                           help="who the draft is for; anything but gm is refused (NPC evidence is GM-only)")
            p.add_argument("--allow-historical-parse", action="store_true",
                           help="when a baseline kept no evidence pack, read the historical chapters its draft "
                                "cites (recorded; counted as parsed_historical). Refused by default (SC-001)")
    elif leaf == "associate decide":
        _plan_id(p)
        _decide(p, "id")
        p.add_argument("--reviewer", default=None, metavar="NAME",
                       help="who is deciding; required (exit 2 without it), never defaulted to the login name")
    elif leaf == "grounding decide":
        _plan_id(p)
        _decide(p, "proposal_id")
        p.add_argument("--reviewer", default=None, metavar="NAME",
                       help="who is deciding; required (exit 2 without it), recorded in the decision file")
    elif leaf == "npc attest":
        _plan_id(p)
        p.add_argument("subject", metavar="SUBJECT")
        p.add_argument("--reason", required=True)
        p.add_argument("--publication", required=True, metavar="SHA")
    elif leaf == "npc publish":
        _plan_id(p)
        p.add_argument("--member", action="append", default=None, metavar="SUBJECT",
                       help="a member to publish; repeatable and explicit (there is no 'all')")
        p.add_argument("--preview-sha", default=None, metavar="SHA")
    elif leaf == "grounding preview":
        _plan_id(p)
        p.add_argument("--review", default=None, metavar="ID",
                       help="the document-review id whose four sign-offs authorise the publication")
        p.add_argument("--claims-report", default=None, metavar="REF",
                       help="the persisted claims report the promotion gate needs")
        p.add_argument("--request-id", default=None, metavar="ID")
    elif leaf == "grounding apply":
        _plan_id(p)
        p.add_argument("--preview-sha", default=None, metavar="SHA")
    elif leaf in ("transfer verify", "transfer bind"):
        _plan_id(p)
        p.add_argument("--canonical", default=None, metavar="DIR",
                       help="the canonical campaign this worktree or artifact copy was taken from")
    else:
        _plan_id(p)


def add_delta_parser(sub) -> argparse.ArgumentParser:
    """Register ``delta`` on the top-level subparsers; returns the ``delta`` parser."""
    delta = sub.add_parser("delta", help="incremental campaign grounding and NPC updates")
    dsub = delta.add_subparsers(dest="delta_group", required=True, metavar="COMMAND")
    groups: dict[str, argparse._SubParsersAction] = {}
    for leaf in LEAVES:
        parts = leaf.split(" ")
        if len(parts) == 1:
            p = dsub.add_parser(parts[0])
        else:
            if parts[0] not in groups:
                gp = dsub.add_parser(parts[0])
                groups[parts[0]] = gp.add_subparsers(dest="delta_sub", required=True, metavar="SUBCOMMAND")
            p = groups[parts[0]].add_parser(parts[1])
        p.set_defaults(delta_leaf=leaf)
        _shared(p)
        _extras(leaf, p)
    return delta


#: Handler modules, one per story, each registering its leaves into ``DELTA_HANDLERS`` on import.
#: Kept separate so the grounding (US1), NPC (US2), review (US3), run (US4) and transfer (US5) verbs
#: do not share one file.
HANDLER_MODULES: tuple[str, ...] = (
    "pipelines.summary_native.delta.cli_plan",
    "pipelines.summary_native.delta.cli_grounding",
    "pipelines.summary_native.delta.cli_grounding_publish",
    "pipelines.summary_native.delta.cli_npc",
    "pipelines.summary_native.delta.cli_npc_publish",
    "pipelines.summary_native.delta.cli_review",
    "pipelines.summary_native.delta.cli_run",
    "pipelines.summary_native.delta.cli_transfer",
)


def load_handlers() -> None:
    """Import every handler module that exists; a module that is absent leaves its leaves as stubs."""
    import importlib
    import importlib.util

    for name in HANDLER_MODULES:
        if importlib.util.find_spec(name) is not None:
            importlib.import_module(name)


def run(args: argparse.Namespace) -> int:
    load_handlers()
    return DELTA_HANDLERS.get(args.delta_leaf, _not_implemented)(args)
