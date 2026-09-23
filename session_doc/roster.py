"""Party roster parsing for session_doc and the sd_* CLIs."""

import sys
from typing import TYPE_CHECKING

from campaignlib.party_md import parse_party_md
from campaignlib.players_config import norm_name
from campaignlib.textproc import split_frontmatter

if TYPE_CHECKING:
    from campaignlib.party_config import ResolvedPartyConfig


def extract_character_roster(party_text: str) -> str:
    """Parse party.md and return a compact name -> class list for prompt injection.

    Handles six hand-authored campaign layouts:

    1. Legacy (H2 heading, fully closed bold, comma-delimited player)::

        ## Soma
        **Tortle Druid 5, Player: Wade**

    2. Unlabeled pipe (H3 heading, species as its own field)::

        ### Brewbarry
        **Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau

    3. Hillsfar (H3 heading, closed bold, em-dash player suffix OUTSIDE the bold)::

        ### Akritas
        **High Elf Ranger 11** — player: kostadis1

    4. out-of-the-abyss (everything in the heading, `·`-separated)::

        ### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe

    5. Labeled pipe, no list prefix (stormgiants / toee)::

        ### Vardis
        **Class/Level:** Cleric 13 (Light Domain) | **Species:** Wood Elf | **Player:** Wade Brown

    6. Labeled pipe, `- ` list prefix (obelisk)::

        ### Zenvon Foreput
        - **Class/Level:** Rogue 2 | **Species:** Halfling | **Player:** Nikhil Reddy

    Outputs::

        - Soma (Wade): Tortle Druid 5
        - Brewbarry (Stephane Boudreau): Goliath Barbarian 6 (Path of the Giant)
        - Akritas (kostadis1): High Elf Ranger 11
        - Zalthir (Gabe): Bronze Dragonborn Monk 8 (Warrior of Shadow)
        - Vardis (Wade Brown): Wood Elf Cleric 13 (Light Domain)
        - Zenvon Foreput (Nikhil Reddy): Halfling Rogue 2

    A heading whose first bold-opening line is not a class line yields nothing,
    and the scan does not continue into the next section looking for one —
    except for out-of-the-abyss's heading-embedded layout, where the heading
    itself supplies the class line and the section is closed immediately,
    before any body line gets a look.

    The layout-detection machinery lives in `campaignlib.party_md`
    (`parse_party_md`) — this is a thin formatter over its `PartyEntry` list,
    shared with `campaignlib.npc.extract_player_character_map` (issue #260).

    NOTE (#398): unlike `roster_from_config` below, this still renders the
    real person's name in the `(player)` parenthetical — it is a parser for
    legacy hand-authored `party.md` dialects and has no production consumer
    today. Do not wire this output into a narration prompt without stripping
    the parenthetical first; handing the model real names of people at the
    table is exactly the defect #398 fixes on the `roster_from_config` path.
    """
    roster: list[str] = []
    for entry in parse_party_md(party_text):
        roster.append(
            f"- {entry.name} ({entry.player}): {entry.class_info}"
            if entry.player
            else f"- {entry.name}: {entry.class_info}"
        )
    return "\n".join(roster)


#: Appended to a character whose player was not at the session.
#:
#: The wording is the whole risk of this feature, and it is deliberately about
#: VOICING, not about presence in the fiction. Brewbarry's player was absent
#: from the session behind #385; Brewbarry was *in the tavern*, because the GM
#: put him there and narrated him walking in. A marker reading "not in this
#: session" would make the roster block — the one Pass 5 is told never to
#: contradict — assert something the extraction flatly contradicts, turning a
#: fabrication guard into a fabrication cause. The character stays fully
#: grounded; only the claim about who spoke for them is added.
UNVOICED_MARKER = (
    " — no player voiced them this session; the GM may still have placed them "
    "in scenes, so narrate what the extraction shows and invent no dialogue "
    "for them"
)


