"""Checks on reconstructed grounding candidates (spec 039, FR-015, T031).

Three deterministic checks run over (baseline, candidate) pairs:

* **headings** are *counted*, not set-compared, so an accidentally deleted repeated heading is caught;
* **table width**: every row of a table has one column count, and a table that exists in the baseline
  keeps its width;
* **citation targets**: a citation the candidate introduces must resolve against a target already
  inherited from the baseline's own citations or against a target of a selected new source.

``propose_consistency_findings`` is the only function here that calls a model.  It returns findings
and nothing else; a report never carries an approval (a model verdict does not approve anything).
"""

from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field

from campaignlib import stream_api
from pipelines.summary_native.delta.client import delta_client

from .errors import EXIT_REFUSAL, DeltaRefusal
from .grounding_edits import _revisions, _write_new, edits_dir

HEADING_LOST = "HEADING_LOST"
HEADING_ADDED = "HEADING_ADDED"
TABLE_WIDTH = "TABLE_WIDTH"
CITATION_UNRESOLVED = "CITATION_UNRESOLVED"
CITATION_CUSTODY = "CITATION_CUSTODY"
CONSISTENCY = "CONSISTENCY_MODEL"
BLOCKING_CODES = frozenset({HEADING_LOST, TABLE_WIDTH, CITATION_UNRESOLVED, CITATION_CUSTODY})

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CITE_BRACKET = re.compile(r"\[(ch \d{3} / [^\]]*)\]")
_CITE_PART = re.compile(r"ch (\d{3}) / ([^;\]]+)")
_PIPE = re.compile(r"(?<!\\)\|")
_SCENE = re.compile(r"^#{2,4}\s+(\d{3}\.\d{2})\b", re.M)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    document: str
    line: int  # 1-based line in the candidate; 0 when about the document as a whole
    detail: str
    severity: str  # "blocking" | "info" | "advisory"


class CheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[Finding] = Field(default_factory=list)
    approval: None = None  # a check never approves

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def passed(self) -> bool:
        return not self.blocking


def _text_lines(data: bytes) -> list[str]:
    return data.decode("utf-8", "replace").splitlines()


def headings(data: bytes) -> Counter:
    """Heading (level, normalised text) counts, ignoring fenced code."""
    counts: Counter = Counter()
    fenced = False
    for line in _text_lines(data):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _HEADING.match(line)
        if m:
            counts[(len(m.group(1)), " ".join(m.group(2).split()))] += 1
    return counts


def _width(row: str) -> int:
    s = row.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return len(_PIPE.split(s))


def tables(data: bytes) -> list[tuple[int, list[tuple[int, str]]]]:
    """Table blocks as ``(first_line, [(line_no, row)...])``; a block is consecutive ``|`` lines."""
    blocks, current, fenced = [], [], False
    for n, line in enumerate(_text_lines(data), start=1):
        if _FENCE.match(line):
            fenced = not fenced
        if not fenced and line.lstrip().startswith("|"):
            current.append((n, line))
            continue
        if current:
            blocks.append((current[0][0], current))
            current = []
    if current:
        blocks.append((current[0][0], current))
    return blocks


def citations(data: bytes) -> set[tuple[int, str]]:
    out: set[tuple[int, str]] = set()
    for line in _text_lines(data):
        for bracket in _CITE_BRACKET.finditer(line):
            for m in _CITE_PART.finditer(bracket.group(0)):
                out.add((int(m.group(1)), m.group(2).strip()))
    return out


def new_targets_for_sources(sources: Mapping[int, str]) -> frozenset[tuple[int, str]]:
    """Targets a selected new chapter really offers: its scene ids plus its entry/moment spans."""
    out: set[tuple[int, str]] = set()
    for chapter, text in sources.items():
        out |= {(chapter, "entry"), (chapter, "moment")}
        out |= {(chapter, s) for s in _SCENE.findall(text)}
    return frozenset(out)


