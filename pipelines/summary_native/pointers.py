"""Validate the reading contract after a draft bundle is copied. No model call or writes."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pipelines.summary_native import schema

_CONTRACT_PATHS = re.compile(r'^> <!-- summary_native pointers: (.+) -->$', re.M)
#: The two lines of a reading contract that name files (``state_sections.reading_contract``): the reference
#: files the document points to, and, for world_state only, the timeline. Each document lists its own.
_REFERENCE_LINE = re.compile(r'^> - Every checked note, by subject: (.+)$', re.M)
_TIMELINE_LINE = re.compile(r'^>\s+Every event, in order: `([^`]+)`', re.M)
_BACKTICKED = re.compile(r'`([^`]+)`')
_DOSSIER = re.compile(r'→ (docs/npcs/[a-z0-9-]+\.md)')


def check_paths(document: Path, campaign: Path) -> list[str]:
    """Report every unresolved contract path. References travel beside the document;
    summaries and published dossiers remain rooted in the campaign (or at an absolute path).
    Older drafts without the machine-readable contract must be regenerated before checking.

    Only the files the document's own reading contract names are required: world_state lists six reference
    files and the timeline, planning three reference files, party one, campaign_state one; a promoted party
    or planning bundle does not carry the files it never pointed to.
    """
    document, campaign = Path(document), Path(campaign)
    try:
        text = document.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read {document}: {exc}"]
    contracts = _CONTRACT_PATHS.findall(text)
    if len(contracts) != 1:
        return ["expected one reading-contract path record; regenerate the document with summary_native synth"]
    try:
        paths = json.loads(contracts[0])
        if not isinstance(paths, dict) or any(not isinstance(paths.get(k), str) or not paths[k]
                                              for k in ("reference", "timeline", "summaries")):
            raise ValueError("expected reference, timeline and summaries paths")
    except ValueError as exc:
        return [f"invalid reading-contract paths: {exc}"]
    listed = _REFERENCE_LINE.search(text)
    if listed is None:
        return ["the reading contract lists no reference files; regenerate the document with summary_native synth"]
    required = [document.parent / name for name in _BACKTICKED.findall(listed.group(1))]
    timeline = _TIMELINE_LINE.search(text)
    if timeline is not None:
        required.append(document.parent / timeline.group(1))
    required.extend(campaign / p for p in sorted(set(_DOSSIER.findall(text))))
    problems = [f"missing file: {p}" for p in required if not p.is_file()]
    summaries = campaign / paths["summaries"]
    if not summaries.is_dir():
        problems.append(f"missing summaries directory: {summaries}")
    else:
        present = {int(m.group(1)) for p in summaries.glob("*.md")
                   if (m := schema.PREFIX_RE.match(p.name))}
        cited = {int(n) for n in re.findall(r'\bch (\d{3}) / ', text)}
        for chapter in sorted(cited - present):
            problems.append(f"missing chapter {chapter:03d} summary in: {summaries}")
    return problems
