"""Tests for the new four-stage editor wiring (scene_editor)."""

import sys
from dataclasses import replace
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
    ExtractKnobs,
    NarrateKnobs,
)
from session_doc import io as session_io  # noqa: E402


def _cfg(*, vtt: str | None = None, work_dir: str = "", campaign_dir: str = "",
         characters: str | None = None, **path_overrides) -> ResolvedEditorConfig:
    """Build a ResolvedEditorConfig directly (no service/platform needed) for
    exercising the CONFIG-free helpers/command-builders — Phase 2 of
    docs/config/session-editor-isolation.md. `path_overrides` are EditorPaths
    fields (session_recap, session_summary, scene_extractions_dir, ...).

    ``characters`` is accepted and ignored: feature 009 deleted the ``roster``
    group, and the narrating cast is now derived from ``party.yaml``. The
    parameter survives so the call sites below read unchanged; assertions about
    ``--characters`` live in the party-roster tests instead.

    ``campaign_dir`` defaults to "" so ``_party_config_path`` looks for
    ``config/party.yaml`` relative to the cwd — which the repo does not have,
    keeping the flag absent unless a test opts in."""
    return ResolvedEditorConfig(
        paths=EditorPaths(**path_overrides),
        extract=ExtractKnobs(),
        narrate=NarrateKnobs(),
        backends=Backends(),
        session_name=None,
        profiles=[],
        active_profile=None,
        model=None,
        work_dir=work_dir,
        campaign_dir=campaign_dir,
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


# ── 018-prefer-smoothed-extractions: Narrate command source selection ───────

def _write_smoothed_scene(
    session_dir: Path,
    *,
    filename: str = "01_scene_one_smoothed_exact.md",
    scene_name: str = "Scene One",
    body: str = "smoothed narrate source\n",
) -> Path:
    smoothed = session_dir / "scene_extractions_smoothed"
    smoothed.mkdir(exist_ok=True)
    path = smoothed / filename
    path.write_text(
        f"---\nscene: {scene_name}\nsource: voice-smoothed\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def _arg_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


class _JsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_build_narrate_cmd_prefers_smoothed_when_both_layers_exist(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed_file = _write_smoothed_scene(sd)
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)
    assert _arg_after(cmd, "--scene-extraction-file") != str(sx / "01_scene_one.md")


def test_build_narrate_cmd_retains_raw_base_and_adds_smoothed_exact_file(
    tmp_path,
):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed_file = _write_smoothed_scene(
        sd,
        filename="01_scene_one_human_smoothed.md",
        body="smoothed body distinct from raw\n",
    )
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extractions") == str(sx)
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)


def test_build_narrate_cmd_uses_smoothed_parent_as_required_base_without_raw_dir(
    tmp_path,
):
    sd, gm, _sx, nd = _seed_session_dir(tmp_path)
    smoothed_file = _write_smoothed_scene(sd)
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extractions") == str(smoothed_file.parent)
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)


def test_build_narrate_cmd_re_resolves_source_after_prior_detail_load(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )
    first_detail = scene_editor.api_get_extraction(1, cfg)
    assert first_detail["narrate_source"]["active_layer"] == "raw"

    smoothed_file = _write_smoothed_scene(
        sd,
        filename="01_scene_one_created_after_detail.md",
        body="fresh smoothed source\n",
    )
    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)


def test_t024_empty_or_artifact_only_smoothed_directory_falls_back_to_raw(
    tmp_path,
):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed = sd / "scene_extractions_smoothed"
    smoothed.mkdir()
    (smoothed / "plan.md").write_text("ignored plan", encoding="utf-8")
    (smoothed / "consistency_report.md").write_text("ignored report", encoding="utf-8")
    (smoothed / "_01_scene_one.md").write_text("private note", encoding="utf-8")
    (smoothed / "01_scene_one.txt").write_text("wrong suffix", encoding="utf-8")
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extractions") == str(sx)
    assert "--scene-extraction-file" not in cmd


def test_t024_partial_smoothed_scenes_one_and_three_do_not_satisfy_scene_two(
    tmp_path,
):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    raw_three = sx / "03_scene_three.md"
    raw_three.write_text(
        "---\nscene: Scene Three\nsource: gmassist\n---\n\nraw three\n",
        encoding="utf-8",
    )
    (nd / "plan.md").write_text(
        "## Section 1\nnarrator: Soma\nscene: Scene One\nchunks: 1-1\nfocus: focus 1\n\n"
        "## Section 2\nnarrator: Brewbarry\nscene: Scene Two\nchunks: 1-1\nfocus: focus 2\n\n"
        "## Section 3\nnarrator: Soma\nscene: Scene Three\nchunks: 1-1\nfocus: focus 3\n",
        encoding="utf-8",
    )
    smoothed_one = _write_smoothed_scene(
        sd,
        filename="01_scene_one.md",
        scene_name="Scene One",
    )
    smoothed_three = _write_smoothed_scene(
        sd,
        filename="03_scene_three.md",
        scene_name="Scene Three",
    )
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    assert session_io.resolve_scene_extraction_file(
        smoothed_one.parent, scene_index=2, scene_name="Scene Two"
    ) is None
    state = scene_editor._narrate_source_state(cfg, 2, "Scene Two")
    assert "02_*.md" in (state.smoothed.reason or "")
    assert state.raw.path == sx / "02_scene_two.md"

    scene_one_cmd = scene_editor._build_narrate_cmd(None, cfg, 1)
    assert isinstance(scene_one_cmd, list), scene_one_cmd
    assert _arg_after(scene_one_cmd, "--scene-extractions") == str(sx)
    assert _arg_after(scene_one_cmd, "--scene-extraction-file") == str(smoothed_one)

    scene_two_cmd = scene_editor._build_narrate_cmd(None, cfg, 2)
    assert isinstance(scene_two_cmd, list), scene_two_cmd
    assert _arg_after(scene_two_cmd, "--scene-extractions") == str(sx)
    assert "--scene-extraction-file" not in scene_two_cmd

    scene_three_cmd = scene_editor._build_narrate_cmd(None, cfg, 3)
    assert isinstance(scene_three_cmd, list), scene_three_cmd
    assert _arg_after(scene_three_cmd, "--scene-extractions") == str(sx)
    assert _arg_after(scene_three_cmd, "--scene-extraction-file") == str(smoothed_three)


