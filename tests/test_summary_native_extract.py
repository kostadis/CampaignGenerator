"""extract: the map step (spec 033 T014, FR-001..FR-006, FR-025, FR-027).

A fake client returns canned chunk outputs, so these tests never reach a backend. ``--chunk-chars 1``
makes each of the four fixture chapters its own chunk.
"""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import extract, notes, schema
from tests.conftest_state import (
    CANNED, fake_models, extract_args, notes_dir, range_dir, run_cli, state_campaign,
)


@pytest.fixture
def camp(tmp_path):
    return state_campaign(tmp_path)


@pytest.fixture
def fm(monkeypatch):
    return fake_models(monkeypatch)


RANGES = ["002-002", "003-003", "004-004", "005-005"]


def test_each_chunk_is_written_to_state_notes(camp, fm):
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    nd = notes_dir(camp)
    for k, rng in enumerate(RANGES, 1):
        for kind in ("user.md", "out.md", "checked.json"):
            assert (nd / f"chunk{k:02d}.{rng}.{kind}").is_file(), (k, kind)
    assert (nd / "drops.md").is_file() and (nd / "manifest.json").is_file()
    assert len(fm.extract_calls) == 4
    # the raw output is kept verbatim, and the checked file is what the code kept
    assert (nd / "chunk02.003-003.out.md").read_text() == CANNED[3]
    checked = json.loads((nd / "chunk02.003-003.checked.json").read_text())
    assert checked["chunk"] == "003-003" and len(checked["drops"]) == 3


def test_the_prompt_has_no_audit_list(camp, fm):
    """FR-027: neither the tracking-file items nor an audit section ever reach an extraction call."""
    assert (camp / "docs" / "tracking" / "tracking.txt").is_file()
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err
    for call in fm.extract_calls:
        text = call["system"] + call["user"]
        assert "AUDIT" not in text.upper()
        assert "Reach Velkynvelve and meet Sarith" not in text
        assert "Obtain the Ilvara signet ring" not in text
    for k, rng in enumerate(RANGES, 1):
        user = (notes_dir(camp) / f"chunk{k:02d}.{rng}.user.md").read_text()
        assert "Obtain the Ilvara signet ring" not in user and "AUDIT" not in user.upper()


def test_the_prompt_is_the_chunks_chapters_and_the_outline(camp, fm):
    run_cli(extract_args(camp))
    user = fm.extract_calls[1]["user"]
    assert user.startswith("CHAPTERS IN THIS CHUNK: 003-003")
    assert "======== CHAPTER 003 (003-the-descent.md) ========" in user
    assert "### 003.02 The Long Stair" in user and "### 002.01" not in user
    for h in schema.STATE_MAP_SECTIONS:
        assert h in user.split("OUTLINE", 1)[1]


def test_the_manifest_records_inputs_and_every_chunk(camp, fm):
    run_cli(extract_args(camp))
    m = json.loads((notes_dir(camp) / "manifest.json").read_text())
    assert m["kind"] == "state_notes" and m["complete"] is True
    assert m["range"] == {"since": 2, "until": 5}
    for k in ("corpus_manifest_sha256", "registry_sha256", "players_sha256"):
        assert m[k]
    assert [c["chapters"] for c in m["chunks"]] == RANGES
    assert all(c["status"] == "checked" and c["cache_key"] for c in m["chunks"])
    assert m["chunks"][1]["dropped"] == 3 and m["chunks"][1]["kept"] > 0
    assert m["model"] == "fake-model" and m["backend"] == "dgx" and m["chunk_chars"] == 1


def test_the_notes_are_fresh_for_synth_after_extract(camp, fm):
    from pipelines.summary_native import freshness
    run_cli(extract_args(camp))
    assert freshness.check_notes_fresh(
        range_dir(camp), camp / "docs" / "entity_registry.yaml", camp / "config" / "players.yaml") is None


