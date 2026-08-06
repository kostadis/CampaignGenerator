"""The one place that decides what "this repository's own source files" means.

Several guardrail tests enforce invariants by walking the tree and asserting
that no file outside a designated seam does something (`make_client(`,
`messages.batches`, `openrouter.ai`, a retrieval call beside a render call).
Each of them grew its own exclusion list — `{"venv", ".venv", "__pycache__",
"node_modules", "frontend"}`, or an inline `if ".specify" in parts`, or nothing
at all — and every one of those lists was a **denylist of directories that
happened to exist when it was written**.

That broke the moment a git worktree appeared under `.claude/worktrees/`. A
worktree is a full second copy of the repo, so `REPO_ROOT.rglob("*.py")` found
`campaignlib/api/client.py` twice and the guardrails reported the *copy* as a
seam violation:

    OpenRouter referenced outside the seam:
      ['.claude/worktrees/dgx-two-phase-extraction/campaignlib/api/client.py',
       '.claude/worktrees/scene-index-join/campaignlib/api/client.py']

Four tests failed on the main checkout, for as long as any worktree existed,
with an error message pointing at a file that was not the problem.

**The fix is to stop maintaining a denylist.** `git ls-files` enumerates
*tracked* files, so anything gitignored — worktrees (`.claude/` is in
`.gitignore`), virtualenvs, `node_modules`, build output, scratch dirs — is
excluded by construction, and stays excluded when someone invents a new place to
put generated files. It is an allowlist that maintains itself.

The walk fallback exists only for running from a source export with no git
metadata; it keeps the old denylist so behaviour degrades rather than vanishes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: Only consulted by the non-git fallback. Kept deliberately close to the union
#: of what the individual tests used to exclude, plus the worktree root that
#: caused this module to exist.
FALLBACK_SKIP_DIRS = frozenset({
    ".claude", ".git", ".specify", ".venv", "venv", "env",
    "__pycache__", "node_modules", "frontend", "logs", "build", "dist",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages",
})


def _git_tracked(root: Path, pattern: str) -> list[Path] | None:
    """Tracked files matching `pattern`, or None when this is not a git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", pattern],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    # A tracked-but-deleted file still lists; callers read these, so drop them.
    return [p for p in (root / n for n in names) if p.is_file()]


def _walked(root: Path, pattern: str) -> list[Path]:
    out = []
    for p in root.rglob(pattern):
        if any(part in FALLBACK_SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            out.append(p)
    return out


def repo_files(root: Path, pattern: str = "*.py") -> list[Path]:
    """This repo's own tracked files matching `pattern`, sorted.

    Never returns a file from a nested git worktree, a virtualenv, or anything
    else gitignored — which is the whole point. Paths are absolute.
    """
    root = Path(root).resolve()
    found = _git_tracked(root, pattern)
    if found is None:
        found = _walked(root, pattern)
    return sorted(found)


def repo_python_files(root: Path) -> list[Path]:
    """This repo's own tracked ``*.py`` files, sorted."""
    return repo_files(root, "*.py")
