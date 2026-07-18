#!/usr/bin/env python3
"""Flag portable narration tics in an assembled per-POV narration document.

A mechanical backstop for the voice-critic pass. Splits a narration doc into
its ``## <Character> — <Scene>`` sections and checks for the cross-narrator tics
that the genre prompt bans but the model still emits:

- "the shape of X"            — gesturing at a pattern instead of naming it
- "with the <quality> of a man who ..."  — portable relative-clause portraits
- bookkeeping-verb convergence — "file/filed" leaking across every POV, and
  Thorin filing at all (he clocks/notes; he never files)

No model calls, no dependencies — pure stdlib, cheap to run in a loop.

Exit code is 1 if any hard ERROR fired (so it can gate a pipeline), else 0.

Usage:
    voice_lint path/to/gm-assist-doc.md
    voice_lint summaries/20260601/*.md
    voice_lint narration.md --quiet      # errors only, no warnings
"""

import argparse
import re
import sys
from pathlib import Path

SECTION_RE = re.compile(r"^##\s+(\w+)", re.M)  # "## Daz — ..." -> "Daz"
SHAPE_RE = re.compile(r"\bthe shape of\b", re.I)
PORTRAIT_RE = re.compile(
    r"\bwith the [^.,;]*? of (?:a |an |the )?"
    r"(?:man|woman|men|someone|creature|people|person)s?\b[^.]*?\bwho\b",
    re.I,
)
# The tic is FIRST-PERSON filing-as-cognition ("I file/filed ..."). Literal third-person
# usage ("the scholars file a grievance") is not the tic and must not trip the check.
FP_FILE_RE = re.compile(r"\bI fil(?:e|ed)\b", re.I)

# Grygum and Daz are the licensed filers (filing is canonical/identity per voice/_genre.md);
# the ban is on it bleeding into Thorin/Zalthir, plus over-repetition in any one section.
UNLICENSED_FILERS = ("thorin", "zalthir")


def split_sections(text):
    """Return [(name, body), ...] split on '## <Name>' headings."""
    parts, cur, name = [], [], None
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            if name is not None:
                parts.append((name, "\n".join(cur)))
            name, cur = m.group(1), []
        else:
            cur.append(line)
    if name is not None:
        parts.append((name, "\n".join(cur)))
    return parts


def lint(text):
    """Return (errors, warns) lists of message strings for one document."""
    sections = split_sections(text)
    errors, warns = [], []

    # Doc-level banned constructions: target 0; >1 is a hard failure.
    for label, rx in [("the shape of", SHAPE_RE), ("with-the-X-of-a-man-who", PORTRAIT_RE)]:
        hits = rx.findall(text)
        if hits:
            bucket = errors if len(hits) > 1 else warns
            bucket.append(f"[{label}] {len(hits)} occurrence(s) doc-wide — target 0")

    # First-person filing-as-cognition convergence across POVs.
    filing_sections = [n for n, b in sections if FP_FILE_RE.search(b)]
    if len(filing_sections) > 2:
        errors.append(
            f'[convergence] first-person "I file/filed" in {len(filing_sections)} sections '
            f'({", ".join(filing_sections)}) — cap is 2'
        )
    for name, body in sections:
        n = len(FP_FILE_RE.findall(body))
        if not n:
            continue
        if name.lower().startswith(UNLICENSED_FILERS):
            errors.append(
                f'[cross-pollination] {name} uses first-person "I filed" {n}x — '
                f"filing is a Daz/Grygum register; {name} clocks/notes/watches, never files"
            )
        elif n > 1:
            warns.append(
                f'[density] {name}: "I filed" {n}x in one section — '
                f"rotate the verb (audited / tallied / noted), don't repeat the same metaphor"
            )

    return errors, warns


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="narration .md file(s) to lint")
    ap.add_argument("--quiet", action="store_true", help="print errors only, suppress warnings")
    args = ap.parse_args()

    total_errors = 0
    for p in args.paths:
        path = Path(p)
        if not path.is_file():
            print(f"skip   {p} (not a file)")
            continue
        errors, warns = lint(path.read_text())
        if errors or (warns and not args.quiet):
            print(f"== {p} ==")
        for e in errors:
            print("ERROR ", e)
        if not args.quiet:
            for w in warns:
                print("warn  ", w)
        total_errors += len(errors)
        if errors or (warns and not args.quiet):
            print(f"  {len(errors)} error(s), {len(warns)} warning(s)\n")

    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
