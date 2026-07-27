"""Tests for sd_consistency.py's --batch routing (spec 004).

sd_consistency.py is a single-call CLI (contract's "Single-call CLIs" group):
with --batch, its one Pass 1 stream_api call must route through
run_single_batch instead — same system/user/model, and the *same max_tokens
stream_api would have defaulted to* (8096), not run_single_batch's own
default (8192), since sd_consistency never passed max_tokens to stream_api
before. A RuntimeError from run_single_batch (item did not succeed) must
exit non-zero and not write the report. The default (no --batch) path is
unaffected (FR-011).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc.sd_consistency as sd_consistency  # noqa: E402


def _make_inputs(tmp_path: Path) -> tuple[Path, Path]:
    recap = tmp_path / "recap.md"
    recap.write_text("The party did things.", encoding="utf-8")
    context = tmp_path / "campaign_state.md"
    context.write_text("Some campaign state.", encoding="utf-8")
    return recap, context


def test_sd_consistency_batch_routes_through_run_single_batch(tmp_path, monkeypatch):
    recap, context = _make_inputs(tmp_path)
    out_path = tmp_path / "consistency_report.md"

    calls = []

    def fake_run_single_batch(client, *, system, user, model, max_tokens=8192,
                              cache_system=False):
        calls.append({"system": system, "user": user, "model": model,
                      "max_tokens": max_tokens, "cache_system": cache_system})
        return "No issues found."

    def fail_if_called(*a, **kw):
        raise AssertionError("stream_api must not be called when --batch is set")

    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_consistency, "run_single_batch", fake_run_single_batch)
    monkeypatch.setattr(sd_consistency, "stream_api", fail_if_called)

    monkeypatch.setattr(sys, "argv", [
        "sd_consistency.py", str(recap),
        "--context", str(context),
        "--out", str(out_path),
        "--batch",
    ])
    sd_consistency.main()

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 8096
    assert calls[0]["cache_system"] is False
    assert out_path.exists()
    assert "No issues found." in out_path.read_text(encoding="utf-8")


def test_sd_consistency_batch_item_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    recap, context = _make_inputs(tmp_path)
    out_path = tmp_path / "consistency_report.md"

    def fake_run_single_batch(client, **kw):
        raise RuntimeError(
            "batch item 'single' did not succeed: status=errored error=boom"
        )

    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_consistency, "run_single_batch", fake_run_single_batch)

    monkeypatch.setattr(sys, "argv", [
        "sd_consistency.py", str(recap),
        "--context", str(context),
        "--out", str(out_path),
        "--batch",
    ])
    with pytest.raises(SystemExit) as exc_info:
        sd_consistency.main()
    assert exc_info.value.code != 0
    assert not out_path.exists()
    assert "Error: batch item failed" in capsys.readouterr().err


def test_sd_consistency_default_path_uses_stream_api(tmp_path, monkeypatch):
    """FR-011 regression guard: default (no --batch) path must be unaffected
    by the batch wiring."""
    recap, context = _make_inputs(tmp_path)
    out_path = tmp_path / "consistency_report.md"

    calls = []

    def fake_stream_api(client, system, user, model, **kwargs):
        calls.append({"system": system, "user": user, "model": model, **kwargs})
        return "No issues found."

    monkeypatch.setattr(sd_consistency, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_consistency, "stream_api", fake_stream_api)

    monkeypatch.setattr(sys, "argv", [
        "sd_consistency.py", str(recap),
        "--context", str(context),
        "--out", str(out_path),
    ])
    sd_consistency.main()

    assert len(calls) == 1
    assert calls[0].get("silent") is True
    assert out_path.exists()
