"""T007: the write-once custody store and old-byte providers (spec 040, R2)."""

from __future__ import annotations

import hashlib
import subprocess

import pytest

from pipelines.summary_native.delta import custody_store as cs
from pipelines.summary_native.delta.errors import DeltaRefusal

OLD = b"chapter two\npayment: 50 gold\n"
NEW = b"chapter two\npayment: 80 gold\n"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "camp"
    (root / "docs/summaries").mkdir(parents=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    f = root / "docs/summaries/002-x.md"
    f.write_bytes(OLD)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "orig")
    f.write_bytes(NEW)
    git(root, "commit", "-qam", "corrected")
    return root


def test_put_is_write_once_and_idempotent(tmp_path):
    h = cs.put(tmp_path, OLD)
    assert h == sha(OLD)
    p = cs.objects_dir(tmp_path) / h
    mtime = p.stat().st_mtime_ns
    assert cs.put(tmp_path, OLD) == h and p.stat().st_mtime_ns == mtime
    assert cs.get(tmp_path, h) == OLD
    assert not list(cs.objects_dir(tmp_path).glob("*.tmp"))


def test_get_missing_is_none_and_corrupt_is_refused(tmp_path):
    assert cs.get(tmp_path, sha(OLD)) is None
    h = cs.put(tmp_path, OLD)
    (cs.objects_dir(tmp_path) / h).write_bytes(b"tampered")
    with pytest.raises(DeltaRefusal, match="corrupt"):
        cs.get(tmp_path, h)
    with pytest.raises(DeltaRefusal, match="corrupt"):
        cs.put(tmp_path, OLD)


def test_git_recovery_by_exact_hash_leaves_repo_untouched(repo):
    head = git(repo, "rev-parse", "HEAD")
    status = git(repo, "status", "--porcelain")
    data, provider, detail = cs.recover(repo, 2, "docs/summaries/002-x.md", sha(OLD))
    assert data == OLD and provider == "git" and "blob" in detail
    assert git(repo, "rev-parse", "HEAD") == head and git(repo, "status", "--porcelain") == status
    assert (repo / "docs/summaries/002-x.md").read_bytes() == NEW  # corrected current bytes untouched


def test_git_finds_blob_even_when_path_differs(repo):
    data, provider, _ = cs.recover(repo, 2, "docs/summaries/elsewhere.md", sha(OLD))
    assert data == OLD and provider == "git"


def test_snapshot_wins_over_git_once_stored(repo):
    cs.put(repo, OLD)
    _d, provider, _ = cs.recover(repo, 2, "docs/summaries/002-x.md", sha(OLD))
    assert provider == "snapshot"


def test_no_repo_is_unavailable_and_lists_providers(tmp_path):
    with pytest.raises(DeltaRefusal) as err:
        cs.recover(tmp_path, 2, "docs/summaries/002-x.md", sha(OLD))
    msg = err.value.message
    assert "REBASE_OLD_BYTES_UNAVAILABLE" in msg and "snapshot" in msg and "git" in msg and "explicit" in msg


def test_missing_blob_is_unavailable(repo):
    with pytest.raises(DeltaRefusal, match="REBASE_OLD_BYTES_UNAVAILABLE"):
        cs.recover(repo, 2, "docs/summaries/002-x.md", sha(b"never committed"))


def test_explicit_file_ok_and_wrong_file_mismatch(tmp_path):
    good = tmp_path / "old.md"
    good.write_bytes(OLD)
    data, provider, _ = cs.recover(tmp_path, 2, "p.md", sha(OLD), explicit=good)
    assert data == OLD and provider == "explicit"
    wrong = tmp_path / "wrong.md"
    wrong.write_bytes(NEW)
    with pytest.raises(DeltaRefusal) as err:
        cs.recover(tmp_path, 2, "p.md", sha(OLD), explicit=wrong)
    assert "REBASE_OLD_BYTES_MISMATCH" in err.value.message
    assert sha(OLD) in err.value.message and sha(NEW) in err.value.message


def test_only_this_module_shells_out_to_git():
    import pathlib
    import re
    root = pathlib.Path(cs.__file__).parent
    for p in root.glob("*.py"):
        if p.name != "custody_store.py":
            assert not re.search(r"\bsubprocess\b|[\"']git[\"']", p.read_text()), p.name
