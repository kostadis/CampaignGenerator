"""Tests for vtt_summary.py's CLI — particularly the --extract-only checkpoint flag."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
import vtt_summary  # noqa: E402


# ── Subprocess-based tests (fast: no API calls required) ─────────────────────

def _run_vtt(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "vtt_summary.py"), *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_help_advertises_extract_only():
    result = _run_vtt("--help")
    assert result.returncode == 0
    assert "--extract-only" in result.stdout
    assert "--synthesize-only" in result.stdout


def test_extract_only_and_synthesize_only_are_mutually_exclusive(tmp_path):
    result = _run_vtt(
        "--extract-only", "--synthesize-only",
        "--extract-dir", str(tmp_path),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


# ── In-process behavior tests (monkeypatch stream_api) ───────────────────────

SAMPLE_VTT = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
GM: You enter the cave.

2
00:00:05.000 --> 00:00:10.000
Alice: I cast light.
"""


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
    monkeypatch.setattr(vtt_summary, "make_client", lambda: None)
    return fake


def test_extract_only_runs_both_extract_passes(
    monkeypatch, fake_stream_api, tmp_path, capsys
):
    """`--extract-only` now runs the roleplay extract pass unconditionally
    (no `--roleplay-output` gate). Verifies vtt_roleplay_extractions/ is
    populated for downstream quote_ledger / enhance_recap consumers."""
    vtt_file = tmp_path / "session.vtt"
    vtt_file.write_text(SAMPLE_VTT, encoding="utf-8")
    output = tmp_path / "summary.md"
    extract_dir = tmp_path / "extractions"
    roleplay_extract_dir = tmp_path / "roleplay_extractions"

    monkeypatch.setattr(sys, "argv", [
        "vtt_summary.py", str(vtt_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--roleplay-extract-dir", str(roleplay_extract_dir),
        "--extract-only",
        "--no-log",
    ])
    vtt_summary.main()

    # Summary extract + roleplay extract; no synthesize calls.
    assert len(fake_stream_api.calls) == 2
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))
    assert any(roleplay_extract_dir.glob("extract_*.md"))


def test_default_run_calls_three_passes(monkeypatch, fake_stream_api, tmp_path):
    """Default flow now runs three passes: summary extract, summary synth,
    roleplay extract (unconditional). The old roleplay synth pass is gone
    along with --roleplay-output."""
    vtt_file = tmp_path / "session.vtt"
    vtt_file.write_text(SAMPLE_VTT, encoding="utf-8")
    output = tmp_path / "summary.md"
    extract_dir = tmp_path / "extractions"
    roleplay_extract_dir = tmp_path / "roleplay_extractions"

    monkeypatch.setattr(sys, "argv", [
        "vtt_summary.py", str(vtt_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--roleplay-extract-dir", str(roleplay_extract_dir),
        "--no-log",
    ])
    vtt_summary.main()

    # summary extract, summary synthesize, roleplay extract.
    assert len(fake_stream_api.calls) == 3
    assert output.exists()
    assert any(extract_dir.glob("extract_*.md"))
    assert any(roleplay_extract_dir.glob("extract_*.md"))
