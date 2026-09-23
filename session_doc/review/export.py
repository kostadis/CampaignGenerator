"""Build a scene export from a narration and its extraction (#455).

Deterministic, no model call. Two inputs:

- the **narration** `sd_narrate` wrote, with its gap markers — parsed into blocks
- the scene **extraction** it was written from — read for the GM's own turns,
  which the reviewer shows at the foot so a gap is ruled against the source
  rather than from memory
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from campaignlib.textproc import split_frontmatter
from session_doc.blocks import parse_blocks
from session_doc.review.schema import ExportBlock, SceneExport, SourceTurn

#: A speaker label opening a line, in any of the conventions the corpus uses:
#: ``**GM**``, ``**[GM]**``, ``**[GM, as the banker]**``, ``**[GM / Brewbarry]**``.
#: Read verbatim; deciding whether a label names the GM is the next line's job,
#: for the reason `session_doc/plan_eligibility.py` gives at length (#453).
_LABEL = re.compile(r"(?m)^\*\*([^*]+?)\*\*(.*)$")

#: A quoted line beneath a label.
_QUOTE = re.compile(r"(?m)^>\s*(.*)$")

#: Whether a label names the game master. Folded containment on a word boundary
#: rather than equality, because the label may be qualified (``GM, as the
#: banker``) or joint (``GM / Brewbarry``) — this is a **display** filter for a
#: reference table, and it asserts nothing about who spoke.
_NAMES_GM = re.compile(r"\b(GM|DM)\b", re.IGNORECASE)


def digest(text: str) -> str:
    """The identity of the draft a review was made against."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_source_gm_turns(extraction: str) -> list[SourceTurn]:
    """Every GM turn in a scene extraction, with its line, note and quote.

    Line numbers are 1-based and refer to the extraction file, so a GM reading
    the table on a phone can find the turn in the source afterwards.
    """
    lines = extraction.splitlines()
    turns: list[SourceTurn] = []
    for i, line in enumerate(lines, start=1):
        m = _LABEL.match(line)
        if not m:
            continue
        label, tail = m.group(1).strip(), m.group(2).strip()
        if not _NAMES_GM.search(label):
            continue
        note = tail.strip(" —-").strip("*").strip()
        quote = ""
        for follow in lines[i:i + 3]:
            q = _QUOTE.match(follow)
            if q:
                quote = q.group(1).strip()
                break
            if follow.strip() and not follow.startswith(">"):
                break
        turns.append(SourceTurn(line=i, label=label, note=note, quote=quote))
    return turns


def build_export(
    *,
    narration_path: Path,
    narration_text: str,
    extraction_text: str = "",
    session: str = "",
) -> SceneExport:
    """One scene, ready for the reviewer.

    ``scene_index``, ``scene_name`` and ``narrator`` come from the narration's
    own frontmatter — the same values `assemble` reads — so the reviewer names a
    scene the way the rest of the pipeline does.
    """
    meta, body = split_frontmatter(narration_text)
    blocks = parse_blocks(body)
    turns = read_source_gm_turns(extraction_text) if extraction_text else []

    try:
        index = int(str(meta.get("scene", "0")).strip())
    except ValueError:
        index = 0

    return SceneExport(
        narration=narration_path.name,
        generated_sha256=digest(narration_text),
        session=session or str(meta.get("session", "")),
        scene_index=index,
        scene_name=str(meta.get("scene_name", "") or meta.get("slug", "")),
        narrator=str(meta.get("narrator", "")),
        word_count=len(body.split()),
        gap_count=sum(1 for b in blocks if b.is_gap),
        gm_turn_count=len(turns),
        blocks=[ExportBlock(id=b.id, kind=b.kind, anchor=b.anchor, text=b.text)
                for b in blocks],
        source_gm_turns=turns,
    )
