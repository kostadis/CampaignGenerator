"""Tests for the Message Batches API helpers in campaignlib + scene_extract.

These tests pin the request shape, the cache_control wiring, and the
on-disk equivalence between live and batch paths so that switching
between them produces byte-identical extraction files.
"""

import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib


# ── build_batch_request ───────────────────────────────────────────────────────

def test_build_batch_request_shape_with_cache():
    req = campaignlib.build_batch_request(
        custom_id="01_scene",
        system="SYS",
        user="USR",
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        cache_system=True,
    )
    assert req["custom_id"] == "01_scene"
    params = req["params"]
    assert params["model"] == "claude-haiku-4-5-20251001"
    assert params["max_tokens"] == 2048
    # System is wrapped in a single ephemeral cache block — same shape
    # stream_api uses for cache_system=True.
    assert params["system"] == [{
        "type": "text",
        "text": "SYS",
        "cache_control": {"type": "ephemeral"},
    }]
    assert params["messages"] == [{"role": "user", "content": "USR"}]


def test_build_batch_request_no_cache_passes_string_system():
    req = campaignlib.build_batch_request(
        custom_id="x", system="SYS", user="USR",
        model="m", max_tokens=10, cache_system=False,
    )
    assert req["params"]["system"] == "SYS"


def test_build_batch_request_accepts_content_block_list():
    """A vision-style content-block list (e.g. dnd_sheet's) is used directly
    as the user message content — no transformation, no string coercion."""
    blocks = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": "AAAA"}},
        {"type": "text", "text": "Describe this."},
    ]
    req = campaignlib.build_batch_request(
        custom_id="vision", system="SYS", user=blocks, model="m", max_tokens=100,
    )
    assert req["params"]["messages"] == [{"role": "user", "content": blocks}]


# ── format_scene_output ───────────────────────────────────────────────────────

def test_format_scene_output_matches_live_path_layout():
    out = campaignlib.format_scene_output(
        "Scene A", "- bullet 1\n- bullet 2", "MOMENTS BODY"
    )
    assert out.startswith("---\nscene: Scene A\nsource: gmassist\n---\n\n")
    assert "# Scene A\n\n" in out
    assert "## Scene summary (from gm-assist, verbatim)\n\n- bullet 1" in out
    assert out.endswith("## Verbatim moments\n\nMOMENTS BODY\n")


def test_format_scene_output_strips_whitespace_consistently():
    # Body and result whitespace must be normalised so a re-run produces
    # the same bytes regardless of how the LLM formats trailing newlines.
    a = campaignlib.format_scene_output("S", "- b\n", "m\n\n")
    b = campaignlib.format_scene_output("S", "- b", "m")
    assert a == b


def test_live_and_batch_paths_write_byte_identical_files(tmp_path):
    """Live run and a simulated batch run must produce identical files."""
    scenes = [{"name": "Scene A", "body": "- bullet"}]
    fake_text = "MOMENTS BODY"

    # Live path: real run_scene_extraction with stream_api stubbed.
    live_dir = tmp_path / "live"
    with patch.object(campaignlib.scenes, "stream_api", return_value=fake_text):
        campaignlib.run_scene_extraction(
            client=None, vtt_text="VTT", scenes=scenes,
            extract_dir=live_dir, model="m",
            extraction_instruction="{name}|{body}",
        )

    # Batch path: hand-write the same file via format_scene_output.
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    plan = campaignlib.plan_scene_extraction(scenes=scenes, extract_dir=batch_dir)
    p = plan[0]
    (batch_dir / p["path"].name).write_text(
        campaignlib.format_scene_output(p["name"], p["body"], fake_text),
        encoding="utf-8",
    )

    live_file = live_dir / "01_scene_a.md"
    batch_file = batch_dir / "01_scene_a.md"
    assert live_file.read_bytes() == batch_file.read_bytes()


# ── plan_scene_extraction ─────────────────────────────────────────────────────

