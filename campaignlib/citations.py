"""Deterministic citation verification for distill.py's extract and
synthesize passes.

distill_extract.md requires every extracted bullet to end with a citation
tag — `[cite: "..."]` — quoting the source text it was drawn from. This
module checks that requirement mechanically: no model call, just a
substring match between the cited quote and the chunk it claims to come
from. A quote that doesn't match is a candidate hallucination, surfaced
for the GM to review at the existing --extract-only checkpoint rather than
silently trusted or silently discarded.

distill_synthesize.md carries the same discipline into the merge pass, but
as numbered citation IDs rather than re-quoted text: CitationIdAssigner
tags every `[cite: "..."]` tag synthesis is shown with a stable ID before
the input reaches the model — `[cite:42 "..."]` — and the prompt asks it
to cite `[42]`, never to re-type the quote. That keeps synthesis output
small (an `[n]` marker costs a few tokens; a re-typed 5-25 word quote
costs many, once per claim) and makes verification exact-match rather
than fuzzy: the model can only ever cite an ID it was shown, so checking
an ID is legitimate is a dict-key lookup, not a substring search. The
human-readable Sources section is assembled entirely in code from the IDs
actually used — the model never spends output tokens reproducing quotes.
"""

import re
from dataclasses import dataclass

from .config import load_agent_prompt

# Shared citation-rule fragments, composed onto each script's own extract/
# synthesize base prompt (`_BASE + "\n\n" + CITATION_RULES_*`). Single source
# of truth so distill.py/planning.py/party.py can't drift out of sync on the
# citation-grounding wording.
CITATION_RULES_EXTRACT = load_agent_prompt("citation_rules_extract")
CITATION_RULES_SYNTHESIZE = load_agent_prompt("citation_rules_synthesize")

_QUOTE_OPEN = '«"“'
_QUOTE_CLOSE = '»"”'

_CITE_RE = re.compile(
    rf'^(?P<bullet>-\s.*?)\s*\[cite:\s*[{_QUOTE_OPEN}](?P<quote>.*?)[{_QUOTE_CLOSE}]\]\s*$',
    re.MULTILINE,
)
_CITE_TAG_RE = re.compile(rf'\[cite:\s*[{_QUOTE_OPEN}].*?[{_QUOTE_CLOSE}]\]\s*$')

_WHITESPACE_RE = re.compile(r'\s+')

# Models routinely re-encode a source's nested double quotes as single quotes
# to avoid colliding with the [cite: "..."] wrapper's own delimiters (e.g.
# source `named the party "the Obsidian Edge"` cited as `'the Obsidian Edge'`).
# That's a faithful quote, not a fabrication, so all quote styles collapse to
# one canonical mark before comparison — a genuinely different quote still
# fails on the words themselves.
_QUOTE_TRANSLATION = str.maketrans({c: "'" for c in '"“”‘’`'})


def _normalize(s: str) -> str:
    """Collapse whitespace/quote-style/case drift so only real wording
    differences count as a mismatch."""
    s = s.translate(_QUOTE_TRANSLATION)
    return _WHITESPACE_RE.sub(' ', s).strip().casefold()


@dataclass
class Citation:
    bullet: str
    quote: str
    verified: bool


def extract_citations(text: str) -> list[tuple[str, str]]:
    """Return (bullet, quote) for every cited bullet in an extract file."""
    return [
        (m.group('bullet').strip(), m.group('quote'))
        for m in _CITE_RE.finditer(text)
    ]


_EXEMPT_LABEL_RE = re.compile(
    r'^-\s*(Faction|Current location|Current goals):', re.IGNORECASE
)
_ABSENCE_RE = re.compile(
    r'^-\s*(does not appear|not (directly )?encountered|not (directly )?present|not visited)\b'
    r'[^.;]*\b(this (chunk|session|chapter))\b\.?$',
    re.IGNORECASE,
)


def _is_exempt_from_citation(stripped_line: str) -> bool:
    """`Faction:`/`Current location:`/`Current goals:` sub-fields classify
    rather than assert, and a bare not-in-this-chunk/session negative has
    nothing to quote by definition — both are allowed to skip the citation
    per distill_extract.md's exception rule."""
    return bool(_EXEMPT_LABEL_RE.match(stripped_line) or _ABSENCE_RE.match(stripped_line))


