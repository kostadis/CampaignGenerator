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


def test_codex_scabard_extraction_preserves_request_and_output_path(
    monkeypatch, fake_stream_api, tmp_path
):
    """Extraction-only Codex runs keep the document envelope and write the
    normal JSON artifact without entering the Scabard sync pass."""
    ws = _write_world_state(tmp_path)
    extract_file = tmp_path / "artifacts" / "entities.json"
    monkeypatch.setattr(
        scabard_sync, "sync_entities",
        lambda *args, **kwargs: pytest.fail("extract-only must not sync"),
    )
    monkeypatch.setattr(sys, "argv", _base_argv(
        ws, extract_file, "--backend", "codex-cli", "--model", "gpt-5-codex",
    ))
    scabard_sync.main()

    assert len(fake_stream_api.calls) == 1
    call = fake_stream_api.calls[0]
    assert call["model"] == "gpt-5-codex"
    assert "Buppido is a derro serial killer." in call["user"]
    assert json.loads(extract_file.read_text(encoding="utf-8")) == json.loads(
        _ENTITIES_JSON
    )


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


def _from_extract_argv(extract_file: Path, *extra: str) -> list[str]:
    return [
        "scabard_sync.py",
        "--campaign-id", "121",
        "--username", "kostadis",
        "--from-extract", str(extract_file),
        "--dry-run",
        *extra,
    ]


def _write_extract(path: Path) -> None:
    path.write_text(_ENTITIES_JSON, encoding="utf-8")


def test_manual_access_key_wins_over_trimmed_environment(
    monkeypatch, tmp_path, capsys
):
    """The explicit manual CLI contract remains authoritative."""
    extract_file = tmp_path / "entities.json"
    _write_extract(extract_file)
    seen = {}

    def fake_sync(entities, campaign_id, username, access_key, manifest,
                  manifest_path, dry_run):
        seen.update(access_key=access_key, campaign_id=campaign_id,
                    username=username, dry_run=dry_run)
        return manifest

    monkeypatch.setattr(scabard_sync, "sync_entities", fake_sync)
    monkeypatch.setenv("SCABARD_ACCESS_KEY", "  env-key  ")
    monkeypatch.setattr(
        sys, "argv", _from_extract_argv(extract_file, "--access-key", "manual-key")
    )

    scabard_sync.main()

    assert seen == {
        "access_key": "manual-key",
        "campaign_id": 121,
        "username": "kostadis",
        "dry_run": True,
    }
    output = capsys.readouterr()
    assert "manual-key" not in output.out + output.err
    assert "env-key" not in output.out + output.err


def test_trimmed_scabard_access_key_environment_fallback(
    monkeypatch, tmp_path, capsys
):
    """The server-facing child contract may omit argv credentials."""
    extract_file = tmp_path / "entities.json"
    _write_extract(extract_file)
    seen = {}

    def fake_sync(entities, campaign_id, username, access_key, manifest,
                  manifest_path, dry_run):
        seen["access_key"] = access_key
        return manifest

    monkeypatch.setattr(scabard_sync, "sync_entities", fake_sync)
    monkeypatch.setenv("SCABARD_ACCESS_KEY", "  env-key  ")
    monkeypatch.setattr(sys, "argv", _from_extract_argv(extract_file))

    scabard_sync.main()

    assert seen["access_key"] == "env-key"
    output = capsys.readouterr()
    assert "env-key" not in output.out + output.err


def test_missing_scabard_access_key_fails_before_sync(monkeypatch, tmp_path, capsys):
    """A missing manual and environment key must fail closed."""
    extract_file = tmp_path / "entities.json"
    _write_extract(extract_file)
    monkeypatch.delenv("SCABARD_ACCESS_KEY", raising=False)
    monkeypatch.setattr(
        scabard_sync, "sync_entities",
        lambda *args, **kwargs: pytest.fail("sync must not run without a key"),
    )
    monkeypatch.setattr(sys, "argv", _from_extract_argv(extract_file))

    with pytest.raises(SystemExit) as exc_info:
        scabard_sync.main()

    assert exc_info.value.code == 1
    assert "access key" in capsys.readouterr().err.lower()
