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
from server.session_editor_config_service import ResolvedEditorConfig  # noqa: E402
from server.session_editor_config_shared import (  # noqa: E402
    Backends,
    EditorPaths,
    NarrateKnobs,
    Roster,
    ScrubKnobs,
)


def _cfg(*, vtt: str | None = None, work_dir: str = "", **path_overrides) -> ResolvedEditorConfig:
    """Build a ResolvedEditorConfig directly (no service/platform needed) for
    exercising the CONFIG-free helpers/command-builders — Phase 2 of
    docs/config/session-editor-isolation.md. `path_overrides` are EditorPaths
    fields (session_recap, session_summary, scene_extractions_dir, ...)."""
    return ResolvedEditorConfig(
        paths=EditorPaths(**path_overrides),
        narrate=NarrateKnobs(),
        scrub=ScrubKnobs(),
        roster=Roster(),
        backends=Backends(),
        session_name=None,
        profiles=[],
        active_profile=None,
        model=None,
        work_dir=work_dir,
        campaign_dir="",
        config_dir="config",
        vtt=vtt,
    )


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
    cfg = _cfg(session_recap=str(gm), scene_extractions_dir=str(sx), narration_dir=str(nd))
    scenes = scene_editor._load_scenes(cfg)
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
    cfg = _cfg(session_recap=str(gm), scene_extractions_dir=str(sx), narration_dir=str(nd))
    scenes = scene_editor._load_scenes(cfg)
    assert len(scenes) == 2
    assert scenes[0]["scene"] == "Scene One"
    assert scenes[0]["narrator"] == ""  # not assigned yet
    assert scenes[0]["has_extraction"] is True
    assert scenes[0]["has_output"] is False


def test_narration_file_for_scene_globs_correctly(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    cfg = _cfg(narration_dir=str(nd))
    p = scene_editor._narration_file_for_scene(cfg, 1)
    assert p is not None
    assert p.name == "session_doc_scene_01_scene_one.md"
    assert scene_editor._narration_file_for_scene(cfg, 2) is None


# ── Command builders ─────────────────────────────────────────────────────────


def test_build_enhance_cmd_returns_error_when_misconfigured(tmp_path):
    cfg = _cfg()
    result = scene_editor._build_enhance_cmd(None, cfg)
    assert isinstance(result, tuple) and result[0] is None


def test_build_enhance_cmd_resolves_paths(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")

    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        vtt=str(vtt),
    )
    cmd = scene_editor._build_enhance_cmd(None, cfg)
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
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
    )
    result = scene_editor._build_narrate_cmd(None, cfg, 1)
    assert isinstance(result, list)
    assert "--scene-extractions" in result
    assert "--per-scene-output" in result
    assert "--scene" in result
    assert str(sx) in result
    assert str(nd) in result
    # Must not use legacy flags
    assert "--from-extractions" not in result
    assert "--by-scene" not in result


# ── Batch forwarding via the resolved selection (005-ui-batch-selection,
#    T029) — the bespoke `?batch=1`/checkbox mechanism is retired; Enhance,
#    Extract, and (for the first time) Narrate now pick up --batch from
#    `_selection_args` -> `resolve_selection` -> `selection_cli_args` the
#    same way every other service's run command does. This is the "natural
#    first end-to-end check that the unified path produces the same
#    behavior the bespoke one did" (research.md D6). ────────────────────────


def test_build_enhance_cmd_forwards_batch_when_resolved_selection_true(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        vtt=str(vtt),
    )
    cfg.backends.anthropic.batch = True
    cmd = scene_editor._build_enhance_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--batch" in cmd


def test_build_enhance_cmd_omits_batch_by_default(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        vtt=str(vtt),
    )
    cmd = scene_editor._build_enhance_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--batch" not in cmd


def test_build_reextract_cmd_forwards_batch_when_resolved_selection_true(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
    )
    cfg.backends.anthropic.batch = True
    cmd = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--batch" in cmd


def test_build_reextract_cmd_omits_batch_by_default(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
    )
    cmd = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--batch" not in cmd


def test_build_narrate_cmd_forwards_batch_when_resolved_selection_true(tmp_path):
    """`session_doc` is classified `degraded` in the batch capability map
    (data-model.md), not `incompatible` — it runs, just as sequential
    one-item batches. Narrate picking up --batch here is new: even the
    retired bespoke checkbox never reached this stage (it only ever forwarded
    to Enhance/Extract), so this is a real behavior addition, not a
    preservation of prior behavior — and it is the intended, correct one."""
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
    )
    cfg.backends.anthropic.batch = True
    result = scene_editor._build_narrate_cmd(None, cfg, 1)
    assert isinstance(result, list)
    assert "--batch" in result


