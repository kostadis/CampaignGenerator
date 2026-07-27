"""Tests for vtt_voice_compare.py's --batch routing (spec 004).

vtt_voice_compare.py is a single-call CLI (contract's "Single-call CLIs"
group): with --batch, its one analysis stream_api call must route through
run_single_batch instead — same system/user/model, and the *same max_tokens
stream_api would have defaulted to* (8096), not run_single_batch's own
default (8192), since vtt_voice_compare never passed max_tokens to
stream_api before. A RuntimeError from run_single_batch (item did not
succeed) must exit non-zero. The default (no --batch) path is unaffected
(FR-011).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc.vtt_voice_compare as vtt_voice_compare  # noqa: E402


VTT_SAMPLE = """WEBVTT

1
00:00:00.000 --> 00:00:05.000
Gabe: I draw my sword and step forward.

2
00:00:05.000 --> 00:00:07.000
GM: Roll for initiative.
"""


def _make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    vtt_path = tmp_path / "session.vtt"
    vtt_path.write_text(VTT_SAMPLE, encoding="utf-8")
    voice_path = tmp_path / "zalthir_voice.md"
    voice_path.write_text("# Zalthir voice\n\nCalm and precise.\n", encoding="utf-8")
    return vtt_path, voice_path


def test_vtt_voice_compare_batch_routes_through_run_single_batch(tmp_path, monkeypatch):
    vtt_path, voice_path = _make_inputs(tmp_path)

    calls = []

    def fake_run_single_batch(client, *, system, user, model, max_tokens=8192,
                              cache_system=False):
        calls.append({"system": system, "user": user, "model": model,
                      "max_tokens": max_tokens, "cache_system": cache_system})
        return "## Recommended Additions\n\nNone."

    def fail_if_called(*a, **kw):
        raise AssertionError("stream_api must not be called when --batch is set")

    monkeypatch.setattr(vtt_voice_compare, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(vtt_voice_compare, "run_single_batch", fake_run_single_batch)
    monkeypatch.setattr(vtt_voice_compare, "stream_api", fail_if_called)

    monkeypatch.setattr(sys, "argv", [
        "vtt_voice_compare.py", str(vtt_path),
        "--player", "Gabe",
        "--voice-file", str(voice_path),
        "--no-log",
        "--batch",
    ])
    vtt_voice_compare.main()

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 8096
    assert calls[0]["cache_system"] is False


def test_vtt_voice_compare_batch_item_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    vtt_path, voice_path = _make_inputs(tmp_path)

    def fake_run_single_batch(client, **kw):
        raise RuntimeError(
            "batch item 'single' did not succeed: status=errored error=boom"
        )

    monkeypatch.setattr(vtt_voice_compare, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(vtt_voice_compare, "run_single_batch", fake_run_single_batch)

    monkeypatch.setattr(sys, "argv", [
        "vtt_voice_compare.py", str(vtt_path),
        "--player", "Gabe",
        "--voice-file", str(voice_path),
        "--no-log",
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        vtt_voice_compare.main()
    assert exc_info.value.code != 0
    assert "Error: batch item failed" in capsys.readouterr().err


def test_vtt_voice_compare_default_path_uses_stream_api(tmp_path, monkeypatch):
    """FR-011 regression guard: default (no --batch) path must be unaffected
    by the batch wiring."""
    vtt_path, voice_path = _make_inputs(tmp_path)

    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append({"system": system, "user": user, "model": model, **kwargs})
        return "## Recommended Additions\n\nNone."

    monkeypatch.setattr(vtt_voice_compare, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(vtt_voice_compare, "stream_api", fake_stream_api)

    monkeypatch.setattr(sys, "argv", [
        "vtt_voice_compare.py", str(vtt_path),
        "--player", "Gabe",
        "--voice-file", str(voice_path),
        "--no-log",
    ])
    vtt_voice_compare.main()

    assert len(calls) == 1
