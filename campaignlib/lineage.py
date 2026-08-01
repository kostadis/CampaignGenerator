"""Source-lineage ladder for chapter extraction (issue #213, Phase 1).

Per chapter, extraction should read the highest-fidelity artifact that
exists instead of always re-deriving structure from chapter prose — the
lossy round trip issue #199 documents (structure → render → re-extract).

The ladder, as ruled on the #213 design anchor (2026-07-31):

1. **Reviewed scene extractions** — session-editor per-scene files carrying
   GM ``.reviewed`` markers. Human-reviewed and verbatim-bearing: the
   authoritative tier of the trust hierarchy. A scene counts as reviewed if
   its own ``.reviewed`` sidecar exists OR its scaffold's does
   (``NN_slug.scaffold.md.reviewed`` — re-runs delete the main file's
   marker by design, and the scaffold embeds verbatim into the new-format
   file). The chapter qualifies when a **majority** of its scenes are
   reviewed (GM ruling: lenient).
2. **Structured session summary** — ``session-summary.md`` with the
   enhance_summary section layout. One lossy hop from the VTT, but an
   unreviewed LLM pass, so it ranks below reviewed scenes. (This amends the
   anchor's originally-written order, per the same ruling.)
3. **Chapter prose** — always available; the fallback and the pre-Phase-1
   status quo.

Every rung above chapter requires the Phase-0 join: an ``approved: true``
row in ``summary_map.yaml``. No approved row → chapter. The gate defaults
CLOSED — a proposal never routes extraction anywhere.

The decision is deterministic (no LLM) and carries a human-readable
``reason`` so ``ensemble_batch --lineage-report`` can show its work.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib.textproc import split_frontmatter

DEFAULT_MAP = Path("docs/ensemble/summary_map.yaml")
DEFAULT_SUMMARIES = Path("summaries")
# Ordered preference: the session editor writes scene_extractions_new/; older
# sessions used scene_extractions/.
SCENE_DIRS = ("scene_extractions_new", "scene_extractions")
_SCENE_FILE_RE = re.compile(r"^\d+_.+\.md$")


@dataclass
class SourceDecision:
    kind: str                       # "scenes" | "summary" | "chapter"
    inputs: list[Path] = field(default_factory=list)
    session: str | None = None      # YYYYMMDD
    session_dir: Path | None = None
    reason: str = ""

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "inputs": [str(p) for p in self.inputs],
            "session": self.session,
            "reason": self.reason,
        }


def load_approved_rows(map_path: Path) -> dict[str, dict]:
    """Return {chapter filename: row} for approved: true summary_map rows.

    Mirrors summary_map.load_approved's contract: only a human's
    ``approved: true`` opens the gate; anything else — missing file,
    malformed YAML, ``approved: false`` — reads as no row at all.
    """
    if not map_path.exists():
        return {}
    try:
        data = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    out: dict[str, dict] = {}
    for e in data.get("entries") or []:
        if (isinstance(e, dict) and e.get("approved") is True
                and e.get("chapter") and e.get("summary")):
            out[e["chapter"]] = e
    return out


def _scene_files(session_dir: Path) -> list[Path]:
    """Ordered per-scene extraction files, excluding scaffolds and snapshots."""
    for name in SCENE_DIRS:
        d = session_dir / name
        if not d.is_dir():
            continue
        files = sorted(
            p for p in d.iterdir()
            if _SCENE_FILE_RE.match(p.name)
            and not p.name.endswith(".scaffold.md")
            and not p.name.endswith(".prev")
        )
        if files:
            return files
    return []


def _scene_reviewed(path: Path) -> bool:
    """A scene counts as reviewed via its own marker or its scaffold's."""
    if path.with_name(path.name + ".reviewed").exists():
        return True
    scaffold_marker = path.with_name(path.name[:-3] + ".scaffold.md.reviewed")
    return scaffold_marker.exists()


def _summary_is_structured(summary_path: Path) -> bool:
    """The enhance_summary layout: ## Scenes and ## NPCs sections present."""
    if not summary_path.is_file():
        return False
    text = summary_path.read_text(encoding="utf-8")
    return (re.search(r"(?m)^##\s+Scenes\b", text) is not None
            and re.search(r"(?m)^##\s+NPCs\b", text) is not None)


def resolve_source(chapter_path: Path, campaign_dir: Path,
                   map_path: Path | None = None,
                   summaries_dir: Path | None = None) -> SourceDecision:
    """Walk the ladder for one chapter. Deterministic; no LLM."""
    map_path = map_path if map_path is not None else campaign_dir / DEFAULT_MAP
    rows = load_approved_rows(map_path)
    row = rows.get(chapter_path.name)
    if row is None:
        return SourceDecision(
            kind="chapter", inputs=[chapter_path],
            reason="no approved session join in summary_map",
        )

    session_dir = campaign_dir / str(row["summary"])
    if summaries_dir is not None:
        # Override root: keep the date component of the mapped summary id.
        session_dir = summaries_dir / Path(str(row["summary"])).name
    session = re.sub(r"[^0-9]", "", str(row.get("summary_date") or session_dir.name))
    session = session if re.fullmatch(r"\d{8}", session) else None
    if not session_dir.is_dir():
        return SourceDecision(
            kind="chapter", inputs=[chapter_path], session=session,
            reason=f"approved join but session dir missing: {session_dir}",
        )

    scenes = _scene_files(session_dir)
    if scenes:
        reviewed = sum(1 for p in scenes if _scene_reviewed(p))
        if reviewed * 2 > len(scenes):
            return SourceDecision(
                kind="scenes", inputs=scenes, session=session,
                session_dir=session_dir,
                reason=f"{reviewed}/{len(scenes)} scenes reviewed (majority)",
            )
        scene_note = f"{reviewed}/{len(scenes)} scenes reviewed (no majority)"
    else:
        scene_note = "no scene extractions"

    summary_path = session_dir / "session-summary.md"
    if _summary_is_structured(summary_path):
        return SourceDecision(
            kind="summary", inputs=[summary_path], session=session,
            session_dir=session_dir,
            reason=f"{scene_note}; structured session-summary",
        )

    return SourceDecision(
        kind="chapter", inputs=[chapter_path], session=session,
        session_dir=session_dir,
        reason=f"{scene_note}; no structured session-summary",
    )


def compose_scenes(files: list[Path], dest: Path) -> Path:
    """Concatenate per-scene extraction files into one extraction input.

    Each file's own YAML frontmatter is stripped — it is scene metadata,
    not scene content, and a mid-document ``---`` block would otherwise
    leak into extraction as prose (the Phase-0 principle applied per part).
    Deterministic; byte-stable for unchanged inputs.
    """
    parts = []
    for p in files:
        _, body = split_frontmatter(p.read_text(encoding="utf-8"))
        parts.append(body.strip())
    dest.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return dest
