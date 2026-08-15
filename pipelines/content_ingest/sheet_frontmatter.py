#!/usr/bin/env python3
"""Deterministic, zero-token importer: propose YAML frontmatter for an
EXISTING D&D Beyond character sheet ``.md`` file, parsed from its
``## Identity`` block (issue #265; ``docs/design/PartyRosterCanonicalFormat.md``,
"Approach" step 5).

Every sheet in every campaign predates ``dnd_sheet.py`` emitting frontmatter
directly (measured 2026-08-10: 0 of 15 existing sheets have it). This CLI is
the migration ramp for those files: it parses the ``## Identity`` block
``dnd_sheet.py`` has always produced, proposes the same five frontmatter
keys ``dnd_sheet.py`` now emits going forward (``name``, ``player``,
``species``, ``class_level``, ``subclass``), and writes NOTHING unless told
to.

No API call, no model, no re-extraction — a regex pass over text already on
disk. See ``tests/test_retrieve_render_isolation.py`` and
``tests/test_layering.py``, which this module must not violate.

``subclass`` is never recoverable from an existing sheet body — it lives in
D&D Beyond's own passthrough layout, rendered differently per character (see
the design doc's fact 3) — so it is always proposed empty, and every
processed sheet is reported as needing it filled in by hand (or via a fresh
``dnd_sheet`` run against the source PDF).

**Never auto-resolves a conflict.** With ``--party PATH``, each sheet's
proposed fields are cross-checked against that character's ``party.md``
entry. A disagreement is reported with BOTH values shown — never preferred
either way — because a mismatch can mean the sheet is stale (the GM leveled
up on paper and hasn't re-exported) as easily as it can mean ``party.md`` is
wrong. Which side is right is a scope decision, and scope decisions get a
human (see the GM ruling in the design doc, and the toee case where the
sheet's ``Player:`` field is a D&D Beyond account handle, not the person).

Usage::

    sheet_frontmatter docs/zalthir.md docs/soma.md            # propose only
    sheet_frontmatter docs/zalthir.md --apply                  # write it
    sheet_frontmatter docs/zalthir.md --apply --force           # overwrite existing frontmatter
    sheet_frontmatter docs/zalthir.md --party docs/party.md     # + conflict report

Template for the CLI shape (refuse-to-clobber-without-``--force``, report
unrecognised keys rather than dropping them): ``server/migrate_session_doc.py``.
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from campaignlib.party_md import PartyEntry, parse_party_md
# The '## Identity' parser moved down to campaignlib for feature 008, which
# reads the class & level off a sheet it is about to archive. Re-exported
# here so this module's public surface is unchanged (D3).
from campaignlib.sheet_identity import (  # noqa: F401
    SheetParseError,
    parse_identity_fields,
    sheet_name,
)
from campaignlib.textproc import split_frontmatter
from campaignlib.util import atomic_write_text

#: The five frontmatter keys dnd_sheet.py's SYSTEM_PROMPT now specifies
#: (issue #265, D1(b)), in emission order. subclass is always proposed
#: empty by this importer — see module docstring.
FRONTMATTER_KEYS: tuple[str, ...] = ("name", "player", "species", "class_level", "subclass")


@dataclass
class SheetProposal:
    path: Path
    error: str | None = None
    name: str = ""
    frontmatter: dict[str, str] = field(default_factory=dict)
    unrecognised_keys: list[str] = field(default_factory=list)
    had_existing_frontmatter: bool = False
    conflicts: list[str] = field(default_factory=list)
    party_match: bool = False


def propose(sheet_path: Path, party_entries: dict[str, PartyEntry] | None = None) -> SheetProposal:
    """Parse one sheet and build its frontmatter proposal.

    ``party_entries`` is a ``{lowercased name: PartyEntry}`` map (already
    parsed once by the caller) used for the conflict cross-check; omit or
    pass ``None`` to skip it.
    """
    text = sheet_path.read_text(encoding="utf-8")
    existing_fm, _ = split_frontmatter(text)

    try:
        identity, unrecognised = parse_identity_fields(text)
    except SheetParseError as e:
        return SheetProposal(path=sheet_path, error=str(e))

    name = sheet_name(text) or sheet_path.stem
    frontmatter = {
        "name": name,
        "player": identity.get("player", "").strip(),
        "species": identity.get("species", "").strip(),
        "class_level": identity.get("class & level", "").strip(),
        # Never recoverable from an existing sheet body — see module docstring.
        "subclass": "",
    }

    prop = SheetProposal(
        path=sheet_path,
        name=name,
        frontmatter=frontmatter,
        unrecognised_keys=unrecognised,
        had_existing_frontmatter=bool(existing_fm),
    )

    if party_entries is not None:
        entry = party_entries.get(name.lower())
        if entry is None:
            prop.party_match = False
        else:
            prop.party_match = True
            sheet_player = frontmatter["player"].strip()
            md_player = entry.player.strip()
            if sheet_player != md_player:
                prop.conflicts.append(
                    f"player: sheet={sheet_player!r} vs party.md={md_player!r}"
                )
            sheet_species = frontmatter["species"].strip()
            if sheet_species and sheet_species.lower() not in entry.class_info.lower():
                prop.conflicts.append(
                    f"species: sheet={sheet_species!r} vs party.md class_info={entry.class_info!r}"
                )
            sheet_class_level = frontmatter["class_level"].strip()
            if sheet_class_level and sheet_class_level.lower() not in entry.class_info.lower():
                prop.conflicts.append(
                    f"class_level: sheet={sheet_class_level!r} vs party.md class_info={entry.class_info!r}"
                )

    return prop


def render_report(prop: SheetProposal) -> str:
    """Human-readable proposal block for stdout. Deterministic — no
    timestamps, no unordered-dict iteration — so two dry runs over the same
    input produce byte-identical output."""
    lines = [f"=== {prop.path} ==="]
    if prop.error:
        lines.append(f"REFUSED: {prop.error}")
        return "\n".join(lines) + "\n"

    yaml_block = yaml.safe_dump(
        {k: prop.frontmatter[k] for k in FRONTMATTER_KEYS},
        default_flow_style=False, sort_keys=False, allow_unicode=True,
    )
    lines.append("Proposed frontmatter:")
    lines.append("---")
    lines.append(yaml_block.rstrip("\n"))
    lines.append("---")

    if prop.had_existing_frontmatter:
        lines.append("NOTE: sheet already has frontmatter — --force required to overwrite it.")

    lines.append(
        "Needs manual fill-in: subclass (not recoverable from the sheet body — "
        "see docs/design/PartyRosterCanonicalFormat.md fact 3)"
    )

    if prop.unrecognised_keys:
        lines.append(
            "Unrecognised '## Identity' keys (left as-is, not added to frontmatter): "
            + ", ".join(prop.unrecognised_keys)
        )

    if prop.conflicts:
        lines.append("Conflicts vs party.md (GM ruling needed — sheet value shown first):")
        for c in prop.conflicts:
            lines.append(f"  {c}")
    elif prop.party_match:
        lines.append("No conflicts vs party.md.")

    return "\n".join(lines) + "\n"


def render_file_content(prop: SheetProposal, original_text: str) -> str:
    """The full new file content: frontmatter block + the body (original
    text with any prior frontmatter block stripped)."""
    _existing_fm, body = split_frontmatter(original_text)
    yaml_block = yaml.safe_dump(
        {k: prop.frontmatter[k] for k in FRONTMATTER_KEYS},
        default_flow_style=False, sort_keys=False, allow_unicode=True,
    )
    return f"---\n{yaml_block}---\n{body}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Propose (and optionally write) YAML frontmatter for existing D&D "
            "Beyond character sheets, parsed from their '## Identity' block. "
            "Deterministic, zero-token, no API call."
        ),
    )
    parser.add_argument("sheets", nargs="+", metavar="FILE",
                        help="Character sheet .md file(s) to process.")
    parser.add_argument("--apply", action="store_true",
                        help="Write the proposed frontmatter. Default: propose to "
                             "stdout, write nothing.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing frontmatter. Without this, a sheet "
                             "that already has frontmatter is refused (report only, "
                             "even with --apply).")
    parser.add_argument("--party", metavar="FILE", default=None,
                        help="party.md — cross-check each sheet's proposed fields "
                             "against that character's entry and report (never "
                             "resolve) any disagreement.")
    args = parser.parse_args(argv)

    party_entries: dict[str, PartyEntry] | None = None
    if args.party:
        party_path = Path(args.party).expanduser()
        if not party_path.exists():
            print(f"Error: --party file not found: {party_path}", file=sys.stderr)
            return 1
        party_text = party_path.read_text(encoding="utf-8")
        party_entries = {e.name.lower(): e for e in parse_party_md(party_text)}

    had_error = False
    for sheet_arg in args.sheets:
        sheet_path = Path(sheet_arg).expanduser()
        if not sheet_path.exists():
            print(f"Error: sheet not found: {sheet_path}", file=sys.stderr)
            had_error = True
            continue

        prop = propose(sheet_path, party_entries)
        print(render_report(prop), end="")

        if prop.error:
            had_error = True
            continue

        if not args.apply:
            continue

        if prop.had_existing_frontmatter and not args.force:
            print(
                f"refusing to overwrite existing frontmatter in {sheet_path} "
                f"— pass --force to overwrite.",
                file=sys.stderr,
            )
            had_error = True
            continue

        original_text = sheet_path.read_text(encoding="utf-8")
        new_content = render_file_content(prop, original_text)
        atomic_write_text(sheet_path, new_content)
        print(f"Wrote frontmatter to {sheet_path}")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
