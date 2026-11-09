"""Handlers for ``delta rebase ...`` and ``delta rebind`` (spec 040).

Phase 2 registers the leaves with stub handlers so the parser and the HTTP parity check have a stable
surface; each user story replaces its stub (``DELTA_HANDLERS["<leaf>"] = fn``).  No model call is made in
this module except by ``rebase propose``'s real handler.
"""

from __future__ import annotations

import sys

from .cli import DELTA_HANDLERS
from .errors import EXIT_USAGE

REBASE_LEAVES = (
    "rebase inspect", "rebase prepare", "rebase show", "rebase propose", "rebase repair", "rebase decide",
    "rebind",
)


def _stub(args) -> int:
    print(f"Error: summary_native delta {args.delta_leaf}: not implemented yet (spec 040)", file=sys.stderr)
    return EXIT_USAGE


for _leaf in REBASE_LEAVES:
    DELTA_HANDLERS.setdefault(_leaf, _stub)
