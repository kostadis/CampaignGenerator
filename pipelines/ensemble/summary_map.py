#!/usr/bin/env python3
"""Propose a chapter <-> session-summary mapping (issue #199, prerequisite only).

``enhance_summary`` already produces a structured ``session-summary.md`` per
recorded session (``## Summary / Memorable Moments / Scenes / Locations /
NPCs / Items / Spells``), and its ``## Scenes`` entries are a correct,
attributed per-scene account of what happened. The five-lens ensemble then
re-derives the same information from chapter prose, by inference over
decontextualized fact fragments — the exact round trip
(structure -> prose -> re-extract structure) that
``docs/design/EnsembleGroundingInvestigation.md`` #199 identifies as lossy.

Wiring the summary into synthesis is NOT this script's job. Before a summary
can ground anything, something has to say *which* summary corresponds to
*which* chapter — and today nothing does: summaries are keyed by session
date (``summaries/20260720/``), chapters by filename index, and the
in-file heading numbers disagree with both (the documented BOM off-by-one:
a chapter file named ``chapter_62_*.md`` opens with ``# Chapter 59``).

This script proposes that mapping. It does NOT decide it. Per this repo's
"LLM renders, humans decide" rule (CLAUDE.md), scope/attribution is a
precision decision — a chapter is matched to a summary here by *evidence*
(scene-heading overlap, secondarily document-order proximity), written to
YAML with ``approved: false``, and a human flips it to ``true`` after
checking the evidence. Nothing downstream may read this file until that
happens; no caller of this file exists yet on purpose (synthesis is not
touched by this phase).

**Deterministic only — no LLM call, no ``campaignlib`` API client.** The
signal here (do these two ordered lists of headings talk about the same
scenes?) is fully computable; reaching for a model to disambiguate would
just relocate the GM's decision into another unreviewed LLM call.

Matching signals:

  1. **Scene-heading overlap (primary).** A structured summary's
     ``## Scenes`` section lists ordered ``### <title>`` scenes. A chapter's
     ``## <heading>`` lines are scored against that list by normalised text
     similarity (``difflib.SequenceMatcher``). Chapters commonly use the
     ``## Name — Scene`` convention (POV name, em dash, scene title) — the
     POV prefix is stripped before comparing, since it is bookkeeping, not
     content the summary would ever record.
  2. **Document-order proximity (secondary, tie-break only).** Summaries
     carry a real calendar date in their directory name; chapters carry
     only a filename index, not a date. This script interpolates each
     dated summary's *expected* chapter-index by its rank among all dated
     summaries (assumes roughly steady pacing) and uses distance from that
     expected index to break near-ties in the overlap score. It is never
     blended into the confidence number itself, so ``confidence`` always
     means exactly one thing: how well the headings agree.

Only 11 of 16 real OOTA summaries have the structured ``## Scenes``
section (the earliest ones use a looser ``## Overview / Session Events``
shape). An unstructured summary contributes an empty scene list, which the
overlap scorer naturally always scores 0 against — so it can never win a
confident match. This script does not invent one; a chapter with no
confident candidate gets ``summary: null`` and an evidence block explaining
why, plus (when available) the nearest-by-position summary as an FYI for
the human, never as a proposal.

62 chapters, 16 summaries: most chapters are expected to map to nothing,
because most recorded sessions never got a written recap at all.

Usage:

    summary_map --chapters-glob 'docs/chapters/chapter_*.md' \\
                --summaries-dir summaries \\
                --out docs/ensemble/summary_map.yaml

Re-running is safe for human review in progress: any row a GM already
flipped to ``approved: true`` is preserved byte-for-byte and never
recomputed. Everything else (new chapters, still-unapproved rows) is
recomputed fresh every run, so the file stays current as chapters or
summaries are added. Pass --force to discard every existing approval and
regenerate the whole file from scratch.
"""

import argparse
import glob as glob_module
import re
import sys
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from campaignlib import utc_now_iso

# Mirrors campaignlib.textproc's _H2_RE / _H2_SPEAKER_RE / _H3_RE exactly.
# Kept as a local copy rather than imported: those are underscore-prefixed
# helpers private to textproc's chunk-annotation use case (see
# pipelines/grounding/normalize_bible_headings.py for the same precedent),
# and this script's use — heading *extraction*, not chunk *annotation* — is
# a different job that happens to need the same three patterns.
_H2_RE = re.compile(r'^##(?!#)\s+(.+)$', re.MULTILINE)
_H2_SPEAKER_RE = re.compile(r'^##(?!#)\s+(.+?)\s+—\s+(.+)$', re.MULTILINE)
_H3_RE = re.compile(r'^###\s+(.+)$', re.MULTILINE)

