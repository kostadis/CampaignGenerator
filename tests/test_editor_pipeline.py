"""Tests for the new four-stage editor wiring (scene_editor)."""

import sys
from pathlib import Path

import pytest

# scene_editor imports fastapi; skip the whole module if it's not installed
# (e.g. in a CLI-only test venv).
pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.routers import scene_editor  # noqa: E402


def _seed_session_dir(tmp_path: Path, *, with_summary=True, with_sx=True, with_narration=True):
    """Build a session dir resembling the new-flow layout."""
    sd = tmp_path / "20260414"
    sd.mkdir()
    gm = sd / "gm-assist.md"
    gm.write_text("# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n\n### Scene Two\n- bullet\n",
                  encoding="utf-8")
    if with_summary:
        (sd / "session-summary.md").write_text(
            "# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n\n### Scene Two\n- bullet\n",
            encoding="utf-8",
        )
    sx = sd / "scene_extractions_new"
    if with_sx:
        sx.mkdir()
        (sx / "01_scene_one.md").write_text(
            "---\nscene: Scene One\nsource: gmassist\n---\n\nbody\n",
            encoding="utf-8",
        )
        (sx / "02_scene_two.md").write_text(
            "---\nscene: Scene Two\nsource: gmassist\n---\n\nbody\n",
            encoding="utf-8",
        )
    nd = sd / "narration"
    if with_narration:
        nd.mkdir()
        (nd / "plan.md").write_text(
            "## Section 1\nnarrator: Soma\nscene: Scene One\nchunks: 1-1\nfocus: focus 1\n\n"
            "## Section 2\nnarrator: Brewbarry\nscene: Scene Two\nchunks: 1-1\nfocus: focus 2\n",
            encoding="utf-8",
        )
        (nd / "session_doc_scene_01_scene_one.md").write_text(
            "---\nscene: 01\nslug: scene_one\nnarrator: Soma\n---\n\nNarration body for scene 1.\n",
            encoding="utf-8",
        )
    return sd, gm, sx, nd


# ── _load_scenes ─────────────────────────────────────────────────────────────


def test_load_scenes_new_flow(tmp_path, monkeypatch):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({
        "session": str(gm),
        "scene_extractions_dir": str(sx),
        "narration_dir": str(nd),
    })
    scenes = scene_editor._load_scenes()
    assert len(scenes) == 2
    assert scenes[0]["scene"] == "Scene One"
    assert scenes[0]["has_extraction"] is True
    assert scenes[0]["has_output"] is True  # narration file present
    assert scenes[1]["has_extraction"] is True
    assert scenes[1]["has_output"] is False  # no narration file for scene 2


def test_load_scenes_falls_back_to_extractions_when_plan_missing(tmp_path):
    """Before first Narrate, plan.md doesn't exist — scenes derive from NN_<slug>.md."""
    sd, gm, sx, _nd = _seed_session_dir(tmp_path, with_narration=False)
    nd = sd / "narration"
    nd.mkdir()  # empty — no plan.md
    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({
        "session": str(gm),
        "scene_extractions_dir": str(sx),
        "narration_dir": str(nd),
    })
    scenes = scene_editor._load_scenes()
    assert len(scenes) == 2
    assert scenes[0]["scene"] == "Scene One"
    assert scenes[0]["narrator"] == ""  # not assigned yet
    assert scenes[0]["has_extraction"] is True
    assert scenes[0]["has_output"] is False


def test_narration_file_for_scene_globs_correctly(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({"narration_dir": str(nd)})
    p = scene_editor._narration_file_for_scene(1)
    assert p is not None
    assert p.name == "session_doc_scene_01_scene_one.md"
    assert scene_editor._narration_file_for_scene(2) is None


# ── Command builders ─────────────────────────────────────────────────────────


def test_build_enhance_cmd_returns_error_when_misconfigured(tmp_path):
    scene_editor.CONFIG.clear()
    result = scene_editor._build_enhance_cmd()
    assert isinstance(result, tuple) and result[0] is None


def test_build_enhance_cmd_resolves_paths(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")

    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({"session": str(gm), "vtt": str(vtt),
                                "session_summary": str(sd / "session-summary.md")})
    cmd = scene_editor._build_enhance_cmd()
    assert isinstance(cmd, list)
    # enhance_summary.py moved into session_doc/ and now runs as the bare
    # `enhance_summary` console script (server.subprocess_runner.console_script()),
    # so cmd[0] is the resolved binary path, not `python <path>.py` — check
    # cmd[0]'s basename instead of a `.py`-suffixed cmd[1].
    assert "enhance_summary" in cmd[0]
    assert str(vtt) in cmd
    assert str(gm) in cmd
    assert str(sd / "session-summary.md") in cmd


def test_build_narrate_cmd_uses_new_flags(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({
        "session": str(gm),
        "session_summary": str(sd / "session-summary.md"),
        "scene_extractions_dir": str(sx),
        "narration_dir": str(nd),
    })
    result = scene_editor._build_narrate_cmd(1)
    assert isinstance(result, list)
    assert "--scene-extractions" in result
    assert "--per-scene-output" in result
    assert "--scene" in result
    assert str(sx) in result
    assert str(nd) in result
    # Must not use legacy flags
    assert "--from-extractions" not in result
    assert "--by-scene" not in result
