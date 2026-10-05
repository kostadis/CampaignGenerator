"""Assemble the system and user prompts for one synthesis call (R9, R10).

String concatenation only. No model call, no ``campaignlib.api`` import, no
retrieval: the corpus is the human-reviewed summaries read from disk, and what
reaches the prompt is chosen by ``select`` and by the flags the GM passed.
Identical inputs give byte-identical prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from campaignlib.party_config import load_party_config, resolve_party_config
from campaignlib.planning_config import load_planning_config, resolve_entries
from pipelines.summary_native.select import Selection

PROMPT_DIR = Path(__file__).parent / "prompts"
AUDIT_LABEL = "AUDIT QUESTIONS — NOT EVIDENCE"
#: The one line a Threat Tracker may hold when no arc score is configured. The
#: planning prompt states it and ``synth`` checks for it, so it is declared once.
NO_ARC_SENTINEL = "_No arc scores configured._"


class DocConfigError(Exception):
    """A party/planning config that cannot be used (CLI exit 2)."""


@dataclass(frozen=True)
class DocConfig:
    """A rendered config block plus what the run record and post-check need."""

    block: str
    path: Path | None = None
    arc_scores: int = 0
    files: tuple[Path, ...] = field(default_factory=tuple)


def _read(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8").rstrip()


def party_config_block(path: Path, root: Path) -> DocConfig:
    """The resolved party roster with each sheet and backstory, labelled by path."""
    path = Path(path)
    # Not load_party_config_arg: it prints its own warning, and the refusal below
    # is the one line the GM should see.
    path = path.expanduser()
    if not path.is_file():
        raise DocConfigError(f"--party-config {_shown(path, root)}: not found")
    try:
        resolved = resolve_party_config(load_party_config(path), Path(root), require_files=False)
    except ValueError as e:
        raise DocConfigError(f"--party-config {_shown(path, root)}: unreadable ({e})") from e
    if not resolved.characters:
        raise DocConfigError(f"--party-config {_shown(path, root)}: no characters declared")
    out = [f"=== PARTY CONFIG — {_shown(path, root)} ===\n"
           "The GM's roster. Sheets and backstories are reference material, not a record of play."]
    files: list[Path] = [path]
    for pc in resolved.characters:
        if pc.trackless:
            arc = "trackless (no arc score by design)"
        elif pc.arc_score:
            arc = f"arc score mechanic: {_shown(pc.arc_score, root)}"
        else:
            arc = "no arc score declared"
        parts = [f"### {pc.name}", f"arc score: {arc}"]
        for label, p in (("SHEET", pc.sheet), ("BACKSTORY", pc.backstory), ("ARC SCORE MECHANIC", pc.arc_score)):
            if p is None:
                continue
            if not p.is_file():
                raise DocConfigError(f"party config: {pc.name} {label.lower()} file missing: {_shown(p, root)}")
            files.append(p)
            parts.append(f"--- {label} ({_shown(p, root)}) ---\n{_read(p)}")
        out.append("\n".join(parts))
    return DocConfig("\n\n".join(out), path, 0, tuple(files))


def planning_config_block(path: Path | None, root: Path, *, explicit: bool) -> DocConfig:
    """Tracked NPCs/factions and their arc scores. An absent default file means none configured."""
    cfg = None
    if path is not None and Path(path).is_file():
        try:
            cfg = load_planning_config(Path(path))
            entries = resolve_entries(cfg.npcs, Path(root), require_files=False) + resolve_entries(
                cfg.factions, Path(root), require_files=False
            )
        except ValueError as e:
            raise DocConfigError(f"--planning-config {_shown(path, root)}: {e}") from e
    elif explicit:
        raise DocConfigError(f"--planning-config {path}: no such file")
    if cfg is None:
        shown = "(no planning config)"
        npcs, factions = [], []
        entries = []
    else:
        shown = _shown(Path(path), root)
        npcs, factions = entries[: len(cfg.npcs)], entries[len(cfg.npcs):]
    scored = [e for e in entries if e.arc_score is not None]
    files: list[Path] = [Path(path)] if cfg is not None else []

    def render(kind: str, group) -> str:
        if not group:
            return f"{kind}: none configured"
        chunks = []
        for e in group:
            lines = [f"### {e.name}"]
            lines.append(
                "arc score: trackless (no arc score by design)" if e.trackless
                else f"arc score mechanic: {_shown(e.arc_score, root)}" if e.arc_score
                else "arc score: none"
            )
            if e.dossier is not None:
                lines.append(f"configured dossier: {_shown(e.dossier, root)} (named by the GM; not supplied as evidence)")
            if e.arc_score is not None:
                if not e.arc_score.is_file():
                    raise DocConfigError(f"planning config: {e.name} arc score file missing: {_shown(e.arc_score, root)}")
                files.append(e.arc_score)
                lines.append(f"--- ARC SCORE MECHANIC ({_shown(e.arc_score, root)}) ---\n{_read(e.arc_score)}")
            chunks.append("\n".join(lines))
        return f"{kind}:\n\n" + "\n\n".join(chunks)

    head = f"=== PLANNING CONFIG — {shown} ===\nThe GM's tracked entities. This says what to track, not what happened."
    body = [head, render("NPCs", npcs), render("FACTIONS", factions)]
    if scored:
        body.append(f"Arc scores configured: {len(scored)}. List them, and only them, in the Threat Tracker.")
    else:
        body.append(
            "No arc scores are configured — leave the Threat Tracker section with the single line: "
            f"{NO_ARC_SENTINEL}"
        )
    return DocConfig("\n\n".join(body), Path(path) if cfg is not None else None, len(scored), tuple(files))


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
    config_block: str | None = None,
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
    if config_block:
        blocks.append(config_block)
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
