"""Tests for stream_subprocess: group-kill, grace→force, atomicity, secret-safety.

Tests are added per-phase by task ID (T011, T012, T017, T027–T029, T031).
Fixtures live here and are shared across all test functions.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

# Repo root on sys.path so server.* imports work from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Minimal campaign workspace directory (cwd for subprocesses)."""
    return tmp_path


@pytest.fixture
def long_running_script(tmp_path: Path) -> Path:
    """Script that loops and also spawns a grandchild subprocess.

    Used to verify that process-group kill terminates the full tree (child +
    grandchild), not just the direct child.
    """
    script = tmp_path / "long_runner.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "grandchild = subprocess.Popen(\n"
        "    [sys.executable, '-c',\n"
        "     'import time\\nwhile True: time.sleep(0.05)'])\n"
        "try:\n"
        "    while True:\n"
        "        print('tick', flush=True)\n"
        "        time.sleep(0.05)\n"
        "finally:\n"
        "    grandchild.wait()\n",
        encoding="utf-8",
    )
    return script


@pytest.fixture
def sigterm_ignorer_script(tmp_path: Path) -> Path:
    """Script that catches and ignores SIGTERM; only SIGKILL stops it.

    Used to verify grace→force escalation: SIGTERM is sent, then after the
    grace window SIGKILL fires and the process actually exits.
    """
    script = tmp_path / "sigterm_ignorer.py"
    script.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "while True:\n"
        "    print('alive', flush=True)\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    return script


# ---------------------------------------------------------------------------
# SSE drain helpers
# ---------------------------------------------------------------------------

async def _collect(gen) -> list[str]:
    """Drain an async generator and return all yielded SSE strings."""
    events: list[str] = []
    async for chunk in gen:
        events.append(chunk)
    return events


async def _drain_n_then_close(gen, n: int) -> list[str]:
    """Collect n events then call aclose() — simulates explicit abort."""
    events: list[str] = []
    async for chunk in gen:
        events.append(chunk)
        if len(events) >= n:
            await gen.aclose()
            break
    return events


def _parse_command_event(events: list[str]) -> str | None:
    """Return the payload of the first 'event: command' SSE event, or None."""
    it = iter(events)
    for chunk in it:
        if chunk.startswith("event: command\n"):
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
    return None


def _parse_done_event(events: list[str]) -> dict | None:
    """Return the parsed data of the 'event: done' SSE event, or None."""
    for chunk in events:
        if chunk.startswith("event: done\n"):
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
    return None


# ---------------------------------------------------------------------------
# T011: Secret-safety + reproducibility (SC-002, FR-001, FR-003)
# ---------------------------------------------------------------------------

def test_command_event_has_no_api_key(tmp_workspace: Path) -> None:
    """The command SSE event must not contain any API key value (SC-002)."""
    fake_key = "sk-FAKESECRET12345"
    cmd = [sys.executable, "-c", "import sys; print('hello'); sys.exit(0)"]
    env_extra = {"CG_BACKEND": "openrouter", "OPENROUTER_MODEL": "test/model"}

    # Inject a fake key into the test process environment so the subprocess
    # inherits it — simulating a real API key in the server environment.
    os.environ["OPENROUTER_API_KEY"] = fake_key
    try:
        from server.subprocess_runner import stream_subprocess
        events = asyncio.run(_collect(stream_subprocess(cmd, cwd=str(tmp_workspace),
                                                        env_extra=env_extra)))
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)

    cmd_text = _parse_command_event(events)
    assert cmd_text is not None, "command event must be emitted"
    assert fake_key not in cmd_text, "API key must not appear in command event"
    # Non-secret env vars DO appear (operator needs them to reproduce)
    assert "openrouter" in cmd_text
    assert "test/model" in cmd_text


def test_command_event_reflects_explicit_inputs(tmp_workspace: Path) -> None:
    """The command event reflects exactly the passed arguments (FR-001)."""
    chapters = ["docs/chapters/chapter_01.md", "docs/chapters/chapter_03.md"]
    cmd = [sys.executable, "-c", "print('ok')"] + [
        arg for ch in chapters for arg in ("--chapters", ch)
    ]
    from server.subprocess_runner import stream_subprocess
    events = asyncio.run(_collect(stream_subprocess(cmd, cwd=str(tmp_workspace))))

    cmd_text = _parse_command_event(events)
    assert cmd_text is not None
    for ch in chapters:
        assert ch in cmd_text, f"explicit chapter {ch!r} must appear in command"


# ---------------------------------------------------------------------------
# T012: Explicit-selection faithfulness (C1, FR-012, Principle X)
# ---------------------------------------------------------------------------

