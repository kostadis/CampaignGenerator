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
an additive ``<!-- cg:unverified -->`` marker on an unverified quote's line,
applied idempotently. Repairing quotes automatically is out of scope by
design: ``scrub_mechanics.py`` was an autonomous LLM repair pass that stripped
spells out of narration (issue #151) and was replaced by a propose→confirm→
apply workflow. Verbatim text is the one thing this module must never touch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

from campaignlib.textproc import locate_quote

from .io import parse_vtt, _split_scene_body


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

# Markers the generation prompts define for "no verbatim quote exists", plus
# the [inaudible] convention that appears in real extractions but that neither
# prompt documents (research D3). A quote consisting wholly of one of these is
# the extractor reporting absence correctly, not fabricating.
_EXEMPT_RE = re.compile(
    r"^\s*[\[(]\s*(inaudible|paraphrase|truncated|unintelligible|silence)\b[^\])]*[\])]\s*$",
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

    Only the ``## Verbatim moments`` section is checked. The other section,
    ``## Scene summary (from gm-assist, verbatim)``, is the GM's own
    hand-authored skeleton copied from ``gm-assist.md`` — flagging the human's
    phrasing as "unverified" would be both wrong and an insult to the
    checkpoint that produced it (research D4).
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


@dataclass
class VerificationReport:
    transcript: Path
    threshold: float
    min_tokens: int
    artifacts: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
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

    out.append("## Not checked")
    out.append("")
    for item in report.not_checked:
        out.append(f"- {item}")
    out.append("")

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
        out.append("## Near — traceable, not verbatim (informational)")
        out.append("")
        out.append(
            "Overwhelmingly disfluency edits: the extraction tidied a filler "
            "word out of a real line. Listed after the unverified section on "
            "purpose — these are the majority and should not bury the findings "
            "that matter."
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

def annotate_text(text: str, findings: list[Finding]) -> tuple[str, int]:
    """Append the unverified marker to offending lines. Returns (text, n_added).

    Idempotent by construction: a line already carrying the marker is left
    exactly as-is, so re-running produces a byte-identical file (FR-007). Only
    ``unverified`` lines are marked — marking ``near`` would re-import the
    false-positive problem the three-verdict design exists to avoid. Quote text
    between the delimiters is never touched (FR-006).
    """
    targets = sorted({f.quote.line_no for f in findings if f.is_problem})
    if not targets:
        return text, 0

    lines = text.splitlines(keepends=True)
    added = 0
    for ln in targets:
        i = ln - 1
        if i < 0 or i >= len(lines):
            continue
        raw = lines[i]
        if ANNOTATION in raw:
            continue
        newline = ""
        body = raw
        for suffix in ("\r\n", "\n", "\r"):
            if raw.endswith(suffix):
                body, newline = raw[: -len(suffix)], suffix
                break
        lines[i] = f"{body}  {ANNOTATION}{newline}"
        added += 1
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
    """Parse and classify one artifact. ``kind`` is ``summary`` or ``scene``."""
    text = read_preserving_newlines(Path(path))
    parser = parse_summary_quotes if kind == "summary" else parse_scene_quotes
    quotes = parser(text, Path(path))
    return [
        classify(q, transcript, threshold=threshold, min_tokens=min_tokens)
        for q in quotes
    ]


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
