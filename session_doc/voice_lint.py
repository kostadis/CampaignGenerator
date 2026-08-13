#!/usr/bin/env python3
"""Flag portable narration tics in an assembled per-POV narration document.

A mechanical backstop for the voice-critic pass. Splits a narration doc into
its ``## <Character> — <Scene>`` sections and checks for the cross-narrator tics
that the genre prompt bans but the model still emits:

- "the shape of X"            — gesturing at a pattern instead of naming it
- "with the <quality> of a man who ..."  — portable relative-clause portraits
- "the way <class> do/say ... when ..."  — the same behavioral-taxonomy move after it
  rotated out of the relative-clause shell (#251)
- bookkeeping-verb convergence — "file/filed" leaking across POVs that the campaign's
  rulebook does not license for it

The first three are banned for every campaign by ``base.md``'s HARD BANS, so they run
unconditionally. **Bookkeeping rules are per-campaign and are read from the campaign's
own rulebook** — the ``paths.genre_file`` document, which #276 made the single source of
truth. They used to be module constants naming out-of-the-abyss' four narrators, which
meant the check was silently inert on every other campaign while still reporting a clean
run (kostadis/mytools#125, F4).

Without ``--genre-file``, or with a rulebook that declares no bookkeeping block, the
filing checks are **skipped and reported as skipped**. A campaign whose rulebook says
nothing about bookkeeping registers has no such rule to enforce, and inventing one — or
reporting "clean" for a check that never ran — is the failure this replaced.

The block is fenced YAML inside the rulebook, so the prose statement of the rule and the
machine-readable form live in one file that the render pipeline already reads:

    ```yaml voice_lint
    bookkeeping:
      licensed:          [grygum, daz]   # filing is canonical for these POVs
      unlicensed:        [thorin, zalthir]
      per_section_cap:   1
      doc_sections_cap:  2
    portable_tics:
      the_shape_of:               1      # max tolerated doc-wide; target is 0
      with_the_x_of_a_man_who:    1
      the_way_x_do_when:          1
    ```

No model calls, no network — pure stdlib plus PyYAML, cheap to run in a loop.

Exit code is 1 if any hard ERROR fired (so it can gate a pipeline), else 0.

Usage:
    voice_lint path/to/gm-assist-doc.md
    voice_lint summaries/20260601/*.md --genre-file ~/src/campaigns/<name>/voice/_genre.md
    voice_lint narration.md --quiet      # errors only, no warnings
"""

import argparse
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SECTION_RE = re.compile(r"^##\s+(\w+)", re.M)  # "## Daz — ..." -> "Daz"
SHAPE_RE = re.compile(r"\bthe shape of\b", re.I)
PORTRAIT_RE = re.compile(
    r"\bwith the [^.,;]*? of (?:a |an |the )?"
    r"(?:man|woman|men|someone|creature|people|person)s?\b[^.]*?\bwho\b",
    re.I,
)
# Same banned move as PORTRAIT_RE, different shell. The #245 benchmark found the taxonomy
# tic surviving the #246 ban by rotating into "the way men say it when ...", which
# PORTRAIT_RE cannot see. The trailing alternation is load-bearing: requiring `when` alone
# misses "the way they say things at that age" (one of the three confirmed instances), and
# requiring nothing over-fires on legitimate specifics ("I liked the way she said my name",
# "the way Brewbarry does" — a named individual is not a class).
TAXONOMY_RE = re.compile(
    r"\b(?:in )?the way (?:he|she|they|men|women|people|\w+)\s+"
    r"(?:do|does|say|says|said|get|gets)\b.{0,40}?"
    r"(?:\bwhen\b|\bat (?:that|his|her|their) age\b)",
    re.I,
)
# The tic is FIRST-PERSON filing-as-cognition ("I file/filed ..."). Literal third-person
# usage ("the scholars file a grievance") is not the tic and must not trip the check.
FP_FILE_RE = re.compile(r"\bI fil(?:e|ed)\b", re.I)

# Fenced ```yaml voice_lint block inside the campaign's rulebook. Leading whitespace is
# tolerated because the block belongs beside the prose rule it encodes, which in a
# hand-authored rulebook usually means indented under a list item.
GENRE_BLOCK_RE = re.compile(
    r"^[ \t]*```yaml[ \t]+voice_lint[ \t]*\n(.*?)^[ \t]*```[ \t]*$", re.M | re.S)

