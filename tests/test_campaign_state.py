"""Tests for campaign_state.py's CLI — focused on the --extract-only checkpoint and
the tracked-items prompt injection (which is script-specific and must survive the
migration onto the shared pipeline)."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import campaignlib  # noqa: E402
import campaign_state  # noqa: E402


# ── Subprocess tests ─────────────────────────────────────────────────────────

def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "campaign_state.py"), *args],
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


def test_synthesize_only_without_extract_dir_reports_missing_staging_sources(tmp_path):
    # Run from REPO_ROOT (no docs/world_state_draft.md there) — auto-staging
    # should fail with a clear pointer instead of a bare "requires --extract-dir".
    result = _run(
        "--synthesize-only",
        "--output", str(tmp_path / "campaign_state_draft.md"),
    )
    assert result.returncode == 1
    assert "world_state_draft.md" in result.stderr
    assert "threads.md" in result.stderr


# ── In-process behavior ──────────────────────────────────────────────────────

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
    monkeypatch.setattr(campaign_state, "make_client", lambda: None)
    return fake


def test_extract_only_skips_synthesis_pass(monkeypatch, fake_stream_api, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "campaign_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "campaign_state.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--extract-only",
    ])
    campaign_state.main()

    assert len(fake_stream_api.calls) == 1
    assert not output.exists()
    assert any(extract_dir.glob("extract_*.md"))


def test_default_run_calls_both_passes(monkeypatch, fake_stream_api, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "campaign_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "campaign_state.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    campaign_state.main()

    assert len(fake_stream_api.calls) == 2
    assert output.exists()


def test_tracked_items_injected_into_both_system_prompts(monkeypatch, fake_stream_api, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "campaign_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "campaign_state.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
        "--track", "Cryovain encounter", "Gnomengarde resolution",
    ])
    campaign_state.main()

    extract_system = fake_stream_api.calls[0]["system"]
    synthesize_system = fake_stream_api.calls[1]["system"]
    assert "Cryovain encounter" in extract_system
    assert "Gnomengarde resolution" in extract_system
    assert "Cryovain encounter" in synthesize_system
    assert "Gnomengarde resolution" in synthesize_system


def test_synthesize_only_auto_stages_world_state_and_threads(monkeypatch, fake_stream_api, tmp_path):
    docs_dir = tmp_path / "docs"
    (docs_dir / "ensemble").mkdir(parents=True)
    (docs_dir / "world_state_draft.md").write_text("world state content", encoding="utf-8")
    (docs_dir / "ensemble" / "threads.md").write_text("threads content", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", [
        "campaign_state.py",
        "--output", "docs/campaign_state_draft.md",
        "--synthesize-only",
    ])
    campaign_state.main()

    staged = docs_dir / "state_staging" / "campaign_state"
    assert staged.joinpath("extract_001_world_state.md").read_text(encoding="utf-8") == "world state content"
    assert staged.joinpath("extract_002_threads.md").read_text(encoding="utf-8") == "threads content"
    assert len(fake_stream_api.calls) == 1  # synthesize pass only, no extract
    assert (docs_dir / "campaign_state_draft.md").exists()


def test_no_tracked_items_omits_tracked_section(monkeypatch, fake_stream_api, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "campaign_state.md"
    extract_dir = tmp_path / "extractions"

    monkeypatch.setattr(sys, "argv", [
        "campaign_state.py", str(input_file),
        "--output", str(output),
        "--extract-dir", str(extract_dir),
    ])
    campaign_state.main()

    extract_system = fake_stream_api.calls[0]["system"]
    synthesize_system = fake_stream_api.calls[1]["system"]
    assert "## Tracked Items" not in extract_system
    assert "Tracked Items Status" not in synthesize_system
