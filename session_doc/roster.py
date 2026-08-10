"""Party roster parsing for session_doc and the sd_* CLIs."""

import re

# A character section opens with an H2 or H3 heading. The class line is the FIRST
# bold-opening line inside that section and nothing else — whether it parses or
# not, the section is then closed. That one-shot rule is what stops the
# cross-section bleed that made `## Characters` pick up a
# `**Candidate Arc Score Events …**` header 30 lines later (issue #245).
_HEADING_RE = re.compile(r'^#{2,3}\s+(.+?)\s*$')

# out-of-the-abyss: the whole class/species/player triple lives in the heading
# itself, `·` (U+00B7 MIDDLE DOT) separated, name before an em dash:
#   ### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe
_HEADING_DASH_SPLIT_RE = re.compile(r'^(.*?)\s+—\s+(.*)$')

# Hillsfar: fully closed bold, player on an em-dash suffix OUTSIDE the closing
# `**` (species/class are fused with no delimiter and are never split — that
# needs a species lexicon, which is inference, not parsing):
#   **High Elf Ranger 11** — player: kostadis1
_HILLSFAR_SUFFIX_RE = re.compile(
    r'^\*\*(?P<class_info>.+?)\*\*\s*—\s*player\s*:\s*(?P<player>.+)$',
    re.IGNORECASE,
)

# stormgiants / obelisk / toee: labeled pipe fields, each `**Label:** value`.
# Obelisk additionally prefixes the whole line with a `- ` list marker (stripped
# by `_strip_list_prefix` before this ever sees it).
_LABEL_FIELD_RE = re.compile(r'^\*\*([^*:]+):\*\*\s*(.*)$')


def _strip_list_prefix(s: str) -> str:
    """Strip a leading ``- `` / ``* `` list marker (obelisk's layout only)."""
    if s.startswith("- ") or s.startswith("* "):
        return s[2:].strip()
    return s


def _combine_species_class(species: str, class_only: str) -> str:
    """Join a separately-carried species onto the class/level string.

    Deterministic string check only — never inference. If ``class_only``
    already starts with ``species`` verbatim (toee: ``Class/Level: Tiefling
    Rogue (Assassin)`` next to ``Species: Tiefling``), the source has already
    folded species into the class field; emit it as-is rather than doubling
    the word. Per the GM's ruling, that toee data isn't being fixed here — the
    parser just doesn't compound the duplication.
    """
    species = species.strip()
    class_only = class_only.strip()
    if not species or class_only.startswith(species):
        return class_only
    return f"{species} {class_only}".strip()


def _parse_labeled_fields(s: str) -> tuple[str, str] | None:
    """Parse the labeled pipe form (stormgiants / obelisk / toee)::

        **Class/Level:** Cleric 13 (Light Domain) | **Species:** Wood Elf | **Player:** Wade Brown

    Every ``**Label:** value`` field is collected; only ``Class/Level``,
    ``Species`` and ``Player`` are consumed — anything else (``Alignment``,
    ``Role``, ...) is a tolerated extra and is silently ignored, no special
    casing per label.

    The ``**Class/Level:**`` label is itself the proof this is a class line,
    so — unlike the unlabeled pipe form below — a missing level number does
    NOT disqualify it: toee has real PCs with no level recorded at all
    (``**Class/Level:** Elf Monk``), and the GM's ruling is to emit what the
    source has rather than infer the missing field.
    """
    head = _LABEL_FIELD_RE.match(s)
    if not head or head.group(1).strip().lower() != "class/level":
        return None

    fields: dict[str, str] = {}
    for raw in s.split("|"):
        m = _LABEL_FIELD_RE.match(raw.strip())
        if not m:
            continue
        label = m.group(1).strip().lower()
        value = m.group(2).strip().rstrip("*").strip()
        if label not in fields:
            fields[label] = value

    class_only = fields.get("class/level", "").strip()
    if not class_only:
        return None
    class_info = _combine_species_class(fields.get("species", ""), class_only)
    return class_info, fields.get("player", "")


