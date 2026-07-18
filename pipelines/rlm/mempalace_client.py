"""
mempalace_client.py — JSON-RPC stdio client for the MemPalace MCP server.

Phase 2 of the RLM integration plan routes every CampaignGenerator ↔ MemPalace
interaction through the MCP boundary — reads, writes, hierarchical searches,
everything — so MemPalace stays a black box with a stable tool surface. This
module is the only file in CampaignGenerator that knows how to spawn
``mempalace-mcp`` and speak its protocol.

Usage (CLI / script):

    from pipelines.rlm.mempalace_client import MempalaceClient

    with MempalaceClient(palace="/mnt/data/mempalace/palaces/chat") as mp:
        mp.add_drawer(wing="wing_bestiary", room="room_ravnica",
                      content="Bugbear Chieftain\\nAC 17 HP 65 ...")
        hits = mp.search_hierarchical("fey forest encounter mid-level",
                                      max_depth=2, limit=5)

The client is unit-test friendly: callers accept a ``MempalaceClient`` or a
protocol-compatible stub (see ``tests/test_mempalace_client.py``). No
network. No state shared across processes. One subprocess per client.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class MempalaceError(RuntimeError):
    """Raised when the MemPalace server reports a JSON-RPC error."""


class MempalaceProcessError(RuntimeError):
    """Raised when the MemPalace subprocess dies or misbehaves."""


class MempalaceClient:
    """Stdio JSON-RPC client around ``mempalace-mcp``.

    The subprocess is spawned on first use (lazy) or at ``__enter__`` when
    used as a context manager. All calls are synchronous; a process-local
    lock serializes concurrent requests so the request/response ordering
    on stdin/stdout stays intact.

    Args:
        palace: Palace alias ("chat", "oota", …) or absolute path. Passed
            to mempalace-mcp via ``--palace``. If ``None``, the server's
            own config-resolution chain kicks in.
        command: Executable to spawn. Defaults to ``mempalace-mcp``
            resolved via ``shutil.which``. Override for testing / unusual
            installs.
        env: Environment for the subprocess. ``None`` inherits the
            parent's environment — typical for CLI scripts.
        startup_timeout: Seconds to wait for the initialize handshake.
        call_timeout: Seconds per tool call. ``None`` waits indefinitely.
    """

    def __init__(
        self,
        palace: str | None = None,
        *,
        command: str | None = None,
        args: Iterable[str] | None = None,
        env: dict[str, str] | None = None,
        startup_timeout: float | None = 15.0,
        call_timeout: float | None = 60.0,
        protocol_version: str = _DEFAULT_PROTOCOL_VERSION,
    ):
        self.palace = palace
        self._user_command = command
        self._user_args = list(args) if args else None
        self._env = env
        self._startup_timeout = startup_timeout
        self._call_timeout = call_timeout
        self._protocol_version = protocol_version

        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next_id = 0
        self._initialized = False

    # ── Lifecycle ─────────────────────────────────────────────────────

    def __enter__(self) -> "MempalaceClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        """Spawn the subprocess and complete the initialize handshake."""
        if self._proc is not None:
            return

        cmd = self._resolve_command()
        logger.debug("mempalace_client: spawning %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._env,
        )
        # Drain stderr in a background thread so a noisy server doesn't
        # deadlock the OS pipe buffer when the parent is busy on stdout.
        threading.Thread(
            target=self._drain_stderr, name="mempalace-stderr", daemon=True
        ).start()

        try:
            self._initialize()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Shut the subprocess down cleanly. Safe to call twice."""
        proc = self._proc
        self._proc = None
        self._initialized = False
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ── Convenience wrappers ──────────────────────────────────────────
    #
    # These mirror the shape of the MemPalace MCP tool set. They each
    # delegate to ``call_tool``; a caller that wants a tool not listed
    # here (e.g. ``mempalace_kg_add``) can just call ``call_tool``
    # directly.

    def add_drawer(
        self,
        *,
        wing: str,
        room: str,
        content: str,
        **extra: Any,
    ) -> dict:
        """Append one drawer via ``mempalace_add_drawer``."""
        payload = {"wing": wing, "room": room, "content": content}
        payload.update(extra)
        return self.call_tool("mempalace_add_drawer", **payload)

    def search(self, query: str, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_search", query=query, **kwargs)

    def search_hierarchical(self, query: str, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_search_hierarchical", query=query, **kwargs)

    def list_wings(self, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_list_wings", **kwargs)

    def list_rooms(self, wing: str | None = None, **kwargs: Any) -> dict:
        if wing is not None:
            kwargs["wing"] = wing
        return self.call_tool("mempalace_list_rooms", **kwargs)

    def reconnect(self) -> dict:
        return self.call_tool("mempalace_reconnect")

    def get_taxonomy(self, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_get_taxonomy", **kwargs)

    # ── Core request plumbing ─────────────────────────────────────────

    def call_tool(self, tool_name: str, **arguments: Any) -> dict:
        """Call one MCP tool; return its parsed JSON result.

        MemPalace wraps every tool return in
        ``{"content": [{"type": "text", "text": "<json-dump>"}]}``. We
        unwrap and ``json.loads`` it so callers get the natural dict the
        tool handler produced.
        """
        self.start()  # idempotent lazy-start
        req_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        response = self._send_and_recv(request)
        return self._unwrap_tool_result(tool_name, response)

    def raw(self, method: str, params: dict | None = None) -> dict:
        """Send a raw JSON-RPC method (escape hatch for non-tool calls)."""
        self.start()
        req_id = self._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        return self._send_and_recv(request)

    # ── Internals ─────────────────────────────────────────────────────

    def _resolve_command(self) -> list[str]:
        if self._user_command is not None:
            cmd = [self._user_command]
        else:
            exe = shutil.which("mempalace-mcp")
            if exe:
                cmd = [exe]
            else:
                # Fall back to running the module directly so developers
                # running from a checkout (no `pip install`) still work.
                import sys

                cmd = [sys.executable, "-m", "mempalace.mcp_server"]

        if self._user_args is not None:
            cmd += list(self._user_args)
        elif self.palace is not None:
            cmd += ["--palace", self.palace]
        return cmd

    def _next_request_id(self) -> int:
        with self._lock:
            self._next_id += 1
            return self._next_id

    def _send_and_recv(self, request: dict) -> dict:
        if self._proc is None:
            raise MempalaceProcessError("subprocess not started")
        payload = json.dumps(request) + "\n"

        with self._lock:
            proc = self._proc
            if proc is None or proc.stdin is None or proc.stdout is None:
                raise MempalaceProcessError("subprocess stdio unavailable")
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise MempalaceProcessError(
                    f"failed to write request: {exc}"
                ) from exc

            line = self._read_response_line(proc)
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MempalaceProcessError(
                f"invalid JSON from mempalace-mcp: {line!r}"
            ) from exc

        if "error" in response:
            err = response["error"]
            raise MempalaceError(
                f"{request['method']}: code={err.get('code')} {err.get('message')}"
            )
        return response

    def _read_response_line(self, proc: subprocess.Popen) -> str:
        # subprocess.Popen in text mode with bufsize=1 is line-buffered on
        # stdin; stdout readline() blocks until a newline. The call_timeout
        # governs the whole round trip.
        import selectors

        if self._call_timeout is None:
            line = proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                raise MempalaceProcessError(
                    "mempalace-mcp closed stdout before responding"
                )
            return line

        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)  # type: ignore[arg-type]
        events = sel.select(self._call_timeout)
        sel.close()
        if not events:
            raise MempalaceProcessError(
                f"mempalace-mcp did not respond within {self._call_timeout}s"
            )
        line = proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            raise MempalaceProcessError(
                "mempalace-mcp closed stdout before responding"
            )
        return line

    def _initialize(self) -> None:
        request = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "campaign-generator", "version": "phase2"},
            },
        }
        # Temporarily widen the timeout for the handshake; Chroma can take
        # several seconds on first palace open.
        saved = self._call_timeout
        self._call_timeout = self._startup_timeout
        try:
            self._send_and_recv(request)
        finally:
            self._call_timeout = saved
        self._initialized = True

    def _unwrap_tool_result(self, tool_name: str, response: dict) -> dict:
        result = response.get("result") or {}
        content = result.get("content") or []
        if not content:
            return {}
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else None
        if not isinstance(text, str) or not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise MempalaceProcessError(
                f"tool {tool_name} returned non-JSON text: {text[:200]!r}"
            ) from exc

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            logger.debug("mempalace-mcp stderr: %s", line.rstrip())