def test_t024_smoothed_exact_identity_beats_differing_slug_and_prefix(
    tmp_path,
):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed_file = _write_smoothed_scene(
        sd,
        filename="12_name_from_an_old_plan.md",
        scene_name="Scene One",
    )
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)


def test_t024_smoothed_scaffold_shadows_plain_source_in_command(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed = sd / "scene_extractions_smoothed"
    smoothed.mkdir()
    plain = smoothed / "01_scene_one.md"
    scaffold = smoothed / "01_scene_one.scaffold.md"
    plain.write_text(
        "---\nscene: Scene One\nsource: voice-smoothed\n---\n\nplain\n",
        encoding="utf-8",
    )
    scaffold.write_text(
        "---\nscene: Scene One\nsource: voice-smoothed\n---\n\nscaffold\n",
        encoding="utf-8",
    )
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extraction-file") == str(scaffold)
    assert _arg_after(cmd, "--scene-extraction-file") != str(plain)


def test_t024_smoothed_command_preserves_custom_raw_location_as_base(tmp_path):
    sd, gm, _sx, nd = _seed_session_dir(tmp_path)
    custom_raw = tmp_path / "custom-raw-extractions"
    custom_raw.mkdir()
    (custom_raw / "01_scene_one.md").write_text(
        "---\nscene: Scene One\n---\n\ncustom raw\n",
        encoding="utf-8",
    )
    smoothed_file = _write_smoothed_scene(sd)
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(custom_raw),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--scene-extractions") == str(custom_raw)
    assert _arg_after(cmd, "--scene-extraction-file") == str(smoothed_file)


def test_t024_unreadable_preferred_smoothed_blocks_raw_fallback(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    smoothed = sd / "scene_extractions_smoothed"
    smoothed.mkdir()
    unreadable = smoothed / "01_scene_one.md"
    unreadable.write_bytes(b"\xff\xfe\x00")
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    result = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(result, tuple)
    assert result[0] is None
    assert "Narrate source unreadable" in result[1]
    assert str(unreadable.resolve()) in result[1]


def test_t024_neither_source_message_names_smoothed_and_raw_directories(
    tmp_path,
):
    sd, gm, _sx, nd = _seed_session_dir(tmp_path)
    raw = tmp_path / "empty-raw-extractions"
    raw.mkdir()
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(raw),
            narration_dir=str(nd),
        ),
        session_dir=str(sd),
    )

    result = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(result, tuple)
    assert result[0] is None
    assert "No Narrate source found" in result[1]
    assert str((sd / "scene_extractions_smoothed").resolve()) in result[1]
    assert str(raw.resolve()) in result[1]


def _smoothed_boundary_cfg(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, Path, ResolvedEditorConfig]:
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n",
        encoding="utf-8",
    )
    context = tmp_path / "world-state.md"
    context.write_text("# World State\n", encoding="utf-8")
    smoothed = _write_smoothed_scene(sd)
    camp = _campaign_with_party_yaml(tmp_path)
    cfg = replace(
        _cfg(
            session_recap=str(gm),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
            vtt=str(vtt),
            campaign_dir=str(camp),
        ),
        session_dir=str(sd),
    )
    cfg.narrate.context = [str(context)]
    return sd, sx, nd, context, smoothed, cfg


def _assert_no_exact_scene_file(cmd: list[str]) -> None:
    assert "--scene-extraction-file" not in cmd


def test_t031_non_narrate_builders_stay_raw_with_smoothed_present(tmp_path):
    _sd, sx, _nd, context, smoothed, cfg = _smoothed_boundary_cfg(tmp_path)

    extract = scene_editor._build_reextract_cmd(None, cfg)
    consistency = scene_editor._build_consistency_cmd(None, cfg)
    direct_consistency = scene_editor._build_check_consistency_cmd(None, cfg)
    plan = scene_editor._build_plan_cmd(None, cfg)

    for cmd in (extract, consistency, direct_consistency, plan):
        assert isinstance(cmd, list), cmd
        _assert_no_exact_scene_file(cmd)
        assert str(smoothed) not in cmd

    assert _arg_after(extract, "--output-dir") == str(sx)
    assert _arg_after(plan, "--scene-extractions") == str(sx)
    assert "--scene-extractions" not in consistency
    assert "--scene-extractions" not in direct_consistency
    assert _arg_after(consistency, "--context") == str(context)
    assert _arg_after(direct_consistency, "--context") == str(context)


def test_t031_raw_editor_reads_and_prev_route_ignore_smoothed_source(tmp_path):
    _sd, sx, _nd, _context, smoothed, cfg = _smoothed_boundary_cfg(tmp_path)
    raw = sx / "01_scene_one.md"
    raw_prev = raw.with_name(raw.name + ".prev")
    raw_prev.write_text("raw previous version\n", encoding="utf-8")
    smoothed_prev = smoothed.with_name(smoothed.name + ".prev")
    smoothed_prev.write_text("smoothed previous version\n", encoding="utf-8")

    detail = scene_editor.api_get_extraction(1, cfg)
    assert isinstance(detail, dict)
    assert detail["narrate_source"]["active_layer"] == "smoothed"
    assert detail["content"] == raw.read_text(encoding="utf-8")
    assert "smoothed narrate source" not in detail["content"]

    prev = scene_editor.api_get_prev_extraction(1, cfg)
    assert isinstance(prev, dict)
    assert prev["content"] == "raw previous version\n"
    assert prev["current"] == raw.read_text(encoding="utf-8")
    assert "smoothed previous version" not in prev["content"]


