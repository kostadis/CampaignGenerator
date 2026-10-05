"""Whole-directory validation: a collector, never a raiser (research R2).

``scan`` parses every ``*.md`` in the summaries directory, runs every check on
every file, and returns a ``ValidationReport`` holding all findings, so one run
tells the GM everything to fix (FR-005a). Content problems never raise. Only
the things that make a run meaningless do:

* ``InputError`` — the directory is missing, empty, or lives under
  ``docs/ensemble`` (an unreadable *file* is an ``unreadable-file`` finding);
* ``RangeError`` — a bound matches no file, ``since > until``, or the range is
  empty (the message lists the chapters present).

Blocking is decided per finding: the code must be in ``schema.BLOCKING_CODES``
and the file must be in range — except ``duplicate-chapter``, which blocks
wherever it occurs because it makes the range itself ambiguous.

No model call (guarded by ``tests/test_summary_native_no_llm.py``).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipelines.summary_native import parse, schema


class ValidationRefusal(Exception):
    """A run that must be refused (CLI exit 2)."""


class RangeError(ValidationRefusal):
    pass


class InputError(ValidationRefusal):
    pass


@dataclass(frozen=True)
class ChapterRange:
    """Resolved inclusive range plus the chapters present and the gaps in it."""

    since: int
    until: int
    present: list[int]
    gaps: list[int]

    @classmethod
    def resolve(cls, present: list[int], since: int | None, until: int | None) -> "ChapterRange":
        have = sorted(set(present))
        if not have:
            raise RangeError("no summary has a numeric chapter prefix; chapters present: none")
        listing = ", ".join(str(c) for c in have)
        for flag, bound in (("--since", since), ("--until", until)):
            if bound is not None and bound not in have:
                raise RangeError(
                    f"{flag} {bound} matches no file; chapters present: {listing}"
                )
        lo = have[0] if since is None else since
        hi = have[-1] if until is None else until
        if lo > hi:
            raise RangeError(f"--since {lo} is after --until {hi}; chapters present: {listing}")
        inside = [c for c in have if lo <= c <= hi]
        if not inside:
            raise RangeError(f"range {lo}-{hi} contains no file; chapters present: {listing}")
        gaps = [c for c in range(lo, hi + 1) if c not in set(have)]
        return cls(since=lo, until=hi, present=have, gaps=gaps)

    def contains(self, chapter: int) -> bool:
        return self.since <= chapter <= self.until


@dataclass(frozen=True)
class Finding:
    file: str
    line: int | None
    code: str
    message: str
    expected: str | None
    found: str | None
    blocking: bool
    in_range: bool
    # possible-duplicate only: {spelling: ["file:line", ...]}.
    locations: dict | None = None


@dataclass
class ValidationReport:
    summaries_dir: str
    range: ChapterRange
    files_scanned: int
    files_in_range: int
    findings: list[Finding] = field(default_factory=list)
    # Exact readable, in-range files scan examined; build parses these and nothing else.
    input_files: list[Path] = field(default_factory=list, repr=False)
    # Set by the CLI: how an existing corpus in the range dir relates to this input.
    existing_corpus: dict | None = None
    dup_threshold: float = schema.DEFAULT_DUP_THRESHOLD

    @property
    def blocking_count(self) -> int:
        return sum(1 for f in self.findings if f.blocking)

    @property
    def files_failing(self) -> int:
        return len({f.file for f in self.findings if f.blocking})

    @property
    def non_blocking_count(self) -> int:
        return sum(1 for f in self.findings if not f.blocking)

    def to_dict(self) -> dict:
        return {
            "summaries_dir": self.summaries_dir,
            "range": {
                "since": self.range.since,
                "until": self.range.until,
                "present": self.range.present,
                "gaps": self.range.gaps,
            },
            "files_scanned": self.files_scanned,
            "files_in_range": self.files_in_range,
            "blocking_count": self.blocking_count,
            "files_failing": self.files_failing,
            "non_blocking_count": self.non_blocking_count,
            "dup_threshold": self.dup_threshold,
            "findings": [_finding_dict(f) for f in self.findings],
            **({"existing_corpus": self.existing_corpus} if self.existing_corpus else {}),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def _existing_lines(self) -> list[str]:
        ec = self.existing_corpus
        if not ec:
            return []
        if ec["state"] == "incomplete":
            return [
                "- Existing corpus: incomplete (the previous build did not finish); "
                "rebuild with build --force"
            ]
        if ec["state"] == "matches":
            return ["- Existing corpus: matches current input"]
        line = (
            f"- Existing corpus: built from {ec['built_from']} files; "
            f"{ec['differ']} differ from current input; rebuild with build --force"
        )
        out = [line]
        for key in ("added", "removed", "changed"):
            if ec[key]:
                out.append(f"  - {key}: {', '.join(ec[key])}")
        return out

    def to_markdown(self) -> str:
        r = self.range
        gaps = ", ".join(str(g) for g in r.gaps) if r.gaps else "none"
        out = [
            "# Validation report",
            "",
            f"- Summaries directory: {self.summaries_dir}",
            f"- Range: {r.since}–{r.until}",
            f"- Files scanned: {self.files_scanned}",
            f"- Files in range: {self.files_in_range}",
            f"- Gaps: {gaps}",
            f"- Duplicate threshold: {self.dup_threshold}",
            *self._existing_lines(),
            "",
            "## In range",
            "",
        ]
        out += _group(f for f in self.findings if f.in_range and f.code not in _DUP_CODES)
        out += ["## Outside range — not blocking", ""]
        out += _group(f for f in self.findings if not f.in_range)
        out += ["## Possible duplicates — fix in the summaries", ""]
        out += _dup_lines([f for f in self.findings if f.code in _DUP_CODES])
        out += [
            "## Summary",
            "",
            f"- Blocking problems: {self.blocking_count}",
            f"- Files failing: {self.files_failing}",
            f"- Non-blocking findings: {self.non_blocking_count}",
            "",
        ]
        return "\n".join(out)


_DUP_CODES = (schema.POSSIBLE_DUPLICATE, schema.STALE_RULING)


def _finding_dict(f: Finding) -> dict:
    d = asdict(f)
    if d["locations"] is None:
        del d["locations"]
    return d


def _dup_lines(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["(none)", ""]
    out: list[str] = []
    for f in sorted(findings, key=lambda f: (f.code != schema.POSSIBLE_DUPLICATE, _sort_key(f), f.message)):
        out.append(f"- {f.code}  — {f.message}")
        for spelling, locs in (f.locations or {}).items():
            out.append(f"  - '{spelling}': {', '.join(locs)}")
    out.append("")
    return out


def _chapter_of(name: str) -> int | None:
    m = schema.PREFIX_RE.match(name.rsplit("/", 1)[-1])
    return int(m.group(1)) if m else None


def _sort_key(f: Finding) -> tuple:
    ch = _chapter_of(f.file)
    return (ch if ch is not None else 10**9, f.file, f.line if f.line is not None else 0, f.code)


def _group(findings) -> list[str]:
    ordered = sorted(findings, key=_sort_key)
    if not ordered:
        return ["(none)", ""]
    out: list[str] = []
    current = None
    for f in ordered:
        if f.file != current:
            current = f.file
            if out and out[-1] != "":
                out.append("")
            out += [f"### {f.file}", ""]
        parts = [f"L{f.line}  {f.code}" if f.line is not None else f.code]
        if f.expected is not None:
            parts.append(f'expected "{f.expected}"')
        if f.found is not None:
            parts.append(f'found "{f.found}"')
        out.append("  ".join(parts) + f"  — {f.message}")
        out.append("")
    return out


def _rel(path: Path, root: Path) -> str:
    return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()


def _check_input_dir(summaries_dir: Path) -> list[Path]:
    resolved = Path(summaries_dir).resolve()
    parts = resolved.parts
    if any(parts[i] == "docs" and parts[i + 1] == "ensemble" for i in range(len(parts) - 1)):
        raise InputError(
            f"{summaries_dir}: lives under docs/ensemble; summary-native and "
            "ensemble corpora must never be mixed"
        )
    if not resolved.is_dir():
        raise InputError(f"{summaries_dir}: not a directory")
    files = sorted(p for p in resolved.iterdir() if p.is_file() and p.suffix == ".md")
    if not files:
        raise InputError(f"{summaries_dir}: no *.md summaries found")
    return files


def _file_findings(pf: parse.ParsedFile, in_range: bool) -> list[Finding]:
    """Every per-file check. Blocking is applied by the caller."""
    out: list[Finding] = []
    name = pf.path
    prefix = pf.prefix_chapter

    def add(code, line, message, expected=None, found=None):
        out.append(Finding(name, line, code, message, expected, found, False, in_range))

    if prefix is None:
        add(
            schema.NO_NUMERIC_PREFIX,
            None,
            "filename has no numeric chapter prefix, so the file cannot be placed in a chapter",
            "NNN-<name>.md",
            name.rsplit("/", 1)[-1],
        )
    if pf.title_chapter is None:
        add(
            schema.MISSING_TITLE,
            None,
            "no `# Chapter N` title line",
            f"# Chapter {prefix}" if prefix is not None else "# Chapter N",
            pf.first_h1,
        )
    elif prefix is not None and pf.title_chapter != prefix:
        add(
            schema.TITLE_CHAPTER_MISMATCH,
            pf.title_line,
            "title chapter disagrees with the filename prefix; fix the summary",
            f"# Chapter {prefix}",
            f"# Chapter {pf.title_chapter}",
        )

    scenes_sec = pf.section(schema.SCENES)
    if scenes_sec is None:
        add(schema.MISSING_SCENES, None, "no `## Scenes` section", "## Scenes", None)
    elif not scenes_sec.entries:
        add(
            schema.EMPTY_SCENES,
            scenes_sec.line,
            "`## Scenes` has no `###` scene headings",
            "### NNN.SS <title>",
            None,
        )
    seen: dict[str, int] = {}
    for sc in pf.scenes:
        if sc.source_scene_id is None:
            add(
                schema.BAD_SCENE_ID,
                sc.line,
                "scene heading does not start with an `NNN.SS` id",
                "### NNN.SS <title>",
                f"### {sc.heading}",
            )
            continue
        if prefix is not None and int(sc.source_scene_id.split(".")[0]) != prefix:
            add(
                schema.SCENE_CHAPTER_MISMATCH,
                sc.line,
                "scene id's chapter part disagrees with the filename prefix",
                f"{prefix:03d}.SS",
                sc.source_scene_id + " " + sc.title,
            )
        if sc.source_scene_id in seen:
            add(
                schema.DUPLICATE_SCENE_ID,
                sc.line,
                f"scene id already used at line {seen[sc.source_scene_id]}",
                "unique scene id",
                sc.source_scene_id,
            )
        else:
            seen[sc.source_scene_id] = sc.line

    for sec in pf.sections:
        if sec.name not in schema.RECOGNISED_SECTIONS:
            add(
                schema.UNKNOWN_SECTION,
                sec.line,
                "unrecognised `##` section; preserved in other_sections.md",
                None,
                sec.name,
            )
    return out


def scan(
    summaries_dir: Path,
    campaign_root: Path,
    since: int | None,
    until: int | None,
    registry=None,
    rulings=None,
    dup_threshold: float = schema.DEFAULT_DUP_THRESHOLD,
) -> ValidationReport:
    """Validate every summary in ``summaries_dir``. See the module docstring."""
    files = _check_input_dir(Path(summaries_dir))
    parsed: list[parse.ParsedFile] = []
    parsed_paths: list[Path] = []
    unreadable: list[tuple[str, int | None, str]] = []
    for p in files:
        try:
            parsed.append(parse.parse_file(p, campaign_root))
            parsed_paths.append(p)
        except (OSError, UnicodeDecodeError) as e:
            rel = _rel(p, campaign_root)
            unreadable.append((rel, _chapter_of(rel), f"cannot read file: {e}"))

    rng = ChapterRange.resolve(
        [pf.prefix_chapter for pf in parsed if pf.prefix_chapter is not None]
        + [ch for _, ch, _ in unreadable if ch is not None],
        since,
        until,
    )

    def in_range(pf: parse.ParsedFile) -> bool:
        # A file with no prefix cannot be placed in any range; it breaks the
        # corpus regardless, so it counts as in range.
        return pf.prefix_chapter is None or rng.contains(pf.prefix_chapter)

    findings: list[Finding] = []
    for pf in parsed:
        ir = in_range(pf)
        for f in _file_findings(pf, ir):
            blocking = f.code in schema.BLOCKING_CODES and ir
            findings.append(Finding(**{**asdict(f), "blocking": blocking}))

    n_unreadable_in_range = 0
    for rel, ch, msg in unreadable:
        ir = ch is None or rng.contains(ch)
        n_unreadable_in_range += ir
        findings.append(
            Finding(rel, None, schema.UNREADABLE_FILE, msg, "a UTF-8 readable file", None, ir, ir)
        )

    by_chapter: dict[int, list[parse.ParsedFile]] = {}
    for pf in parsed:
        if pf.prefix_chapter is not None:
            by_chapter.setdefault(pf.prefix_chapter, []).append(pf)
    for ch in sorted(by_chapter):
        group = by_chapter[ch]
        if len(group) < 2:
            continue
        for pf in group:
            others = ", ".join(o.path.rsplit("/", 1)[-1] for o in group if o is not pf)
            findings.append(
                Finding(
                    pf.path,
                    None,
                    schema.DUPLICATE_CHAPTER,
                    f"chapter {ch} is claimed by more than one file; ordering would be ambiguous",
                    "one file per chapter number",
                    f"also: {others}",
                    True,
                    in_range(pf),
                )
            )

    dir_rel = _rel(Path(summaries_dir), campaign_root)
    for gap in rng.gaps:
        findings.append(
            Finding(
                dir_rel,
                None,
                schema.RANGE_GAP,
                f"chapter {gap} has no file inside the range",
                None,
                str(gap),
                False,
                True,
            )
        )

    from pipelines.summary_native import corpus, duplicates

    obs = corpus.build_observations(
        sorted(
            (pf for pf in parsed if pf.prefix_chapter is not None and rng.contains(pf.prefix_chapter)),
            key=lambda pf: (pf.prefix_chapter, pf.path),
        ),
        duplicates.make_grouper(registry),
    )
    rulings = rulings if rulings is not None else duplicates.Rulings()
    findings += duplicates.find_possible_duplicates(obs, registry, rulings, dup_threshold)
    findings += duplicates.stale_rulings(rulings, duplicates.headings_by_category(obs))

    findings.sort(key=_sort_key)
    return ValidationReport(
        dup_threshold=dup_threshold,
        summaries_dir=dir_rel,
        range=rng,
        files_scanned=len(parsed) + len(unreadable),
        files_in_range=sum(1 for pf in parsed if in_range(pf)) + n_unreadable_in_range,
        findings=findings,
        input_files=[
            p
            for p, pf in zip(parsed_paths, parsed)
            if pf.prefix_chapter is not None and rng.contains(pf.prefix_chapter)
        ],
    )
