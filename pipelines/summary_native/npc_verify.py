"""Mechanical trust report for an NPC draft dossier (spec 032 T028, research R10, FR-024).

Deterministic. No model, never edits a draft. Reports, with the draft line of each:

* ``invalid`` / ``outside-evidence`` citations;
* ``not-found`` quotes (not verbatim in this NPC's evidence) and ``citation-mismatch`` quotes
  (verbatim, but not in the item the citation names);
* ``uncited`` History bullets (a bullet with cited bullets nested under it is a label);
* manual edits ``dropped`` (never cited) or cited ``invalid``.

``typography-normalised`` quotes, ``placeholder-speaker`` attributions and
``status-claim-unsupported`` wording are advisories: they never change the verdict.

The quote and citation primitives are ``npc_check``'s, shared with the chunked map check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from campaignlib.util import atomic_write_text
from pipelines.summary_native import npc_check, npc_link, parse, schema

PASS, FAIL = "pass", "fail"
INVALID = "invalid"
OUTSIDE_EVIDENCE = "outside-evidence"
NOT_FOUND = npc_check.NOT_FOUND
CITATION_MISMATCH = npc_check.CITATION_MISMATCH
UNCITED = "uncited"
MANUAL_DROPPED = "manual-dropped"
MANUAL_INVALID = "manual-invalid"
FAIL_CODES = (INVALID, OUTSIDE_EVIDENCE, NOT_FOUND, CITATION_MISMATCH, UNCITED, MANUAL_DROPPED, MANUAL_INVALID)
TYPOGRAPHY = npc_check.TYPOGRAPHY
STATUS_UNSUPPORTED = "status-claim-unsupported"
PLACEHOLDER = "placeholder-speaker"

STATUS_WORDS = ("alive", "dead", "died", "killed", "slain", "missing", "departed", "captured", "freed")
USED_NOT_MEANING = (
    "This check confirms each manual edit was used (cited at least once). It does not confirm "
    "that the edit's meaning survived the rewrite: read each cited passage beside its edit."
)
_STATUS_RE = re.compile(r"\b(" + "|".join(STATUS_WORDS) + r")\b", re.IGNORECASE)
LAST_STATE = "## Last Observed State"

CITATION_CHECK = "citation"
QUOTE_CHECK = "quote"
HISTORY_CHECK = "history"
MANUAL_CHECK = "manual"
STATUS_CHECK = "status-word"
CHECK_IDS = (
    CITATION_CHECK,
    QUOTE_CHECK,
    HISTORY_CHECK,
    MANUAL_CHECK,
    STATUS_CHECK,
)


@dataclass(frozen=True)
class CorpusIndex:
    """What exists in the in-range corpus: chapters and scene ids."""

    chapters: frozenset[int]
    scenes: frozenset[str]

    @property
    def targets(self) -> frozenset[tuple[int, str]]:
        t = {(c, "entry") for c in self.chapters} | {(c, "moment") for c in self.chapters}
        t |= {(int(s[:3]), s) for s in self.scenes}
        return frozenset(t)

    @classmethod
    def from_parsed(cls, files) -> "CorpusIndex":
        chapters, scenes = set(), set()
        for pf in files:
            ch = pf.title_chapter if pf.title_chapter is not None else pf.prefix_chapter
            if ch is not None:
                chapters.add(int(ch))
            scenes.update(s.source_scene_id for s in pf.scenes if s.source_scene_id)
        return cls(frozenset(chapters), frozenset(scenes))


def load_summaries_text(paths) -> str:
    return "\n".join(Path(p).read_text(encoding="utf-8") for p in sorted(paths))


@dataclass(frozen=True)
class Finding:
    code: str
    line: int  # 1-based line of the draft file; 0 when the finding is about the draft as a whole
    text: str
    detail: str = ""


@dataclass(frozen=True)
class ManualUse:
    n: int
    text: str
    cited: tuple[tuple[int, str], ...]  # (draft line, that line's text)


@dataclass
class VerificationResult:
    verdict: str
    failures: list[Finding]
    advisories: list[Finding]
    counts: dict[str, int]  # every FAIL_CODE, plus typography-normalised, status-claim-unsupported, placeholder-speaker
    totals: dict = field(default_factory=dict)
    manual: list[ManualUse] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == PASS

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "counts": dict(sorted(self.counts.items())),
            "totals": self.totals,
            "failures": [f.__dict__ for f in self.failures],
            "advisories": [f.__dict__ for f in self.advisories],
            "manual": [
                {"n": m.n, "text": m.text, "cited": [list(c) for c in m.cited]} for m in self.manual
            ],
        }

    def summary_line(self) -> str:
        c = self.counts
        if self.passed:
            bits = []
        else:
            bits = [f"{k} {c[k]}" for k in FAIL_CODES if c.get(k)]
        adv = [f"{k} {c[k]}" for k in (TYPOGRAPHY, STATUS_UNSUPPORTED, PLACEHOLDER) if c.get(k)]
        head = f"{self.verdict} ({', '.join(bits)})" if bits else self.verdict
        return head + (f"; advisories: {', '.join(adv)}" if adv else "")


def _strip_frontmatter(text: str) -> str:
    return npc_link.split_frontmatter(text)[1] if text.startswith("---\n") else text


@dataclass(frozen=True)
class VerificationContext:
    """Parsed immutable inputs shared by independently runnable checks."""

    draft_text: str
    evidence: npc_check.EvidenceIndex
    corpus_index: CorpusIndex
    summaries_text: str
    manual: tuple[str, ...]
    lines: tuple[str, ...]
    sections: dict[str, tuple[int, list[str]]]
    body_start: int


@dataclass
class ScopedCheckResult:
    failures: list[Finding] = field(default_factory=list)
    advisories: list[Finding] = field(default_factory=list)
    totals: dict = field(default_factory=dict)
    manual: list[ManualUse] = field(default_factory=list)


def build_context(
    draft_text: str,
    evidence_dossier: str,
    corpus_index: CorpusIndex,
    summaries_text: str,
    manual: list[str],
) -> VerificationContext:
    """Parse shared inputs without running any verification check."""

    evidence = npc_check.EvidenceIndex.of(npc_check.split_chapters(_strip_frontmatter(evidence_dossier)))
    lines = tuple(draft_text.splitlines())
    sections = npc_check.parse_sections(draft_text)
    body_start = next((n for n, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    return VerificationContext(
        draft_text=draft_text,
        evidence=evidence,
        corpus_index=corpus_index,
        summaries_text=summaries_text,
        manual=tuple(manual),
        lines=lines,
        sections=sections,
        body_start=body_start,
    )


def check_citations(context: VerificationContext) -> ScopedCheckResult:
    """Check only corpus/evidence membership of source citations."""

    n_cites = n_valid = 0
    failures: list[Finding] = []
    for n in range(context.body_start, len(context.lines)):
        for bracket, (ch, tgt) in npc_check.citation_parts(context.lines[n]):
            n_cites += 1
            if (
                ch < 0
                or not npc_check.scene_chapter_ok(ch, tgt)
                or (ch, tgt) not in context.corpus_index.targets
            ):
                failures.append(Finding(INVALID, n + 1, bracket, "not in the in-range corpus"))
            elif (ch, tgt) not in context.evidence.targets:
                failures.append(Finding(OUTSIDE_EVIDENCE, n + 1, bracket, "real, but not in this NPC's evidence"))
            else:
                n_valid += 1
    return ScopedCheckResult(
        failures=failures,
        totals={"citations": n_cites, "citations_valid": n_valid},
    )


def check_quotes(context: VerificationContext) -> ScopedCheckResult:
    """Check only notable quotes, inline quoted spans, and attribution placeholders."""

    failures: list[Finding] = []
    advisories: list[Finding] = []
    by_source: dict[str, int] = {}
    quote_lines: set[int] = set()
    n_quotes = 0
    first, qlines = context.sections.get(schema.MAP_SECTIONS[1], (0, []))
    for q in npc_check.quotes_in(qlines, first):
        n_quotes += 1
        chk = npc_check.check_quote(q.text, q.attribution, context.evidence)
        loc = q.line + 1
        if chk.status == NOT_FOUND:
            where = (
                " (verbatim in the summaries, not in this NPC's evidence)"
                if _in_summaries(q.text, context.summaries_text)
                else ""
            )
            failures.append(Finding(NOT_FOUND, loc, q.text, chk.detail + where))
        elif chk.status == CITATION_MISMATCH:
            failures.append(Finding(CITATION_MISMATCH, loc, q.text, chk.detail))
        else:
            by_source[chk.source or "unknown"] = by_source.get(chk.source or "unknown", 0) + 1
            if chk.status == TYPOGRAPHY:
                advisories.append(Finding(TYPOGRAPHY, loc, q.text, "differs only in quote marks or apostrophes"))
        if npc_check.placeholder_speaker(q):
            advisories.append(Finding(PLACEHOLDER, loc, q.text, "attribution is missing or a placeholder"))
    for off, ln in enumerate(qlines):
        if ln.lstrip().startswith(">"):
            quote_lines.add(first + off)
    n_spans = 0
    for n in range(context.body_start, len(context.lines)):
        if n in quote_lines:
            continue
        for span in npc_check.SPAN_RE.findall(context.lines[n]):
            n_spans += 1
            verdict, _ = npc_check.in_evidence(span, context.evidence)
            if verdict is None:
                failures.append(Finding(NOT_FOUND, n + 1, span, "quoted span not verbatim in this NPC's evidence"))
            elif verdict == TYPOGRAPHY:
                advisories.append(Finding(TYPOGRAPHY, n + 1, span, "differs only in quote marks or apostrophes"))
    return ScopedCheckResult(
        failures=failures,
        advisories=advisories,
        totals={
            "quotes": n_quotes,
            "quotes_by_source": dict(sorted(by_source.items())),
            "quoted_spans": n_spans,
        },
    )


def check_history(context: VerificationContext) -> ScopedCheckResult:
    """Check only leaf History bullets for a source or manual pointer."""

    failures: list[Finding] = []
    first, hlines = context.sections.get(schema.MAP_SECTIONS[0], (0, []))
    bl = npc_check.bullets(hlines, first)
    n_leaf = 0
    for i, b in enumerate(bl):
        has_nested = i + 1 < len(bl) and bl[i + 1].indent > b.indent
        if has_nested:
            continue
        n_leaf += 1
        if not (schema.CITATION_RE.search(b.text) or schema.MANUAL_CITATION_RE.search(b.text)):
            failures.append(Finding(UNCITED, b.line + 1, b.text, "no citation"))
    return ScopedCheckResult(
        failures=failures,
        totals={"history_bullets": n_leaf},
    )


def check_manual(context: VerificationContext) -> ScopedCheckResult:
    """Check only manual pointer bounds and whether each authored edit was retained."""

    failures: list[Finding] = []
    uses = {n: [] for n in range(1, len(context.manual) + 1)}
    for n in range(context.body_start, len(context.lines)):
        for m in schema.MANUAL_CITATION_RE.finditer(context.lines[n]):
            k = int(m.group(1))
            if k in uses:
                uses[k].append((n + 1, context.lines[n].strip()))
            else:
                failures.append(Finding(
                    MANUAL_INVALID,
                    n + 1,
                    m.group(0),
                    f"the authored file has {len(context.manual)} manual edits",
                ))
    manual_uses = []
    for k, text in enumerate(context.manual, 1):
        manual_uses.append(ManualUse(k, text, tuple(dict.fromkeys(uses[k]))))
        if not uses[k]:
            failures.append(Finding(MANUAL_DROPPED, 0, f"manual edit {k}: {text}", "never cited as [manual %d]" % k))
    return ScopedCheckResult(
        failures=failures,
        totals={"manual_edits": len(context.manual)},
        manual=manual_uses,
    )


def check_status_words(context: VerificationContext) -> ScopedCheckResult:
    """Check only deterministic status words against the complete evidence text."""

    advisories: list[Finding] = []
    ev_text = context.evidence.text
    flo, fl = context.sections.get(LAST_STATE, (0, []))
    scopes = [(flo, fl), context.sections.get(schema.MAP_SECTIONS[0], (0, []))]
    seen: set[tuple[int, str]] = set()
    for start, sl in scopes:
        for off, ln in enumerate(sl):
            for m in _STATUS_RE.finditer(ln):
                w = m.group(1).casefold()
                if (start + off, w) in seen:
                    continue
                seen.add((start + off, w))
                if not re.search(rf"\b{w}\b", ev_text, re.IGNORECASE):
                    advisories.append(Finding(STATUS_UNSUPPORTED, start + off + 1, ln.strip(), f'"{w}" appears nowhere in the evidence'))
    return ScopedCheckResult(advisories=advisories)


def scoped_checkers() -> dict[str, object]:
    """Return the stable public check-id mapping used by selected reruns."""

    return {
        CITATION_CHECK: check_citations,
        QUOTE_CHECK: check_quotes,
        HISTORY_CHECK: check_history,
        MANUAL_CHECK: check_manual,
        STATUS_CHECK: check_status_words,
    }


def verify_scoped(
    draft_text: str,
    evidence_dossier: str,
    corpus_index: CorpusIndex,
    summaries_text: str,
    manual: list[str],
    check_ids,
) -> VerificationResult:
    """Run exactly the named deterministic checks over shared parsed inputs."""

    selected = tuple(check_ids)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("verification requires unique explicit check ids")
    checkers = scoped_checkers()
    unknown = [check_id for check_id in selected if check_id not in checkers]
    if unknown:
        raise ValueError(f"unknown verification check id: {unknown[0]}")
    context = build_context(
        draft_text,
        evidence_dossier,
        corpus_index,
        summaries_text,
        manual,
    )
    failures: list[Finding] = []
    advisories: list[Finding] = []
    totals: dict = {}
    manual_uses: list[ManualUse] = []
    for check_id in selected:
        result = checkers[check_id](context)
        failures.extend(result.failures)
        advisories.extend(result.advisories)
        totals.update(result.totals)
        if check_id == MANUAL_CHECK:
            manual_uses = result.manual

    counts = {k: 0 for k in FAIL_CODES}
    for f in failures:
        counts[f.code] += 1
    for k in (TYPOGRAPHY, STATUS_UNSUPPORTED, PLACEHOLDER):
        counts[k] = sum(1 for a in advisories if a.code == k)
    return VerificationResult(
        verdict=FAIL if failures else PASS,
        failures=sorted(failures, key=lambda f: (f.line, f.code, f.text)),
        advisories=sorted(advisories, key=lambda f: (f.line, f.code, f.text)),
        counts=counts,
        totals=totals,
        manual=manual_uses,
    )


def verify(
    draft_text: str,
    evidence_dossier: str,
    corpus_index: CorpusIndex,
    summaries_text: str,
    manual: list[str],
) -> VerificationResult:
    """Run the complete legacy verifier through the scoped check functions."""

    return verify_scoped(
        draft_text,
        evidence_dossier,
        corpus_index,
        summaries_text,
        manual,
        CHECK_IDS,
    )


def _in_summaries(quote: str, summaries_text: str) -> bool:
    inner = npc_check.strip_quote_marks(quote)
    return bool(inner) and npc_check._contains(summaries_text, inner) is not None


def render_verify_md(result: VerificationResult, npc: str = "") -> str:
    out = [f"# Verification: {npc}".rstrip(), "", f"**Verdict: {result.verdict}**", "", "## Totals", ""]
    t = result.totals
    out += [
        f"- citations: {t.get('citations', 0)} ({t.get('citations_valid', 0)} valid)",
        f"- notable quotes: {t.get('quotes', 0)}; by source: {t.get('quotes_by_source') or {}}",
        f"- other quoted spans: {t.get('quoted_spans', 0)}",
        f"- history bullets needing a citation: {t.get('history_bullets', 0)}",
        f"- manual edits: {t.get('manual_edits', 0)}",
        "",
        "## Failures",
        "",
    ]
    if result.failures:
        for f in result.failures:
            at = f"line {f.line}" if f.line else "draft"
            out.append(f"- {f.code} ({at}): {f.text}" + (f" -- {f.detail}" if f.detail else ""))
    else:
        out.append("None.")
    out += ["", "## Manual edits", "", USED_NOT_MEANING, ""]
    if result.manual:
        for m in result.manual:
            out.append(f"- [manual {m.n}] {m.text}")
            if m.cited:
                out += [f"  - line {ln}: {txt}" for ln, txt in m.cited]
            else:
                out.append("  - DROPPED: not cited anywhere in the draft")
    else:
        out.append("None.")
    out += ["", "## Advisories (do not change the verdict)", ""]
    if result.advisories:
        for a in result.advisories:
            out.append(f"- {a.code} (line {a.line}): {a.text}" + (f" -- {a.detail}" if a.detail else ""))
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


def load_context(root: Path, report) -> tuple[CorpusIndex, str]:
    """The in-range corpus index and summaries text, from a validation report's input files."""
    files = [parse.parse_file(p, root) for p in sorted(report.input_files)]
    return CorpusIndex.from_parsed(files), load_summaries_text(report.input_files)


def verify_draft(draft_dir: Path, stem: str, subject: str, ev, manual: list[str], ctx) -> VerificationResult:
    """Verify ``<draft_dir>/<stem>.md`` and write ``<stem>.verify.md``. The draft is never touched."""
    index, summaries = ctx
    text = (Path(draft_dir) / f"{stem}.md").read_text(encoding="utf-8")
    result = verify(text, ev.body, index, summaries, manual)
    atomic_write_text(Path(draft_dir) / f"{stem}.verify.md", render_verify_md(result, subject))
    return result
