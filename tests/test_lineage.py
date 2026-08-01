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
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from campaignlib import compose_scenes, resolve_source  # noqa: E402
from campaignlib.textproc import split_frontmatter  # noqa: E402
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
