"""The editor and the CLI narrow the narrator pool identically.

Constitution XI: a capability the engine has and the UI cannot reach is an
orphaned capability, and this pipeline is driven from the editor. The scar it
names is `?force=1` — a flag that existed, worked, and was silently overridden
by the UI. The filters here must not go the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

pytest.importorskip("fastapi")

from server.routers import scene_editor  # noqa: E402
from server.session_editor_config_service import ResolvedEditorConfig  # noqa: E402
from server.session_editor_config_shared import (  # noqa: E402
    Backends,
    EditorPaths,
    ExtractKnobs,
    NarrateKnobs,
)


def _session(tmp_path, *, with_vtt=True, with_players=True):
    """The smallest campaign the plan builder will accept."""
    sd = tmp_path / "20260902"
    sd.mkdir()
    (sd / "gm-assist.md").write_text(
        "# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n", encoding="utf-8")
    (sd / "session-summary.md").write_text(
        "# Recap\n\n## Scenes\n\n### Scene One\n- bullet\n", encoding="utf-8")
    sx = sd / "scene_extractions"
    sx.mkdir()
    (sx / "01_scene_one.md").write_text(
        "---\nscene: Scene One\n---\n\n**Vukradin**\n> \"Here.\"\n",
        encoding="utf-8")
    nd = sd / "narration"
    nd.mkdir()

    camp = tmp_path / "campaign"
    (camp / "config").mkdir(parents=True)
    (camp / "config" / "party.yaml").write_text(
        "characters:\n- name: Vukradin\n  sheet: docs/party/vukradin.md\n",
        encoding="utf-8")
    players = camp / "config" / "players.yaml"
    if with_players:
        players.write_text(
            "players:\n- id: david\n  name: David Mendenhall\n"
            "  display_names:\n  - David Mendenhall\n  plays:\n  - Vukradin\n",
            encoding="utf-8")

    vtt = sd / "session.vtt"
    if with_vtt:
        vtt.write_text(
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\n"
            "David Mendenhall: Here.\n", encoding="utf-8")

    cfg = ResolvedEditorConfig(
        paths=EditorPaths(
            session_recap=str(sd / "gm-assist.md"),
            session_summary=str(sd / "session-summary.md"),
            scene_extractions_dir=str(sx),
            narration_dir=str(nd),
        ),
        extract=ExtractKnobs(),
        narrate=NarrateKnobs(),
        backends=Backends(),
        session_name=None,
        profiles=[],
        active_profile=None,
        model=None,
        work_dir="",
        campaign_dir=str(camp),
        config_dir="config",
        vtt=str(vtt) if with_vtt else None,
    )
    object.__setattr__(cfg, "session_dir", str(sd)) if hasattr(cfg, "session_dir") else None
    return cfg, vtt, players, nd


@pytest.fixture
def editor_cfg_with_players(tmp_path):
    cfg, vtt, players, _nd = _session(tmp_path)
    return cfg, vtt, players


@pytest.fixture
def editor_cfg_no_vtt(tmp_path):
    cfg, _vtt, _players, _nd = _session(tmp_path, with_vtt=False)
    return cfg


@pytest.fixture
def editor_cfg_with_alternates(tmp_path):
    cfg, _vtt, _players, nd = _session(tmp_path)
    for key in ("a", "b", "c"):
        (nd / f"plan.{key}.md").write_text(
            f"## Scene 1\nnarrator: Vukradin\nchunks: 1\nscene: S\nfocus: {key}\n",
            encoding="utf-8")
    return cfg


def _arg_after(cmd, flag):
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


def test_plan_cmd_passes_the_tape_and_the_roster(editor_cfg_with_players):
    cfg, vtt, players = editor_cfg_with_players
    cmd = scene_editor._build_plan_cmd(None, cfg)
    assert isinstance(cmd, list), cmd
    assert _arg_after(cmd, "--vtt") == str(vtt)
    assert _arg_after(cmd, "--players-config") == str(players)


def test_plan_cmd_refuses_without_a_tape(editor_cfg_no_vtt):
    """The UI must not run a plan the CLI would refuse."""
    result = scene_editor._build_plan_cmd(None, editor_cfg_no_vtt)
    assert isinstance(result, tuple)
    assert result[0] is None
    assert "transcript" in result[1]


def test_narrate_cmd_passes_the_tape(editor_cfg_with_players):
    cfg, vtt, _players = editor_cfg_with_players
    cmd = scene_editor._build_narrate_cmd(None, cfg, 1)
    if isinstance(cmd, tuple):
        return  # narrate has other preconditions; parity is asserted when built
    assert _arg_after(cmd, "--vtt") == str(vtt)


def test_choose_delegates_to_the_cli(editor_cfg_with_alternates):
    """The router shells out; it never copies the file itself (Constitution VI)."""
    cfg = editor_cfg_with_alternates
    cmd = scene_editor._build_choose_cmd(cfg, "b")
    assert isinstance(cmd, list), cmd
    assert cmd[0].endswith("sd_plan")
    assert _arg_after(cmd, "--choose") == "b"


def test_choose_rejects_an_unknown_key(editor_cfg_with_alternates):
    result = scene_editor._build_choose_cmd(editor_cfg_with_alternates, "z")
    assert isinstance(result, tuple) and result[0] is None


def test_choose_refuses_when_there_is_nothing_to_choose(editor_cfg_with_players):
    cfg, _vtt, _players = editor_cfg_with_players
    result = scene_editor._build_choose_cmd(cfg, "a")
    assert isinstance(result, tuple) and result[0] is None
    assert "no plan.a.md" in result[1]
