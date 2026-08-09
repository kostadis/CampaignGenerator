"""Party roster parsing for session_doc and the sd_* CLIs."""

import re

# A character section opens with an H2 or H3 heading. The class line is the FIRST
# bold-opening line inside that section and nothing else — whether it parses or
# not, the section is then closed. That one-shot rule is what stops the
# cross-section bleed that made `## Characters` pick up a
# `**Candidate Arc Score Events …**` header 30 lines later (issue #245).
_HEADING_RE = re.compile(r'^#{2,3}\s+(.+?)\s*$')


def _parse_class_line(line: str) -> tuple[str, str] | None:
    """Parse a party.md class line into ``(class_info, player)``.

    Two hand-authored formats are supported:

    Legacy (fully closed bold, comma-delimited player)::

        **Tortle Druid 5, Player: Wade**        -> ("Tortle Druid 5", "Wade")

    Pipe (species carried as its own field; the closing ``**`` and the
    ``Player:`` label are both optional, and a trailing space is common)::

        **Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau
            -> ("Goliath Barbarian 6 (Path of the Giant)", "Stephane Boudreau")
        **Cleric 6 (Peace Domain) | Drow Elf | Player: Gary Young**
            -> ("Drow Elf Cleric 6 (Peace Domain)", "Gary Young")

    Returns ``None`` when the line is not a class line at all. Two guards do
    that work: a class field must contain a level number (so an NPC-companion
    line like ``**Skeletal Horse (Undead) | NPC Companion**`` is rejected), and
    the body must not contain an inner ``**`` (so a prose label like
    ``**Stats (from sheet):** HP 59 max | AC 16 | ...`` is rejected).
    """
    s = line.strip()
    if not s.startswith("**"):
        return None
    body = s[2:]
    closed = body.endswith("**")
    if closed:
        body = body[:-2]
    body = body.strip()
    if not body or "**" in body:
        return None

    if "|" in body:
        fields = [f.strip().rstrip("*").strip() for f in body.split("|")]
        fields = [f for f in fields if f]
        if not fields or not re.search(r'\d', fields[0]):
            return None
        class_only = fields[0]
        species = fields[1] if len(fields) > 1 else ""
        player = ""
        if len(fields) > 2:
            player = re.sub(r'^Player\s*:\s*', '', fields[2]).strip()
        class_info = f"{species} {class_only}".strip() if species else class_only
        return class_info, player

    # Legacy form requires the bold to be closed — an unclosed, pipe-less bold
    # line is prose, not a class line.
    if not closed or not re.search(r'\d', body):
        return None
    pm = re.search(r',\s*Player:\s*(.+)$', body)
    if pm:
        return body[:pm.start()].strip(), pm.group(1).strip().rstrip('*').strip()
    return body, ""


def extract_character_roster(party_text: str) -> str:
    """Parse party.md and return a compact name -> class list for prompt injection.

    Handles both hand-authored section layouts::

        ## Soma                                     ### Brewbarry
        **Tortle Druid 5, Player: Wade**            **Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau

    Outputs::

        - Soma (Wade): Tortle Druid 5
        - Brewbarry (Stephane Boudreau): Goliath Barbarian 6 (Path of the Giant)

    A heading whose first bold-opening line is not a class line yields nothing,
    and the scan does not continue into the next section looking for one.
    """
    roster: list[str] = []
    current_name: str | None = None
    for line in party_text.splitlines():
        s = line.strip()
        hm = _HEADING_RE.match(s)
        if hm:
            current_name = hm.group(1).strip()
            continue
        if current_name is None or not s.startswith("**"):
            continue
        # First bold-opening line of the section: its one and only chance.
        name, current_name = current_name, None
        parsed = _parse_class_line(s)
        if parsed is None:
            continue
        class_info, player = parsed
        roster.append(f"- {name} ({player}): {class_info}" if player
                      else f"- {name}: {class_info}")
    return "\n".join(roster)
