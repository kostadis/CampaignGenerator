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


def test_extract_honors_custom_filename_template(fake_stream_api, tmp_path):
    result = campaignlib.run_extract_pipeline(
        client=None, text="x",
        extract_system="", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
        filename_template="dossier_extract_{i:03d}.md",
    )
    assert result[0].name == "dossier_extract_001.md"


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


# ── input_normalizer / system_suffix kwargs ──────────────────────────────────

def test_extract_applies_input_normalizer_before_chunking(fake_stream_api, tmp_path):
    text = "Session 1: Cap. Tolubb and Captain Tolubb spoke."

    campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="SYS", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
        input_normalizer=lambda s: s.replace("Cap. Tolubb", "Tolubb").replace("Captain Tolubb", "Tolubb"),
    )
    user_prompt = fake_stream_api.calls[0]["user"]
    assert "Cap. Tolubb" not in user_prompt
    assert "Captain Tolubb" not in user_prompt
    assert user_prompt.count("Tolubb") == 2


def test_extract_appends_system_suffix(fake_stream_api, tmp_path):
    campaignlib.run_extract_pipeline(
        client=None, text="hello",
        extract_system="BASE SYSTEM", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
        system_suffix="Known NPCs: Tolubb",
    )
    system = fake_stream_api.calls[0]["system"]
    assert system == "BASE SYSTEM\n\nKnown NPCs: Tolubb"


def test_extract_no_normalizer_no_suffix_is_default_shape(fake_stream_api, tmp_path):
    campaignlib.run_extract_pipeline(
        client=None, text="hello",
        extract_system="BASE", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert fake_stream_api.calls[0]["system"] == "BASE"
    assert fake_stream_api.calls[0]["user"] == "hello"


def test_synthesize_applies_input_normalizer_per_file(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "Cap. Tolubb did a thing.")
    f2 = _write(tmp_path / "b.md", "Later, Captain Tolubb did another.")

    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("NOTES", [f1, f2])],
        synthesize_system="SYS", model="m",
        input_normalizer=lambda s: s.replace("Cap. Tolubb", "Tolubb").replace("Captain Tolubb", "Tolubb"),
    )
    prompt = fake_stream_api.calls[0]["user"]
    assert "Cap. Tolubb" not in prompt
    assert "Captain Tolubb" not in prompt
    assert prompt.count("Tolubb") == 2


def test_synthesize_appends_system_suffix(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "body")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="BASE", model="m",
        system_suffix="Known NPCs: Tolubb",
    )
    assert fake_stream_api.calls[0]["system"] == "BASE\n\nKnown NPCs: Tolubb"


# ── Alias machinery (lifted into campaignlib) ────────────────────────────────

def test_parse_dossier_with_full_frontmatter(tmp_path):
    p = tmp_path / "tolubb.md"
    p.write_text(
        "---\nname: Tolubb\naliases:\n  - Cap. Tolubb\n  - Captain Tolubb\n"
        "source_extracts: [1, 3, 5]\n---\n\n# Body\n",
        encoding="utf-8",
    )
    name, aliases, source_extracts, body = campaignlib.parse_dossier(p)
    assert name == "Tolubb"
    assert aliases == ["Cap. Tolubb", "Captain Tolubb"]
    assert source_extracts == [1, 3, 5]
    assert body.startswith("# Body")


def test_parse_dossier_no_frontmatter_falls_back_to_stem(tmp_path):
    p = tmp_path / "legacy.md"
    p.write_text("just body, no frontmatter\n", encoding="utf-8")
    name, aliases, source_extracts, _ = campaignlib.parse_dossier(p)
    assert name == "legacy"
    assert aliases == []
    assert source_extracts == []


def test_load_alias_map_skips_sidecars(tmp_path):
    (tmp_path / "tolubb.md").write_text(
        "---\nname: Tolubb\naliases:\n  - Cap. Tolubb\n---\n\nbody\n",
        encoding="utf-8",
    )
    # Sidecar file — must NOT appear in the alias map.
    (tmp_path / "tolubb.new_notes.003.md").write_text("sidecar contents", encoding="utf-8")
    m = campaignlib.load_alias_map(tmp_path)
    assert "Tolubb" in m
    assert m["Tolubb"] == ["Cap. Tolubb"]
    assert len(m) == 1


def test_load_alias_map_empty_or_missing_dir(tmp_path):
    assert campaignlib.load_alias_map(None) == {}
    assert campaignlib.load_alias_map(tmp_path / "does-not-exist") == {}
    # Empty but existing dir → empty map.
    (tmp_path / "empty").mkdir()
    assert campaignlib.load_alias_map(tmp_path / "empty") == {}


def test_build_alias_normalizer_rewrites_longest_first():
    normalize, _ = campaignlib.build_alias_normalizer({
        "Tolubb": ["Cap. Tolubb", "Captain Tolubb"],
    })
    assert normalize("Captain Tolubb walked in, and Cap. Tolubb sat down.") \
        == "Tolubb walked in, and Tolubb sat down."


def test_build_alias_normalizer_case_insensitive():
    normalize, _ = campaignlib.build_alias_normalizer({"Xalvosh": ["xalvos"]})
    assert normalize("Then XALVOS appeared.") == "Then Xalvosh appeared."


def test_build_alias_normalizer_whole_word_only():
    normalize, _ = campaignlib.build_alias_normalizer({"Tolubb": ["Cap"]})
    # "Cap" should not match inside "Capture" or "Captain"
    assert normalize("Capture the Captain.") == "Capture the Captain."
    assert normalize("The Cap arrived.") == "The Tolubb arrived."


def test_build_alias_normalizer_empty_map_is_identity():
    normalize, entries = campaignlib.build_alias_normalizer({})
    assert normalize("anything at all") == "anything at all"
    assert entries == []


def test_format_npc_roster_empty_is_empty_string():
    assert campaignlib.format_npc_roster({}) == ""


def test_format_npc_roster_renders_sorted_with_aliases():
    roster = campaignlib.format_npc_roster({
        "Tolubb": ["Cap. Tolubb", "Captain Tolubb"],
        "Xalvosh": [],
    })
    lines = roster.splitlines()
    assert lines[0].startswith("Known NPCs")
    # Sorted alphabetically.
    assert lines[1] == "- Tolubb (also: Cap. Tolubb, Captain Tolubb)"
    assert lines[2] == "- Xalvosh"


def test_normalize_npc_key_strips_punctuation_and_case():
    assert campaignlib.normalize_npc_key("Harbin (Townmaster)") == "harbin townmaster"
    assert campaignlib.normalize_npc_key("Elara 'Seasong' Meliamne") == "elara seasong meliamne"