def roster_from_config(
    cfg: "ResolvedPartyConfig",
    unvoiced: "set[str] | None" = None,
) -> str | None:
    """Render the roster from each character's D&D Beyond sheet, per the GM
    ruling in ``docs/design/PartyRosterCanonicalFormat.md`` (issue #265):
    the sheet is canonical for character-specific data, ``party.yaml``
    only references it.

    ``cfg`` must already be resolved (:func:`campaignlib.party_config.
    resolve_party_config`) — this function does not choose a base
    directory itself, the caller owns that decision. (Which base was
    correct used to be campaign-dependent; #291 made every campaign's
    ``party.yaml`` campaign-root-relative, so the cwd default now works
    everywhere.)

    For each character, reads ``sheet``, splits its YAML frontmatter
    (:func:`campaignlib.textproc.split_frontmatter`), and formats one line::

        - {name}: {species} {class_level} ({subclass})

    ``subclass`` is appended only when non-empty. It is optional because it
    cannot be recovered from an unmigrated sheet body, but omitting it is a
    real loss: ``party.md`` carries the parenthetical ("Barbarian 6 (Path of
    the Giant)"), so a blank one silently shortens the roster block that
    goes into the narration prompt.

    #398: this never renders the person's name. It used to — a ``players``
    parameter supplied it (feature 009) and the line shape was
    ``- {name} ({player}): ...`` — but nothing forbade the model from writing
    a real person's name into the prose once it was in the prompt, so the fix
    is to stop supplying it at all. The roster block is scoped to what a
    narrator needs to know about the *character*: species, class, subclass.
    Who plays them is not narration-relevant and must never reach this
    prompt. (``extract_character_roster`` above still renders it, for its own
    unrelated legacy reasons — see the note on that function.)

    Every field is ``.strip()``-ed (one real sheet has a trailing space after
    a frontmatter value). ``name`` comes from ``cfg`` — the party.yaml
    entry's own name — not from the sheet's frontmatter, since ``party.yaml``
    is what maps a roster slot to a sheet.

    ALL-OR-NOTHING: returns ``None`` unless EVERY character's sheet exists
    on disk and yields frontmatter with non-empty ``species`` and
    ``class_level``. A roster silently missing one PC from the "never
    contradict these" narration prompt block is worse than falling back to
    ``party.md`` entirely, so a single unusable sheet fails the whole
    roster. On returning ``None``, prints to stderr which character(s)
    were unusable and why.
    """
    lines: list[str] = []
    problems: list[str] = []
    if not cfg.characters:
        # A roster of nobody is a broken config, not an empty-but-valid one.
        # Falling through would return "" — which callers accept — and render
        # with the "never contradict these" block silently absent, the exact
        # roster-less render #265 exists to prevent.
        problems.append("party.yaml lists no characters at all")
    for character in cfg.characters:
        sheet = character.sheet
        if not sheet.exists():
            problems.append(f"{character.name}: sheet not found at {sheet}")
            continue
        frontmatter, _body = split_frontmatter(sheet.read_text(encoding="utf-8"))
        if not frontmatter:
            problems.append(f"{character.name}: sheet has no YAML frontmatter ({sheet})")
            continue
        species = str(frontmatter.get("species") or "").strip()
        class_level = str(frontmatter.get("class_level") or "").strip()
        if not species or not class_level:
            problems.append(
                f"{character.name}: sheet frontmatter missing 'species' or "
                f"'class_level' ({sheet})"
            )
            continue
        subclass = str(frontmatter.get("subclass") or "").strip()
        class_info = f"{species} {class_level}".strip()
        if subclass:
            class_info = f"{class_info} ({subclass})"
        # #398: never render the person's name here — see the docstring.
        line = f"- {character.name}: {class_info}"
        # `unvoiced` of None is the whole of today's behaviour, byte for byte —
        # `pipelines/ensemble/polish.py` is a second caller and must stay inert.
        if unvoiced and norm_name(character.name) in {
            norm_name(n) for n in unvoiced
        }:
            line += UNVOICED_MARKER
        lines.append(line)
    if problems:
        print(
            "roster_from_config: no usable roster — not every character's "
            "sheet yields usable frontmatter:\n"
            + "\n".join(f"  - {p}" for p in problems),
            file=sys.stderr,
        )
        return None
    return "\n".join(lines)