_DATE_DIR_RE = re.compile(r'^(\d{4})(\d{2})(\d{2})$')
_CHAPTER_INDEX_RE = re.compile(r'chapter_(\d+)', re.IGNORECASE)

# A chapter is only proposed a summary when the mean best-match heading
# score clears this bar. Calibrated against the real OOTA corpus (62
# chapters x 16 summaries, all pairs scored — see the "REAL OOTA
# VALIDATION" run this was checked against): every genuine match (a chapter
# whose ## headings really are a summary's scenes, POV-prefix stripped)
# scored >= 0.992, chapter_62 -> summaries/20260720 among them at 1.0.
# Every coincidental short-heading collision (chapters with 1-2 generic
# ## headings matching unrelated scene text on shared common words) topped
# out at 0.511. That is a ~0.48-wide dead zone with nothing in it — 0.75
# sits in the middle of it, nowhere near either edge, rather than on a
# boundary that the next campaign's vocabulary could shift past.
MIN_CONFIDENCE_DEFAULT = 0.75

# A single heading-pair match at/above this score counts as "confident" for
# the human-readable coverage note in evidence (informational only — it does
# not feed the confidence number, which is always the plain mean).
CONFIDENT_HEADING_SCORE = 0.6

# Candidates within this much of the top score are considered tied and
# broken by document-order proximity instead of an arbitrary sort order.
TIE_EPSILON = 0.05


# ── Heading extraction ──────────────────────────────────────────────────

def parse_chapter_headings(text: str) -> list[str]:
    """Return a chapter's ``##``-level headings as scene-comparable text.

    ``## Name — Scene`` headings keep only the scene half (the POV name is
    bookkeeping a summary never records). Plain ``##`` headings (date
    boundaries, or campaigns that don't use the POV-prefix convention) are
    kept verbatim — they simply will not overlap with a summary's scene
    titles, which is the conservative, correct behaviour rather than a
    special case: see the heading-convention table in
    docs/design/EnsembleGroundingInvestigation.md (#202) — 14/62 OOTA
    chapters use ``## Name — Scene``, 25 use a plain ``## <date>``, 7 use
    ``### Name`` only (no ``##`` at all), 16 have no heading structure.
    """
    headings = []
    for m in _H2_RE.finditer(text):
        speaker_match = _H2_SPEAKER_RE.match(m.group(0))
        if speaker_match:
            headings.append(speaker_match.group(2).strip())
        else:
            headings.append(m.group(1).strip())
    return headings


def parse_summary_scenes(text: str) -> list[str] | None:
    """Return the ordered ``### <title>`` scenes under a summary's ``## Scenes``.

    Returns None if the summary has no ``## Scenes`` section at all (or the
    section is empty) — the signal for "unstructured", not an empty list.
    Only 11 of 16 real OOTA summaries have this section; the other 5 use a
    looser ``## Overview / Session Events`` shape with no ordered scene list
    to compare against.
    """
    h2_matches = list(_H2_RE.finditer(text))
    scenes_start = None
    scenes_end = len(text)
    for i, m in enumerate(h2_matches):
        if m.group(1).strip().lower() == "scenes":
            scenes_start = m.end()
            if i + 1 < len(h2_matches):
                scenes_end = h2_matches[i + 1].start()
            break
    if scenes_start is None:
        return None
    section = text[scenes_start:scenes_end]
    scenes = [m.group(1).strip() for m in _H3_RE.finditer(section)]
    return scenes or None


