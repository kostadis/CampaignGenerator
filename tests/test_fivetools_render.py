"""Tests for fivetools_render — verbatim-ish text drawer rendering."""

from __future__ import annotations

import pytest

from pipelines.content_ingest.fivetools_render import (
    render_class_feature,
    render_entity,
    render_entries_block,
    render_item,
    render_monster,
    render_spell,
    render_subclass,
    strip_tags,
)


# ── Tag stripping ──────────────────────────────────────────────────────────


class TestStripTags:
    def test_returns_unchanged_when_no_tags(self):
        assert strip_tags("plain text") == "plain text"

    def test_dc_keeps_label(self):
        assert strip_tags("must make a {@dc 14} save") == "must make a DC 14 save"

    def test_hit_prefixes_plus(self):
        assert strip_tags("attack {@hit 5}") == "attack +5"
        assert strip_tags("attack {@hit -2}") == "attack -2"

    def test_named_pipe_uses_display(self):
        assert strip_tags("cast {@spell fireball|XPHB|fireball}") == "cast fireball"

    def test_named_pipe_no_display_uses_name(self):
        assert strip_tags("cast {@spell fireball|XPHB}") == "cast fireball"

    def test_italic_strips_braces(self):
        assert strip_tags("an {@i italic} word") == "an italic word"

    def test_atk_expands(self):
        assert strip_tags("{@atk mw}") == "Melee Weapon Attack:"
        assert strip_tags("{@atk rs}") == "Ranged Spell Attack:"

    def test_scaledamage_uses_first_segment(self):
        # "8d6|3-9|1d6" → base damage is 8d6.
        assert strip_tags("deal {@scaledamage 8d6|3-9|1d6}") == "deal 8d6"

    def test_repeated_substitution_handles_neighboring_tags(self):
        out = strip_tags("{@dc 15} save vs {@damage 2d6} fire")
        assert out == "DC 15 save vs 2d6 fire"


# ── Entries block walker ─────────────────────────────────────────────────


class TestRenderEntriesBlock:
    def test_string_passthrough(self):
        assert render_entries_block(["plain"]) == "plain"

    def test_named_entries_emit_bold_inline(self):
        block = [{"type": "entries", "name": "Brave",
                  "entries": ["Has advantage on saves."]}]
        out = render_entries_block(block, depth=1)
        assert "**Brave.**" in out
        assert "Has advantage" in out

    def test_top_level_named_entries_get_h2(self):
        block = [{"type": "entries", "name": "Trait",
                  "entries": ["body."]}]
        out = render_entries_block(block, depth=0)
        assert out.startswith("## Trait")

    def test_list_renders_with_dashes(self):
        block = [{"type": "list", "items": ["one", "two", "three"]}]
        out = render_entries_block(block)
        assert "- one" in out
        assert "- two" in out
        assert "- three" in out

    def test_table_renders_markdown(self):
        block = [{"type": "table", "caption": "Loot",
                  "colLabels": ["Roll", "Result"],
                  "rows": [[1, "gold"], [2, "gem"]]}]
        out = render_entries_block(block)
        assert "Loot" in out
        assert "| Roll | Result |" in out
        assert "| 1 | gold |" in out


# ── Monster ────────────────────────────────────────────────────────────────


def _aboleth():
    return {
        "name": "Aboleth", "source": "MM", "page": 13,
        "size": ["L"], "type": "aberration", "alignment": ["L", "E"],
        "ac": [{"ac": 17, "from": ["natural armor"]}],
        "hp": {"average": 135, "formula": "18d10 + 36"},
        "speed": {"walk": 10, "swim": 40},
        "str": 21, "dex": 9, "con": 15, "int": 18, "wis": 15, "cha": 18,
        "save": {"con": "+6", "int": "+8", "wis": "+6"},
        "skill": {"history": "+12", "perception": "+10"},
        "senses": ["darkvision 120 ft."],
        "passive": 20,
        "languages": ["Deep Speech", "telepathy 120 ft."],
        "cr": "10",
        "trait": [
            {"name": "Amphibious", "entries": ["The aboleth can breathe air and water."]},
        ],
        "action": [
            {"name": "Multiattack", "entries": ["The aboleth makes three tentacle attacks."]},
            {"name": "Tentacle", "entries": ["{@atk mw} {@hit 9} to hit. {@h}{@damage 2d6 + 5} bludgeoning."]},
        ],
    }


