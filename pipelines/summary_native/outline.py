"""Model-free grounding-document outline validation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).parent / "prompts"


def load_outline(doc: str) -> list[str]:
    path = PROMPT_DIR / f"{doc}.outline.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [str(heading) for heading in data["headings"]]


def check_outline(text: str, headings: list[str]) -> list[str]:
    """Return deterministic outline problems; an empty list means complete."""
    lines = text.splitlines()
    wanted = {heading.strip(): index for index, heading in enumerate(headings)}
    at: dict[str, int] = {}
    problems: list[str] = []
    for number, line in enumerate(lines):
        if line.startswith("## ") and line.rstrip() in wanted and line.rstrip() not in at:
            at[line.rstrip()] = number
    first = min(at.values()) if at else len(lines)
    preamble = "\n".join(lines[:first]).strip()
    preamble = re.sub(r"\A(?:<!--.*?-->\s*)+", "", preamble, flags=re.S).strip()
    if preamble and not re.fullmatch(r"(?:>[^\n]*(?:\n|$))+", preamble):
        problems.append("text before the first heading (no preamble allowed)")
    for heading in headings:
        if heading not in at:
            problems.append(f"missing heading: {heading}")
    present = [heading for heading in headings if heading in at]
    positions = [at[heading] for heading in present]
    if positions != sorted(positions):
        problems.append("headings out of order (expected: " + " | ".join(present) + ")")
    h2_lines = sorted(number for number, line in enumerate(lines) if line.startswith("## "))
    for number in h2_lines:
        if lines[number].rstrip() not in wanted:
            problems.append(f"unexpected heading: {lines[number].rstrip()}")
    for heading in present:
        start = at[heading]
        end = next((number for number in h2_lines if number > start), len(lines))
        if not "\n".join(lines[start + 1 : end]).strip():
            problems.append(f"empty body: {heading}")
    return problems
