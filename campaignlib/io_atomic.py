"""Atomic file writes for callers that may race a duplicate process on the
same destination path.

This is a distinct helper from ``campaignlib.util.atomic_write_text`` (which
uses a fixed ``.tmp`` suffix): that one is safe against a single writer being
killed mid-write, but two processes racing on the *same* fixed tmp name could
still interleave writes into it before the loser's rename. The PID suffix
here keeps concurrent writers' tmp files from colliding at all, so the race
is fully resolved at the (atomic) rename step instead. Not merged with
``campaignlib.util.atomic_write_text`` — same name, incompatible on-disk
behavior, and existing call sites there depend on its fixed-suffix + mkdir
semantics.
"""

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write via tmp + os.replace so a kill mid-write never leaves a torn file.

    The ensemble's speculative re-execution runs a duplicate of the same unit
    in another process sharing this cache dir, and terminates the loser — the
    PID suffix keeps the tmp names from colliding, and the rename makes the
    loser's death harmless (last writer wins, both wrote the same chunk).
    """
    path = Path(path)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
