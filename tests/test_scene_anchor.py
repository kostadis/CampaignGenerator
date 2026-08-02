"""Tests for the scene boundary map (summary scenes -> chapter prose).

The point of the feature: a derived session-summary's ## Scenes list is a good
scene *index* but a poor extraction *source* (26% of the chapter's words on the
Phandalin corpus). So the scenes are used only to place ## headings into the
full prose, which then chunks per-scene and gives event_spine a real `scene`.
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from campaignlib.scene_anchor import (  # noqa: E402
    anchor_scenes, demote_h2, inject_scene_headings, snap_to_paragraph)
from campaignlib.textproc import chunk_by_scenes  # noqa: E402

# Prose with in-world-date H2s and POV H3s — the shape early chapters have,
# and the reason `scene` degenerates without this feature.
CHAPTER = """# Chapter 5 Saving Adabra

## 04-01 Taraskh 1495

### Vukradin

The bard haggled over a breastplate in the armoury, complaining that the
gorget chafed and that nobody appreciated a lute properly.

### Soma

The windmill came into view at dusk, its sails torn. A manticore circled
above the ridge, screeching, and the bandit cowered behind a millstone.

## 04-02 Taraskh 1495

### Valphine

Adabra thanked them for the rescue and explained the Emerald Enclave's
schism over interventionism, pouring elderflower cordial as she talked.
"""

SUMMARY_SCENES = [
    "### Armouring the Recruit\n- The bard haggles over a breastplate; the gorget chafes.\n",
    "### The Manticore at the Windmill\n- A manticore circles the torn sails; the bandit cowers.\n",
    "### Adabra and the Schism\n- Adabra explains the Enclave schism over elderflower cordial.\n",
]
TITLES = ["Armouring the Recruit", "The Manticore at the Windmill",
          "Adabra and the Schism"]


# ── anchoring ────────────────────────────────────────────────────────────

def test_anchors_are_in_order_and_land_on_the_right_prose():
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    assert all(x is not None for x in a)
    offs = [x.offset for x in a]
    assert offs == sorted(offs)
    assert "breastplate" in CHAPTER[a[0].offset:a[1].offset]
    assert "manticore" in CHAPTER[a[1].offset:a[2].offset].lower()
    assert "Adabra thanked" in CHAPTER[a[2].offset:]


def test_scene_with_no_distinctive_vocabulary_is_not_guessed():
    """Better an unanchored scene the GM can see than a confident wrong one."""
    a = anchor_scenes(CHAPTER, ["### Filler\n- and the of a to in it\n"], ["Filler"])
    assert a == [None]


def test_anchoring_is_monotonic_even_when_a_later_scene_matches_earlier_text():
    """Scene 3 repeats scene 1's vocabulary; the floor must keep it after."""
    scenes = SUMMARY_SCENES[:2] + [
        "### The Bard Again\n- The bard and the breastplate and the lute.\n"]
    a = anchor_scenes(CHAPTER, scenes, TITLES)
    placed = [x.offset for x in a if x is not None]
    assert placed == sorted(placed)


def test_snap_to_paragraph_never_splits_mid_sentence():
    i = CHAPTER.index("torn")
    assert snap_to_paragraph(CHAPTER, i) < i
    assert CHAPTER[snap_to_paragraph(CHAPTER, i):].startswith("The windmill")
    assert snap_to_paragraph(CHAPTER, 0) == 0


def test_anchor_reports_context_for_the_reviewer():
    """A boundary is a scope decision; the map must show its evidence."""
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    assert "breastplate" in a[0].context
    assert a[0].hits >= 3


# ── injection ────────────────────────────────────────────────────────────

def test_demote_h2_leaves_h3_alone():
    out = demote_h2("## Date\n### Soma\n#### deep\ntext\n")
    assert out.startswith("### Date")
    assert "### Soma" in out and "#### deep" in out


def test_injection_yields_one_chunk_per_scene():
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    derived = inject_scene_headings(CHAPTER, a)
    chunks, conv = chunk_by_scenes(derived, 6000)
    assert len(chunks) == 3
    assert [re.search(r"(?m)^##(?!#)\s+(.+)$", c).group(1) for _, c in chunks] == TITLES


def test_injection_demotes_the_date_headings_that_would_compete():
    """Left as H2, the in-world dates would split too and double the chunks."""
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    derived = inject_scene_headings(CHAPTER, a)
    # line-anchored: '### 04-01' trivially contains the substring '## 04-01'
    h2 = re.findall(r"(?m)^##(?!#)\s+(.+)$", derived)
    assert h2 == TITLES                              # only scene headings are H2 now
    assert re.search(r"(?m)^###\s+04-01 Taraskh 1495$", derived)  # kept, not structural