def test_the_run_record_names_inputs_settings_and_every_chunk(camp, fm):
    run_cli(extract_args(camp))
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    rec = json.loads((run / "record.json").read_text())
    assert rec["step"] == "extract" and rec["exit_code"] == 0
    assert rec["backend"] == "dgx" and rec["model"] == "fake-model" and rec["max_tokens"] == schema.DEFAULT_MAX_TOKENS
    assert rec["range"] == {"since": 2, "until": 5} and rec["absent_chapters"] == []
    assert len(rec["inputs"]["summaries"]) == 4 and rec["inputs"]["registry_sha256"]
    assert [c["chapters"] for c in rec["chunks"]] == RANGES
    assert all(c["status"] == "extracted" and "secs" in c and "endpoint" in c for c in rec["chunks"])
    assert rec["started"] and rec["finished"]


def test_drops_md_lists_the_reasons_and_the_totals(camp, fm):
    rc, out, _ = run_cli(extract_args(camp))
    md = (notes_dir(camp) / "drops.md").read_text()
    assert "outside-chunk [ch 004 / 004.01]" in md
    assert "quoted-span-not-found" in md and '"the web is a lie"' in md
    assert "missing-thread-tag" in md
    assert "chunk 02/04 ch 003-003" in out and "dropped 3" in out
    assert "kept" in out.splitlines()[-1] or "dropped" in out


def test_a_cached_run_makes_zero_calls(camp, fm):
    run_cli(extract_args(camp))
    n = len(fm.extract_calls)
    before = {p.name: p.read_bytes() for p in notes_dir(camp).iterdir()}
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert len(fm.extract_calls) == n
    assert "cached" in out
    after = {p.name: p.read_bytes() for p in notes_dir(camp).iterdir()}
    assert after == before  # the notes (and the manifest) are byte-identical


def test_named_resume_of_completed_extract_makes_zero_calls(camp, fm):
    assert run_cli(extract_args(camp))[0] == 0
    runs = range_dir(camp) / schema.STATE_DIR / "runs"
    (run,) = [p for p in runs.iterdir() if p.is_dir()]
    fm.extract_calls.clear()
    rc, out, err = run_cli([*extract_args(camp), "--resume", run.name])
    assert rc == 0, err
    assert fm.extract_calls == []
    assert f"resuming run {run.name}" in out


def test_a_changed_extraction_prompt_is_never_served_from_cache(camp, fm, monkeypatch):
    """Spec 034 FR-002: the system prompt (here: its ``## Party`` grammar) is part of the cache key,
    so editing it re-extracts every chunk rather than reusing notes written under the old grammar."""
    run_cli(extract_args(camp))
    n = len(fm.extract_calls)
    keys = [c["cache_key"] for c in json.loads((notes_dir(camp) / "manifest.json").read_text())["chunks"]]
    real = extract.load_system()
    assert "- **Subject** — fact [cite]" in real and "- [LEVEL] **Subject** — N [cite]" in real
    monkeypatch.setattr(extract, "load_system", lambda: real.replace("**Subject**", "**Name**", 1))
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert len(fm.extract_calls) == n + 4  # every chunk re-extracted: nothing reused
    new_keys = [c["cache_key"] for c in json.loads((notes_dir(camp) / "manifest.json").read_text())["chunks"]]
    assert set(keys).isdisjoint(new_keys)


def test_a_failed_chunk_exits_3_and_the_next_run_extracts_only_it(camp, fm):
    fm.fail_chunks["004-004"] = 1  # campaignlib exhausted its transport policy once
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 3
    assert "004-004" in err and "failed" in err
    assert sum(1 for c in fm.extract_calls if c["range"] == "004-004") == 1
    assert len(fm.extract_calls) == 4
    nd = notes_dir(camp)
    assert not (nd / "chunk03.004-004.checked.json").exists()
    m = json.loads((nd / "manifest.json").read_text())
    assert m["complete"] is False and [c["status"] for c in m["chunks"]] == ["checked", "checked", "failed", "checked"]

    fm.extract_calls.clear()
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]
    assert json.loads((nd / "manifest.json").read_text())["complete"] is True


def test_final_transport_failure_is_not_retried_by_the_pipeline(camp, fm):
    fm.fail_chunks["003-003"] = 1
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 3
    assert sum(1 for c in fm.extract_calls if c["range"] == "003-003") == 1


def test_when_nothing_worked_the_backend_was_not_reached_exit_4(camp, fm):
    for r in RANGES:
        fm.fail_chunks[r] = 5
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 4
    assert "could not be reached" in err or "no chunk" in err


