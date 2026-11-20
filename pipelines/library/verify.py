"""Verify a quoted span appears verbatim in a rendered passage (SC-002).

Whitespace runs are normalised; nothing else is. No LLM.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipelines.library import LibraryError

_WS = re.compile(r"\s+")


def _normalise(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to one space; return (text, index map to original)."""
    out: list[str] = []
    idx: list[int] = []
    for m in re.finditer(r"\s+|\S+", text):
        if m.group().isspace():
            out.append(" ")
            idx.append(m.start())
        else:
            out.append(m.group())
            idx.extend(range(m.start(), m.end()))
    return "".join(out), idx


def verify_citation(work_dir, file: str, quote: str) -> dict:
    root = (Path(work_dir) / "rendered").resolve()
    path = (root / file).resolve()
    if root not in path.parents:
        raise LibraryError(f"{file} is outside the rendered library tree; refusing")
    if not path.is_file():
        return {"file": file, "found": False, "offset": None}
    q = _WS.sub(" ", quote).strip()
    if not q:
        return {"file": file, "found": False, "offset": None}
    text = path.read_text(encoding="utf-8")
    norm, idx = _normalise(text)
    pos = norm.find(q)
    if pos < 0:
        return {"file": file, "found": False, "offset": None}
    return {"file": file, "found": True, "offset": idx[pos]}
