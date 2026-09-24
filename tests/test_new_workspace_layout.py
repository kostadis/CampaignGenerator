"""new_workspace writes the one valid config location.

It used to write a top-level <workspace>/config.yaml with docs/ paths — the
legacy layout that find_default_config, check_consistency and mcp_server now
reject — so every freshly created campaign failed on first use.
"""

from __future__ import annotations

import sys

from campaignlib import assemble_docs, campaign_root_for_config, load_config
from pipelines.workspace import new_workspace

_LABELS = ["campaign_state", "world_state", "mechanics", "planning", "party"]


def test_new_workspace_writes_config_dir_config(tmp_path, monkeypatch):
    workspace = tmp_path / "ws"
    external = tmp_path / "lore.md"
    external.write_text("External lore.", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "new_workspace", str(workspace), "--world-state", str(external),
    ])

    new_workspace.main()

    config_file = workspace / "config" / "config.yaml"
    assert config_file.is_file()
    assert not (workspace / "config.yaml").exists()
    assert campaign_root_for_config(config_file) == workspace.resolve()

    config, base_dir = load_config(str(config_file))
    paths = {d["label"]: d["path"] for d in config["documents"]}
    assert paths["campaign_state"] == "../docs/campaign_state.md"
    assert paths["world_state"] == str(external.resolve())
    assert "External lore." in assemble_docs(config, _LABELS, base_dir)
