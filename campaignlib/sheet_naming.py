"""Roster-driven naming for converted character sheets (feature 008).

The roster (``<config>/party.yaml``) is the authority for a converted sheet's
character name, the file it is written to, and who plays it. This module holds
the deterministic decisions that follow from that; ``dnd_sheet`` orchestrates
them around its one API call, and the web router only forwards flags.

**There is no fuzzy matching here, on purpose.** :func:`attribute` is an exact,
case-insensitive, whitespace-trimmed match requiring exactly one hit. Zero hits
and two hits both refuse. GM ruling, 2026-08-13: "let's just have it fail
loudly, and then I will go and fix the yaml." It is also what this project
already learned the hard way — a similarity band tells you an edit happened and
never that the result is safe (``project_similarity_cannot_separate_semantic_edits``),
so no prefix, token, edit-distance or embedding fallback may be added below.
Case-insensitivity is not fuzziness: ``sheet_frontmatter.propose`` already keys
its party cross-check on ``name.lower()``, and stripping is required because
``zalthir.md:5`` has a documented trailing space.

Every refusal carries the values that disagree and the one-line fix, and
nothing on disk is touched — ``dnd_sheet`` runs its API call before the first
filesystem mutation (D7), so a refusal costs tokens, never damage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol, TypeVar

import yaml

from campaignlib.sheet_identity import (
    AmbiguousLevelError,
    identity_block_span,
    parse_level,
    read_class_level,
)

#: The leading ``---`` block, captured RAW. Deliberately not
#: ``textproc.split_frontmatter``: that one parses, and a parse-then-redump
#: round trip rewrites key order, quoting and comments in a document this
#: feature only means to change one line of.
_RAW_FRONTMATTER_RE = re.compile(r"\A(---[ \t]*\n)(.*?\n)(---[ \t]*\n?)", re.DOTALL)
_FM_PLAYER_RE = re.compile(r"^player:.*$", re.MULTILINE)
_FM_NAME_RE = re.compile(r"^name:.*$", re.MULTILINE)
_IDENTITY_PLAYER_RE = re.compile(r"^(-\s+\*\*Player:\*\*).*$", re.MULTILINE)
_IDENTITY_FIELD_RE = re.compile(r"^-\s+\*\*[^*:]+:\*\*")


class RosterCharacter(Protocol):
    """The shape :func:`attribute` needs — ``PartyCharacter`` satisfies it.

    Deliberately structural: this module never imports the pydantic models,
    so the naming rules stay testable against a stub and the authored-vs-
    resolved distinction stays the caller's business.
    """

    name: str
    sheet: str


C = TypeVar("C", bound=RosterCharacter)


class SheetNamingError(Exception):
    """Base for every refusal below.

    Callers catch this rather than the individual classes — in particular it
    spares anyone from writing ``except AttributionError`` next to Python's own
    ``AttributeError``, which differs by one character and would swallow a
    genuine bug.
    """


class AttributionError(SheetNamingError):
    """The sheet's character name does not resolve to exactly one roster entry.

    ``matches`` is 0 (no such character) or >1 (duplicate names in the roster).
    ``roster_names`` is every name available, so the message can show the GM
    what they could have meant without the caller re-deriving it.
    """

    def __init__(self, extracted_name: str, roster_names: list[str], matches: int):
        self.extracted_name = extracted_name
        self.roster_names = roster_names
        self.matches = matches
        if matches:
            super().__init__(
                f"{extracted_name!r} matches {matches} roster entries"
            )
        else:
            super().__init__(
                f"{extracted_name!r} is not in the roster "
                f"({', '.join(roster_names) or 'the roster is empty'})"
            )


def attribute(extracted_name: str | None, characters: Iterable[C]) -> C:
    """The one roster entry whose name matches ``extracted_name``.

    Both sides are stripped and lowercased; anything short of exactly one hit
    raises :class:`AttributionError`. See the module docstring for why there is
    no fallback.
    """
    roster = list(characters)
    roster_names = sorted(c.name.strip() for c in roster)

    key = (extracted_name or "").strip().lower()
    if not key:
        raise AttributionError("", roster_names, 0)

    hits = [c for c in roster if c.name.strip().lower() == key]
    if len(hits) != 1:
        raise AttributionError(extracted_name.strip(), roster_names, len(hits))
    return hits[0]


class RosterFilenameMismatch(SheetNamingError):
    """The roster points at a filename this conversion would not write.

    FR-006 requires the roster's ``sheet:`` pointer to stay valid, and there
    are only two ways to guarantee that: edit the roster automatically, or
    refuse until it agrees. ``party.yaml`` is hand-authored — the whole
    authored-vs-resolved split exists to stop a round-trip rewriting what the
    GM typed — and the GM's ruling on the sibling question was "fail loudly,
    and then I will go and fix the yaml". So this carries the exact
    replacement line and ``dnd_sheet`` never writes to ``party.yaml``.
    """

    def __init__(self, character_name: str, declared: str, replacement: str):
        self.character_name = character_name
        self.declared = declared
        self.replacement = replacement
        super().__init__(
            f"roster says sheet: {declared} but this conversion writes "
            f"{PurePosixPath(replacement).name}"
        )


class RosterDirectoryMissing(SheetNamingError):
    """The directory the roster declares the sheet lives in does not exist.

    Not in the original FR list, and deliberately a refusal rather than a
    ``mkdir``: outside roster mode the operator chooses the output directory
    and creating it is the obvious kindness, but in roster mode the directory
    is *declared* by ``party.yaml`` and a missing one means the roster or the
    working directory is wrong. All five campaign rosters are campaign-root
    relative (#291 rewrote the three that were not), so this fires when the
    tool is run from somewhere other than the campaign root — and silently
    creating a ``docs/party/`` under whatever directory that happened to be,
    then writing a character sheet into it, is a far worse outcome than
    stopping.
    """

    def __init__(self, character_name: str, declared: str, directory: Path):
        self.character_name = character_name
        self.declared = declared
        self.directory = directory
        super().__init__(f"no such directory: {directory}")


def destination_for(character: RosterCharacter, base: Path) -> Path:
    """Where this conversion writes: the roster's own sheet directory, and the
    roster's own spelling of the character's name (FR-005).

    ``base`` is supplied by the caller — the campaign directory the roster's
    relative paths are written against — never derived from ``party.yaml``'s
    location, so moving the roster does not change what its contents mean.
    """
    declared = Path(character.sheet).expanduser()
    resolved = (Path(base).expanduser() / declared).resolve()
    return resolved.parent / f"{character.name.strip()}.md"


def check_destination(character: RosterCharacter, base: Path) -> Path:
    """:func:`destination_for`, refusing when the roster disagrees with it.

    Two disagreements are possible and both are the GM's to settle:
    :class:`RosterFilenameMismatch` (the declared ``sheet:`` basename is not
    what gets written — including a case-only difference, which a
    case-insensitive filesystem would otherwise blur, FR-007) and
    :class:`RosterDirectoryMissing`.
    """
    destination = destination_for(character, base)

    declared_name = PurePosixPath(character.sheet).name
    if declared_name != destination.name:
        raise RosterFilenameMismatch(
            character_name=character.name.strip(),
            declared=character.sheet,
            replacement=str(
                PurePosixPath(character.sheet).with_name(destination.name)
            ),
        )

    if not destination.parent.is_dir():
        raise RosterDirectoryMissing(
            character_name=character.name.strip(),
            declared=character.sheet,
            directory=destination.parent,
        )

    return destination


class DisplacedLevelUnreadable(SheetNamingError):
    """The sheet about to be replaced does not state exactly one level.

    ``phrase`` is what it said (``None`` when it recorded nothing at all), so
    the refusal can quote the value it could not interpret rather than making
    the GM go and find it.
    """

    def __init__(self, sheet: Path, phrase: str | None):
        self.sheet = sheet
        self.phrase = phrase
        super().__init__(
            f"cannot read a single level from {sheet}"
            + (f": {phrase!r}" if phrase else "")
        )


class ArchiveSlotOccupied(SheetNamingError):
    """A sheet is already archived at that level.

    Never overwritten and never suffixed. Losing an archived sheet is the one
    thing this whole feature exists to prevent, so it cannot be the failure
    mode of running the same conversion twice.
    """

    def __init__(self, path: Path, level: int):
        self.path = path
        self.level = level
        super().__init__(f"{path} already exists")


@dataclass(frozen=True)
class ArchivePlan:
    """One move, decided before anything on disk is touched."""

    source: Path
    destination: Path
    level: int


def archive_path(destination: Path, level: int, char_name: str) -> Path:
    """``<sheet dir>/old/level/<N>/<char-name>.md`` (FR-012, D5).

    Matches the archive the GM had already built by hand under
    ``Phandalin/docs/party/old/level/5/`` — note the roster-shaped filenames
    there, capitalised, sitting above lowercase live sheets. The archived name
    follows the roster too, so the two conventions never coexist.
    """
    return destination.parent / "old" / "level" / str(level) / f"{char_name.strip()}.md"


def plan_archive(destination: Path, char_name: str) -> ArchivePlan | None:
    """Where the sheet currently at ``destination`` must go, or ``None``.

    ``None`` means there is nothing to displace — the first conversion for a
    character. The level is read from the sheet **being displaced**, not the
    incoming one, so the archive reads as "the sheet as it was at level N".

    Raises before touching anything: :class:`DisplacedLevelUnreadable` when the
    old sheet states no level or more than one, :class:`ArchiveSlotOccupied`
    when that level is already filed.
    """
    if not destination.exists():
        return None

    phrase = read_class_level(destination.read_text(encoding="utf-8"))
    try:
        level = parse_level(phrase)
    except AmbiguousLevelError as exc:
        raise DisplacedLevelUnreadable(destination, phrase) from exc

    target = archive_path(destination, level, char_name)
    if target.exists():
        raise ArchiveSlotOccupied(target, level)
    return ArchivePlan(source=destination, destination=target, level=level)


def _frontmatter_player_line(player: str) -> str:
    """``player: <value>``, quoted the way YAML needs it."""
    return yaml.safe_dump(
        {"player": player},
        default_flow_style=False, sort_keys=False, allow_unicode=True, width=10 ** 6,
    ).strip()


def _apply_frontmatter_player(markdown: str, player: str) -> str:
    m = _RAW_FRONTMATTER_RE.match(markdown)
    if not m:
        return markdown  # no machine channel on this sheet — nothing to rewrite

    block = m.group(2)
    line = _frontmatter_player_line(player)
    if _FM_PLAYER_RE.search(block):
        block = _FM_PLAYER_RE.sub(lambda _m: line, block, count=1)
    else:
        # Keep the canonical key order (name, player, species, class_level,
        # subclass) the downstream parser expects rather than appending.
        name = _FM_NAME_RE.search(block)
        cut = name.end() if name else 0
        block = block[:cut] + ("\n" if name else "") + line + ("" if name else "\n") + block[cut:]
    return m.group(1) + block + m.group(3) + markdown[m.end():]


def _apply_identity_player(markdown: str, player: str) -> str:
    span = identity_block_span(markdown)
    if span is None:
        return markdown
    start, end = span
    block, replaced = _IDENTITY_PLAYER_RE.subn(
        lambda m: f"{m.group(1)} {player}".rstrip(), markdown[start:end], count=1
    )
    if not replaced:
        # No ``- **Player:**`` line to rewrite. SYSTEM_PROMPT tells the model to
        # omit body fields the sheet leaves blank, so a PDF with no player
        # produces exactly this — and returning unchanged would leave the
        # frontmatter carrying the roster's player and the prose carrying none,
        # which is the self-contradiction this function exists to prevent.
        block = _insert_identity_player(markdown[start:end], player)
    return markdown[:start] + block + markdown[end:]


def _insert_identity_player(block: str, player: str) -> str:
    """Add a ``- **Player:**`` line after the block's last bullet field."""
    line = f"- **Player:** {player}".rstrip()
    lines = block.splitlines(keepends=True)
    last = max(
        (i for i, text in enumerate(lines) if _IDENTITY_FIELD_RE.match(text.strip())),
        default=None,
    )
    if last is None:
        return block
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines.insert(last + 1, line + "\n")
    return "".join(lines)


def apply_roster_player(markdown: str, player: str | None) -> str:
    """Put the roster's player into **both** identity channels (FR-010a).

    A converted sheet states the player twice — the YAML frontmatter and the
    ``## Identity`` block's ``- **Player:**`` line — and rewriting one leaves
    the downloader's name legible in the document while tooling reports someone
    else. So both, or the document contradicts itself.

    ``player`` of ``None`` or blank empties both fields rather than leaving what
    the export produced. That is not data loss: a D&D Beyond download stamps the
    *downloader's* name into every sheet, so keeping it would record the GM as
    every character's player (FR-009). The caller says so on stderr.

    Only those two values change. The frontmatter block is spliced, never parsed
    and re-dumped, so key order, quoting and anything else the GM has in there
    survive untouched.
    """
    value = (player or "").strip()
    return _apply_identity_player(_apply_frontmatter_player(markdown, value), value)