def _normalize_heading(text: str) -> str:
    """Lowercase, punctuation-stripped comparison key for heading text."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def heading_similarity(a: str, b: str) -> float:
    """Deterministic text-similarity ratio (stdlib difflib, no embeddings)."""
    return SequenceMatcher(None, _normalize_heading(a), _normalize_heading(b)).ratio()


# ── Discovery ────────────────────────────────────────────────────────────

@dataclass
class ChapterInfo:
    path: Path
    index: int | None
    headings: list[str]


@dataclass
class SummaryInfo:
    path: Path                 # .../session-summary.md
    summary_id: str            # str(path.parent), e.g. "summaries/20260720"
    dir_date: date | None      # parsed from the parent dirname, or None
    raw_dirname: str = ""
    scenes: list[str] | None = None
    structured: bool = False


def chapter_index_from_filename(path: Path) -> int | None:
    """Trust the filename's number, not in-file heading numbers.

    The investigation doc records that chapter files, in-file headings, and
    summary session numbering all disagree (the BOM off-by-one: a file
    named ``chapter_62_*.md`` opens with ``# Chapter 59``). The filename
    index is what ``ensemble_batch`` already treats as authoritative — it
    stamps ``source_chapter = chapter.stem`` onto every fact — so this
    script uses the same source of truth rather than adding a fourth
    disagreeing counter.
    """
    m = _CHAPTER_INDEX_RE.search(path.stem)
    return int(m.group(1)) if m else None


def summary_date_from_dirname(dirname: str) -> date | None:
    m = _DATE_DIR_RE.match(dirname)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def discover_chapters(chapters_glob: str) -> list[ChapterInfo]:
    paths = sorted(Path(p) for p in glob_module.glob(chapters_glob))
    chapters = []
    for p in paths:
        text = p.read_text(encoding="utf-8")
        chapters.append(ChapterInfo(
            path=p,
            index=chapter_index_from_filename(p),
            headings=parse_chapter_headings(text),
        ))
    return chapters


def discover_summaries(summaries_dir: Path) -> list[SummaryInfo]:
    """Recursively find every ``session-summary.md`` under summaries_dir.

    Real campaign trees do not keep these flat — OOTA has 14 of 16 nested
    under ``summaries/old/`` (some further nested, e.g.
    ``summaries/old/20260404.old/``) — so this walks the whole tree
    (``rglob``) rather than listing immediate children.
    """
    paths = sorted(summaries_dir.rglob("session-summary.md"))
    summaries = []
    for p in paths:
        parent = p.parent
        dirname = parent.name
        text = p.read_text(encoding="utf-8")
        scenes = parse_summary_scenes(text)
        summaries.append(SummaryInfo(
            path=p,
            summary_id=parent.as_posix(),
            dir_date=summary_date_from_dirname(dirname),
            raw_dirname=dirname,
            scenes=scenes,
            structured=scenes is not None,
        ))
    return summaries


def build_expected_index_map(summaries: list["SummaryInfo"], num_chapters: int) -> dict[str, float]:
    """Interpolate each dated summary's expected chapter index by date rank.

    Chapters carry no calendar date at all, only a filename index — so
    "date proximity" is necessarily approximate: this assumes chapters
    accumulate at roughly the pace sessions were recorded and places each
    dated summary at the chapter index its rank-fraction among all dated
    summaries would predict. It is a tie-break signal only (TIE_EPSILON),
    never a source of confidence by itself. Needs >= 2 dated summaries to
    interpolate at all; returns {} otherwise.
    """
    dated = sorted((s for s in summaries if s.dir_date is not None), key=lambda s: s.dir_date)
    n = len(dated)
    if n < 2 or num_chapters < 2:
        return {}
    return {
        s.summary_id: 1 + (rank / (n - 1)) * (num_chapters - 1)
        for rank, s in enumerate(dated)
    }


# ── Scoring ──────────────────────────────────────────────────────────────

def score_overlap(chapter_headings: list[str], summary_scenes: list[str] | None) -> tuple[float, list[dict]]:
    """Mean best-match heading-similarity score, plus the matched pairs.

    The matched pairs ARE the evidence a human checks before flipping
    approved: true — this function never returns a bare number without
    them. An empty scene list (unstructured summary) or empty heading list
    (chapter with no ``##`` headings at all) always scores 0.0 with no
    evidence, by construction — that is what correctly prevents an
    unstructured summary or a headingless chapter from ever winning a
    confident match.
    """
    if not chapter_headings or not summary_scenes:
        return 0.0, []
    matched = []
    for heading in chapter_headings:
        best_score = 0.0
        best_scene = None
        for scene in summary_scenes:
            s = heading_similarity(heading, scene)
            if s > best_score:
                best_score = s
                best_scene = scene
        matched.append({
            "chapter_heading": heading,
            "summary_scene": best_scene,
            "score": round(best_score, 3),
        })
    overlap = sum(m["score"] for m in matched) / len(matched)
    return round(overlap, 3), matched


def propose_for_chapter(
    chapter: ChapterInfo,
    summaries: list[SummaryInfo],
    expected_index: dict[str, float],
    min_confidence: float,
) -> dict:
    """Score every summary against one chapter and return its YAML entry.

    Picks the top-scoring summary if it clears min_confidence; ties within
    TIE_EPSILON of the top score are broken by document-order proximity
    (build_expected_index_map). Below min_confidence, returns
    summary: null with the best-scored candidate and nearest-by-position
    summary surfaced as evidence, never as a guess — see module docstring.
    """
    scored = [
        (s, *score_overlap(chapter.headings, s.scenes))
        for s in summaries
    ]
    scored.sort(key=lambda t: t[1], reverse=True)

    entry: dict = {
        "chapter": chapter.path.name,
        "chapter_index": chapter.index,
    }

    top_score = scored[0][1] if scored else 0.0
    if not scored or top_score < min_confidence or top_score == 0.0:
        best = scored[0] if scored else None
        nearest_id = None
        if chapter.index is not None and expected_index:
            nearest_id = min(
                expected_index, key=lambda sid: abs(expected_index[sid] - chapter.index)
            )
        entry.update({
            "summary": None,
            "confidence": 0.0,
            "approved": False,
            "evidence": {
                "method": "none",
                "reason": (
                    f"no summary scored >= {min_confidence} on scene-heading overlap "
                    f"({len(chapter.headings)} chapter heading(s) found)"
                ),
                "best_scored_candidate": (
                    {"summary": best[0].summary_id, "score": best[1]}
                    if best is not None and best[1] > 0 else None
                ),
                "nearest_by_position": nearest_id,
            },
        })
        return entry

    # Tie-break candidates must themselves still clear min_confidence — a
    # weak candidate that only *looks* tied because a stronger sibling
    # dragged top_score down must never be allowed to win and report a
    # confidence below the bar this function just checked (that would
    # silently contradict the entry's own gate: see the calibration note in
    # tests/test_summary_map.py for the real bug this guards).
    tied = [t for t in scored if top_score - t[1] <= TIE_EPSILON and t[1] >= min_confidence]
    winner = scored[0]
    tie_break_note = None
    if len(tied) > 1 and chapter.index is not None and expected_index:
        candidates = [
            (t, expected_index[t[0].summary_id])
            for t in tied if t[0].summary_id in expected_index
        ]
        if candidates:
            winner, _ = min(candidates, key=lambda tp: abs(tp[1] - chapter.index))
            tie_break_note = (
                f"{len(tied)} summaries scored within {TIE_EPSILON} of the top "
                f"score; picked by nearest expected chapter position"
            )

    summary, overlap, matched = winner
    confident_n = sum(1 for m in matched if m["score"] >= CONFIDENT_HEADING_SCORE)
    evidence = {
        "method": "scene_heading_overlap",
        "matched": matched,
        "coverage": f"{confident_n}/{len(matched)} heading(s) scored >= {CONFIDENT_HEADING_SCORE}",
    }
    if tie_break_note:
        evidence["tie_break"] = tie_break_note
    entry.update({
        "summary": summary.summary_id,
        "summary_date": summary.dir_date,
        "confidence": overlap,
        "approved": False,
        "evidence": evidence,
    })
    return entry


# ── Preserve-on-rerun ────────────────────────────────────────────────────

def load_approved(path: Path) -> dict[str, dict]:
    """Return {chapter filename: entry} for every approved: true row in path.

    Anything not approved is dropped here on purpose — it gets recomputed
    fresh on every run. Only a human's approved: true is a one-way door.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"warning: could not parse existing {path}: {exc} — ignoring it", file=sys.stderr)
        return {}
    entries = data.get("entries") or []
    return {
        e["chapter"]: e
        for e in entries
        if isinstance(e, dict) and e.get("approved") is True and e.get("chapter")
    }


# ── CLI ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--chapters-glob", default="docs/chapters/chapter_*.md", metavar="GLOB",
        help="Glob for chapter files — same convention ensemble_batch's --chapters "
             "already uses (default: docs/chapters/chapter_*.md)",
    )
    p.add_argument(
        "--summaries-dir", default="summaries", metavar="DIR",
        help="Root directory to search recursively for session-summary.md files. "
             "Real campaigns nest these under dated subdirectories, sometimes "
             "several levels deep (e.g. summaries/old/20260420/session-summary.md) "
             "— every session-summary.md anywhere under this tree is found "
             "(default: summaries)",
    )
    p.add_argument(
        "--out", default="docs/ensemble/summary_map.yaml", metavar="FILE",
        help="Where to write the proposed mapping (default: docs/ensemble/summary_map.yaml)",
    )
    p.add_argument(
        "--min-confidence", type=float, default=MIN_CONFIDENCE_DEFAULT, metavar="FLOAT",
        help="Minimum mean scene-heading-overlap score (0-1) required before a "
             "chapter gets a proposed summary at all; below this the row is left "
             f"with summary: null instead of a low-confidence guess (default: {MIN_CONFIDENCE_DEFAULT})",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Discard every existing approved: true row in --out and regenerate "
             "the whole file from scratch. Without this flag, a rerun preserves "
             "every row a human already approved byte-for-byte and only "
             "recomputes the rest — approving a row is a one-way door unless you "
             "pass this.",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    chapters = discover_chapters(args.chapters_glob)
    if not chapters:
        print(f"No chapter files matched: {args.chapters_glob}", file=sys.stderr)
        sys.exit(1)

    summaries_dir = Path(args.summaries_dir)
    if not summaries_dir.is_dir():
        print(f"Summaries directory not found: {summaries_dir}", file=sys.stderr)
        sys.exit(1)
    summaries = discover_summaries(summaries_dir)
    if not summaries:
        print(f"No session-summary.md files found under: {summaries_dir}", file=sys.stderr)
        sys.exit(1)

    structured = [s for s in summaries if s.structured]
    unstructured = [s for s in summaries if not s.structured]
    print(f"Chapters:   {len(chapters)} matched {args.chapters_glob!r}")
    print(f"Summaries:  {len(summaries)} found under {summaries_dir} "
          f"({len(structured)} structured, {len(unstructured)} unstructured — "
          f"unstructured summaries have no ## Scenes section and can never win "
          f"a confident match)")

    seen_dates: dict[date, list[str]] = {}
    for s in summaries:
        if s.dir_date is not None:
            seen_dates.setdefault(s.dir_date, []).append(s.summary_id)
    collisions = {d: ids for d, ids in seen_dates.items() if len(ids) > 1}
    if collisions:
        print(f"  note: {len(collisions)} date(s) have more than one session-summary.md "
              f"(kept as separate entries — see 'summaries:' in the output; which one is "
              f"authoritative is a human call, not auto-resolved):")
        for d, ids in sorted(collisions.items()):
            print(f"    {d}: {', '.join(sorted(ids))}")
    unparsed = [s for s in summaries if s.dir_date is None]
    if unparsed:
        print(f"  note: {len(unparsed)} summary dir name(s) did not parse as YYYYMMDD "
              f"(date proximity unavailable for these): "
              f"{', '.join(sorted(s.summary_id for s in unparsed))}")

    expected_index = build_expected_index_map(summaries, len(chapters))

    out_path = Path(args.out)
    approved = load_approved(out_path)
    if args.force:
        if approved:
            print(f"--force: discarding {len(approved)} previously-approved row(s) in {out_path}",
                  file=sys.stderr)
        approved = {}

    entries = []
    consumed: set[str] = set()
    proposed = unmatched = preserved = 0
    for chapter in chapters:
        key = chapter.path.name
        if key in approved:
            entries.append(approved[key])
            consumed.add(key)
            preserved += 1
            continue
        entry = propose_for_chapter(chapter, summaries, expected_index, args.min_confidence)
        entries.append(entry)
        if entry["summary"] is not None:
            proposed += 1
        else:
            unmatched += 1

    orphaned = set(approved) - consumed
    if orphaned:
        print(f"warning: {len(orphaned)} previously-approved chapter row(s) no longer match "
              f"a discovered chapter file — dropped from output: {sorted(orphaned)}",
              file=sys.stderr)

    summaries_catalog = [
        {
            "id": s.summary_id,
            "date": s.dir_date,
            "structured": s.structured,
            "scene_count": len(s.scenes) if s.scenes else 0,
        }
        for s in sorted(summaries, key=lambda s: (s.dir_date is None, s.dir_date or date.min, s.summary_id))
    ]

    doc = {
        "generated_at": utc_now_iso(),
        "chapters_glob": args.chapters_glob,
        "summaries_dir": str(summaries_dir),
        "min_confidence": args.min_confidence,
        "stats": {
            "chapters_found": len(chapters),
            "summaries_found": len(summaries),
            "summaries_structured": len(structured),
            "summaries_unstructured": len(unstructured),
            "chapters_proposed": proposed,
            "chapters_unmatched": unmatched,
            "chapters_preserved_approved": preserved,
        },
        "summaries": summaries_catalog,
        "entries": entries,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"\n[done] {proposed} proposed, {unmatched} unmatched, {preserved} preserved -> {out_path}")
    print("Nothing downstream reads this file yet. A human reviews the evidence for each "
          "proposed row and flips approved: false -> true before any consumer may rely on it.")


if __name__ == "__main__":
    main()