class TestRenderMonster:
    def test_header_block(self):
        out = render_monster(_aboleth())
        assert out.startswith("# Aboleth")
        assert "Large aberration" in out
        assert "lawful evil" in out
        assert "Source: MM, p. 13" in out

    def test_defenses_block(self):
        out = render_monster(_aboleth())
        assert "**Armor Class** 17 (natural armor)" in out
        assert "**Hit Points** 135 (18d10 + 36)" in out
        assert "**Speed** 10 ft., swim 40 ft." in out

    def test_ability_table(self):
        out = render_monster(_aboleth())
        assert "STR | DEX" in out
        assert "21 (+5)" in out  # str 21 modifier
        assert "9 (-1)" in out   # dex 9 modifier

    def test_saves_skills_senses_languages_cr(self):
        out = render_monster(_aboleth())
        assert "**Saving Throws** Con +6, Int +8, Wis +6" in out
        assert "**Skills** History +12, Perception +10" in out
        assert "darkvision 120 ft." in out
        assert "passive Perception 20" in out
        assert "Deep Speech, telepathy" in out
        assert "**Challenge** 10" in out

    def test_traits_section(self):
        out = render_monster(_aboleth())
        assert "## Traits" in out
        assert "**Amphibious.**" in out

    def test_actions_render_inline_attack_block(self):
        out = render_monster(_aboleth())
        assert "## Actions" in out
        assert "**Multiattack.**" in out
        assert "**Tentacle.**" in out
        # Tag-flattened attack:
        assert "Melee Weapon Attack:" in out
        assert "+9 to hit" in out
        assert "2d6 + 5" in out


# ── Spell ──────────────────────────────────────────────────────────────────


class TestRenderSpell:
    def test_full_spell(self):
        s = {
            "name": "Fireball",
            "source": "PHB", "page": 241,
            "level": 3, "school": "V",
            "time": [{"number": 1, "unit": "action"}],
            "range": {"type": "point", "distance": {"type": "feet", "amount": 150}},
            "components": {"v": True, "s": True, "m": "a tiny ball of bat guano"},
            "duration": [{"type": "instant"}],
            "entries": ["A bright streak flashes."],
            "entriesHigherLevel": [
                {"type": "entries", "name": "At Higher Levels",
                 "entries": ["damage increases by {@scaledamage 8d6|3-9|1d6}."]}
            ],
        }
        out = render_spell(s)
        assert out.startswith("# Fireball")
        assert "3rd-level Evocation" in out
        assert "**Casting Time:** 1 action" in out
        assert "150 feet" in out
        assert "V, S, M" in out
        assert "Instantaneous" in out
        # entriesHigherLevel header should appear once, not twice.
        assert out.count("At Higher Levels") == 1
        # scaledamage flattens to base damage.
        assert "8d6" in out


# ── Item ───────────────────────────────────────────────────────────────────


class TestRenderItem:
    def test_magic_item(self):
        item = {
            "name": "Bag of Holding",
            "source": "DMG",
            "rarity": "uncommon",
            "wondrous": True,
            "entries": ["This bag has an interior space."],
        }
        out = render_item(item)
        assert out.startswith("# Bag of Holding")
        assert "uncommon" in out
        assert "wondrous item" in out
        assert "interior space" in out


# ── Class feature ─────────────────────────────────────────────────────────


class TestRenderClassFeature:
    def test_renders_with_class_and_level(self):
        cf = {
            "name": "Fighting Style",
            "source": "PHB",
            "className": "Fighter",
            "classSource": "PHB",
            "level": 1,
            "entries": ["You adopt a particular style."],
        }
        out = render_class_feature(cf)
        assert out.startswith("# Fighting Style")
        assert "Fighter feature" in out
        assert "level 1" in out


# ── Dispatcher ────────────────────────────────────────────────────────────


class TestRenderEntity:
    def test_dispatches_monster(self):
        assert render_entity("monster", _aboleth()).startswith("# Aboleth")

    def test_dispatches_unknown_to_generic(self):
        out = render_entity("variantrule", {"name": "Optional Rule",
                                            "entries": ["Use this if..."]})
        assert "Optional Rule" in out
        assert "Use this if" in out
