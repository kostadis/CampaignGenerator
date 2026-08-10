"""Party roster parsing for session_doc and the sd_* CLIs."""

from campaignlib.party_md import parse_party_md


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
    """
    roster: list[str] = []
    for entry in parse_party_md(party_text):
        roster.append(
            f"- {entry.name} ({entry.player}): {entry.class_info}"
            if entry.player
            else f"- {entry.name}: {entry.class_info}"
        )
    return "\n".join(roster)
