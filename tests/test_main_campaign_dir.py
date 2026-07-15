"""Tests for the loud-fail / chdir behavior in ``server.main.main()``.

Covers the fix for the bug where the server never ``os.chdir()``'d into the
resolved campaign directory, so the ensemble/grounding routers (which
resolve paths against ``Path.cwd()``) silently globbed the code repo instead
of the campaign workspace. Also covers the removal of the broken silent
default (``_get_or_create_default_campaign_dir``): when no campaign
directory can be determined, ``main()`` must now fail loudly instead of
falling back to a synthetic ``~/.campaigngenerator`` directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import server.main as server_main


def test_main_exits_loudly_with_no_campaign_dir_determinable(tmp_path, monkeypatch, capsys):
    """No --campaign-dir, no --session-dir, and a config-less CWD must raise
    SystemExit with an actionable message on stderr — never silently fall
    back to a synthetic default campaign directory."""
    monkeypatch.chdir(tmp_path)
    orig_argv = sys.argv
    try:
        sys.argv = ["prog"]
        with pytest.raises(SystemExit) as exc_info:
            server_main.main()
        assert exc_info.value.code == 1
    finally:
        sys.argv = orig_argv

    captured = capsys.readouterr()
    assert "Could not determine the campaign directory" in captured.err
    assert "--campaign-dir" in captured.err


def test_main_chdirs_into_resolved_campaign_dir(tmp_path, monkeypatch):
    """``main()`` must os.chdir() into the resolved campaign directory before
    handing off to uvicorn, so routers that resolve paths against
    ``Path.cwd()`` (e.g. the ensemble chapter picker) see the campaign
    workspace rather than whatever directory the process was launched from."""
    campaign = tmp_path / "campaign"
    config_dir = campaign / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("log_dir: logs/\n", encoding="utf-8")

    orig_argv = sys.argv
    orig_cwd = os.getcwd()
    holder: dict = {}

    def fake_run(*args, **kwargs):
        holder["cwd"] = os.getcwd()

    monkeypatch.setattr("uvicorn.run", fake_run)

    try:
        sys.argv = [
            "prog",
            "--campaign-dir", str(campaign),
            "--config-dir", "config",
        ]
        server_main.main()
    finally:
        sys.argv = orig_argv
        os.chdir(orig_cwd)

    assert holder["cwd"] == str(campaign.resolve())
