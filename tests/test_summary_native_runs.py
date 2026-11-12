"""The shared run-directory helper: one atomic seam for every summary_native stage."""

from __future__ import annotations

from datetime import datetime, timezone

from pipelines.summary_native import runs


def test_run_stamp_is_second_resolution_utc():
    assert runs.run_stamp(datetime(2026, 1, 2, 3, 4, 5, 999, tzinfo=timezone.utc)) == "20260102T030405Z"


def test_same_stamp_yields_distinct_suffixed_dirs_and_never_reuses(tmp_path):
    root = tmp_path / "state" / "runs"
    a = runs.new_run_dir(root, "20260102T030405Z")
    (a / "record.json").write_text("first")
    b = runs.new_run_dir(root, "20260102T030405Z")
    c = runs.new_run_dir(root, "20260102T030405Z")
    assert [a.name, b.name, c.name] == ["20260102T030405Z", "20260102T030405Z-1", "20260102T030405Z-2"]
    assert (a / "record.json").read_text() == "first" and not any(b.iterdir())


def test_a_different_stamp_gets_the_bare_name(tmp_path):
    runs.new_run_dir(tmp_path, "20260102T030405Z")
    assert runs.new_run_dir(tmp_path, "20260102T030406Z").name == "20260102T030406Z"
