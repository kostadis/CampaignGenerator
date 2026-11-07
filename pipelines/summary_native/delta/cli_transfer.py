"""Handlers for ``delta transfer verify|bind`` (T081, US5)."""

from __future__ import annotations

from pathlib import Path

from . import transfer as transfer_mod
from .cli import DELTA_HANDLERS
from .cli_plan import campaign_root, emit, guarded
from .errors import EXIT_USAGE, DeltaRefusal


def _canonical(args) -> Path:
    if not getattr(args, "canonical", None):
        raise DeltaRefusal("--canonical DIR is required (the campaign the worktree was copied from)", EXIT_USAGE)
    return Path(args.canonical)


@guarded
def _verify(args) -> int:
    v = transfer_mod.verify(_canonical(args), campaign_root(args))
    return emit(args, {"verified": True, **v.to_dict()},
                f"verified: {v.worktree_root} carries campaign {v.campaign_id} (canonical {v.canonical_root})")


@guarded
def _bind(args) -> int:
    path = transfer_mod.bind(_canonical(args), campaign_root(args))
    return emit(args, {"bound": True, "binding": str(path)}, f"bound: {path}")


DELTA_HANDLERS["transfer verify"] = _verify
DELTA_HANDLERS["transfer bind"] = _bind
