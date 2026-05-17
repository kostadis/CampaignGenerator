"""Async subprocess runner with SSE streaming output."""

import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path


def _log_stem(cmd: list[str]) -> str:
    """Derive a filename stem from the script being run."""
    for arg in cmd[1:]:
        if arg.endswith(".py"):
            return Path(arg).stem
    return "run"


def _save_run_log(cmd: list[str], cwd: str | None, output: str,
                  returncode: int | None, duration: float) -> None:
    """Persist the run to `logs/` so it survives the SSE buffer.

    Mirrors the format of `campaignlib.save_log` — markdown sections, one
    file per run with a timestamped filename. Failures here are silent;
    logging is best-effort and must not break the running subprocess.
    """
    try:
        log_dir = Path(cwd or os.getcwd()) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        log_file = log_dir / f"{ts}_{_log_stem(cmd)}.md"
        cmd_block = " \\\n  ".join(cmd)
        body = (
            f"# Subprocess run — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"## Command\n\n```\n{cmd_block}\n```\n\n"
            f"## Result\n\n"
            f"- returncode: `{returncode}`\n"
            f"- duration: `{duration:.2f}s`\n"
            f"- cwd: `{cwd or os.getcwd()}`\n\n"
            f"## Output\n\n```\n{output.rstrip()}\n```\n"
        )
        log_file.write_text(body, encoding="utf-8")
    except Exception:
        # Logging is opportunistic — never break the SSE stream.
        pass


async def stream_subprocess(
    cmd: list[str],
    cwd: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    """Run a subprocess and yield Server-Sent Events as output arrives.

    Yields SSE-formatted strings:
      - ``data: "text chunk"\\n\\n`` for stdout/stderr output
      - ``event: done\\ndata: {"returncode": N}\\n\\n`` when the process exits

    `env_extra` is merged on top of the inherited environment after
    ``PYTHONUNBUFFERED``. Used to inject per-route LLM backend env
    (``DGX_ENDPOINT`` / ``DGX_MODEL``) without leaking it into routes that
    must stay on the default Anthropic path.

    On exit, writes a per-run log file under `<cwd>/logs/` capturing the
    command line, returncode, duration, and full output so failed runs can
    be reproduced after the browser session is closed.
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if env_extra:
        env.update(env_extra)

    cmd_display = " \\\n  ".join(cmd)
    yield f"data: {json.dumps(f'$ {cmd_display}\\n\\n')}\n\n"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env=env,
    )

    assert proc.stdout is not None
    buf = ""
    captured: list[str] = []
    started = time.monotonic()
    while True:
        chunk = await proc.stdout.read(64)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        if len(buf) >= 20 or "\n" in buf:
            captured.append(buf)
            yield f"data: {json.dumps(buf)}\n\n"
            buf = ""

    if buf:
        captured.append(buf)
        yield f"data: {json.dumps(buf)}\n\n"

    await proc.wait()
    _save_run_log(cmd, cwd, "".join(captured), proc.returncode,
                  time.monotonic() - started)
    yield f"event: done\ndata: {json.dumps({'returncode': proc.returncode})}\n\n"


def python_exe() -> str:
    """Return the current Python interpreter path."""
    return sys.executable
