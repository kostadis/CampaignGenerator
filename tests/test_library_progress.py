import json
import re

import pytest

from pipelines.library import cli, progress
from pipelines.library.build import build, refresh
from tests.test_library_build import FakeClient, world
from tests.test_library_refresh import _touch_change

LINE = re.compile(r"^library: \d\d:\d\d:\d\d ")


@pytest.fixture(autouse=True)
def _loud():
    progress.set_quiet(False)
    yield
    progress.set_quiet(False)


def test_build_progress_on_stderr(tmp_path, capsys):
    cfg = world(tmp_path, {1: ("A",), 2: ("B",)})
    build(cfg, client=FakeClient())
    cap = capsys.readouterr()
    assert cap.out == ""
    lines = cap.err.splitlines()
    assert all(LINE.match(ln) for ln in lines)
    text = cap.err
    for needle in ("palace", "turbovec", "qwen3-embedding:0.6b", "2 books selected",
                   "rendering 1/2 Book 1", "rendering 2/2 Book 2",
                   "mining all files into wing", "mined in", "done:"):
        assert needle in text, needle


def test_refresh_progress_has_plan_and_files(tmp_path, capsys):
    cfg = world(tmp_path, {1: ("A",), 2: ("B",)})
    c = FakeClient()
    build(cfg, client=c)
    _touch_change(cfg, 1, ("A", "A2"))
    capsys.readouterr()
    refresh(cfg, client=c)
    err = capsys.readouterr().err
    assert "plan: 1 to process (0 added, 1 changed), 0 removed" in err
    assert "rendering 1/1 Book 1" in err
    assert "mining 2 files into wing" in err
    assert "done:" in err


def _cli(monkeypatch, cfg, client):
    monkeypatch.setattr(cli, "load_library_config", lambda *a, **k: cfg)
    monkeypatch.setattr(cli, "_client", lambda c: client)


def test_cli_quiet_silences_and_json_stays_valid(tmp_path, monkeypatch, capsys):
    cfg = world(tmp_path, {1: ("A",)})
    _cli(monkeypatch, cfg, FakeClient())
    assert cli.main(["build", "--json", "--quiet"]) == 0
    cap = capsys.readouterr()
    assert cap.err == ""
    assert json.loads(cap.out)["indexed"] == 1


def test_cli_json_with_progress_keeps_stdout_clean(tmp_path, monkeypatch, capsys):
    cfg = world(tmp_path, {1: ("A",)})
    _cli(monkeypatch, cfg, FakeClient())
    assert cli.main(["build", "--json"]) == 0
    cap = capsys.readouterr()
    assert "library:" in cap.err and "done:" in cap.err
    assert json.loads(cap.out)["selected"] == 1
    assert cli.main(["refresh", "--json", "--quiet"]) == 0
    cap = capsys.readouterr()
    assert cap.err == "" and "changed" in json.loads(cap.out)
