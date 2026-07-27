"""Tests for make_tracking.py's --batch wiring (feature 004-claude-api-batch).

Single-call CLI: the live call has never passed an explicit max_tokens (so it
uses stream_api's own default, 8096); the --batch branch must pass that same
8096 explicitly to run_single_batch (whose own default, 8192, differs) so the
two paths bill/behave identically.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.grounding import make_tracking  # noqa: E402


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return "# Main Quests\nCryovain encounter — Icespire Hold\n"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "# Main Quests\nCryovain encounter — Icespire Hold\n"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(make_tracking, "stream_api", fake)
    monkeypatch.setattr(make_tracking, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(make_tracking, "run_single_batch", fake)
    monkeypatch.setattr(make_tracking, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_adventure(tmp_path: Path) -> Path:
    p = tmp_path / "adventure.md"
    p.write_text("Cryovain lairs at Icespire Hold.", encoding="utf-8")
    return p


def test_default_path_uses_stream_api_unchanged(monkeypatch, fake_stream_api, tmp_path):
    """FR-011: no --batch => stream_api called with no explicit max_tokens
    (its own 8096 default), exactly as before this feature."""
    input_file = _write_adventure(tmp_path)
    output = tmp_path / "tracking.txt"
    monkeypatch.setattr(sys, "argv", [
        "make_tracking.py", str(input_file), "--output", str(output),
    ])
    make_tracking.main()

    assert len(fake_stream_api.calls) == 1
    assert "max_tokens" not in fake_stream_api.calls[0]["kwargs"]
    assert output.exists()


def test_batch_flag_routes_through_run_single_batch(monkeypatch, fake_run_single_batch, tmp_path):
    input_file = _write_adventure(tmp_path)
    output = tmp_path / "tracking.txt"
    monkeypatch.setattr(sys, "argv", [
        "make_tracking.py", str(input_file), "--output", str(output), "--batch",
    ])
    make_tracking.main()

    assert len(fake_run_single_batch.calls) == 1
    call = fake_run_single_batch.calls[0]
    assert call["max_tokens"] == 8096  # mirrors stream_api's own default
    assert output.exists()


def test_batch_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    input_file = _write_adventure(tmp_path)
    output = tmp_path / "tracking.txt"
    monkeypatch.setattr(make_tracking, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(make_tracking, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "make_tracking.py", str(input_file), "--output", str(output), "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        make_tracking.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
    assert not output.exists()  # failure happens before the write