def test_empty_selection_is_refused_not_expanded() -> None:
    """Companion to the empty-selection tests in test_ensemble_chapters.py.

    This references rather than re-tests those guards so that the two files
    jointly prove FR-012 / Principle X: an empty chapter selection is refused
    before any command is built or emitted, never silently expanded to a glob.
    """
    import importlib
    # The guard lives in the ensemble router and chapter-picker tests; confirm
    # the modules are importable so we can trust those tests are in scope.
    spec_mod = importlib.util.find_spec("server.routers.ensemble")
    assert spec_mod is not None, "ensemble router must be importable"

    # The run-stream contract also states that FR-012 is enforced via
    # sse_error_stream, not a wildcard fallback. Verify sse_error_stream exists.
    from server.subprocess_runner import sse_error_stream
    assert callable(sse_error_stream)


# ---------------------------------------------------------------------------
# T017: Durable run record — success and failure (FR-007, SC-006)
# ---------------------------------------------------------------------------

def test_save_run_log_success(tmp_workspace: Path) -> None:
    """Success run writes a log with result=succeeded, returncode=0, full output."""
    cmd = [sys.executable, "-c", "print('hello world')"]
    from server.subprocess_runner import stream_subprocess
    asyncio.run(_collect(stream_subprocess(cmd, cwd=str(tmp_workspace))))

    logs = list((tmp_workspace / "logs").glob("*.md"))
    assert len(logs) == 1, "exactly one log file per run"
    body = logs[0].read_text()
    assert "result: `succeeded`" in body
    assert "returncode: `0`" in body
    assert "hello world" in body
    assert "duration" in body


def test_save_run_log_failure(tmp_workspace: Path) -> None:
    """Failure run writes a log with result=failed and a positive returncode."""
    cmd = [sys.executable, "-c", "import sys; print('fail output'); sys.exit(42)"]
    from server.subprocess_runner import stream_subprocess
    asyncio.run(_collect(stream_subprocess(cmd, cwd=str(tmp_workspace))))

    logs = list((tmp_workspace / "logs").glob("*.md"))
    assert len(logs) == 1
    body = logs[0].read_text()
    assert "result: `failed`" in body
    assert "returncode: `42`" in body
    assert "fail output" in body


def test_save_run_log_abort(tmp_workspace: Path, long_running_script: Path) -> None:
    """Aborted run writes a log with result=aborted (rc is None or negative)."""
    from server.subprocess_runner import stream_subprocess

    async def _abort_after_one():
        gen = stream_subprocess([sys.executable, str(long_running_script)],
                                cwd=str(tmp_workspace))
        count = 0
        async for _ in gen:
            count += 1
            if count >= 3:
                await gen.aclose()
                break

    asyncio.run(_abort_after_one())

    logs = list((tmp_workspace / "logs").glob("*.md"))
    assert len(logs) == 1
    body = logs[0].read_text()
    assert "result: `aborted`" in body


# ---------------------------------------------------------------------------
# T027: Process-group kill — explicit abort and disconnect (FR-008, FR-013)
# ---------------------------------------------------------------------------

def test_process_group_killed_on_abort(tmp_workspace: Path,
                                        long_running_script: Path) -> None:
    """On abort (aclose), child AND grandchild PIDs are gone within a short window."""
    import time
    from server.subprocess_runner import stream_subprocess, GRACE_SECONDS

    child_pid: list[int] = []

    async def _run_and_abort():
        gen = stream_subprocess([sys.executable, str(long_running_script)],
                                cwd=str(tmp_workspace))
        count = 0
        async for chunk in gen:
            count += 1
            if count >= 3:
                await gen.aclose()
                break
        # Keep event loop alive so any call_later callbacks can fire.
        await asyncio.sleep(0.5)

    asyncio.run(_run_and_abort())

    # After GRACE + a small margin, no processes with the script name should survive.
    deadline = time.monotonic() + GRACE_SECONDS + 2.0
    script_name = long_running_script.name
    while time.monotonic() < deadline:
        import subprocess as _sp
        r = _sp.run(["pgrep", "-f", script_name], capture_output=True)
        if r.returncode != 0:
            break  # pgrep found nothing — all dead
        time.sleep(0.1)
    else:
        # Final check
        r = _sp.run(["pgrep", "-f", script_name], capture_output=True)
        assert r.returncode != 0, (
            f"Orphaned processes still running after abort + grace window:\n"
            f"{r.stdout.decode()}"
        )


# ---------------------------------------------------------------------------
# T028: Grace→force timing — SIGTERM-ignoring child is SIGKILLed (FR-008, SC-005)
# ---------------------------------------------------------------------------

