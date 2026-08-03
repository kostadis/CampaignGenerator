"""Tests for the source-lineage ladder (issue #213, Phase 1).

Rulings under test (recorded on the #213 anchor, 2026-07-31):
- Ladder order: reviewed scene extractions > structured session-summary >
  chapter prose (amends the anchor's originally-written order).
- Review gate: lenient — a scene counts via its own .reviewed marker OR its
  scaffold's; the chapter qualifies on a majority of scenes.
- Every rung above chapter is gated on an approved: true summary_map row;
  proposals (approved: false) open nothing.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from campaignlib import (  # noqa: E402
    compose_scenes, compose_summary_scenes, resolve_source, route_plan)
from campaignlib.lineage import SourceDecision, _summary_is_structured  # noqa: E402
from campaignlib.textproc import chunk_by_scenes, split_frontmatter  # noqa: E402
from pipelines.ensemble.ensemble_merge import stamp_lineage  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────

STRUCTURED_SUMMARY = (
    "# Chapter 40 Through the Valley\n\n## Summary\n\nStuff.\n\n"
    "## Scenes\n\n### Recap\n\n#### It begins.\n\n"
    "## NPCs\n\n### Orc Nine\n\nDied.\n"
)


def _campaign(tmp_path: Path, *, approved: bool = True,
              scenes: int = 0, reviewed: int = 0,
              scaffold_reviewed: int = 0, summary: str | None = None) -> tuple[Path, Path]:
    """Build a minimal campaign tree; returns (campaign_dir, chapter_path)."""
    camp = tmp_path / "camp"
    chdir = camp / "docs" / "chapters"
    chdir.mkdir(parents=True)
    chapter = chdir / "chapter_40_through_the_valley.md"
    chapter.write_text("# Chapter 40 Through the Valley\n\nProse.\n")

    session = camp / "summaries" / "20260505"
    session.mkdir(parents=True)
    if summary is not None:
        (session / "session-summary.md").write_text(summary)
    if scenes:
        sdir = session / "scene_extractions_new"
        sdir.mkdir()
        for i in range(1, scenes + 1):
            f = sdir / f"{i:02d}_scene_{i}.md"
            f.write_text(f"---\nscene: S{i}\nsource: gmassist\n---\n"
                         f"# Scene {i}\n\nQuote {i}.\n")
            (sdir / f"{i:02d}_scene_{i}.scaffold.md").write_text("scaffold")
            if i <= reviewed:
                (sdir / f"{i:02d}_scene_{i}.md.reviewed").touch()
            elif i <= reviewed + scaffold_reviewed:
                (sdir / f"{i:02d}_scene_{i}.scaffold.md.reviewed").touch()

    map_dir = camp / "docs" / "ensemble"
    map_dir.mkdir(parents=True)
    (map_dir / "summary_map.yaml").write_text(yaml.safe_dump({"entries": [{
        "chapter": chapter.name,
        "summary": "summaries/20260505",
        "summary_date": "20260505",
        "approved": approved,
    }]}))
    return camp, chapter


# ── ladder rungs ─────────────────────────────────────────────────────────

def test_no_approved_row_falls_to_chapter(tmp_path):
    camp, chapter = _campaign(tmp_path, approved=False, scenes=3, reviewed=3,
                              summary=STRUCTURED_SUMMARY)
    d = resolve_source(chapter, camp)
    assert d.kind == "chapter"
    assert d.inputs == [chapter]
    assert "no approved session join" in d.reason


def test_majority_reviewed_scenes_win(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=5, reviewed=3,
                              summary=STRUCTURED_SUMMARY)
    d = resolve_source(chapter, camp)
    assert d.kind == "scenes"
    assert len(d.inputs) == 5          # all scenes feed extraction
    assert d.session == "20260505"
    assert "3/5 scenes reviewed (majority)" in d.reason
    # scaffolds and markers are never inputs
    assert all(not p.name.endswith(".scaffold.md") for p in d.inputs)


def test_scaffold_marker_counts_as_reviewed(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=4, reviewed=1,
                              scaffold_reviewed=2, summary=STRUCTURED_SUMMARY)
    d = resolve_source(chapter, camp)
    assert d.kind == "scenes"
    assert "3/4" in d.reason


def test_minority_reviewed_falls_to_summary(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=4, reviewed=2,
                              summary=STRUCTURED_SUMMARY)
    d = resolve_source(chapter, camp)          # 2/4 is not a majority
    assert d.kind == "summary"
    assert d.inputs[0].name == "session-summary.md"
    assert "no majority" in d.reason


def test_unstructured_summary_falls_to_chapter(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=0,
                              summary="# Chapter 40\n\nJust prose, no sections.\n")
    d = resolve_source(chapter, camp)
    assert d.kind == "chapter"
    assert "no structured session-summary" in d.reason


def test_missing_session_dir_falls_to_chapter(tmp_path):
    camp, chapter = _campaign(tmp_path)
    (camp / "summaries" / "20260505").rename(camp / "summaries" / "gone")
    d = resolve_source(chapter, camp)
    assert d.kind == "chapter"
    assert "session dir missing" in d.reason


def test_missing_map_falls_to_chapter(tmp_path):
    camp, chapter = _campaign(tmp_path)
    (camp / "docs" / "ensemble" / "summary_map.yaml").unlink()
    d = resolve_source(chapter, camp)
    assert d.kind == "chapter"


# ── scene composition ────────────────────────────────────────────────────

def test_compose_scenes_strips_frontmatter_and_orders(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=3, reviewed=3)
    d = resolve_source(chapter, camp)
    out = compose_scenes(d.inputs, tmp_path / "composed.md")
    text = out.read_text()
    assert "---" not in text          # every per-scene frontmatter stripped
    assert "scene: S1" not in text
    assert text.index("# Scene 1") < text.index("# Scene 2") < text.index("# Scene 3")
    # byte-stable on re-compose
    first = text
    compose_scenes(d.inputs, tmp_path / "composed.md")
    assert (tmp_path / "composed.md").read_text() == first


# ── summary scene slicing (the H2/H3 tension) ────────────────────────────

MULTI_SCENE_SUMMARY = (
    "# Chapter 40 Through the Valley\n\n"
    "## Summary\n\nThe party crossed the valley.\n\n"
    "## Scenes\n\n"
    "### The Crossing\n#### They cross.\n- Boots got wet.\n\n"
    "### The Ridge\n#### They climb.\n- Orcs waited above.\n\n"
    "### The Descent\n#### They come down.\n- Nobody died.\n\n"
    "## NPCs\n\n"
    "### Orc Nine\n\nDied anyway.\n\n"
    "### Xanth\n\nGuided them.\n"
)


def test_compose_summary_scenes_gives_one_chunk_per_scene(tmp_path):
    """The whole summary chunks on its ## headings and collapses every scene
    into one; the slice chunks on ### and gives each scene its own index."""
    src = tmp_path / "session-summary.md"
    src.write_text(MULTI_SCENE_SUMMARY)

    # Whole file: splits on ## Summary / ## Scenes / ## NPCs, so all three
    # scenes share a single chunk and therefore a single scene_index.
    whole, conv_whole = chunk_by_scenes(MULTI_SCENE_SUMMARY, 6000)
    assert conv_whole != "h3"
    holding = [c for _, c in whole if "### The Crossing" in c]
    assert len(holding) == 1
    assert "### The Ridge" in holding[0] and "### The Descent" in holding[0]

    out = compose_summary_scenes(src, tmp_path / "sliced.md")
    assert out is not None
    chunks, conv = chunk_by_scenes(out.read_text(), 6000)
    assert conv == "h3"
    assert len(chunks) == 3
    # One scene per chunk, in order. Chunk 0 also carries the H1 title, which
    # chunk_by_scenes folds into the first scene — an H1 matches neither the
    # H2 nor the H3 pattern, so it cannot open a chunk of its own.
    assert [re.findall(r"(?m)^###\s+.+$", c) for _, c in chunks] == [
        ["### The Crossing"], ["### The Ridge"], ["### The Descent"]]
    assert chunks[0][1].startswith("# Chapter 40 Through the Valley")