def test_t031_put_extraction_and_reviewed_marker_stay_on_raw_file(tmp_path):
    _sd, sx, _nd, _context, smoothed, cfg = _smoothed_boundary_cfg(tmp_path)
    raw = sx / "01_scene_one.md"
    original_smoothed = smoothed.read_text(encoding="utf-8")

    import asyncio

    save_result = asyncio.run(
        scene_editor.api_save_extraction(
            1, _JsonRequest({"content": "edited raw body\n"}), cfg
        )
    )
    assert save_result == {"ok": True}
    assert raw.read_text(encoding="utf-8") == "edited raw body\n"
    assert smoothed.read_text(encoding="utf-8") == original_smoothed

    reviewed_result = asyncio.run(
        scene_editor.api_set_reviewed(1, _JsonRequest({"reviewed": True}), cfg)
    )
    assert reviewed_result == {"ok": True, "reviewed": True}
    assert raw.with_name(raw.name + ".reviewed").exists()
    assert not smoothed.with_name(smoothed.name + ".reviewed").exists()
    assert scene_editor.api_get_reviewed(1, cfg) == {"reviewed": True}


# ── Pass 5 style-input forwarding (#299) ─────────────────────────────────────
# `_build_narrate_cmd` is the ONLY seam where the genre rulebook, the voice
# specs, the style examples and the character roster enter the subprocess.
# Until #299 nothing asserted any of them reached argv, on either side of the
# `if value:` guard — which is how #295 (no campaign delivering a rulebook to
# Pass 5) stayed invisible with a green suite. `tests/test_narrate_genre_file.py`
# covers the reader and the describer; these cover the hand-off between them.


def _narrate_cfg(tmp_path: Path, **overrides) -> ResolvedEditorConfig:
    """A `_cfg` with the four Narrate preconditions (summary, extractions,
    narration dir, plan.md) already satisfied, so a test can vary one input."""
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    (nd / "plan.md").write_text("plan", encoding="utf-8")
    base = dict(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
    )
    base.update(overrides)
    return _cfg(**base)


def test_narrate_cmd_forwards_the_genre_rulebook_path(tmp_path):
    """The #295 seam: a configured rulebook must reach sd_narrate as a PATH.

    Passing the text was #276's defect; passing nothing at all was #295's.
    """
    genre = tmp_path / "_genre.md"
    genre.write_text("# Register\n\nFirst person, past tense.\n", encoding="utf-8")
    cfg = _narrate_cfg(tmp_path, genre_file=str(genre))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--narration-genre-file") + 1] == str(genre)
    # The rulebook's TEXT must never be on the command line (#276 fix 2).
    assert not any("First person" in part for part in cmd)


def test_narrate_cmd_omits_the_genre_flag_when_unset(tmp_path):
    """Unset means Pass 5 runs with no genre directive at all.

    Asserted so the state #295 describes is pinned rather than incidental:
    the router emits nothing, and `_load_genre_file(None)` is what decides
    how loud that is.
    """
    cfg = _narrate_cfg(tmp_path)

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert "--narration-genre-file" not in cmd


def test_narrate_cmd_forwards_the_two_style_directories(tmp_path):
    """Both directories still travel, for one job: reporting files nothing
    declares. A character's own voice and example files are named by its
    party.yaml entry now, so `--characters` is gone — it was the routing key
    for a rule that no longer exists (feature 009)."""
    voice = tmp_path / "voice"
    voice.mkdir()
    examples = tmp_path / "examples"
    examples.mkdir()
    cfg = _narrate_cfg(tmp_path, voice_dir=str(voice), examples_dir=str(examples))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-dir") + 1] == str(voice)
    assert cmd[cmd.index("--examples") + 1] == str(examples)
    assert "--characters" not in cmd


def test_narrate_cmd_omits_style_flags_when_unset(tmp_path):
    cfg = _narrate_cfg(tmp_path)

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    for flag in ("--voice-dir", "--examples", "--characters"):
        assert flag not in cmd


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


def test_build_reextract_cmd_omits_force_by_default(tmp_path):
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
    assert "--force" not in cmd


def test_build_reextract_cmd_forwards_force_when_requested(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
    )
    cmd = scene_editor._build_reextract_cmd(None, cfg, force=True)
    assert isinstance(cmd, list)
    assert "--force" in cmd


def test_build_reextract_cmd_forwards_default_max_tokens(tmp_path):
    """8192 is ExtractKnobs' own default — matches scene_extract.py's own
    --max-tokens default, so an unconfigured campaign's command is
    unchanged from before this field existed."""
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
    assert "--max-tokens" in cmd
    assert cmd[cmd.index("--max-tokens") + 1] == "8192"


def test_build_reextract_cmd_forwards_configured_max_tokens(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
    )
    cfg.extract.tokens = 12000
    cmd = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--max-tokens" in cmd
    assert cmd[cmd.index("--max-tokens") + 1] == "12000"


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


def test_shared_scene_resolver_prefers_exact_identity_before_prefix(tmp_path):
    sx, _cfg = _sx_cfg(tmp_path)
    prefix_match = sx / "05_wrong_scene.md"
    prefix_match.write_text(
        "---\nscene: The Wrong Scene\n---\n\nprefix body\n",
        encoding="utf-8",
    )
    identity_match = sx / "12_the_statue_returned.md"
    identity_match.write_text(
        "---\nscene: The Statue Returned\n---\n\nidentity body\n",
        encoding="utf-8",
    )

    got = session_io.resolve_scene_extraction_file(
        sx, scene_index=5, scene_name="The Statue Returned")

    assert got == identity_match


def test_shared_scene_resolver_uses_prefix_to_disambiguate_duplicate_identity(
    tmp_path,
):
    sx, _cfg = _sx_cfg(tmp_path)
    first = sx / "01_combat.md"
    first.write_text(
        "---\nscene: Combat\n---\n\nfirst combat\n",
        encoding="utf-8",
    )
    second = sx / "02_combat.md"
    second.write_text(
        "---\nscene: Combat\n---\n\nsecond combat\n",
        encoding="utf-8",
    )

    got = session_io.resolve_scene_extraction_file(
        sx, scene_index=2, scene_name="Combat")

    assert got == second