def test_force_re_extracts_everything(camp, fm):
    run_cli(extract_args(camp))
    fm.extract_calls.clear()
    rc, _, _ = run_cli(extract_args(camp, "--force"))
    assert rc == 0 and len(fm.extract_calls) == 4


def test_a_changed_model_misses_the_cache(camp, fm):
    run_cli(extract_args(camp))
    fm.extract_calls.clear()
    args = extract_args(camp)
    args[args.index("--model") + 1] = "another-model"
    rc, _, _ = run_cli(args)
    assert rc == 0 and len(fm.extract_calls) == 4


def test_only_a_changed_chapter_is_re_extracted(camp, fm):
    """A summary edit makes the corpus stale (refusal); after a rebuild only that chunk's key changed."""
    run_cli(extract_args(camp))
    f = camp / "docs" / "summaries" / "004-the-reckoning.md"
    f.write_text(f.read_text() + "\nAn added line.\n")
    rc, out, err = run_cli(["build", "--config", str(camp / "config/config.yaml"),
                            "--summaries-dir", str(camp / "docs/summaries"), "--since", "2", "--until", "5", "--force"])
    assert rc == 0, err
    fm.extract_calls.clear()
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]


def test_dump_only_writes_prompts_and_a_manifest_and_makes_no_call(camp, fm, monkeypatch):
    from pipelines.summary_native import extract

    def boom(*a, **k):
        raise AssertionError("a client was created")

    monkeypatch.setattr(extract, "client_from_args", boom)
    rc, out, err = run_cli(extract_args(camp, "--dump-only"))
    assert rc == 0, err
    assert not fm.extract_calls
    nd = notes_dir(camp)
    assert all((nd / f"chunk{k:02d}.{r}.user.md").is_file() for k, r in enumerate(RANGES, 1))
    assert not list(nd.glob("*.out.md")) and not list(nd.glob("*.checked.json"))
    m = json.loads((nd / "manifest.json").read_text())
    assert m["complete"] is False and all(c["status"] == "pending" for c in m["chunks"])
    assert "--dump-only" in out


def test_refuses_when_no_corpus_was_built(tmp_path, fm):
    import shutil
    from tests.conftest_state import STATE_FIXTURE
    root = tmp_path / "camp"
    shutil.copytree(STATE_FIXTURE, root)
    rc, _, err = run_cli(extract_args(root))
    assert rc == 2 and "summary_native build" in err and not fm.extract_calls


def test_refuses_a_stale_corpus(camp, fm):
    f = camp / "docs" / "summaries" / "002-the-pens.md"
    f.write_text(f.read_text() + "\nAn edit after build.\n")
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 2 and "summaries changed since build" in err and not fm.extract_calls


def test_refuses_a_non_positive_chunk_size(camp, fm):
    args = extract_args(camp)
    args[args.index("--chunk-chars") + 1] = "0"
    rc, _, err = run_cli(args)
    assert rc == 2 and "--chunk-chars" in err


def test_chunk_size_comes_from_config_when_no_flag(camp, fm):
    (camp / "config" / "grounding.yaml").write_text("summary_native:\n  extract:\n    chunk_chars: 10000000\n")
    args = [a for a in extract_args(camp) if a not in ("--chunk-chars", "1")]
    rc, _, err = run_cli(args)
    assert rc == 0, err
    assert len(fm.extract_calls) == 1 and fm.extract_calls[0]["range"] == "002-005"


def test_a_gap_in_the_range_is_recorded(camp, fm):
    (camp / "docs" / "summaries" / "004-the-reckoning.md").unlink()
    rc, _, err = run_cli(["build", "--config", str(camp / "config/config.yaml"),
                          "--summaries-dir", str(camp / "docs/summaries"), "--since", "2", "--until", "5", "--force"])
    assert rc == 0, err
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    assert json.loads((run / "record.json").read_text())["absent_chapters"] == [4]


