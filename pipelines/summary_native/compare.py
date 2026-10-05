"""Draft-versus-live comparison (FR-026, research R12). Reads two files; no model."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_CHAPTER_RE = re.compile(r"(?i)\bch(?:apter)?\.?\s*(\d+)")


@dataclass(frozen=True)
class Side:
    label: str
    bytes: int
    lines: int
    highest_chapter: int | None  # a heuristic: the largest "ch N" / "Chapter N" mention


@dataclass(frozen=True)
class CompareReport:
    draft: Side
    live: Side
    diff: str

    def to_text(self) -> str:
        rows = [f"{'':8}{'bytes':>10}{'lines':>8}  highest chapter (heuristic)"]
        for s in (self.draft, self.live):
            hc = "none found" if s.highest_chapter is None else str(s.highest_chapter)
            rows.append(f"{s.label:8}{s.bytes:>10}{s.lines:>8}  {hc}")
        return "\n".join(rows) + "\n"


def _side(label: str, text: str) -> Side:
    nums = [int(n) for n in _CHAPTER_RE.findall(text)]
    return Side(label, len(text.encode("utf-8")), len(text.splitlines()), max(nums) if nums else None)


def compare(draft: str, live: str, draft_name: str = "draft", live_name: str = "live") -> CompareReport:
    """``live`` is the diff's 'a' side, ``draft`` its 'b' side."""
    diff = "".join(
        difflib.unified_diff(
            live.splitlines(keepends=True),
            draft.splitlines(keepends=True),
            fromfile=f"a/{live_name}",
            tofile=f"b/{draft_name}",
        )
    )
    return CompareReport(_side("draft", draft), _side("live", live), diff)
