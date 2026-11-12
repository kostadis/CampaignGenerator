"""The one place a ``delta`` leaf turns its resolved backend and parsed CLI options into a client.

Two things the leaves must not lose on the way to :func:`campaignlib.client_from_args` (Principle V):

* **Every accepted flag takes effect.** ``add_backend_args`` registers ``--endpoint``, ``--batch`` and the
  Codex / Claude Code effort and thinking options; a leaf that parses them must hand them on
  (:func:`client_options` collects them, :func:`delta_client` applies them).
* **The backend used is the backend recorded.** ``client_from_args`` maps ``"anthropic"`` to "no backend",
  which lets ``CG_BACKEND`` win; a plan or run record that says ``anthropic`` must mean anthropic
  (the semantics of the ``make_client(backend=...)`` calls this replaced), so :func:`pinned_backend`
  masks the environment variable around the call for an explicit ``anthropic``.
"""

from __future__ import annotations

import contextlib
import os
from types import SimpleNamespace
from typing import Any, Iterator, Mapping

from campaignlib.api.client import client_from_args

#: The attributes ``add_backend_args`` registers beyond ``--backend`` / ``--model``.
OPTION_ATTRS = ("endpoint", "batch", "codex_reasoning_effort", "claude_code_effort", "claude_code_thinking")


def client_options(args: Any) -> dict[str, Any]:
    """The parsed backend options of a leaf's namespace (absent ones are omitted, not defaulted)."""
    return {k: getattr(args, k) for k in OPTION_ATTRS if hasattr(args, k)}


@contextlib.contextmanager
def pinned_backend(backend: str | None) -> Iterator[None]:
    """Make an explicit ``anthropic`` beat ``CG_BACKEND`` for the duration; any other value is untouched."""
    if backend != "anthropic" or "CG_BACKEND" not in os.environ:
        yield
        return
    saved = os.environ.pop("CG_BACKEND")
    try:
        yield
    finally:
        os.environ["CG_BACKEND"] = saved


def delta_client(backend: str | None, model: str | None, options: Mapping[str, Any] | None = None):
    """A client for the backend a plan or run record names, with the leaf's parsed options applied."""
    ns = SimpleNamespace(backend=backend, model=model, **dict(options or {}))
    with pinned_backend(backend):
        return client_from_args(ns)