PORTABLE_TICS = (
    ("the shape of", "the_shape_of", SHAPE_RE),
    ("with-the-X-of-a-man-who", "with_the_x_of_a_man_who", PORTRAIT_RE),
    ("the-way-X-do-when", "the_way_x_do_when", TAXONOMY_RE),
)
# Max tolerated doc-wide. 1 reproduces the pre-#125 behaviour exactly: a lone occurrence
# warns (the target is 0), a second one is a hard error.
DEFAULT_TIC_CAP = 1

_BOOKKEEPING_KEYS = {"licensed", "unlicensed", "per_section_cap", "doc_sections_cap"}


@dataclass(frozen=True)
class Bookkeeping:
    """Per-campaign filing-register rules, as declared by its rulebook."""

    licensed: tuple[str, ...] = ()
    unlicensed: tuple[str, ...] = ()
    per_section_cap: int = 1
    doc_sections_cap: int = 2


@dataclass(frozen=True)
class LintConfig:
    """What the campaign's rulebook says. ``bookkeeping is None`` means it says nothing."""

    source: str | None = None
    bookkeeping: Bookkeeping | None = None
    tic_caps: dict[str, int] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    def cap_for(self, key: str) -> int:
        return self.tic_caps.get(key, DEFAULT_TIC_CAP)


def extract_block(genre_text: str) -> str | None:
    """Return the body of the rulebook's ```yaml voice_lint fence, dedented, if it has one."""
    m = GENRE_BLOCK_RE.search(genre_text)
    return textwrap.dedent(m.group(1)) if m else None


def parse_config(genre_text: str, source: str | None = None) -> LintConfig:
    """Parse a rulebook's voice_lint block. Malformed input degrades to 'says nothing'.

    A rulebook is hand-authored campaign content, so a typo here must not crash a lint
    run or, worse, silently fall back to another campaign's rules. Every problem is
    collected and reported alongside the findings.
    """
    body = extract_block(genre_text)
    if body is None:
        return LintConfig(source=source)

    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError as exc:
        return LintConfig(source=source, problems=(f"voice_lint block is not valid YAML: {exc}",))
    if data is None:
        return LintConfig(source=source, problems=("voice_lint block is empty",))
    if not isinstance(data, dict):
        return LintConfig(source=source,
                          problems=(f"voice_lint block must be a mapping, got {type(data).__name__}",))

    problems: list[str] = []
    for key in data:
        if key not in ("bookkeeping", "portable_tics"):
            problems.append(f"unrecognised voice_lint key {key!r} — ignored")

    bookkeeping = None
    raw_bk = data.get("bookkeeping")
    if raw_bk is not None:
        if not isinstance(raw_bk, dict):
            problems.append("bookkeeping: must be a mapping — filing checks skipped")
        else:
            for key in raw_bk:
                if key not in _BOOKKEEPING_KEYS:
                    problems.append(f"unrecognised bookkeeping key {key!r} — ignored")
            bookkeeping = Bookkeeping(
                licensed=_name_tuple(raw_bk.get("licensed"), "licensed", problems),
                unlicensed=_name_tuple(raw_bk.get("unlicensed"), "unlicensed", problems),
                per_section_cap=_positive_int(raw_bk.get("per_section_cap"), "per_section_cap", 1, problems),
                doc_sections_cap=_positive_int(raw_bk.get("doc_sections_cap"), "doc_sections_cap", 2, problems),
            )

    tic_caps: dict[str, int] = {}
    raw_tics = data.get("portable_tics")
    if raw_tics is not None:
        if not isinstance(raw_tics, dict):
            problems.append("portable_tics: must be a mapping — defaults used")
        else:
            known = {key for _, key, _ in PORTABLE_TICS}
            for key, value in raw_tics.items():
                if key not in known:
                    problems.append(f"unrecognised portable_tics key {key!r} — ignored")
                    continue
                tic_caps[key] = _positive_int(value, key, DEFAULT_TIC_CAP, problems, allow_zero=True)

    return LintConfig(source=source, bookkeeping=bookkeeping, tic_caps=tic_caps,
                      problems=tuple(problems))