def test_shared_scene_resolver_falls_back_to_the_two_digit_prefix(tmp_path):
    sx, _cfg = _sx_cfg(tmp_path)
    expected = sx / "05_the_original_stage_title.md"
    expected.write_text(
        "---\nscene: The Original Stage Title\n---\n\nbody\n",
        encoding="utf-8",
    )

    got = session_io.resolve_scene_extraction_file(
        sx, scene_index=5, scene_name="The Retitled Plan Scene")

    assert got == expected


def test_shared_scene_resolver_ignores_sibling_artifacts(tmp_path):
    sx, _cfg = _sx_cfg(tmp_path)
    (sx / "plan.md").write_text("plan", encoding="utf-8")
    (sx / "consistency_report.md").write_text("report", encoding="utf-8")
    (sx / "_05_private_notes.md").write_text("notes", encoding="utf-8")
    (sx / "05_scene_five.txt").write_text("not markdown", encoding="utf-8")
    (sx / "scene_five.md").write_text("missing prefix", encoding="utf-8")

    got = session_io.resolve_scene_extraction_file(
        sx, scene_index=5, scene_name="Scene Five")

    assert got is None


def test_shared_scene_resolver_uses_scaffold_precedence(tmp_path):
    sx, _cfg = _sx_cfg(tmp_path)
    plain = sx / "05_the_statue.md"
    plain.write_text(
        "---\nscene: The Statue\n---\n\nsource body\n",
        encoding="utf-8",
    )
    scaffold = sx / "05_the_statue.scaffold.md"
    scaffold.write_text(
        "---\nscene: The Statue\n---\n\nedited body\n",
        encoding="utf-8",
    )

    got = session_io.resolve_scene_extraction_file(
        sx, scene_index=5, scene_name="The Statue")

    assert got == scaffold
    assert got != plain


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


def test_codex_editor_keeps_stage_artifacts_and_explicit_force(tmp_path, monkeypatch):
    """A subscription selection must not change editor destinations or resume rules."""
    from campaignlib.selection import ModelSelection

    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        vtt=str(vtt),
    )
    monkeypatch.setattr(
        scene_editor,
        "_editor_service_selection",
        lambda _cfg: (ModelSelection(backend="codex-cli", model="gpt-5-codex"), None),
    )

    enhance = scene_editor._build_enhance_cmd(None, cfg)
    resume = scene_editor._build_reextract_cmd(None, cfg, force=False)
    force = scene_editor._build_reextract_cmd(None, cfg, force=True)

    assert isinstance(enhance, list) and "codex-cli" in enhance
    assert str(sd / "session-summary.md") in enhance
    assert isinstance(resume, list) and "--force" not in resume
    assert str(sx) in resume
    assert isinstance(force, list) and "--force" in force


def _codex_editor_cfg(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    return _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        vtt=str(vtt),
    )


def test_codex_editor_omits_inherited_claude_model(tmp_path, monkeypatch):
    from campaignlib.selection import ModelSelection

    cfg = _codex_editor_cfg(tmp_path)
    monkeypatch.setattr(
        scene_editor,
        "_editor_service_selection",
        lambda _cfg: (ModelSelection(backend="codex-cli", model=None), None),
    )
    cmd = scene_editor._build_enhance_cmd(None, cfg)
    assert "codex-cli" in cmd
    assert "--model" not in cmd


def test_codex_editor_refuses_explicit_claude_model(tmp_path, monkeypatch):
    from campaignlib.selection import ModelSelection
    from server.platform_config_service import IncompatibleSelection

    cfg = _codex_editor_cfg(tmp_path)
    monkeypatch.setattr(
        scene_editor,
        "_editor_service_selection",
        lambda _cfg: (ModelSelection(backend="codex-cli", model="claude-sonnet-4-6"), None),
    )
    with pytest.raises(IncompatibleSelection):
        scene_editor._build_enhance_cmd(None, cfg)


def test_editor_preserves_openrouter_selection(tmp_path, monkeypatch):
    from campaignlib.selection import ModelSelection

    cfg = _codex_editor_cfg(tmp_path)
    monkeypatch.setattr(
        scene_editor,
        "_editor_service_selection",
        lambda _cfg: (ModelSelection(backend="openrouter", model="anthropic/claude-sonnet-4"), "https://router"),
    )
    cmd = scene_editor._build_enhance_cmd(None, cfg)
    assert cmd[cmd.index("--backend") + 1] == "openrouter"
    assert cmd[cmd.index("--model") + 1] == "anthropic/claude-sonnet-4"


def test_editor_status_exposes_codex_run_issue_counts(tmp_path):
    """The review strip reads the same typed issue counts for any backend."""
    import json

    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    report = nd / "quote_report.md"
    report.write_text("# report\n", encoding="utf-8")
    report.with_suffix(".json").write_text(json.dumps({
        "counts": {"verified": 3, "near": 1, "unverified": 2,
                    "unscored": 0, "exempt": 0},
        "refusals": {"total": 1},
    }), encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm), session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx), narration_dir=str(nd), vtt=str(vtt),
    )

    status = scene_editor.api_pipeline_status(cfg)
    assert status["verify"]["verified"] == 3
    assert status["verify"]["unverified"] == 2
    assert status["verify"]["refused"] == 1


# ── --party-config plumbing (#265) ───────────────────────────────────────────
#
# The sheet-frontmatter roster was unreachable from the Session Doc Editor:
# the readers take --party-config, the editor only ever passed --party, so
# args.party_config was always None for UI runs and roster_from_config's
# per-character diagnostics never ran. The fallback was silent exactly where
# it mattered. The path is resolved by declaration (Track 0), not configured.

def _campaign_with_party_yaml(tmp_path) -> Path:
    """A campaign dir holding the one declared <config>/party.yaml."""
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "party.yaml").write_text(
        "characters:\n- name: Brewbarry\n  sheet: docs/party/brewbarry.md\n",
        encoding="utf-8")
    return tmp_path


def test_party_config_path_resolves_the_declared_location(tmp_path):
    camp = _campaign_with_party_yaml(tmp_path)
    cfg = _cfg(campaign_dir=str(camp))
    assert scene_editor._party_config_path(cfg) == camp / "config" / "party.yaml"


