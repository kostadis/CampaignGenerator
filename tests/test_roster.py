"""Tests for session_doc/roster.py (issue #245 defect 4; issue #248 follow-up).

Covers all six hand-authored party.md layouts now supported:

1. Legacy (`## Name` / `**Race Class N, Player: X**`)
2. Unlabeled pipe (`### Name` / `**Class N (Subclass) | Species | Player`)
3. Hillsfar (`### Name` / `**Class N** — player: X`, em-dash suffix outside
   the closing bold, species+class fused with no delimiter)
4. out-of-the-abyss (everything in the heading, `·`-separated:
   `### Name — Class N (Sub) · Species · Player: X`)
5. Labeled pipe, no list prefix — stormgiants / toee
   (`**Class/Level:** ... | **Species:** ... | **Player:** ...`)
6. Labeled pipe, `- ` list prefix — obelisk (same fields, list-marked)

plus the Phandalin regression that produced cross-section junk. The
fixtures below for layouts 3-6 are verbatim excerpts from each campaign's
real `~/src/campaigns/<name>/docs/party.md` (issue #248).
"""

import pytest

from session_doc.roster import extract_character_roster

# Verbatim excerpt from /home/kroussos/src/campaigns/Phandalin/docs/party.md.
# NOTE: the Brewbarry class line has an UNCLOSED bold and a TRAILING SPACE.
# Both are real. Do not "clean them up" — they are the regression.
PHANDALIN_PARTY = (
    "# Party Reference — Icespire Peak / Phandalin Campaign\n"
    "\n"
    "> **Hand-correction (2026-08-07) — Cryovain hoard.** The generated text said the "
    "hoard was *\"at Icespire Hold — unclaimed\"*.\n"
    "\n"
    "## Party Overview\n"
    "\n"
    "**Current location:** Scattered between the Woodland Manse vicinity and the road "
    "south to Phandalin.\n"
    "\n"
    "**Active obligations:**\n"
    "- Return stolen goods and a statue to Neverwinter contacts.\n"
    "\n"
    "## Characters\n"
    "\n"
    "### Brewbarry\n"
    "\n"
    "**Barbarian 6 (Path of the Giant) | Goliath | Stephane Boudreau \n"
    "\n"
    "*The character sheet lists the player as Stephane Boudreau.*\n"
    "\n"
    "**Stats (from sheet):** HP 59 max | AC 16 | STR +4 | CON +2 | Speed 45 ft. | "
    "Rage ×4/LR | Extra Attack\n"
    "\n"
    "**Notable relationships:**\n"
    "- *Vukradin* — musical partner, protector, anchor\n"
    "\n"
    "**Candidate Arc Score Events — Thistle's Echo Score (0–30)**\n"
    "\n"
    "- [Ch 39]: Used Uthgardt tribal knowledge to identify twig effigies. → Candidate "
    "**+2 The Unnatural Radar**\n"
    "\n"
    "### Valphine Sotorra\n"
    "\n"
    "**Cleric 6 (Peace Domain) | Drow Elf | Player: Gary Young**\n"
    "\n"
    "**Stats (from sheet):** HP 45 max | AC 18 | WIS +4\n"
    "\n"
    "### Soma\n"
    "\n"
    "**Druid 6 (Circle of the Moon) | Tortle | Player: Wade Brown**\n"
    "\n"
    "### Vukradin\n"
    "\n"
    "**Bard 6 (College of Eloquence) | Aasimar | Player: David Mendenhall (Dave)**\n"
    "\n"
    "### Boney\n"
    "\n"
    "**Skeletal Horse (Undead) | NPC Companion**\n"
    "\n"
    "**Combat role:** Active combatant; bites paralyzed or frozen targets (ch43).\n"
    "\n"
    "## Party Dynamics\n"
    "\n"
    "**The center of gravity is Vukradin.** He sets the ethical frame.\n"
)


def test_fixture_still_has_the_trailing_space():
    """Guard the guard: a whitespace-stripping editor would silently defuse the
    unclosed-bold regression this whole module exists to pin."""
    assert "Stephane Boudreau \n" in PHANDALIN_PARTY, (
        "fixture lost the trailing space after 'Stephane Boudreau' — restore it; "
        "it is the real file's content and the point of the test"
    )


# ── Phandalin format (pipe, H3) ──────────────────────────────────────────────

EXPECTED_PHANDALIN_ROSTER = "\n".join([
    "- Brewbarry (Stephane Boudreau): Goliath Barbarian 6 (Path of the Giant)",
    "- Valphine Sotorra (Gary Young): Drow Elf Cleric 6 (Peace Domain)",
    "- Soma (Wade Brown): Tortle Druid 6 (Circle of the Moon)",
    "- Vukradin (David Mendenhall (Dave)): Aasimar Bard 6 (College of Eloquence)",
])


