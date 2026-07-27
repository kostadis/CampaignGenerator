"""Tests for distill.py's CLI — particularly the --extract-only checkpoint flag."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
from pipelines.grounding import distill  # noqa: E402

# distill.py has moved into pipelines/grounding/ and now runs as the `distill`
# console script (pyproject.toml's [project.scripts]). Resolve it next to the
# current interpreter (same venv bin/) rather than relying on $PATH, so this
# test doesn't depend on the venv being "activated" in the process running
# pytest — same rationale as server.subprocess_runner.console_script().
DISTILL_BIN = str(Path(sys.executable).parent / "distill")


# ── Subprocess-based tests (fast: no API calls required) ─────────────────────

def _run_distill(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [DISTILL_BIN, *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_help_advertises_extract_only():
    result = _run_distill("--help")
    assert result.returncode == 0
    assert "--extract-only" in result.stdout


def test_extract_only_and_synthesize_only_are_mutually_exclusive(tmp_path):
    result = _run_distill(
        "--extract-only", "--synthesize-only",
        "--extract-dir", str(tmp_path),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


# ── In-process behavior tests (monkeypatch stream_api) ───────────────────────

class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model})
        return f"[stub-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
    monkeypatch.setattr(distill, "client_from_args", lambda *a, **kw: None)
    return fake


def test_extract_only_skips_synthesis_pass(monkeypatch, fake_stream_api, tmp_path, capsys):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "world_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "distill.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    distill.main()

    assert len(fake_stream_api.calls) == 1  # extract pass ran; synthesis did not
    assert not output.exists()  # no final document written
    assert any(extract_dir.glob("extract_*.md"))  # extract files persisted

    stdout = capsys.readouterr().out
    assert "Extract-only mode" in stdout
    assert "--synthesize-only" in stdout  # tells user how to continue


def test_default_run_calls_both_passes(monkeypatch, fake_stream_api, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "world_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "distill.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    distill.main()

    assert len(fake_stream_api.calls) == 2  # extract + synthesize
    assert output.exists()


# ── --batch: routes through the batch entry points ───────────────────────────
# Mirrors the FakeStreamAPI two-binding pattern: distill.py never imports
# run_batch/run_single_batch itself (both extract and synthesize route
# through campaignlib.pipelines), so patching that one module binding is
# enough to intercept both stages.

class FakeRunBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        return {
            r["custom_id"]: {"status": "succeeded", "text": f"[batch-{r['custom_id']}]",
                             "stop_reason": "end_turn", "error": None, "usage": None}
            for r in requests
        }


class FakeRunSingleBatch:
    def __init__(self):
        self.calls = []

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return "[batch-synth-result]"


@pytest.fixture
def fake_batch_entry_points(monkeypatch):
    run_batch = FakeRunBatch()
    run_single_batch = FakeRunSingleBatch()
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", run_batch)
    monkeypatch.setattr(campaignlib.pipelines, "run_single_batch", run_single_batch)
    monkeypatch.setattr(distill, "client_from_args", lambda *a, **kw: None)
    return run_batch, run_single_batch


def test_batch_flag_routes_extract_and_synthesize_through_batch_entry_points(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    run_batch, run_single_batch = fake_batch_entry_points
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "world_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "distill.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--batch",
    ])
    distill.main()

    assert len(run_batch.calls) == 1  # one batch call for the extract fan-out
    assert len(run_single_batch.calls) == 1  # one batch call for synthesis
    assert output.exists()
    assert "[batch-synth-result]" in output.read_text(encoding="utf-8")


def test_default_no_batch_path_still_uses_stream_api_unaffected_by_batch_wiring(
    monkeypatch, fake_stream_api, tmp_path
):
    """FR-011 regression guard: adding --batch plumbing must not change the
    default (no --batch) path — same assertion shape as
    test_default_run_calls_both_passes, re-asserted after the batch wiring
    landed."""
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "world_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "distill.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    distill.main()

    assert len(fake_stream_api.calls) == 2
    assert output.exists()
