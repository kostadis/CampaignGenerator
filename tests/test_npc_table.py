"""Tests for npc_table.py's --batch wiring (feature 004-claude-api-batch).

npc_table is a single-call CLI (contract: `contracts/cli-batch-flag.md` §
"Single-call CLIs"): --batch routes the one stream_api call through
run_single_batch instead, with the same system/user/model/max_tokens; the
default (no --batch) path must stay byte-identical.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.grounding import npc_table  # noqa: E402


def _write_config(tmp_path: Path) -> Path:
    (tmp_path / "world_state.md").write_text("Buppido runs the Derro.", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "documents:\n  - label: world_state\n    path: world_state.md\n",
        encoding="utf-8",
    )
    return config


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return "| NPC Name | Faction / Affiliation | Current State | Core Motivations |"


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "[batch-npc-table-result]"


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(npc_table, "stream_api", fake)
    monkeypatch.setattr(npc_table, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(npc_table, "run_single_batch", fake)
    monkeypatch.setattr(npc_table, "client_from_args", lambda *a, **kw: None)
    return fake


def test_default_path_uses_stream_api_unchanged(monkeypatch, fake_stream_api, tmp_path):
    """FR-011: with --batch absent, behavior (and the stream_api call shape) is
    unchanged — same max_tokens=4096 the live call always used."""
    config = _write_config(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "npc_table.py", "--config", str(config), "--no-log",
    ])
    npc_table.main()

    assert len(fake_stream_api.calls) == 1
    assert fake_stream_api.calls[0]["kwargs"].get("max_tokens") == 4096


def test_batch_flag_routes_through_run_single_batch(monkeypatch, fake_run_single_batch, tmp_path):
    config = _write_config(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "npc_table.py", "--config", str(config), "--no-log", "--batch",
    ])
    npc_table.main()

    assert len(fake_run_single_batch.calls) == 1
    call = fake_run_single_batch.calls[0]
    assert call["max_tokens"] == 4096
    assert call["model"] == npc_table.DEFAULT_MODEL


def test_batch_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    config = _write_config(tmp_path)
    monkeypatch.setattr(npc_table, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(npc_table, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "npc_table.py", "--config", str(config), "--no-log", "--batch",
    ])

    with pytest.raises(SystemExit) as exc_info:
        npc_table.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