def test_phandalin_format_yields_four_characters():
    assert extract_character_roster(PHANDALIN_PARTY) == EXPECTED_PHANDALIN_ROSTER


def test_species_reaches_the_roster_line():
    """The ch46 regression: a Goliath was narrated as 'all five and a half feet'
    because species never reached the prompt. Assert it by name."""
    out = extract_character_roster(PHANDALIN_PARTY)
    brewbarry_line = next(line for line in out.splitlines() if line.startswith("- Brewbarry"))
    assert "Goliath" in brewbarry_line


def test_unclosed_bold_and_trailing_space_parse():
    out = extract_character_roster(PHANDALIN_PARTY)
    assert "- Brewbarry (Stephane Boudreau): Goliath Barbarian 6 (Path of the Giant)" in out


def test_npc_companion_without_a_level_is_excluded():
    out = extract_character_roster(PHANDALIN_PARTY)
    assert "Boney" not in out


def test_no_cross_section_junk():
    out = extract_character_roster(PHANDALIN_PARTY)
    for junk in (
        "Candidate Arc Score",
        "Characters",
        "Party Overview",
        "Party Dynamics",
        "Stats",
        "center of gravity",
    ):
        assert junk not in out
    # The exact bug this rewrite fixes:
    assert "- Characters: Candidate Arc Score Events" not in out


# ── Legacy format (closed bold, H2, comma-delimited player) ─────────────────

def test_legacy_format_still_parses():
    assert extract_character_roster(
        "## Soma\n**Tortle Druid 5, Player: Wade**\n"
    ) == "- Soma (Wade): Tortle Druid 5"

    # Golden-matrix fixture.
    assert extract_character_roster(
        "## Brewbarry\n**Halfling Rogue 5, Player: Sam**"
    ) == "- Brewbarry (Sam): Halfling Rogue 5"


def test_legacy_without_player_label():
    assert extract_character_roster(
        "## Grug\n**Orc Barbarian 3**"
    ) == "- Grug: Orc Barbarian 3"


def test_pipe_format_without_player_field():
    assert extract_character_roster(
        "### Ana\n**Ranger 4 | Elf**"
    ) == "- Ana: Elf Ranger 4"


def test_empty_party_text_yields_empty_string():
    assert extract_character_roster("") == ""
    assert extract_character_roster(
        "## Party Overview\n\n**Current location:** Nowhere in particular.\n"
    ) == ""


# ── Hillsfar format (H3, closed bold, em-dash player suffix OUTSIDE the bold) ─
#
# Verbatim from ~/src/campaigns/Hillsfar/docs/party.md. Species+class are
# fused with no delimiter ("High Elf Ranger 11") — the parser must NOT try to
# split them; that needs a species lexicon, which is inference, not parsing.

HILLSFAR_PARTY = (
    "## Characters\n"
    "\n"
    "### Akritas\n"
    "**High Elf Ranger 11** — player: kostadis1\n"
    "\n"
    "### Bramgrim Stoutale\n"
    "**Hill Dwarf Life Cleric 11** — player: kostadis1\n"
    "\n"
    "### Daein\n"
    "**Human Fighter 9 / Bard 2** — player: kostadis1\n"
    "\n"
    "### Felkur Oldenwood\n"
    "**Rock Gnome Artillerist Artificer 11** — player: kostadis1\n"
)

EXPECTED_HILLSFAR_ROSTER = "\n".join([
    "- Akritas (kostadis1): High Elf Ranger 11",
    "- Bramgrim Stoutale (kostadis1): Hill Dwarf Life Cleric 11",
    "- Daein (kostadis1): Human Fighter 9 / Bard 2",
    "- Felkur Oldenwood (kostadis1): Rock Gnome Artillerist Artificer 11",
])


def test_hillsfar_format_yields_four_characters():
    assert extract_character_roster(HILLSFAR_PARTY) == EXPECTED_HILLSFAR_ROSTER


# ── out-of-the-abyss format (everything in the H3 heading, `·`-separated) ───
#
# Verbatim from ~/src/campaigns/out-of-the-abyss/docs/party.md. Class first,
# species second (species may itself carry parens: "Orc (Sage)"), then
# `Player:`, plus a tolerated extra (`Faith:`) that must be ignored.