def test_party_config_path_is_none_when_absent(tmp_path):
    """A campaign with no roster config must not get a flag pointing at a
    file that isn't there — the CLI would warn and fall back anyway, but the
    router should not be the one inventing the path."""
    cfg = _cfg(campaign_dir=str(tmp_path))
    assert scene_editor._party_config_path(cfg) is None


def test_party_config_honours_a_renamed_config_dir(tmp_path):
    """Mirrors PlatformConfigService.config_path_base (campaign_dir /
    config_dir) rather than hardcoding 'config', so a campaign that renamed
    its config directory is still found."""
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "party.yaml").write_text("characters: []\n", encoding="utf-8")
    cfg = _cfg(campaign_dir=str(tmp_path))
    object.__setattr__(cfg, "config_dir", "conf")
    assert scene_editor._party_config_path(cfg) == tmp_path / "conf" / "party.yaml"


def test_reextract_cmd_passes_party_config(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    camp = _campaign_with_party_yaml(tmp_path)
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
        party=str(tmp_path / "party.md"),
        campaign_dir=str(camp),
    )
    cmd = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert cmd[cmd.index("--party-config") + 1] == str(camp / "config" / "party.yaml")
    # party.md still goes along — which roster wins is the reader's decision,
    # not the router's.
    assert cmd[cmd.index("--party") + 1] == str(tmp_path / "party.md")


# (The "--party alone, no config" case is covered by
# test_party_without_a_config_refuses_instead_of_emitting_a_fatal_flag below.
# An earlier version of this file asserted the router emitted `--party` alone
# there — which is exactly the defect: that flag combination is fatal
# downstream since #265 deleted the party.md roster fallback.)


def test_narrate_cmd_passes_party_config(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    (nd / "plan.md").write_text("plan", encoding="utf-8")
    camp = _campaign_with_party_yaml(tmp_path)
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        party=str(tmp_path / "party.md"),
        campaign_dir=str(camp),
    )
    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)
    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--party-config") + 1] == str(camp / "config" / "party.yaml")


def test_plan_cmd_never_gets_party_config(tmp_path):
    """sd_plan takes --party as raw prompt text and declares no
    --party-config; passing one would abort the run with 'unrecognized
    arguments'."""
    import inspect
    src = inspect.getsource(scene_editor._build_plan_cmd)
    assert "--party-config" not in src
    assert "_party_args" not in src


def test_enhance_cmd_stays_roster_free(tmp_path):
    """enhance_summary gates its roster block on `if party_path is not None`,
    so --party-config alone is inert there; adding --party would newly switch
    on speaker-attribution checking in Stage 1, which is a behaviour change
    rather than plumbing."""
    import inspect
    src = inspect.getsource(scene_editor._build_enhance_cmd)
    assert "_party_args" not in src


def test_party_without_a_config_refuses_instead_of_emitting_a_fatal_flag(tmp_path):
    """#265 made `--party` alone fatal downstream. Emitting it anyway would
    hand the GM a subprocess crash naming --party-config, a flag the UI does
    not expose. Refuse here, where the editor renders (None, reason)."""
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
        party=str(tmp_path / "party.md"),
        campaign_dir=str(tmp_path),          # no config/party.yaml here
    )
    result = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(result, tuple)
    assert result[0] is None
    assert "party.yaml" in result[1] and "sheet_frontmatter" in result[1]


def test_narrate_also_refuses_rather_than_emitting_party_alone(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    (nd / "plan.md").write_text("plan", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        party=str(tmp_path / "party.md"),
        campaign_dir=str(tmp_path),
    )
    result = scene_editor._build_narrate_cmd(None, cfg, 1)
    assert isinstance(result, tuple) and result[0] is None


def test_no_party_configured_at_all_emits_neither_flag(tmp_path):
    """A campaign that never set paths.party is not misconfigured — it just
    runs without speaker normalisation, as it always could."""
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    cfg = _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
        campaign_dir=str(tmp_path),
    )
    cmd = scene_editor._build_reextract_cmd(None, cfg)
    assert isinstance(cmd, list)
    assert "--party" not in cmd and "--party-config" not in cmd


# ── #300: a voice_dir that cannot deliver is refused, not forwarded ──────────
#
# Mirrors `_party_args`: the editor turns `(None, reason)` into readable text,
# where the subprocess's stderr reaches the GM only as a failed run they have
# to open a terminal to read.


def _voice_cfg(tmp_path: Path, keep_plan: bool = False,
               **overrides) -> ResolvedEditorConfig:
    """A cfg with Narrate's preconditions satisfied, so a test can vary voice_dir.

    `keep_plan=True` retains `_seed_session_dir`'s real two-section plan
    (Soma then Brewbarry) for the tests that need a narrator to resolve.
    """
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    if not keep_plan:
        (nd / "plan.md").write_text("plan", encoding="utf-8")
    return _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        **overrides,
    )


def test_narrate_refuses_a_voice_dir_that_is_not_a_directory(tmp_path):
    cfg = _voice_cfg(tmp_path, voice_dir=str(tmp_path / "nope"))

    result = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(result, tuple) and result[0] is None
    assert "not a directory" in result[1]


def test_narrate_does_not_refuse_a_voice_dir_with_no_specs_yet(tmp_path):
    """`new_workspace` creates voice/ empty and `derive` fills voice_dir in
    from its mere existence, so this state is usually the tool's doing rather
    than a GM declaration. Refusing here would break Narrate on every fresh
    campaign — and on any campaign holding only `voice/_genre.md`."""
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "_genre.md").write_text("# Register\n", encoding="utf-8")
    cfg = _voice_cfg(tmp_path, voice_dir=str(vd))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-dir") + 1] == str(vd)


def test_a_narrator_without_a_spec_is_no_longer_the_routers_refusal(tmp_path):
    """This refusal existed because the router could describe the miss better
    than the subprocess could: the live `sequioa`/`sequoia_voice.md` case in
    toee produced an opaque failed run rather than a sentence naming the typo.

    Feature 009 moved the question. A narrator's spec is DECLARED by its roster
    entry, and `sd_narrate`'s pre-flight names the character and the path
    before spending a token — a better message than this one, and one the CLI
    has too. Duplicating it here would mean reading party.yaml twice and
    keeping two wordings in step.
    """
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "brewbarry_new_pipeline.md").write_text("spec\n", encoding="utf-8")
    cfg = _voice_cfg(tmp_path, voice_dir=str(vd), keep_plan=True)

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-dir") + 1] == str(vd)


