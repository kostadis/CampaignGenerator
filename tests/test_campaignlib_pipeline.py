"""Tests for campaignlib.run_extract_pipeline and run_synthesize_pipeline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeStreamAPI:
    """Callable stub that records calls and returns scripted (or auto) responses."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses) if responses else None

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model})
        if self._responses:
            return self._responses.pop(0)
        return f"[stub-response-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib, "stream_api", fake)
    return fake


# ── run_extract_pipeline ─────────────────────────────────────────────────────

def test_extract_chunks_and_writes_files(fake_stream_api, tmp_path):
    text = "\n\n".join("paragraph " + ("x " * 200) for _ in range(4))
    extract_dir = tmp_path / "extracts"

    result = campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="SYS", model="test-model",
        extract_dir=extract_dir, chunk_size=500,
    )

    assert len(result) >= 2
    assert all(p.exists() for p in result)
    assert len(fake_stream_api.calls) == len(result)


def test_extract_default_filename_pattern(fake_stream_api, tmp_path):
    result = campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert result[0].name == "extract_001.md"


def test_extract_writes_stream_response_to_file(fake_stream_api, tmp_path):
    result = campaignlib.run_extract_pipeline(
        client=None, text="short input",
        extract_system="", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert result[0].read_text(encoding="utf-8") == "[stub-response-1]"


def test_extract_passes_system_prompt_through(fake_stream_api, tmp_path):
    campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="MY EXTRACT SYSTEM", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert fake_stream_api.calls[0]["system"] == "MY EXTRACT SYSTEM"
    assert fake_stream_api.calls[0]["model"] == "m"


def test_extract_skips_existing_files(fake_stream_api, tmp_path):
    extract_dir = tmp_path / "e"
    extract_dir.mkdir()
    (extract_dir / "extract_001.md").write_text("precomputed", encoding="utf-8")

    result = campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="", model="m",
        extract_dir=extract_dir, chunk_size=60000,
    )

    assert len(fake_stream_api.calls) == 0
    assert (extract_dir / "extract_001.md").read_text() == "precomputed"
    assert result == [extract_dir / "extract_001.md"]


def test_extract_resumes_after_partial_completion(fake_stream_api, tmp_path):
    text = "\n\n".join("para " + ("x " * 300) for _ in range(3))
    extract_dir = tmp_path / "e"
    extract_dir.mkdir()
    (extract_dir / "extract_001.md").write_text("precomputed", encoding="utf-8")

    result = campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="", model="m",
        extract_dir=extract_dir, chunk_size=500,
    )

    assert len(result) >= 2
    assert (extract_dir / "extract_001.md").read_text() == "precomputed"
    # stream_api was called only for the non-cached chunks
    assert len(fake_stream_api.calls) == len(result) - 1


def test_extract_uses_split_chapters(fake_stream_api, tmp_path):
    text = "# Chapter 1\nContent A\n\n# Chapter 2\nContent B\n"
    result = campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
        split_chapters="# Chapter",
    )
    assert len(result) == 2
    assert len(fake_stream_api.calls) == 2


def test_extract_creates_output_dir(fake_stream_api, tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    assert not nested.exists()
    campaignlib.run_extract_pipeline(
        client=None, text="x",
        extract_system="", model="m",
        extract_dir=nested, chunk_size=60000,
    )
    assert nested.exists()


# ── run_synthesize_pipeline ──────────────────────────────────────────────────

def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_synthesize_single_group_no_heading_starts_with_source_comment(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "alpha content")
    f2 = _write(tmp_path / "b.md", "beta content")

    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1, f2])],
        synthesize_system="SYS", model="m",
    )

    prompt = fake_stream_api.calls[0]["user"]
    assert prompt.startswith("<!-- Source: a.md -->")
    assert "<!-- Source: b.md -->" in prompt
    assert "alpha content" in prompt
    assert "beta content" in prompt


def test_synthesize_files_joined_by_file_separator(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "alpha")
    f2 = _write(tmp_path / "b.md", "beta")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1, f2])],
        synthesize_system="", model="m",
    )
    assert "\n\n---\n\n" in fake_stream_api.calls[0]["user"]


def test_synthesize_multiple_groups_render_headings_and_separator(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "char.md", "Soma stats")
    f2 = _write(tmp_path / "ext.md", "session note")

    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("CHARACTER SHEETS", [f1]), ("SESSION EXTRACTIONS", [f2])],
        synthesize_system="", model="m",
    )

    prompt = fake_stream_api.calls[0]["user"]
    assert "# CHARACTER SHEETS" in prompt
    assert "# SESSION EXTRACTIONS" in prompt
    assert "\n\n===\n\n" in prompt


def test_synthesize_skips_empty_groups(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "alpha")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("HEADING ONE", [f1]), ("HEADING TWO", [])],
        synthesize_system="", model="m",
    )
    prompt = fake_stream_api.calls[0]["user"]
    assert "HEADING ONE" in prompt
    assert "HEADING TWO" not in prompt


def test_synthesize_all_empty_groups_exits(fake_stream_api):
    with pytest.raises(SystemExit):
        campaignlib.run_synthesize_pipeline(
            client=None,
            source_groups=[("A", []), ("B", [])],
            synthesize_system="", model="m",
        )
    assert len(fake_stream_api.calls) == 0


def test_synthesize_custom_source_label(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "soma.md", "Tortle Druid")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
        source_label="Character sheet",
    )
    assert "<!-- Character sheet: soma.md -->" in fake_stream_api.calls[0]["user"]


def test_synthesize_per_group_label_override(fake_stream_api, tmp_path):
    sheet = _write(tmp_path / "soma.md", "Tortle Druid")
    extract = _write(tmp_path / "extract_001.md", "session note")
    backstory = _write(tmp_path / "soma_backstory.md", "backstory prose")

    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[
            ("CHARACTERS", [sheet], "Character sheet"),
            ("EXTRACTIONS", [extract], "Session extract"),
            ("BACKSTORIES", [backstory]),  # no per-group label — falls back to default
        ],
        synthesize_system="", model="m",
        source_label="Source",
    )
    prompt = fake_stream_api.calls[0]["user"]
    assert "<!-- Character sheet: soma.md -->" in prompt
    assert "<!-- Session extract: extract_001.md -->" in prompt
    assert "<!-- Source: soma_backstory.md -->" in prompt


def test_synthesize_returns_stream_response(monkeypatch, tmp_path):
    fake = FakeStreamAPI(responses=["scripted result"])
    monkeypatch.setattr(campaignlib, "stream_api", fake)
    f1 = _write(tmp_path / "a.md", "x")

    result = campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
    )
    assert result == "scripted result"


def test_synthesize_passes_system_prompt_and_model(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "x")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="SYN SYS", model="some-model",
    )
    assert fake_stream_api.calls[0]["system"] == "SYN SYS"
    assert fake_stream_api.calls[0]["model"] == "some-model"


def test_synthesize_strips_trailing_whitespace_from_file_contents(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "   alpha with padding   \n\n")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
    )
    prompt = fake_stream_api.calls[0]["user"]
    assert "alpha with padding" in prompt
    assert not prompt.endswith("   \n\n")
