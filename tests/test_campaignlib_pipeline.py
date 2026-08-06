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

    def __call__(self, client, system, user, model, *args, max_tokens=8096, **kwargs):
        # max_tokens defaults to stream_api's own default (8096) so a caller that
        # omits it is recorded as the real behaviour would be.
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        if self._responses:
            return self._responses.pop(0)
        return f"[stub-response-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
    return fake


class FakeRunBatch:
    """Callable stub for campaignlib.pipelines.run_batch: records the
    requests it was called with and returns a results dict keyed by
    custom_id. Every item succeeds by default; `status_by_id` overrides
    specific custom_ids to simulate partial failure."""

    def __init__(self, status_by_id=None):
        self.calls = []
        self._status_by_id = status_by_id or {}

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        results = {}
        for r in requests:
            cid = r["custom_id"]
            status = self._status_by_id.get(cid, "succeeded")
            if status == "succeeded":
                results[cid] = {"status": "succeeded", "text": f"[batch-result-{cid}]",
                                "stop_reason": "end_turn", "error": None, "usage": None}
            else:
                results[cid] = {"status": status, "text": None,
                                "stop_reason": None, "error": "boom", "usage": None}
        return results


@pytest.fixture
def fake_run_batch(monkeypatch):
    fake = FakeRunBatch()
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", fake)
    return fake


class FakeRunSingleBatch:
    """Callable stub for campaignlib.pipelines.run_single_batch."""

    def __init__(self, response="[batch-synth-result]"):
        self.calls = []
        self._response = response

    def __call__(self, client, *, system, user, model, max_tokens=8192, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model,
                           "max_tokens": max_tokens})
        return self._response


@pytest.fixture
def fake_run_single_batch(monkeypatch):
    fake = FakeRunSingleBatch()
    monkeypatch.setattr(campaignlib.pipelines, "run_single_batch", fake)
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


# ── run_extract_pipeline(batch=True) ─────────────────────────────────────────

def test_extract_batch_excludes_precomputed_chunks_from_requests(fake_run_batch, tmp_path):
    extract_dir = tmp_path / "e"
    extract_dir.mkdir()
    (extract_dir / "extract_001.md").write_text("precomputed", encoding="utf-8")
    text = "\n\n".join("para " + ("x " * 300) for _ in range(3))

    failed = campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="SYS", model="m",
        extract_dir=extract_dir, chunk_size=500,
        batch=True,
    )

    assert failed == []
    assert len(fake_run_batch.calls) == 1
    ids = [r["custom_id"] for r in fake_run_batch.calls[0]["requests"]]
    assert "extract_001" not in ids  # already on disk — must not be requested
    assert len(ids) >= 1


def test_extract_batch_writes_results_to_same_paths_as_serial(fake_run_batch, tmp_path):
    extract_dir = tmp_path / "e"
    campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="SYS", model="m",
        extract_dir=extract_dir, chunk_size=60000,
        batch=True,
    )
    out_file = extract_dir / "extract_001.md"  # same path the serial loop uses
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == "[batch-result-extract_001]"


def test_extract_batch_uses_atomic_write(monkeypatch, tmp_path):
    recorded = []

    def fake_atomic_write(path, text):
        recorded.append(Path(path))
        Path(path).write_text(text, encoding="utf-8")

    monkeypatch.setattr(campaignlib.pipelines, "_atomic_write_text", fake_atomic_write)
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", FakeRunBatch())

    extract_dir = tmp_path / "e"
    campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="SYS", model="m",
        extract_dir=extract_dir, chunk_size=60000,
        batch=True,
    )

    assert recorded == [extract_dir / "extract_001.md"]
    assert not list(extract_dir.glob("*.tmp.*"))  # no leftover tmp files


def test_extract_batch_empty_missing_set_skips_submission(fake_run_batch, tmp_path):
    extract_dir = tmp_path / "e"
    extract_dir.mkdir()
    (extract_dir / "extract_001.md").write_text("precomputed", encoding="utf-8")

    failed = campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="SYS", model="m",
        extract_dir=extract_dir, chunk_size=60000,
        batch=True,
    )

    assert failed == []
    assert len(fake_run_batch.calls) == 0  # nothing missing — run_batch never called


def test_extract_batch_partial_failure_returns_failed_ids_and_keeps_successes(
    monkeypatch, tmp_path, capsys
):
    fake = FakeRunBatch(status_by_id={"extract_002": "errored"})
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", fake)

    text = "\n\n".join("para " + ("x " * 300) for _ in range(3))
    extract_dir = tmp_path / "e"

    failed = campaignlib.run_extract_pipeline(
        client=None, text=text,
        extract_system="SYS", model="m",
        extract_dir=extract_dir, chunk_size=500,
        batch=True,
    )

    assert failed == ["extract_002"]
    assert (extract_dir / "extract_001.md").exists()  # success stays on disk
    assert not (extract_dir / "extract_002.md").exists()  # failure never written
    err = capsys.readouterr().err
    assert "FAILED extract_002: errored boom" in err


