"""Tests for the MemPalace JSON-RPC client.

Mixes fast unit coverage (fake subprocess, mocked I/O) with a live
round-trip against the real ``mempalace-mcp`` to catch protocol drift.
The live tests auto-skip if mempalace isn't installed in the test venv.
"""

import json
import shutil
import sys

import pytest

import pipelines.rlm.mempalace_client as mempalace_client
from pipelines.rlm.mempalace_client import (
    FakeMempalaceClient,
    MempalaceClient,
    MempalaceError,
    MempalaceProcessError,
)


# ── FakeMempalaceClient (pure-Python stand-in) ──────────────────────────


class TestFakeMempalaceClient:
    def test_records_calls_and_returns_stock_ack(self):
        fake = FakeMempalaceClient()
        result = fake.add_drawer(wing="wing_x", room="room_y", content="hello")
        assert result == {"ok": True, "tool": "mempalace_add_drawer"}
        assert fake.calls == [
            {
                "tool": "mempalace_add_drawer",
                "arguments": {"wing": "wing_x", "room": "room_y", "content": "hello"},
            }
        ]

    def test_canned_dict_response(self):
        fake = FakeMempalaceClient(
            responses={"mempalace_search": {"results": [{"text": "hit"}]}}
        )
        assert fake.search("anything") == {"results": [{"text": "hit"}]}

    def test_callable_response_sees_arguments(self):
        fake = FakeMempalaceClient(
            responses={
                "mempalace_search_hierarchical": lambda **kw: {"echo": kw},
            }
        )
        got = fake.search_hierarchical("q", max_depth=1, limit=2)
        assert got == {"echo": {"query": "q", "max_depth": 1, "limit": 2}}

    def test_context_manager_marks_closed(self):
        with FakeMempalaceClient() as fake:
            fake.add_drawer(wing="w", room="r", content="c")
        assert fake.closed is True

    def test_list_rooms_forwards_wing(self):
        fake = FakeMempalaceClient()
        fake.list_rooms(wing="notes")
        assert fake.calls[-1]["arguments"] == {"wing": "notes"}


# ── Unit tests for MempalaceClient internals (no subprocess) ────────────


class _StubProc:
    """Minimal subprocess.Popen stand-in driven by in-memory buffers."""

    def __init__(self, queued_responses: list[dict]):
        from io import StringIO

        self.stdin = StringIO()
        # Preload stdout with one response per expected round-trip plus
        # the initialize handshake response.
        lines = [json.dumps(r) + "\n" for r in queued_responses]
        self.stdout = _BlockingReadIO("".join(lines))
        self.stderr = _BlockingReadIO("")
        self._wrote: list[str] = []
        self.terminated = False

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


class _BlockingReadIO:
    """File-like that supports readline() + selectors.EVENT_READ."""

    def __init__(self, text: str):
        from io import StringIO

        self._io = StringIO(text)

    def readline(self):
        return self._io.readline()

    def fileno(self):
        # selectors refuses StringIO directly; this fake client path
        # only runs when call_timeout is None (no selectors involved).
        raise OSError("fake stdio has no fd")

    def __iter__(self):
        return iter(self._io)


@pytest.fixture
def stub_client(monkeypatch):
    """MempalaceClient with Popen monkeypatched to return a _StubProc."""

    def _factory(responses):
        stub = _StubProc(responses)

        def fake_popen(*args, **kwargs):
            return stub

        monkeypatch.setattr(mempalace_client.subprocess, "Popen", fake_popen)

        client = MempalaceClient(
            palace="/fake/path",
            command="/does/not/exist",
            call_timeout=None,     # skip selectors path during tool calls
            startup_timeout=None,  # skip selectors path during initialize too
        )
        return client, stub

    return _factory


