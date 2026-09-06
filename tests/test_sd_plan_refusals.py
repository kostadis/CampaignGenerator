"""`sd_plan` refuses rather than falling back to the unnarrowed roster.

Issue #385's defect *is* the unnarrowed roster: the planner was handed the whole
campaign cast and an instruction to give everyone a scene, and gave one to a
character whose player was not at the table. So every case where attendance
cannot be established has to refuse. A fallback would be the bug, restored by
omission, and Constitution X forbids the implicit "all" it amounts to.

The GM ruled on 2026-09-06 that all three refusals are hard, with no opt-out.
Verified before that ruling: no session on disk in any campaign has a `plan.md`
without a VTT beside it, so nothing existing is blocked by this.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import session_doc.sd_plan as sd_plan  # noqa: E402
from tests.helpers.eligibility_session import write_session  # noqa: E402


def _argv(scene_dir, out, *, vtt=None, players=None):
    argv = [
        "sd_plan.py",
        "--scene-extractions", str(scene_dir),
        "--characters", "Vukradin, Valphine Sotorra, Soma, Brewbarry",
        "--out", str(out),
    ]
    if vtt is not None:
        argv += ["--vtt", str(vtt)]
    if players is not None:
        argv += ["--players-config", str(players)]
    return argv


def _no_api(monkeypatch):
    """Any model call in a refusal path is itself a failure."""
    def boom(*a, **kw):
        raise AssertionError("refused runs must not reach the API")
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "stream_api", boom)
    monkeypatch.setattr(sd_plan, "run_single_batch", boom)


def test_refuses_without_a_vtt(tmp_path, monkeypatch, capsys):
    scene_dir, _vtt, players = write_session(tmp_path)
    out = tmp_path / "plan.md"
    _no_api(monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, players=players))

    with pytest.raises(SystemExit) as exc:
        sd_plan.main()

    assert exc.value.code != 0
    assert "--vtt" in capsys.readouterr().err
    assert not out.exists()


def test_refuses_without_a_players_config(tmp_path, monkeypatch, capsys):
    scene_dir, vtt, _players = write_session(tmp_path)
    out = tmp_path / "plan.md"
    _no_api(monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt=vtt))

    with pytest.raises(SystemExit) as exc:
        sd_plan.main()

    assert exc.value.code != 0
    assert "--players-config" in capsys.readouterr().err
    assert not out.exists()


def test_refuses_when_nobody_attended(tmp_path, monkeypatch, capsys):
    """An empty pool means the wrong tape, not a session nobody came to."""
    scene_dir, vtt, players = write_session(tmp_path, gm_only_vtt=True)
    out = tmp_path / "plan.md"
    _no_api(monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt=vtt, players=players))

    with pytest.raises(SystemExit) as exc:
        sd_plan.main()

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "no narrator" in err.lower() or "empty" in err.lower()
    assert "vtt" in err.lower()          # names the probable cause
    assert not out.exists()


def test_refusal_never_falls_back_to_the_full_roster(tmp_path, monkeypatch, capsys):
    """The regression guard for the defect itself.

    Whatever a refusal does, it must not be "plan anyway with everyone".
    """
    scene_dir, _vtt, players = write_session(tmp_path)
    out = tmp_path / "plan.md"
    _no_api(monkeypatch)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, players=players))

    with pytest.raises(SystemExit):
        sd_plan.main()

    assert not out.exists(), "a refused run must write no plan at all"
