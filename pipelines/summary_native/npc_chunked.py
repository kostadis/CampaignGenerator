"""The deterministic half of chunked drafting (spec 032 T062, research R17). No model call.

``npc_draft`` makes the model calls; everything between them is here, so that no model
output reaches another model call unchecked:

    chunk (code) -> map call -> map check (code) -> stitch (code) -> reduce call -> assembly (code)

The map check uses the same quote and citation primitives as ``npc_verify`` (``npc_check``).
Guarded by ``tests/test_summary_native_no_llm.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pipelines.summary_native import context, npc_check, schema

HISTORY, QUOTES, ARC = schema.MAP_SECTIONS

# Drop reasons (stable strings; they appear in drops.md and in tests).
SPAN_NOT_FOUND = "quoted-span-not-found"
UNCITED = "uncited"
INVALID = "invalid-citation"
OUTSIDE_CHUNK = "outside-chunk"
NOT_FOUND = npc_check.NOT_FOUND
CITATION_MISMATCH = npc_check.CITATION_MISMATCH


# ── Chunking ────────────────────────────────────────────────────────────────


def make_chunks(chapters: list[npc_check.Chapter], limit: int) -> list[list[npc_check.Chapter]]:
    """Whole chapters, in order, packed until the next would exceed ``limit`` characters.

    A chapter larger than the limit is its own chunk. A chapter is never split.
    """
    chunks: list[list[npc_check.Chapter]] = []
    cur: list[npc_check.Chapter] = []
    size = 0
    for ch in chapters:
        if cur and size + len(ch.text) > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(ch)
        size += len(ch.text)
    if cur:
        chunks.append(cur)
    return chunks


def chunk_text(chunk: list[npc_check.Chapter]) -> str:
    return "".join(c.text for c in chunk)


def chunk_range(chunk: list[npc_check.Chapter]) -> str:
    return f"{chunk[0].number:03d}-{chunk[-1].number:03d}"


# ── Prompts ─────────────────────────────────────────────────────────────────


def load_map_system() -> str:
    return (context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.map.system.md").read_text(encoding="utf-8")


def load_reduce_system() -> str:
    return (context.PROMPT_DIR / f"{schema.NPC_OUTLINE}.reduce.system.md").read_text(encoding="utf-8")


def manual_block(manual: list[str]) -> str:
    return "\n".join(f"[manual {n}] {t}" for n, t in enumerate(manual, 1)) if manual else "(none)"


def reduce_headings(headings: list[str]) -> list[str]:
    """The outline sections the reduce call writes: everything the map calls do not."""
    return [h for h in headings if h not in schema.MAP_SECTIONS]


def map_prompt(name: str, chunk: list[npc_check.Chapter], manual: list[str]) -> tuple[str, str]:
    user = (
        f"NPC: {name}\n\n"
        f"EVIDENCE (chapters {chunk_range(chunk)}; verbatim; every item names the NPC; a mention is not a presence):\n\n"
        f"{chunk_text(chunk)}\n"
        "GM MANUAL EDITS:\n\n"
        f"{manual_block(manual)}\n\n"
        "OUTLINE: write exactly these `##` sections, in this order, and nothing else at that level:\n\n"
        + "\n".join(schema.MAP_SECTIONS)
        + "\n"
    )
    return load_map_system(), user


def reduce_prompt(
    name: str, header: str, notes: str, last_chunk: list[npc_check.Chapter], manual: list[str], headings: list[str]
) -> tuple[str, str]:
    user = (
        f"NPC: {name}\n\n"
        "READ-ONLY HEADER (computed from the evidence; context only, do not copy or restate it):\n\n"
        f"{header}\n"
        "VERIFIED NOTES from all chapters (already checked by code against the evidence):\n\n"
        f"{notes}\n"
        f"EVIDENCE OF THE LAST CHUNK ONLY (chapters {chunk_range(last_chunk)}), for Last Observed State:\n\n"
        f"{chunk_text(last_chunk)}\n"
        "GM MANUAL EDITS:\n\n"
        f"{manual_block(manual)}\n\n"
        "OUTLINE: write exactly these `##` sections, in this order, and nothing else at that level:\n\n"
        + "\n".join(reduce_headings(headings))
        + "\n"
    )
    return load_reduce_system(), user


# ── The map check ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Drop:
    section: str  # "history" | "quotes" | "arc"
    reason: str
    text: str


@dataclass
class MapResult:
    history: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    arc: list[str] = field(default_factory=list)
    drops: list[Drop] = field(default_factory=list)
    typography: list[str] = field(default_factory=list)  # kept quotes that needed folding
    advisories: list[str] = field(default_factory=list)  # kept, but worth a look
    quote_report: npc_check.QuoteReport = field(default_factory=npc_check.QuoteReport)

    def counts(self) -> dict:
        dropped = {k: sum(1 for d in self.drops if d.section == k) for k in ("history", "quotes", "arc")}
        return {
            "kept": {"history": len(self.history), "quotes": len(self.quotes), "arc": len(self.arc)},
            "dropped": dropped,
            "typography_normalised": len(self.typography),
            "quotes_by_source": dict(sorted(self.quote_report.by_source.items())),
            "drop_reasons": _reason_counts(self.drops),
        }


def _reason_counts(drops) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in drops:
        key = f"{d.section}:{d.reason}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _citation_problem(text: str, index: npc_check.EvidenceIndex, n_manual: int) -> str | None:
    """A drop reason for a bullet's citations, or None when it has at least one and all are good."""
    manual = [int(n) for n in schema.MANUAL_CITATION_RE.findall(text)]
    parts = npc_check.citation_parts(text)
    if not parts and not manual:
        return UNCITED
    if any(not 1 <= n <= n_manual for n in manual):
        return INVALID
    _, probs = npc_check.cite_problems(text, index.targets, outside=OUTSIDE_CHUNK)
    if probs:
        return INVALID if any(s == "invalid" for s, _ in probs) else OUTSIDE_CHUNK
    return None


