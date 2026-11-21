"""Library-facing seam of mempalace_client: mine / delete_room / explicit-palace search."""

import subprocess
from types import SimpleNamespace

import pytest

from pipelines.rlm import mempalace_client as mc
from pipelines.rlm.mempalace_client import (
    FakeMempalaceClient,
    MempalaceClient,
    MempalaceProcessError,
)


class _FakePopen:
    def __init__(self, cmd, out, returncode, seen, **kw):
        import io
        seen["cmd"], seen["kw"] = cmd, kw
        if "--files-from" in cmd:
            from pathlib import Path

            seen["files"] = Path(cmd[cmd.index("--files-from") + 1]).read_text().split("\n")
        self.stdout = io.StringIO(out)
        self._rc = returncode

    def wait(self):
        return self._rc


def _run_recorder(monkeypatch, returncode=0, stderr="", out="mined"):
    seen = {}
    monkeypatch.setattr(
        subprocess, "Popen",
        lambda cmd, **kw: _FakePopen(cmd, stderr or out, returncode, seen, **kw))
    return seen


def test_mine_command_and_env(tmp_path, monkeypatch):
    seen = _run_recorder(monkeypatch)
    env = {"MEMPALACE_BACKEND": "turbovec", "X": "y"}
    out = mc.mine(tmp_path / "r", palace=tmp_path / "p", wing="wing_dmsguild", env=env)
    cmd = seen["cmd"]
    assert cmd[0] == "mempalace" and "mine" in cmd and "--direct" in cmd
    assert cmd[cmd.index("--wing") + 1] == "wing_dmsguild"
    assert cmd[cmd.index("--palace") + 1] == str(tmp_path / "p")
    assert str(tmp_path / "r") in cmd
    assert seen["kw"]["env"]["MEMPALACE_BACKEND"] == "turbovec"
    assert seen["kw"]["env"]["X"] == "y"
    assert seen["kw"]["env"]["MEMPALACE_PALACE_PATH"] == str(tmp_path / "p")
    assert "env" in seen["kw"] and env.get("MEMPALACE_PALACE_PATH") is None  # not mutated
    assert out == "mined"
    assert seen["kw"]["stderr"] == subprocess.STDOUT


def test_mine_files_from(tmp_path, monkeypatch):
    seen = _run_recorder(monkeypatch)
    mc.mine(tmp_path / "r", palace=tmp_path / "p", wing="w", env={}, files=["b1/001-a.md", "b1/002-b.md"])
    assert seen["files"][:2] == ["b1/001-a.md", "b1/002-b.md"]


def test_mine_nonzero_raises(tmp_path, monkeypatch):
    _run_recorder(monkeypatch, returncode=2, stderr="boom")
    with pytest.raises(MempalaceProcessError, match="boom"):
        mc.mine(tmp_path, palace=tmp_path / "p", wing="w", env={})


def _drawers(*rows):
    return {"drawers": [
        {"drawer_id": i, "room": "b7", "metadata": {"source_file": s} if s else {}}
        for i, s in rows
    ]}


def test_delete_room_uses_delete_by_source_per_distinct_source(tmp_path):
    pages = {0: _drawers(("d1", "/r/b7/001.md"), ("d2", "/r/b7/001.md"), ("d3", "/r/b7/002.md"))}
    fake = FakeMempalaceClient({
        "mempalace_list_drawers": lambda **kw: dict(pages.get(kw["offset"], {"drawers": []}), total=3),
    })
    n = mc.delete_room(tmp_path / "p", "wing_dmsguild", "b7", client=fake)
    tools = [(c["tool"], c["arguments"]) for c in fake.calls]
    dels = [a for t, a in tools if t == "mempalace_delete_by_source"]
    assert sorted(d["source_file"] for d in dels) == ["/r/b7/001.md", "/r/b7/002.md"]
    assert all(d["dry_run"] is False for d in dels)
    assert all(a.get("wing") == "wing_dmsguild" and a.get("room") == "b7"
               for t, a in tools if t == "mempalace_list_drawers")
    assert n == 2


