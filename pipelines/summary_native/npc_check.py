"""Quote, citation and attribution primitives for NPC dossiers (spec 032 T028 / T062).

One implementation, used by both the chunked map check (``npc_chunked``) and the standalone
verifier (``npc_verify``). Deterministic, no model, no file writes (guarded by
``tests/test_summary_native_no_llm.py``).

The rules (GM rulings 2026-10-06):

* a quote must be verbatim in the NPC's evidence (entries, scene bodies and moments alike);
  curly and straight quote marks and apostrophes compare as equal and are reported as
  ``typography-normalised``; any other changed character is ``not-found``;
* a quote is about the NPC and spoken by anyone; it names its speaker as the evidence gives it;
* a quote carries a citation that points at the item it comes from. A quote that is in the
  evidence but not in the cited item is a ``citation-mismatch``.

Verbatim matching uses ``campaignlib.textproc.locate_quote`` (exact, then whitespace-tolerant),
never similarity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from campaignlib.textproc import locate_quote
from pipelines.summary_native import schema

BRACKET_RE = re.compile(r"\[[^\[\]]*\]")
_META_LINE_RE = re.compile(r"^- (?:Source|Scene|Mention lines):")
_ITEM_HEAD_RE = re.compile(r"^### (Entry|Scene (\d{3}\.\d{2})|Moment)\b")

OK = "ok"
TYPOGRAPHY = "typography-normalised"
NOT_FOUND = "not-found"
CITATION_MISMATCH = "citation-mismatch"

# Every quote mark and apostrophe folds to one character: curly vs straight, and single vs
# double marks nested inside a quote (GM ruling 2026-10-06). One character for one, so offsets hold.
_FOLD = str.maketrans({"\u201c": "'", "\u201d": "'", "\u2018": "'", "\u2019": "'", '"': "'"})


def fold_typography(text: str) -> str:
    """All quote marks and apostrophes to one character."""
    return text.translate(_FOLD)


# ── Evidence ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Item:
    """One citable thing in an evidence dossier: an entry, a scene or a moment."""

    chapter: int
    target: str  # "entry" | "moment" | "NNN.SS"
    kind: str  # "entry" | "scene" | "moment"
    text: str  # the item's body, metadata lines removed


@dataclass(frozen=True)
class Chapter:
    number: int
    text: str  # the whole ``## Chapter NNN`` section, verbatim (what a chunk is made of)
    items: tuple[Item, ...]


def split_chapters(body: str) -> list[Chapter]:
    """Whole ``## Chapter NNN`` sections of an evidence body, in file order."""
    out = []
    for part in re.split(r"(?m)^(?=## Chapter \d+)", body):
        m = re.match(r"## Chapter (\d+)", part)
        if m:
            out.append(Chapter(int(m.group(1)), part, tuple(_items_of(int(m.group(1)), part))))
    return out


def _items_of(chapter: int, text: str):
    for blk in re.split(r"(?m)^(?=### )", text):
        m = _ITEM_HEAD_RE.match(blk)
        if not m:
            continue
        lines = blk.splitlines()[1:]
        body = "\n".join(ln for ln in lines if not _META_LINE_RE.match(ln)).strip()
        if m.group(1) == "Entry":
            yield Item(chapter, "entry", "entry", body)
        elif m.group(1) == "Moment":
            yield Item(chapter, "moment", "moment", body)
        else:
            yield Item(chapter, m.group(2), "scene", body)


@dataclass(frozen=True)
class EvidenceIndex:
    """The citable items of some evidence (a whole dossier, or one chunk of it)."""

    items: tuple[Item, ...]

    @classmethod
    def of(cls, chapters) -> "EvidenceIndex":
        return cls(tuple(i for c in chapters for i in c.items))

    @property
    def targets(self) -> frozenset[tuple[int, str]]:
        return frozenset((i.chapter, i.target) for i in self.items)

    def items_at(self, chapter: int, target: str) -> list[Item]:
        return [i for i in self.items if i.chapter == chapter and i.target == target]

    @property
    def text(self) -> str:
        return "\n\n".join(i.text for i in self.items)


# ── Markdown structure ──────────────────────────────────────────────────────


