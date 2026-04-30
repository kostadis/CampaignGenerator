"""Tests for scene-anchored VTT extraction (campaignlib + scene_extract + session_doc wiring)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
import session_doc


# ── parse_gmassist_scenes ─────────────────────────────────────────────────────

GMASSIST_SAMPLE = """\
# Session 2026-04-28

Date: Apr 28th, 2026

## Scenes
### Farewell to Eldeth
#### The party enjoys the sunlight as Eldeth prepares to depart.
- Glabbagool looks up into the sun with his googly eyes.
- Eldeth declares she and Thorin are "like brothers".

### Shadows at Dusk
#### While traveling toward Candlekeep the party realizes they are stalked.
- Grygum rolls a 9 on insight and concludes the tracker is a deer.
- Thorin asks whether they are on a stone surface.

### A Shadow in the Woods
#### The party moves to intercept the tracker.
- Daz uses Misty Step to teleport into a tree.
- Zalthir teleports and Stunning-Strikes the spy.

## NPCs
### Eldeth
A dwarven warrior.
"""


def test_parse_gmassist_scenes_returns_ordered_scenes():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    assert [s["name"] for s in scenes] == [
        "Farewell to Eldeth",
        "Shadows at Dusk",
        "A Shadow in the Woods",
    ]


def test_parse_gmassist_scenes_preserves_body():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    assert "Glabbagool looks up into the sun" in scenes[0]["body"]
    assert "Stunning-Strikes the spy" in scenes[2]["body"]


def test_parse_gmassist_scenes_stops_at_next_top_heading():
    scenes = campaignlib.parse_gmassist_scenes(GMASSIST_SAMPLE)
    # No scene should leak content from the ## NPCs section.
    for s in scenes:
        assert "Eldeth\nA dwarven warrior" not in s["body"]


def test_parse_gmassist_scenes_no_scenes_section():
    assert campaignlib.parse_gmassist_scenes("# Session\n\n## Summary\n\nNothing here.") == []


def test_parse_gmassist_scenes_empty_scenes_section():
    text = "## Scenes\n\n## NPCs\n### Eldeth\nA warrior.\n"
    assert campaignlib.parse_gmassist_scenes(text) == []


# ── run_scene_extraction ──────────────────────────────────────────────────────

def test_run_scene_extraction_writes_one_file_per_scene(tmp_path):
    scenes = [
        {"name": "Farewell to Eldeth", "body": "- bullet 1\n- bullet 2"},
        {"name": "Shadows at Dusk", "body": "- bullet 3"},
    ]
    captured = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        captured.append({"system": system, "user": user, "cache": cache_system})
        return f"FAKE EXTRACTED MOMENTS for {scenes[len(captured) - 1]['name']}"

    with patch.object(campaignlib, "stream_api", side_effect=fake_stream):
        out = campaignlib.run_scene_extraction(
            client=None,
            vtt_text="GM: hello\nThorin: hi",
            scenes=scenes,
            extract_dir=tmp_path / "out",
            model="claude-haiku-4-5-20251001",
            extraction_instruction="Scene: {name}\n\nBullets:\n{body}",
        )

    assert len(out) == 2
    assert out[0].name == "01_farewell_to_eldeth.md"
    assert out[1].name == "02_shadows_at_dusk.md"

    body0 = out[0].read_text(encoding="utf-8")
    assert body0.startswith("---\nscene: Farewell to Eldeth\n")
    assert "## Scene summary (from gm-assist, verbatim)" in body0
    assert "bullet 1" in body0
    assert "FAKE EXTRACTED MOMENTS" in body0


def test_run_scene_extraction_caches_system_by_default(tmp_path):
    scenes = [{"name": "Scene A", "body": "- thing"}]
    captured = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        captured.append(cache_system)
        return "moments"

    with patch.object(campaignlib, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )
    assert captured == [True]


def test_run_scene_extraction_resumes_existing_files(tmp_path):
    scenes = [
        {"name": "Scene A", "body": "- a"},
        {"name": "Scene B", "body": "- b"},
    ]
    (tmp_path / "01_scene_a.md").write_text("ALREADY DONE", encoding="utf-8")

    calls = []

    def fake_stream(client, system, user, model, max_tokens=8096, silent=False,
                    verbose=False, cache_system=False):
        calls.append(user)
        return "fresh"

    with patch.object(campaignlib, "stream_api", side_effect=fake_stream):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=tmp_path, model="m",
            extraction_instruction="{name} {body}",
        )

    # Scene A was skipped (file existed), Scene B got the only API call.
    assert len(calls) == 1
    assert "Scene B" in calls[0]
    assert (tmp_path / "01_scene_a.md").read_text(encoding="utf-8") == "ALREADY DONE"


def test_run_scene_extraction_empty_scenes_exits(tmp_path):
    with pytest.raises(SystemExit):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=[],
            extract_dir=tmp_path, model="m",
            extraction_instruction="x",
        )


# ── session_doc.load_scene_extractions ────────────────────────────────────────

def test_load_scene_extractions_parses_frontmatter_and_splits_body(tmp_path):
    (tmp_path / "01_farewell_to_eldeth.md").write_text(
        "---\n"
        "scene: Farewell to Eldeth\n"
        "source: gmassist\n"
        "---\n\n"
        "# Farewell to Eldeth\n\n"
        "## Scene summary (from gm-assist, verbatim)\n\n"
        "- bullet 1\n- bullet 2\n\n"
        "## Verbatim moments\n\n"
        "**[Glabbagool]**\n"
        "> \"oh!\"\n",
        encoding="utf-8",
    )
    (tmp_path / "02_shadows_at_dusk.md").write_text(
        "---\n"
        "scene: Shadows at Dusk\n"
        "---\n\n"
        "## Scene summary (from gm-assist, verbatim)\n\n"
        "summary text\n\n"
        "## Verbatim moments\n\n"
        "moments text\n",
        encoding="utf-8",
    )
    # Sibling artifacts should be ignored.
    (tmp_path / "plan.md").write_text("plan", encoding="utf-8")
    (tmp_path / "_notes.md").write_text("notes", encoding="utf-8")

    items = session_doc.load_scene_extractions(tmp_path)
    assert [s["name"] for s in items] == ["Farewell to Eldeth", "Shadows at Dusk"]
    assert "bullet 1" in items[0]["summary"]
    assert "Glabbagool" in items[0]["moments"]
    assert items[1]["summary"] == "summary text"
    assert items[1]["moments"] == "moments text"


def test_load_scene_extractions_skips_files_without_NN_prefix(tmp_path):
    (tmp_path / "session-doc.md").write_text("not a scene", encoding="utf-8")
    (tmp_path / "1_too_short.md").write_text("not NN_ pattern", encoding="utf-8")
    assert session_doc.load_scene_extractions(tmp_path) == []
