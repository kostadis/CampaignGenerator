"""Tests for pipelines/rlm/query.py's --batch MAP/REDUCE wiring.

query.py runs a per-chunk MAP (independent stream_api calls, each filtering
its own chunk for relevance) then a single REDUCE call that depends on every
MAP output. With --batch, the MAP fans out as one grouped run_batch call and
the REDUCE goes through run_single_batch. This file pins:
  - the request shape (one request per chunk, custom_id per chunk index)
  - map-output ordering into the reduce input (chunk order, not dict order)
  - partial-failure handling (FAILED lines + sys.exit(1), reduce never runs)
  - the default (no --batch) path is unaffected by the batch plumbing
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaignlib import chunk_text  # noqa: E402
from pipelines.rlm import query  # noqa: E402


# ── Fakes ──────────────────────────────────────────────────────────────────

class FakeStreamAPI:
    """Callable stub for query.stream_api. Returns scripted responses in
    order, or a non-NONE stub string once the script runs out — mirrors
    FakeStreamAPI in test_distill.py / test_campaignlib_pipeline.py."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = list(responses) if responses else None

    def __call__(self, client, system, user, model, *args, **kwargs):
        self.calls.append({"system": system, "user": user, "model": model})
        if self._responses:
            return self._responses.pop(0)
        return f"[stub-{len(self.calls)}]"


@pytest.fixture
def fake_stream_api(monkeypatch):
    fake = FakeStreamAPI()
    monkeypatch.setattr(query, "stream_api", fake)
    return fake


class FakeRunBatch:
    """Callable stub for query.run_batch: records the requests it was
    called with and returns a results dict keyed by custom_id.

    `text_by_id` supplies per-chunk response text (default: f"hit-{cid}");
    `status_by_id` overrides specific custom_ids to simulate partial
    failure (error message is always "boom", matching the established
    FakeRunBatch convention in tests/test_campaignlib_pipeline.py).
    """

    def __init__(self, text_by_id=None, status_by_id=None):
        self.calls = []
        self._text_by_id = text_by_id or {}
        self._status_by_id = status_by_id or {}

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        results = {}
        for r in requests:
            cid = r["custom_id"]
            status = self._status_by_id.get(cid, "succeeded")
            if status == "succeeded":
                text = self._text_by_id.get(cid, f"hit-{cid}")
                results[cid] = {"status": "succeeded", "text": text,
                                "stop_reason": "end_turn", "error": None, "usage": None}
            else:
                results[cid] = {"status": status, "text": None,
                                "stop_reason": None, "error": "boom", "usage": None}
        return results


@pytest.fixture
def fake_run_batch(monkeypatch):
    fake = FakeRunBatch()
    monkeypatch.setattr(query, "run_batch", fake)
    return fake


class FakeRunSingleBatch:
    """Callable stub for query.run_single_batch."""

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
    monkeypatch.setattr(query, "run_single_batch", fake)
    return fake


@pytest.fixture
def fake_batch_entry_points(monkeypatch):
    run_batch = FakeRunBatch()
    run_single_batch = FakeRunSingleBatch()
    monkeypatch.setattr(query, "run_batch", run_batch)
    monkeypatch.setattr(query, "run_single_batch", run_single_batch)
    monkeypatch.setattr(query, "client_from_args", lambda *a, **kw: None)
    return run_batch, run_single_batch


def _long_text(n_paragraphs: int = 4) -> str:
    return "\n\n".join("paragraph " + ("x " * 200) for _ in range(n_paragraphs))


def _three_chunk_text() -> str:
    """Text engineered to split into exactly 3 chunks at chunk_size=150 —
    each 100-char paragraph is short enough to be its own chunk, but any two
    together exceed the chunk size (verified against campaignlib.chunk_text)."""
    para = "y" * 100
    text = "\n\n".join([para, para, para])
    assert len(chunk_text(text, 150)) == 3
    return text


# ── run_query_batch: request shape ────────────────────────────────────────

def test_batch_map_submits_one_request_per_chunk_with_expected_custom_ids(fake_run_batch):
    text = _long_text()
    query.run_query_batch(client=None, text=text, query="q", chunk_size=500, model="m")

    assert len(fake_run_batch.calls) == 1  # one grouped MAP call, not N serial ones
    requests = fake_run_batch.calls[0]["requests"]
    assert len(requests) >= 2  # the long text must actually split into >1 chunk
    assert [r["custom_id"] for r in requests] == [
        f"chunk_{i:03d}" for i in range(1, len(requests) + 1)
    ]
    assert all(r["params"]["model"] == "m" for r in requests)


# ── run_query_batch: map-output ordering + NONE filtering ────────────────

def test_batch_map_returns_hits_in_chunk_order_filtering_none(monkeypatch):
    text = _three_chunk_text()
    fake = FakeRunBatch(text_by_id={
        "chunk_001": "first hit",
        "chunk_002": "NONE",
        "chunk_003": "third hit",
    })
    monkeypatch.setattr(query, "run_batch", fake)

    hits = query.run_query_batch(client=None, text=text, query="q", chunk_size=150, model="m")
    assert hits == ["first hit", "third hit"]


