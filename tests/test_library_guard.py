import subprocess

import pytest

from pipelines.library import cli
from pipelines.library.guard import PalaceGuardError, mine_command, require_pilot_palace

E = "MEMPALACE_PALACE_PATH"


def test_guard_unset(tmp_path):
    with pytest.raises(PalaceGuardError):
        require_pilot_palace({}, tmp_path)
    with pytest.raises(PalaceGuardError):
        require_pilot_palace({E: ""}, tmp_path)


def test_guard_default_palace(tmp_path):
    with pytest.raises(PalaceGuardError):
        require_pilot_palace({E: str(tmp_path / ".mempalace/palace")}, tmp_path)


def test_guard_campaign_palace(tmp_path):
    with pytest.raises(PalaceGuardError):
        require_pilot_palace({E: str(tmp_path / "src/campaigns/x/.mempalace")}, tmp_path)


def test_guard_resolves_symlink(tmp_path):
    (tmp_path / ".mempalace").mkdir()
    link = tmp_path / "innocent"
    link.symlink_to(tmp_path / ".mempalace")
    with pytest.raises(PalaceGuardError):
        require_pilot_palace({E: str(link)}, tmp_path)


def test_guard_ok(tmp_path):
    p = tmp_path / "rpglib-palace/palace"
    assert require_pilot_palace({E: str(p)}, tmp_path) == p.resolve()


def test_mine_command_direct(tmp_path):
    cmd = mine_command(tmp_path, tmp_path / "p")
    assert "--direct" in cmd and cmd[cmd.index("--wing") + 1] == "wing_dmsguild"


def test_cli_mine_refuses_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv(E, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    called = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(SystemExit) as ei:
        cli.main(["mine"])
    assert ei.value.code != 0
    assert not called
