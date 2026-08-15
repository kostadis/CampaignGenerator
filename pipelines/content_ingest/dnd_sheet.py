#!/usr/bin/env python3
"""Convert a D&D Beyond character sheet PDF into a structured markdown document.

Extracts text via PyMuPDF (no vision required) and sends it to Claude as a
plain-text prompt. Works with the claude-code (subscription) backend.

With ``--party-config`` the campaign's roster decides where the sheet goes and
who plays the character (feature 008): the ``# `` title of the converted sheet
is matched to a roster entry, the file is written to
``<roster sheet dir>/<char-name>.md``, whatever sheet was already there is
archived under ``old/level/<N>/`` keyed by *its* level, and the roster's
``player`` replaces the exported one — a D&D Beyond download stamps the
downloader's name into every sheet it produces.

Attribution is exact (case-insensitive, trimmed) with **no fuzzy fallback**;
every disagreement is a refusal that names the fix and touches nothing. That is
free because the API call completes before the first filesystem mutation, which
is also why no rollback path exists — see ``contracts/cli-dnd-sheet.md`` in
``specs/008-sheet-naming-archival/`` for every message this prints verbatim.

Usage:
  dnd_sheet Soma.pdf --party-config config/party.yaml   # roster mode
  dnd_sheet Soma.pdf --output soma.md                   # legacy: explicit path
  dnd_sheet Soma.pdf                                    # legacy: writes to doc/
  dnd_sheet *.pdf --output-dir ~/campaigns/Phandalin/characters/
"""

import argparse
import sys
from pathlib import Path

import fitz  # pymupdf

from campaignlib import add_backend_args, call_api, client_from_args, run_single_batch, DEFAULT_MODEL
from campaignlib.party_config import (
    PartyCharacter,
    load_party_config,
    load_party_config_arg,
)
from campaignlib.sheet_identity import read_player, sheet_name
from campaignlib.sheet_naming import (
    ArchiveSlotOccupied,
    AttributionError,
    DisplacedLevelUnreadable,
    RosterDirectoryMissing,
    RosterFilenameMismatch,
    SheetNamingError,
    apply_roster_player,
    attribute,
    check_destination,
    plan_archive,
)

#: FR-017 — an explicit output location wins, and the run has to say that the
#: roster's naming and archival were therefore not applied.
SKIPPED_FOR_EXPLICIT_OUTPUT = (
    "Note: an explicit output location was given, so roster naming and archival "
    "were skipped. Drop --output/--output-dir to let the roster name the file."
)

#: FR-018 — legacy behaviour is still legacy behaviour, but it no longer looks
#: like roster mode silently doing nothing.
NO_ROSTER_NOTICE = (
    "Note: no usable party roster, so roster naming and archival were not applied "
    "— each sheet is named from its source PDF, as before. Pass --party-config "
    "config/party.yaml to name sheets from the roster."
)

