"""Tests for enhance_summary.py's --batch alignment (spec 004).

Plain `--batch` (no --submit-only/--collect) must now BLOCK: submit + poll +
collect + write in one invocation via campaignlib.run_batch, exit non-zero
on item failure, and never leave a sidecar file behind. --submit-only /
--collect keep their pre-existing detached, sidecar-based behavior
unchanged (grandfathered, FR-012) — mirrors scene_extract.py's Phase 3
conversion (tests/test_scene_extract.py).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib  # noqa: E402
from session_doc import enhance_summary  # noqa: E402


VTT_SAMPLE = """WEBVTT

1
00:00:00.000 --> 00:00:02.000
Kostadis: Roll for initiative.
"""

GMASSIST_SAMPLE = "## Summary\n\nThe party rolled for initiative.\n"


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    vtt_path = tmp_path / "session.vtt"
    vtt_path.write_text(VTT_SAMPLE, encoding="utf-8")
    gm_path = tmp_path / "gm-assist.md"
    gm_path.write_text(GMASSIST_SAMPLE, encoding="utf-8")
    return vtt_path, gm_path


class FakeRunBatch:
    def __init__(self, record: dict):
        self.calls = []
        self._record = record

    def __call__(self, client, requests, **kwargs):
        self.calls.append({"requests": requests, "kwargs": kwargs})
        return {r["custom_id"]: self._record for r in requests}


def test_batch_routes_through_run_batch_and_writes_output_no_sidecar(monkeypatch, tmp_path):
    vtt_path, gm_path = _write_inputs(tmp_path)
    out_path = tmp_path / "session-summary.md"

    fake_run_batch = FakeRunBatch({
        "status": "succeeded", "text": "[enriched summary]",
        "stop_reason": "end_turn", "error": None, "usage": {"output_tokens": 42},
    })
    monkeypatch.setattr(enhance_summary, "run_batch", fake_run_batch)
    monkeypatch.setattr(enhance_summary, "client_from_args", lambda *a, **kw: object())

    monkeypatch.setattr(sys, "argv", [
        "enhance_summary", str(vtt_path),
        "--gmassist", str(gm_path),
        "--output", str(out_path),
        "--batch", "--no-log",
    ])
    enhance_summary.main()

    assert len(fake_run_batch.calls) == 1
    assert fake_run_batch.calls[0]["requests"][0]["custom_id"] == enhance_summary.CUSTOM_ID
    assert out_path.exists()
    assert "[enriched summary]" in out_path.read_text(encoding="utf-8")

    sidecar = enhance_summary._sidecar_path(out_path)
    assert not sidecar.exists()  # blocking path never writes a sidecar


def test_batch_item_failure_exits_nonzero_no_output_no_sidecar(monkeypatch, tmp_path, capsys):
    vtt_path, gm_path = _write_inputs(tmp_path)
    out_path = tmp_path / "session-summary.md"

    fake_run_batch = FakeRunBatch({
        "status": "errored", "text": None,
        "stop_reason": None, "error": "boom", "usage": None,
    })
    monkeypatch.setattr(enhance_summary, "run_batch", fake_run_batch)
    monkeypatch.setattr(enhance_summary, "client_from_args", lambda *a, **kw: object())

    monkeypatch.setattr(sys, "argv", [
        "enhance_summary", str(vtt_path),
        "--gmassist", str(gm_path),
        "--output", str(out_path),
        "--batch", "--no-log",
    ])
    with pytest.raises(SystemExit) as exc_info:
        enhance_summary.main()
    assert exc_info.value.code != 0
    assert not out_path.exists()
    assert not enhance_summary._sidecar_path(out_path).exists()
    stderr = capsys.readouterr().err
    assert f"FAILED {enhance_summary.CUSTOM_ID}" in stderr


def test_submit_only_and_collect_unchanged(monkeypatch, tmp_path):
    """--submit-only / --collect keep their existing sidecar-based detached
    behavior — unaffected by the plain --batch rewrite (FR-012)."""
    vtt_path, gm_path = _write_inputs(tmp_path)
    out_path = tmp_path / "session-summary.md"

    def fake_submit_batch(client, requests):
        return "batch-123"

    monkeypatch.setattr(enhance_summary, "submit_batch", fake_submit_batch)
    monkeypatch.setattr(enhance_summary, "client_from_args", lambda *a, **kw: object())

    monkeypatch.setattr(sys, "argv", [
        "enhance_summary", str(vtt_path),
        "--gmassist", str(gm_path),
        "--output", str(out_path),
        "--batch", "--submit-only", "--no-log",
    ])
    enhance_summary.main()

    sidecar = enhance_summary._sidecar_path(out_path)
    assert sidecar.exists()
    payload = campaignlib.read_batch_sidecar(sidecar)
    assert payload["batch_id"] == "batch-123"
    assert payload["kind"] == enhance_summary.SIDECAR_KIND
    assert not out_path.exists()  # submit-only never writes output

    # ── --collect: reads the sidecar, polls, writes output, removes sidecar ──
    def fake_poll_batch(client, batch_id, interval=10, on_tick=None):
        assert batch_id == "batch-123"

    def fake_collect_batch(client, batch_id):
        assert batch_id == "batch-123"
        return {
            enhance_summary.CUSTOM_ID: {
                "status": "succeeded", "text": "[collected enriched summary]",
                "stop_reason": "end_turn", "error": None, "usage": None,
            }
        }

    monkeypatch.setattr(enhance_summary, "poll_batch", fake_poll_batch)
    monkeypatch.setattr(enhance_summary, "collect_batch", fake_collect_batch)

    monkeypatch.setattr(sys, "argv", [
        "enhance_summary",
        "--output", str(out_path),
        "--batch", "--collect", "--no-log",
    ])
    enhance_summary.main()

    assert out_path.exists()
    assert "[collected enriched summary]" in out_path.read_text(encoding="utf-8")
    assert not sidecar.exists()  # removed after a successful collect
