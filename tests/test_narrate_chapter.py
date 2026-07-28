"""Tests for narrate_chapter.py (issue #202 part 2 — the narrative pass).

No network, no API key: every test that would otherwise call a model
monkeypatches ``stream_api``/``client_from_args`` with a fake, mirroring
tests/test_synthesise_world_state.py's FakeStreamAPI pattern. Real OOTA
chapter text is used only to sanity-check chunking/label derivation against
real heading conventions — never to make a live model call (see the module
docstring in narrate_chapter.py and the builder brief: DO NOT run the LLM
against the real corpus).
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.textproc import split_frontmatter  # noqa: E402
from pipelines.ensemble import narrate_chapter as nc  # noqa: E402

SCRIPT = ROOT / "pipelines" / "ensemble" / "narrate_chapter.py"

OOTA_CHAPTERS = Path("/home/kroussos/out-of-the-abyss/out-of-the-abyss/docs/chapters")
CH62 = OOTA_CHAPTERS / "chapter_62_the_key_is_secured.md"          # h2_speaker convention
CH01 = OOTA_CHAPTERS / "chapter_01_exploring_the_prison.md"        # h2 + h3 mixed
CH09 = OOTA_CHAPTERS / "chapter_09_leemooggoogoon_vs_sea_mother.md"  # no headings at all


# ── split_frontmatter (campaignlib.textproc, shared with synthesise_world_state) ──

def test_split_frontmatter_roundtrip():
    text = "---\napproved: true\nchapter: chapter_01\n---\n\nBody text here.\n"
    fm, body = split_frontmatter(text)
    assert fm == {"approved": True, "chapter": "chapter_01"}
    assert body == "\nBody text here.\n"


def test_split_frontmatter_no_marker_returns_empty_dict_and_whole_text():
    text = "Just plain text, no frontmatter.\n"
    fm, body = split_frontmatter(text)
    assert fm == {}
    assert body == text


def test_split_frontmatter_malformed_yaml_fails_closed():
    text = "---\n[ this is not : valid yaml : at all\n---\nBody\n"
    fm, body = split_frontmatter(text)
    assert fm == {}
    assert body == text  # nothing dropped


def test_split_frontmatter_non_mapping_yaml_fails_closed():
    text = "---\n- a\n- b\n---\nBody\n"
    fm, body = split_frontmatter(text)
    assert fm == {}
    assert body == text


# ── scene_label ──────────────────────────────────────────────────────────────

def test_scene_label_h2_speaker():
    chunk = "## Zalthir — The Aftermath of the Sanctum Attack\n\nSome prose."
    assert nc.scene_label(chunk, 1) == "Zalthir — The Aftermath of the Sanctum Attack"


def test_scene_label_h3():
    chunk = "### Grygum\n\nSome prose."
    assert nc.scene_label(chunk, 3) == "Grygum"


def test_scene_label_no_heading_falls_back_to_generic():
    chunk = "Plain prose with no heading at all."
    assert nc.scene_label(chunk, 5) == "Scene 5"


# ── render_narrative_md ──────────────────────────────────────────────────────

def test_render_narrative_md_frontmatter_defaults_unapproved():
    doc = nc.render_narrative_md(
        "chapter_01", Path("/x/chapter_01.md"),
        [("Scene A", "Prose A."), ("Scene B", "Prose B.")],
        "scene",
    )
    fm, body = split_frontmatter(doc)
    assert fm["approved"] is False
    assert fm["chapter"] == "chapter_01"
    assert fm["scenes"] == 2
    assert fm["chunking"] == "scene"
    assert "source" in fm and "generated_at" in fm


def test_render_narrative_md_scene_headers_in_order():
    doc = nc.render_narrative_md(
        "chapter_01", Path("/x/chapter_01.md"),
        [("Zalthir — Intro", "First."), ("Daz — Fallout", "Second.")],
        "scene",
    )
    assert doc.index("## Scene 1 — Zalthir — Intro") < doc.index("First.")
    assert doc.index("First.") < doc.index("## Scene 2 — Daz — Fallout")
    assert doc.index("## Scene 2 — Daz — Fallout") < doc.index("Second.")


def test_render_narrative_md_never_writes_approved_true():
    # render_narrative_md has no path that can produce `approved: true` —
    # only a human editing the file afterward does. Pin that contract.
    doc = nc.render_narrative_md("c", Path("/x/c.md"), [("s", "p")], "chunk")
    assert "approved: true" not in doc.lower()


# ── check_approval_gate ──────────────────────────────────────────────────────

def _write_narrative(path: Path, approved: bool) -> None:
    fm = yaml.safe_dump({"chapter": "c", "approved": approved}, sort_keys=False)
    path.write_text(f"---\n{fm}---\n\nBody.\n", encoding="utf-8")


def test_approval_gate_allows_missing_file(tmp_path):
    nc.check_approval_gate(tmp_path / "narrative.md", force=False)  # no raise


def test_approval_gate_allows_unapproved_overwrite(tmp_path):
    p = tmp_path / "narrative.md"
    _write_narrative(p, approved=False)
    nc.check_approval_gate(p, force=False)  # no raise


def test_approval_gate_refuses_approved_without_force(tmp_path, capsys):
    p = tmp_path / "narrative.md"
    _write_narrative(p, approved=True)
    with pytest.raises(SystemExit) as exc:
        nc.check_approval_gate(p, force=False)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "approved: true" in err
    assert "--force" in err


def test_approval_gate_force_overrides_approved(tmp_path):
    p = tmp_path / "narrative.md"
    _write_narrative(p, approved=True)
    nc.check_approval_gate(p, force=True)  # no raise


# ── main(): full run against a fake client, mirroring test_synthesise_world_state.py ──

class FakeStreamAPI:
    def __init__(self):
        self.calls = []

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model, "kwargs": kwargs})
        # Echo something that proves the RIGHT chunk reached the RIGHT call.
        first_line = user.strip().splitlines()[0][:40]
        return f"[rendered] {first_line}"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(nc, "stream_api", fake)
    monkeypatch.setattr(nc, "client_from_args", lambda *a, **kw: None)
    return fake


SCENE_CHAPTER = """# Chapter 09 Test Chapter