class TestClientUnit:
    def test_initialize_is_first_request(self, stub_client):
        # The initialize response, followed by one tool response.
        client, stub = stub_client(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "x"}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps({"ok": True})}
                        ]
                    },
                },
            ]
        )
        client.call_tool("mempalace_ping_stub")

        requests = [json.loads(line) for line in stub.stdin.getvalue().splitlines()]
        client.close()
        assert requests[0]["method"] == "initialize"
        assert requests[1]["method"] == "tools/call"
        assert requests[1]["params"]["name"] == "mempalace_ping_stub"

    def test_unwraps_tool_result_json(self, stub_client):
        payload = {"hits": [1, 2, 3]}
        client, _ = stub_client(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
                },
            ]
        )
        got = client.call_tool("mempalace_search")
        assert got == payload
        client.close()

    def test_empty_content_returns_empty_dict(self, stub_client):
        client, _ = stub_client(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {"jsonrpc": "2.0", "id": 2, "result": {"content": []}},
            ]
        )
        assert client.call_tool("mempalace_anything") == {}
        client.close()

    def test_error_response_raises(self, stub_client):
        client, _ = stub_client(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "error": {"code": -32601, "message": "Unknown tool: bogus"},
                },
            ]
        )
        with pytest.raises(MempalaceError, match="Unknown tool"):
            client.call_tool("bogus")
        client.close()

    def test_closed_stdout_raises_process_error(self, stub_client):
        # Only the initialize response — tool call reads EOF.
        client, _ = stub_client(
            [{"jsonrpc": "2.0", "id": 1, "result": {}}]
        )
        with pytest.raises(MempalaceProcessError):
            client.call_tool("mempalace_anything")
        client.close()

    def test_non_json_payload_raises_process_error(self, stub_client):
        client, stub = stub_client([{"jsonrpc": "2.0", "id": 1, "result": {}}])
        # Manually queue a garbage response for the next read.
        stub.stdout = _BlockingReadIO("not json at all\n")
        with pytest.raises(MempalaceProcessError):
            client.call_tool("mempalace_anything")
        client.close()


# ── Live round-trip against real mempalace-mcp ─────────────────────────


def _mempalace_available() -> bool:
    try:
        import mempalace  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _mempalace_available(),
    reason="mempalace package not installed in this venv",
)
class TestLiveRoundTrip:
    def test_add_drawer_then_list_wings(self, tmp_path):
        palace_path = str(tmp_path / "palace")
        # Use the module entry point so we don't depend on the
        # mempalace-mcp executable being on PATH (it may not be in a
        # nested venv).
        with MempalaceClient(
            palace=palace_path,
            command=sys.executable,
            args=["-m", "mempalace.mcp_server", "--palace", palace_path],
            call_timeout=30.0,
            startup_timeout=30.0,
        ) as mp:
            add_result = mp.add_drawer(
                wing="wing_test",
                room="room_integration",
                content="the quick brown fox jumps over the lazy dog",
            )
            assert isinstance(add_result, dict)

            wings = mp.list_wings()
            # MemPalace returns {"wings": {name: count, ...}} for this tool.
            assert "wings" in wings
            assert "wing_test" in wings["wings"]

    def test_search_hierarchical_on_fresh_palace_falls_back(self, tmp_path):
        palace_path = str(tmp_path / "palace_fresh")
        with MempalaceClient(
            palace=palace_path,
            command=sys.executable,
            args=["-m", "mempalace.mcp_server", "--palace", palace_path],
            call_timeout=30.0,
            startup_timeout=30.0,
        ) as mp:
            # Add something so there's a drawer to find.
            mp.add_drawer(
                wing="wing_live",
                room="room_smoke",
                content="a JWT rotation policy refreshing every 15 minutes",
            )
            hits = mp.search_hierarchical("jwt rotation policy", limit=3)
            # Indices haven't been built on a freshly seeded palace → tool
            # must fall back to flat search and still find the drawer.
            assert hits.get("fallback") is True
            assert hits.get("results")
            assert any(
                "jwt" in (h.get("text") or "").lower() for h in hits["results"]
            )