def parse_sections(text: str) -> dict[str, tuple[int, list[str]]]:
    """``{"## Heading": (first body line index, body lines)}`` for each ``## `` section."""
    secs: dict[str, tuple[int, list[str]]] = {}
    cur = None
    for n, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            cur = line.rstrip()
            secs.setdefault(cur, (n + 1, []))
        elif cur is not None:
            secs[cur][1].append(line)
    return secs


def section_text(secs: dict, heading: str) -> str:
    return "\n".join(secs.get(heading, (0, []))[1]).strip("\n")


@dataclass(frozen=True)
class Bullet:
    line: int  # 0-based index into the document
    indent: int
    text: str  # the bullet and its continuation lines, joined by single spaces


def bullets(lines: list[str], first_line: int = 0) -> list[Bullet]:
    out: list[Bullet] = []
    for n, raw in enumerate(lines):
        m = re.match(r"^(\s*)[-*] (.*)$", raw)
        if m:
            out.append(Bullet(first_line + n, len(m.group(1)), raw.strip()))
        elif out and raw.strip() and not raw.startswith("#") and not raw.lstrip().startswith(">"):
            last = out[-1]
            out[-1] = Bullet(last.line, last.indent, last.text + " " + raw.strip())
    return out


# ── Citations ───────────────────────────────────────────────────────────────


def citation_parts(text: str) -> list[tuple[str, tuple[int, str]]]:
    """Every ``[ch NNN / target]`` bracket in ``text`` as ``(bracket, (chapter, target))`` pairs,
    one per part. A bracket that starts ``[ch `` but breaks the grammar yields ``(bracket, None)``
    wrapped as ``(bracket, (-1, ""))`` so callers count it as invalid."""
    out = []
    for b in BRACKET_RE.findall(text):
        if not b.startswith("[ch "):
            continue
        if not schema.CITATION_RE.fullmatch(b):
            out.append((b, (-1, "")))
            continue
        for c, t in schema.CITATION_PART_RE.findall(b):
            out.append((b, (int(c), t)))
    return out


def scene_chapter_ok(chapter: int, target: str) -> bool:
    return "." not in target or int(target[:3]) == chapter


def cite_problems(
    text: str, evidence_targets, corpus_targets=None, *, outside: str = "outside-evidence"
) -> tuple[int, list[tuple[str, str]]]:
    """``(valid count, [(status, bracket), ...])``.

    ``invalid``: malformed, a scene id whose chapter part differs from the citation's chapter,
    or (when ``corpus_targets`` is given) a target absent from the corpus. ``outside`` names
    the status for a real target outside ``evidence_targets``.
    """
    ok, probs = 0, []
    for bracket, (ch, tgt) in citation_parts(text):
        if ch < 0 or not scene_chapter_ok(ch, tgt):
            probs.append(("invalid", bracket))
        elif corpus_targets is not None and (ch, tgt) not in corpus_targets:
            probs.append(("invalid", bracket))
        elif (ch, tgt) not in evidence_targets:
            probs.append((outside, bracket))
        else:
            ok += 1
    return ok, probs


# ── Quotes and attributions ─────────────────────────────────────────────────

_PAIR_RE = re.compile(
    r'(?P<q>["“].+?["”])\s*[—–]\s*(?P<a>[^"“\[]*?)\s*(?P<c>\[[^\]]*\])?(?=\s*["“]|\s*$)'
)
_DASH_RE = re.compile(r"^[—–-]{1,2}\s")
SPAN_RE = re.compile(r'“[^“”\n]+”|"[^"\n]+"')


@dataclass(frozen=True)
class QuoteRef:
    text: str  # as written, quote marks included
    attribution: str  # "— Speaker [ch NNN / moment]" or ""
    line: int  # 0-based index of the quote's first line in the document

    @property
    def speaker(self) -> str:
        a = re.sub(r"\[[^\]]*\]", "", self.attribution)
        return re.sub(r"^[—–-]+\s*", "", a).strip()