def test_extract_writes_nothing_outside_state(camp, fm):
    before = {p.relative_to(camp).as_posix(): p.read_bytes() for p in camp.rglob("*") if p.is_file()}
    run_cli(extract_args(camp))
    after = {p.relative_to(camp).as_posix(): p.read_bytes() for p in camp.rglob("*") if p.is_file()}
    changed = {k for k in after if before.get(k) != after[k]}
    assert changed and all("/state/" in k for k in changed), sorted(changed)[:5]
    assert not (set(before) - set(after))


def test_the_notes_it_wrote_load_back(camp, fm):
    run_cli(extract_args(camp))
    manifest, results = notes.load_checked(range_dir(camp))
    assert [r.chunk for r in results] == RANGES and manifest["complete"] is True


def test_load_checked_refuses_an_incomplete_extraction(camp, fm):
    fm.fail_chunks["004-004"] = 2
    run_cli(extract_args(camp))
    with pytest.raises(notes.NotesIncomplete) as e:
        notes.load_checked(range_dir(camp))
    assert "004-004" in str(e.value)


# ── #515: a chunk missing outline sections is a failed chunk ────────────────


def _without(raw: str, heading: str, keep_heading: bool = False, body: str = "") -> str:
    """``raw`` with one ``##`` section removed (or, with ``keep_heading``, its body replaced)."""
    out, skipping = [], False
    for line in raw.splitlines():
        if line.startswith("## "):
            skipping = line.strip() == heading
            if skipping and keep_heading:
                out += [line, body]
            if skipping:
                continue
        if not skipping:
            out.append(line)
    return "\n".join(out) + "\n"


def _drop_world_in(fm, monkeypatch, rng: str, times: int | None = None, **kw):
    """Make the fake backend answer ``rng`` without ``## World`` (``times`` calls, else always)."""
    left = [times]

    def render(client, system, user, model, max_tokens):
        raw = fm.extract_render(client, system, user, model, max_tokens)
        if f"CHAPTERS IN THIS CHUNK: {rng}" not in user or left[0] == 0:
            return raw
        if left[0] is not None:
            left[0] -= 1
        return _without(raw, "## World", **kw)

    monkeypatch.setattr(extract, "render_part", render)


def test_an_output_missing_world_is_a_failed_chunk_named_in_output_record_and_drops(camp, fm, monkeypatch):
    _drop_world_in(fm, monkeypatch, "004-004")
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 3
    assert sum(1 for c in fm.extract_calls if c["range"] == "004-004") == 2  # one retry, like a failed call
    assert "004-004" in err and "## World" in err
    assert "extracted 3/4 chunks" in out  # not counted as a success
    nd = notes_dir(camp)
    assert not (nd / "chunk03.004-004.checked.json").exists()
    assert (nd / "chunk03.004-004.out.md").is_file()  # the raw output stays for inspection
    m = json.loads((nd / "manifest.json").read_text())
    assert m["complete"] is False and [c["status"] for c in m["chunks"]] == ["checked", "checked", "failed", "checked"]
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    rec = json.loads((run / "record.json").read_text())
    bad = rec["chunks"][2]
    assert rec["exit_code"] == 3 and bad["status"] == "failed" and bad["missing_sections"] == ["## World"]
    assert "## World" in bad["error"]
    drops = (nd / "drops.md").read_text()
    assert "004-004: missing ## World" in drops
    with pytest.raises(notes.NotesIncomplete):
        notes.load_checked(range_dir(camp))


def test_a_missing_section_gets_one_retry_and_a_complete_answer_then_passes(camp, fm, monkeypatch):
    _drop_world_in(fm, monkeypatch, "003-003", times=1)
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert sum(1 for c in fm.extract_calls if c["range"] == "003-003") == 2
    assert (notes_dir(camp) / "chunk02.003-003.out.md").read_text() == CANNED[3]


def test_every_missing_section_is_named(camp, fm, monkeypatch):
    monkeypatch.setattr(
        extract, "render_part",
        lambda client, system, user, model, max_tokens: "## Events\n- (none)\n\n## Concluded\n- (none)\n")
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 3  # the backend answered, so it was reached: incomplete, not exit 4
    for h in ("## Threads", "## NPC Status", "## World", "## Party"):
        assert h in err
    assert "## Events" not in err.split("output missing outline section(s)", 1)[1]


