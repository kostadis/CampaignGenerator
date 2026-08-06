"""The backend roster: what could have answered, and what actually did.

Story 3's whole complaint is that **an uninstalled backend and a backend that
found nothing are indistinguishable**. A caller who gets zero hits has to decide
whether to widen the query or go install something, and today the tool tells
them nothing either way.

So every search response and ``provenance capabilities`` carry a roster: each
backend's status, *why* if it is unavailable, and whether it contributed to the
result the caller is holding. The probe runs for real, per machine — it reads
``available`` on the WSL2 desktop where MemPalace is installed and ``unavailable``
here, and that difference is the point (research D15).

The ``literal`` backend reports its own guts for the same reason. It has two
interchangeable implementations with a ~60× latency difference, and which one
runs depends on whether ``rg`` resolves in the spawning process's ``PATH``. An
unreported swing that varies by host is exactly the tribal per-machine state
Principle VIII exists to eliminate (research D1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .scan import ScannerImpl, available_scanners

#: Where MemPalace keeps its palaces. Probed, never created.
PALACE_DIR = Path.home() / ".mempalace" / "palaces"


class BackendStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_WIRED = "not-wired"


@dataclass(frozen=True)
class Backend:
    """One retrieval backend, honestly described."""

    name: str
    status: BackendStatus
    reason: str | None = None
    contributed: str = "no"
    impl: str | None = None
    impl_version: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "contributed": self.contributed,
            "impl": self.impl,
            "impl_version": self.impl_version,
        }


def literal_backend(impl: ScannerImpl | None = None, *, contributed: bool = True) -> Backend:
    """Always available: rg when discoverable, the stdlib scanner otherwise."""
    fallbacks = ", ".join(n for n in available_scanners() if impl is None or n != impl.name)
    reason = f"other implementation(s) available: {fallbacks}" if fallbacks else None
    return Backend(
        name="literal",
        status=BackendStatus.AVAILABLE,
        reason=reason,
        contributed="yes" if contributed else "not-consulted",
        impl=impl.name if impl else None,
        impl_version=impl.version if impl else None,
    )


def semantic_backend() -> Backend:
    """Probed for real, so the answer is truthful on *this* host.

    Two independent reasons it can be unavailable, reported separately: the
    package may not import, or it may import with no palace to search. Both are
    "unavailable", and a caller deciding whether to go install something needs
    to know which one they are looking at.
    """
    try:  # the guarded-import pattern already used at pipelines/rlm/mcp_server.py
        import mempalace.searcher  # noqa: F401

        importable = True
    except Exception:  # ImportError, or a broken install raising something else
        importable = False

    if not importable:
        return Backend(
            name="semantic",
            status=BackendStatus.UNAVAILABLE,
            reason="mempalace is not importable on this host",
            contributed="not-consulted (semantic backend not wired in increment 1)",
        )

    if not PALACE_DIR.is_dir() or not any(PALACE_DIR.iterdir()):
        return Backend(
            name="semantic",
            status=BackendStatus.UNAVAILABLE,
            reason=f"mempalace imports, but {PALACE_DIR} holds no palace",
            contributed="not-consulted (semantic backend not wired in increment 1)",
        )

    # Installed and populated — and still not consulted, which is a different
    # sentence from "unavailable" and must not be written as one.
    return Backend(
        name="semantic",
        status=BackendStatus.NOT_WIRED,
        reason="installed and populated, but this increment issues no semantic query",
        contributed="not-consulted (semantic backend not wired in increment 1)",
    )


def roster(impl: ScannerImpl | None = None, *, contributed: bool = True) -> tuple[Backend, ...]:
    """The full roster, repeated on every response so no result looks complete."""
    return (literal_backend(impl, contributed=contributed), semantic_backend())
