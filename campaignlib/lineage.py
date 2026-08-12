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

from campaignlib.scenes import find_scenes_section
from campaignlib.textproc import chunk_by_scenes, split_frontmatter

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


# Lenses whose subject matter exists only in the chapter prose, regardless of
# what the ladder resolves for the factual lenses. Interiority — why the
# characters acted, how they felt — is authored into the memoir-voice
# narration; it was never in the transcript, so scene extractions and session
# summaries mostly do not contain it. Routing this lens to the chapter is also
# zero-regression: it is exactly what the lens read before Phase 1.
# (GM ruling, #213 Phase 1.1, 2026-07-31.)
CHAPTER_BOUND_PASSES = ("interiority",)


def route_plan(plan: dict, decision: "SourceDecision", chapter_path: Path,
               resolved_input: Path) -> tuple[dict, dict[str, str]]:
    """Give each extract-plan pass the document its lens should read.

    Returns ``(routed_plan, pass_kinds)`` where ``pass_kinds`` maps pass name
    to the lineage kind of the document it will read — the merge stamps
    per-fact provenance from it.

    - Passes matching :data:`CHAPTER_BOUND_PASSES` (by name or agent) read the
      chapter prose (kind ``chapter``).
    - Passes with an explicit ``document`` already in the plan are the plan
      author's routing decision — left untouched, kind ``plan``.
    - Every other pass reads the ladder-resolved input (``decision.kind``).
    """
    routed = {k: v for k, v in plan.items() if k != "passes"}
    routed["passes"] = []
    kinds: dict[str, str] = {}
    for p in plan.get("passes") or []:
        q = dict(p)
        name = str(q.get("name") or q.get("agent") or "")
        agent = str(q.get("agent") or "")
        # Absolute paths: ensemble_extract resolves a pass's `document`
        # relative to the plan file's own directory, and the routed plan
        # lives in the workdir — relative paths would double up.
        if q.get("document"):
            kinds[name] = "plan"
        elif any(t in name for t in CHAPTER_BOUND_PASSES) or \
                any(t in agent for t in CHAPTER_BOUND_PASSES):
            q["document"] = str(Path(chapter_path).resolve())
            kinds[name] = "chapter"
        else:
            q["document"] = str(Path(resolved_input).resolve())
            kinds[name] = decision.kind
        routed["passes"].append(q)
    return routed, kinds


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


_H1_RE = re.compile(r"(?s)\A\s*(#(?!#)[ \t]+[^\n]*)\n")
# Big enough that chunk_by_scenes never sub-splits during the probe below: we
# are asking which heading convention it *detects*, not how it would cut.
_PROBE_CHUNK = 10 ** 9


def compose_summary_scenes(summary: Path, dest: Path) -> Path | None:
    """Slice a session-summary's ``## Scenes`` body out as its own document.

    Returns ``dest`` on success, or ``None`` when the summary has no usable
    scene list — the caller then falls back to the summary as-is, which is the
    pre-existing behaviour.

    **Why this exists.** Two consumers read a ``session-summary.md`` and want
    opposite things from its headings:

    - ``_summary_is_structured`` (the ladder gate, above) admits the file to the
      summary rung only if literal ``## Scenes`` AND ``## NPCs`` are present.
    - ``chunk_by_scenes`` splits on ``##`` and consults ``###`` *only when no*
      ``##`` *heading exists anywhere*. Its chunk index becomes ``scene_index``
      (``ensemble_merge.stamp_scene_index``), which is the ``scene`` component
      of ``event_spine``'s ``(chapter, scene, seq)`` key.

    So the gate requires the H2 wrapper and the chunker is defeated by it: fed
    the whole file, ``chunk_by_scenes`` returns Summary / Scenes / NPCs and
    every scene collapses into a single ``scene_index``. Slicing to the
    ``## Scenes`` section alone does not help — ``## Scenes`` is itself an H2.

    One document cannot satisfy both, so the resolution is here rather than in
    the format: the file on disk keeps its H2s for the gate, and extraction is
    handed this derived document, whose only headings are the ``###`` scene
    titles. Convention flips to ``h3`` and each scene gets its own chunk.

    Stripping every ``##`` line from the whole file would NOT work: the
    ``### <NPC name>`` entries under ``## NPCs`` are H3 too and would become
    chunk boundaries, so a 9-scene chapter yields 18 "scenes", half of them NPC
    paragraphs. The section must be sliced first, then its one wrapper line
    dropped.

    The chapter's ``# H1`` title is carried over for context;
    ``chunk_by_scenes`` folds pre-first-heading content into the first scene,
    and an H1 matches neither the H2 nor the H3 pattern, so it cannot create a
    boundary.

    Deterministic; byte-stable for unchanged input. Writing the slice to disk
    (rather than slicing in memory) is load-bearing: ``ensemble_merge.
    load_document`` re-reads the document from the path recorded in the
    manifest, so extract-time and merge-time text must be the same file or
    ``quote_offset`` and ``scene_index`` would be computed against different
    coordinates.

    The ``## Scenes`` heading match itself is ``find_scenes_section``
    (campaignlib/scenes.py) — this was one of four independent heading
    rules in the codebase before issue #262 unified them; see that
    function's docstring for why.
    """
    text = summary.read_text(encoding="utf-8")
    found = find_scenes_section(text)
    if found is None:
        return None
    body = found[0].strip()
    if not body:
        return None
    # Ask chunk_by_scenes itself rather than re-implementing its priority rule:
    # anything other than a clean h3 read means slicing bought us nothing.
    probe = chunk_by_scenes(body, _PROBE_CHUNK)
    if probe is None or probe[1] != "h3":
        return None
    title = _H1_RE.match(text)
    head = f"{title.group(1).strip()}\n\n" if title else ""
    dest.write_text(head + body + "\n", encoding="utf-8")
    return dest
