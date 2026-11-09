"""Write-once, content-addressed store for custody snapshots, and old-byte providers (spec 040, R2).

``put``/``get`` keep ``docs/summaries/delta/custody/objects/<sha256>``: an object is never rewritten and is
verified on every read.  ``recover`` finds the bytes a stale pin names, trying, in a fixed order, a retained
snapshot, the campaign's own git history, and an explicit file; every candidate is accepted only when its
SHA-256 equals the pin.

This is the ONLY module in the delta family that runs ``git`` and it is read-only (``rev-list``, ``cat-file``,
``log``): no checkout, no ref change, no index write.  No model call is made here.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .errors import EXIT_REFUSAL, DeltaRefusal
from .plan import DELTA_ROOT_REL

CUSTODY_REL = f"{DELTA_ROOT_REL}/custody/objects"
PROVIDERS = ("snapshot", "git", "explicit")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_GIT_TIMEOUT = 60


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def objects_dir(root: Path | str) -> Path:
    return Path(root) / CUSTODY_REL


def _object_path(root: Path | str, sha: str) -> Path:
    if not _SHA.fullmatch(sha):
        raise DeltaRefusal(f"not a SHA-256: {sha!r}", EXIT_REFUSAL)
    return objects_dir(root) / sha


def put(root: Path | str, data: bytes) -> str:
    """Store ``data`` under its SHA-256 and return it.  Write-once: an existing object is verified, never rewritten."""
    sha = _sha(data)
    target = _object_path(root, sha)
    if target.exists():
        if _sha(target.read_bytes()) != sha:
            raise DeltaRefusal(f"custody object is corrupt: {target}; it is never rewritten, repair it by hand "
                               "or restore it from backup.", EXIT_REFUSAL)
        return sha
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return sha


def get(root: Path | str, sha: str) -> bytes | None:
    """The stored bytes for ``sha`` (None when absent).  A stored object whose bytes no longer hash to its name is refused."""
    target = _object_path(root, sha)
    if not target.is_file():
        return None
    data = target.read_bytes()
    if _sha(data) != sha:
        raise DeltaRefusal(f"custody object is corrupt: {target} no longer hashes to {sha}.", EXIT_REFUSAL)
    return data


def _git(root: Path, *args: str, binary: bool = False) -> bytes | None:
    """Run a read-only git command with ``cwd`` at the campaign; None when git or the repository is unavailable."""
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=_GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _git_candidates(root: Path, path: str) -> list[str]:
    """Blob ids, path history first, then every other blob reachable in the repository."""
    ordered: list[str] = []
    seen: set[str] = set()
    log = _git(root, "log", "--all", "--format=", "--raw", "--no-abbrev", "--", path)
    for line in (log or b"").decode("utf-8", "replace").splitlines():
        # ":100644 100644 <old> <new> M\t<path>"
        fields = line.split()
        if len(fields) >= 5 and fields[0].startswith(":"):
            blob = fields[3]
            if blob.strip("0") and blob not in seen:
                seen.add(blob)
                ordered.append(blob)
    objs = _git(root, "rev-list", "--objects", "--all")
    for line in (objs or b"").decode("utf-8", "replace").splitlines():
        blob = line.split(" ", 1)[0]
        if blob and blob not in seen:
            seen.add(blob)
            ordered.append(blob)
    return ordered


def _from_git(root: Path, path: str, expected: str) -> tuple[bytes | None, str]:
    if _git(root, "rev-parse", "--git-dir") is None:
        return None, "no git repository at the campaign root"
    for blob in _git_candidates(root, path):
        data = _git(root, "cat-file", "blob", blob)  # trees and commits fail here and are skipped
        if data is not None and _sha(data) == expected:
            return data, f"git blob {blob}"
    return None, "no git blob hashes to the pinned digest"


def recover(root: Path | str, chapter: int, path: str, expected_sha: str,
            explicit: Path | str | None = None) -> tuple[bytes, str, str]:
    """``(bytes, provider, detail)`` for the content ``expected_sha`` pins, from the first provider that has it.

    Refuses ``REBASE_OLD_BYTES_MISMATCH`` when an explicit file hashes differently (it is a wrong file, so it
    never silently falls through) and ``REBASE_OLD_BYTES_UNAVAILABLE`` when no provider holds the bytes.
    """
    root = Path(root)
    tried: list[str] = []
    data = get(root, expected_sha)
    if data is not None:
        return data, "snapshot", f"{CUSTODY_REL}/{expected_sha}"
    tried.append("snapshot: no retained object")
    data, detail = _from_git(root, path, expected_sha)
    if data is not None:
        return data, "git", detail
    tried.append(f"git: {detail}")
    if explicit is not None:
        file = Path(explicit)
        try:
            data = file.read_bytes()
        except OSError as exc:
            tried.append(f"explicit: cannot read {file} ({exc.strerror or exc})")
        else:
            actual = _sha(data)
            if actual != expected_sha:
                raise DeltaRefusal(
                    f"REBASE_OLD_BYTES_MISMATCH: --old-bytes file {file} for chapter {chapter} ({path}) does "
                    f"not hash to the pin.\n  expected sha256: {expected_sha}\n  actual sha256:   {actual}",
                    EXIT_REFUSAL)
            return data, "explicit", str(file)
    else:
        tried.append("explicit: no --old-bytes given")
    raise DeltaRefusal(
        f"REBASE_OLD_BYTES_UNAVAILABLE: cannot recover the bytes of chapter {chapter} ({path}) pinned at "
        f"sha256 {expected_sha}. Providers tried:\n  - " + "\n  - ".join(tried) +
        f"\nSupply them with --old-bytes {chapter}=PATH.", EXIT_REFUSAL)


def probe(root: Path | str, path: str, expected_sha: str, explicit: Path | str | None = None) -> list[dict]:
    """Which providers could supply the bytes ``expected_sha`` pins; never writes and never raises.

    ``[{provider, available, detail}]`` in the fixed provider order.  A missing, corrupt or
    wrong-hash candidate is reported unavailable with the reason, so inspection can say what ``prepare``
    would do without doing any of it.
    """
    root = Path(root)
    out: list[dict] = []
    try:
        data = get(root, expected_sha)
    except DeltaRefusal as exc:
        out.append({"provider": "snapshot", "available": False, "detail": exc.message})
    else:
        out.append({"provider": "snapshot", "available": data is not None,
                    "detail": f"{CUSTODY_REL}/{expected_sha}" if data is not None else "no retained object"})
    git_data, git_detail = _from_git(root, path, expected_sha)
    out.append({"provider": "git", "available": git_data is not None, "detail": git_detail})
    if explicit is None:
        out.append({"provider": "explicit", "available": False, "detail": "no --old-bytes given"})
    else:
        try:
            actual = _sha(Path(explicit).read_bytes())
        except OSError as exc:
            out.append({"provider": "explicit", "available": False,
                        "detail": f"cannot read {explicit} ({exc.strerror or exc})"})
        else:
            out.append({"provider": "explicit", "available": actual == expected_sha,
                        "detail": str(explicit) if actual == expected_sha else f"{explicit} hashes to {actual}"})
    return out
