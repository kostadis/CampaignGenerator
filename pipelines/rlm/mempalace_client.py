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
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


_DEFAULT_PROTOCOL_VERSION = "2025-06-18"


def known_palaces(config_dir=None, environ=os.environ) -> list[Path]:
    """Palace paths registered in mempalace's config.json (pure file read).

    ``config_dir``: default $MEMPALACE_CONFIG_DIR, else ~/.mempalace. A missing
    or invalid file yields ``[]``.
    """
    if config_dir is None:
        config_dir = environ.get("MEMPALACE_CONFIG_DIR") or "~/.mempalace"
    try:
        data = json.loads((Path(config_dir).expanduser() / "config.json").read_text("utf-8"))
        if not isinstance(data, dict):
            return []
        vals = list((data.get("palaces") or {}).values()) + [data.get("palace_path")]
        return [Path(v).expanduser() for v in vals if isinstance(v, str) and v]
    except (OSError, ValueError, AttributeError):
        return []


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


# ── Library-facing seam (spec 044) ─────────────────────────────────────
#
# pipelines/library never imports mempalace or shells to it; it calls these.
#
# MCP ``mempalace_search`` hit shape (verified against ~/src/Mempalace
# mcp_server/tools_read.py + searcher/*.py, 2026-11-20). ``search`` returns
#
#     {"query", "filters", "total_before_filter", "primary", "results" (alias),
#      "themes", ["error": str]}
#
# and each hit in ``results`` carries ``drawer_id``, ``text`` (the chunk),
# ``wing``, ``room``, ``source_file`` (BASENAME only), ``source_path`` (the
# FULL stored path) and ``similarity``/``distance``. So both ``source_path``
# and ``room`` are present: section mapping by source_path (fallback
# room + basename) works unchanged over MCP. ``limit`` is capped at 100.
#
# R10 (delete on refresh): the MCP surface has NO delete-by-room tool, but it
# has ``mempalace_delete_by_source`` (exact source_file, bulk, also purges
# closets) and ``mempalace_list_drawers`` (wing/room filter, drawers carry
# ``metadata.source_file``). ``delete_room`` composes them: list the room,
# delete each distinct source. No rebuild fallback is needed.

import tempfile
from pathlib import Path

_LIST_PAGE = 100


def mine(
    render_root,
    *,
    palace,
    wing: str,
    env: dict | None = None,
    files: Iterable[str] | None = None,
    stream: bool = True,
) -> str:
    """Run ``mempalace mine <root> --direct --wing <wing>`` against ``palace``.

    ``--direct``: the shared daemon could be serving a live palace. ``files``
    (relative to ``render_root``) limits the run to exactly those files via
    ``--files-from``. ``env`` is passed through; the caller's dict is not
    mutated. Raises :class:`MempalaceProcessError` on a non-zero exit.

    stderr is merged into stdout. With ``stream`` (default) each line is echoed
    live to *this process's stderr* (so stdout stays clean for JSON); the
    full output is still collected and returned, and the error message uses
    its last 500 chars.
    """
    run_env = dict(env if env is not None else os.environ)
    run_env["MEMPALACE_PALACE_PATH"] = str(palace)
    # A piped child Python block-buffers stdout; without this, per-file progress
    # arrives in 8 KB bursts instead of live.
    run_env["PYTHONUNBUFFERED"] = "1"
    cmd = ["mempalace", "--palace", str(palace), "mine", str(render_root), "--direct", "--wing", wing]
    tmp = None
    try:
        if files is not None:
            tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
            tmp.write("\n".join(files))
            tmp.close()
            cmd += ["--files-from", tmp.name]
        proc = subprocess.Popen(
            cmd, env=run_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        chunks: list[str] = []
        try:
            for line in proc.stdout:
                chunks.append(line)
                if stream:
                    sys.stderr.write(line if line.endswith("\n") else line + "\n")
                    sys.stderr.flush()
        finally:
            proc.stdout.close()
            returncode = proc.wait()
    finally:
        if tmp is not None:
            Path(tmp.name).unlink(missing_ok=True)
    out = "".join(chunks)
    if returncode != 0:
        raise MempalaceProcessError(
            f"mempalace mine exited {returncode}: {out.strip()[-500:]}"
        )
    return out


def _check_result(result, what: str) -> None:
    """Raise MempalaceError for an error / unsuccessful tool result."""
    if not isinstance(result, dict):
        return
    if result.get("error") or result.get("success") is False:
        raise MempalaceError(f"mempalace could not {what}: {result.get('error') or result}")


def delete_room(palace, wing: str, room: str, *, client=None, env: dict | None = None) -> int:
    """Delete every drawer in ``wing``/``room``; return distinct sources removed."""
    own = client is None
    client = client or MempalaceClient(palace=str(palace), env=env)
    try:
        sources: set[str] = set()
        orphans: list[str] = []
        offset = 0
        while True:
            page = client.call_tool(
                "mempalace_list_drawers", wing=wing, room=room, limit=_LIST_PAGE, offset=offset
            )
            _check_result(page, f"list drawers {wing}/{room}")
            drawers = page.get("drawers") or []
            for d in drawers:
                src = (d.get("metadata") or {}).get("source_file")
                if src:
                    sources.add(src)
                elif d.get("drawer_id"):
                    orphans.append(d["drawer_id"])
            offset += len(drawers)
            if not drawers or offset >= int(page.get("total") or 0):
                break
        for src in sorted(sources):
            _check_result(
                client.call_tool("mempalace_delete_by_source", source_file=src, dry_run=False),
                f"delete drawers of {src}",
            )
        for did in orphans:
            _check_result(
                client.call_tool("mempalace_delete_drawer", drawer_id=did),
                f"delete drawer {did}",
            )
        return len(sources) + len(orphans)
    finally:
        if own:
            client.close()


def search(
    query: str,
    *,
    palace,
    wing: str | None = None,
    limit: int = 50,
    env: dict | None = None,
    client_factory=None,
) -> dict:
    """Search an explicit palace path (passes ``--palace`` to the server)."""
    factory = client_factory or MempalaceClient
    client = factory(palace=str(palace), env=env)
    try:
        kwargs: dict = {"limit": limit}
        if wing:
            kwargs["wing"] = wing
        return client.search(query, **kwargs)
    finally:
        client.close()


class LibraryPalaceClient:
    """The object ``pipelines/library`` is handed: one palace, one env.

    Thin binding of :func:`mine` / :func:`delete_room` / :func:`search` so the
    library layer never touches mempalace itself (Principle V).
    """

    def __init__(self, palace, env: dict | None = None):
        self.palace = palace
        self.env = env

    def mine(self, render_root, *, wing: str, files: Iterable[str] | None = None,
             stream: bool = True) -> str:
        return mine(render_root, palace=self.palace, wing=wing, env=self.env, files=files,
                    stream=stream)

    def delete_room(self, wing: str, room: str) -> int:
        return delete_room(self.palace, wing, room, env=self.env)

    def search(self, query: str, *, wing: str | None = None, limit: int = 50) -> dict:
        return search(query, palace=self.palace, wing=wing, limit=limit, env=self.env)


__all__ = [
    "LibraryPalaceClient",
    "mine",
    "delete_room",
    "search",
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