def test_injection_preserves_the_prose():
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    derived = inject_scene_headings(CHAPTER, a)
    for phrase in ("breastplate", "manticore circled", "elderflower cordial"):
        assert phrase in derived
    # only headings were added
    assert len(derived.split()) >= len(CHAPTER.split())


def test_unanchored_scene_merges_into_its_predecessor():
    a = anchor_scenes(CHAPTER, SUMMARY_SCENES, TITLES)
    a[1] = None
    derived = inject_scene_headings(CHAPTER, a)
    chunks, _ = chunk_by_scenes(derived, 6000)
    assert len(chunks) == 2
    assert "manticore" in chunks[0][1].lower()      # folded in, not dropped


# ── CLI ──────────────────────────────────────────────────────────────────

def _campaign(tmp_path: Path) -> Path:
    camp = tmp_path / "camp"
    (camp / "docs" / "chapters").mkdir(parents=True)
    (camp / "docs" / "chapters" / "chapter_05_saving_adabra.md").write_text(CHAPTER)
    sd = camp / "summaries" / "haiku" / "005-saving_adabra"
    sd.mkdir(parents=True)
    (sd / "session-summary.md").write_text(
        "# Chapter 5 Saving Adabra\n\n## Summary\n\nStuff.\n\n## Scenes\n\n"
        + "\n".join(SUMMARY_SCENES) + "\n## NPCs\n\n### Adabra\n\nA druid.\n")
    return camp


def _run(camp: Path, *args):
    return subprocess.run(
        [sys.executable, "-m", "pipelines.ensemble.scene_map",
         "--campaign-dir", str(camp), *args],
        capture_output=True, text=True, cwd=REPO)


def test_propose_writes_unapproved_rows_with_evidence(tmp_path):
    camp = _campaign(tmp_path)
    p = _run(camp, "propose")
    assert p.returncode == 0, p.stderr
    doc = yaml.safe_load((camp / "docs/ensemble/scene_map.yaml").read_text())
    row = doc["chapters"][0]
    assert row["approved"] is False
    assert row["chapter_index"] == 5
    assert [s["title"] for s in row["scenes"]] == TITLES
    assert all(s.get("context") for s in row["scenes"])


def test_apply_refuses_unapproved_rows(tmp_path):
    camp = _campaign(tmp_path)
    _run(camp, "propose")
    p = _run(camp, "apply")
    assert p.returncode == 0
    assert not (camp / "docs/chapters_scened").exists() or \
        not list((camp / "docs/chapters_scened").glob("*.md"))
    assert "1 unapproved skipped" in p.stdout


def test_apply_writes_a_derived_chapter_once_approved(tmp_path):
    camp = _campaign(tmp_path)
    _run(camp, "propose")
    mp = camp / "docs/ensemble/scene_map.yaml"
    doc = yaml.safe_load(mp.read_text())
    doc["chapters"][0]["approved"] = True
    mp.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    p = _run(camp, "apply")
    assert p.returncode == 0, p.stderr
    out = camp / "docs/chapters_scened/chapter_05_saving_adabra.md"
    assert out.exists()
    chunks, conv = chunk_by_scenes(out.read_text(), 6000)
    assert conv == "h2_date" and len(chunks) == 3
    assert "breastplate" in out.read_text()          # full prose, not the summary


def test_propose_preserves_approved_rows(tmp_path):
    camp = _campaign(tmp_path)
    _run(camp, "propose")
    mp = camp / "docs/ensemble/scene_map.yaml"
    doc = yaml.safe_load(mp.read_text())
    doc["chapters"][0]["approved"] = True
    doc["chapters"][0]["scenes"][0]["offset"] = 999   # a hand edit
    mp.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))

    _run(camp, "propose")
    again = yaml.safe_load(mp.read_text())
    assert again["chapters"][0]["approved"] is True
    assert again["chapters"][0]["scenes"][0]["offset"] == 999
    assert again["stats"]["preserved_approved"] == 1


def test_propose_refuses_duplicate_chapter_indices(tmp_path):
    camp = _campaign(tmp_path)
    (camp / "docs/chapters/chapter_05_saving_adabra_copy.md").write_text(CHAPTER)
    p = _run(camp, "propose")
    assert p.returncode == 2
    assert "duplicate chapter indices" in p.stderr