SYSTEM_PROMPT = """\
You are converting a D&D Beyond character sheet PDF into a clean markdown document \
for use as a campaign reference.

Extract ALL information visible on the sheet and structure it as follows.

First, a YAML frontmatter block — a machine-readable summary of the same
Identity fields that follow, so downstream tooling can read the roster
without re-parsing prose (issue #265). Emit EXACTLY these five keys, in
this order, with no others:

---
name: [Character Name]
player: [Player Name]
species: [Species]
class_level: [Class & Level, e.g. "Monk 8" — one string, do not split into
  separate class/level/subclass fields]
subclass: [Subclass, e.g. "Warrior of Shadow" — leave EMPTY (subclass: "")
  if the sheet does not state one; never guess]
---

Then the markdown document itself:

# [Character Name]

## Identity
- **Class & Level:**
- **Subclass:**
- **Species:**
- **Background:**
- **Player:**
- **Alignment:**
- **Age / Gender / Size:**

## Ability Scores
| Ability | Score | Modifier |
|---|---|---|
| Strength | | |
| Dexterity | | |
| Constitution | | |
| Intelligence | | |
| Wisdom | | |
| Charisma | | |

## Combat
- **HP:** (max / current)
- **AC:**
- **Initiative:**
- **Speed:**
- **Hit Dice:**
- **Proficiency Bonus:**

## Saving Throws
List each with modifier and whether proficient.

## Skills
List each skill with modifier and proficiency status.

## Proficiencies & Languages
List armor, weapons, tools, and languages.

## Attacks & Cantrips
| Name | Hit | Damage | Notes |
|---|---|---|---|

## Features & Traits
List all class features, racial traits, and background features with their descriptions.

## Feats
List each feat with its description.

## Equipment
List all items carried.

## Spells
If applicable, list spell slots and known/prepared spells by level.

## Personality
- **Traits:**
- **Ideals:**
- **Bonds:**
- **Flaws:**

## Notes
Any additional information from the sheet.

Rules:
- Include every piece of information visible on the sheet.
- Preserve modifier signs (e.g. +4, -1).
- For features and traits, include the full description text, not just the name.
- If a field is blank on the sheet, omit it from the body. The frontmatter
  block is the one exception: always emit all five of its keys, even when a
  value is empty (e.g. `subclass: ""`) — omitting a frontmatter key breaks
  the downstream parser, which expects all five every time.
- Output only the frontmatter block followed by the markdown document. No
  preamble or commentary.
"""


def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


def pdf_to_markdown(client, pdf_path: Path, model: str, batch: bool = False) -> str:
    text = extract_text(pdf_path)
    user_prompt = (
        "Please convert this D&D Beyond character sheet into the structured "
        f"markdown format.\n\n{text}"
    )
    # user_prompt is a plain string today (PyMuPDF text extraction — the module
    # docstring's "no vision required"); it is passed through as-is to whichever
    # call path is used so a future multimodal/vision payload (a content-block
    # list) would flow identically without touching this function.
    if batch:
        try:
            return run_single_batch(client, system=SYSTEM_PROMPT, user=user_prompt,
                                    model=model, max_tokens=8096)
        except RuntimeError as e:
            print(f"Error: batch item failed: {e}", file=sys.stderr)
            sys.exit(1)
    return call_api(client, SYSTEM_PROMPT, user_prompt, model)


