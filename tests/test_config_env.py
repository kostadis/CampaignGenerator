"""Env-var expansion in config values + repo-file auto-discovery.

Covers the portability fixes that let a checked-in campaign config.yaml work
across a different username or clone location:
  - `${VAR}` / `$VAR` expansion in config string values and load_file paths
  - load_repo_file discovering code-repo prompts regardless of base_dir
"""

import textwrap
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


def test_load_repo_file_recovers_stale_absolute_by_basename():
    # An old config holding another machine's absolute path recovers by basename.
    stale = "/home/someone-else/CampaignGenerator/config/system_prompt.md"
    real = load_repo_file("config/system_prompt.md")
    assert load_repo_file(stale) == real


def test_load_repo_file_missing_exits():
    with pytest.raises(SystemExit):
        load_repo_file("config/does_not_exist_xyz.md")
