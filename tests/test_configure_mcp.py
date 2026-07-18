"""Tests for pipelines/workspace/configure_mcp.py's server-block gating."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.workspace.configure_mcp import build_server_block


def test_campaign_server_always_present(tmp_path):
    servers = build_server_block(tmp_path, kanka_token="", kanka_url="")
    assert servers["campaign"]["command"] == "mcp_server"
    assert "5etools" not in servers
    assert "registry" not in servers
    assert "kanka" not in servers


def test_registry_server_gated_on_entity_registry_yaml(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "entity_registry.yaml").write_text("version: 1\nentities: []\n")

    servers = build_server_block(tmp_path, kanka_token="", kanka_url="")
    assert servers["registry"]["command"] == "registry_mcp"
    assert servers["registry"]["env"]["CAMPAIGN_DIR"] == str(tmp_path)


def test_5etools_server_gated_on_refs_yaml(tmp_path):
    (tmp_path / "refs.yaml").write_text("sources: []\n")

    servers = build_server_block(tmp_path, kanka_token="", kanka_url="")
    assert servers["5etools"]["command"] == "launch_5etools_mcp"


def test_kanka_server_gated_on_token(tmp_path):
    servers = build_server_block(tmp_path, kanka_token="tok", kanka_url="http://x")
    assert servers["kanka"]["env"]["KANKA_TOKEN"] == "tok"