def load_config(genre_file: str | Path | None) -> LintConfig:
    """Read a rulebook from disk. A missing path is 'says nothing', reported as such."""
    if not genre_file:
        return LintConfig()
    path = Path(genre_file)
    if not path.is_file():
        return LintConfig(source=str(path),
                          problems=(f"--genre-file {path} does not exist",))
    return parse_config(path.read_text(), source=str(path))


def _name_tuple(value, label: str, problems: list[str]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"bookkeeping.{label}: expected a list of narrator names — ignored")
        return ()
    return tuple(v.strip().lower() for v in value if v.strip())


def _positive_int(value, label: str, default: int, problems: list[str], allow_zero: bool = False) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < (0 if allow_zero else 1):
        problems.append(f"{label}: expected a{'' if allow_zero else ' positive'} integer, "
                        f"got {value!r} — using {default}")
        return default
    return value


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


def lint(text, config: LintConfig | None = None):
    """Return (errors, warns, notes) message lists for one document.

    ``notes`` carries what was *not* checked and why. It is separate from ``warns`` on
    purpose: a skipped check is not a clean check, and folding the two together is how the
    OOTA-only filing rules read as passing on three other campaigns for months.
    """
    config = config or LintConfig()
    sections = split_sections(text)
    errors, warns, notes = [], [], []

    notes.extend(f"[config] {p}" for p in config.problems)

    # Doc-level banned constructions. base.md bans these for every campaign, so they run
    # whether or not a rulebook was supplied; only the cap is campaign-tunable.
    for label, key, rx in PORTABLE_TICS:
        hits = rx.findall(text)
        if not hits:
            continue
        cap = config.cap_for(key)
        bucket = errors if len(hits) > cap else warns
        bucket.append(f"[{label}] {len(hits)} occurrence(s) doc-wide — target 0, cap {cap}")

    if config.bookkeeping is None:
        where = config.source or "no --genre-file given"
        notes.append(
            f"[skipped] bookkeeping/filing checks — this campaign's rulebook declares no "
            f"voice_lint bookkeeping block ({where}). Not the same as clean: nothing was checked."
        )
        return errors, warns, notes

    bk = config.bookkeeping
    filing_sections = [n for n, b in sections if FP_FILE_RE.search(b)]
    if len(filing_sections) > bk.doc_sections_cap:
        errors.append(
            f'[convergence] first-person "I file/filed" in {len(filing_sections)} sections '
            f'({", ".join(filing_sections)}) — cap is {bk.doc_sections_cap}'
        )
    for name, body in sections:
        n = len(FP_FILE_RE.findall(body))
        if not n:
            continue
        if name.lower().startswith(bk.unlicensed):
            licensed = "/".join(v.title() for v in bk.licensed) or "no one's"
            errors.append(
                f'[cross-pollination] {name} uses first-person "I filed" {n}x — '
                f"filing is a {licensed} register; {name}'s rulebook entry does not license it"
            )
        elif n > bk.per_section_cap:
            warns.append(
                f'[density] {name}: "I filed" {n}x in one section — cap is '
                f"{bk.per_section_cap}; rotate the verb (audited / tallied / noted), "
                f"don't repeat the same metaphor"
            )

    return errors, warns, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="narration .md file(s) to lint")
    ap.add_argument("--genre-file", default=None, metavar="PATH",
                    help="the campaign's rulebook (paths.genre_file, conventionally "
                         "voice/_genre.md). Supplies the bookkeeping rules; without it "
                         "those checks are skipped, not passed.")
    ap.add_argument("--quiet", action="store_true", help="print errors only, suppress warnings")
    args = ap.parse_args()

    config = load_config(args.genre_file)

    total_errors = 0
    for p in args.paths:
        path = Path(p)
        if not path.is_file():
            print(f"skip   {p} (not a file)")
            continue
        errors, warns, notes = lint(path.read_text(), config)
        if errors or notes or (warns and not args.quiet):
            print(f"== {p} ==")
        for e in errors:
            print("ERROR ", e)
        if not args.quiet:
            for w in warns:
                print("warn  ", w)
        for n in notes:
            print("note  ", n)
        total_errors += len(errors)
        if errors or notes or (warns and not args.quiet):
            print(f"  {len(errors)} error(s), {len(warns)} warning(s), {len(notes)} note(s)\n")

    sys.exit(1 if total_errors else 0)


if __name__ == "__main__":
    main()