def test_extract_batch_custom_id_matches_filename_stem(fake_run_batch, tmp_path):
    extract_dir = tmp_path / "e"
    campaignlib.run_extract_pipeline(
        client=None, text="x",
        extract_system="", model="m",
        extract_dir=extract_dir, chunk_size=60000,
        filename_template="dossier_extract_{i:03d}.md",
        batch=True,
    )
    assert fake_run_batch.calls[0]["requests"][0]["custom_id"] == "dossier_extract_001"


def test_extract_batch_false_is_byte_identical_to_pre_batch_behavior(fake_stream_api, tmp_path):
    """FR-011: with batch=False (the default), behavior is unchanged."""
    result = campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="SYS", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert result[0].name == "extract_001.md"
    assert len(fake_stream_api.calls) == 1


# ── resolve_extract_output ────────────────────────────────────────────────────

def test_resolve_extract_output_passthrough_when_not_batch(tmp_path):
    paths = [tmp_path / "a.md"]
    assert campaignlib.resolve_extract_output(paths, batch=False, extract_dir=tmp_path) is paths


def test_resolve_extract_output_globs_extract_dir_on_batch_success(tmp_path):
    (tmp_path / "extract_001.md").write_text("x", encoding="utf-8")
    (tmp_path / "extract_002.md").write_text("y", encoding="utf-8")
    result = campaignlib.resolve_extract_output([], batch=True, extract_dir=tmp_path)
    assert result == [tmp_path / "extract_001.md", tmp_path / "extract_002.md"]


def test_resolve_extract_output_exits_on_batch_failure(tmp_path, capsys):
    with pytest.raises(SystemExit):
        campaignlib.resolve_extract_output(["extract_002"], batch=True, extract_dir=tmp_path)
    err = capsys.readouterr().err
    assert "1 extraction chunk(s) failed" in err


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
    monkeypatch.setattr(campaignlib.pipelines, "stream_api", fake)
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


def test_synthesize_forwards_default_max_tokens(fake_stream_api, tmp_path):
    # Whole-document synthesis raises the ceiling well above the 8096 extraction
    # default — a full campaign_state.md overflows 8096 (and hard-errors on the
    # claude-code backend). Guard the raised default.
    f1 = _write(tmp_path / "a.md", "x")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
    )
    assert fake_stream_api.calls[0]["max_tokens"] == campaignlib.pipelines.SYNTHESIS_MAX_TOKENS


def test_synthesize_forwards_explicit_max_tokens(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "x")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
        max_tokens=50000,
    )
    assert fake_stream_api.calls[0]["max_tokens"] == 50000


def test_extract_keeps_8096_default(fake_stream_api, tmp_path):
    # Per-chunk extraction must NOT inherit the raised synthesis ceiling — it
    # stays at stream_api's 8096 default (chunks are small).
    campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
    )
    assert fake_stream_api.calls[0]["max_tokens"] == 8096


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


# ── run_synthesize_pipeline(batch=True) ──────────────────────────────────────

def test_synthesize_batch_routes_through_run_single_batch(fake_run_single_batch, tmp_path):
    f1 = _write(tmp_path / "a.md", "alpha content")
    result = campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="SYS", model="m",
        batch=True,
    )
    assert len(fake_run_single_batch.calls) == 1
    assert result == "[batch-synth-result]"
    assert "alpha content" in fake_run_single_batch.calls[0]["user"]
    assert fake_run_single_batch.calls[0]["system"] == "SYS"
    assert fake_run_single_batch.calls[0]["model"] == "m"


def test_synthesize_batch_false_still_uses_stream_api(fake_stream_api, tmp_path):
    f1 = _write(tmp_path / "a.md", "x")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="SYS", model="m",
        batch=False,
    )
    assert len(fake_stream_api.calls) == 1


def test_synthesize_batch_forwards_max_tokens(fake_run_single_batch, tmp_path):
    f1 = _write(tmp_path / "a.md", "x")
    campaignlib.run_synthesize_pipeline(
        client=None,
        source_groups=[("", [f1])],
        synthesize_system="", model="m",
        max_tokens=5000,
        batch=True,
    )
    assert fake_run_single_batch.calls[0]["max_tokens"] == 5000


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


def test_load_alias_map_registry_replaces_dossier_scan(tmp_path):
    # A dossier says one thing; the registry (single authority) says another —
    # when registry_path is given, the registry wins and the dossier is ignored.
    (tmp_path / "tolubb.md").write_text(
        "---\nname: Tolubb\naliases:\n  - Cap. Tolubb\n---\n\nbody\n",
        encoding="utf-8",
    )
    registry_path = tmp_path / "entity_registry.yaml"
    registry_path.write_text(
        "version: 1\n"
        "entities:\n"
        "  - name: Ilvara Mizzrym\n"
        "    type: npc\n"
        "    aliases: [Ilvara, Mistress Ilvara]\n",
        encoding="utf-8",
    )
    m = campaignlib.load_alias_map(tmp_path, registry_path=registry_path)
    assert m == {"Ilvara Mizzrym": ["Ilvara", "Mistress Ilvara"]}
    assert "Tolubb" not in m  # dossier scan fully superseded


