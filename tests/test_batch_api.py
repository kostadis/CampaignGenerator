"""Tests for the Message Batches API helpers in campaignlib + scene_extract.

These tests pin the request shape, the cache_control wiring, and the
on-disk equivalence between live and batch paths so that switching
between them produces byte-identical extraction files.
"""

import json
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
    with patch.object(campaignlib, "stream_api", return_value=fake_text):
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