_CITE_TAG_ANY_RE = re.compile(
    rf'[ \t]*\[cite:\s*\d*\s*[{_QUOTE_OPEN}].*?[{_QUOTE_CLOSE}]\]'
)
_TRAILING_LINE_WS_RE = re.compile(r'[ \t]+$', re.MULTILINE)


def strip_citation_tags(text: str) -> str:
    """Remove every `[cite: "..."]` (extract-pass) or `[cite:N "..."]`
    (synthesis-pass, post-CitationIdAssigner) tag from `text`, collapsing
    the whitespace a removed tag would otherwise leave behind.

    For a later phase's use: planning.py's --build-dossiers Phase 3 folds
    raw extraction excerpts straight into a dossier's `raw_notes` with no
    normalization today. Once Phase 1 extraction carries real citation
    tags, those excerpts would leak into the dossier file as-is — a later
    synthesis run reading that dossier could then cite a stale tag as if
    it were freshly verified. This strips the tags at that one leak point
    without touching them in the extract files themselves (still useful
    there for review) or in the human-reviewed new_notes sidecars.
    """
    stripped = _CITE_TAG_ANY_RE.sub('', text)
    return _TRAILING_LINE_WS_RE.sub('', stripped)


def find_uncited_bullets(text: str) -> list[str]:
    """Return bullet lines that carry no `[cite: ...]` tag and aren't exempt."""
    uncited = []
    for line in text.splitlines():
        stripped = line.strip()
        if (stripped.startswith('- ')
                and not _CITE_TAG_RE.search(stripped)
                and not _is_exempt_from_citation(stripped)):
            uncited.append(stripped)
    return uncited


def verify_citations(text: str, source: str) -> list[Citation]:
    """Check every cited quote in `text` is a verbatim substring of `source`.

    A citation is "verified" iff its quote (after whitespace/case
    normalization) appears somewhere in `source`. An empty quote never
    verifies.
    """
    norm_source = _normalize(source)
    return [
        Citation(bullet=bullet, quote=quote, verified=bool(quote) and _normalize(quote) in norm_source)
        for bullet, quote in extract_citations(text)
    ]


def render_report(
    results_by_file: dict[str, tuple[list[Citation], list[str]]],
    tool_name: str = "distill.py",
) -> str:
    """Render a citation_report.md body from {filename: (citations, uncited_bullets)}.

    Only files with at least one flagged item (unverified citation or
    uncited bullet) are included — a clean file has nothing to review.

    tool_name — attributed in the report's opening line (default preserves
                distill.py's original wording). Other scripts wiring this
                checker in via campaignlib.citation_checks should pass their
                own name so a report doesn't misattribute itself.
    """
    lines = [
        "# Citation Report",
        "",
        f"Generated by {tool_name}'s citation check (plain substring matching,"
        " not a model call). Every bullet in extract_*.md is expected to end"
        " with `[cite: \"...\"]`, a verbatim quote from its source chunk."
        " Items below failed that check and are candidate hallucinations —"
        " verify against the source before this material reaches synthesis.",
    ]
    any_flagged = False
    for filename, (citations, uncited) in results_by_file.items():
        unverified = [c for c in citations if not c.verified]
        if not unverified and not uncited:
            continue
        any_flagged = True
        lines += ["", f"## {filename}"]
        if unverified:
            lines += ["", "### Unverified citations (quote not found in source)"]
            for c in unverified:
                lines.append(f'- {c.bullet}\n  cited: "{c.quote}"')
        if uncited:
            lines += ["", "### Bullets missing a citation"]
            for bullet in uncited:
                lines.append(f"- {bullet}")
    if not any_flagged:
        lines += ["", "No flagged claims — every bullet carried a citation that matched its source."]
    return "\n".join(lines) + "\n"


# ── Synthesis citation IDs ───────────────────────────────────────────────────

_CITE_TAG_INJECT_RE = re.compile(
    rf'\[cite:\s*[{_QUOTE_OPEN}](?P<quote>.*?)[{_QUOTE_CLOSE}]\]'
)
_TRAILING_CITE_REFS_RE = re.compile(r'((?:\[\d+\])+)\s*$')


