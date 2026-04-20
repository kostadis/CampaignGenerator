"""Tests for planning.py's CLI — focused on the --extract-only checkpoint in both
the standard synthesize flow and --build-dossiers mode. The script-specific
alias resolution in run_synthesize is covered indirectly by tests/test_prep.py
and is intentionally out of scope for this migration."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
import planning  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "planning.py"), *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def test_help_advertises_extract_only():
    result = _run("--help")
    assert result.returncode == 0
    assert "--extract-only" in result.stdout


def test_extract_only_and_synthesize_only_are_mutually_exclusive(tmp_path):
    result = _run(
        "--extract-only", "--synthesize-only",
        "--extract-dir", str(tmp_path),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


def test_extract_only_requires_summaries(tmp_path):
    result = _run(
        "--extract-only",
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "--extract-only requires --summaries" in result.stderr


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
    # planning.py imports stream_api directly; also stub that binding.
    monkeypatch.setattr(planning, "stream_api", fake)
    monkeypatch.setattr(planning, "make_client", lambda: None)
    return fake


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_only_standard_mode_skips_synthesis(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "some session content")
    output = tmp_path / "planning.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    planning.main()

    # One extract call, no synthesis call.
    assert len(fake_stream_api.calls) == 1
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))


def test_extract_only_build_dossiers_mode_stops_after_phase_1(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "session content with ## Grundar mentions")
    dossier_dir = tmp_path / "npcs"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "planning.py",
        "--build-dossiers",
        "--summaries", str(summaries),
        "--dossier-dir", str(dossier_dir),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    planning.main()

    # Phase 1 runs → one extract call. Phase 3 (per-NPC LLM synth) does NOT run.
    assert len(fake_stream_api.calls) == 1
    assert any(extract_dir.glob("dossier_extract_*.md"))
    # No dossier files created — Phase 3 was skipped.
    assert not any(dossier_dir.glob("*.md")) if dossier_dir.exists() else True