def test_plan_scene_extraction_assigns_custom_ids_and_paths(tmp_path):
    scenes = [
        {"name": "Farewell to Eldeth", "body": "- a"},
        {"name": "Shadows at Dusk", "body": "- b"},
    ]
    plan = campaignlib.plan_scene_extraction(scenes=scenes, extract_dir=tmp_path)
    assert [p["custom_id"] for p in plan] == [
        "01_farewell_to_eldeth", "02_shadows_at_dusk",
    ]
    assert plan[0]["path"] == tmp_path / "01_farewell_to_eldeth.md"
    assert plan[0]["exists"] is False


def test_plan_scene_extraction_marks_existing_files(tmp_path):
    (tmp_path / "01_scene_a.md").write_text("done", encoding="utf-8")
    plan = campaignlib.plan_scene_extraction(
        scenes=[{"name": "Scene A", "body": ""}, {"name": "Scene B", "body": ""}],
        extract_dir=tmp_path,
    )
    assert plan[0]["exists"] is True
    assert plan[1]["exists"] is False


# ── build_scene_extraction_system_prompt ──────────────────────────────────────

def test_system_prompt_concatenation_matches_live_inline_assembly():
    """The shared builder must emit the same string the live loop does."""
    vtt = "GM: hi"
    prefix = "PREFIX BODY"
    suffix = "SUFFIX BODY"
    built = campaignlib.build_scene_extraction_system_prompt(
        vtt_text=vtt, system_prefix=prefix, system_suffix=suffix,
    )
    # Mirror the inline assembly in run_scene_extraction.
    expected = "\n\n".join([
        prefix.strip(),
        "# TRANSCRIPT (full session VTT)\n\n" + vtt.strip(),
        suffix.strip(),
    ])
    assert built == expected


def test_system_prompt_runs_input_normalizer():
    norm = lambda t: t.replace("Xalvos ", "Xalvosh ")  # alias → canonical
    out = campaignlib.build_scene_extraction_system_prompt(
        vtt_text="Xalvos waved",
        system_prefix="P",
        input_normalizer=norm,
    )
    assert "Xalvosh waved" in out
    assert "Xalvos waved" not in out


# ── submit_batch / poll_batch / collect_batch with mocked client ──────────────

def _fake_client_with_batches(*, batch_id="batch_x", final_status="ended",
                              results_iter=None):
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id=batch_id)
    client.messages.batches.retrieve.return_value = SimpleNamespace(
        id=batch_id,
        processing_status=final_status,
        request_counts=SimpleNamespace(
            processing=0, succeeded=1, errored=0, canceled=0, expired=0,
        ),
    )
    client.messages.batches.cancel.return_value = SimpleNamespace(
        processing_status="canceling")
    if results_iter is not None:
        client.messages.batches.results.return_value = iter(results_iter)
    return client


def test_submit_batch_returns_id_and_calls_create():
    client = _fake_client_with_batches(batch_id="abc123")
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]
    out = campaignlib.submit_batch(client, requests)
    assert out == "abc123"
    client.messages.batches.create.assert_called_once_with(requests=requests)


def test_submit_batch_rejects_empty():
    with pytest.raises(ValueError):
        campaignlib.submit_batch(MagicMock(), [])


def test_poll_batch_exits_when_ended():
    client = _fake_client_with_batches(final_status="ended")
    ticks = []
    out = campaignlib.poll_batch(
        client, "abc", interval=0,
        on_tick=lambda b: ticks.append(b.processing_status),
    )
    assert out.processing_status == "ended"
    assert ticks == ["ended"]


def test_poll_batch_sleeps_between_polls_until_ended():
    """A batch that isn't done on the first retrieve must hit the poll-interval
    sleep (batch.py:119). The interval=0 / first-poll-ended test above skips it,
    which is exactly how the missing `import time` (issue #98) slipped through.
    """
    client = MagicMock()
    in_progress = SimpleNamespace(
        id="b", processing_status="in_progress", request_counts=None)
    ended = SimpleNamespace(
        id="b", processing_status="ended", request_counts=None)
    client.messages.batches.retrieve.side_effect = [in_progress, ended]

    # Patch the real time module's sleep — batch.py looks up `time.sleep` at
    # call time, so a missing `import time` raises NameError here regardless.
    with patch("time.sleep") as mock_sleep:
        out = campaignlib.poll_batch(client, "b", interval=10)

    assert out.processing_status == "ended"
    assert client.messages.batches.retrieve.call_count == 2
    mock_sleep.assert_called_once_with(10)  # the poll interval (batch.py:119)