def check_headings(name: str, baseline: bytes, candidate: bytes) -> list[Finding]:
    before, after = headings(baseline), headings(candidate)
    found = []
    for key in sorted(before):
        if after[key] < before[key]:
            level, text = key
            found.append(Finding(
                code=HEADING_LOST, document=name, line=0, severity="blocking",
                detail=f"heading {'#' * level} {text!r} appears {after[key]} time(s), baseline had {before[key]}"))
    for key in sorted(after):
        if after[key] > before[key]:
            level, text = key
            found.append(Finding(
                code=HEADING_ADDED, document=name, line=0, severity="info",
                detail=f"heading {'#' * level} {text!r} appears {after[key]} time(s), baseline had {before[key]}"))
    return found


def check_tables(name: str, baseline: bytes, candidate: bytes) -> list[Finding]:
    base_tables = tables(baseline)
    base_widths = {rows[0][1].strip(): _width(rows[0][1]) for _n, rows in base_tables}
    cand_tables = tables(candidate)
    positional = len(base_tables) == len(cand_tables)  # same tables, edited header: match by order
    found = []
    for index, (start, rows) in enumerate(cand_tables):
        widths = {_width(r) for _n, r in rows}
        if len(widths) > 1:
            bad = next(n for n, r in rows if _width(r) != _width(rows[0][1]))
            found.append(Finding(
                code=TABLE_WIDTH, document=name, line=bad, severity="blocking",
                detail=f"table at line {start} has rows of different column counts {sorted(widths)}"))
            continue
        expected = base_widths.get(rows[0][1].strip())
        if expected is None and positional:
            expected = _width(base_tables[index][1][0][1])
        if expected is not None and expected != next(iter(widths)):
            found.append(Finding(
                code=TABLE_WIDTH, document=name, line=start, severity="blocking",
                detail=f"table at line {start} has {next(iter(widths))} columns, baseline had {expected}"))
    return found


def check_citations(name: str, inherited: set[tuple[int, str]], candidate: bytes,
                    new_targets: frozenset[tuple[int, str]], custody=None) -> list[Finding]:
    """With ``custody``, a target held by the baseline's own custody resolves too, and a chapter that is
    not a selected source is judged by :func:`check_custody` (one finding, not two)."""
    new_chapters = {c for c, _t in new_targets}
    found = []
    for n, line in enumerate(_text_lines(candidate), start=1):
        for bracket in _CITE_BRACKET.finditer(line):
            for m in _CITE_PART.finditer(bracket.group(0)):
                target = (int(m.group(1)), m.group(2).strip())
                if target in inherited or target in new_targets:
                    continue
                if custody is not None and target[0] not in new_chapters:
                    continue  # check_custody resolves it or blocks it, once
                found.append(Finding(
                    code=CITATION_UNRESOLVED, document=name, line=n, severity="blocking",
                    detail=f"[ch {target[0]:03d} / {target[1]}] is neither inherited from the "
                           "baseline nor a target of a selected source"))
    return found


def check_custody(candidate: Mapping[str, bytes], new_chapters: frozenset[int], resolver) -> list[Finding]:
    """Every INHERITED citation (a chapter no selected source covers) must resolve through baseline custody.

    ``resolver`` is ``baseline.custody_resolver(...)``.  A citation whose support the baseline does not
    hold blocks with a targeted repair message (FR-016, SC-009); the check never invents support.
    """
    found: list[Finding] = []
    for name in sorted(candidate):
        for n, line in enumerate(_text_lines(candidate[name]), start=1):
            for bracket in _CITE_BRACKET.finditer(line):
                for m in _CITE_PART.finditer(bracket.group(0)):
                    chapter, entry = int(m.group(1)), m.group(2).strip()
                    if chapter in new_chapters or resolver(chapter, entry) is not None:
                        continue
                    found.append(Finding(
                        code=CITATION_CUSTODY, document=name, line=n, severity="blocking",
                        detail=f"inherited citation [ch {chapter:03d} / {entry}] has no baseline custody: chapter "
                               f"{chapter:03d} is not a selected source and the baseline does not hold it. Restore "
                               "the line that carried this support, or select the chapter as a source and re-plan."))
    return found