# ── Null client for tests ──────────────────────────────────────────────


class FakeMempalaceClient:
    """In-process stand-in for :class:`MempalaceClient` used in unit tests.

    Records every ``call_tool`` / ``add_drawer`` call for assertions and
    returns a canned response (either a callable, a dict, or a stock
    acknowledgment). Does not speak JSON-RPC and never spawns a
    subprocess — tests stay fast.
    """

    def __init__(self, responses: dict | None = None):
        self.calls: list[dict] = []
        self.responses = responses or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self):
        pass

    def close(self):
        self.closed = True

    def call_tool(self, tool_name: str, **arguments: Any) -> dict:
        self.calls.append({"tool": tool_name, "arguments": arguments})
        response = self.responses.get(tool_name)
        if callable(response):
            return response(**arguments)
        if isinstance(response, dict):
            return response
        return {"ok": True, "tool": tool_name}

    def add_drawer(self, *, wing: str, room: str, content: str, **extra: Any) -> dict:
        return self.call_tool(
            "mempalace_add_drawer", wing=wing, room=room, content=content, **extra
        )

    def search(self, query: str, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_search", query=query, **kwargs)

    def search_hierarchical(self, query: str, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_search_hierarchical", query=query, **kwargs)

    def list_wings(self, **kwargs: Any) -> dict:
        return self.call_tool("mempalace_list_wings", **kwargs)

    def list_rooms(self, wing: str | None = None, **kwargs: Any) -> dict:
        if wing is not None:
            kwargs["wing"] = wing
        return self.call_tool("mempalace_list_rooms", **kwargs)

    def reconnect(self) -> dict:
        return self.call_tool("mempalace_reconnect")


__all__ = [
    "MempalaceClient",
    "FakeMempalaceClient",
    "MempalaceError",
    "MempalaceProcessError",
]


def _demo() -> None:  # pragma: no cover — manual smoke test
    """Run a tiny round-trip against a real mempalace-mcp for debugging.

    Usage::

        python pipelines/rlm/mempalace_client.py /path/to/palace
    """
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("palace")
    p.add_argument("--query", default="test")
    args = p.parse_args()

    with MempalaceClient(palace=args.palace) as mp:
        print(json.dumps(mp.list_wings(), indent=2))
        print(json.dumps(mp.search_hierarchical(args.query, limit=3), indent=2))


if __name__ == "__main__":  # pragma: no cover
    _demo()