class CitationIdAssigner:
    """Tags every `[cite: "..."]` in text fed to it with a stable, sequential
    ID — `[cite:42 "..."]` — so synthesis can cite `[42]` instead of
    re-typing the quote.

    Use as `run_synthesize_pipeline`'s `input_normalizer`: it's called once
    per extraction file, in file order, while the synthesis prompt is being
    assembled — before any API call — so `.id_to_quote` is complete by the
    time the pipeline call returns. IDs are assigned in call order, so the
    same instance must not be reused across unrelated synthesis runs.
    """

    def __init__(self):
        self.id_to_quote: dict[int, str] = {}
        self._next_id = 1

    def __call__(self, body: str) -> str:
        def _assign(m: re.Match) -> str:
            quote = m.group('quote')
            cid = self._next_id
            self._next_id += 1
            self.id_to_quote[cid] = quote
            return f'[cite:{cid} "{quote}"]'
        return _CITE_TAG_INJECT_RE.sub(_assign, body)


@dataclass
class IdCitation:
    number: int
    claim: str
    verified: bool


def find_citation_refs(text: str) -> list[tuple[str, list[int]]]:
    """Return (claim, [citation IDs]) for every claim ending in a trailing
    run of `[n]` markers, e.g. `...before the coup. [12][47]`."""
    refs = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('- '):
            continue
        m = _TRAILING_CITE_REFS_RE.search(stripped)
        if m:
            nums = [int(n) for n in re.findall(r'\d+', m.group(1))]
            refs.append((stripped, nums))
    return refs


def find_unreferenced_claims(text: str) -> list[str]:
    """Return claims with no trailing `[n]` marker and no exemption (same
    Faction:/Current location:/Current goals:/bare-absence exemption as the
    extract pass's find_uncited_bullets)."""
    unreferenced = []
    for line in text.splitlines():
        stripped = line.strip()
        if (stripped.startswith('- ')
                and not _TRAILING_CITE_REFS_RE.search(stripped)
                and not _is_exempt_from_citation(stripped)):
            unreferenced.append(stripped)
    return unreferenced


def verify_id_citations(text: str, known_ids: dict[int, str]) -> list[IdCitation]:
    """Check every citation ID referenced in `text` is a key in `known_ids`
    — the IDs CitationIdAssigner actually showed the model during synthesis.
    Synthesis can only ever cite an ID it saw, never invent a new one or a
    new quote, so this is exact membership, not fuzzy text matching.
    """
    return [
        IdCitation(number=n, claim=claim, verified=n in known_ids)
        for claim, nums in find_citation_refs(text)
        for n in nums
    ]


def render_synthesis_report(
    results: list[IdCitation],
    unreferenced: list[str],
    tool_name: str = "distill.py",
) -> str:
    """Render a synthesis_citation_report.md body.

    results      — from verify_id_citations(); unverified entries are flagged.
    unreferenced — claims with no [n] marker, from find_unreferenced_claims().
    tool_name    — attributed in the report's opening line (default preserves
                   distill.py's original wording); see render_report.
    """
    unverified = [r for r in results if not r.verified]
    lines = [
        "# Synthesis Citation Report",
        "",
        f"Generated by {tool_name}'s synthesis citation check (plain ID lookup,"
        " not a model call). Every claim in the synthesized document is"
        " expected to carry a citation ID — [n] — copied from the extraction"
        " notes' [cite:n \"...\"] tags.",
    ]
    if not unverified and not unreferenced:
        lines += ["", "No flagged claims — every citation ID traces to one the"
                       " model was actually shown during synthesis."]
        return "\n".join(lines) + "\n"
    if unverified:
        lines += ["", "### Citation IDs not shown to the model during synthesis (candidate fabrication)"]
        for r in unverified:
            lines.append(f"- [{r.number}] cited by: {r.claim}")
    if unreferenced:
        lines += ["", "### Claims missing a citation ID"]
        for claim in unreferenced:
            lines.append(f"- {claim}")
    return "\n".join(lines) + "\n"


def render_sources_section(used_ids: set[int], known_ids: dict[int, str]) -> str:
    """Render a `## Sources` section for the IDs actually referenced in the
    synthesized document — assembled entirely in code from IDs the model
    saw during synthesis, so the model never spends output tokens
    reproducing quote text."""
    lines = ["## Sources", ""]
    for n in sorted(used_ids):
        lines.append(f'[{n}] "{known_ids.get(n, "<unknown citation>")}"')
    return "\n".join(lines) + "\n"
