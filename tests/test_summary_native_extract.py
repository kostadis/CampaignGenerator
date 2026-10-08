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


def test_a_failed_chunk_exits_3_and_the_next_run_extracts_only_it(camp, fm):
    fm.fail_chunks["004-004"] = 2  # the call and its one retry both fail
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 3
    assert "004-004" in err and "failed" in err
    assert sum(1 for c in fm.extract_calls if c["range"] == "004-004") == 2
    assert len(fm.extract_calls) == 5
    nd = notes_dir(camp)
    assert not (nd / "chunk03.004-004.checked.json").exists()
    m = json.loads((nd / "manifest.json").read_text())
    assert m["complete"] is False and [c["status"] for c in m["chunks"]] == ["checked", "checked", "failed", "checked"]

    fm.extract_calls.clear()
    rc, out, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert [c["range"] for c in fm.extract_calls] == ["004-004"]
    assert json.loads((nd / "manifest.json").read_text())["complete"] is True


def test_one_transient_failure_is_retried_once(camp, fm):
    fm.fail_chunks["003-003"] = 1
    rc, _, err = run_cli(extract_args(camp))
    assert rc == 0, err
    assert sum(1 for c in fm.extract_calls if c["range"] == "003-003") == 2


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
    assert [c["chapters"] for c in rec["chunks"]] == RANGES
    assert all(c["endpoint"] in ("spark:8001", "spark2:8001") for c in rec["chunks"])
    assert "@spark" in out


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


def test_preflight_refuses_an_unreachable_endpoint_before_any_call(camp, fm):
    fm.unreachable.add(EP_B)
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 2
    assert "spark2:8001" in err and "not answering" in err
    assert fm.extract_calls == [] and fm.client_args == []
    assert not list(notes_dir(camp).glob("*.out.md"))


def test_preflight_refuses_an_endpoint_serving_another_model_before_any_call(camp, fm):
    fm.served[EP_B] = ["some-other-model"]
    rc, _, err = run_cli(two_endpoint_args(camp))
    assert rc == 2
    assert "spark2:8001" in err and "some-other-model" in err and "fake-model" in err
    assert fm.extract_calls == []


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