## Zalthir — Opening the Door

Zalthir opens the door. Nothing happens.


## Daz — What Was Behind It

Daz looks past Zalthir. He sees a pit fiend. Thorin kills it in two strikes.
"""


def test_main_writes_narrative_with_frontmatter_and_scenes(monkeypatch, fake_stream_api, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output),
    ])
    nc.main()

    assert output.exists()
    fm, body = split_frontmatter(output.read_text(encoding="utf-8"))
    assert fm["approved"] is False
    assert fm["chunking"] == "scene"
    assert fm["scenes"] == 2
    assert "## Scene 1 — Zalthir — Opening the Door" in body
    assert "## Scene 2 — Daz — What Was Behind It" in body
    assert len(fake_stream_api.calls) == 2


def test_main_caches_scenes_and_skips_recall_on_rerun(monkeypatch, fake_stream_api, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"
    argv = ["narrate_chapter.py", str(chapter), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    nc.main()
    assert len(fake_stream_api.calls) == 2

    # Delete the output (but NOT the cache) and re-run: cache should be reused,
    # so the fake sees no new calls.
    output.unlink()
    monkeypatch.setattr(sys, "argv", argv)
    nc.main()
    assert len(fake_stream_api.calls) == 2  # unchanged — both scenes came from cache
    assert output.exists()


def test_main_headerless_chapter_falls_back_to_chunk_labels(monkeypatch, fake_stream_api, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text("Just plain prose.\n\nNo headings anywhere in this chapter at all.\n",
                       encoding="utf-8")
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output),
    ])
    nc.main()
    fm, body = split_frontmatter(output.read_text(encoding="utf-8"))
    assert fm["chunking"] == "chunk"
    assert "## Scene 1 — Scene 1" in body


def test_main_refuses_to_clobber_approved_without_force(monkeypatch, fake_stream_api, tmp_path, capsys):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"
    _write_narrative(output, approved=True)
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output),
    ])
    with pytest.raises(SystemExit) as exc:
        nc.main()
    assert exc.value.code == 1
    assert len(fake_stream_api.calls) == 0  # refused BEFORE any model call
    assert "approved: true" in capsys.readouterr().err


def test_main_force_regenerates_and_resets_approved_false(monkeypatch, fake_stream_api, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"
    _write_narrative(output, approved=True)
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output), "--force",
    ])
    nc.main()
    fm, _ = split_frontmatter(output.read_text(encoding="utf-8"))
    assert fm["approved"] is False
    assert len(fake_stream_api.calls) == 2


def test_main_dry_run_makes_no_model_calls_and_writes_nothing(monkeypatch, fake_stream_api, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output), "--dry-run",
    ])
    nc.main()
    assert not output.exists()
    assert len(fake_stream_api.calls) == 0


def test_main_empty_input_errors(monkeypatch, tmp_path):
    chapter = tmp_path / "empty.md"
    chapter.write_text("   \n", encoding="utf-8")
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output),
    ])
    with pytest.raises(SystemExit) as exc:
        nc.main()
    assert exc.value.code == 1


# ── --help smoke test (argparse wiring only, no model call) ─────────────────

def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        sys_argv = sys.argv
        sys.argv = ["narrate_chapter.py", "--help"]
        try:
            nc.main()
        finally:
            sys.argv = sys_argv
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--output" in out
    assert "--force" in out
    assert "--dry-run" in out


# ── Real OOTA chapter text: chunking/label sanity only, NO model calls ──────
# Per the builder brief: read-only reference data may be used to verify
# chunking/assembly, but the LLM must never be called against it. These tests
# monkeypatch stream_api just like the synthetic-chapter tests above.

@pytest.mark.skipif(not CH62.exists(), reason="OOTA reference corpus not present in this environment")
def test_real_chapter62_h2_speaker_scene_labels(monkeypatch, fake_stream_api, tmp_path):
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(CH62), "--output", str(output),
    ])
    nc.main()
    fm, body = split_frontmatter(output.read_text(encoding="utf-8"))
    assert fm["chunking"] == "scene"
    # Chapter 62 has 6 "## Name — Scene" headings (see EnsembleGroundingInvestigation.md).
    assert fm["scenes"] == 6
    assert "## Scene 1 — Zalthir — The Aftermath of the Sanctum Attack" in body
    assert "## Scene 2 — Daz — The Death of Bookwyrm" in body


@pytest.mark.skipif(not CH09.exists(), reason="OOTA reference corpus not present in this environment")
def test_real_chapter09_headerless_falls_back_to_character_chunking(monkeypatch, fake_stream_api, tmp_path):
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(CH09), "--output", str(output),
        "--chunk-size", "6000",
    ])
    nc.main()
    fm, _body = split_frontmatter(output.read_text(encoding="utf-8"))
    assert fm["chunking"] == "chunk"  # confirms the 16-of-62 no-heading fallback path


@pytest.mark.skipif(not CH01.exists(), reason="OOTA reference corpus not present in this environment")
def test_real_chapter01_dry_run_reports_scene_plan_no_calls(monkeypatch, fake_stream_api, tmp_path, capsys):
    output = tmp_path / "narrative.md"
    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(CH01), "--output", str(output), "--dry-run",
    ])
    nc.main()
    assert len(fake_stream_api.calls) == 0
    out = capsys.readouterr().out
    assert "scene 1:" in out


# ── run_batched_scenes / --batch ─────────────────────────────────────────────
# Every other script that calls add_backend_args() (which always adds
# --batch) actually implements it (run_batch/run_single_batch) — leaving it a
# silent no-op here would be exactly the "computed a signal, ignored it"
# pattern issue #202 exists to stop repeating. Mirrors
# tests/test_extract_facts.py's FakeRunBatch pattern.

class FakeRunBatch:
    """Stands in for campaignlib.api.run_batch — records the one grouped call."""

    def __init__(self, results: dict):
        self.calls = []
        self._results = results

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        return self._results


def _batch_record(text=None, status="succeeded", error=None):
    return {"status": status, "text": text, "stop_reason": "end_turn",
            "error": error, "usage": None}


def test_run_batched_scenes_skips_cached(tmp_path, monkeypatch):
    (tmp_path / "scene_001.txt").write_text("cached prose", encoding="utf-8")
    fake = FakeRunBatch({"scene_002": _batch_record(text="fresh prose")})
    monkeypatch.setattr(nc, "run_batch", fake)

    results = nc.run_batched_scenes(["c1", "c2"], tmp_path, None, "sys", "m", 4096)
    assert results == {1: "cached prose", 2: "fresh prose"}
    assert len(fake.calls) == 1
    assert [r["custom_id"] for r in fake.calls[0]["requests"]] == ["scene_002"]
    assert (tmp_path / "scene_002.txt").read_text(encoding="utf-8") == "fresh prose"


def test_run_batched_scenes_fully_cached_submits_nothing(tmp_path, monkeypatch):
    (tmp_path / "scene_001.txt").write_text("cached", encoding="utf-8")
    fake = FakeRunBatch({})
    monkeypatch.setattr(nc, "run_batch", fake)
    results = nc.run_batched_scenes(["c1"], tmp_path, None, "sys", "m", 4096)
    assert results == {1: "cached"}
    assert fake.calls == []


def test_run_batched_scenes_failed_item_exits(tmp_path, monkeypatch, capsys):
    fake = FakeRunBatch({"scene_001": _batch_record(status="errored", error="boom")})
    monkeypatch.setattr(nc, "run_batch", fake)
    with pytest.raises(SystemExit) as exc:
        nc.run_batched_scenes(["c1"], tmp_path, None, "sys", "m", 4096)
    assert exc.value.code == 1
    assert "errored boom" in capsys.readouterr().err


def test_main_batch_flag_routes_through_run_batch(monkeypatch, tmp_path):
    chapter = tmp_path / "chapter_09_test.md"
    chapter.write_text(SCENE_CHAPTER, encoding="utf-8")
    output = tmp_path / "narrative.md"

    fake = FakeRunBatch({
        "scene_001": _batch_record(text="[batched] scene one"),
        "scene_002": _batch_record(text="[batched] scene two"),
    })
    monkeypatch.setattr(nc, "run_batch", fake)
    monkeypatch.setattr(nc, "client_from_args", lambda *a, **kw: None)

    monkeypatch.setattr(sys, "argv", [
        "narrate_chapter.py", str(chapter), "--output", str(output),
        "--backend", "anthropic", "--batch",
    ])
    nc.main()

    assert len(fake.calls) == 1
    body = output.read_text(encoding="utf-8")
    assert "[batched] scene one" in body
    assert "[batched] scene two" in body