def test_submit_batch_retries_after_transient_error():
    """A retryable error on create() must back off and retry (batch.py:71),
    which also requires `time` to be importable."""
    httpx = pytest.importorskip("httpx")
    client = MagicMock()
    client.messages.batches.create.side_effect = [
        httpx.ConnectError("transient"),
        SimpleNamespace(id="ok"),
    ]
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]

    with patch("time.sleep") as mock_sleep:
        out = campaignlib.submit_batch(client, requests)

    assert out == "ok"
    assert client.messages.batches.create.call_count == 2
    mock_sleep.assert_called_once_with(10)  # first backoff delay (batch.py:71)


def test_collect_batch_extracts_text_and_usage():
    msg = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="HELLO WORLD")],
        usage=SimpleNamespace(
            input_tokens=10, output_tokens=5,
            cache_creation_input_tokens=0, cache_read_input_tokens=99,
        ),
    )
    entry = SimpleNamespace(
        custom_id="01_scene_a",
        result=SimpleNamespace(type="succeeded", message=msg),
    )
    client = _fake_client_with_batches(results_iter=[entry])
    got = campaignlib.collect_batch(client, "abc")
    assert "01_scene_a" in got
    rec = got["01_scene_a"]
    assert rec["status"] == "succeeded"
    assert rec["text"] == "HELLO WORLD"
    assert rec["usage"]["cache_read_input_tokens"] == 99


def test_collect_batch_records_errored_results():
    err = SimpleNamespace(error=SimpleNamespace(message="rate limited"))
    entry = SimpleNamespace(
        custom_id="02_scene_b",
        result=SimpleNamespace(type="errored", error=err),
    )
    client = _fake_client_with_batches(results_iter=[entry])
    got = campaignlib.collect_batch(client, "abc")
    assert got["02_scene_b"]["status"] == "errored"
    assert "rate limited" in got["02_scene_b"]["error"]
    assert got["02_scene_b"]["text"] is None
    assert got["02_scene_b"]["stop_reason"] is None


def test_collect_batch_carries_stop_reason_for_succeeded():
    msg = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="partial")],
        stop_reason="max_tokens",
        usage=None,
    )
    entry = SimpleNamespace(
        custom_id="c1", result=SimpleNamespace(type="succeeded", message=msg))
    client = _fake_client_with_batches(results_iter=[entry])
    got = campaignlib.collect_batch(client, "abc")
    assert got["c1"]["stop_reason"] == "max_tokens"


# ── run_batch / run_single_batch ──────────────────────────────────────────────

def _succeeded_entry(custom_id: str, text: str, stop_reason: str = "end_turn"):
    msg = SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=None,
    )
    return SimpleNamespace(custom_id=custom_id,
                           result=SimpleNamespace(type="succeeded", message=msg))


def _errored_entry(custom_id: str, message: str):
    err = SimpleNamespace(error=SimpleNamespace(message=message))
    return SimpleNamespace(custom_id=custom_id,
                           result=SimpleNamespace(type="errored", error=err))


def test_run_batch_prints_submission_line(capsys):
    entry = _succeeded_entry("x", "OK")
    client = _fake_client_with_batches(batch_id="b1", results_iter=[entry])
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]

    out = campaignlib.run_batch(client, requests, poll_interval=0)

    err = capsys.readouterr().err
    assert "Batch submitted: b1 (1 requests)" in err
    assert out["x"]["status"] == "succeeded"
    assert out["x"]["text"] == "OK"