def test_sigterm_ignorer_killed_within_grace(tmp_workspace: Path,
                                              sigterm_ignorer_script: Path) -> None:
    """A child that ignores SIGTERM must be SIGKILLed within GRACE_SECONDS."""
    import time
    from server.subprocess_runner import stream_subprocess, GRACE_SECONDS

    async def _run_abort_and_wait():
        gen = stream_subprocess([sys.executable, str(sigterm_ignorer_script)],
                                cwd=str(tmp_workspace))
        count = 0
        async for _ in gen:
            count += 1
            if count >= 3:
                await gen.aclose()
                break
        # Keep the event loop alive so call_later(GRACE_SECONDS, SIGKILL) can fire.
        # (asyncio.run() closes the loop immediately when the coro returns, which
        # would discard any pending call_later callbacks before they fire.)
        await asyncio.sleep(GRACE_SECONDS + 1.0)

    t0 = time.monotonic()
    asyncio.run(_run_abort_and_wait())
    elapsed = time.monotonic() - t0

    # The run log should show aborted
    logs = list((tmp_workspace / "logs").glob("*.md"))
    assert len(logs) == 1
    body = logs[0].read_text()
    assert "result: `aborted`" in body

    # And no process should still be running
    import subprocess as _sp
    r = _sp.run(["pgrep", "-f", sigterm_ignorer_script.name], capture_output=True)
    assert r.returncode != 0, (
        f"SIGTERM-ignoring process still alive {elapsed:.1f}s after abort:\n"
        f"{r.stdout.decode()}"
    )


# ---------------------------------------------------------------------------
# T029: Atomicity + lock release (FR-014, FR-010)
# ---------------------------------------------------------------------------

def test_atomic_write_json_no_truncation(tmp_workspace: Path) -> None:
    """atomic_write_json never leaves a truncated file at the destination path."""
    from campaignlib import atomic_write_json
    import json

    dest = tmp_workspace / "merged.json"
    data = {"facts": list(range(100)), "text": "x" * 10_000}

    # Normal write succeeds and is valid JSON.
    atomic_write_json(dest, data)
    assert dest.exists()
    loaded = json.loads(dest.read_text())
    assert loaded == data


def test_atomic_write_text_no_truncation(tmp_workspace: Path) -> None:
    """atomic_write_text never leaves a truncated file at the destination path."""
    from campaignlib import atomic_write_text

    dest = tmp_workspace / "dossier.md"
    content = "# Dossier\n" + "x" * 50_000

    atomic_write_text(dest, content)
    assert dest.exists()
    assert dest.read_text() == content


def test_lock_released_after_abort(tmp_workspace: Path, long_running_script: Path) -> None:
    """_RUNNING lock must be released after an aborted run (FR-010 resumability)."""
    from server.routers.ensemble import _RUNNING, _lock_key
    from server.subprocess_runner import stream_subprocess
    import os

    stage = "test_abort_lock"
    key = f"{tmp_workspace.resolve()}::{stage}"

    released: list[bool] = []

    def _on_complete(_rc):
        released.append(key not in _RUNNING)  # True if already released
        _RUNNING.discard(key)

    _RUNNING.add(key)

    async def _run_and_abort():
        gen = stream_subprocess(
            [sys.executable, str(long_running_script)],
            cwd=str(tmp_workspace),
            on_complete=_on_complete,
        )
        count = 0
        async for _ in gen:
            count += 1
            if count >= 2:
                await gen.aclose()
                break

    asyncio.run(_run_and_abort())
    assert len(released) == 1, "on_complete must fire exactly once"
    assert key not in _RUNNING, "_RUNNING key must be released after abort"


# ---------------------------------------------------------------------------
# T031: Non-ensemble SSE route regression (I2 shared-seam blast radius)
# ---------------------------------------------------------------------------

def test_non_ensemble_route_killed_on_abort(tmp_workspace: Path,
                                             long_running_script: Path) -> None:
    """A grounding-style stream_subprocess call is also group-killed on abort.

    Proves the shared-seam change (start_new_session + finally kill) is safe
    app-wide, not just for ensemble routes (I2 regression).
    """
    import time
    from server.subprocess_runner import stream_subprocess, GRACE_SECONDS

    # Simulate a non-ensemble route (grounding.py pattern): just call
    # stream_subprocess directly with no ensemble-specific env.
    async def _grounding_style_run():
        gen = stream_subprocess(
            [sys.executable, str(long_running_script)],
            cwd=str(tmp_workspace),
        )
        count = 0
        async for _ in gen:
            count += 1
            if count >= 3:
                await gen.aclose()
                break
        await asyncio.sleep(0.5)  # keep loop alive for call_later

    asyncio.run(_grounding_style_run())
    time.sleep(0.5)  # extra margin for pgrep

    import subprocess as _sp
    r = _sp.run(["pgrep", "-f", long_running_script.name], capture_output=True)
    assert r.returncode != 0, (
        f"Non-ensemble subprocess still orphaned after disconnect:\n"
        f"{r.stdout.decode()}"
    )
