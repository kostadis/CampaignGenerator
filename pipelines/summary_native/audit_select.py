"""The deterministic half of the tracking audit (spec 033 US6, FR-026). No model call.

``audit`` makes the one model call per item; every decision about what the model may be shown and
what its answer is worth is made here, by code (Principle II):

* :func:`load_items` numbers the ``- `` lines of the track files ``A1``, ``A2`` ...;
* :func:`candidate_chapters` picks the chapters an item is judged against (research R11): registry
  name forms found in the item, plus words of four or more letters outside the packaged generic word
  list, matched as whole words in each chapter's summary; the top ``n`` chapters with a hit;
* :func:`check_verdict` accepts SUPPORTED only for a citation inside those candidates and a verbatim
  span from the cited chapter, and otherwise downgrades the answer to NOT FOUND (``unverified``) and
  says why;
* :func:`render_audit_md` renders the verdicts, which is campaign_state's Audit section.

Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pipelines.summary_native import notes, npc_check, npc_forms, schema

SUPPORTED = "SUPPORTED"
NOT_FOUND = "NOT FOUND"
#: A call failed after its retry: the item has no verdict yet (the next run judges only these).
NOT_JUDGED = "NOT JUDGED"

# NOT FOUND reasons (stable strings; they appear in audit.json, audit.md and tests).
NO_CANDIDATES = "no-candidates"
NOT_SHOWN = "not-shown"
UNVERIFIED = "unverified"

#: A word shorter than this is never a distinctive token.
MIN_TOKEN_LETTERS = 4
#: A SUPPORTED span shorter than this (marks stripped) is too short to be evidence.
MIN_SPAN_CHARS = 8

_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_SHOWN_RE = re.compile(r"^\W*(NOT\s+SHOWN|SHOWN)\b", re.I)
_CITE_LINE_RE = re.compile(r"^\W*CITE\s*:", re.I)


# ── Items ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    id: str  # A1, A2 ... numbered across the files in the order given
    file: str  # the track file's name
    text: str


def load_items(track_files: Iterable[Path | str]) -> list[Item]:
    """Every ``- `` line of every track file, numbered ``A1``.. across the files in order.

    Raises ``OSError`` for a file that cannot be read; the caller names it.
    """
    items: list[Item] = []
    for p in track_files:
        p = Path(p)
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("- ") and line[2:].strip():
                items.append(Item(f"A{len(items) + 1}", p.name, line[2:].strip()))
    return items


# ── Candidate chapters ──────────────────────────────────────────────────────


def _whole(token: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(token)}(?!\w)", re.I)


def item_tokens(text: str, forms: Iterable[str], wordlist) -> list[str]:
    """The item's distinctive tokens, casefolded, in order of appearance.

    A registry form (``forms`` holds casefolded names and aliases) counts when it occurs in the item
    as whole words, unless it is a single generic word; every other word of four or more letters
    counts unless it is in ``wordlist`` (``npc_forms.load_wordlist``). Duplicates are kept once.
    """
    folded = text.casefold()
    found: list[tuple[int, str]] = []
    for form in forms:
        f = form.strip().casefold()
        if not f or f not in folded or npc_forms.is_generic_token(f, wordlist):
            continue
        m = _whole(f).search(folded)
        if m:
            found.append((m.start(), f))
    for m in _WORD_RE.finditer(text):
        w = m.group(0).casefold()
        if len(w) >= MIN_TOKEN_LETTERS and w not in wordlist:
            found.append((m.start(), w))
    out: list[str] = []
    for _, tok in sorted(found):
        if tok not in out:
            out.append(tok)
    return out


def score_chapters(tokens: Sequence[str], chapters: Sequence) -> list[tuple[int, int]]:
    """``[(chapter number, score)]`` for every chapter with a hit, best first.

    The score is the number of distinct tokens the chapter's summary contains as whole words; ties
    go to the earlier chapter, so the order never depends on anything but the text.
    """
    pats = [_whole(t) for t in tokens]
    scored = []
    for ch in chapters:
        n = sum(1 for p in pats if p.search(ch.text))
        if n:
            scored.append((ch.number, n))
    return sorted(scored, key=lambda s: (-s[1], s[0]))


def candidate_chapters(
    item: str, chapters: Sequence, forms: Iterable[str], wordlist, n: int = schema.DEFAULT_AUDIT_CANDIDATES
) -> list[int]:
    """The (at most ``n``) chapter numbers ``item`` is judged against, in chapter order.

    Empty when the item has no distinctive token or no chapter contains one; the audit then reports
    NOT FOUND (``no-candidates``) and makes no model call. Deterministic.
    """
    tokens = item_tokens(item, forms, wordlist)
    return sorted(num for num, _ in score_chapters(tokens, chapters)[: max(n, 0)])


# ── Verdicts ────────────────────────────────────────────────────────────────


@dataclass
class Verdict:
    verdict: str  # SUPPORTED | NOT FOUND | NOT JUDGED
    reason: str | None = None  # NOT FOUND only: no-candidates | not-shown | unverified
    citation: str | None = None  # SUPPORTED: "[ch NNN / target]"
    span: str | None = None  # SUPPORTED: verbatim, marks stripped
    #: unverified: why code did not accept the model's SHOWN (or its unreadable answer)
    detail: str | None = None
    #: not-shown / unverified: what the model said the evidence does show, kept only where its
    #: citations resolve inside the candidates and its quotations are verbatim
    partial: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {"verdict": self.verdict}
        for k in ("reason", "citation", "span", "detail"):
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        if self.partial:
            d["partial"] = list(self.partial)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Verdict":
        return cls(
            d.get("verdict", NOT_JUDGED), d.get("reason"), d.get("citation"), d.get("span"),
            d.get("detail"), list(d.get("partial") or []),
        )


def no_candidates() -> Verdict:
    return Verdict(NOT_FOUND, NO_CANDIDATES)


def _allowed(candidates: Mapping[int, object]) -> dict[int, set[str]]:
    return {n: set(ch.targets) for n, ch in candidates.items()}


def _partial(rest: str, candidates: Mapping[int, object]) -> list[str]:
    """The claims in the model's NOT SHOWN remark that code can stand behind: each ends in a
    citation inside the candidates, and any quotation in it is verbatim in the cited chapter."""
    allowed = _allowed(candidates)
    out = []
    for claim in notes.claims_of(rest):
        claim = " ".join(claim.split()).lstrip("-*• ").strip()
        if not claim or notes.cite_problem(claim, allowed):
            continue
        chapters = {ch for _, ch, _ in notes.cites(claim)}
        if any(notes.bad_span(claim, candidates[c].text) for c in chapters):
            continue
        out.append(claim)
    return out[:3]


def check_verdict(answer: str, candidates: Mapping[int, object]) -> Verdict:
    """The verdict for a judge's answer; ``candidates`` maps each candidate chapter number to its
    ``notes.Chapter``.

    The first line is SHOWN or NOT SHOWN. SHOWN is accepted (SUPPORTED) only when a ``CITE:`` line
    gives a citation that resolves to a scene or section of a candidate chapter and a quoted span
    of at least ``MIN_SPAN_CHARS`` characters that is verbatim in that chapter. Anything else is
    NOT FOUND (``unverified``) and ``detail`` says which check failed. NOT SHOWN is NOT FOUND
    (``not-shown``). An answer that starts with neither word claims nothing checkable and is
    ``unverified``.
    """
    lines = [ln for ln in (answer or "").splitlines() if ln.strip()]
    m = _SHOWN_RE.match(lines[0]) if lines else None
    if not m:
        return Verdict(NOT_FOUND, UNVERIFIED, detail="the answer did not begin with SHOWN or NOT SHOWN")
    rest = "\n".join(lines[1:])
    if re.sub(r"\s+", " ", m.group(1)).upper() == "NOT SHOWN":
        return Verdict(NOT_FOUND, NOT_SHOWN, partial=_partial(rest, candidates))

    def reject(why: str) -> Verdict:
        return Verdict(NOT_FOUND, UNVERIFIED, detail=why, partial=_partial(rest, candidates))

    cite_line = next((ln for ln in lines[1:] if _CITE_LINE_RE.match(ln)), None)
    if cite_line is None:
        return reject("SHOWN without a CITE line")
    found = notes.cites(cite_line)
    if not found:
        return reject("SHOWN without a citation")
    allowed = _allowed(candidates)
    for bracket, ch, tgt in found:
        if ch < 0:
            return reject(f"the citation {bracket} is not well formed")
        if ch not in candidates:
            return reject(f"the citation {bracket} is outside the candidate chapters "
                          f"({', '.join(f'{n:03d}' for n in sorted(candidates))})")
        if tgt not in allowed[ch] or ("." in tgt and int(tgt[:3]) != ch):
            return reject(f"the citation {bracket} does not resolve to a scene or section of chapter {ch:03d}")
    spans = npc_check.SPAN_RE.findall(cite_line)
    if not spans:
        return reject("SHOWN without a quoted span")
    span = npc_check.strip_quote_marks(spans[0])
    if len(span) < MIN_SPAN_CHARS:
        return reject(f"the span {spans[0]} is too short to be evidence")
    for bracket, ch, _ in found:
        if npc_check._contains(candidates[ch].text, span) is not None:
            return Verdict(SUPPORTED, citation=bracket, span=span)
    return reject(f"the span {spans[0]} is not verbatim in the cited chapter")


# ── Rendering ───────────────────────────────────────────────────────────────

_REASON_TEXT = {
    NO_CANDIDATES: "no candidate chapters",
    NOT_SHOWN: "the candidate chapters do not show it",
    UNVERIFIED: "unverified",
}


def counts_of(verdicts: Sequence[Mapping]) -> dict[str, int]:
    """``items``, ``supported``, ``not_found`` (with its three reasons) and ``not_judged``."""
    by = lambda pred: sum(1 for v in verdicts if pred(v))  # noqa: E731
    return {
        "items": len(verdicts),
        "supported": by(lambda v: v["verdict"] == SUPPORTED),
        "not_found": by(lambda v: v["verdict"] == NOT_FOUND),
        "no_candidates": by(lambda v: v.get("reason") == NO_CANDIDATES),
        "not_shown": by(lambda v: v.get("reason") == NOT_SHOWN),
        "unverified": by(lambda v: v.get("reason") == UNVERIFIED),
        "not_judged": by(lambda v: v["verdict"] == NOT_JUDGED),
    }


def summary_line(c: Mapping[str, int]) -> str:
    """``audit: 443 items — 171 SUPPORTED, 249 NOT FOUND (31 no candidates, 18 unverified)``."""
    tail = f", {c['not_judged']} NOT JUDGED" if c.get("not_judged") else ""
    return (
        f"audit: {c['items']} items — {c['supported']} SUPPORTED, {c['not_found']} NOT FOUND "
        f"({c['no_candidates']} no candidates, {c['unverified']} unverified){tail}"
    )


def render_audit_md(data: Mapping) -> str:
    """campaign_state's ``## Audit: Tracking Claims`` body, from ``audit.json``'s content.

    One ``###`` group per track file in the order the items were numbered; a SUPPORTED item lists its
    citation and span; a NOT FOUND item lists the reason (``unverified`` says which check failed) and
    any partial evidence the code could verify; a NOT JUDGED item says its call failed.
    """
    verdicts = list(data.get("verdicts") or [])
    out = [summary_line(data.get("counts") or counts_of(verdicts)), ""]
    cur = None
    for v in verdicts:
        if v.get("file") != cur:
            cur = v.get("file")
            out += [f"### {cur}", ""]
        head = f'- [{v["id"]}] "{v["text"]}" — '
        if v["verdict"] == SUPPORTED:
            out += [head + f"`{SUPPORTED}`", f'  - {v["citation"]} "{v["span"]}"']
        elif v["verdict"] == NOT_JUDGED:
            out.append(head + f"`{NOT_JUDGED}` (the model call failed; run `summary_native audit` again)")
        else:
            reason = v.get("reason")
            out.append(head + f"`{NOT_FOUND}` ({_REASON_TEXT.get(reason, reason)})")
            if v.get("detail"):
                out.append(f"  - not accepted: {v['detail']}")
            out += [f"  - partial: {p}" for p in v.get("partial") or []]
    return "\n".join(out).rstrip() + "\n"
