#!/usr/bin/env python3
"""Normalize ambiguous scene headings in a campaign's master narrative bible.

Some bible chapters use a bare `##`-level heading for two different purposes
within the same chapter: a date boundary (`## 9th day of the 2nd Tenday of
Taraskh 1493`) AND, elsewhere in the same chapter, a bare narrator heading
(`## Zalthir`) — both at the same heading level. Any fixed heading-level
heuristic (including ensemble_extract.py's chunk annotation) can't tell these
apart, and a chunk boundary landing right after one of the bare-name headings
loses the "this is a speaker" signal entirely.

This script finds every bare `##`-level heading in the bible whose text
resolves to a known character name — via the campaign's
`docs/entity_registry.yaml` and, optionally, `config/party.yaml` for PCs the
registry doesn't track — and demotes that single line from `##` to `###`,
matching the speaker convention already used elsewhere in the same document
(`## <date>` / `### <Name>`). Every `##` line that does NOT resolve to a known
name (dates, recap section titles, the current `## Name — Scene` format) is
left untouched.

Mechanical only — no LLM calls, no content changes, heading level only. The
name-resolution rule is chapter-agnostic: it doesn't hardcode which chapters
are affected, so it also catches this mixing pattern in chapters written in
the future, not just the ones already known to have it.

Usage:
  python normalize_bible_headings.py docs/TheUnderdark.md --dry-run
  python normalize_bible_headings.py docs/TheUnderdark.md
  python normalize_bible_headings.py docs/TheUnderdark.md --registry docs/entity_registry.yaml --party config/party.yaml
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

from campaignlib.registry import find_registry, load_registry
from campaignlib.textproc import norm_subject
from split_chapters import CHAPTER_RE_TEMPLATE

_H2_RE = re.compile(r'^##(?!#)\s+(.+)$', re.MULTILINE)
_DEFAULT_PREFIX = "# Chapter "


def load_known_names(bible_path: Path, registry_arg: str | None, party_arg: str | None) -> set[str]:
    """Union of registry entity/alias names and party.yaml PC names, normalized."""
    campaign_dir = bible_path.resolve().parent.parent  # <campaign>/docs/Bible.md -> <campaign>
    known: set[str] = set()

    registry_path = Path(registry_arg).expanduser() if registry_arg else find_registry(campaign_dir)
    if registry_path and registry_path.is_file():
        reg = load_registry(registry_path)
        known |= reg.known_names()
        print(f"[registry] {len(reg.entities)} entities loaded from {registry_path}")
    else:
        print("[registry] none found — names will only come from --party, if given", file=sys.stderr)

    party_path = Path(party_arg).expanduser() if party_arg else (campaign_dir / "config" / "party.yaml")
    if party_path.is_file():
        data = yaml.safe_load(party_path.read_text(encoding="utf-8")) or {}
        names = [c["name"] for c in data.get("characters", []) if c.get("name")]
        for n in names:
            known.add(norm_subject(n))
        print(f"[party] {len(names)} character(s) loaded from {party_path}")

    return known


def find_demotions(text: str, known_names: set[str], prefix: str = _DEFAULT_PREFIX) -> list[tuple[int, int, str]]:
    """Return [(start, end, name), ...] spans of bare `##` lines to demote to `###`.

    Only lines whose full heading text resolves to a known name are demoted.
    An em-dash `## Name — Scene` line never matches here (the full text
    normalizes to something like "namescenetitle", not a bare registry key),
    so the current chapter format is never touched.
    """
    chapter_pattern = re.compile(CHAPTER_RE_TEMPLATE.format(prefix=re.escape(prefix)))
    chapter_bounds = [m.start() for m in chapter_pattern.finditer(text)] + [len(text)]

    demotions: list[tuple[int, int, str]] = []
    for i in range(len(chapter_bounds) - 1):
        start, end = chapter_bounds[i], chapter_bounds[i + 1]
        for m in _H2_RE.finditer(text, start, end):
            name = m.group(1).strip()
            if norm_subject(name) in known_names:
                demotions.append((m.start(), m.start() + 2, name))  # the "##" span only
    return demotions


def apply_demotions(text: str, demotions: list[tuple[int, int, str]]) -> str:
    """Insert one '#' at each demotion span, from the end so offsets stay valid."""
    out = text
    for start, end, _name in sorted(demotions, reverse=True):
        out = out[:start] + "#" + out[start:]
    return out


def line_number(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("bible", type=Path, help="Path to the master bible markdown file")
    parser.add_argument("--registry", metavar="PATH", default=None,
                        help="Path to entity_registry.yaml (default: auto-discover "
                             "<campaign-dir>/docs/entity_registry.yaml)")
    parser.add_argument("--party", metavar="PATH", default=None,
                        help="Path to party.yaml for PC names not in the registry "
                             "(default: <campaign-dir>/config/party.yaml if present)")
    parser.add_argument("--prefix", default=_DEFAULT_PREFIX,
                        help="Chapter heading prefix (default: '# Chapter ')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing to disk")
    args = parser.parse_args()

    if not args.bible.is_file():
        print(f"error: bible file not found: {args.bible}", file=sys.stderr)
        return 1

    text = args.bible.read_text(encoding="utf-8")
    known_names = load_known_names(args.bible, args.registry, args.party)
    if not known_names:
        print("error: no known names loaded (no registry, no party.yaml found); "
              "nothing to check against", file=sys.stderr)
        return 1

    demotions = find_demotions(text, known_names, args.prefix)

    if not demotions:
        print("\nNo ambiguous headings found — nothing to change.")
        return 0

    print(f"\n{len(demotions)} heading(s) to demote from ## to ###:\n")
    for start, _end, name in sorted(demotions):
        print(f"  line {line_number(text, start):>6}:  ## {name}  ->  ### {name}")

    if args.dry_run:
        print(f"\n[dry-run] {len(demotions)} change(s) would be written to {args.bible}")
        return 0

    new_text = apply_demotions(text, demotions)
    if new_text == text:
        print("\nNo changes needed — file unchanged.")
        return 0

    args.bible.write_text(new_text, encoding="utf-8")
    print(f"\nWrote {len(demotions)} change(s) to {args.bible}")
    print("Re-run split_chapters.py to regenerate docs/chapters/ from the updated bible.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
