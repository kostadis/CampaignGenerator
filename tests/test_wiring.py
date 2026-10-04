"""External wiring selection and retired-checkout refusal."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from campaignlib.wiring import assert_no_retired_wiring, load_wiring


def test_explicit_env_default_precedence(tmp_path, monkeypatch):
    home = tmp_path / "home"
    default = home / ".config/campaigngenerator/wiring.yaml"
    default.parent.mkdir(parents=True)
    default.write_text("dgx_model: default\n")
    env_file = tmp_path / "env.yaml"
    env_file.write_text("dgx_model: env\n")
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("dgx_model: explicit\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MNEME_WIRING", str(env_file))
    assert load_wiring(explicit)["dgx_model"] == "explicit"
    assert load_wiring()["dgx_model"] == "env"
    monkeypatch.delenv("MNEME_WIRING")
    assert load_wiring()["dgx_model"] == "default"


def test_optional_missing_default_but_selected_missing_is_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MNEME_WIRING", raising=False)
    assert load_wiring() == {}
    missing = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError, match="missing.yaml"):
        load_wiring(missing)
    monkeypatch.setenv("MNEME_WIRING", str(missing))
    with pytest.raises(FileNotFoundError, match="missing.yaml"):
        load_wiring()


@pytest.mark.parametrize("body", ["[not, a, mapping]", "bad: [yaml"])
def test_malformed_selected_file_is_error(tmp_path, body):
    path = tmp_path / "wiring.yaml"
    path.write_text(body)
    with pytest.raises(ValueError, match="wiring.yaml"):
        load_wiring(path)


def test_no_checkout_or_cwd_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MNEME_WIRING", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/wiring.yaml").write_text("dgx_model: retired\n")
    monkeypatch.chdir(tmp_path)
    assert load_wiring() == {}
    with pytest.raises(RuntimeError, match="migrate_wiring --source-checkout"):
        assert_no_retired_wiring(tmp_path)
    assert (tmp_path / "config/wiring.yaml").is_file()


def test_known_checkout_without_retired_wiring_is_allowed(tmp_path):
    assert_no_retired_wiring(tmp_path)


def test_checkout_startup_refuses_retired_file_before_build(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / "startup", tmp_path / "startup")
    (tmp_path / "config").mkdir()
    retired = tmp_path / "config" / "wiring.yaml"
    retired.write_text("dgx_model: retired\n")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    result = subprocess.run(
        ["bash", str(tmp_path / "startup")], cwd=tmp_path, env=env,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert f"migrate_wiring --source-checkout {tmp_path}" in result.stderr
    assert retired.is_file()


def test_checkout_migration_mode_reaches_server_with_retired_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / "startup", tmp_path / "startup")
    (tmp_path / "config").mkdir()
    retired = tmp_path / "config" / "wiring.yaml"
    retired.write_text("dgx_model: retired\n")
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dist" / "index.html").write_text("ready")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TRACE_FILE"\n')
    fake_python.chmod(0o755)
    trace = tmp_path / "args.txt"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["TRACE_FILE"] = str(trace)
    result = subprocess.run(
        ["bash", str(tmp_path / "startup"), "--migration-only"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert trace.read_text().splitlines() == ["-m", "server.main", "--migration-only"]
    assert retired.is_file()
