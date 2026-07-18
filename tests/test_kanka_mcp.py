"""Tests for kanka_mcp.py core functions.

The FastMCP tool wrappers need the `mcp` package; the core functions
(pull_world_state / push_preview / push_apply) are pure wrappers over the
already-tested kanka_sync + kanka_push engines and are exercised here with a
FakeClient — no `mcp` dependency required. The module must import even when
`mcp` is not installed (the FastMCP import is guarded).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelines.integrations.kanka import kanka_mcp


class FakeClient:
    def __init__(self, existing=None, campaigns=None):
        self.existing = existing or {}
        self.campaigns = campaigns or [{"id": 1, "name": "Test Campaign"}]
        self.created = []
        self.updated = []

    def list_campaigns(self):
        return self.campaigns

    def list_all(self, campaign_id, entity_type):
        return self.existing.get(entity_type, [])

    def create(self, campaign_id, entity_type, **fields):
        self.created.append((entity_type, fields))
        return {"id": 999, **fields}

    def update(self, campaign_id, entity_type, record_id, **fields):
        self.updated.append((entity_type, record_id, fields))
        return {"id": record_id, **fields}


def test_pull_renders_world_state_markdown():
    client = FakeClient(existing={
        "characters": [{"id": 1, "name": "Sera Voss", "entry": "<p>Spy.</p>"}],
    })
    md = kanka_mcp.pull_world_state(client, 1)
    assert "## NPCs" in md
    assert "Sera Voss" in md


def test_push_preview_reports_plan_without_writing():
    client = FakeClient(existing={"characters": []})
    md = "## NPCs\n\n**New NPC**\n\nbody"
    out = kanka_mcp.push_preview(client, 1, md)
    assert client.created == []           # preview must never write
    assert "create=1" in out
    assert "CREATE characters/New NPC" in out


def test_push_apply_commits_and_reports_counts():
    client = FakeClient(existing={
        "characters": [{"id": 5, "name": "Sera Voss", "entry": "<p>Old.</p>"}],
    })
    md = "## NPCs\n\n**Sera Voss**\n\nNew text.\n\n**Fresh NPC**\n\nHi."
    out = kanka_mcp.push_apply(client, 1, md)
    assert len(client.updated) == 1
    assert len(client.created) == 1
    assert "update=1" in out
    assert "create=1" in out
    assert "failed=0" in out


def test_push_apply_surfaces_failures():
    class Flaky(FakeClient):
        def update(self, campaign_id, entity_type, record_id, **fields):
            raise RuntimeError("kanka 422")

    client = Flaky(existing={
        "characters": [{"id": 5, "name": "Sera Voss", "entry": "<p>Old.</p>"}],
    })
    md = "## NPCs\n\n**Sera Voss**\n\nNew text."
    out = kanka_mcp.push_apply(client, 1, md)
    assert "failed=1" in out


def test_module_imports_and_exposes_core_without_mcp():
    # Reaching this line means `import kanka_mcp` succeeded despite `mcp` being
    # absent in this env — i.e. the FastMCP import is properly guarded.
    assert hasattr(kanka_mcp, "pull_world_state")
    assert hasattr(kanka_mcp, "push_preview")
    assert hasattr(kanka_mcp, "push_apply")
    assert hasattr(kanka_mcp, "build_server")
