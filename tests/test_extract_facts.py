"""Tests for extract_facts.py — JSON parsing/salvage and the --parallel path.

The parallel orchestrator (run_parallel) takes an injected ``call_fn(chunk) ->
raw text``, so everything here runs without a server. The CLI smoke test runs
the script as a subprocess against a fully pre-seeded chunk cache (zero API
calls), mirroring tests/test_ensemble_pipeline.py.
"""
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract_facts as ef  # noqa: E402

SCRIPT = ROOT / "extract_facts.py"


def _fact(text: str) -> dict:
    return {"type": "event", "subject": "s", "fact": text, "source_quote": ""}


def _raw_for(chunk: str) -> str:
    """A valid model response whose single fact embeds the chunk text."""
    return json.dumps([_fact(chunk)])


# ── parse_facts_block ────────────────────────────────────────────────────────

def test_parse_clean_array():
    facts = ef.parse_facts_block('[{"type": "npc", "subject": "Daz", '
                                 '"fact": "f", "source_quote": ""}]')
    assert len(facts) == 1 and facts[0]["subject"] == "Daz"


def test_parse_fenced_array():
    raw = '```json\n[{"type": "npc", "subject": "Daz", "fact": "f", ' \
          '"source_quote": ""}]\n```'
    assert len(ef.parse_facts_block(raw)) == 1


def test_parse_preamble_then_array():
    raw = 'Here are the facts:\n[{"type": "npc", "subject": "Daz", ' \
          '"fact": "f", "source_quote": ""}]'
    assert len(ef.parse_facts_block(raw)) == 1


def test_parse_salvages_around_malformed_object():
    # middle object has a trailing comma — whole-array parse fails, the two
    # well-formed neighbours are salvaged individually
    raw = ('[{"type": "npc", "subject": "A", "fact": "f", "source_quote": ""},\n'
           '{"type": "npc", "subject": "B", "fact": "f",},\n'
           '{"type": "npc", "subject": "C", "fact": "f", "source_quote": ""}]')
    facts = ef.parse_facts_block(raw)
    assert [f["subject"] for f in facts] == ["A", "C"]


def test_parse_no_array_raises():
    with pytest.raises(ValueError):
        ef.parse_facts_block("Sorry, I cannot extract facts from this text.")


def test_parse_repairs_unescaped_dialogue_quotes():
    # Real failure from runs/s1: dialogue copied into source_quote with bare
    # quotes. The bare quote flips string-parity, so per-object salvage also
    # recovers nothing — only the escape-repair retry saves the chunk.
    raw = (
        '[\n'
        '  {\n'
        '    "type": "npc",\n'
        '    "subject": "Grygum",\n'
        '    "fact": "Grygum is relieved.",\n'
        '    "source_quote": "Well, that saves me money on potions," '
        'said Grygum, relieved."\n'
        '  },\n'
        '  {\n'
        '    "type": "npc",\n'
        '    "subject": "Queenie",\n'
        '    "fact": "Queenie woke around eight.",\n'
        '    "source_quote": "She woke from her afternoon nap around eight"\n'
        '  }\n'
        ']'
    )
    facts = ef.parse_facts_block(raw)
    assert [f["subject"] for f in facts] == ["Grygum", "Queenie"]
    assert facts[0]["source_quote"] == (
        'Well, that saves me money on potions," said Grygum, relieved.'
    )


def test_repair_leaves_valid_lines_untouched():
    raw = '[{"type": "npc", "subject": "Daz", "fact": "f", "source_quote": ""}]'
    assert ef._repair_unescaped_quotes(raw) == raw


# ── verify_quotes ────────────────────────────────────────────────────────────

def test_verify_quotes_flags_each_failure_mode():
    chunk = "Daz crept into the vault.\nGrygum counted his coins twice."
    facts = [
        _fact("a") | {"source_quote": "crept into the vault"},      # verbatim
        _fact("b") | {"source_quote": "Daz crept into the vault. Grygum"},
        _fact("c") | {"source_quote": "Daz snuck into the vault"},  # paraphrase
        _fact("d") | {"source_quote": "Daz crept ... his coins"},   # stitched
        _fact("e") | {"source_quote": ""},                          # empty
    ]
    ef.verify_quotes(facts, chunk)
    # b spans the newline — only the whitespace-normalized fallback passes it
    assert [f["quote_verified"] for f in facts] == [True, True, False, False, False]


def test_extract_one_chunk_caches_quote_verified(tmp_path):
    chunk = "Daz crept into the vault."
    raw = json.dumps([
        _fact("real") | {"source_quote": "crept into the vault"},
        _fact("fake") | {"source_quote": "Daz boldly strode in"},
    ])
    out = tmp_path / "facts_001.json"
    facts, err = ef.extract_one_chunk(lambda c: raw, chunk, out)
    assert err is None
    cached = json.loads(out.read_text())
    assert [f["quote_verified"] for f in cached] == [True, False]


# ── run_parallel ─────────────────────────────────────────────────────────────