OOTA_PARTY = (
    "## Characters\n"
    "\n"
    "### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe\n"
    "- **Personality & motivations:** Silent tactical architect.\n"
    "\n"
    "### Thorin — Fighter 8 (Battle Master) · Dwarf (Giant Foundling) · Player: Joe Beda\n"
    "- **Personality & motivations:** Blunt melee pragmatist.\n"
    "\n"
    "### Grygum — Cleric 8 (Life Domain) · Orc (Sage) · Player: Ben Pfaff · Faith: Bahamut\n"
    "- **Personality & motivations:** Compulsive documentarian.\n"
    "\n"
    "### Daz — Wizard 8 (Evoker) · Elf (Drow Lineage) · Player: Mike Hall\n"
    "- **Personality & motivations:** Lead investigator.\n"
)

EXPECTED_OOTA_ROSTER = "\n".join([
    "- Zalthir (Gabe): Bronze Dragonborn Monk 8 (Warrior of Shadow)",
    "- Thorin (Joe Beda): Dwarf (Giant Foundling) Fighter 8 (Battle Master)",
    "- Grygum (Ben Pfaff): Orc (Sage) Cleric 8 (Life Domain)",
    "- Daz (Mike Hall): Elf (Drow Lineage) Wizard 8 (Evoker)",
])


def test_oota_format_yields_four_characters():
    assert extract_character_roster(OOTA_PARTY) == EXPECTED_OOTA_ROSTER


def test_oota_heading_fields_close_the_section():
    """The heading supplies the whole class line; the body's `- **...**` line
    must not get a second chance at it (there's nothing left to parse anyway,
    but the section must be closed, not left open)."""
    out = extract_character_roster(OOTA_PARTY)
    assert "Personality" not in out
    assert "Silent tactical architect" not in out


def test_oota_plain_heading_is_unaffected():
    """A heading with no em-dash/middle-dot field structure must fall through
    to the ordinary heading-name path untouched."""
    assert extract_character_roster(
        "### Akritas\n**High Elf Ranger 11** — player: kostadis1\n"
    ) == "- Akritas (kostadis1): High Elf Ranger 11"


# ── Labeled pipe format, no list prefix (stormgiants / toee) ────────────────

# Verbatim from ~/src/campaigns/stormgiants/docs/party.md. Must tolerate the
# extra `| **Alignment:** ...` field on Unla Key.

STORMGIANTS_PARTY = (
    "## Characters\n"
    "\n"
    "### Vardis\n"
    "**Class/Level:** Cleric 13 (Light Domain) | **Species:** Wood Elf | **Player:** Wade Brown\n"
    "\n"
    "### Orsik\n"
    "**Class/Level:** Fighter 11 / Artificer 2 | **Species:** Mountain Dwarf | "
    "**Player:** David Mendenhall\n"
    "\n"
    "### Unla Key\n"
    "**Class/Level:** Wizard 13 (School of Divination) | **Species:** Lightfoot Halfling | "
    "**Player:** Jared Rossof | **Alignment:** Neutral Evil\n"
)

EXPECTED_STORMGIANTS_ROSTER = "\n".join([
    "- Vardis (Wade Brown): Wood Elf Cleric 13 (Light Domain)",
    "- Orsik (David Mendenhall): Mountain Dwarf Fighter 11 / Artificer 2",
    "- Unla Key (Jared Rossof): Lightfoot Halfling Wizard 13 (School of Divination)",
])


def test_stormgiants_format_yields_three_characters():
    # Only Vardis/Orsik/Unla Key exist in the real doc — there is no Thistle
    # entry. That's a known data gap in stormgiants, not a parser bug.
    assert extract_character_roster(STORMGIANTS_PARTY) == EXPECTED_STORMGIANTS_ROSTER


# ── Labeled pipe format, `- ` list prefix (obelisk) ──────────────────────────

# Verbatim from ~/src/campaigns/obelisk/docs/party.md (post campaigns#142 data
# fix: sidekicks now carry `**Player:** GM` and `**Role:** Sidekick` in the
# same labeled shape as Zenvon's line, rather than the unparseable prose bold
# they used to have).

OBELISK_PARTY = (
    "## Characters\n"
    "\n"
    "### Zenvon Foreput\n"
    "- **Class/Level:** Rogue 2 | **Species:** Halfling | **Player:** Nikhil Reddy\n"
    "\n"
    "### Veyra of the Blue Candle\n"
    "- **Class/Level:** Mage 2 | **Species:** Tiefling | **Player:** GM | **Role:** Sidekick\n"
    "- *(Level-up to 3 pending.)*\n"
    "\n"
    "### Sister Maela Dawnforge\n"
    "- **Class/Level:** Cleric 2 | **Species:** Dwarf | **Player:** GM | **Role:** Sidekick\n"
    "- *(Level-up to 3 pending.)*\n"
    "\n"
    "### Pip Thistlewick\n"
    "- **Class/Level:** Fighter 2 | **Species:** Human | **Player:** GM | **Role:** Sidekick\n"
    "- *(Level-up to 3 pending.)*\n"
)