def test_a_world_section_holding_only_none_passes(camp, fm, monkeypatch):
    _drop_world_in(fm, monkeypatch, "004-004", keep_heading=True, body="- (none)")
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert sum(1 for c in fm.extract_calls if c["range"] == "004-004") == 1
    assert "extracted 4/4 chunks" in out


def test_a_present_but_empty_section_passes(camp, fm, monkeypatch):
    _drop_world_in(fm, monkeypatch, "004-004", keep_heading=True, body="")
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err


def _break_cached_world(camp, rng_stem="chunk03.004-004"):
    f = notes_dir(camp) / f"{rng_stem}.out.md"
    f.write_text(_without(f.read_text(), "## World"))


def test_a_cached_chunk_missing_a_section_is_reported_without_a_model_call(camp, fm):
    run_cli(extract_args(camp))
    _break_cached_world(camp)
    fm.extract_calls.clear()
    rc, out, err = run_cli(extract_args(camp, "--dump-only"))
    assert rc == 3 and not fm.extract_calls
    assert "004-004" in err and "INCOMPLETE" in err and "## World" in err
    nd = notes_dir(camp)
    m = json.loads((nd / "manifest.json").read_text())
    assert m["complete"] is False and m["chunks"][2]["status"] == "failed"
    assert "004-004: missing ## World" in (nd / "drops.md").read_text()
    # reported, not repaired: the next full run extracts only that chunk
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]
    assert json.loads((nd / "manifest.json").read_text())["complete"] is True


def test_a_rerun_over_a_cached_incomplete_chunk_exits_3_with_no_model_call_then_fixes_it(camp, fm, monkeypatch):
    run_cli(extract_args(camp))
    _break_cached_world(camp)
    fm.extract_calls.clear()
    monkeypatch.setattr(extract, "client_from_args", lambda *a, **k: (_ for _ in ()).throw(AssertionError("client")))
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 3 and not fm.extract_calls
    assert "cached INCOMPLETE" in err and "## World" in err and "extracted 3/4 chunks (0 new, 3 cached)" in out
    monkeypatch.setattr(extract, "client_from_args", fm.make_client)
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]


def test_a_cached_incomplete_chunk_does_not_hide_an_unreachable_backend_exit_4(camp, fm):
    run_cli(extract_args(camp))
    _break_cached_world(camp)
    nd = notes_dir(camp)
    for stem in ("chunk01.002-002", "chunk02.003-003", "chunk04.005-005"):  # the rest must be called again
        (nd / f"{stem}.checked.json").unlink()
    for r in RANGES:
        fm.fail_chunks[r] = 5
    fm.extract_calls.clear()
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 4, err
    assert "could not be reached" in err
    assert "004-004" not in [c["range"] for c in fm.extract_calls]  # the cached one made no call


def test_the_closing_message_words_cached_chunks_separately(camp, fm):
    run_cli(extract_args(camp))
    _break_cached_world(camp)
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 3
    assert "1 cached chunk(s) found incomplete, not called: 004-004" in err
    assert "retried once" not in err


def test_a_complete_sibling_copy_replaces_an_incomplete_local_one(camp, fm):
    run_cli(extract_args(camp))
    nd = notes_dir(camp)
    sib = range_dir(camp).parent / "ch001-009" / "state" / "notes"
    sib.mkdir(parents=True)
    for suffix in ("checked.json", "out.md"):
        (sib / f"chunk01.004-004.{suffix}").write_bytes((nd / f"chunk03.004-004.{suffix}").read_bytes())
    _break_cached_world(camp)
    fm.extract_calls.clear()
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert not fm.extract_calls
    assert (nd / "chunk03.004-004.out.md").read_text() == CANNED[4]


def test_a_retry_that_raises_after_an_incomplete_answer_keeps_the_missing_sections(camp, fm, monkeypatch):
    calls = []

    def render(client, system, user, model, max_tokens):
        raw = fm.extract_render(client, system, user, model, max_tokens)
        if "CHAPTERS IN THIS CHUNK: 004-004" not in user:
            return raw
        calls.append(1)
        if len(calls) == 1:
            return _without(raw, "## World")
        raise RuntimeError("upstream failure")

    monkeypatch.setattr(extract, "render_part", render)
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 3, err  # the backend answered once, so it was reached
    nd = notes_dir(camp)
    assert not (nd / "chunk03.004-004.checked.json").exists()
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    rec = json.loads((run / "record.json").read_text())
    assert rec["chunks"][2]["status"] == "failed"
    assert "004-004" not in (nd / "drops.md").read_text()


