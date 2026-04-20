"""Tests for party.py's CLI — focused on the --extract-only checkpoint and the
per-group labeling that the shared pipeline needs to support (character sheet
vs session extract vs backstory vs arc score vs context)."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
import party  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "party.py"), *args],
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
        "--character", str(tmp_path / "soma.md"),
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
    monkeypatch.setattr(party, "make_client", lambda: None)
    return fake


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_extract_only_skips_synthesis(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "a session")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    party.main()

    assert len(fake_stream_api.calls) == 1
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))


def test_default_run_uses_per_group_source_labels(monkeypatch, fake_stream_api, tmp_path):
    summaries = _write(tmp_path / "summaries.md", "session content")
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    backstory = _write(tmp_path / "soma_backstory.md", "backstory prose")
    arc_score = _write(tmp_path / "soma_arc.md", "arc score mechanic")
    context = _write(tmp_path / "campaign_state.md", "grounding context")
    output = tmp_path / "party.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--summaries", str(summaries),
        "--backstory", str(backstory),
        "--arc-scores", str(arc_score),
        "--context", str(context),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    party.main()

    synthesize_prompt = fake_stream_api.calls[1]["user"]
    # Each source group carries its own source-comment label.
    assert "<!-- Character sheet: soma.md -->" in synthesize_prompt
    assert "<!-- Session extract: extract_001.md -->" in synthesize_prompt
    assert "<!-- Backstory: soma_backstory.md -->" in synthesize_prompt
    assert "<!-- Arc score mechanic: soma_arc.md -->" in synthesize_prompt
    assert "<!-- Context: campaign_state.md -->" in synthesize_prompt
    # Group headings present.
    assert "# CHARACTER SHEETS" in synthesize_prompt
    assert "# SESSION EXTRACTIONS" in synthesize_prompt
    assert "# BACKSTORY DOCUMENTS" in synthesize_prompt
    assert "# ARC SCORE MECHANICS" in synthesize_prompt
    assert "# ADDITIONAL CONTEXT" in synthesize_prompt
    assert output.exists()


def test_characters_only_skips_extract_pass(monkeypatch, fake_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--character", str(sheet),
        "--output", str(output),
    ])
    party.main()

    # No summaries → no extract pass; one API call for synthesis only.
    assert len(fake_stream_api.calls) == 1
    synthesize_prompt = fake_stream_api.calls[0]["user"]
    assert "# CHARACTER SHEETS" in synthesize_prompt
    assert "# SESSION EXTRACTIONS" not in synthesize_prompt
