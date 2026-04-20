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
    # party.py imports stream_api directly (for the --party-config path);
    # also stub that binding so the direct call is captured.
    monkeypatch.setattr(party, "stream_api", fake)
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


# ── Party config ─────────────────────────────────────────────────────────────


def _write_party_config(tmp_path, body: str):
    cfg = tmp_path / "party.yaml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_load_party_config_parses_sheet_backstory_arc(tmp_path):
    _write(tmp_path / "brew.md", "Brewbarry sheet")
    _write(tmp_path / "brew_back.md", "Brewbarry backstory")
    _write(tmp_path / "brew_score.md", "Brewbarry score")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
    backstory: brew_back.md
    arc_score: brew_score.md
""")
    config = party.load_party_config(cfg)
    assert len(config.characters) == 1
    pc = config.characters[0]
    assert pc.name == "Brewbarry"
    assert pc.sheet.name == "brew.md"
    assert pc.backstory.name == "brew_back.md"
    assert pc.arc_score.name == "brew_score.md"
    assert pc.trackless is False


def test_load_party_config_trackless_vs_absent(tmp_path):
    _write(tmp_path / "vuk.md", "Vukradin sheet")
    _write(tmp_path / "omit.md", "Omit sheet")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
  - name: Omit
    sheet: omit.md
""")
    config = party.load_party_config(cfg)
    vuk, omit = config.characters
    assert vuk.arc_score is None and vuk.trackless is True
    assert omit.arc_score is None and omit.trackless is False


def test_load_party_config_missing_file_fails_loud(tmp_path):
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Ghost
    sheet: does_not_exist.md
""")
    with pytest.raises(SystemExit):
        party.load_party_config(cfg)


def test_load_party_config_empty_characters_fails(tmp_path):
    cfg = _write_party_config(tmp_path, "characters: []\n")
    with pytest.raises(SystemExit):
        party.load_party_config(cfg)


def test_party_config_is_mutex_with_flat_flags(tmp_path):
    _write(tmp_path / "any.md", "x")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Any
    sheet: any.md
""")
    result = _run(
        "--party-config", str(cfg),
        "--character", str(tmp_path / "any.md"),
        "--output", str(tmp_path / "out.md"),
    )
    assert result.returncode == 1
    assert "mutually exclusive" in result.stderr


def test_party_config_renders_per_character_block(monkeypatch, fake_stream_api, tmp_path):
    _write(tmp_path / "brew.md", "Brewbarry sheet content")
    _write(tmp_path / "brew_back.md", "Brewbarry backstory content")
    _write(tmp_path / "brew_score.md", "Brewbarry arc score content")
    _write(tmp_path / "vuk.md", "Vukradin sheet content")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Brewbarry
    sheet: brew.md
    backstory: brew_back.md
    arc_score: brew_score.md
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
""")
    output = tmp_path / "party.md"

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(output),
    ])
    party.main()

    assert len(fake_stream_api.calls) == 1
    prompt = fake_stream_api.calls[0]["user"]
    # PARTY group with per-character subsections
    assert "# PARTY" in prompt
    assert "## Brewbarry" in prompt
    assert "## Vukradin" in prompt
    # Brewbarry has all three file blocks
    assert "<!-- Character sheet: brew.md -->" in prompt
    assert "<!-- Backstory: brew_back.md -->" in prompt
    assert "<!-- Arc score mechanic: brew_score.md -->" in prompt
    # Vukradin has only the sheet + the trackless marker (no arc file)
    assert "<!-- Character sheet: vuk.md -->" in prompt
    assert "INTENTIONALLY TRACKLESS" in prompt
    # Flat group headers should NOT appear — party-config path uses # PARTY
    assert "# CHARACTER SHEETS" not in prompt
    assert "# ARC SCORE MECHANICS" not in prompt
    assert output.exists()


def test_party_config_trackless_character_gets_no_arc_file_block(monkeypatch, fake_stream_api, tmp_path):
    _write(tmp_path / "vuk.md", "Vukradin sheet")
    cfg = _write_party_config(tmp_path, """
characters:
  - name: Vukradin
    sheet: vuk.md
    arc_score: null
""")

    monkeypatch.setattr(sys, "argv", [
        "party.py",
        "--party-config", str(cfg),
        "--output", str(tmp_path / "party.md"),
    ])
    party.main()

    prompt = fake_stream_api.calls[0]["user"]
    # No "Arc score mechanic" source comment, but the trackless marker is there.
    assert "<!-- Arc score mechanic:" not in prompt
    assert "<!-- Arc score: INTENTIONALLY TRACKLESS -->" in prompt