def refusal(pdf_name: str, error: SheetNamingError, party_config_arg: str) -> str:
    """The stderr block for one refused PDF (contracts/cli-dnd-sheet.md).

    Every one names the file, shows the values that disagree, says which file
    to fix, and ends by stating that nothing was touched — because nothing was:
    the API call runs before the first filesystem mutation (D7), so every
    refusal below costs tokens and changes no bytes.
    """
    head = f"REFUSED {pdf_name}: "
    tail = "  Nothing was written or moved."

    if isinstance(error, AttributionError):
        if error.matches > 1:
            return (
                f'{head}"{error.extracted_name}" matches {error.matches} roster '
                f"entries. Names must be unique.\n{tail}"
            )
        if not error.extracted_name:
            return (
                f"{head}the converted sheet has no '# ' title, so there is no "
                f"name to attribute.\n"
                f"  Roster has:      {', '.join(error.roster_names) or '(empty)'}\n"
                f"{tail}"
            )
        return (
            f"{head}the name on this sheet is not in the roster.\n"
            f'  Sheet says:      "{error.extracted_name}"\n'
            f"  Roster has:      {', '.join(error.roster_names) or '(empty)'}\n"
            f"  The roster and the sheet disagree. Fix {party_config_arg} (or the\n"
            f"  sheet's own title) so one of them matches exactly — there is no fuzzy\n"
            f"  matching here on purpose.\n"
            f"{tail}"
        )

    if isinstance(error, RosterFilenameMismatch):
        return (
            f"{head}the roster points at a filename this conversion would not write.\n"
            f"  party.yaml says: sheet: {error.declared}\n"
            f"  would write:     {error.replacement}\n"
            f"  Fix the roster entry for {error.character_name} to:\n"
            f"      sheet: {error.replacement}\n"
            f"  If a sheet already exists at the old name, RENAME IT TOO —\n"
            f"      git mv {error.declared} {error.replacement}\n"
            f"  — or the next run will see no sheet to displace, archive nothing,\n"
            f"  and leave the old file orphaned beside the new one.\n"
            f"{tail}"
        )

    if isinstance(error, RosterDirectoryMissing):
        return (
            f"{head}the directory the roster declares for this sheet does not exist.\n"
            f"  party.yaml says: sheet: {error.declared}\n"
            f"  which resolves to: {error.directory}\n"
            f"  Relative roster paths resolve against the current directory, so either\n"
            f"  run this from the directory {party_config_arg}'s paths are written\n"
            f"  against, or fix the entry for {error.character_name}. This will not\n"
            f"  create the directory: writing a character sheet into a tree nobody\n"
            f"  meant to exist is worse than stopping.\n"
            f"{tail}"
        )

    if isinstance(error, DisplacedLevelUnreadable):
        if error.phrase is None:
            return (
                f"{head}cannot read a level from the sheet being replaced.\n"
                f'  {error.sheet} has no "Class & Level" in its ## Identity block\n'
                f"  and no class_level frontmatter.\n"
                f"{tail}"
            )
        return (
            f"{head}cannot read a single level from the sheet being replaced.\n"
            f'  {error.sheet} says: "{error.phrase}"\n'
            f"  The archive is keyed by one level and this sheet records more than\n"
            f"  one class. Move it by hand, or record a single class & level.\n"
            f"{tail}"
        )

    if isinstance(error, ArchiveSlotOccupied):
        return (
            f"{head}{error.path} already exists.\n"
            f"  A level-{error.level} sheet is already archived; overwriting it is the\n"
            f"  one thing this archive exists to prevent.\n"
            f"{tail}"
        )

    return f"{head}{error}\n{tail}"


