"""Env-var expansion in config values + repo-file auto-discovery.

Covers the portability fixes that let a checked-in campaign config.yaml work
across a different username or clone location:
  - `${VAR}` / `$VAR` expansion in config string values and load_file paths
  - load_repo_file discovering code-repo prompts regardless of base_dir
"""

import textwrap
import subprocess
import sys
from pathlib import Path

import pytest

from campaignlib.config import (
    _expand_env,
    load_config,
    load_file,
    load_repo_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_expand_env_recurses_strings_dicts_lists(monkeypatch):
    monkeypatch.setenv("WT", "/wt")
    out = _expand_env(
        {"a": "${WT}/x", "b": ["$WT/y", 3, None], "c": {"d": "${WT}/z"}}
    )
    assert out == {"a": "/wt/x", "b": ["/wt/y", 3, None], "c": {"d": "/wt/z"}}


def test_undefined_var_left_verbatim():
    assert _expand_env("${NOPE_NOT_SET}/x") == "${NOPE_NOT_SET}/x"


def test_load_config_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPAIGN_DOCS", str(tmp_path / "docs"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            log_dir: ${CAMPAIGN_DOCS}/logs
            documents:
              - label: world_state
                path: ${CAMPAIGN_DOCS}/world_state.md
            """
        )
    )
    config, _ = load_config(str(cfg))
    assert config["log_dir"] == str(tmp_path / "docs" / "logs")
    assert config["documents"][0]["path"] == str(tmp_path / "docs" / "world_state.md")


def test_load_file_expands_env(tmp_path, monkeypatch):
    target = tmp_path / "world_state.md"
    target.write_text("hello canon")
    monkeypatch.setenv("CAMPAIGN_DOCS", str(tmp_path))
    assert load_file("${CAMPAIGN_DOCS}/world_state.md") == "hello canon"


def test_load_repo_file_relative_with_bogus_base_dir():
    # A campaign config names the prompt relatively; base_dir is the (unrelated)
    # campaign workspace. It must still resolve to the repo copy.
    txt = load_repo_file("config/system_prompt.md", base_dir=Path("/tmp/not/a/repo"))
    assert txt.strip()


def test_load_repo_file_rejects_stale_absolute_by_basename(capsys):
    # An explicitly selected file must not become a different shipped file.
    stale = "/home/someone-else/CampaignGenerator/config/system_prompt.md"
    with pytest.raises(SystemExit):
        load_repo_file(stale)
    assert stale in capsys.readouterr().err


def test_load_repo_file_prefers_campaign_logical_path(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "system_prompt.md").write_text("campaign text", encoding="utf-8")
    assert load_repo_file("config/system_prompt.md", base_dir=config) == "campaign text"
    (config / "system_prompt.md").unlink()
    assert load_repo_file("config/system_prompt.md", base_dir=config).strip()


def test_load_repo_file_does_not_map_unrelated_basename(tmp_path, capsys):
    with pytest.raises(SystemExit):
        load_repo_file("other/system_prompt.md", base_dir=tmp_path)
    assert "other/system_prompt.md" in capsys.readouterr().err


def test_load_repo_file_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="traverse"):
        load_repo_file("config/../system_prompt.md", base_dir=tmp_path)


def test_new_workspace_logical_prompt_names_remain_readable(tmp_path):
    workspace = tmp_path / "campaign"
    subprocess.run(
        [sys.executable, "-m", "pipelines.workspace.new_workspace", str(workspace)],
        check=True, capture_output=True, text=True,
    )
    config = (workspace / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "config/system_prompt.md" in config
    assert "config/agents/lore_oracle.md" in config
    assert load_repo_file("config/system_prompt.md", base_dir=workspace / "config").strip()
    assert load_repo_file("config/agents/lore_oracle.md", base_dir=workspace / "config").strip()


def test_load_repo_file_missing_exits():
    with pytest.raises(SystemExit):
        load_repo_file("config/does_not_exist_xyz.md")
