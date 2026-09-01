"""Tests for campaignlib.util.atomic_write_text — the single atomic-write helper.

Formerly split across campaignlib.util (fixed ``.tmp`` suffix, mkdir + cleanup)
and campaignlib.io_atomic (PID-suffixed tmp, no mkdir). The two were merged
into one helper with the union of both behaviours; io_atomic.py is gone.
Crash/no-truncation coverage lives in tests/test_subprocess_abort.py.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from campaignlib.util import atomic_write_bytes, atomic_write_text


def test_atomic_write_text_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "out.json"
    atomic_write_text(target, "[]")
    assert target.read_text() == "[]"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_bytes_preserves_non_utf8_and_fsyncs_file(tmp_path, monkeypatch):
    target = tmp_path / "binary.dat"
    calls: list[int] = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    atomic_write_bytes(target, b"\xff\x00\xfe")
    assert target.read_bytes() == b"\xff\x00\xfe"
    assert calls
    assert not list(tmp_path.glob("*.tmp.*"))


def test_atomic_write_bytes_replacement_failure_preserves_destination(tmp_path, monkeypatch):
    target = tmp_path / "binary.dat"
    target.write_bytes(b"before")
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError, match="boom"):
        atomic_write_bytes(target, b"after")
    assert target.read_bytes() == b"before"
    assert not list(tmp_path.glob("*.tmp.*"))


def test_atomic_write_text_overwrites_existing_content(tmp_path):
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_tmp_name_is_pid_suffixed(tmp_path):
    """Two processes racing on the same destination must not share a tmp
    filename. The ensemble's speculative re-execution terminates a losing
    duplicate process; only a unique-per-writer tmp name makes that harmless,
    since a shared fixed name lets both interleave writes into it before
    either rename.
    """
    target = tmp_path / "out.txt"
    seen_tmp_names = []
    real_replace = os.replace

    def spy_replace(src, dst):
        seen_tmp_names.append(Path(src).name)
        real_replace(src, dst)

    with patch("campaignlib.util.os.replace", side_effect=spy_replace), \
         patch("campaignlib.util.os.getpid", return_value=4242):
        atomic_write_text(target, "content")

    assert seen_tmp_names == [f"{target.name}.tmp.4242"]


def test_atomic_write_text_creates_parent_directories(tmp_path):
    """The util-side behaviour the merge had to preserve: config writers call
    this against paths whose docs/ subtree may not exist yet."""
    target = tmp_path / "docs" / "nested" / "out.md"
    atomic_write_text(target, "body")
    assert target.read_text() == "body"


def test_atomic_write_text_honors_encoding_argument(tmp_path):
    target = tmp_path / "out.txt"
    atomic_write_text(target, "café", encoding="latin-1")
    assert target.read_bytes() == "café".encode("latin-1")


def test_atomic_write_text_cleans_up_tmp_on_failure(tmp_path):
    """A failed write must leave neither a tmp file nor a clobbered target."""
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    with patch("campaignlib.util.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            atomic_write_text(target, "new")

    assert target.read_text() == "original"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_bytes_never_closes_the_descriptor_fdopen_owns(tmp_path, monkeypatch):
    """A failed replace must not close a number the runtime may have reissued.

    os.fdopen takes ownership of the descriptor, so the context manager has
    already closed it by the time the failure handler runs. Closing the raw
    number a second time inside the threadpooled server can reach another
    request's open file or socket rather than harmlessly raising EBADF.
    """
    target = tmp_path / "binary.dat"
    temp_fds: list[int] = []
    closed_fds: list[int] = []
    real_open, real_close = os.open, os.close

    def spy_open(path, flags, mode=0o777, **kwargs):
        fd = real_open(path, flags, mode, **kwargs)
        if str(path).endswith(f".tmp.{os.getpid()}"):
            temp_fds.append(fd)
        return fd

    def spy_close(fd):
        closed_fds.append(fd)
        return real_close(fd)

    monkeypatch.setattr("campaignlib.util.os.open", spy_open)
    monkeypatch.setattr("campaignlib.util.os.close", spy_close)
    monkeypatch.setattr("campaignlib.util.os.replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(OSError, match="boom"):
        atomic_write_bytes(target, b"payload")

    assert temp_fds, "the temporary file was never opened"
    assert not set(closed_fds) & set(temp_fds)