def test_narrate_allows_a_scene_whose_own_narrator_resolves(tmp_path):
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "brewbarry_new_pipeline.md").write_text("spec\n", encoding="utf-8")
    cfg = _voice_cfg(tmp_path, voice_dir=str(vd), keep_plan=True)

    cmd = scene_editor._build_narrate_cmd(None, cfg, 2)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-dir") + 1] == str(vd)


def test_narrate_forwards_a_usable_voice_dir(tmp_path):
    vd = tmp_path / "voice"
    vd.mkdir()
    (vd / "_genre.md").write_text("# Register\n", encoding="utf-8")
    (vd / "vukradin_new_pipeline.md").write_text("spec\n", encoding="utf-8")
    cfg = _voice_cfg(tmp_path, voice_dir=str(vd))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-dir") + 1] == str(vd)


def test_no_voice_dir_configured_is_not_a_refusal(tmp_path):
    """Rendering without voice specs stays a legitimate mode."""
    cfg = _voice_cfg(tmp_path)

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert "--voice-dir" not in cmd


# ── The router validates the declared directories; the bleed is structural ──
#
# The refusals this block used to hold — "a per-character file would reach
# every narrator", "the roster is incomplete" — described the fall-through
# feature 009 deleted. There is no longer a way for an undeclared file to reach
# a prompt, so there is nothing for the router to refuse on those grounds. What
# remains is the typo: a declared directory that is not a directory.


def _ex_cfg(tmp_path: Path, characters: str | None = None,
            **overrides) -> ResolvedEditorConfig:
    """Narrate preconditions satisfied, keeping the seeded Soma/Brewbarry plan.

    `characters` no longer exists as config (feature 009); the parameter is
    accepted and ignored so the call sites below read unchanged.
    """
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    return _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        narration_dir=str(nd),
        **overrides,
    )


def _examples(tmp_path: Path, *names: str) -> Path:
    ed = tmp_path / "examples"
    ed.mkdir()
    for n in names:
        (ed / f"{n}.md").write_text(f"{n} style\n", encoding="utf-8")
    return ed


def test_narrate_refuses_examples_dir_that_is_not_a_directory(tmp_path):
    cfg = _ex_cfg(tmp_path, examples_dir=str(tmp_path / "nope"))

    result = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(result, tuple) and result[0] is None
    assert "is not a directory" in result[1]


def test_narrate_refuses_voice_dir_that_is_not_a_directory(tmp_path):
    cfg = _ex_cfg(tmp_path, voice_dir=str(tmp_path / "nope"))

    result = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(result, tuple) and result[0] is None
    assert "is not a directory" in result[1]


def test_a_file_matching_a_narrators_name_is_no_longer_a_refusal(tmp_path):
    """`soma.md` sitting in examples/ used to mean every narrator would read
    Soma's style reference, because an unmatched file fell through to a global
    block. Nothing falls through now: an undeclared file reaches nobody, and
    the CLI reports it as an orphan rather than the router refusing the run."""
    ed = _examples(tmp_path, "soma")
    cfg = _ex_cfg(tmp_path, examples_dir=str(ed))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--examples") + 1] == str(ed)


def test_narrate_allows_house_style_examples(tmp_path):
    """toee's shape: files that belong to the campaign rather than a character.
    They reach every narrator because `shared_examples:` says so."""
    ed = _examples(tmp_path, "political_maneuvering", "combat_and_consequences")
    cfg = _ex_cfg(tmp_path, examples_dir=str(ed))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--examples") + 1] == str(ed)
    assert "--characters" not in cmd


def test_empty_examples_dir_is_not_refused(tmp_path):
    ed = tmp_path / "examples"
    ed.mkdir()
    cfg = _ex_cfg(tmp_path, examples_dir=str(ed))

    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--examples") + 1] == str(ed)


# ── 013-batched-scene-extraction: the three-state resolution at the route ──
#
# DM-18/DM-19/FR-007a. `batch_scenes` on GET /api/editor/extract is
# `int | None`, and absent-vs-present is load-bearing:
#
#   omitted  -> the GM did not touch the control; resolve from
#               cfg.batch_scenes_effective (the config pin, else True on
#               claude-code, False elsewhere)
#   0 or 1   -> an explicit per-run choice that WINS over both
#
# A plain `int = 0` default would make "unchecked" and "untouched"
# indistinguishable and permanently defeat the subscription pre-selection,
# which is the entire point of the feature's activation design. The resolved
# boolean is then ALWAYS rendered as an explicit flag (DM-19) so the streamed
# command line stays copyable.

def _reextract_cfg(tmp_path):
    sd, gm, sx, nd = _seed_session_dir(tmp_path)
    vtt = sd / "session.vtt"
    vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n", encoding="utf-8")
    return _cfg(
        session_recap=str(gm),
        session_summary=str(sd / "session-summary.md"),
        scene_extractions_dir=str(sx),
        vtt=str(vtt),
    )


def test_reextract_cmd_always_renders_an_explicit_batch_scenes_flag(tmp_path):
    """DM-19: never omitted, so the copyable command line is unambiguous."""
    cfg = _reextract_cfg(tmp_path)
    for resolved in (True, False):
        cmd = scene_editor._build_reextract_cmd(None, cfg, batch_scenes=resolved)
        assert isinstance(cmd, list)
        assert ("--batch-scenes" in cmd) is resolved
        assert ("--no-batch-scenes" in cmd) is (not resolved)


def test_reextract_cmd_batch_scenes_flag_is_not_confused_with_batch(tmp_path):
    """--batch (Message Batches) and --batch-scenes are separate features."""
    cfg = _reextract_cfg(tmp_path)
    cmd = scene_editor._build_reextract_cmd(None, cfg, batch_scenes=True)
    assert "--batch-scenes" in cmd
    # Bare --batch must NOT appear just because --batch-scenes did.
    assert "--batch" not in cmd