def load_roster(path_str: str | None) -> list[PartyCharacter] | None:
    """The campaign's roster entries as the GM authored them, or ``None``.

    ``load_party_config_arg`` owns the soft-fail contract every ``--party-config``
    CLI shares — a missing or malformed file prints and degrades to ``None``
    rather than raising — so it is the gate. Its result is a *resolved* config,
    though, and the refusals here have to print a ``sheet:`` line the GM can
    paste straight back into ``party.yaml``; an absolute resolved path would
    make their roster machine-specific, which is exactly what the
    authored-vs-resolved split in ``campaignlib/party_config.py`` exists to
    prevent. So the authored copy is read alongside it.
    """
    if not path_str:
        return None
    if load_party_config_arg(path_str, Path.cwd()) is None:
        return None
    return load_party_config(Path(path_str).expanduser()).characters


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a D&D Beyond character sheet PDF to markdown."
    )
    parser.add_argument("pdfs", nargs="+", metavar="PDF",
                        help="PDF file(s) to convert")
    parser.add_argument("--party-config", metavar="PATH", default=None,
                        help="The campaign's config/party.yaml. Giving it turns on "
                             "roster mode: each sheet is attributed to a roster "
                             "entry by the character name on the sheet, written to "
                             "<roster sheet dir>/<char-name>.md, any sheet already "
                             "there is archived under old/level/<N>/, and the "
                             "roster's player value replaces the one in the export "
                             "(a D&D Beyond download stamps the downloader's name). "
                             "That player value must be the player's ZOOM DISPLAY "
                             "NAME — speaker attribution downstream matches VTT "
                             "prefixes exactly, and a near-miss silently drops that "
                             "character's lines. Relative paths in the roster "
                             "resolve against the current directory.")
    parser.add_argument("--output", "-o", metavar="FILE",
                        help="Output file (single PDF only). Overrides --output-dir. "
                             "Suppresses roster naming and archival.")
    parser.add_argument("--output-dir", metavar="DIR", default=None,
                        help="Output directory (default: doc). One .md per PDF. "
                             "Suppresses roster naming and archival.")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Claude model to use")
    add_backend_args(parser)
    args = parser.parse_args()

    # Mode selection (contracts/cli-dnd-sheet.md). --output-dir's default is
    # None rather than "doc" precisely so "unset" is distinguishable from
    # "explicitly doc" — without that the web UI, which always had an output
    # field, could never reach roster mode (D11).
    explicit_output = bool((args.output or "").strip()) or bool((args.output_dir or "").strip())
    roster: list[PartyCharacter] | None = None
    if args.party_config and explicit_output:
        print(SKIPPED_FOR_EXPLICIT_OUTPUT, file=sys.stderr)
    else:
        roster = load_roster(args.party_config)
        if roster is None:
            print(NO_ROSTER_NOTICE, file=sys.stderr)

    client = client_from_args(args)
    base = Path.cwd()
    refused = False

    for pdf_path_str in args.pdfs:
        pdf_path = Path(pdf_path_str).expanduser().resolve()
        if not pdf_path.exists():
            # Per-PDF, like every refusal below: one unreadable file does not
            # cancel the conversions that would have succeeded (FR-004).
            print(f"Error: file not found: {pdf_path}", file=sys.stderr)
            refused = True
            continue

        print(f"Converting {pdf_path.name}...", file=sys.stderr)
        # The API call comes before the first filesystem mutation, which is what
        # makes every refusal below free (D7, FR-015).
        #
        # Stripped HERE, not at the write. Everything downstream that reads the
        # frontmatter — `read_player`, `read_class_level`, the substitution in
        # `apply_roster_player` — anchors its match at \A, so one stray leading
        # newline from the model would silently skip the machine channel while
        # still rewriting the prose one. The sheet would then name the roster's
        # player in ## Identity and the downloader in frontmatter, and
        # `player_map_from_config` reads frontmatter.
        markdown = pdf_to_markdown(client, pdf_path, args.model, batch=args.batch).strip()

        if roster is not None:
            # Everything that can refuse is decided here, before the first byte
            # moves: attribution, the destination, the level of the sheet being
            # displaced, and whether its archive slot is free.
            try:
                character = attribute(sheet_name(markdown), roster)
                out = check_destination(character, base)
                plan = plan_archive(out, character.name)
            except SheetNamingError as e:
                print(refusal(pdf_path.name, e, args.party_config), file=sys.stderr)
                refused = True
                continue

            print(f"Matched roster entry: {character.name}", file=sys.stderr)

            downloaded = read_player(markdown)
            markdown = apply_roster_player(markdown, character.player)
            if character.player and character.player.strip():
                print(
                    f"Player: {downloaded or '(none)'} -> {character.player.strip()}"
                    f"  (from party.yaml)",
                    file=sys.stderr,
                )
            else:
                print(
                    "Player: none recorded in party.yaml — left empty (the "
                    "downloaded value names the downloader, not the player)",
                    file=sys.stderr,
                )

            if plan is not None:
                plan.destination.parent.mkdir(parents=True, exist_ok=True)
                plan.source.replace(plan.destination)
                print(
                    f"Archived: {plan.source} -> {plan.destination}  "
                    f"(level {plan.level})",
                    file=sys.stderr,
                )
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
        elif args.output and len(args.pdfs) == 1:
            out = Path(args.output).expanduser()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
        else:
            out_dir = Path(args.output_dir or "doc").expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / (pdf_path.stem + ".md")
            out.write_text(markdown.strip() + "\n", encoding="utf-8")
        print(f"Saved to: {out}", file=sys.stderr)

    if refused:
        sys.exit(1)


if __name__ == "__main__":
    main()
