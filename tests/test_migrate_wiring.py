"""One-shot host wiring migration keeps source intact on refusal/failure."""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from server.migrate_wiring import migrate_wiring


def _source(tmp_path, body="dgx_endpoint: http://example.invalid\nunknown_key: keep\n"):
    checkout = tmp_path / "checkout"
    (checkout / "config").mkdir(parents=True)
    source = checkout / "config" / "wiring.yaml"
    source.write_text(body, encoding="utf-8")
    return checkout, source


def test_preserves_unknown_keys_and_removes_source_only_after_success(tmp_path, capsys):
    checkout, source = _source(tmp_path)
    target = tmp_path / "config" / "wiring.yaml"
    migrate_wiring(checkout, target)
    assert not source.exists()
    assert yaml.safe_load(target.read_text()) == {
        "dgx_endpoint": "http://example.invalid", "unknown_key": "keep"
    }
    assert "unknown_key" in capsys.readouterr().out


def test_missing_or_malformed_source_refuses_without_target(tmp_path):
    checkout = tmp_path / "missing"
    target = tmp_path / "target.yaml"
    with pytest.raises(FileNotFoundError):
        migrate_wiring(checkout, target)
    checkout, source = _source(tmp_path, "bad: [yaml")
    with pytest.raises(ValueError):
        migrate_wiring(checkout, target)
    assert source.exists() and not target.exists()


def test_target_conflict_refuses_until_deliberate_force(tmp_path):
    checkout, source = _source(tmp_path)
    target = tmp_path / "target.yaml"
    target.write_text("dgx_model: existing\n")
    with pytest.raises(FileExistsError):
        migrate_wiring(checkout, target)
    assert source.exists() and target.read_text() == "dgx_model: existing\n"
    migrate_wiring(checkout, target, force=True)
    assert not source.exists() and "unknown_key: keep" in target.read_text()


def test_write_failure_keeps_source(tmp_path):
    checkout, source = _source(tmp_path)
    parent_file = tmp_path / "not-a-directory"
    parent_file.write_text("existing")
    with pytest.raises(OSError):
        migrate_wiring(checkout, parent_file / "wiring.yaml")
    assert source.exists()


def test_cli_help_runs_as_module(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "server.migrate_wiring", "--help"],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert "--source-checkout" in result.stdout