def check_documents(baseline: Mapping[str, bytes], candidate: Mapping[str, bytes], *,
                    new_targets: frozenset[tuple[int, str]] = frozenset(),
                    custody=None) -> CheckReport:
    """Deterministic preservation checks; never a model call, never an approval.

    ``custody`` is an optional ``baseline.custody_resolver``; when given, inherited citations must resolve
    through baseline custody.
    """
    inherited: set[tuple[int, str]] = set()
    for data in baseline.values():
        inherited |= citations(data)
    findings: list[Finding] = []
    for name in sorted(candidate):
        base = baseline.get(name, b"")
        findings += check_headings(name, base, candidate[name])
        findings += check_tables(name, base, candidate[name])
        findings += check_citations(name, inherited, candidate[name], new_targets, custody)
    if custody is not None:
        findings += check_custody(candidate, frozenset(c for c, _t in new_targets), custody)
    return CheckReport(findings=findings)


# --------------------------------------------------------------------------- the one model call

_SYSTEM = """You review proposed edits to a campaign's grounding documents for internal consistency. \
You are shown changed lines only, with the selected source text. Report contradictions between a \
changed line and the sources or neighbouring facts, and claims the sources do not support. You do not \
approve or reject anything. Reply with ONE JSON object: \
{"findings":[{"document":"...","line":0,"detail":"..."}]} ; an empty list if you find nothing."""


def _changed_view(baseline: Mapping[str, bytes], candidate: Mapping[str, bytes]) -> str:
    parts = []
    for name in sorted(candidate):
        a = _text_lines(baseline.get(name, b""))
        b = _text_lines(candidate[name])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            parts.append(f"## {name} line {j1 + 1}\n- before:\n" + "\n".join(a[i1:i2])
                         + "\n- after:\n" + "\n".join(b[j1:j2]))
    return "\n\n".join(parts)


def propose_consistency_findings(baseline: Mapping[str, bytes], candidate: Mapping[str, bytes],
                                 source_texts: Mapping[str, str], *, backend: str | None = None,
                                 model: str, client=None, max_tokens: int = 4000,
                                 client_options: dict | None = None) -> list[Finding]:
    """Bounded model review of the changed lines.  Returns findings only; sets no approval."""
    view = _changed_view(baseline, candidate)
    if not view:
        return []
    if client is None:
        client = delta_client(backend, model, client_options)
    user = ("## Selected sources\n" + "\n\n".join(f"### {p}\n{t}" for p, t in sorted(source_texts.items()))
            + "\n\n## Changed lines\n" + view)
    raw = stream_api(client, _SYSTEM, user, model, max_tokens=max_tokens, silent=True)
    body = raw.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", body, re.S)
    try:
        value = json.loads(fence.group(1) if fence else body)
        items = value["findings"]
        assert isinstance(items, list)
    except (ValueError, KeyError, AssertionError, TypeError) as exc:
        raise DeltaRefusal(f"the consistency reviewer's output is not usable ({exc!r}); "
                           "no findings were recorded", EXIT_REFUSAL) from exc
    out = []
    for item in items:
        if isinstance(item, dict) and str(item.get("detail", "")).strip():
            line = item.get("line", 0)
            out.append(Finding(code=CONSISTENCY, document=str(item.get("document", "")),
                               line=line if isinstance(line, int) else 0,
                               detail=str(item["detail"]), severity="advisory"))
    return out


# --------------------------------------------------------------------------- storage

def save_check_report(campaign_dir, plan_id: str, report: CheckReport, *, candidate_sha256: dict[str, str],
                      model_calls: int) -> dict:
    """Write ``check-r<N>.json`` (a new revision each time).  It binds the candidate digests it checked."""
    directory = edits_dir(campaign_dir, plan_id)
    existing = _revisions(directory, "check")
    revision = (existing[-1][0] + 1) if existing else 1
    record = {"plan_id": plan_id, "revision": revision, "passed": report.passed,
              "candidate_sha256": dict(sorted(candidate_sha256.items())), "model_calls": model_calls,
              "findings": [f.model_dump(mode="json") for f in report.findings], "approval": None}
    record["path"] = str(_write_new(directory, "check", revision, record))
    return record


def load_check_report(campaign_dir, plan_id: str) -> dict | None:
    files = _revisions(edits_dir(campaign_dir, plan_id), "check")
    return json.loads(files[-1][1].read_text(encoding="utf-8")) if files else None
