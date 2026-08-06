"""Corpus enumeration and the two literal scanners.

Three things live here: the walk that decides *which files are in scope*, the
two interchangeable implementations that find matching lines in them, and the
shared excerpt extractor that turns a `(path, line)` into verbatim text.

## Two scanners, one answer

`rg` is the primary and is roughly 60× faster; the stdlib walk is the fallback
and the parity oracle. They are required to return **identical** results —
`tests/test_provenance_scanner_parity.py` asserts it over the fixture workspace
and one live campaign. That is not perfectionism: which one runs depends on
whether `shutil.which("rg")` resolves in the spawning process's `PATH`, and on
this host that answer differed between an interactive shell and a Python
subprocess on the same day. Results that varied with it would be results nobody
could reproduce.

Parity is achieved by construction wherever it can be. Both implementations
share one scope declaration (`enumerate_files`), one exclude counter, and one
excerpt extractor; the scanners themselves only answer *"which (path, line)
pairs match"*. What is left to diverge is small enough to test.

## `.gitignore` gets no vote

Neither implementation consults version-control state. 230 real files in the
live workspace are `.gitignore`d — 213 of them Phandalin NPC sidecars, all
working-reference tier — and they are all on disk, all true, and all
searchable. What is or is not committed is a version-control concern; the
manifest's ``exclude`` list is the single scope authority (research D17). For
rg this means `--no-ignore --hidden` are mandatory, not tuning.

## The suppression counter is per-glob, on purpose

A single total would be dominated by the built-in defaults (`.git/**`,
`node_modules/**`), which is precisely how a GM-added glob that quietly narrows
every future search would hide. Attributing each suppressed file to the glob
that removed it keeps the one number that matters visible next to the noise.

Files are extension-filtered *before* exclude attribution, so the counter reports
searchable files removed rather than several thousand git objects.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from base64 import b64decode
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

from .tiers import compile_glob

# ── the pinned rg invocation (research D17) ──────────────────────────────────

#: The binary. Never a shell string — argv is a list, always.
RG = "rg"

#: Local name every ``subprocess`` call in this module must pass as argv.
#: ``tests/test_provenance_readonly.py`` asserts it statically, so an argv
#: assembled at the call site cannot slip past the allow-list below.
RG_ARGV_BUILDER = "argv"

#: Required for correctness, not speed. Dropping any one of them changes what
#: the search can see, silently. See the table in research D17.
RG_REQUIRED_FLAGS: tuple[str, ...] = ("--no-config", "--no-ignore", "--hidden", "--json")

#: Never emitted. ``--smart-case`` would make `Ilvara` and `ilvara` search
#: differently based on the query's own casing; the rest are write or
#: output-shape modes this package has no business using.
RG_FORBIDDEN_FLAGS: tuple[str, ...] = (
    "--smart-case",
    "-S",
    "--replace",
    "-r",
    "--passthru",
    "--files-with-matches",
    "-l",
    "--count",
    "-c",
)

#: The complete set of flags this module can emit, version probe included.
#: Anything outside it is a change somebody has to make deliberately.
RG_ALLOWED_FLAGS: tuple[str, ...] = RG_REQUIRED_FLAGS + (
    "-g",       # one per search_extension, plus the negated exclude globs
    "-e",       # the pattern, so a query starting with `-` is never a flag
    "-F",       # literal unless regex=True
    "-i",       # explicit case-insensitivity …
    "-s",       # … or explicit sensitivity. Never left to a default.
    "--",       # end of flags
    "--version",  # the version probe's only flag
)

#: Re-excluded because ``--hidden`` would otherwise admit it. The object store
#: is bytes, not content, and it is the one thing `.gitignore` was right about.
GIT_EXCLUDE = "!.git/**"


class ScannerUnavailable(Exception):
    """A requested scanner cannot run here. Maps to a CLI refusal, exit 1.

    Never a silent fallback: ``--scanner rg`` on a host without rg has to say
    so, or the flag is a lie the caller has no way to detect.
    """


@dataclass(frozen=True)
class ScannerImpl:
    """Which implementation is active, and its version.

    Reported on every search response and by ``capabilities``. An unreported
    60× latency swing that varies by host is exactly the tribal per-machine
    state Principle VIII exists to eliminate.
    """

    name: str            # "rg" | "python"
    version: str
    location: str | None = None


def _rg_path() -> str | None:
    return shutil.which(RG)


@lru_cache(maxsize=1)
def _rg_version(location: str) -> str:
    argv = [location, "--version"]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "ripgrep (version unavailable)"
    first = proc.stdout.splitlines()
    return first[0].strip() if first else "ripgrep (version unavailable)"


def available_scanners() -> tuple[str, ...]:
    """Names that ``select_scanner`` will accept on this host, best first."""
    return (("rg",) if _rg_path() else ()) + ("python",)


def select_scanner(preference: str | None = None) -> ScannerImpl:
    """``--scanner`` -> rg if discoverable -> python.

    Forcing an implementation that is not available is a refusal. A silent
    fallback would produce a result the caller believes came from somewhere
    else — which is the same defect Story 3 names, one level down.
    """
    if preference is not None and preference not in ("rg", "python"):
        raise ScannerUnavailable(
            f"unknown scanner {preference!r}; this build has {', '.join(('rg', 'python'))}"
        )

    if preference == "python":
        return _python_impl()

    location = _rg_path()
    if preference == "rg" and location is None:
        raise ScannerUnavailable(
            "--scanner rg was requested but rg is not on PATH.\n"
            "  Not falling back silently: the caller asked for a specific "
            "implementation.\n"
            "  Drop --scanner to use the stdlib scanner (identical results, ~60× slower)."
        )
    if location is not None:
        return ScannerImpl("rg", _rg_version(location), location)
    return _python_impl()


def _python_impl() -> ScannerImpl:
    return ScannerImpl(
        "python", f"python {platform.python_version()} (stdlib scanner)", None
    )


# ── scope: which files a campaign's manifest block covers ────────────────────


@dataclass(frozen=True)
class FileSet:
    """Every searchable file under one campaign root, and what was left out."""

    paths: tuple[str, ...]
    """Campaign-relative POSIX paths, sorted. Sorted because rg is multithreaded
    and its file order is not stable; every ordering guarantee downstream is
    built on a total order established here."""

    excluded: Mapping[str, int]
    """Exclude glob -> count of searchable files it removed. Every declared glob
    is a key, including the ones that removed nothing — a glob with a zero is
    how a GM sees that a pattern is not doing what they thought."""

    unreadable: tuple[str, ...] = ()
    """Directories the walk could not read. Reported, never swallowed."""

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())


def enumerate_files(campaign, campaign_root: str | Path) -> FileSet:
    """Walk one campaign root, applying ``search_extensions`` then ``exclude``.

    ``campaign`` is a manifest ``Campaign`` (only ``.search_extensions`` and
    ``.exclude`` are touched, so a stub works in tests).

    Symlinked directories are not followed: a cycle would hang the walk, and a
    symlink out of the campaign root would silently pull another game's files
    into a search that named exactly one campaign (FR-008).
    """
    root = Path(campaign_root)
    exts = {e.lower() for e in getattr(campaign, "search_extensions", ())}
    globs = tuple(getattr(campaign, "exclude", ()))
    excluded: dict[str, int] = {g: 0 for g in globs}
    unreadable: list[str] = []
    paths: list[str] = []

    def _onerror(exc: OSError) -> None:
        unreadable.append(str(getattr(exc, "filename", exc)))

    for dirpath, dirnames, filenames in os.walk(root, onerror=_onerror, followlinks=False):
        dirnames.sort()
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for filename in filenames:
            rel = filename if rel_dir == "." else f"{rel_dir}/{filename}"
            if exts and Path(filename).suffix.lower() not in exts:
                continue
            hit = next((g for g in globs if compile_glob(g).search(rel)), None)
            if hit is not None:
                excluded[hit] += 1
                continue
            paths.append(rel)

    return FileSet(tuple(sorted(paths)), excluded, tuple(sorted(unreadable)))


# ── excerpts: verbatim, or explicitly undecodable ────────────────────────────

UTF8 = "utf-8"
UNDECODABLE = "undecodable"


@dataclass(frozen=True)
class Excerpt:
    """One matched line plus its context, exactly as the bytes on disk read."""

    text: str
    encoding: str            # "utf-8" | "undecodable"
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


def _decode(raw: bytes) -> tuple[str, str]:
    """Decode one line, or say plainly that it could not be decoded.

    ``errors="replace"`` is not used anywhere here. It would substitute U+FFFD
    for bytes that were really on disk and hand the caller a line that looks
    verbatim and is not — which Constitution IV forbids. ``backslashreplace``
    produces an escaped, reversible rendering, and the companion status field
    says it happened (research D18).
    """
    try:
        return raw.decode(UTF8), UTF8
    except UnicodeDecodeError:
        return raw.decode(UTF8, errors="backslashreplace"), UNDECODABLE


def read_lines(path: Path, cache: dict | None = None) -> list[bytes]:
    """The file's lines as raw bytes, newline separators removed.

    ``cache`` is an optional per-request dict. It is memory, not a stored
    artifact — nothing in this package persists anything (SC-009, SC-010).
    """
    key = str(path)
    if cache is not None and key in cache:
        return cache[key]
    lines = path.read_bytes().split(b"\n")
    if cache is not None:
        cache[key] = lines
    return lines


def decode_line(lines: list[bytes], line: int) -> tuple[str, str]:
    """One 1-indexed line as ``(text, encoding)``, from already-read bytes.

    The cheap half of ``extract_excerpt``, for the ranking pass — which needs the
    matched line's text to score it but no context, and runs once per *match*
    rather than once per returned hit. On a broad query that is the difference
    between hundreds of thousands of ``Path`` constructions and one per file.
    """
    index = line - 1
    if index < 0 or index >= len(lines):
        return "", UTF8
    return _decode(lines[index])


def extract_excerpt(
    path: str | Path, line: int, context_lines: int = 2, cache: dict | None = None
) -> Excerpt:
    """Slice a 1-indexed line and its context out of the file's own bytes.

    Shared by both scanners deliberately. rg's ``--json`` already carries the
    matched line, but taking it from two different sources is two chances to
    disagree about trailing whitespace, CRLF, or an undecodable byte — and the
    disagreement would show up as a parity failure nobody could localise.
    """
    lines = read_lines(Path(path), cache)
    index = line - 1
    if index < 0 or index >= len(lines):
        return Excerpt("", UTF8)

    text, encoding = _decode(lines[index])
    start = max(0, index - context_lines)
    before = tuple(_decode(b)[0] for b in lines[start:index])
    after = tuple(_decode(b)[0] for b in lines[index + 1 : index + 1 + context_lines])
    return Excerpt(text, encoding, before, after)


# ── the scanners ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RawMatch:
    """One matching line. Deliberately minimal — see the module docstring.

    A scanner answers *where*, and the shared extractor answers *what*. Multiple
    matches on one line collapse to one ``RawMatch``, which both
    implementations do identically.
    """

    path: str    # campaign-relative POSIX
    line: int    # 1-indexed


@dataclass(frozen=True)
class ScanResult:
    matches: tuple[RawMatch, ...]
    files: FileSet
    impl: ScannerImpl
    out_of_scope: tuple[str, ...] = field(default=())
    """Files the scanner matched that the manifest's scope walk did not
    enumerate. Should always be empty; surfaced rather than dropped quietly so
    a glob-semantics disagreement between rg and the walk is visible the first
    time it happens instead of at the next parity run."""


def build_rg_argv(campaign, query: str, *, regex: bool, case_sensitive: bool) -> list[str]:
    """The pinned invocation. Every flag here is guarded by a test.

    Run with ``cwd`` at the campaign root and a search path of ``./``, because
    rg matches ``-g`` globs containing a ``/`` relative to the working
    directory — which is what makes one manifest declaration drive both
    scanners.
    """
    argv = [RG, *RG_REQUIRED_FLAGS, "-g", GIT_EXCLUDE]
    for ext in getattr(campaign, "search_extensions", ()):
        argv += ["-g", f"*{ext}"]
    # Excludes come last: in rg, a later glob overrides an earlier one, so the
    # manifest's exclusions must be able to override the extension whitelist.
    for pattern in getattr(campaign, "exclude", ()):
        argv += ["-g", f"!{pattern}"]
    argv.append("-s" if case_sensitive else "-i")
    if not regex:
        argv.append("-F")
    argv += ["-e", query, "--", "./"]
    return argv


def _scan_rg(campaign, root: Path, query: str, *, regex: bool, case_sensitive: bool):
    argv = build_rg_argv(campaign, query, regex=regex, case_sensitive=case_sensitive)
    proc = subprocess.run(
        argv, cwd=str(root), capture_output=True, text=True, check=False
    )
    # rg exits 1 for "no matches" and 2 for a real error; only the latter is a
    # problem, and even then partial output is better than a crash mid-search.
    if proc.returncode not in (0, 1) and not proc.stdout:
        raise ScannerUnavailable(
            f"rg exited {proc.returncode}: {proc.stderr.strip() or '(no stderr)'}"
        )

    seen: list[RawMatch] = []
    for raw in proc.stdout.splitlines():
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        text = data.get("path", {}).get("text")
        if text is None:  # a path rg could not decode; base64 under "bytes"
            encoded = data.get("path", {}).get("bytes")
            if encoded is None:
                continue
            text = b64decode(encoded).decode(UTF8, errors="backslashreplace")
        rel = text[2:] if text.startswith("./") else text
        seen.append(RawMatch(rel, int(data["line_number"])))
    return seen


def _pattern(query: str, *, regex: bool, case_sensitive: bool) -> re.Pattern[bytes]:
    body = query.encode(UTF8) if regex else re.escape(query.encode(UTF8))
    return re.compile(body, 0 if case_sensitive else re.IGNORECASE)


def _scan_python(files: FileSet, root: Path, query: str, *, regex: bool, case_sensitive: bool):
    """`read_bytes` + a whole-file fast reject, decoding nothing that misses.

    Bytes rather than text throughout: decoding 131 MB to find out most of it
    does not match costs more than the search, and a file that is not valid
    UTF-8 must not take the scan down (research D1, D18).
    """
    pattern = _pattern(query, regex=regex, case_sensitive=case_sensitive)
    out: list[RawMatch] = []
    for rel in files.paths:
        try:
            blob = (root / rel).read_bytes()
        except OSError:
            continue
        if not pattern.search(blob):
            continue
        for number, line in enumerate(blob.split(b"\n"), start=1):
            if pattern.search(line):
                out.append(RawMatch(rel, number))
    return out


def scan(
    campaign,
    campaign_root: str | Path,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    impl: ScannerImpl,
) -> ScanResult:
    """Find every matching line under one campaign root.

    The manifest's scope walk runs either way — it is what produces the
    ``suppressed_by_exclude`` count both implementations must report
    identically, and it is the authority rg's output is reconciled against.
    """
    root = Path(campaign_root)
    files = enumerate_files(campaign, root)

    if impl.name == "rg":
        found = _scan_rg(
            campaign, root, query, regex=regex, case_sensitive=case_sensitive
        )
    else:
        found = _scan_python(
            files, root, query, regex=regex, case_sensitive=case_sensitive
        )

    in_scope = set(files.paths)
    kept = [m for m in found if m.path in in_scope]
    strayed = sorted({m.path for m in found if m.path not in in_scope})

    kept.sort(key=lambda m: (m.path, m.line))
    return ScanResult(tuple(kept), files, impl, tuple(strayed))


def match_counts(matches: Iterable[RawMatch]) -> dict[str, int]:
    """Matching lines per file — the base term of the relevance score (D9).

    Lines, not occurrences: both scanners agree on lines by construction, and
    "this line matched" is what a reader is shown. Counting occurrences would
    make the two implementations answerable for rg's submatch semantics.
    """
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.path] = counts.get(match.path, 0) + 1
    return counts
