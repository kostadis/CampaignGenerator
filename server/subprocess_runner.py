"""Async subprocess runner with SSE streaming output."""

import asyncio
import json
import os
import sys
from collections.abc import AsyncGenerator


async def stream_subprocess(
    cmd: list[str],
    cwd: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run a subprocess and yield Server-Sent Events as output arrives.

    Yields SSE-formatted strings:
      - ``data: "text chunk"\\n\\n`` for stdout/stderr output
      - ``event: done\\ndata: {"returncode": N}\\n\\n`` when the process exits
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=env,
    )

    assert proc.stdout is not None
    buf = ""
    while True:
        chunk = await proc.stdout.read(64)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        if len(buf) >= 20 or "\n" in buf:
            yield f"data: {json.dumps(buf)}\n\n"
            buf = ""

    if buf:
        yield f"data: {json.dumps(buf)}\n\n"

    await proc.wait()
    yield f"event: done\ndata: {json.dumps({'returncode': proc.returncode})}\n\n"


def python_exe() -> str:
    """Return the current Python interpreter path."""
    return sys.executable
