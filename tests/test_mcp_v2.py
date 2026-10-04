"""Smoke-test each Python server against the installed MCP SDK."""

import asyncio

from entity_registry.registry_mcp import build_server as build_registry_server
from pipelines.integrations.kanka.kanka_mcp import build_server as build_kanka_server
from pipelines.rlm.mcp_server import mcp as campaign_server
from provenance.provenance_mcp import build_server as build_provenance_server


def test_all_python_servers_register_with_mcp_v2(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPAIGNS_ROOT", str(tmp_path))

    async def check():
        servers = {
            "campaign": campaign_server,
            "registry": build_registry_server(tmp_path),
            "kanka": build_kanka_server(),
            "provenance": build_provenance_server(),
        }
        for name, server in servers.items():
            assert server.name == name
            assert await server.list_tools(), name

        resources = await campaign_server.list_resources()
        assert {str(resource.uri) for resource in resources} >= {
            "campaign://docs/campaign_state",
            "campaign://docs/world_state",
        }

    asyncio.run(check())
