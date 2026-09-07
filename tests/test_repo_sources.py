"""The guardrail scanners' file-enumeration is itself now under test.

It was not, which is why four guardrail tests failed on the main checkout for
as long as a git worktree existed under `.claude/worktrees/` — each scanner
carried its own hand-maintained denylist of directories, and a worktree is a
full second copy of the repo that none of them had thought to exclude. The
failure pointed at `campaignlib/api/client.py` (a copy of it), so it read as a
seam violation rather than as a scanning bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "tests"))

from repo_sources import FALLBACK_SKIP_DIRS, _walked, repo_files, repo_python_files  # noqa: E402


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   capture_output=True, timeout=30)


@pytest.fixture
def repo(tmp_path):
    """A tiny real git repo with a gitignored nested copy of itself."""
    _git("init", "-q", cwd=tmp_path)
    _git("config", "user.email", "t@example.com", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / ".gitignore").write_text(".claude/\n.venv/\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "real.py").write_text("x = 1\n")
    _git("add", "-A", cwd=tmp_path)
    _git("commit", "-qm", "init", cwd=tmp_path)

    # the nested worktree copy — untracked and gitignored, exactly like
    # .claude/worktrees/<branch>/ in the real repo
    nested = tmp_path / ".claude" / "worktrees" / "wt" / "pkg"
    nested.mkdir(parents=True)
    (nested / "real.py").write_text("x = 1\n")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "vendored.py").write_text("y = 2\n")
    return tmp_path


# ── The bug this module exists to prevent ────────────────────────────────────

def test_nested_worktree_copy_is_never_returned(repo):
    """The regression itself: a second copy of a tracked file under .claude/
    must not appear, or every seam guardrail reports it as a violation."""
    found = repo_python_files(repo)
    assert [p.relative_to(repo).as_posix() for p in found] == ["pkg/real.py"]


def test_gitignored_virtualenv_is_never_returned(repo):
    found = {p.relative_to(repo).as_posix() for p in repo_python_files(repo)}
    assert not any(p.startswith(".venv/") for p in found)


def test_naive_rglob_would_have_found_the_copy(repo):
    """Pins WHY this helper exists — the obvious implementation is wrong."""
    naive = {p.relative_to(repo).as_posix() for p in repo.rglob("*.py")}
    assert ".claude/worktrees/wt/pkg/real.py" in naive
    assert ".claude/worktrees/wt/pkg/real.py" not in {
        p.relative_to(repo).as_posix() for p in repo_python_files(repo)
    }


# ── Contract ─────────────────────────────────────────────────────────────────

def test_returns_absolute_sorted_paths(repo):
    found = repo_python_files(repo)
    assert all(p.is_absolute() for p in found)
    assert found == sorted(found)


def test_untracked_new_file_is_not_returned(repo):
    """Tracked-only is the rule. A brand-new unstaged file is invisible until
    it is added — acceptable, and the price of not maintaining a denylist."""
    (repo / "pkg" / "brand_new.py").write_text("z = 3\n")
    assert "pkg/brand_new.py" not in {
        p.relative_to(repo).as_posix() for p in repo_python_files(repo)
    }


def test_deleted_but_still_tracked_file_is_skipped(repo):
    """`git ls-files` still lists a deleted file; callers read these, so a
    stale entry would raise instead of failing an assertion."""
    (repo / "pkg" / "real.py").unlink()
    assert repo_python_files(repo) == []


def test_non_python_pattern(repo):
    (repo / "doc.md").write_text("# hi\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "doc", cwd=repo)
    assert [p.name for p in repo_files(repo, "*.md")] == ["doc.md"]


# ── Fallback (no git metadata) ───────────────────────────────────────────────

def test_fallback_walk_also_excludes_the_worktree(repo):
    """Running from a source export with no .git must degrade, not regress."""
    found = {p.relative_to(repo).as_posix() for p in _walked(repo, "*.py")}
    assert "pkg/real.py" in found
    assert not any(p.startswith(".claude/") for p in found)
    assert not any(p.startswith(".venv/") for p in found)


def test_fallback_skip_dirs_covers_the_worktree_root():
    assert ".claude" in FALLBACK_SKIP_DIRS


def test_non_git_directory_falls_back_rather_than_raising(tmp_path):
    (tmp_path / "a.py").write_text("q = 1\n")
    # No `git init` — must still return something usable.
    assert [p.name for p in repo_python_files(tmp_path)] == ["a.py"]


# ── The real repo ────────────────────────────────────────────────────────────

def test_real_repo_finds_the_seam_file_exactly_once():
    hits = [p for p in repo_python_files(_REPO_ROOT)
            if p.relative_to(_REPO_ROOT).as_posix() == "campaignlib/api/client.py"]
    assert len(hits) == 1


def test_real_repo_returns_no_dot_claude_paths():
    assert not [p for p in repo_python_files(_REPO_ROOT)
                if ".claude" in p.relative_to(_REPO_ROOT).parts]


# ── The ignore rules these scanners inherit ──────────────────────────────────
#
# `repo_files` enumerates with `git ls-files`, so `.gitignore` is not merely a
# `git status` convenience here — it is the allowlist five guardrail suites read
# (test_backend_seam_guardrails, test_retrieve_render_isolation,
# test_openrouter_seam, test_externalized_prompts, and this module). An ignore
# rule that is broader than intended does not just hide a file from `git
# status`; it removes that file from every seam check, silently and with a
# green suite — the same shape as the worktree bug at the top of this file, in
# the other direction.

def _is_ignored(repo_root, relpath: str) -> bool:
    """Would git ignore `relpath`? `--no-index` so the path need not exist."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", "--no-index", relpath],
        capture_output=True, timeout=30)
    return proc.returncode == 0


def test_the_worktrees_ignore_rule_is_anchored_to_the_repo_root():
    """#403 ignored `worktrees/` to stop a nested checkout showing as untracked.

    Unanchored, that pattern matches the directory name at any depth, so a
    future `server/worktrees/` or `docs/worktrees/` would be un-addable and —
    because gitignored files never reach `git ls-files` — exempt from every
    guardrail above. The root-level checkout is the only thing meant to be
    covered, and `/worktrees/` covers exactly it.
    """
    assert _is_ignored(_REPO_ROOT, "worktrees/cg-353/session_doc/narrate.py")
    for nested in ("server/worktrees/x.py", "docs/worktrees/x.py",
                   "campaignlib/api/worktrees/client.py"):
        assert not _is_ignored(_REPO_ROOT, nested), nested


def test_no_ignore_rule_matches_a_directory_that_holds_tracked_source():
    """An invariant, not a regression test — it passes before the #403 fix too.

    Ignore rules do not evict an already-tracked file, so a match here does not
    shrink today's guardrail input. What it creates is a trap for the *next*
    file added beside it: that one is silently un-addable, never reaches
    `git ls-files`, and so is born exempt from every seam check. Catching the
    overlap is cheaper than catching the file that goes missing because of it.
    """
    tracked = repo_python_files(_REPO_ROOT)
    assert tracked, "expected a tracked-file listing to check against"
    hidden = [p for p in tracked
              if _is_ignored(_REPO_ROOT, p.relative_to(_REPO_ROOT).as_posix())]
    assert not hidden, [str(p) for p in hidden[:5]]
