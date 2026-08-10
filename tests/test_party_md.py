"""Tests for campaignlib/party_md.py (issue #260).

`parse_party_md` is the single layout-detection parser for the six
hand-authored `party.md` dialects; `session_doc.roster.extract_character_roster`
and `campaignlib.npc.extract_player_character_map` are thin projections over
its `PartyEntry` list — see tests/test_roster.py and the
`extract_player_character_map` tests in tests/test_prep.py for coverage of
those two projections against real campaign excerpts. This module tests the
shared parser directly.
"""

from campaignlib.party_md import PartyEntry, parse_party_md


# ── One test per layout ──────────────────────────────────────────────────────


def test_legacy_comma_form():
    text = "## Soma\n**Tortle Druid 5, Player: Wade**\n"
    assert parse_party_md(text) == [
        PartyEntry(name="Soma", class_info="Tortle Druid 5", player="Wade")
    ]


def test_unlabeled_pipe_form():
    """Phandalin: species carried as its own pipe field."""
    text = (
        "### Brewbarry\n"
        "**Barbarian 6 (Path of the Giant) | Goliath | Player: Stephane Boudreau**\n"
    )
    assert parse_party_md(text) == [
        PartyEntry(
            name="Brewbarry",
            class_info="Goliath Barbarian 6 (Path of the Giant)",
            player="Stephane Boudreau",
        )
    ]


def test_hillsfar_em_dash_form():
    """Hillsfar: closed bold, player on an em-dash suffix OUTSIDE the bold."""
    text = "### Akritas\n**High Elf Ranger 11** — player: kostadis1\n"
    assert parse_party_md(text) == [
        PartyEntry(name="Akritas", class_info="High Elf Ranger 11", player="kostadis1")
    ]


def test_oota_heading_embedded_form():
    """out-of-the-abyss: the whole triple lives in the heading, `·`-separated."""
    text = "### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe\n"
    assert parse_party_md(text) == [
        PartyEntry(
            name="Zalthir",
            class_info="Bronze Dragonborn Monk 8 (Warrior of Shadow)",
            player="Gabe",
        )
    ]


def test_labeled_pipe_form():
    """stormgiants / toee: labeled pipe fields, no list prefix."""
    text = (
        "### Vardis\n"
        "**Class/Level:** Cleric 13 (Light Domain) | **Species:** Wood Elf | "
        "**Player:** Wade Brown\n"
    )
    assert parse_party_md(text) == [
        PartyEntry(
            name="Vardis",
            class_info="Wood Elf Cleric 13 (Light Domain)",
            player="Wade Brown",
        )
    ]


def test_obelisk_list_prefix_form():
    """obelisk: labeled pipe fields, `- ` list marker."""
    text = (
        "### Zenvon Foreput\n"
        "- **Class/Level:** Rogue 2 | **Species:** Halfling | **Player:** Nikhil Reddy\n"
    )
    assert parse_party_md(text) == [
        PartyEntry(
            name="Zenvon Foreput", class_info="Halfling Rogue 2", player="Nikhil Reddy"
        )
    ]


# ── Edge cases ────────────────────────────────────────────────────────────────


def test_no_heading_yields_empty_list():
    text = "Just some prose, no heading at all.\n**Bold text** too.\n"
    assert parse_party_md(text) == []


def test_heading_with_unparseable_body_is_skipped():
    text = "### Some NPC\n**Notable relationships:** Close ally of the party.\n"
    assert parse_party_md(text) == []


def test_one_shot_rule_ignores_a_later_bold_line():
    """issue #245: once a section's first bold-opening line has been consumed
    (successfully or not), the scan must not keep looking within that section
    — a `**Candidate Arc Score Events…**` line 30 lines below the heading must
    not be picked up as if it belonged to it."""
    text = (
        "## Brewbarry\n\n"
        "**Barbarian 6 (Path of the Giant) | Goliath | Player: Stephane Boudreau**\n\n"
        + "Filler line about unrelated party lore.\n" * 30
        + "\n**Candidate Arc Score Events — Thistle's Echo Score (0–30)**\n"
    )
    entries = parse_party_md(text)
    assert entries == [
        PartyEntry(
            name="Brewbarry",
            class_info="Goliath Barbarian 6 (Path of the Giant)",
            player="Stephane Boudreau",
        )
    ]
    assert not any("Candidate Arc Score" in e.class_info for e in entries)
