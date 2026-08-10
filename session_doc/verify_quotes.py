"""Deterministic quote verification against a session transcript.

The Session Doc Editor's two extraction stages both tell the model to
reproduce dialogue verbatim — ``config/agents/enhance_summary.md`` ("Quote
dialogue VERBATIM when promoting a line to Memorable Moments") and
``config/agents/scene_extract.md`` ("Quote dialogue VERBATIM. Do not
paraphrase.") — and until now nothing checked. The sibling ensemble pipeline
has enforced the same contract mechanically since ``extract_facts.
verify_quotes``; this module is that enforcement for the session_doc path.

**No model is called.** A quote is a span of the VTT or it is not, so the
check is a text comparison and costs nothing. That matters beyond thrift: a
reviewing model grading another model's output is exactly the LLM-checks-LLM
shape the project constitution forbids (Principle II), and it would be
unreliable in precisely the cases that matter.

**Three verdicts, not two.** Measured over 522 real quotes from a Claude-
generated session (specs/007-two-phase-extraction/research.md D1), only **64%
are exact verbatim**. The other 36% are dominated by *disfluency edits* — the
extraction says "I do cross promotions." where the tape says "I do, like,
cross promotions." Those are real quotes, lightly tidied, and a binary check
would report 186 findings for one session with ~90% of them benign. A report
that cries wolf two-thirds of the time is worse than no report, because it
teaches the reader to skip it. So a quote that is not verbatim but is
traceable to a transcript line is ``near`` (informational), and only an
untraceable one is ``unverified`` (the fabrication signal).

**Nothing is rewritten.** The only permitted modification to a checked file is
an additive ``<!-- cg:unverified -->`` / ``<!-- cg:refused:RN -->`` marker on
an offending quote's line, applied idempotently. Repairing quotes
automatically is out of scope by design: ``scrub_mechanics.py`` was an
autonomous LLM repair pass that stripped spells out of narration (issue #151)
and was replaced by a propose→confirm→apply workflow. Verbatim text is the one
thing this module must never touch.

**Verdicts and refusals are two different axes.** A verdict answers *is this
in the tape*. A refusal (extraction contract #250, R1/R3 — see
``docs/design/ExtractionContract_proposal.md``) answers *may the pipeline
choose this*, and the answer can be no for a span that is perfectly verbatim.
``> "…the strength of [Lathander]"`` matches the tape once the bracket is
stripped and is still an editorial hand inside a span marked verbatim. The two
axes are computed independently and reported separately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

from campaignlib.textproc import locate_quote

from .io import CLAIM_VERBATIM, CLAIM_VOICED, parse_vtt, split_scene_sections, _split_scene_body


# ── Verdicts ─────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    """Outcome of classifying one quote. Only ``UNVERIFIED`` is an accusation."""

    VERIFIED = "verified"      # exact, or whitespace-equal, span of the transcript
    NEAR = "near"              # traceable to a line but not verbatim (usually disfluency edits)
    UNVERIFIED = "unverified"  # no plausible source line — the fabrication signal
    UNSCORED = "unscored"      # too short to carry signal either way
    EXEMPT = "exempt"          # an editorial marker, not a quote at all


#: Verdicts the report treats as problems. Deliberately just one.
PROBLEM_VERDICTS = (Verdict.UNVERIFIED,)

DEFAULT_THRESHOLD = 0.85
DEFAULT_MIN_TOKENS = 4

ANNOTATION = "<!-- cg:unverified -->"

# Words that state a fact *about the tape* rather than supplying text: the
# extractor reporting that something could not be heard. Shared by the two
# rules below so the two cannot drift apart.
_MARKER_WORDS = (
    r"inaudible|unclear|unintelligible|indistinct|crosstalk"
    r"|paraphrase|truncated|silence"
)

# Markers the generation prompts define for "no verbatim quote exists", plus
# the [inaudible] convention that appears in real extractions but that neither
# prompt documents (research D3). A quote consisting wholly of one of these is
# the extractor reporting absence correctly, not fabricating.
_EXEMPT_RE = re.compile(
    rf"^\s*[\[(]\s*({_MARKER_WORDS})\b[^\])]*[\])]\s*$",
    re.IGNORECASE,
)

# Bracketed editorial insertions *inside* an otherwise real quote — a GM
# clarifying a garbled word, e.g. "...the strength of [Lathander]" or
# "a Brewbarry bathroom [bathrobe]". These can never match verbatim, so they
# are stripped before matching rather than exempting the whole sentence.
_BRACKET_SPAN_RE = re.compile(r"\[[^\]]*\]")

# "Speaker Name: " prefix that parse_vtt leaves on each cue. Bounded length so
# a colon inside dialogue ("I said: no") is not mistaken for a speaker label.
_SPEAKER_PREFIX_RE = re.compile(r"^([^:]{1,40}):\s*")


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


# ── Transcript ───────────────────────────────────────────────────────────────

@dataclass
class SourceTranscript:
    """The record of what was actually said. Read-only; never modified.

    ``parse_vtt`` leaves each cue speaker-prefixed ("Gary Young: Hey there."),
    so a quote spanning two cues by the same speaker has an interposed
    ``Speaker: `` in the joined text and cannot match as a contiguous span.
    The prefixes are stripped for matching and kept alongside, so a finding can
    still name who said the nearest line.
    """

    path: Path
    lines: list[str]        # speaker-prefixed, as parse_vtt returns them
    spoken: list[str]       # prefix stripped — what was actually said
    speakers: list[str]     # the stripped prefix, "" when a line had none
    haystack: str           # normalized join of `spoken` — the match target

    @classmethod
    def load(cls, path: Path) -> "SourceTranscript":
        """Read and parse a .vtt. Raises rather than yielding an empty corpus.

        A missing or unparseable transcript must never be reported as "every
        quote is unverified" (FR-011) — that reads as a catastrophic
        fabrication rate when it is in fact operator error.
        """
        path = Path(path).expanduser()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"transcript not readable: {path} ({e})") from e

        lines = [ln for ln in parse_vtt(raw).splitlines() if ln.strip()]
        if not lines:
            raise ValueError(
                f"transcript parsed to no dialogue: {path} — wrong file, or not a WebVTT?"
            )

        spoken: list[str] = []
        speakers: list[str] = []
        for ln in lines:
            m = _SPEAKER_PREFIX_RE.match(ln)
            if m:
                speakers.append(m.group(1).strip())
                spoken.append(ln[m.end():])
            else:
                speakers.append("")
                spoken.append(ln)

        return cls(
            path=path,
            lines=lines,
            spoken=spoken,
            speakers=speakers,
            haystack=_normalize(" ".join(spoken)),
        )


# ── Quotes and findings ──────────────────────────────────────────────────────

@dataclass
class Quote:
    """A span presented as something a person said.

    ``text`` is the identity and is never mutated. ``match_text`` is a derived
    view used only for comparison, so tolerance in matching can never be
    written back into the document.
    """

    text: str
    artifact: Path
    line_no: int
    section: str | None = None
    speaker_hint: str | None = None

    @property
    def match_text(self) -> str:
        """Primary comparison view: bracketed editorial spans removed."""
        return _normalize(_BRACKET_SPAN_RE.sub(" ", self.text))

    @property
    def match_variants(self) -> list[str]:
        """Every reading of this quote worth testing for a verbatim match.

        A bracketed span inside a quote is a GM annotation, and it is used two
        different ways in real files. Sometimes it *replaces* a garble, so the
        tape does not contain the bracketed word (`the strength of [Lathander]`
        where the tape says "Morninglord"); sometimes it merely *clarifies*, so
        the tape does contain it. Testing both readings means the second kind
        matches verbatim instead of being demoted to `near` for a punctuation
        artifact left behind by the strip.
        """
        stripped = self.match_text
        variants = [stripped]
        unwrapped = _normalize(self.text.replace("[", "").replace("]", ""))
        if unwrapped and unwrapped != stripped:
            variants.append(unwrapped)
        return variants

    @property
    def is_exempt(self) -> bool:
        return bool(_EXEMPT_RE.match(self.text.strip()))


# An ellipsis inside a quote almost always means two separate utterances were
# stitched into one. `config/agents/extract_facts.md` names this explicitly for
# the ensemble path — "The ellipsis is the tell: if you reach for `...` to build
# a quote, you have bundled" — and the same tell holds here. It is still a
# verbatim violation (the sentence as written was never said contiguously), so
# it stays `unverified`; naming it just saves the reader working it out.
_STITCH_RE = re.compile(r"\.\.\.|…")


@dataclass
class Finding:
    """The classification of one quote. Every quote produces exactly one."""

    quote: Quote
    verdict: Verdict
    score: float | None = None
    nearest_line: str | None = None
    nearest_speaker: str | None = None
    offset: int | None = None

    @property
    def is_problem(self) -> bool:
        return self.verdict in PROBLEM_VERDICTS

    @property
    def looks_stitched(self) -> bool:
        """Only meaningful on a quote that failed — a verbatim ellipsis is fine."""
        return self.verdict is Verdict.UNVERIFIED and bool(_STITCH_RE.search(self.quote.text))


# ── Scoring and classification ───────────────────────────────────────────────

def score_quote(match_text: str, transcript: SourceTranscript) -> tuple[float, str, str]:
    """Best (score, line, speaker) for a non-verbatim quote.

    Scoring is **containment-biased**: a quote is usually a sub-span of a long
    cue, and a symmetric ``SequenceMatcher.ratio()`` between a 12-word quote
    and a 60-word cue scores low even when the quote sits inside it verbatim.
    Taking ``max(ratio, longest_common_block / len(quote))`` adds a containment
    measure, which is what pushes a genuine sub-span back up near 1.0
    (research D2 — using ratio() alone put real quotes in the 0.6–0.8 band and
    would have manufactured findings).

    Candidates are prefiltered on token overlap so this stays linear enough for
    a 3,400-cue transcript.
    """
    tokens = set(match_text.split())
    if not tokens:
        return 0.0, "", ""

    need = max(2, len(tokens) // 4)
    best_score = 0.0
    best_i = -1
    for i, line in enumerate(transcript.spoken):
        cand = _normalize(line)
        if not cand:
            continue
        if len(tokens & set(cand.split())) < need:
            continue
        sm = SequenceMatcher(None, match_text, cand)
        if sm.real_quick_ratio() < best_score:
            continue
        score = sm.ratio()
        block = sm.find_longest_match(0, len(match_text), 0, len(cand)).size
        score = max(score, block / len(match_text))
        if score > best_score:
            best_score, best_i = score, i

    if best_i < 0:
        return 0.0, "", ""
    return best_score, transcript.spoken[best_i].strip(), transcript.speakers[best_i]


def classify(
    quote: Quote,
    transcript: SourceTranscript,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> Finding:
    """Classify one quote. Order matters — see the module docstring."""
    if quote.is_exempt:
        return Finding(quote, Verdict.EXEMPT)

    match_text = quote.match_text
    if not match_text:
        return Finding(quote, Verdict.EXEMPT)

    # Verbatim first: the shared matcher, so "verbatim" means the same thing
    # here as it does in the ensemble pipeline. Checked before the length gate
    # below — a genuine verbatim span is a fact whatever its length.
    for variant in quote.match_variants:
        offset = locate_quote(variant, transcript.haystack)
        if offset is not None:
            return Finding(quote, Verdict.VERIFIED, offset=offset)

    # A two-word quote matches something in any 128KB transcript, so a high
    # score is as meaningless as a low one. Report it; never accuse it (D7).
    if len(match_text.split()) < min_tokens:
        return Finding(quote, Verdict.UNSCORED)

    score, line, speaker = score_quote(match_text, transcript)
    verdict = Verdict.NEAR if score >= threshold else Verdict.UNVERIFIED
    return Finding(
        quote,
        verdict,
        score=score,
        nearest_line=line or None,
        nearest_speaker=speaker or None,
    )


# ── Extraction contract #250 — refusals ──────────────────────────────────────

class Rule(str, Enum):
    """A ratified extraction-contract rule that can refuse a span."""

    R1 = "R1"   # the two sections carry the span differently; the tape cannot settle it
    R3 = "R3"   # an editorial insertion sits inside a span marked verbatim


#: One-line statement of each rule, for the report. Kept next to the enum so
#: the wording the GM reads and the wording that was ratified stay together.
RULE_TEXT = {
    Rule.R1: (
        "The `## Scene summary` and `## Verbatim moments` copies of one span "
        "disagree and neither is verbatim in the tape. Renders as neither copy "
        "until you resolve it. A span verbatim in *both* copies is never a "
        "conflict — two true statements must not be escalated."
    ),
    Rule.R3: (
        "An editorial insertion sits inside a span marked verbatim. Does not "
        "render until it is rewritten. Bare transcription markers "
        "(`[inaudible]`) are facts about the tape and are preserved; a marker "
        "carrying a conjecture is not."
    ),
}


@dataclass
class Refusal:
    """A span the contract will not let render until the GM resolves it.

    Orthogonal to ``Verdict``: ``verdict`` records what the tape said about
    this copy, which for R3 is frequently ``VERIFIED``. Refusing a verbatim
    span is not a contradiction — the objection is to the editorial hand
    inside it, not to the words around it.
    """

    rule: Rule
    quote: Quote
    detail: str
    verdict: Verdict | None = None
    counterpart: Quote | None = None
    counterpart_verdict: Verdict | None = None
    similarity: float | None = None


# A bracket whose whole content is one marker word states a fact about the
# tape (contract class 3) and is preserved — deleting one fabricates
# certainty. The same marker carrying a reconstruction, e.g.
# `[inaudible — probable "I'll fill you in the whole way"]`, is a hybrid: the
# marker half is a fact and the conjecture half is the editor's, and it is the
# conjecture that would render. Hybrids are class 4.
_TRANSCRIPTION_MARKER_RE = re.compile(
    rf"^\s*({_MARKER_WORDS})\s*[.?!]?\s*$", re.IGNORECASE
)


def editorial_brackets(text: str) -> list[str]:
    """Class-4 brackets in one span: editorial insertions, not tape facts.

    Counting brackets by *position* — inside a `> "…"` span — rather than by
    token identity is what took the ch46 count from 3 to 10. Keying on the
    token made `[Lathander]` a speaker label (it is one, elsewhere in the same
    file) and let every marker-with-a-comment fall through unmatched.
    """
    return [
        m.group(0)
        for m in _BRACKET_SPAN_RE.finditer(text)
        if not _TRANSCRIPTION_MARKER_RE.match(m.group(0)[1:-1])
    ]


def find_bracket_refusals(findings: list[Finding]) -> list[Refusal]:
    """R3 — refuse every span carrying an editorial insertion.

    Ruled as stated: no carve-out for a *clarifying* bracket whose content is
    present in the tape (`[Lathander]` — the tape says it ten times). Whether
    to add one is open question 1 in the ratified doc, and adding it here
    before it is ruled would be the component deciding again.
    """
    out: list[Refusal] = []
    for f in findings:
        if f.verdict is Verdict.EXEMPT:
            # The whole span is a marker. There is no quote for a bracket to
            # sit inside, so there is nothing for R3 to object to.
            continue
        brackets = editorial_brackets(f.quote.text)
        if brackets:
            out.append(Refusal(rule=Rule.R3, quote=f.quote, verdict=f.verdict,
                               detail=" ".join(brackets)))
    return out


#: A quoted span in a `## Scene summary` shorter than this is treated as a
#: label rather than speech — the same judgement `_parse_blockquote_quotes`
#: makes by refusing inline quotes outright (research D5). Pairing is the only
#: thing these spans are used for; they are never classified as findings, so a
#: label slipping through costs a missed pair, never a false accusation.
PAIR_MIN_CHARS = 25

#: Below this similarity two copies are two different spans, not one span in
#: conflict. Deliberately loose: the smoothed splice in the evidence corpus
#: scores 0.80 against the tape, so pairing it with its clean sibling has to
#: tolerate at least that much drift or the conflict is invisible.
PAIR_FLOOR = 0.55

_SUMMARY_SPAN_RE = re.compile(r'["“]([^"“”]+)["”]')


@dataclass
class ConflictScan:
    """What R1 found, including its denominator.

    ``refused`` alone is unreadable: two refusals out of eight paired spans is
    a working rule, two out of two is a broken one. The report states all four
    numbers so the rate is visible, not just the interruptions.
    """

    paired: int = 0        # the same span appears in both sections
    consistent: int = 0    # identical copies, or both verbatim — never a conflict
    settled: int = 0       # exactly one copy is verbatim; the tape names the winner
    refusals: list[Refusal] = field(default_factory=list)

    @property
    def refused(self) -> int:
        return len(self.refusals)


def parse_scene_summary_spans(text: str, artifact: Path) -> list[Quote]:
    """Quoted spans in the `## Scene summary` half — **for pairing only**.

    This deliberately parses inline `"…"`, which `parse_scene_quotes` refuses
    to do, and the difference is what the spans are used for. There they would
    become findings, and calling the GM's own hand-authored gm-assist phrasing
    "unverified" would be both wrong and an insult to the checkpoint that
    produced it (research D4). Here they are only ever the *other copy* of a
    span, so the worst a mis-parse can do is fail to notice a conflict.
    """
    summary, _moments = _split_scene_body(text)
    if not summary:
        return []
    offset = text.find(summary)
    line_offset = text.count("\n", 0, offset) if offset > 0 else 0

    out: list[Quote] = []
    for idx, line in enumerate(summary.splitlines()):
        for m in _SUMMARY_SPAN_RE.finditer(line):
            span = m.group(1).strip()
            if len(span) < PAIR_MIN_CHARS:
                continue
            out.append(Quote(text=span, artifact=artifact,
                             line_no=line_offset + idx + 1,
                             section="Scene summary"))
    return out


def scan_section_conflicts(
    summary_spans: list[Quote],
    moment_findings: list[Finding],
    transcript: SourceTranscript,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> ConflictScan:
    """R1 — refuse a span the two sections carry differently that the tape cannot settle.

    Authority comes from the transcript and from nothing else (contract C1).
    Every intuitive tiebreak picks the wrong copy on the evidence corpus: the
    section named `Verbatim moments` is the *unfaithful* one in defect A, the
    corrupted copy is the longer one in both defects, and smoothing degrades
    the same span from 0.97 to 0.80, so "the later stage wins" is backwards.

    Three outcomes, and only the last one wakes the GM:

    * **consistent** — identical copies, or both verbatim. R1's load-bearing
      exclusion. Without it the rule fires on any two similar-but-distinct real
      utterances and the GM is asked to adjudicate between two facts.
    * **settled** — exactly one copy is verbatim. The tape has already named
      the faithful copy; the other is reported by its own verdict.
    * **refused** — neither copy is in the tape. Nothing here can choose.

    ``near`` never settles anything. A similarity band says *an edit happened*,
    never that the edit was *safe*: 0.92 has been a meaning-changing misquote
    and 0.94 a harmless disfluency, in that order.
    """
    scan = ConflictScan()
    if not summary_spans or not moment_findings:
        return scan

    for span in summary_spans:
        norm = _normalize(span.text)
        best: Finding | None = None
        best_sim = 0.0
        for mf in moment_findings:
            sim = SequenceMatcher(None, norm, _normalize(mf.quote.text)).ratio()
            if sim > best_sim:
                best, best_sim = mf, sim
        if best is None or best_sim < PAIR_FLOOR:
            continue          # a different span, not a second copy of this one

        scan.paired += 1
        if best_sim >= 0.999:
            scan.consistent += 1
            continue

        summary_finding = classify(span, transcript,
                                   threshold=threshold, min_tokens=min_tokens)
        a = summary_finding.verdict is Verdict.VERIFIED
        b = best.verdict is Verdict.VERIFIED
        if a and b:
            scan.consistent += 1
            continue
        if a or b:
            scan.settled += 1
            continue

        scan.refusals.append(Refusal(
            rule=Rule.R1,
            quote=best.quote,
            verdict=best.verdict,
            counterpart=span,
            counterpart_verdict=summary_finding.verdict,
            similarity=best_sim,
            detail=(f"neither copy is verbatim "
                    f"(`## Scene summary` {summary_finding.verdict.value}, "
                    f"`## Verbatim moments` {best.verdict.value})"),
        ))
    return scan


# ── Parsers ──────────────────────────────────────────────────────────────────

# `> "quote"` — the blockquote form both stages emit. The closing quote may be
# followed by a trailing attribution, e.g. `> "..." (GM)`.
_BLOCKQUOTE_QUOTE_RE = re.compile(r'^\s*>\s*[""“](?P<q>.+?)[""”]\s*(?P<attr>\([^)]*\))?\s*$')
# `> — Name` attribution line under a Stage 1 blockquote.
_ATTRIBUTION_RE = re.compile(r"^\s*>\s*[—–-]\s*(?P<who>.+?)\s*$")
# `**[Speaker]** — context` block header in Stage 2 verbatim moments.
_SPEAKER_BLOCK_RE = re.compile(r"^\s*\*\*\[(?P<who>[^\]]+)\]\*\*")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")


def _parse_blockquote_quotes(
    text: str, artifact: Path, *, line_offset: int = 0, speaker_from_blocks: bool = False
) -> list[Quote]:
    """Shared `> "…"` scanner for both stages.

    Deliberately does **not** look at inline ``"…"`` spans in prose. In real
    summaries those are frequently not dialogue at all — a stone plaque
    honouring the "liberators of the Ordning" is a label, and treating every
    inline pair of quote marks as speech manufactures findings out of prose
    (research D5). The report states this limitation rather than hiding it.
    """
    quotes: list[Quote] = []
    section: str | None = None
    speaker_block: str | None = None
    lines = text.splitlines()

    for idx, line in enumerate(lines):
        h = _HEADING_RE.match(line)
        if h:
            section = h.group("title")
            speaker_block = None
            continue

        if speaker_from_blocks:
            sb = _SPEAKER_BLOCK_RE.match(line)
            if sb:
                speaker_block = sb.group("who").strip()
                continue

        m = _BLOCKQUOTE_QUOTE_RE.match(line)
        if not m:
            if line.strip() and not line.lstrip().startswith(">"):
                speaker_block = speaker_block if speaker_from_blocks else None
            continue

        speaker = speaker_block
        attr = m.group("attr")
        if attr:
            speaker = attr.strip("() ") or speaker
        if speaker is None:
            # Stage 1 puts attribution on the following `> — Name` line.
            for nxt in lines[idx + 1: idx + 3]:
                if _BLOCKQUOTE_QUOTE_RE.match(nxt):
                    break
                a = _ATTRIBUTION_RE.match(nxt)
                if a:
                    speaker = a.group("who").strip()
                    break

        quotes.append(
            Quote(
                text=m.group("q").strip(),
                artifact=artifact,
                line_no=line_offset + idx + 1,
                section=section,
                speaker_hint=speaker,
            )
        )
    return quotes


def parse_summary_quotes(text: str, artifact: Path) -> list[Quote]:
    """Stage 1 — quotes in a ``session-summary.md``."""
    return _parse_blockquote_quotes(text, artifact)


def parse_scene_quotes(text: str, artifact: Path) -> list[Quote]:
    """Stage 2 — quotes in a ``scene_extractions/NN_*.md``.

    Only the moments section is parsed — ``## Verbatim moments``, or its
    ``## Voiced moments`` sibling in a voice-smoothed layer. The other section,
    ``## Scene summary (from gm-assist, verbatim)``, is the GM's own
    hand-authored skeleton copied from ``gm-assist.md`` — flagging the human's
    phrasing as "unverified" would be both wrong and an insult to the
    checkpoint that produced it (research D4).

    A ``Voiced`` section is still classified. Dropping the *verbatim* claim is
    not dropping verification: ``unverified`` means untraceable to any line,
    which is a fabrication or a splice, and both remain defects in a layer that
    only claims to be tidied. What a voiced heading switches off is the
    contract axis — see :func:`verify_artifact_contract`.
    """
    _summary, moments = _split_scene_body(text)
    if not moments:
        return []
    # Keep line numbers pointing at the real file, not the extracted section.
    offset = text.find(moments)
    line_offset = text.count("\n", 0, offset) if offset > 0 else 0
    return _parse_blockquote_quotes(
        moments, artifact, line_offset=line_offset, speaker_from_blocks=True
    )


# ── Report ───────────────────────────────────────────────────────────────────

#: Limitations always stated in the report. Never empty — Principle VIII: a
#: question the system surfaces is worth as much as an answer it gives.
NOT_CHECKED = [
    'Inline `"…"` spans in prose — not reliably dialogue (a plaque honouring '
    'the "liberators of the Ordning" is a label, not speech). Only `> "…"` '
    "blockquotes are verified.",
    "Speaker attribution. This report answers *were these words said*, not "
    "*did this person say them*.",
]

NOT_CHECKED_SCENES = (
    "`## Scene summary` sections — human-authored gm-assist content, not model output."
)

NOT_CHECKED_VOICED = (
    "Contract rules R1/R3 in any file whose moments section is `## Voiced "
    "moments` — that heading declares the quotes are tidied, so the exactness "
    "those rules police was never claimed. Verdicts still apply there."
)


@dataclass
class VerificationReport:
    transcript: Path
    threshold: float
    min_tokens: int
    artifacts: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    conflicts: ConflictScan = field(default_factory=ConflictScan)
    #: artifact → what its moments section claims. Populated per artifact so
    #: the report can say *why* a file produced no refusals (R5).
    claims: dict[Path, str] = field(default_factory=dict)
    not_checked: list[str] = field(default_factory=lambda: list(NOT_CHECKED))
    generated_at: str = ""

    @property
    def counts(self) -> dict[Verdict, int]:
        out = {v: 0 for v in Verdict}
        for f in self.findings:
            out[f.verdict] += 1
        return out

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.is_problem]

    @property
    def refusal_counts(self) -> dict[Rule, int]:
        out = {r: 0 for r in Rule}
        for r in self.refusals:
            out[r.rule] += 1
        return out

    @property
    def voiced_artifacts(self) -> list[Path]:
        """Artifacts outside the contract because they declare tidied quotes (R5)."""
        return [p for p, c in self.claims.items() if c == CLAIM_VOICED]

    @property
    def verbatim_artifacts(self) -> list[Path]:
        return [p for p, c in self.claims.items() if c != CLAIM_VOICED]


def _sorted_for_report(findings: list[Finding]) -> list[Finding]:
    """Unverified first (worst score first), then near, then unscored."""
    rank = {Verdict.UNVERIFIED: 0, Verdict.NEAR: 1, Verdict.UNSCORED: 2}
    shown = [f for f in findings if f.verdict in rank]
    return sorted(shown, key=lambda f: (rank[f.verdict], f.score if f.score is not None else 1.0))


def render_report(report: VerificationReport) -> str:
    counts = report.counts
    total = len(report.findings)
    out: list[str] = ["# Quote Verification Report", ""]
    out.append(f"**Generated**: {report.generated_at}")
    out.append(f"**Transcript**: `{report.transcript}`")
    out.append(f"**Threshold**: {report.threshold} (near/unverified boundary)")
    out.append(f"**Minimum tokens to score**: {report.min_tokens}")
    out.append("")

    if total == 0:
        out.append("**No quotes found.** Nothing was checked — this is not the "
                   "same as everything passing. Verify the input is the right "
                   "file and that it uses `> \"…\"` blockquotes.")
        out.append("")
    else:
        out.append("| verdict | count | share |")
        out.append("|---|---|---|")
        for v in (Verdict.VERIFIED, Verdict.NEAR, Verdict.UNVERIFIED,
                  Verdict.UNSCORED, Verdict.EXEMPT):
            n = counts[v]
            label = f"**{v.value}**" if v is Verdict.UNVERIFIED and n else v.value
            out.append(f"| {label} | {n} | {n / total:.0%} |")
        out.append("")
        rc = report.refusal_counts
        n_ref = len(report.refusals)
        out.append(
            f"**Refused by the extraction contract (#250)**: {n_ref}"
            + (f" — R1 {rc[Rule.R1]}, R3 {rc[Rule.R3]}." if n_ref else ".")
        )
        out.append("")

    out.append("## Not checked")
    out.append("")
    for item in report.not_checked:
        out.append(f"- {item}")
    out.append("")

    out.extend(_render_refusals(report))

    shown = _sorted_for_report(report.findings)
    unverified = [f for f in shown if f.verdict is Verdict.UNVERIFIED]
    near = [f for f in shown if f.verdict is Verdict.NEAR]
    unscored = [f for f in shown if f.verdict is Verdict.UNSCORED]

    out.append("## Unverified — review these")
    out.append("")
    if not unverified:
        out.append("None. No quote was untraceable to the transcript.")
        out.append("")
    else:
        for f in unverified:
            out.extend(_render_finding(f))

    if near:
        out.append("## Near — an edit happened here (traceable, not verbatim)")
        out.append("")
        out.append(
            "Most of these are disfluency edits: the extraction tidied a filler "
            "word out of a real line. Listed after the unverified section on "
            "purpose — they are the majority and should not bury the findings "
            "that matter."
        )
        out.append("")
        out.append(
            "**But `near` means *an edit*, not *a safe edit*.** Similarity cannot "
            "tell the two apart: a measured DeepSeek run scored "
            "`\"My kind has been spreading violence\"` (transcript: `\"Mankind …\"`) "
            "at **0.92** and the harmless `\"No, I have\"` for `\"No, I, I have,\"` "
            "at **0.94** — the meaning-changing edit ranked *below* the harmless "
            "one, and no threshold separates them, because both are edits of the "
            "same tiny size. Skim this list for changed *words*, not low scores."
        )
        out.append("")
        for f in near:
            out.extend(_render_finding(f))

    if unscored:
        out.append("## Unscored — too short to judge")
        out.append("")
        out.append(
            f"Under {report.min_tokens} tokens. A quote this short matches "
            "something in any transcript, so neither a high nor a low score "
            "means anything. Not an accusation."
        )
        out.append("")
        for f in unscored:
            out.append(f"- `{f.quote.artifact.name}:{f.quote.line_no}` — \"{f.quote.text}\"")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def _render_refusals(report: VerificationReport) -> list[str]:
    """The `## Refused` section — always emitted, empty or not.

    Printed before `## Unverified` because a refusal is the stronger claim: an
    unverified quote is a thing to look at, a refused span is a thing the
    pipeline has declined to decide for you.
    """
    scan = report.conflicts
    out = ["## Refused — the contract will not choose for you", ""]
    out.append(
        "Extraction contract #250 (`docs/design/ExtractionContract_proposal.md`), "
        "rules R1 and R3. A refusal is **not** a claim that the text is wrong. "
        "It is a claim that this pipeline is not the thing that should decide, "
        "so the span stays as it is until you rule on it. Nothing here was "
        "auto-corrected and nothing here will be — and nothing here is blocked "
        "either: `sd_narrate` still renders these. Refusal means flagged."
    )
    out.append("")

    if scan.paired:
        out.append(
            f"R1 scanned **{scan.paired}** span(s) carried by both sections: "
            f"**{scan.consistent}** consistent (identical, or verbatim in both "
            f"— never a conflict), **{scan.settled}** settled by the transcript, "
            f"**{scan.refused}** refused."
        )
        out.append("")

    if report.voiced_artifacts:
        n = len(report.voiced_artifacts)
        out.append(
            f"**{n} artifact(s) declare `## Voiced moments`** and are outside the "
            f"contract (R5): a section that says its quotes are tidied has not "
            f"claimed the exactness R1 and R3 police. Their quotes are still "
            f"classified — `unverified` means untraceable, which is a splice or a "
            f"fabrication whatever the heading says."
        )
        out.append("")

    if not report.refusals:
        if report.voiced_artifacts and not report.verbatim_artifacts:
            out.append("Not applicable. Nothing checked here claims to be verbatim.")
        else:
            out.append("None. No span was refused by R1 or R3.")
        out.append("")
        return out

    by_rule: dict[Rule, list[Refusal]] = {}
    for r in report.refusals:
        by_rule.setdefault(r.rule, []).append(r)

    for rule in (Rule.R1, Rule.R3):
        items = by_rule.get(rule)
        if not items:
            continue
        out.append(f"### {rule.value} — {len(items)} span(s)")
        out.append("")
        out.append(RULE_TEXT[rule])
        out.append("")
        for r in items:
            out.extend(_render_refusal(r))
    return out


def _render_refusal(r: Refusal) -> list[str]:
    q = r.quote
    loc = f"`{q.artifact.name}:{q.line_no}`"
    if q.section:
        loc += f" (§ {q.section})"
    lines = [f"#### {loc}", ""]
    lines.append(f'- **Quote**: "{q.text}"')
    if r.verdict is not None:
        lines.append(f"- **Verdict**: {r.verdict.value}")
    if r.rule is Rule.R3:
        lines.append(f"- **Editorial insertion(s)**: `{r.detail}`")
        lines.append(
            "- **To resolve**: rewrite the span so it is what was said, and "
            "put the clarification outside the quote."
        )
    else:
        lines.append(f"- **Conflict**: {r.detail}")
        if r.counterpart is not None:
            cv = r.counterpart_verdict.value if r.counterpart_verdict else "?"
            lines.append(
                f'- **Other copy** (`{r.counterpart.artifact.name}:'
                f'{r.counterpart.line_no}`, {cv}): "{r.counterpart.text}"'
            )
        if r.similarity is not None:
            lines.append(f"- **Similarity between the copies**: {r.similarity:.2f}")
        lines.append(
            "- **To resolve**: pick the copy the tape supports, or correct the "
            "tape (R2) if the transcript itself is the defect."
        )
    lines.append("")
    return lines


def _render_finding(f: Finding) -> list[str]:
    q = f.quote
    loc = f"`{q.artifact.name}:{q.line_no}`"
    if q.section:
        loc += f" (§ {q.section})"
    lines = [f"### {loc}", ""]
    lines.append(f'- **Quote**: "{q.text}"')
    if f.looks_stitched:
        lines.append(
            "- **Likely stitched**: contains `...` — two separate utterances "
            "joined into one quote. Usually fixed by splitting it, not by "
            "rewording."
        )
    if q.speaker_hint:
        lines.append(f"- **Attributed to**: {q.speaker_hint}")
    if f.score is not None:
        lines.append(f"- **Score**: {f.score:.2f}")
    if f.nearest_line:
        who = f" ({f.nearest_speaker})" if f.nearest_speaker else ""
        lines.append(f'- **Nearest transcript line**{who}: "{f.nearest_line}"')
    else:
        lines.append("- **Nearest transcript line**: none found")
    lines.append("")
    return lines


# ── Annotation ───────────────────────────────────────────────────────────────

def refusal_marker(rule: Rule) -> str:
    return f"<!-- cg:refused:{rule.value} -->"


def annotate_text(
    text: str,
    findings: list[Finding],
    refusals: list[Refusal] | None = None,
) -> tuple[str, int]:
    """Append markers to offending lines. Returns (text, n_added).

    Idempotent by construction: a line already carrying a marker does not
    receive it twice, so re-running produces a byte-identical file (FR-007).
    Only ``unverified`` findings are marked — marking ``near`` would re-import
    the false-positive problem the three-verdict design exists to avoid — plus
    every contract refusal, which is a separate axis and can land on a line
    that is already marked unverified or on one that is perfectly verbatim.
    Quote text between the delimiters is never touched (FR-006).
    """
    wanted: dict[int, list[str]] = {}
    for f in findings:
        if f.is_problem:
            wanted.setdefault(f.quote.line_no, []).append(ANNOTATION)
    for r in refusals or ():
        marker = refusal_marker(r.rule)
        slot = wanted.setdefault(r.quote.line_no, [])
        if marker not in slot:
            slot.append(marker)
    if not wanted:
        return text, 0

    lines = text.splitlines(keepends=True)
    added = 0
    for ln in sorted(wanted):
        i = ln - 1
        if i < 0 or i >= len(lines):
            continue
        raw = lines[i]
        newline = ""
        body = raw
        for suffix in ("\r\n", "\n", "\r"):
            if raw.endswith(suffix):
                body, newline = raw[: -len(suffix)], suffix
                break
        changed = False
        for marker in wanted[ln]:
            if marker in body:
                continue
            body = f"{body}  {marker}"
            added += 1
            changed = True
        if changed:
            lines[i] = f"{body}{newline}"
    return "".join(lines), added


# ── Orchestration ────────────────────────────────────────────────────────────

def read_preserving_newlines(path: Path) -> str:
    """Read a file WITHOUT translating line endings.

    ``Path.read_text()`` applies universal-newline translation, so a CRLF file
    comes back LF-only and writing it back would silently rewrite every line in
    the document. FR-006 permits exactly one modification — appending a marker
    to an unverified quote's line — so the read side has to be lossless too.
    """
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def verify_artifact(
    path: Path,
    transcript: SourceTranscript,
    *,
    kind: str,
    threshold: float = DEFAULT_THRESHOLD,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> list[Finding]:
    """Parse and classify one artifact — verdicts only.

    ``kind`` is ``summary`` or ``scene``. This is the spec-007 layer and
    answers only *is this in the tape*. For the #250 contract axis on top of
    it, call :func:`verify_artifact_contract`.
    """
    text = read_preserving_newlines(Path(path))
    parser = parse_summary_quotes if kind == "summary" else parse_scene_quotes
    quotes = parser(text, Path(path))
    return [
        classify(q, transcript, threshold=threshold, min_tokens=min_tokens)
        for q in quotes
    ]


@dataclass
class ArtifactResult:
    """Both axes for one artifact: what the tape says, and what may render."""

    path: Path
    kind: str
    findings: list[Finding] = field(default_factory=list)
    refusals: list[Refusal] = field(default_factory=list)
    conflicts: ConflictScan = field(default_factory=ConflictScan)
    #: What this artifact's moments section promises — `verbatim`, `voiced`, or
    #: `""` for a file with no dual-section layout. A `voiced` artifact carries
    #: no refusals by construction (R5), so an empty refusal list means two
    #: different things and the report has to be able to tell them apart.
    claim: str = CLAIM_VERBATIM


def verify_artifact_contract(
    path: Path,
    transcript: SourceTranscript,
    *,
    kind: str,
    threshold: float = DEFAULT_THRESHOLD,
    min_tokens: int = DEFAULT_MIN_TOKENS,
) -> ArtifactResult:
    """Verdicts plus the ratified extraction contract (#250 R1/R3/R5).

    R3 applies to both stages — an editorial hand inside a verbatim span is
    the same defect wherever it appears. R1 applies only to scene extractions,
    because it compares two sections and a Stage 1 summary has only one.

    **R5: the contract binds what a section promises.** A scene file whose
    moments heading reads ``## Voiced moments`` has declared that its quotes
    are tidied, and both rules then have nothing to say — R3 objects to an
    editorial hand inside a span *marked verbatim*, and R1 asks which of two
    copies is *faithful*. Neither question survives the declaration. Verdicts
    are still computed and ``unverified`` is still a defect, because a
    fabrication or a splice is untraceable whatever the heading claims.
    """
    path = Path(path)
    text = read_preserving_newlines(path)
    if kind == "summary":
        quotes = parse_summary_quotes(text, path)
        claim = CLAIM_VERBATIM
    else:
        quotes = parse_scene_quotes(text, path)
        _summary, _moments, claim = split_scene_sections(text)

    findings = [
        classify(q, transcript, threshold=threshold, min_tokens=min_tokens)
        for q in quotes
    ]
    result = ArtifactResult(path=path, kind=kind, findings=findings, claim=claim)
    if claim == CLAIM_VOICED:
        return result

    result.refusals.extend(find_bracket_refusals(findings))
    if kind != "summary":
        result.conflicts = scan_section_conflicts(
            parse_scene_summary_spans(text, path), findings, transcript,
            threshold=threshold, min_tokens=min_tokens,
        )
        result.refusals.extend(result.conflicts.refusals)
    return result


# A blockquote line that opens a quote but never closes it on the same line.
# Every one of the 534 quotes in the measured corpus is single-line, so the
# parser only handles that shape — but a multi-line quote would then be
# silently skipped, and silent non-coverage reads exactly like a pass. Counting
# them lets the report say so instead (Principle VIII).
_UNCLOSED_QUOTE_RE = re.compile(r'^\s*>\s*[""“][^""”]*$')


def count_unparsed_quote_lines(text: str) -> int:
    return sum(1 for ln in text.splitlines() if _UNCLOSED_QUOTE_RE.match(ln))


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()
