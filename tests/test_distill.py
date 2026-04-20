"""Tests for distill.py's CLI — particularly the --extract-only checkpoint flag."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
import distill  # noqa: E402


# ── Subprocess-based tests (fast: no API calls required) ─────────────────────

def _run_distill(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "distill.py"), *args],
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
    monkeypatch.setattr(campaignlib, "stream_api", fake)
    monkeypatch.setattr(distill, "make_client", lambda: None)
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
