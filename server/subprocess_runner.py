"""Async subprocess runner with SSE streaming output.

Shared seam used by ALL SSE routes (ensemble, grounding, prep, setup,
scene_editor, …). The termination behaviour added here (T020–T021: start_new_session
+ group-kill on disconnect) is intentionally global — no route should leak a runaway
subprocess when the client disconnects. Non-ensemble routes' request/response shapes
are unchanged; they additionally gain disconnect-driven cleanup for free.
See plan.md "Constraints / Shared-seam blast radius (I2)" and tests/test_subprocess_abort.py
for regression coverage.
"""

import asyncio
import json
import os
import signal
import sys
import time
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from pathlib import Path

GRACE_SECONDS = 4.0  # SIGTERM grace window before SIGKILL (FR-008)


def classify_result(returncode: int | None) -> str:
    """Map a subprocess returncode to a run outcome string (R5, data-model.md).

    - ``None`` or negative (signal) → ``"aborted"``
    - ``0``                         → ``"succeeded"``
    - positive non-zero             → ``"failed"``
    """
    if returncode is None or returncode < 0:
        return "aborted"
    if returncode == 0:
        return "succeeded"
    return "failed"


def _killpg_safe(pgid: int, sig: int) -> None:
    """Send sig to process group pgid, silently ignoring ProcessLookupError."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _log_stem(cmd: list[str]) -> str:
    """Derive a filename stem from the script or console command being run.

    Scripts not yet migrated still run as ``[python_exe(), "<name>.py", ...]``
    (matched via the ``.py`` scan below). Migrated scripts run as a bare
    console-script entry point (see :func:`console_script`) with no ``.py``
    argument anywhere in ``cmd`` — fall back to ``cmd[0]``'s own stem so their
    log files still get a meaningful name instead of the generic ``"run"``.
    """
    for arg in cmd[1:]:
        if arg.endswith(".py"):
            return Path(arg).stem
    return Path(cmd[0]).stem if cmd else "run"


def _save_run_log(cmd: list[str], cwd: str | None, output: str,
                  returncode: int | None, result: str, duration: float) -> None:
    """Persist the run to `logs/` so it survives the SSE buffer (FR-007, SC-006).

    Mirrors the format of `campaignlib.save_log` — markdown sections, one file
    per run with a timestamped filename. Failures here are silent; logging is
    best-effort and must not break the running subprocess. Runs on every exit
    path (normal, abort, disconnect) via the finally in stream_subprocess.
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
            f"- result: `{result}`\n"
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
    on_complete: Callable[[int | None], None] | None = None,
    emit_done: bool = True,
) -> AsyncGenerator[str, None]:
    """Run a subprocess and yield Server-Sent Events as output arrives.

    Yields SSE-formatted strings (in order):
      - ``event: command\\ndata: "<invocation>"\\n\\n`` — distinct named event
        carrying the secret-free, copyable invocation (US1, FR-001/002/003)
      - ``data: "$ <invocation>\\n\\n"\\n\\n`` — legacy inline chunk (back-compat)
      - ``data: "text chunk"\\n\\n`` — stdout/stderr as produced (US2, FR-004)
      - ``event: done\\ndata: {...}\\n\\n`` — terminal event (US3, FR-006)

    `env_extra` is merged on top of the inherited environment after
    ``PYTHONUNBUFFERED``. Secrets (API keys) are inherited from the server
    environment, never on the command line — so cmd_display is secret-safe.

    `on_complete`, if provided, fires once with the returncode (or None on
    abort) from the finally block — always fires on every exit path so that
    callers (e.g. ensemble.py's _RUNNING lock release) are never orphaned.

    `emit_done` (default True) controls the terminal ``event: done`` yield.
    Pass False when this call is a NON-final stage of a chained response
    (e.g. the consistency pass before the plan pass in scene_editor's /plan):
    ``connectSSE`` closes the EventSource on the first ``done`` it sees, which
    would disconnect the client mid-chain and group-kill the next subprocess.
    Everything else (command event, output, log write, on_complete) is
    unaffected — only the post-``finally`` ``done`` yield is suppressed.

    On exit (normal, explicit-abort, or disconnect), writes a per-run log
    under ``<cwd>/logs/`` capturing the command, full output, result, and
    duration — survives browser close (FR-007, SC-006).

    Termination (US4, R1):
    Subprocess is launched in its own session (``start_new_session=True``) so
    the whole worker tree is signalable as a group. When the client disconnects
    (or calls es.close()), Starlette cancels the response task via anyio's
    cancel scope, which propagates as CancelledError into this generator.  The
    finally block sends SIGTERM to the process group and schedules SIGKILL via
    loop.call_later (avoiding any await in the cancelled context, where any await
    would re-raise CancelledError immediately, per Starlette's anyio cancel scope).
    """
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if env_extra:
        env.update(env_extra)

    env_prefix = " \\\n  ".join(f"{k}={v}" for k, v in (env_extra or {}).items())
    cmd_parts = ([env_prefix] if env_prefix else []) + list(cmd)
    cmd_display = " \\\n  ".join(cmd_parts)

    # proc is initialised here so the finally can reference it even if aclose()
    # is called before the subprocess starts (e.g. during the command yields).
    proc: asyncio.subprocess.Process | None = None
    buf = ""
    captured: list[str] = []
    started = time.monotonic()

    try:
        # US1: distinct named event for copyable command (FR-001/002/003) — FIRST
        # These yields are inside the try so that aclose() before subprocess start
        # still triggers the finally (on_complete / log write).
        yield f"event: command\ndata: {json.dumps(cmd_display)}\n\n"
        # Back-compat inline chunk (clients ignoring the command event still see it)
        yield f"data: {json.dumps(f'$ {cmd_display}\\n\\n')}\n\n"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
            env=env,
            start_new_session=True,  # own process group → killpg kills child workers (R1)
        )

        assert proc.stdout is not None
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

    finally:
        # Fires on: normal exit, explicit abort (es.close()), browser disconnect.
        # Guard on proc/returncode to avoid signaling an already-exited process
        # or one that was never started (aclose before proc was created).
        if proc is not None and proc.returncode is None:
            try:
                pgid = os.getpgid(proc.pid)
                _killpg_safe(pgid, signal.SIGTERM)
                # SIGKILL via call_later — do NOT await here. Starlette delivers
                # disconnect as anyio cancel-scope cancellation, which makes any
                # await in this finally re-raise CancelledError immediately.
                # call_later schedules from the event loop after finally exits,
                # guaranteeing bounded stop within GRACE_SECONDS (FR-008).
                loop = asyncio.get_running_loop()
                loop.call_later(GRACE_SECONDS, _killpg_safe, pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # already exited between the returncode check and getpgid

        returncode = proc.returncode if proc is not None else None
        result = classify_result(returncode)
        _save_run_log(cmd, cwd, "".join(captured), returncode, result,
                      time.monotonic() - started)
        if on_complete is not None:
            try:
                on_complete(returncode)
            except Exception:
                pass  # activity recording is opportunistic — never break the stream

    # Only reached on normal completion (abort/disconnect exits via exception propagation)
    if proc is not None and emit_done:
        result = classify_result(proc.returncode)
        done_payload: dict[str, object] = {"returncode": proc.returncode}
        if result == "aborted":
            done_payload["aborted"] = True
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"


async def sse_error_stream(message: str, returncode: int = 1) -> AsyncGenerator[str, None]:
    """Emit a precondition failure as an SSE stream an EventSource can read.

    A plain ``JSONResponse(..., status_code=400)`` is invisible to the
    browser's ``EventSource``: it only sees a connection error with no body,
    so the frontend can only show a generic "Stream error". Instead we open
    a real ``text/event-stream`` and emit the reason as a ``data`` chunk
    (so it lands in the output panel) followed by a non-zero ``done`` event
    carrying the same message. The ``done`` handler then surfaces the actual
    cause ("characters not configured") instead of masking it.
    """
    yield f"data: {json.dumps(message.rstrip() + chr(10))}\n\n"
    yield f"event: done\ndata: {json.dumps({'returncode': returncode, 'error': message})}\n\n"


def python_exe() -> str:
    """Return the current Python interpreter path."""
    return sys.executable


def console_script(name: str) -> str:
    """Return the path to a console-script entry point (pyproject.toml's
    ``[project.scripts]``) installed in the same venv as the running server.

    Scripts that have migrated into ``pipelines/`` no longer live at a fixed
    path relative to the repo root, so callers invoke them by their installed
    command name instead of ``python_exe() + SCRIPT_DIR / "<name>.py"``.
    Resolved via ``sys.executable``'s own directory rather than ``$PATH``, so
    it works whether or not the venv is "activated" in the parent shell —
    the same robustness ``python_exe()`` already gives the interpreter path.
    """
    return str(Path(python_exe()).parent / name)