def _cmd_from_route(cfg, batch_scenes):
    """Drive the REAL route and capture the argv it builds.

    Calls `scene_editor.api_extract` rather than re-deriving its resolution
    rule in the test. A test that recomputes `bool(x) if x is not None else
    default` and asserts on its own arithmetic passes whatever the route
    does, which is the opposite of a regression guard.
    """
    import asyncio
    from unittest.mock import patch
    captured = {}

    def fake_stream_subprocess(cmd, **kw):
        captured["cmd"] = cmd
        async def _empty():
            if False:
                yield ""
        return _empty()

    with patch.object(scene_editor, "stream_subprocess", fake_stream_subprocess):
        asyncio.run(scene_editor.api_extract(
            None, force=0, batch_scenes=batch_scenes, cfg=cfg))
    return captured["cmd"]


def test_batch_scenes_omitted_resolves_from_effective_not_from_false(tmp_path):
    """The trap: `None` means untouched and must NOT collapse to False.

    If this regresses, the subscription pre-selection still SHOWS in the UI
    but never reaches the subprocess — the checkbox looks on and the run is
    per-scene. Nothing in the output says so.
    """
    import dataclasses
    cfg = dataclasses.replace(_reextract_cfg(tmp_path), batch_scenes_effective=True)
    cmd = _cmd_from_route(cfg, batch_scenes=None)
    assert "--batch-scenes" in cmd
    assert "--no-batch-scenes" not in cmd


def test_batch_scenes_omitted_follows_a_false_effective_too(tmp_path):
    """Same path, other direction — omission follows the default, not a constant."""
    import dataclasses
    cfg = dataclasses.replace(_reextract_cfg(tmp_path), batch_scenes_effective=False)
    cmd = _cmd_from_route(cfg, batch_scenes=None)
    assert "--no-batch-scenes" in cmd
    assert "--batch-scenes" not in cmd


def test_explicit_choice_beats_the_effective_default_both_ways(tmp_path):
    """An explicit per-run choice outranks the backend default in both directions."""
    import dataclasses
    # separate roots: _seed_session_dir builds a dated dir and collides on reuse
    # separate roots: _seed_session_dir builds a dated dir and collides on reuse
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    on = dataclasses.replace(_reextract_cfg(tmp_path / "a"), batch_scenes_effective=True)
    off = dataclasses.replace(_reextract_cfg(tmp_path / "b"), batch_scenes_effective=False)

    # effective True, GM explicitly unticked -> off wins
    assert "--no-batch-scenes" in _cmd_from_route(on, batch_scenes=0)
    # effective False, GM explicitly ticked -> on wins
    assert "--batch-scenes" in _cmd_from_route(off, batch_scenes=1)


def test_reextract_cmd_forwards_the_batched_ceiling(tmp_path):
    """--batch-max-tokens is the per-GROUP ceiling, distinct from --max-tokens."""
    cfg = _reextract_cfg(tmp_path)
    cfg.extract.batch_tokens = 48000
    cfg.extract.tokens = 8192
    cmd = scene_editor._build_reextract_cmd(None, cfg, batch_scenes=True)
    assert "--batch-max-tokens" in cmd
    assert cmd[cmd.index("--batch-max-tokens") + 1] == "48000"
    assert cmd[cmd.index("--max-tokens") + 1] == "8192"


# ── Message Batches and batched scenes must never be emitted together ───────
#
# scene_extract refuses `--batch` + `--batch-scenes` outright (exit 1, before
# any work). They arrive here from two places that cannot see each other:
# `--batch` from the stored selection profile via `_selection_args`, and
# `batch_scenes` already resolved from the per-run control / config pin /
# backend default. Both can land true, and the run then died naming a flag
# the GM never typed, with nothing written.

def _batch_on(cfg):
    """The same cfg with Message Batches on in the active backend profile."""
    import dataclasses
    prof = cfg.backends.anthropic.model_copy(update={"batch": True})
    return dataclasses.replace(
        cfg, backends=cfg.backends.model_copy(update={"anthropic": prof}))


def _route(cfg, *, batch_scenes=None, rc=0):
    """Drive the real route; return (argv, streamed chunks, logged knobs)."""
    import asyncio
    from unittest.mock import patch

    captured: dict = {}

    def fake_stream_subprocess(cmd, **kw):
        captured["cmd"] = cmd
        on_complete = kw.get("on_complete")

        async def _empty():
            if on_complete is not None:
                on_complete(rc)
            if False:
                yield ""
        return _empty()

    def fake_record(cfg_, **kw):
        captured["knobs"] = kw.get("knobs")

    chunks: list[str] = []

    async def _drive():
        resp = await scene_editor.api_extract(
            None, force=0, batch_scenes=batch_scenes, cfg=cfg)
        async for chunk in resp.body_iterator:
            chunks.append(chunk)

    with patch.object(scene_editor, "stream_subprocess", fake_stream_subprocess), \
            patch.object(scene_editor, "_record_activity", fake_record):
        asyncio.run(_drive())
    return captured["cmd"], chunks, captured.get("knobs")


@pytest.mark.parametrize("batch_scenes", [None, 1])
def test_batch_selection_stands_batched_scenes_down(tmp_path, batch_scenes):
    """Whether batching came from the config pin (None -> effective True) or
    from the GM ticking the box this run (1), the pair is never emitted."""
    import dataclasses
    cfg = _batch_on(dataclasses.replace(_reextract_cfg(tmp_path),
                                        batch_scenes_effective=True))
    cmd, _chunks, _knobs = _route(cfg, batch_scenes=batch_scenes)
    assert "--batch" in cmd
    assert "--batch-scenes" not in cmd
    assert "--no-batch-scenes" in cmd, "DM-19: the flag is still explicit"