def test_compose_summary_scenes_excludes_npc_headings(tmp_path):
    """Stripping every ## from the whole file would turn the ### NPC entries
    into chunk boundaries too. Slicing the section first must not."""
    src = tmp_path / "session-summary.md"
    src.write_text(MULTI_SCENE_SUMMARY)
    text = compose_summary_scenes(src, tmp_path / "sliced.md").read_text()
    assert "Orc Nine" not in text and "Xanth" not in text
    assert "## NPCs" not in text and "## Summary" not in text
    assert text.startswith("# Chapter 40 Through the Valley")   # H1 kept for context


def test_compose_summary_scenes_leaves_the_gate_intact(tmp_path):
    """The on-disk summary is untouched, so _summary_is_structured still
    admits it to the summary rung — the slice is a derived extraction input."""
    src = tmp_path / "session-summary.md"
    src.write_text(MULTI_SCENE_SUMMARY)
    compose_summary_scenes(src, tmp_path / "sliced.md")
    assert src.read_text() == MULTI_SCENE_SUMMARY
    assert _summary_is_structured(src)


@pytest.mark.parametrize("body,why", [
    ("# Ch\n\n## Summary\n\nNo scenes at all.\n", "no ## Scenes section"),
    ("# Ch\n\n## Scenes\n\n## NPCs\n\n### A\n\nx\n", "empty ## Scenes section"),
    ("# Ch\n\n## Scenes\n\nProse, no ### entries.\n", "no ### scene headings"),
])
def test_compose_summary_scenes_returns_none_when_unusable(tmp_path, body, why):
    """Caller falls back to the summary as-is rather than extracting from an
    empty or heading-less document."""
    src = tmp_path / "session-summary.md"
    src.write_text(body)
    assert compose_summary_scenes(src, tmp_path / "sliced.md") is None, why


