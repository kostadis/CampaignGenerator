#!/usr/bin/env python3
"""Verify that quotes in session-doc artifacts really appear in the transcript.

Deterministic and free: no model is called, no API key is read, no token is
spent. See ``session_doc/verify_quotes.py`` for the three-verdict rationale and
``specs/007-two-phase-extraction/contracts/sd_verify_quotes.md`` for the
contract this implements.

Usage::

    sd_verify_quotes --vtt session.vtt --summary session-summary.md \\
        --out narration/quote_report.md

    sd_verify_quotes --vtt session.vtt \\
        --scene-extractions scene_extractions_new/ --report-only

Exit codes are meaningful — ``sd_agent`` depends on the 1/2 split to tell
"the check worked and found things" from "the check could not run":

    0  ran; no unverified quotes
    1  ran; one or more unverified quotes (a finding, not an error)
    2  could not run (no transcript, no artifact, unreadable input)
"""

import argparse
import sys
from pathlib import Path

from campaignlib.util import atomic_write_text

from .verify_quotes import (
    DEFAULT_MIN_TOKENS,
    DEFAULT_THRESHOLD,
    NOT_CHECKED,
    NOT_CHECKED_SCENES,
    SourceTranscript,
    Verdict,
    VerificationReport,
    annotate_text,
    count_unparsed_quote_lines,
    now_iso,
    read_preserving_newlines,
    render_report,
    verify_artifact,
)

# Sidecars scene_extract leaves beside the real files. Mirrors the filter in
# server/routers/scene_editor.py:api_pipeline_status so the two agree on what
# counts as a scene extraction.
_SKIP_SUFFIXES = (".scaffold.md", ".prev", ".reviewed")


def _scene_files(d: Path) -> list[Path]:
    return sorted(
        f for f in d.glob("[0-9][0-9]_*.md")
        if not any(f.name.endswith(s) for s in _SKIP_SUFFIXES)
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Verify quotes in session-doc artifacts against the session "
                    "transcript. Deterministic; calls no model.",
    )
    p.add_argument("--vtt", metavar="FILE", required=True,
                   help="Session transcript. MUST be the same .vtt the artifact "
                        "was generated from — verifying against a different one "
                        "reports edits that were never made.")
    p.add_argument("--summary", metavar="FILE",
                   help="Stage 1 session-summary.md. Only `> \"…\"` blockquotes "
                        "are checked; inline quotes in prose are not reliably "
                        "dialogue.")
    p.add_argument("--scene-extractions", metavar="DIR",
                   help="Stage 2 directory of NN_*.md. Only the "
                        "`## Verbatim moments` section of each file is checked — "
                        "`## Scene summary` is human-authored gm-assist content.")
    p.add_argument("--out", metavar="FILE", default=None,
                   help="Report path (default: quote_report.md beside the artifact).")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"near/unverified boundary (default: {DEFAULT_THRESHOLD}). "
                        "NOT calibrated for a local model — see research D8.")
    p.add_argument("--min-tokens", type=int, default=DEFAULT_MIN_TOKENS,
                   help=f"Below this many tokens a quote is 'unscored' rather "
                        f"than judged (default: {DEFAULT_MIN_TOKENS}).")
    p.add_argument("--report-only", action="store_true",
                   help="Write the report but do not annotate the artifacts.")
    p.add_argument("--verbose", action="store_true",
                   help="Print each per-quote classification.")
    return p


