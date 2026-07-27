"""Tests for scabard_sync.py's --batch wiring (feature 004-claude-api-batch).

scabard_sync's extraction pass is a single-call CLI per the contract
(`contracts/cli-batch-flag.md`): --batch routes the one stream_api call
through run_single_batch instead, same system/user/model/max_tokens=8192;
--extract-only stops before any Scabard network call, so these tests never
touch ScabardClient.
"""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scabard_sdk import scabard_sync  # noqa: E402

_ENTITIES_JSON = json.dumps([
    {"concept": "character", "name": "Buppido", "briefSummary": "A derro.",
     "description": "Full description.", "secrets": ""},
])


class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        return _ENTITIES_JSON


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return _ENTITIES_JSON


class FailingRunSingleBatch:
    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        raise RuntimeError("batch item 'single' did not succeed: status=errored error=boom")


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(scabard_sync, "stream_api", fake)
    monkeypatch.setattr(scabard_sync, "client_from_args", lambda *a, **kw: None)
    return fake


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(scabard_sync, "run_single_batch", fake)
    monkeypatch.setattr(scabard_sync, "client_from_args", lambda *a, **kw: None)
    return fake


def _write_world_state(tmp_path: Path) -> Path:
    p = tmp_path / "world_state.md"
    p.write_text("Buppido is a derro serial killer.", encoding="utf-8")
    return p


def _base_argv(world_state: Path, extract_file: Path, *extra: str) -> list[str]:
    return [
        "scabard_sync.py",
        "--campaign-id", "121",
        "--username", "kostadis",
        "--access-key", "testkey",
        "--world-state", str(world_state),
        "--extract-only",
        "--extract-file", str(extract_file),
        *extra,
    ]


def test_default_path_uses_stream_api_unchanged(monkeypatch, fake_stream_api, tmp_path):
    """FR-011: no --batch => stream_api called with max_tokens=8192, exactly
    as before this feature."""
    ws = _write_world_state(tmp_path)
    extract_file = tmp_path / "entities.json"
    monkeypatch.setattr(sys, "argv", _base_argv(ws, extract_file))
    scabard_sync.main()

    assert len(fake_stream_api.calls) == 1
    assert fake_stream_api.calls[0]["kwargs"].get("max_tokens") == 8192
    assert extract_file.exists()


def test_batch_flag_routes_through_run_single_batch(monkeypatch, fake_run_single_batch, tmp_path):
    ws = _write_world_state(tmp_path)
    extract_file = tmp_path / "entities.json"
    monkeypatch.setattr(sys, "argv", _base_argv(ws, extract_file, "--batch"))
    scabard_sync.main()

    assert len(fake_run_single_batch.calls) == 1
    assert fake_run_single_batch.calls[0]["max_tokens"] == 8192
    assert extract_file.exists()


def test_batch_failure_exits_nonzero(monkeypatch, tmp_path, capsys):
    ws = _write_world_state(tmp_path)
    extract_file = tmp_path / "entities.json"
    monkeypatch.setattr(scabard_sync, "run_single_batch", FailingRunSingleBatch())
    monkeypatch.setattr(scabard_sync, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", _base_argv(ws, extract_file, "--batch"))

    with pytest.raises(SystemExit) as exc_info:
        scabard_sync.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "Error: batch item failed:" in err
    assert not extract_file.exists()
