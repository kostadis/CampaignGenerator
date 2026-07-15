"""Unit tests for ``server.main._resolve_campaign_dir_for_service``.

The resolver decides which directory the unified config service anchors to,
given CLI args (``--campaign-dir``, ``--session-dir``, ``--config-dir``) and
the process CWD. It must detect both the current ``<campaign>/<config-dir>/
config.yaml`` layout and the legacy top-level ``<campaign>/config.yaml``
layout, and return ``None`` (never a synthetic default) when nothing can be
determined — callers are responsible for failing loudly on ``None``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import _resolve_campaign_dir_for_service


def _args(**over):
    base = dict(campaign_dir=None, session_dir=None, config_dir="config")
    base.update(over)
    return SimpleNamespace(**base)


def test_campaign_dir_flag_wins(tmp_path):
    result = _resolve_campaign_dir_for_service(_args(campaign_dir=str(tmp_path)))
    assert result == tmp_path.resolve()


def test_cwd_with_config_subdir_layout(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("")
    monkeypatch.chdir(tmp_path)

    result = _resolve_campaign_dir_for_service(_args())
    assert result == tmp_path.resolve()


def test_session_dir_walks_parents_to_campaign_root_with_config_subdir(tmp_path):
    campaign = tmp_path / "campaign"
    (campaign / "config").mkdir(parents=True)
    (campaign / "config" / "config.yaml").write_text("")
    session_dir = campaign / "summaries" / "20260101"
    session_dir.mkdir(parents=True)

    result = _resolve_campaign_dir_for_service(_args(session_dir=str(session_dir)))
    assert result == campaign.resolve()


def test_cwd_top_level_config_yaml_backcompat(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("")
    monkeypatch.chdir(tmp_path)

    result = _resolve_campaign_dir_for_service(_args())
    assert result == tmp_path.resolve()


def test_session_dir_walks_parents_to_campaign_root_top_level_config_backcompat(tmp_path):
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    (campaign / "config.yaml").write_text("")
    session_dir = campaign / "summaries" / "20260101"
    session_dir.mkdir(parents=True)

    result = _resolve_campaign_dir_for_service(_args(session_dir=str(session_dir)))
    assert result == campaign.resolve()


def test_no_config_anywhere_returns_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = _resolve_campaign_dir_for_service(_args())
    assert result is None