def test_compose_summary_scenes_is_byte_stable(tmp_path):
    src = tmp_path / "session-summary.md"
    src.write_text(MULTI_SCENE_SUMMARY)
    first = compose_summary_scenes(src, tmp_path / "sliced.md").read_text()
    again = compose_summary_scenes(src, tmp_path / "sliced.md").read_text()
    assert first == again


# ── merge stamping ───────────────────────────────────────────────────────

def test_stamp_lineage_stamps_kind_and_session(tmp_path):
    (tmp_path / "lineage.json").write_text(json.dumps(
        {"chapter": "chapter_40_x", "kind": "scenes", "session": "20260505",
         "inputs": [], "reason": "3/5"}))
    facts = [{"fact": "a"}, {"fact": "b"}]
    lineage = stamp_lineage(facts, tmp_path)
    assert lineage["kind"] == "scenes"
    assert all(f["source"] == {"kind": "scenes", "session": "20260505"}
               for f in facts)


def test_stamp_lineage_absent_file_stamps_nothing(tmp_path):
    facts = [{"fact": "a"}]
    assert stamp_lineage(facts, tmp_path) is None
    assert "source" not in facts[0]


# ── per-lens routing (#213 Phase 1.1) ────────────────────────────────────

PLAN = {"passes": [
    {"name": "small", "agent": "extract_facts", "chunk_size": 6000},
    {"name": "temporal", "agent": "extract_facts_temporal", "chunk_size": 15000},
    {"name": "interiority", "agent": "extract_facts_interiority", "chunk_size": 15000},
    {"name": "custom", "agent": "extract_facts", "document": "docs/other.md"},
]}


def test_route_plan_sends_interiority_to_chapter(tmp_path):
    decision = SourceDecision(kind="scenes", session="20260505")
    routed, kinds = route_plan(
        PLAN, decision, Path("docs/chapters/chapter_40_x.md"),
        Path("per_chapter/chapter_40_x/lineage_scenes.md"))
    by_name = {p["name"]: p for p in routed["passes"]}
    # Routed documents are absolute — ensemble_extract resolves relative
    # documents against the plan file's directory (the workdir).
    assert by_name["small"]["document"].endswith("lineage_scenes.md")
    assert Path(by_name["small"]["document"]).is_absolute()
    assert by_name["temporal"]["document"].endswith("lineage_scenes.md")
    assert by_name["interiority"]["document"].endswith("docs/chapters/chapter_40_x.md")
    assert Path(by_name["interiority"]["document"]).is_absolute()
    assert by_name["custom"]["document"] == "docs/other.md"  # author routing kept
    assert kinds == {"small": "scenes", "temporal": "scenes",
                     "interiority": "chapter", "custom": "plan"}
    # original plan untouched
    assert "document" not in PLAN["passes"][0]


def test_stamp_lineage_per_pass_kinds(tmp_path):
    (tmp_path / "lineage.json").write_text(json.dumps(
        {"chapter": "chapter_40_x", "kind": "scenes", "session": "20260505",
         "passes": {"small": "scenes", "temporal": "scenes",
                    "interiority": "chapter"}}))
    facts = [
        {"fact": "orc nine died", "passes": ["small", "temporal"]},
        {"fact": "vukradin felt doubt", "passes": ["interiority"]},
        {"fact": "both saw it", "passes": ["interiority", "small"]},
    ]
    stamp_lineage(facts, tmp_path)
    assert facts[0]["source"] == {"kind": "scenes", "session": "20260505"}
    assert facts[1]["source"] == {"kind": "chapter", "session": "20260505"}
    assert facts[2]["source"] == {"kind": "mixed",
                                  "kinds": ["chapter", "scenes"],
                                  "session": "20260505"}


def test_stamp_lineage_without_passes_is_uniform(tmp_path):
    (tmp_path / "lineage.json").write_text(json.dumps(
        {"chapter": "c", "kind": "scenes", "session": "20260505"}))
    facts = [{"fact": "a", "passes": ["interiority"]}]
    stamp_lineage(facts, tmp_path)
    assert facts[0]["source"] == {"kind": "scenes", "session": "20260505"}


# ── batch report smoke test ──────────────────────────────────────────────

def test_batch_lineage_report_runs_without_model(tmp_path):
    camp, chapter = _campaign(tmp_path, scenes=5, reviewed=3)
    proc = subprocess.run(
        [sys.executable, str(REPO / "pipelines/ensemble/ensemble_batch.py"),
         "--chapters", str(chapter), "--campaign-dir", str(camp),
         "--lineage-report"],
        capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "scenes" in proc.stdout
    assert "3/5 scenes reviewed" in proc.stdout