def _bad_span(text: str, index: npc_check.EvidenceIndex, res: "MapResult") -> str | None:
    """The first double-quoted span in ``text`` that is not verbatim in the chunk, else None.

    Spans that pass only after normalisation are recorded as typography-normalised.
    """
    for span in npc_check.SPAN_RE.findall(text):
        verdict, _ = npc_check.in_evidence(span, index)
        if verdict is None:
            return span
        if verdict == npc_check.TYPOGRAPHY:
            res.typography.append(f"span {span} in: {text}")
    return None


def _render_quote(q: npc_check.QuoteRef) -> str:
    text = q.text if q.text[:1] in ('"', "“") else f'"{q.text}"'
    return f"> {text} {q.attribution}".rstrip()


def check_map(raw: str, index: npc_check.EvidenceIndex, n_manual: int = 0) -> MapResult:
    """Check one map call's output against that chunk's evidence; drop what fails, log why."""
    res = MapResult()
    secs = npc_check.parse_sections(raw)
    for key, heading, bucket in (("history", HISTORY, res.history), ("arc", ARC, res.arc)):
        first, lines = secs.get(heading, (0, []))
        for b in npc_check.bullets(lines, first):
            text = b.text
            why = _citation_problem(text, index, n_manual)
            if why:
                res.drops.append(Drop(key, why, text))
                continue
            bad = _bad_span(text, index, res)
            if bad:
                res.drops.append(Drop(key, SPAN_NOT_FOUND, f"span {bad} in: {text}"))
            else:
                bucket.append(text)
    first, lines = secs.get(QUOTES, (0, []))
    for q in npc_check.quotes_in(lines, first):
        block = _render_quote(q)
        if q.attribution:
            _, probs = npc_check.cite_problems(q.attribution, index.targets, outside=OUTSIDE_CHUNK)
        else:
            probs = []
        chk = npc_check.check_quote(q.text, q.attribution, index)
        res.quote_report.add(chk)
        if chk.status == NOT_FOUND:
            res.drops.append(Drop("quotes", NOT_FOUND, block))
        elif probs:
            why = INVALID if any(s == "invalid" for s, _ in probs) else OUTSIDE_CHUNK
            res.drops.append(Drop("quotes", why, block))
        elif chk.status == CITATION_MISMATCH:
            res.drops.append(Drop("quotes", f"{CITATION_MISMATCH} ({chk.detail})", block))
        else:
            res.quotes.append(block)
            if chk.status == npc_check.TYPOGRAPHY:
                res.typography.append(block)
            if npc_check.placeholder_speaker(q):
                res.advisories.append(f"placeholder-speaker: {block}")
    return res


# ── Stitch and assembly ─────────────────────────────────────────────────────


def _first_chapter(text: str) -> int:
    parts = npc_check.citation_parts(text)
    return parts[0][1][0] if parts and parts[0][1][0] >= 0 else 9999


def _dedup(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def stitch(results: list[MapResult]) -> dict[str, list[str]]:
    """Survivors of every chunk joined in chapter order, exact duplicates removed.

    Nothing is merged, reworded or reordered beyond the stable chapter sort.
    """
    return {
        HISTORY: sorted(_dedup([x for r in results for x in r.history]), key=_first_chapter),
        QUOTES: sorted(_dedup([x for r in results for x in r.quotes]), key=_first_chapter),
        ARC: sorted(_dedup([x for r in results for x in r.arc]), key=_first_chapter),
    }


def section_body(heading: str, items: list[str]) -> str:
    if not items:
        return schema.NONE_VERIFIED
    return ("\n\n" if heading == QUOTES else "\n").join(items)


def render_notes(stitched: dict[str, list[str]]) -> str:
    return "".join(f"{h}\n{section_body(h, stitched[h])}\n\n" for h in schema.MAP_SECTIONS)


def assemble(headings: list[str], stitched: dict[str, list[str]], reduce_raw: str) -> str:
    """The draft body in outline order: map sections from the stitched survivors, the rest from
    the reduce call. A section the reduce call left out is omitted, so ``check_outline`` reports
    it and the draft is written ``.incomplete.md``."""
    red = npc_check.parse_sections(reduce_raw)
    out = []
    for h in headings:
        if h in schema.MAP_SECTIONS:
            out.append(f"{h}\n{section_body(h, stitched[h])}\n")
        elif h in red:
            body = npc_check.section_text(red, h)
            out.append(f"{h}\n{body}\n" if body else f"{h}\n")
    return "\n".join(out)


def render_drops_md(npc: str, per_chunk: list[tuple[str, MapResult]]) -> str:
    lines = [f"# Map-check drops: {npc}", ""]
    total = sum(len(r.drops) for _, r in per_chunk)
    lines.append(f"{total} dropped across {len(per_chunk)} chunks. Every drop is listed with its reason.")
    for rng, r in per_chunk:
        lines += ["", f"## Chunk {rng}"]
        c = r.counts()
        lines.append(f"kept {c['kept']}, dropped {c['dropped']}, typography-normalised {c['typography_normalised']}")
        for d in r.drops:
            lines.append(f"- [{d.section}] {d.reason}: {d.text.replace(chr(10), ' // ')}")
        for t in r.typography:
            lines.append(f"- [quotes] kept, typography-normalised: {t.replace(chr(10), ' // ')}")
        for a in r.advisories:
            lines.append(f"- [quotes] kept, advisory {a.replace(chr(10), ' // ')}")
    return "\n".join(lines) + "\n"
