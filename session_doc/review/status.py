"""What state a scene's review is in — one row per narration (#455).

Read-only, no model call. Exists so a phone can ask "what is left?" without the
GM reading four files per scene, and so the gap-review skill has an engine to
call rather than reimplementing the arithmetic in prose (Principle VI).
"""

from __future__ import annotations

from pathlib import Path

from campaignlib.textproc import split_frontmatter
from session_doc.authored import AuthoredError, load_record_for, record_path
from session_doc.blocks import parse_blocks
from session_doc.review.export import digest


def scene_status(narration: Path) -> dict:
    text = narration.read_text(encoding="utf-8")
    _meta, body = split_frontmatter(text)
    gaps = [b for b in parse_blocks(body) if b.is_gap]

    try:
        record = load_record_for(narration)
        broken = False
    except AuthoredError:
        record, broken = None, True

    entries = record.by_id() if record else {}
    ruled = sum(1 for g in gaps if g.id in entries and entries[g.id].disposition)
    written = sum(1 for g in gaps if g.id in entries
                  and entries[g.id].disposition in ("authored", "cut"))
    composed = narration.with_name(narration.stem + ".composed.md")
    return {
        "scene": narration.stem,
        "narration": narration.name,
        "gaps": len(gaps),
        "ruled": ruled,
        "written": written,
        "outstanding": [g.id for g in gaps
                        if g.id not in entries
                        or entries[g.id].disposition not in ("authored", "cut")],
        "record": record_path(narration).name if record else None,
        "record_unreadable": broken,
        # A review made against a draft that has since changed. `sd_compose`
        # refuses this, so it is worth surfacing before the GM writes more.
        "stale": bool(record and record.generated_sha256 != digest(text)),
        "composed": composed.is_file(),
    }