def quotes_in(lines: list[str], first_line: int = 0) -> list[QuoteRef]:
    """Blockquote quotes with their attributions.

    An attribution is split off in three placements: as the last line inside the blockquote,
    on the next plain line, or on the same line as the quote (several pairs may share a line).
    """
    out: list[QuoteRef] = []
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith(">"):
            i += 1
            continue
        blk: list[tuple[int, str]] = []
        while i < len(lines) and lines[i].lstrip().startswith(">"):
            blk.append((first_line + i, lines[i].lstrip()[1:].strip()))
            i += 1
        q: list[str] = []
        q_line = [0]

        def flush(attr: str = "") -> None:
            if q:
                out.append(QuoteRef(" ".join(q), attr, q_line[0]))
                q.clear()

        for n, ln in blk:
            if not ln:
                flush()
                continue
            if _DASH_RE.match(ln):
                flush(ln)
                continue
            pairs = list(_PAIR_RE.finditer(ln))
            if pairs:
                flush()
                for m in pairs:
                    attr = ("— " + m.group("a").strip() + " " + (m.group("c") or "")).strip()
                    out.append(QuoteRef(m.group("q"), attr, n))
            else:
                if not q:
                    q_line[0] = n
                q.append(ln)
        if q:
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _DASH_RE.match(lines[j].strip()):
                flush(lines[j].strip())
                i = j + 1
            else:
                flush()
    return out


def strip_quote_marks(q: str) -> str:
    q = q.strip()
    for a, b in (('"', '"'), ("“", "”"), ("“", '"'), ('"', "”")):
        if len(q) >= 2 and q[0] == a and q[-1] == b:
            return q[1:-1].strip()
    return q


def _contains(text: str, quote: str) -> str | None:
    """``ok`` (verbatim), ``typography-normalised``, or None.

    Normalised means equal after folding quote marks and apostrophes (curly/straight, single/
    double nested), or after moving a trailing comma or period back outside the closing mark.
    Any other changed character is not a match.
    """
    if locate_quote(quote, text) is not None:
        return OK
    folded = fold_typography(text)
    for cand in (quote, quote.rstrip(",.") if quote[-1:] in (",", ".") else None):
        if cand and locate_quote(fold_typography(cand), folded) is not None:
            return TYPOGRAPHY
    return None


@dataclass(frozen=True)
class QuoteCheck:
    status: str  # ok | typography-normalised | not-found | citation-mismatch
    source: str | None  # "moment" | "scene" | "entry": the kind of the item it was found in
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status in (OK, TYPOGRAPHY)


def in_evidence(quote: str, index: EvidenceIndex) -> tuple[str | None, str | None]:
    """``(verdict, kind)`` of the first item holding ``quote`` (exact wins over typography)."""
    inner = strip_quote_marks(quote)
    if not inner:
        return None, None
    best = (None, None)
    for it in index.items:
        v = _contains(it.text, inner)
        if v == OK:
            return OK, it.kind
        if v and best[0] is None:
            best = (v, it.kind)
    return best


def check_quote(quote: str, attribution: str, index: EvidenceIndex) -> QuoteCheck:
    """Verbatim in ``index``, and in an item the attribution's citation points at."""
    inner = strip_quote_marks(quote)
    anywhere, kind_any = in_evidence(quote, index)
    if anywhere is None:
        return QuoteCheck(NOT_FOUND, None, "not verbatim in this NPC's evidence")
    cited = citation_parts(attribution)
    if not cited:
        return QuoteCheck(CITATION_MISMATCH, kind_any, "no citation naming the item it comes from")
    verdict, kind = None, None
    for _, (ch, tgt) in cited:
        for it in index.items_at(ch, tgt):
            v = _contains(it.text, inner)
            if v == OK or (v and verdict is None):
                verdict, kind = v, it.kind
                if v == OK:
                    break
        if verdict == OK:
            break
    if verdict is None:
        where = "; ".join(b for b, _ in cited)
        return QuoteCheck(CITATION_MISMATCH, kind_any, f"found in the evidence but not in the cited item {where}")
    # typography-normalised if the best match anywhere needed folding too
    return QuoteCheck(verdict, kind)


def placeholder_speaker(ref: QuoteRef) -> bool:
    s = ref.speaker.casefold()
    return not s or s in schema.PLACEHOLDER_SPEAKERS


@dataclass
class QuoteReport:
    """Tallies a caller can print: quotes by source and by status."""

    by_source: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)

    def add(self, c: QuoteCheck) -> None:
        self.by_status[c.status] = self.by_status.get(c.status, 0) + 1
        if c.passed and c.source:
            self.by_source[c.source] = self.by_source.get(c.source, 0) + 1