def test_build_enhance_cmd_refuses_incompatible_batch_selection(tmp_path):
    """Batch is a Claude API option (research D2/D3) — a batch selection
    that resolves against a non-anthropic backend raises
    IncompatibleSelection before any command is built, exactly like every
    other service (tests/test_ui_batch_service_selection.py's
    grounding/party/planning coverage), never a silent full-price run."""
    from server.platform_config_service import IncompatibleSelection

    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        vtt=str(vtt),
    )
    cfg.backends.active = "dgx"
    cfg.backends.dgx.model = "Qwen3-Next-80B"
    cfg.backends.dgx.endpoint = "http://localhost:8000"
    cfg.backends.dgx.batch = True
    with pytest.raises(IncompatibleSelection):
        scene_editor._build_enhance_cmd(None, cfg)


# ── _scene_extraction_file_new: resolution when the plan title has drifted ───
#
# The UI builds the Stage-2 filename by slugifying the scene name taken from
# the PLAN, but sd_plan retitles scenes, so the plan title often no longer
# slugifies to what Stage 2 wrote. When that happened the file read as missing,
# has_extraction went False, and the editor greyed out Narrate for a scene the
# CLI would narrate fine — sd_narrate.py:235 already does "name match, fallback
# to index", so the UI was strictly stricter than the engine it fronts.


def _sx_cfg(tmp_path: Path):
    sx = tmp_path / "scene_extractions_new"
    sx.mkdir()
    return sx, _cfg(scene_extractions_dir=str(sx))


def test_scene_file_prefers_the_exact_slug(tmp_path):
    sx, cfg = _sx_cfg(tmp_path)
    (sx / "05_the_return_of_the_statue.md").write_text("body", encoding="utf-8")
    got = scene_editor._scene_extraction_file_new(cfg, 5, "The Return Of The Statue")
    assert got == sx / "05_the_return_of_the_statue.md"


def test_scene_file_prefers_the_scaffold_over_the_stage2_source(tmp_path):
    """The scaffold is what the user edits and what Narrate consumes; the
    Stage-2 file is the expensive LLM source we never overwrite."""
    sx, cfg = _sx_cfg(tmp_path)
    (sx / "05_the_statue.md").write_text("source", encoding="utf-8")
    (sx / "05_the_statue.scaffold.md").write_text("edited", encoding="utf-8")
    got = scene_editor._scene_extraction_file_new(cfg, 5, "The Statue")
    assert got == sx / "05_the_statue.scaffold.md"


def test_scene_file_falls_back_to_index_when_the_title_drifted(tmp_path):
    """The regression: plan says "The Statue Returned, a Quest Begun", Stage 2
    wrote 05_the_return_of_the_meliamne_statue.md. Slug resolution misses."""
    sx, cfg = _sx_cfg(tmp_path)
    real = sx / "05_the_return_of_the_meliamne_statue.md"
    real.write_text("body", encoding="utf-8")
    got = scene_editor._scene_extraction_file_new(
        cfg, 5, "The Statue Returned, a Quest Begun")
    assert got == real
    assert got.exists(), "has_extraction would be False and Narrate greyed out"


def test_index_fallback_still_prefers_a_scaffold(tmp_path):
    sx, cfg = _sx_cfg(tmp_path)
    (sx / "05_some_other_title.md").write_text("source", encoding="utf-8")
    (sx / "05_some_other_title.scaffold.md").write_text("edited", encoding="utf-8")
    got = scene_editor._scene_extraction_file_new(cfg, 5, "Totally Different Name")
    assert got == sx / "05_some_other_title.scaffold.md"


def test_index_fallback_never_resolves_to_a_different_scene(tmp_path):
    """The NN_ prefix is unique per scene, so a miss must not borrow scene 4's
    file — that would silently narrate the wrong scene, which is worse than a
    greyed-out button."""
    sx, cfg = _sx_cfg(tmp_path)
    (sx / "04_scene_four.md").write_text("four", encoding="utf-8")
    (sx / "06_scene_six.md").write_text("six", encoding="utf-8")
    got = scene_editor._scene_extraction_file_new(cfg, 5, "Nothing Matches This")
    assert not got.exists()
    assert "04_" not in got.name and "06_" not in got.name


def test_missing_everything_returns_the_slug_path_unchanged(tmp_path):
    """Callers test .exists() on the result, so the genuinely-absent case must
    behave exactly as it did before the fallback existed."""
    sx, cfg = _sx_cfg(tmp_path)
    got = scene_editor._scene_extraction_file_new(cfg, 5, "No Such Scene")
    assert got == sx / "05_no_such_scene.md"
    assert not got.exists()
