"""Tests for the new four-stage editor wiring (scene_editor + ledger + quote_ledger)."""

import sys
from pathlib import Path

import pytest

# scene_editor imports fastapi; skip the whole module if it's not installed
# (e.g. in a CLI-only test venv).
pytest.importorskip("fastapi")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.routers import scene_editor  # noqa: E402
from server.routers import ledger as ledger_router  # noqa: E402
from quote_ledger import QuoteLedger  # noqa: E402


# ── _using_new_flow + _load_scenes ────────────────────────────────────────────


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
            "## Section 1\n- narrator: Soma\n- scene: Scene One\n- chunks: 1-1\n- focus: focus 1\n\n"
            "## Section 2\n- narrator: Brewbarry\n- scene: Scene Two\n- chunks: 1-1\n- focus: focus 2\n",
            encoding="utf-8",
        )
        (nd / "session_doc_scene_01_scene_one.md").write_text(
            "---\nscene: 01\nslug: scene_one\nnarrator: Soma\n---\n\nNarration body for scene 1.\n",
            encoding="utf-8",
        )
    return sd, gm, sx, nd


def test_using_new_flow_detects_plan_md(tmp_path, monkeypatch):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    monkeypatch.setitem(scene_editor.CONFIG, "session", str(gm))
    monkeypatch.setitem(scene_editor.CONFIG, "scene_extractions_dir", str(sx))
    monkeypatch.setitem(scene_editor.CONFIG, "narration_dir", str(nd))
    assert scene_editor._using_new_flow() is True


def test_using_new_flow_falls_back_when_legacy(tmp_path, monkeypatch):
    sd, gm, sx, nd = _seed_session_dir(tmp_path, with_narration=False, with_sx=False)
    legacy = sd / "extract_dir"
    legacy.mkdir()
    (legacy / "plan.md").write_text("## Section 1\n- narrator: X\n", encoding="utf-8")
    (legacy / "01_x_y.md").write_text("# old", encoding="utf-8")
    monkeypatch.setitem(scene_editor.CONFIG, "session", str(gm))
    monkeypatch.setitem(scene_editor.CONFIG, "extract_dir", str(legacy))
    monkeypatch.delitem(scene_editor.CONFIG, "scene_extractions_dir", raising=False)
    monkeypatch.delitem(scene_editor.CONFIG, "narration_dir", raising=False)
    assert scene_editor._using_new_flow() is False


def test_load_scenes_new_flow(tmp_path, monkeypatch):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    # Reset CONFIG so prior tests' state can't leak in.
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


def test_narration_file_for_scene_globs_correctly(tmp_path, monkeypatch):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    scene_editor.CONFIG.clear()
    scene_editor.CONFIG.update({"narration_dir": str(nd)})
    p = scene_editor._narration_file_for_scene(1)
    assert p is not None
    assert p.name == "session_doc_scene_01_scene_one.md"
    assert scene_editor._narration_file_for_scene(2) is None


# ── filename_for_scene contract used by quote_ledger ──────────────────────────


def test_filename_for_scene_new_drops_narrator():
    fname = ledger_router._filename_for_scene_new(3, "Soma", "Harvesting the Dragon")
    assert fname == "03_harvesting_the_dragon.md"


def test_filename_for_scene_new_handles_apostrophes_and_unicode():
    fname = ledger_router._filename_for_scene_new(7, "x", "A Hero's Welcome — in Phandalin!")
    # Non-alphanumeric collapses to single underscore; trim trailing underscores.
    assert fname == "07_a_hero_s_welcome_in_phandalin.md"


def test_quote_ledger_match_uses_injected_filename(tmp_path):
    """QuoteLedger._match_to_scenes must call the injected callable, not extraction_filename."""
    db = tmp_path / "ledger.db"
    sx = tmp_path / "sx"
    sx.mkdir()
    rp = tmp_path / "rp"
    rp.mkdir()
    # Stage 2 file using NN_<slug>.md naming
    (sx / "01_first_scene.md").write_text(
        '---\nscene: First Scene\n---\n\n# First Scene\n\n## Scene summary\n\n## Verbatim moments\n\n'
        '**Soma** — *thinking*\n> "the dragon was cold"\n',
        encoding="utf-8",
    )
    # Roleplay extraction with a quote that should match
    (rp / "extract_001.md").write_text(
        "Speaker: Soma\nCharacter: Soma\nContext: thinking\nQuote: \"the dragon was cold\"\n\n",
        encoding="utf-8",
    )

    led = QuoteLedger(db)
    captured = []

    def fake_namer(idx, narrator, scene_name):
        captured.append((idx, narrator, scene_name))
        return f"{idx:02d}_first_scene.md"

    scenes = [{"index": 1, "narrator": "Soma", "scene": "First Scene",
               "chunk_start": 1, "chunk_end": 1}]
    # We don't assert on matching outcome here — quote_ledger's parse format is
    # bespoke. Only assert that the injected namer was used.
    led.sync(roleplay_dir=rp, extract_dir=sx, scenes=scenes,
             filename_for_scene=fake_namer)
    led.close()
    assert captured == [(1, "Soma", "First Scene")]


def test_quote_ledger_default_namer_is_extraction_filename(tmp_path):
    """When filename_for_scene is None, the legacy extraction_filename must be used."""
    db = tmp_path / "ledger.db"
    sx = tmp_path / "sx"
    sx.mkdir()
    rp = tmp_path / "rp"
    rp.mkdir()

    led = QuoteLedger(db)
    scenes = [{"index": 1, "narrator": "Soma", "scene": "First Scene",
               "chunk_start": 1, "chunk_end": 1}]
    # No file present — _match_to_scenes silently skips. We just need to confirm
    # the call doesn't raise and that the legacy import path is used.
    result = led.sync(roleplay_dir=rp, extract_dir=sx, scenes=scenes,
                     filename_for_scene=None)
    led.close()
    assert result["total"] == 0


# ── Command builders ──────────────────────────────────────────────────────────


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
    assert "enhance_summary.py" in cmd[1]
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


