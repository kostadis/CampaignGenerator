"""Tests for session_doc/roster.py (issue #245, defect 4).

Covers the two hand-authored party.md layouts (legacy `## Name` /
`**Race Class N, Player: X**` and pipe `### Name` /
`**Class N (Subclass) | Species | Player`), the Phandalin regression that
produced cross-section junk, and — separately — the four other campaign
layouts that are knowingly unsupported (issue #245 follow-up): they must
come back empty, never junk, and the silent-failure warning added to
sd_narrate.py is what surfaces that to the GM.
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


# ── Other campaign layouts: knowingly unsupported, must be empty not junk ───
#
# These four formats (Hillsfar, OOTA, obelisk, stormgiants) are out of scope
# for this fix (issue #245 follow-up). The requirement here is narrower than
# "parse them": they must yield an empty string, never a junk match, and the
# --party warning added to sd_narrate.py is what surfaces the gap to the GM
# so a future work order can add real support instead of silent failure.

OTHER_CAMPAIGN_FIXTURES = {
    "hillsfar": (
        "## Characters\n\n### Akritas\n**High Elf Ranger 11** — player: kostadis1\n"
    ),
    "oota": (
        "## Characters\n\n### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · "
        "Player: Gabe\n- **Personality & motivations:** Silent tactical architect.\n"
    ),
    "obelisk": (
        "## Characters\n\n### Zenvon Foreput\n- **Class/Level:** Rogue 2 | "
        "**Species:** Halfling | **Player:** Nikhil Reddy\n"
    ),
    "stormgiants": (
        "## Characters\n\n### Vardis\n\n**Notable Relationships:** Close to Orsik.\n"
    ),
}


@pytest.mark.parametrize("name", sorted(OTHER_CAMPAIGN_FIXTURES))
def test_other_campaign_layouts_yield_empty_not_junk(name):
    assert extract_character_roster(OTHER_CAMPAIGN_FIXTURES[name]) == ""