def test_batch_map_preserves_chunk_order_even_if_results_dict_is_reordered(monkeypatch):
    """collect_batch's dict is keyed by custom_id but not guaranteed to
    preserve submission order (results stream back as the batch finishes
    them) — run_query_batch must index results by chunk position, not by
    dict iteration order, so the reduce input is deterministic."""
    text = _three_chunk_text()

    class ReorderedRunBatch(FakeRunBatch):
        def __call__(self, client, requests, **kwargs):
            results = super().__call__(client, requests, **kwargs)
            return dict(reversed(list(results.items())))

    fake = ReorderedRunBatch(text_by_id={
        "chunk_001": "first",
        "chunk_002": "second",
        "chunk_003": "third",
    })
    monkeypatch.setattr(query, "run_batch", fake)

    hits = query.run_query_batch(client=None, text=text, query="q", chunk_size=150, model="m")
    assert hits == ["first", "second", "third"]


# ── run_query_batch: partial failure ──────────────────────────────────────

def test_batch_map_partial_failure_prints_failed_line_and_exits_nonzero(monkeypatch, capsys):
    text = "\n\n".join("para " + ("x " * 300) for _ in range(3))
    fake = FakeRunBatch(status_by_id={"chunk_002": "errored"})
    monkeypatch.setattr(query, "run_batch", fake)

    with pytest.raises(SystemExit) as exc_info:
        query.run_query_batch(client=None, text=text, query="q", chunk_size=500, model="m")

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "FAILED chunk_002: errored boom" in err


def test_batch_map_all_failed_reports_every_custom_id(monkeypatch, capsys):
    text = "\n\n".join("para " + ("x " * 300) for _ in range(3))
    fake = FakeRunBatch(status_by_id={
        "chunk_001": "errored", "chunk_002": "errored", "chunk_003": "errored",
    })
    monkeypatch.setattr(query, "run_batch", fake)

    with pytest.raises(SystemExit):
        query.run_query_batch(client=None, text=text, query="q", chunk_size=500, model="m")

    err = capsys.readouterr().err
    assert "FAILED chunk_001:" in err
    assert "FAILED chunk_002:" in err
    assert "FAILED chunk_003:" in err


# ── run_synthesize_batch: routes through run_single_batch ─────────────────

def test_synthesize_batch_routes_through_run_single_batch(fake_run_single_batch):
    result = query.run_synthesize_batch(client=None, hits=["a", "b"], query="q", model="m")
    assert result == "[batch-synth-result]"
    assert len(fake_run_single_batch.calls) == 1
    assert "a" in fake_run_single_batch.calls[0]["user"]
    assert "b" in fake_run_single_batch.calls[0]["user"]


# ── main(): end-to-end batch wiring ───────────────────────────────────────

def test_main_batch_flag_routes_map_and_reduce_through_batch_entry_points(
    monkeypatch, fake_batch_entry_points, tmp_path
):
    run_batch, run_single_batch = fake_batch_entry_points
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content " * 50, encoding="utf-8")
    output = tmp_path / "answer.md"

    monkeypatch.setattr(sys, "argv", [
        "query.py", str(input_file), "some query",
        "--output", str(output),
        "--batch",
    ])
    query.main()

    assert len(run_batch.calls) == 1         # one grouped MAP call
    assert len(run_single_batch.calls) == 1  # one REDUCE call
    assert output.exists()
    assert "[batch-synth-result]" in output.read_text(encoding="utf-8")


def test_main_batch_map_failure_exits_before_reduce_runs(monkeypatch, tmp_path):
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content " * 50, encoding="utf-8")

    run_single_batch = FakeRunSingleBatch()
    run_batch = FakeRunBatch(status_by_id={"chunk_001": "errored"})
    monkeypatch.setattr(query, "run_batch", run_batch)
    monkeypatch.setattr(query, "run_single_batch", run_single_batch)
    monkeypatch.setattr(query, "client_from_args", lambda *a, **kw: None)

    monkeypatch.setattr(sys, "argv", [
        "query.py", str(input_file), "some query",
        "--batch",
    ])
    with pytest.raises(SystemExit):
        query.main()

    assert len(run_single_batch.calls) == 0  # reduce never called on map failure


# ── Default (no --batch) path is unaffected ───────────────────────────────

def test_default_no_batch_path_uses_stream_api_for_both_map_and_reduce(
    monkeypatch, fake_stream_api, tmp_path
):
    """FR-011-style regression guard: adding --batch plumbing must not change
    the default (no --batch) path."""
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")
    output = tmp_path / "answer.md"

    monkeypatch.setattr(query, "client_from_args", lambda *a, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "query.py", str(input_file), "some query",
        "--output", str(output),
    ])
    query.main()

    assert len(fake_stream_api.calls) == 2  # 1 MAP chunk + 1 REDUCE call
    assert output.exists()


def test_default_no_batch_path_never_touches_run_batch(
    monkeypatch, fake_stream_api, fake_batch_entry_points, tmp_path
):
    run_batch, run_single_batch = fake_batch_entry_points
    input_file = tmp_path / "summaries.md"
    input_file.write_text("some session content", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["query.py", str(input_file), "some query"])
    query.main()

    assert len(run_batch.calls) == 0
    assert len(run_single_batch.calls) == 0
    assert len(fake_stream_api.calls) == 2
