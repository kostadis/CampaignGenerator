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
    ScrubKnobs,
)


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
        narrate=NarrateKnobs(),
        scrub=ScrubKnobs(),
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
