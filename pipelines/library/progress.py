"""Live progress lines for long library runs (stderr, never stdout).

``library: HH:MM:SS <message>``, flushed. Silenced with ``set_quiet(True)``
(``--quiet``). stdout is reserved for the report / ``--json``.
"""

from __future__ import annotations

import sys
import time

_quiet = False


def set_quiet(quiet: bool) -> None:
    global _quiet
    _quiet = bool(quiet)


def log(msg: str) -> None:
    if _quiet:
        return
    print(f"library: {time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)
