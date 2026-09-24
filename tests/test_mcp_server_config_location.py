"""mcp_server loads its config from <campaign>/config/config.yaml only.

It used to prefer a legacy root config.yaml and, failing both, load
CampaignGenerator's own config/config.yaml — so a misconfigured campaign
served the toolkit's grounding documents instead of failing. The config is
resolved at import time, so each case imports the module in a subprocess
with CAMPAIGN_DIR pointing at a fixture layout.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "import pipelines.rlm.mcp_server as m; "
    "print(m._config_path); print(sorted(m._doc_index))"
)


def _import_with(campaign_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CAMPAIGN_DIR": str(campaign_dir)}
    return subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def _config(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"documents:\n  - {{label: {label}, path: ../docs/{label}.md}}\n",
        encoding="utf-8",
    )


def test_loads_config_dir_config(tmp_path):
    _config(tmp_path / "config" / "config.yaml", "campaign_state")
    result = _import_with(tmp_path)
    assert result.returncode == 0, result.stderr
    assert str(tmp_path / "config" / "config.yaml") in result.stdout
    assert "campaign_state" in result.stdout


def test_missing_config_fails_instead_of_loading_toolkit_config(tmp_path):
    result = _import_with(tmp_path)
    assert result.returncode == 1
    assert "no config at" in result.stderr


@pytest.mark.parametrize("with_config_dir", [False, True])
def test_root_config_is_rejected(tmp_path, with_config_dir):
    (tmp_path / "config.yaml").write_text("documents: []\n", encoding="utf-8")
    if with_config_dir:
        _config(tmp_path / "config" / "config.yaml", "campaign_state")
    result = _import_with(tmp_path)
    assert result.returncode == 1
    assert "misplaced config" in result.stderr
