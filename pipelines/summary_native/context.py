"""Assemble the system and user prompts for one synthesis call (R9, R10).

String concatenation only. No model call, no ``campaignlib.api`` import, no
retrieval: the corpus is the human-reviewed summaries read from disk, and what
reaches the prompt is chosen by ``select`` and by the flags the GM passed.
Identical inputs give byte-identical prompts.
"""

from __future__ import annotations

from pathlib import Path

from pipelines.summary_native.select import Selection

PROMPT_DIR = Path(__file__).parent / "prompts"
AUDIT_LABEL = "AUDIT QUESTIONS — NOT EVIDENCE"


def load_system_prompt(doc: str) -> str:
    return (PROMPT_DIR / f"{doc}.system.md").read_text(encoding="utf-8").strip()


def _shown(path: Path, root: Path | None) -> str:
    p = Path(path)
    if root is not None:
        try:
            return p.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def _outline_instruction(headings: list[str], part_headings: list[str] | None) -> str:
    if part_headings is None:
        return (
            "Output format: emit exactly these H2 headings, in this order, each followed by a "
            "non-empty body, and no other H2 headings. Begin with the first heading; write no "
            "preamble and no closing commentary.\n\n" + "\n".join(headings)
        )
    return (
        "Output format: this document is written in parts. The full outline is:\n\n"
        + "\n".join(headings)
        + "\n\nIn this call write ONLY these headings, in this order, each followed by a "
        "non-empty body, and nothing else. Begin with the first of them; write no preamble "
        "and no closing commentary.\n\n" + "\n".join(part_headings)
    )


def build_context(
    doc: str,
    range_dir: Path,
    selection: Selection,
    upstream: dict[str, Path],
    audit: list[Path],
    part_headings: list[str] | None,
    *,
    headings: list[str],
    range_since: int,
    root: Path | None = None,
) -> tuple[str, str]:
    """Return ``(system, user)``. ``headings`` is the document's full outline."""
    range_dir = Path(range_dir)
    system = load_system_prompt(doc) + "\n\n" + _outline_instruction(headings, part_headings) + "\n"

    blocks: list[str] = [
        f"RANGE: chapters {range_since}-{selection.range_end} "
        f"(selection: recent {selection.recent_chapters} chapters, recurring >= {selection.recurring_min})"
    ]
    blocks.append(
        "=== CHRONOLOGY ===\n" + (range_dir / "chronology.md").read_text(encoding="utf-8").rstrip()
    )
    blocks.append(
        "=== MEMORABLE MOMENTS ===\n"
        + (range_dir / "memorable_moments.md").read_text(encoding="utf-8").rstrip()
    )
    dossier_blocks = [
        f"--- DOSSIER: {i.dossier.stem} (selected: {i.reason}; last chapter {i.dossier.last_chapter}; "
        f"{i.dossier.n_observations} observations) ---\n"
        + i.dossier.path.read_text(encoding="utf-8").rstrip()
        for i in selection.items
    ]
    blocks.append("=== ENTITY DOSSIERS ===\n" + ("\n\n".join(dossier_blocks) or "(none selected)"))
    for name in sorted(upstream):
        path = Path(upstream[name])
        blocks.append(
            f"=== UPSTREAM DRAFT (GM-reviewed): {name} — {_shown(path, root)} ===\n"
            + path.read_text(encoding="utf-8").rstrip()
        )
    if audit:
        files = [
            f"--- {_shown(Path(p), root)} ---\n" + Path(p).read_text(encoding="utf-8").rstrip()
            for p in audit
        ]
        blocks.append(
            f"=== {AUDIT_LABEL} ===\n"
            "These files are questions to check against the summaries above. Nothing in them "
            "is evidence that it happened.\n"
            "`````text\n" + "\n\n".join(files) + "\n`````"
        )
    return system, "\n\n".join(blocks) + "\n"