def test_delete_room_falls_back_to_delete_drawer_without_source(tmp_path):
    fake = FakeMempalaceClient({
        "mempalace_list_drawers": lambda **kw: dict(_drawers(("d9", None)) if kw["offset"] == 0
                                                  else {"drawers": []}, total=1),
    })
    mc.delete_room(tmp_path / "p", "w", "b7", client=fake)
    assert ("mempalace_delete_drawer", {"drawer_id": "d9"}) in [
        (c["tool"], c["arguments"]) for c in fake.calls]


def test_search_passes_explicit_palace_and_env(tmp_path):
    made = {}

    class Fake(FakeMempalaceClient):
        def __init__(self, palace=None, env=None, **kw):
            super().__init__({"mempalace_search": {"results": [{"room": "b1"}]}})
            made.update(palace=palace, env=env)

    out = mc.search("tavern", palace=tmp_path / "p", wing="w", limit=5,
                    env={"A": "1"}, client_factory=Fake)
    assert made == {"palace": str(tmp_path / "p"), "env": {"A": "1"}}
    assert out == {"results": [{"room": "b1"}]}


def test_client_command_has_palace_flag(tmp_path):
    c = MempalaceClient(palace=str(tmp_path / "p"), command="mempalace-mcp")
    cmd = c._resolve_command()
    assert cmd[-2:] == ["--palace", str(tmp_path / "p")]


from pipelines.rlm.mempalace_client import MempalaceError


def _one_source(**over):
    r = {
        "mempalace_list_drawers": lambda **kw: dict(
            _drawers(("d1", "/r/b7/001.md")) if kw["offset"] == 0 else {"drawers": []}, total=1),
    }
    r.update(over)
    return FakeMempalaceClient(r)


def test_delete_room_list_error_raises(tmp_path):
    fake = FakeMempalaceClient({"mempalace_list_drawers": {"error": "boom"}})
    with pytest.raises(MempalaceError, match="boom"):
        mc.delete_room(tmp_path / "p", "w", "b7", client=fake)


def test_delete_room_delete_by_source_failure_raises(tmp_path):
    fake = _one_source(mempalace_delete_by_source={"success": False, "error": "nope"})
    with pytest.raises(MempalaceError):
        mc.delete_room(tmp_path / "p", "w", "b7", client=fake)


def test_delete_room_delete_drawer_failure_raises(tmp_path):
    fake = FakeMempalaceClient({
        "mempalace_list_drawers": lambda **kw: dict(
            _drawers(("d9", None)) if kw["offset"] == 0 else {"drawers": []}, total=1),
        "mempalace_delete_drawer": {"success": False, "error": "nope"},
    })
    with pytest.raises(MempalaceError):
        mc.delete_room(tmp_path / "p", "w", "b7", client=fake)


def _real_mine(monkeypatch, tmp_path, script, **kw):
    """Run mine() against a tiny python child instead of mempalace."""
    import sys
    real = subprocess.Popen

    def popen(cmd, **k):
        return real([sys.executable, "-c", script], **k)

    monkeypatch.setattr(subprocess, "Popen", popen)
    return mc.mine(tmp_path, palace=tmp_path / "p", wing="w", env={}, **kw)


_SCRIPT = "import sys; print('one'); print('two', file=sys.stderr); sys.stdout.flush()"


def test_mine_streams_to_stderr_and_returns_output(tmp_path, monkeypatch, capfd):
    out = _real_mine(monkeypatch, tmp_path, _SCRIPT)
    cap = capfd.readouterr()
    assert "one" in cap.err and "two" in cap.err
    assert cap.out == ""  # stdout stays clean
    assert "one" in out and "two" in out


def test_mine_stream_false_is_silent(tmp_path, monkeypatch, capfd):
    out = _real_mine(monkeypatch, tmp_path, _SCRIPT, stream=False)
    cap = capfd.readouterr()
    assert cap.err == "" and cap.out == ""
    assert "one" in out


def test_mine_nonzero_streams_and_raises_with_tail(tmp_path, monkeypatch, capfd):
    script = "import sys; print('x'*600); print('the-tail'); sys.exit(3)"
    with pytest.raises(MempalaceProcessError, match="(?s)exited 3: .*the-tail") as ei:
        _real_mine(monkeypatch, tmp_path, script)
    assert len(str(ei.value)) < 560
    assert "the-tail" in capfd.readouterr().err
