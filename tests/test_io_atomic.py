"""Tests for campaignlib.io_atomic — the PID-suffixed tmp + os.replace helper.

Promoted from pipelines/ensemble/extract_facts.py (T002, spec
004-claude-api-batch) so future batch-result writers can reuse the same
crash-safe write extract_facts already relied on. Kept distinct from
campaignlib.util.atomic_write_text (fixed ``.tmp`` suffix) — see the module
docstring for why the two aren't merged.
"""

import os
from pathlib import Path
from unittest.mock import patch

from campaignlib.io_atomic import atomic_write_text


def test_atomic_write_text_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "out.json"
    atomic_write_text(target, "[]")
    assert target.read_text() == "[]"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_text_overwrites_existing_content(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_tmp_name_is_pid_suffixed(tmp_path):
    """Two processes racing on the same destination must not share a tmp
    filename — that's the whole reason this isn't the fixed-suffix
    campaignlib.util.atomic_write_text (see io_atomic.py's module docstring:
    the ensemble's speculative re-execution terminates a losing duplicate
    process, and only a unique-per-writer tmp name makes that harmless).
    """
    target = tmp_path / "out.txt"
    seen_tmp_names = []
    real_replace = os.replace

    def spy_replace(src, dst):
        seen_tmp_names.append(Path(src).name)
        real_replace(src, dst)

    with patch("campaignlib.io_atomic.os.replace", side_effect=spy_replace), \
         patch("campaignlib.io_atomic.os.getpid", return_value=4242):
        atomic_write_text(target, "content")

    assert seen_tmp_names == [f"{target.name}.tmp.4242"]