def test_a_sibling_ranges_incomplete_output_is_not_reused(camp, fm, monkeypatch, tmp_path):
    from tests.conftest_state import extract_args as _ea  # noqa: F401 - the same CLI, a second range
    run_cli(extract_args(camp))
    # An older sibling build of the same chunk whose raw output lacks a section: its key matches,
    # but it must not be copied in as a success.
    nd = notes_dir(camp)
    sib = range_dir(camp).parent / "ch001-009" / "state" / "notes"
    sib.mkdir(parents=True)
    key = json.loads((nd / "chunk03.004-004.checked.json").read_text())["cache_key"]
    (sib / "chunk01.004-004.checked.json").write_text(json.dumps({"chunk": "004-004", "notes": [], "drops": [], "cache_key": key}))
    (sib / "chunk01.004-004.out.md").write_text(_without(CANNED[4], "## World"))
    (nd / "chunk03.004-004.checked.json").unlink()
    fm.extract_calls.clear()
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]


# ── spec 033 US5: several endpoints on one queue (T039) ─────────────────────

import re
import threading
import time

EP_A, EP_B = "http://spark:8001/v1", "http://spark2:8001/v1"


def two_endpoint_args(camp, *extra):
    base = [a for a in extract_args(camp) if a not in ("--endpoint", EP_A)]
    return [*base, "--endpoints", EP_A, EP_B, *extra]


def _canned_for(user):
    return CANNED[int(re.search(r"CHAPTERS IN THIS CHUNK: (\d{3})", user).group(1))]


def test_every_chunk_runs_once_across_two_endpoints_and_the_record_names_the_endpoint(camp, fm):
    rc, out, err = run_cli(two_endpoint_args(camp))
    assert rc == 0, err
    assert sorted(c["range"] for c in fm.extract_calls) == RANGES
    assert {a["endpoint"] for a in fm.client_args} == {EP_A, EP_B}
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    rec = json.loads((run / "record.json").read_text())
    assert rec["endpoints"] == ["spark:8001", "spark2:8001"] and rec["parallel"] == schema.DEFAULT_EXTRACT_PARALLEL
    assert rec["concurrency"] == {"value": schema.DEFAULT_EXTRACT_PARALLEL, "source": "fallback", "model": "fake-model", "declared_max": None}
    assert [c["chapters"] for c in rec["chunks"]] == RANGES
    assert all(c["endpoint"] in ("spark:8001", "spark2:8001") for c in rec["chunks"])
    assert "@spark" in out


def test_final_transport_failure_fails_over_to_an_untried_endpoint(camp, fm, monkeypatch):
    import httpx

    calls = []

    def render(client, system, user, model, max_tokens):
        calls.append((client, user))
        if client == EP_A:
            raise httpx.ConnectError("offline")
        return _canned_for(user)

    monkeypatch.setattr(extract, "render_part", render)
    rc, _, err = run_cli(two_endpoint_args(camp, "--parallel", "1"))
    assert rc == 0, err
    assert any(endpoint == EP_A for endpoint, _ in calls)
    assert any(endpoint == EP_B for endpoint, _ in calls)


def test_extract_rejoins_a_recovered_endpoint_while_work_remains(camp, fm, monkeypatch):
    import httpx
    calls = []
    failed = {EP_A: False}
    def render(client, system, user, model, max_tokens):
        calls.append(client)
        if client == EP_A and not failed[EP_A]:
            failed[EP_A] = True
            raise httpx.ConnectError("brief outage")
        return _canned_for(user)
    monkeypatch.setattr(extract, "render_part", render)
    rc, _, err = run_cli(two_endpoint_args(camp, "--parallel", "1"))
    assert rc == 0, err
    assert calls.count(EP_A) >= 2 and EP_B in calls


