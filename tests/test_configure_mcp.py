"""Tests for pipelines/workspace/configure_mcp.py's server-block gating."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipelines.workspace.configure_mcp import build_server_block, configure_campaign, find_campaigns, git_root, main


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
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "refs.yaml").write_text("sources: []\n")

    servers = build_server_block(tmp_path, kanka_token="", kanka_url="")
    assert servers["5etools"]["command"] == "launch_5etools_mcp"


def test_kanka_server_gated_on_token(tmp_path):
    servers = build_server_block(tmp_path, kanka_token="tok", kanka_url="http://x")
    assert servers["kanka"]["env"]["KANKA_TOKEN"] == "tok"


# ── git_root / monorepo .mcp.json placement ─────────────────────────────────

def test_git_root_finds_repo_root_above_a_nested_campaign_dir(tmp_path):
    repo = tmp_path / "workspace"
    (repo / ".git").mkdir(parents=True)
    campaign = repo / "out-of-the-abyss"
    _make_campaign(campaign)

    assert git_root(campaign) == repo


def test_git_root_returns_campaign_dir_when_it_is_the_repo_root_itself(tmp_path):
    campaign = tmp_path / "Phandalin"
    _make_campaign(campaign)
    (campaign / ".git").mkdir()

    assert git_root(campaign) == campaign


def test_git_root_returns_path_itself_when_not_in_a_repo(tmp_path):
    campaign = tmp_path / "no-repo-here"
    _make_campaign(campaign)

    assert git_root(campaign) == campaign


def test_configure_campaign_writes_to_repo_root_not_campaign_dir(tmp_path, capsys):
    repo = tmp_path / "workspace"
    (repo / ".git").mkdir(parents=True)
    campaign = repo / "out-of-the-abyss"
    _make_campaign(campaign)

    mcp_path = configure_campaign(campaign, kanka_token="", kanka_url="", dry_run=False, force=False)

    assert mcp_path == repo / ".mcp.json"
    assert mcp_path.is_file()
    assert not (campaign / ".mcp.json").exists()

    payload = json.loads(mcp_path.read_text())
    # server args/env still point at the campaign dir itself, only the file
    # location moved to the repo root
    assert payload["mcpServers"]["campaign"]["args"] == ["--campaign-dir", str(campaign)]

    out = capsys.readouterr().out
    assert "repo root, not the campaign dir itself" in out


def test_main_warns_when_two_campaigns_share_a_repo_root(tmp_path, capsys):
    repo = tmp_path / "workspace"
    (repo / ".git").mkdir(parents=True)
    _make_campaign(repo / "out-of-the-abyss")
    _make_campaign(repo / "Phandalin")

    rc = main([str(repo), "--dry-run"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "NOTE:" in out
    assert "'out-of-the-abyss'" in out and "overwrote" in out