def test_run_batch_polls_until_ended_and_prints_progress(capsys):
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="b2")
    in_progress = SimpleNamespace(
        id="b2", processing_status="in_progress",
        request_counts=SimpleNamespace(
            processing=1, succeeded=0, errored=0, canceled=0, expired=0),
    )
    ended = SimpleNamespace(
        id="b2", processing_status="ended",
        request_counts=SimpleNamespace(
            processing=0, succeeded=1, errored=0, canceled=0, expired=0),
    )
    client.messages.batches.retrieve.side_effect = [in_progress, ended]
    client.messages.batches.results.return_value = iter([_succeeded_entry("x", "OK")])
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]

    with patch("time.sleep"):
        out = campaignlib.run_batch(client, requests, poll_interval=10)

    err = capsys.readouterr().err
    assert "[batch b2] processing: 1 succeeded: 0 errored: 0" in err
    assert "elapsed" in err
    assert "[batch b2] processing: 0 succeeded: 1 errored: 0" in err
    assert out["x"]["status"] == "succeeded"


def test_run_batch_sigint_cancels_and_exits(capsys):
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="b3")
    client.messages.batches.retrieve.return_value = SimpleNamespace(
        id="b3", processing_status="in_progress",
        request_counts=SimpleNamespace(
            processing=1, succeeded=0, errored=0, canceled=0, expired=0),
    )
    client.messages.batches.cancel.return_value = SimpleNamespace(
        processing_status="canceling")
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _tick(batch):
        os.kill(os.getpid(), signal.SIGINT)

    try:
        with pytest.raises(SystemExit) as exc_info:
            campaignlib.run_batch(client, requests, poll_interval=0, on_tick=_tick)
    finally:
        # Belt-and-suspenders: don't let a test failure leak a bad handler
        # into the rest of the suite.
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    assert exc_info.value.code == 1
    client.messages.batches.cancel.assert_called_once_with("b3")
    err = capsys.readouterr().err
    assert "Abort received — requesting batch cancellation… status: canceling" in err
    assert signal.getsignal(signal.SIGINT) is prev_sigint
    assert signal.getsignal(signal.SIGTERM) is prev_sigterm


def test_run_batch_sigterm_cancels_and_exits(capsys):
    """SIGTERM matters because the web UI's abort (spec 002) sends graceful
    SIGTERM before force-kill — the cancel must fire on that signal too."""
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="b4")
    client.messages.batches.retrieve.return_value = SimpleNamespace(
        id="b4", processing_status="in_progress",
        request_counts=SimpleNamespace(
            processing=1, succeeded=0, errored=0, canceled=0, expired=0),
    )
    client.messages.batches.cancel.return_value = SimpleNamespace(
        processing_status="canceling")
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _tick(batch):
        os.kill(os.getpid(), signal.SIGTERM)

    try:
        with pytest.raises(SystemExit) as exc_info:
            campaignlib.run_batch(client, requests, poll_interval=0, on_tick=_tick)
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    assert exc_info.value.code == 1
    client.messages.batches.cancel.assert_called_once_with("b4")
    err = capsys.readouterr().err
    assert "Abort received — requesting batch cancellation… status: canceling" in err
    assert signal.getsignal(signal.SIGINT) is prev_sigint
    assert signal.getsignal(signal.SIGTERM) is prev_sigterm


def test_run_batch_abort_reports_cancel_failure(capsys):
    """A best-effort cancel that itself fails must still report and exit —
    the abort path can't be allowed to hang or swallow the failure."""
    client = MagicMock()
    client.messages.batches.create.return_value = SimpleNamespace(id="b5")
    client.messages.batches.retrieve.return_value = SimpleNamespace(
        id="b5", processing_status="in_progress",
        request_counts=SimpleNamespace(
            processing=1, succeeded=0, errored=0, canceled=0, expired=0),
    )
    client.messages.batches.cancel.side_effect = RuntimeError("network down")
    requests = [campaignlib.build_batch_request(
        custom_id="x", system="s", user="u", model="m", max_tokens=10)]
    prev_sigint = signal.getsignal(signal.SIGINT)
    prev_sigterm = signal.getsignal(signal.SIGTERM)

    def _tick(batch):
        os.kill(os.getpid(), signal.SIGTERM)

    try:
        with pytest.raises(SystemExit) as exc_info:
            campaignlib.run_batch(client, requests, poll_interval=0, on_tick=_tick)
    finally:
        signal.signal(signal.SIGINT, prev_sigint)
        signal.signal(signal.SIGTERM, prev_sigterm)

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "status: failed: network down" in err