def test_a_slow_endpoint_takes_fewer_chunks(camp, fm, monkeypatch):
    seen: list[str] = []
    lock = threading.Lock()

    def render(client, system, user, model, max_tokens):
        if client == EP_B:
            time.sleep(0.4)
        with lock:
            seen.append(client)
        return _canned_for(user)

    monkeypatch.setattr(extract, "render_part", render)
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 0, err
    assert len(seen) == 4 and seen.count(EP_B) < seen.count(EP_A)


def test_parallel_runs_that_many_calls_per_endpoint_at_once(camp, fm, monkeypatch):
    state = {"live": 0, "peak": 0}
    lock = threading.Lock()

    def render(client, system, user, model, max_tokens):
        with lock:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
        time.sleep(0.15)
        with lock:
            state["live"] -= 1
        return _canned_for(user)

    monkeypatch.setattr(extract, "render_part", render)
    rc, _, err = run_cli(extract_args(camp, "--parallel", "3"))
    assert rc == 0, err
    assert state["peak"] == 3
    (run,) = [p for p in (range_dir(camp) / schema.STATE_DIR / "runs").iterdir() if p.is_dir()]
    assert json.loads((run / "record.json").read_text())["parallel"] == 3


def test_parallel_below_one_is_refused_by_the_parser(camp, fm):
    with pytest.raises(SystemExit):
        run_cli(extract_args(camp, "--parallel", "0"))


def test_preflight_quarantines_an_unreachable_peer_and_runs_on_survivor(camp, fm):
    fm.unreachable.add(EP_B)
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 0
    assert "quarantined" in err and "spark2:8001" in err
    assert {call["endpoint"] for call in fm.client_args} == {EP_A}


def test_preflight_quarantines_a_peer_serving_another_model(camp, fm):
    fm.served[EP_B] = ["some-other-model"]
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 0
    assert "spark2:8001" in err and "some-other-model" in err and "fake-model" in err
    assert len(fm.extract_calls) == len(RANGES)


def test_a_single_endpoint_is_preflighted_too(camp, fm):
    fm.served[EP_A] = ["nope"]
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 2 and "spark:8001" in err and fm.extract_calls == []


def test_a_fully_cached_run_makes_no_preflight(camp, fm):
    assert run_cli(two_endpoint_args(camp))[0] == 0
    fm.preflighted.clear()
    fm.unreachable.update({EP_A, EP_B})
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 0, err
    assert fm.preflighted == []


def test_dump_only_makes_no_preflight(camp, fm):
    fm.unreachable.add(EP_A)
    rc, _, err = run_cli(two_endpoint_args(camp, "--dump-only"))
    assert rc == 0, err
    assert fm.preflighted == [] and fm.extract_calls == []


def test_endpoints_with_a_non_dgx_backend_refuses(camp, fm):
    args = two_endpoint_args(camp)
    args[args.index("dgx")] = "openrouter"
    rc, _, err = run_cli(args)
    assert rc == 2 and "--endpoints" in err and "dgx" in err
    assert fm.extract_calls == [] and fm.preflighted == []


def test_endpoint_and_endpoints_together_refuse(camp, fm):
    rc, _, err = run_cli([*extract_args(camp), "--endpoints", EP_B])
    assert rc == 2 and "--endpoint" in err and "not both" in err


def test_a_failed_chunk_on_two_endpoints_still_finishes_the_others(camp, fm):
    fm.fail_chunks["004-004"] = 2
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 3 and "004-004" in err
    m = json.loads((notes_dir(camp) / "manifest.json").read_text())
    assert [c["status"] for c in m["chunks"]] == ["checked", "checked", "failed", "checked"]


def test_extract_content_rejection_is_terminal_and_does_not_quarantine_peer(camp, fm, monkeypatch):
    """Validation failure is content work, never a transport failover signal."""
    seen = []
    def render(client, system, user, model, max_tokens):
        seen.append(client)
        return "## Events\n"  # rejected by the chunk checker, but transport succeeded
    monkeypatch.setattr(extract, "render_part", render)
    rc, _, _ = run_cli(two_endpoint_args(camp, "--parallel", "1"))
    assert rc == 3
    # Both configured endpoints remain usable for independent chunks.
    assert {EP_A, EP_B}.issubset(set(seen))