def _parse_class_line(line: str) -> tuple[str, str] | None:
    """Parse a party.md class line into ``(class_info, player)``.

    Formats supported (see module docstring of `extract_character_roster`
    for the full layout catalogue):

    Legacy (fully closed bold, comma-delimited player)::

        **Tortle Druid 5, Player: Wade**        -> ("Tortle Druid 5", "Wade")

    Unlabeled pipe (species carried as its own field; the closing ``**`` and
    the ``Player:`` label are both optional, and a trailing space is common)::

        **Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau
            -> ("Goliath Barbarian 6 (Path of the Giant)", "Stephane Boudreau")
        **Cleric 6 (Peace Domain) | Drow Elf | Player: Gary Young**
            -> ("Drow Elf Cleric 6 (Peace Domain)", "Gary Young")

    Hillsfar (closed bold, em-dash player suffix OUTSIDE the bold)::

        **High Elf Ranger 11** — player: kostadis1
            -> ("High Elf Ranger 11", "kostadis1")

    Labeled pipe (stormgiants / obelisk / toee; see `_parse_labeled_fields`).

    Returns ``None`` when the line is not a class line at all. For the
    unlabeled forms two guards do that work: a class field must contain a
    level number (so an NPC-companion line like ``**Skeletal Horse (Undead)
    | NPC Companion**`` is rejected), and the body must not contain an inner
    ``**`` (so a prose label like ``**Stats (from sheet):** HP 59 max | AC 16
    | ...`` is rejected). The labeled form has its own proof-of-class-ness
    (the ``**Class/Level:**`` label) and does not apply the digit guard.
    """
    s = _strip_list_prefix(line.strip())
    if not s.startswith("**"):
        return None

    labeled = _parse_labeled_fields(s)
    if labeled is not None:
        return labeled

    hm = _HILLSFAR_SUFFIX_RE.match(s)
    if hm:
        class_info = hm.group("class_info").strip()
        if class_info and re.search(r'\d', class_info):
            return class_info, hm.group("player").strip()
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
        class_info = _combine_species_class(species, class_only)
        return class_info, player

    # Legacy form requires the bold to be closed — an unclosed, pipe-less bold
    # line is prose, not a class line.
    if not closed or not re.search(r'\d', body):
        return None
    pm = re.search(r',\s*Player:\s*(.+)$', body)
    if pm:
        return body[:pm.start()].strip(), pm.group(1).strip().rstrip('*').strip()
    return body, ""


def _parse_oota_heading(heading: str) -> tuple[str, str, str] | None:
    """Parse the out-of-the-abyss heading-embedded layout::

        Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe

    Everything lives in the heading itself: class first, species second
    (species may itself carry parens, e.g. ``Orc (Sage)``), then a
    ``Player:`` field, plus tolerated extras (``Faith:``, ...) that are
    silently ignored. Returns ``(name, class_info, player)``, or ``None`` if
    the heading doesn't carry this ``·``-separated field structure — a plain
    ``### Akritas`` heading (no dash, no dot) must fall through untouched.
    """
    m = _HEADING_DASH_SPLIT_RE.match(heading)
    if not m:
        return None
    name, rest = m.group(1).strip(), m.group(2).strip()
    if '·' not in rest:
        return None
    fields = [f.strip() for f in rest.split('·') if f.strip()]
    if not fields:
        return None
    class_only = fields[0]
    species = ""
    player = ""
    for f in fields[1:]:
        pm = re.match(r'(?i)^player\s*:\s*(.+)$', f)
        if pm:
            player = pm.group(1).strip()
        elif not species:
            species = f
        # else: tolerated extra field (Faith:, ...) — ignored.
    return name, _combine_species_class(species, class_only), player


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
    """
    roster: list[str] = []
    current_name: str | None = None
    for line in party_text.splitlines():
        s = line.strip()
        hm = _HEADING_RE.match(s)
        if hm:
            heading_text = hm.group(1).strip()
            oota = _parse_oota_heading(heading_text)
            if oota is not None:
                name, class_info, player = oota
                roster.append(f"- {name} ({player}): {class_info}" if player
                              else f"- {name}: {class_info}")
                current_name = None
            else:
                current_name = heading_text
            continue
        if current_name is None or not _strip_list_prefix(s).startswith("**"):
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