def test_load_alias_map_missing_registry_falls_back_to_dossiers(tmp_path):
    (tmp_path / "tolubb.md").write_text(
        "---\nname: Tolubb\naliases:\n  - Cap. Tolubb\n---\n\nbody\n",
        encoding="utf-8",
    )
    # registry_path points at a non-existent file → fall back to the dossier scan.
    m = campaignlib.load_alias_map(tmp_path, registry_path=tmp_path / "nope.yaml")
    assert m == {"Tolubb": ["Cap. Tolubb"]}


def test_find_alias_registry_announces_when_found(tmp_path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "entity_registry.yaml").write_text(
        "version: 1\nentities: []\n", encoding="utf-8")
    p = campaignlib.find_alias_registry(tmp_path)
    assert p is not None
    err = capsys.readouterr().err
    assert "Entity registry" in err and "superseded" in err


def test_find_alias_registry_silent_when_absent(tmp_path, capsys):
    assert campaignlib.find_alias_registry(tmp_path) is None
    assert capsys.readouterr().err == ""


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


# ── preserve_quoted: alias rewriting must never reach a verbatim record (#223) ──

def test_preserve_quoted_leaves_double_quoted_speech_untouched():
    normalize, _ = campaignlib.build_alias_normalizer(
        {'Iarno "Glasstaff" Albrek': ["Glasstaff"]}, preserve_quoted=True)
    assert normalize('Wick shrugged. "Glasstaff? Man, he\'s scary."') == \
        'Wick shrugged. "Glasstaff? Man, he\'s scary."'


def test_preserve_quoted_still_rewrites_the_prose_around_the_quote():
    normalize, _ = campaignlib.build_alias_normalizer(
        {"Nezznar the Spider": ["Spider"]}, preserve_quoted=True)
    assert normalize('Spider had been here. "Spider," he said. Spider was gone.') == \
        'Nezznar the Spider had been here. "Spider," he said. Nezznar the Spider was gone.'


def test_preserve_quoted_protects_curly_quotes_and_italic_spans():
    normalize, _ = campaignlib.build_alias_normalizer(
        {"Dagult Neverember": ["Lord Neverember"]}, preserve_quoted=True)
    assert normalize("“Lord Neverember said so.”") == \
        "“Lord Neverember said so.”"
    # *...* carries VTT-truncated speech and stage directions.
    assert normalize("*Lord Neverember, cut off*") == "*Lord Neverember, cut off*"


def test_preserve_quoted_correct_aliases_are_the_dangerous_case():
    """The alias data here is RIGHT — which is exactly why nothing downstream
    catches the edit. Laeral Silverhand really is the Open Lord of Waterdeep,
    so the substitution is canon-correct and produces a self-referential
    sentence no fact-check can flag."""
    alias_map = {"Laeral Silverhand": ["Open Lord of Waterdeep"]}
    src = 'Lady Laeral Silverhand, "who\'s the Open Lord of Waterdeep."'

    unscoped, _ = campaignlib.build_alias_normalizer(alias_map)
    assert unscoped(src) == 'Lady Laeral Silverhand, "who\'s the Laeral Silverhand."'

    scoped, _ = campaignlib.build_alias_normalizer(alias_map, preserve_quoted=True)
    assert scoped(src) == src


def test_preserve_quoted_unpaired_quote_fails_safe():
    """An odd quotation mark must not freeze normalization off for the rest of
    the document — a protected span never crosses a blank line."""
    normalize, _ = campaignlib.build_alias_normalizer(
        {"Tolubb": ["Cap"]}, preserve_quoted=True)
    assert normalize('He said "hello, Cap\n\nCap walked away.') == \
        'He said "hello, Tolubb\n\nTolubb walked away.'


def test_preserve_quoted_defaults_off_so_grounding_pipelines_are_unchanged():
    normalize, _ = campaignlib.build_alias_normalizer({"Tolubb": ["Cap"]})
    assert normalize('He said "Cap".') == 'He said "Tolubb".'


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


@pytest.mark.parametrize("status", ["expired", "canceled"])
def test_extract_batch_expired_and_canceled_count_as_failures(
    monkeypatch, tmp_path, capsys, status
):
    """T026: the Batch API's other terminal item states are failures too —
    an expired or canceled item must not be mistaken for a success."""
    fake = FakeRunBatch(status_by_id={"extract_001": status})
    monkeypatch.setattr(campaignlib.pipelines, "run_batch", fake)

    failed = campaignlib.run_extract_pipeline(
        client=None, text="short",
        extract_system="SYS", model="m",
        extract_dir=tmp_path / "e", chunk_size=60000,
        batch=True,
    )

    assert failed == ["extract_001"]
    assert not (tmp_path / "e" / "extract_001.md").exists()
    assert f"FAILED extract_001: {status}" in capsys.readouterr().err
