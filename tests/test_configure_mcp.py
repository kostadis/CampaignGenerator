"""Tests for pipelines/workspace/configure_mcp.py's server-block gating."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.workspace.configure_mcp import build_server_block, find_campaigns


def _make_campaign(dir_path: Path) -> None:
    (dir_path / "config").mkdir(parents=True)
    (dir_path / "config" / "config.yaml").write_text("documents: []\n")


def test_find_campaigns_matches_root_itself(tmp_path):
    _make_campaign(tmp_path)
    assert find_campaigns([tmp_path]) == [tmp_path]


def test_find_campaigns_matches_children_of_a_container_root(tmp_path):
    _make_campaign(tmp_path / "Phandalin")
    _make_campaign(tmp_path / "toee")
    (tmp_path / "not-a-campaign").mkdir()

    assert find_campaigns([tmp_path]) == [tmp_path / "Phandalin", tmp_path / "toee"]


def test_find_campaigns_ignores_bare_config_yaml_at_campaign_root(tmp_path):
    # Regression: config.yaml directly at the campaign root (the old
    # location) must NOT match — only config/config.yaml does. A campaign
    # with only the old-style file should be treated as not-a-campaign, not
    # silently misidentified as a container whose children get scanned.
    (tmp_path / "config.yaml").write_text("documents: []\n")

    assert find_campaigns([tmp_path]) == []


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
