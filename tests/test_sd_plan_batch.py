"""Tests for sd_plan.py's --batch routing (spec 004).

sd_plan.py is a single-call CLI (contract's "Single-call CLIs" group): with
--batch, its one Pass 3 stream_api call must route through run_single_batch
instead — same system/user/model, and the *same max_tokens stream_api would
have defaulted to* (8096), not run_single_batch's own default (8192), since
sd_plan never passed max_tokens to stream_api before. A RuntimeError from
run_single_batch (item did not succeed) must exit non-zero and not write
plan.md. The default (no --batch) path is unaffected — see
tests/test_prep.py::test_sd_plan_writes_plan_md for that regression guard,
left untouched.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import session_doc.sd_plan as sd_plan  # noqa: E402


def _make_scene_extractions(sx_dir: Path) -> None:
    sx_dir.mkdir(parents=True, exist_ok=True)
    (sx_dir / "01_stone_giants.md").write_text(
        "---\nscene: The Stone Giants\n---\n\nVukradin stared down the giants.\n",
        encoding="utf-8",
    )


def test_sd_plan_batch_routes_through_run_single_batch(tmp_path, monkeypatch):
    sx_dir = tmp_path / "scene_extractions"
    _make_scene_extractions(sx_dir)
    out_path = tmp_path / "plan.md"
    fake_plan = (
        "## Section 1\n"
        "narrator: Vukradin\n"
        "chunks: 1-1\n"
        "scene: The Stone Giants\n"
        "focus: holding the line against the giants\n"
    )

    calls = []

    def fake_run_single_batch(client, *, system, user, model, max_tokens=8192,
                              cache_system=False):
        calls.append({"system": system, "user": user, "model": model,
                      "max_tokens": max_tokens, "cache_system": cache_system})
        return fake_plan

    def fail_if_called(*a, **kw):
        raise AssertionError("stream_api must not be called when --batch is set")

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "run_single_batch", fake_run_single_batch)
    monkeypatch.setattr(sd_plan, "stream_api", fail_if_called)

    monkeypatch.setattr(
        sys, "argv",
        [
            "sd_plan.py",
            "--scene-extractions", str(sx_dir),
            "--characters", "Vukradin",
            "--out", str(out_path),
            "--batch",
        ],
    )

    sd_plan.main()

    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 8096
    assert calls[0]["cache_system"] is False
    assert out_path.exists()
    assert "narrator: Vukradin" in out_path.read_text(encoding="utf-8")


def test_sd_plan_batch_item_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    sx_dir = tmp_path / "scene_extractions"
    _make_scene_extractions(sx_dir)
    out_path = tmp_path / "plan.md"

    def fake_run_single_batch(client, **kw):
        raise RuntimeError(
            "batch item 'single' did not succeed: status=errored error=boom"
        )

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "run_single_batch", fake_run_single_batch)

    monkeypatch.setattr(
        sys, "argv",
        [
            "sd_plan.py",
            "--scene-extractions", str(sx_dir),
            "--characters", "Vukradin",
            "--out", str(out_path),
            "--batch",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        sd_plan.main()
    assert exc_info.value.code != 0
    assert not out_path.exists()
    assert "Error: batch item failed" in capsys.readouterr().err