def test_parallel_results_map_to_chunk_index(tmp_path):
    # All three chunks genuinely in flight at once (barrier), completing in
    # reverse order — results must still map each index to its own chunk.
    chunks = ["alpha", "bravo", "charlie"]
    barrier = threading.Barrier(3)

    def call_fn(chunk: str) -> str:
        barrier.wait(timeout=10)
        return _raw_for(chunk)

    results, failures = ef.run_parallel(chunks, tmp_path, call_fn, parallel=3)
    assert failures == []
    assert {i: results[i][0]["fact"] for i in results} == \
        {1: "alpha", 2: "bravo", 3: "charlie"}
    for i in (1, 2, 3):
        cached = json.loads((tmp_path / f"facts_{i:03d}.json").read_text())
        assert cached == results[i]
    assert not list(tmp_path.glob("*.tmp.*"))


def test_parallel_skips_cached_chunks(tmp_path):
    seeded = [_fact("pre-seeded")]
    (tmp_path / "facts_002.json").write_text(json.dumps(seeded))
    called = []

    def call_fn(chunk: str) -> str:
        called.append(chunk)
        return _raw_for(chunk)

    results, failures = ef.run_parallel(["a", "b", "c"], tmp_path, call_fn,
                                        parallel=2)
    assert failures == []
    assert sorted(called) == ["a", "c"]
    # Cache hits pass through, gaining the quote_verified stamp (empty
    # source_quote -> False)
    assert results[2] == [seeded[0] | {"quote_verified": False}]


def test_parallel_failure_does_not_cancel_others(tmp_path):
    def call_fn(chunk: str) -> str:
        if chunk == "bad":
            return "not json at all"
        return _raw_for(chunk)

    results, failures = ef.run_parallel(["ok1", "bad", "ok2"], tmp_path,
                                        call_fn, parallel=3)
    assert [i for i, _ in failures] == [2]
    assert (tmp_path / "facts_002.raw.txt").read_text() == "not json at all"
    # the good chunks finished and cached despite the failure
    assert (tmp_path / "facts_001.json").exists()
    assert (tmp_path / "facts_003.json").exists()
    assert set(results) == {1, 3}

    # hand-fix the bad chunk, re-run: nothing is called, everything resumes
    (tmp_path / "facts_002.json").write_text(json.dumps([_fact("fixed")]))
    called = []
    results, failures = ef.run_parallel(
        ["ok1", "bad", "ok2"], tmp_path,
        lambda c: called.append(c) or _raw_for(c), parallel=3)
    assert failures == [] and called == []
    assert results[2][0]["fact"] == "fixed"


def test_corrupt_cache_treated_as_miss(tmp_path):
    (tmp_path / "facts_001.json").write_text('[{"torn": ')
    results, failures = ef.run_parallel(["a"], tmp_path, _raw_for, parallel=2)
    assert failures == []
    assert results[1][0]["fact"] == "a"
    assert json.loads((tmp_path / "facts_001.json").read_text()) == results[1]


def test_parallel_exceeding_chunk_count(tmp_path):
    results, failures = ef.run_parallel(["only"], tmp_path, _raw_for,
                                        parallel=8)
    assert failures == [] and results[1][0]["fact"] == "only"


def test_all_cached_skips_pool(tmp_path):
    for i in (1, 2):
        (tmp_path / f"facts_{i:03d}.json").write_text(json.dumps([_fact(str(i))]))

    def boom(chunk: str) -> str:
        raise AssertionError("call_fn must not run when everything is cached")

    results, failures = ef.run_parallel(["a", "b"], tmp_path, boom, parallel=4)
    assert failures == [] and set(results) == {1, 2}


# ── helpers ──────────────────────────────────────────────────────────────────

def test_atomic_write_leaves_no_tmp(tmp_path):
    target = tmp_path / "out.json"
    ef._atomic_write_text(target, "[]")
    assert target.read_text() == "[]"
    assert list(tmp_path.iterdir()) == [target]


def test_load_cached_missing_and_corrupt(tmp_path):
    assert ef._load_cached(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{torn")
    assert ef._load_cached(bad) is None


def test_extract_one_chunk_failure_writes_raw(tmp_path):
    out = tmp_path / "facts_001.json"
    facts, err = ef.extract_one_chunk(lambda c: "garbage", "chunk", out)
    assert facts is None and "facts_001.raw.txt" in err
    assert not out.exists()


# ── CLI (no server: every chunk pre-seeded) ──────────────────────────────────

def test_cli_parallel_fully_cached(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Some session text.\n")
    extract_dir = tmp_path / "cache"
    extract_dir.mkdir()
    seeded = [_fact("seeded")]
    (extract_dir / "facts_001.json").write_text(json.dumps(seeded))
    out = tmp_path / "facts.json"

    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc),
         "--output", str(out), "--extract-dir", str(extract_dir),
         "--parallel", "2",
         "--dgx-endpoint", "http://127.0.0.1:1"],  # unreachable: must not be hit
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text()) == [seeded[0] | {"quote_verified": False}]


def test_cli_rejects_parallel_zero(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("text\n")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc),
         "--output", str(tmp_path / "f.json"), "--parallel", "0"],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "must be >= 1" in r.stderr