def main() -> int:
    args = build_parser().parse_args()

    if not args.summary and not args.scene_extractions:
        print("Error: give --summary and/or --scene-extractions (there is no "
              "implicit 'check everything').", file=sys.stderr)
        return 2

    try:
        transcript = SourceTranscript.load(Path(args.vtt))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    targets: list[tuple[Path, str]] = []
    if args.summary:
        sp = Path(args.summary).expanduser()
        if not sp.exists():
            print(f"Error: --summary not found: {sp}", file=sys.stderr)
            return 2
        targets.append((sp, "summary"))
    not_checked = list(NOT_CHECKED)
    if args.scene_extractions:
        sd = Path(args.scene_extractions).expanduser()
        if not sd.is_dir():
            print(f"Error: --scene-extractions is not a directory: {sd}", file=sys.stderr)
            return 2
        files = _scene_files(sd)
        if not files:
            print(f"Error: no NN_*.md scene extractions in {sd}", file=sys.stderr)
            return 2
        targets.extend((f, "scene") for f in files)
        not_checked.append(NOT_CHECKED_SCENES)

    print(f"[sd_verify_quotes | transcript: {transcript.path.name} | "
          f"{len(transcript.lines):,} cues | threshold {args.threshold}]")
    print("=" * 60)

    report = VerificationReport(
        transcript=transcript.path,
        threshold=args.threshold,
        min_tokens=args.min_tokens,
        not_checked=not_checked,
        generated_at=now_iso(),
    )

    unparsed = 0
    for path, kind in targets:
        try:
            findings = verify_artifact(
                path, transcript, kind=kind,
                threshold=args.threshold, min_tokens=args.min_tokens,
            )
            unparsed += count_unparsed_quote_lines(read_preserving_newlines(path))
        except OSError as e:
            print(f"Error: cannot read {path}: {e}", file=sys.stderr)
            return 2
        report.artifacts.append(path)
        report.findings.extend(findings)

    if unparsed:
        # Non-coverage must be stated, not inferred from a clean-looking report.
        msg = (f"{unparsed} blockquote line(s) opened a quote without closing it "
               f"on the same line and were NOT checked — the parser handles "
               f"single-line quotes only.")
        report.not_checked.append(msg)
        print(f"  warning: {msg}", file=sys.stderr)
        if args.verbose:
            for f in findings:
                print(f"  {f.verdict.value:11} {f.quote.artifact.name}:{f.quote.line_no}"
                      f"  \"{f.quote.text[:60]}\"")

    total = len(report.findings)
    counts = report.counts
    if total == 0:
        # Distinct from "all verified" (FR-010): finding nothing to check is
        # suspicious, and reporting it as a pass would be a lie of omission.
        print("  No quotes found. Nothing was checked — this is NOT the same as "
              "everything passing.")
    else:
        for v in (Verdict.VERIFIED, Verdict.NEAR, Verdict.UNVERIFIED,
                  Verdict.UNSCORED, Verdict.EXEMPT):
            n = counts[v]
            if not n:
                continue
            note = ""
            if v is Verdict.NEAR:
                note = "   — not verbatim, but traceable to a transcript line"
            elif v is Verdict.UNVERIFIED:
                note = "   ← review these"
            elif v is Verdict.UNSCORED:
                note = f"   — under {args.min_tokens} tokens, no reliable signal"
            elif v is Verdict.EXEMPT:
                note = "   — [inaudible] / (paraphrase) / (truncated)"
            print(f"    {v.value:11} {n:5}  ({n / total:>3.0%}){note}")

    n_annotated = 0
    if not args.report_only:
        by_file: dict[Path, list] = {}
        for f in report.findings:
            by_file.setdefault(f.quote.artifact, []).append(f)
        for path, findings in by_file.items():
            original = read_preserving_newlines(path)
            updated, added = annotate_text(original, findings)
            if added:
                atomic_write_text(path, updated)
                n_annotated += added

    out_path = Path(args.out).expanduser() if args.out else (
        (report.artifacts[0].parent if report.artifacts else Path.cwd()) / "quote_report.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out_path, render_report(report))

    print("=" * 60)
    n_problem = len(report.problems)
    if n_annotated:
        print(f"  Marked {n_annotated} line(s) with {'<!-- cg:unverified -->'}.")
    print(f"  {n_problem} unverified quote(s). Wrote {out_path}")
    if n_problem:
        print("  Nothing was auto-corrected — review the report and fix the source.")

    return 1 if n_problem else 0


if __name__ == "__main__":
    sys.exit(main())