def test_the_refused_pair_is_never_built(tmp_path):
    """The property, stated as scene_extract states it: not both."""
    import dataclasses
    base = _batch_on(_reextract_cfg(tmp_path))
    for effective in (True, False):
        for per_run in (None, 0, 1):
            cfg = dataclasses.replace(base, batch_scenes_effective=effective)
            cmd, _c, _k = _route(cfg, batch_scenes=per_run)
            assert not ("--batch" in cmd and "--batch-scenes" in cmd), (
                f"effective={effective} per_run={per_run} builds the command "
                f"scene_extract refuses")


def test_without_message_batches_batched_scenes_are_untouched(tmp_path):
    """The stand-down must not reach further than the conflict it resolves."""
    import dataclasses
    cfg = dataclasses.replace(_reextract_cfg(tmp_path),
                              batch_scenes_effective=True)
    cmd, _c, _k = _route(cfg)
    assert "--batch" not in cmd
    assert "--batch-scenes" in cmd


def test_a_stood_down_run_says_so_before_it_starts(tmp_path):
    import dataclasses
    cfg = _batch_on(dataclasses.replace(_reextract_cfg(tmp_path),
                                        batch_scenes_effective=True))
    _cmd, chunks, _knobs = _route(cfg)
    assert any("stood down" in c for c in chunks), \
        "a control that silently does nothing is the failure being prevented"


def test_a_normal_run_carries_no_stand_down_notice(tmp_path):
    import dataclasses
    cfg = dataclasses.replace(_reextract_cfg(tmp_path),
                              batch_scenes_effective=True)
    _cmd, chunks, _knobs = _route(cfg)
    assert not any("stood down" in c for c in chunks)


def test_the_activity_log_records_what_ran_not_what_was_asked(tmp_path):
    """A knob record that disagrees with its own command line is worse than
    none — it is the evidence a later cost question gets answered from."""
    import dataclasses
    cfg = _batch_on(dataclasses.replace(_reextract_cfg(tmp_path),
                                        batch_scenes_effective=True))
    cmd, _chunks, knobs = _route(cfg, batch_scenes=1)
    assert knobs is not None
    assert knobs["batch_scenes"] is False
    assert ("--batch-scenes" in cmd) is knobs["batch_scenes"]


# ── Direct US4 scene-editor faces (feature 016, T044) ──────────────────────


def _codex_cfg(cfg: ResolvedEditorConfig) -> ResolvedEditorConfig:
    """Select Codex in the editor-owned profile for command-builder tests."""
    cfg.backends.active = "codex-cli"
    cfg.backends.codex_cli.model = "gpt-5-codex"
    return cfg


def test_check_consistency_cmd_forwards_selected_document_context_and_codex(
    tmp_path,
):
    """The direct audit face preserves its input/context and model selection."""
    summary = tmp_path / "session-summary.md"
    summary.write_text("# Session summary\n", encoding="utf-8")
    context = tmp_path / "world-state.md"
    context.write_text("# World state\n", encoding="utf-8")
    narration = tmp_path / "narration"
    narration.mkdir()
    cfg = _codex_cfg(
        _cfg(session_summary=str(summary), narration_dir=str(narration))
    )
    cfg.narrate.context = [str(context)]

    cmd = scene_editor._build_check_consistency_cmd(None, cfg)

    assert isinstance(cmd, list), cmd
    assert "check_consistency" in cmd[0]
    assert str(summary) in cmd
    assert cmd[cmd.index("--context") + 1] == str(context)
    assert "--output" in cmd
    assert str(narration / "consistency_report.md") in cmd
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


def test_voice_compare_cmd_forwards_selected_vtt_voice_and_codex(tmp_path):
    vtt = tmp_path / "session.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    voice = tmp_path / "soma.md"
    voice.write_text("Measured, precise, and calm.\n", encoding="utf-8")
    cfg = _codex_cfg(_cfg(vtt=str(vtt), voice_dir=str(tmp_path)))

    cmd = scene_editor._build_voice_compare_cmd(
        None, cfg, player="Soma", voice_file=str(voice), update=False
    )

    assert isinstance(cmd, list), cmd
    assert "vtt_voice_compare" in cmd[0]
    assert str(vtt) in cmd
    assert cmd[cmd.index("--player") + 1] == "Soma"
    assert cmd[cmd.index("--voice-file") + 1] == str(voice)
    assert "--update" not in cmd
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


def test_voice_compare_cmd_resolves_relative_voice_against_session_dir(tmp_path):
    vtt = tmp_path / "session.vtt"
    vtt.write_text("WEBVTT\n", encoding="utf-8")
    voice = tmp_path / "soma.md"
    voice.write_text("Measured, precise, and calm.\n", encoding="utf-8")
    cfg = replace(_codex_cfg(_cfg(vtt=str(vtt))), session_dir=str(tmp_path))

    cmd = scene_editor._build_voice_compare_cmd(
        None, cfg, player="Soma", voice_file="soma.md", update=False
    )

    assert isinstance(cmd, list), cmd
    assert cmd[cmd.index("--voice-file") + 1] == str(voice)


def test_polish_cmd_preserves_assembled_artifacts_and_checkpoint(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    recap = session / "gm-assist.md"
    recap.write_text("# Recap\n", encoding="utf-8")
    assembled = session / "gm-assist-doc.md"
    assembled.write_text("# Assembled\n", encoding="utf-8")
    voice = tmp_path / "voice"
    voice.mkdir()
    party = tmp_path / "party.md"
    party.write_text("# Party\n", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    (config / "party.yaml").write_text("characters: []\n", encoding="utf-8")
    cfg = _codex_cfg(
        _cfg(
            session_recap=str(recap),
            voice_dir=str(voice),
            party=str(party),
            campaign_dir=str(tmp_path),
        )
    )

    cmd = scene_editor._build_polish_cmd(None, cfg)

    assert isinstance(cmd, list), cmd
    assert "polish" in cmd[0]
    assert str(assembled) in cmd
    assert cmd[cmd.index("--recap") + 1] == str(recap)
    assert "--output" in cmd and "--changelog" in cmd
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"
    # Polish is an explicit post-assemble review checkpoint: it must not
    # silently approve narration or chain into another stage.
    assert "--approve" not in cmd
    assert "--narrate" not in cmd