EXPECTED_OBELISK_ROSTER = "\n".join([
    "- Zenvon Foreput (Nikhil Reddy): Halfling Rogue 2",
    "- Veyra of the Blue Candle (GM): Tiefling Mage 2",
    "- Sister Maela Dawnforge (GM): Dwarf Cleric 2",
    "- Pip Thistlewick (GM): Human Fighter 2",
])


def test_obelisk_format_yields_four_characters():
    assert extract_character_roster(OBELISK_PARTY) == EXPECTED_OBELISK_ROSTER


# ── toee wrinkles: level after the subclass parens; three PCs with no level
#    at all, one of which duplicates species into Class/Level ────────────────

# Verbatim from ~/src/campaigns/toee/docs/party.md.

TOEE_PARTY = (
    "## Characters\n"
    "\n"
    "### Calmer\n"
    "**Class/Level:** Cleric (War Domain) 6 | **Species:** Human | "
    "**Player:** Kostadis/Kostadis Roussos/kostadis1\n"
    "\n"
    "### Zephyr\n"
    "**Class/Level:** Tiefling Rogue (Assassin) | **Species:** Tiefling | "
    "**Player:** Thomas/Thomas Kolivakis\n"
    "\n"
    "### Zinnia\n"
    "**Class/Level:** Elf Monk | **Species:** Elf | **Player:** George/George Kolivakis \n"
    "\n"
    "### Sequoia\n"
    "**Class/Level:** Halfling Rogue | **Species:** Halfling | **Player:** Nicholas\n"
)

EXPECTED_TOEE_ROSTER = "\n".join([
    "- Calmer (Kostadis/Kostadis Roussos/kostadis1): Human Cleric (War Domain) 6",
    "- Zephyr (Thomas/Thomas Kolivakis): Tiefling Rogue (Assassin)",
    "- Zinnia (George/George Kolivakis): Elf Monk",
    "- Sequoia (Nicholas): Halfling Rogue",
])


def test_toee_format_yields_four_characters():
    assert extract_character_roster(TOEE_PARTY) == EXPECTED_TOEE_ROSTER


def test_toee_species_never_doubles_into_a_missing_level():
    """Zephyr/Zinnia/Sequoia have no level on the sheet, and Class/Level
    already has species folded in ('Tiefling Rogue (Assassin)'). The parser
    must emit that as-is — never invent a level, never double the species
    word by blindly prepending it again."""
    out = extract_character_roster(TOEE_PARTY)
    zephyr = next(line for line in out.splitlines() if line.startswith("- Zephyr"))
    assert zephyr == "- Zephyr (Thomas/Thomas Kolivakis): Tiefling Rogue (Assassin)"
    assert "Tiefling Tiefling" not in out


# ── Labeled form: unknown trailing label is ignored, no special-casing ──────

def test_labeled_form_ignores_unknown_trailing_label():
    """Real-world shape: stormgiants' `**Alignment:**`, obelisk's `**Role:**`.
    The labeled-pipe parser must ignore any label it doesn't recognise rather
    than choke on it, fold it into another field, or need a name check for
    what the label says (no "sidekick" special-casing anywhere)."""
    assert extract_character_roster(
        "### Test Char\n"
        "**Class/Level:** Fighter 3 | **Species:** Human | **Player:** Jamie | "
        "**Role:** Sidekick\n"
    ) == "- Test Char (Jamie): Human Fighter 3"

    assert extract_character_roster(
        "### Other Char\n"
        "**Class/Level:** Wizard 5 | **Species:** Elf | **Player:** Robin | "
        "**Alignment:** Chaotic Good\n"
    ) == "- Other Char (Robin): Elf Wizard 5"


# ── No-bleed / no-guess: non-class bold lines still yield nothing ───────────
#
# Synthetic fixtures (not tied to any one campaign's current file — obelisk's
# real sidekick lines now parse, see above). The requirement is narrower than
# "parse them": an unparseable bold line must yield nothing, never a junk
# guess.

SYNTHETIC_NON_CLASS_FIXTURES = {
    "prose_label_no_digit": (
        "### Some NPC\n**Notable relationships:** Close ally of the party.\n"
    ),
    "unlabeled_prose_with_list_prefix": (
        "### Some Sidekick\n"
        "- **Something mage sidekick, Level 2** (level-up to 3 pending).\n"
    ),
    "hillsfar_shape_without_player_suffix": (
        "### Some Character\n**Human Fighter 5** — a footnote, not a player field.\n"
    ),
}


@pytest.mark.parametrize("name", sorted(SYNTHETIC_NON_CLASS_FIXTURES))
def test_non_class_bold_lines_yield_nothing_not_junk(name):
    assert extract_character_roster(SYNTHETIC_NON_CLASS_FIXTURES[name]) == ""