def test_run_batch_prints_truncation_banner_naming_custom_id(capsys):
    entry = _succeeded_entry("chunk_02", "partial output", stop_reason="max_tokens")
    client = _fake_client_with_batches(batch_id="b6", results_iter=[entry])
    requests = [campaignlib.build_batch_request(
        custom_id="chunk_02", system="s", user="u", model="m", max_tokens=512)]

    out = campaignlib.run_batch(client, requests, poll_interval=0)

    err = capsys.readouterr().err
    assert "!" * 70 in err
    assert "TRUNCATED" in err
    assert "chunk_02" in err
    assert "512" in err
    # Still written — the banner is a loud warning, not a failure.
    assert out["chunk_02"]["status"] == "succeeded"


def test_run_batch_returns_all_items_including_failures(capsys):
    ok = _succeeded_entry("a", "fine")
    bad = _errored_entry("b", "boom")
    client = _fake_client_with_batches(batch_id="b7", results_iter=[ok, bad])
    requests = [
        campaignlib.build_batch_request(
            custom_id="a", system="s", user="u", model="m", max_tokens=10),
        campaignlib.build_batch_request(
            custom_id="b", system="s", user="u", model="m", max_tokens=10),
    ]

    out = campaignlib.run_batch(client, requests, poll_interval=0)

    assert set(out) == {"a", "b"}
    assert out["a"]["status"] == "succeeded"
    assert out["b"]["status"] == "errored"
    assert out["b"]["error"] == "boom"


def test_run_single_batch_returns_text_on_success():
    entry = _succeeded_entry("single", "the answer")
    client = _fake_client_with_batches(batch_id="b8", results_iter=[entry])

    text = campaignlib.run_single_batch(
        client, system="s", user="u", model="m", max_tokens=10)

    assert text == "the answer"


def test_run_single_batch_raises_on_failure():
    entry = _errored_entry("single", "rate limited")
    client = _fake_client_with_batches(batch_id="b9", results_iter=[entry])

    with pytest.raises(RuntimeError, match="rate limited"):
        campaignlib.run_single_batch(client, system="s", user="u", model="m", max_tokens=10)


# ── sidecar round-trip ────────────────────────────────────────────────────────

def test_sidecar_round_trip(tmp_path):
    p = tmp_path / "session-summary.md.batch.json"
    payload = {
        "kind": "enhance_summary",
        "batch_id": "batch_xyz",
        "model": "claude-sonnet-4-6",
        "custom_ids": ["enhance"],
        "submitted_at": campaignlib.utc_now_iso(),
    }
    campaignlib.write_batch_sidecar(p, payload)
    assert p.exists()
    got = campaignlib.read_batch_sidecar(p)
    assert got == payload
    # Pretty-printed JSON, sorted keys — easy to inspect by hand.
    raw = p.read_text(encoding="utf-8")
    assert raw.startswith("{\n")
    assert json.loads(raw) == payload


# ── format_batch_progress ─────────────────────────────────────────────────────

def test_format_batch_progress_summarises_counts():
    batch = SimpleNamespace(
        id="b1",
        processing_status="in_progress",
        request_counts=SimpleNamespace(
            processing=2, succeeded=5, errored=1, canceled=0, expired=0,
        ),
    )
    line = campaignlib.format_batch_progress(batch)
    assert "batch b1" in line
    assert "5/8 succeeded" in line  # 5+1+0+0+2 = 8 total
    assert "2 processing" in line
    assert "1 errored" in line
