"""Tests for fivetools_copy._copy resolver.

Mirrors the cases the canonical 5e data actually exercises. Heavy on
``replaceTxt`` (OotA's pattern) and on the bestiary-specific mods that
templates rely on. Cross-file dependency loading is exercised against
a tiny on-disk fixture tree.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.content_ingest.fivetools_copy import (
    _CopyResolver,
    _path_get,
    _path_set,
    load_dependency_pool,
    resolve_copies,
)


def _knight() -> dict:
    return {
        "name": "Knight",
        "source": "MM",
        "size": ["M"],
        "type": "humanoid",
        "alignment": ["L", "G"],
        "ac": [{"ac": 18, "from": ["plate"]}],
        "hp": {"average": 52, "formula": "8d8 + 16"},
        "speed": {"walk": 30},
        "str": 16, "dex": 11, "con": 14, "int": 11, "wis": 11, "cha": 15,
        "save": {"con": "+4", "wis": "+2"},
        "senses": ["passive Perception 10"],
        "passive": 10,
        "languages": ["any one language (usually Common)"],
        "cr": "3",
        "trait": [
            {"name": "Brave", "entries": ["The knight has advantage on saving throws against being frightened."]},
        ],
        "action": [
            {"name": "Multiattack", "entries": ["The knight makes two melee attacks."]},
            {"name": "Greatsword", "entries": ["Melee Weapon Attack: +5 to hit."]},
        ],
        "reaction": [
            {"name": "Parry", "entries": ["The knight adds 2 to its AC."]},
        ],
    }


# ── Field merge ────────────────────────────────────────────────────────────


class TestParentFieldMerge:
    def test_parent_fills_missing_keys(self):
        child = {
            "name": "Aljanor",
            "source": "OotA",
            "_copy": {"name": "Knight", "source": "MM"},
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert child["str"] == 16
        assert child["cr"] == "3"
        assert "_copy" not in child
        assert child["_isCopy"] is True

    def test_child_value_wins(self):
        child = {
            "name": "Aljanor",
            "source": "OotA",
            "cr": "5",  # override parent's "3"
            "_copy": {"name": "Knight", "source": "MM"},
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert child["cr"] == "5"

    def test_explicit_null_suppresses_parent(self):
        child = {
            "name": "Aljanor",
            "source": "OotA",
            "save": None,  # null → drop
            "_copy": {"name": "Knight", "source": "MM"},
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert "save" not in child

    def test_missing_parent_warns_and_drops_copy(self):
        child = {
            "name": "Lonely",
            "source": "X",
            "_copy": {"name": "NoSuchParent", "source": "Z"},
        }
        warnings = []
        resolve_copies(
            [child], prop="monster", extra_pool=[], on_warning=warnings.append
        )
        assert "_copy" not in child
        assert any("missing" in w for w in warnings)


# ── Mod modes ──────────────────────────────────────────────────────────────


class TestReplaceTxt:
    def test_replaces_in_action_entries_via_star_prop(self):
        child = {
            "name": "Aljanor Keenblade",
            "source": "OotA",
            "_copy": {
                "name": "Knight",
                "source": "MM",
                "_mod": {
                    "*": {
                        "mode": "replaceTxt",
                        "replace": "the knight",
                        "with": "Aljanor",
                        "flags": "i",
                    }
                },
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        actions = child["action"]
        # "The knight makes two…" → "Aljanor makes two…"
        assert "Aljanor makes two" in actions[0]["entries"][0]
        assert "the knight" not in " ".join(
            e for a in actions for e in a["entries"]
        ).lower()

    def test_skips_tag_segments(self):
        # @hit segment must remain literal even though replace might match.
        knight = _knight()
        knight["action"][1]["entries"] = ["{@hit 5} {@damage 1d8} cut"]
        child = {
            "name": "X",
            "source": "Y",
            "_copy": {
                "name": "Knight",
                "source": "MM",
                "_mod": {
                    "*": {"mode": "replaceTxt", "replace": "cut", "with": "slash"}
                },
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[knight])
        out = child["action"][1]["entries"][0]
        assert "slash" in out
        assert "{@hit 5}" in out
        assert "{@damage 1d8}" in out


class TestArrayMods:
    def test_append_arr(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"trait": {"mode": "appendArr", "items": {"name": "New", "entries": ["..."]}}},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        names = [t["name"] for t in child["trait"]]
        assert names == ["Brave", "New"]

    def test_prepend_arr(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"trait": {"mode": "prependArr", "items": {"name": "First", "entries": ["..."]}}},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        names = [t["name"] for t in child["trait"]]
        assert names == ["First", "Brave"]

    def test_replace_arr_by_name(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {
                    "action": {
                        "mode": "replaceArr",
                        "replace": "Greatsword",
                        "items": {"name": "Longsword", "entries": ["..."]},
                    }
                },
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        names = [a["name"] for a in child["action"]]
        assert "Longsword" in names
        assert "Greatsword" not in names

    def test_replace_or_append_falls_back_to_append(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {
                    "action": {
                        "mode": "replaceOrAppendArr",
                        "replace": "Nonexistent",
                        "items": {"name": "Bow", "entries": ["..."]},
                    }
                },
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        names = [a["name"] for a in child["action"]]
        assert "Bow" in names

    def test_remove_arr_by_names(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"action": {"mode": "removeArr", "names": ["Greatsword"]}},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        names = [a["name"] for a in child["action"]]
        assert "Greatsword" not in names
        assert "Multiattack" in names


class TestBestiarySpecificMods:
    def test_add_senses(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"senses": {"mode": "addSenses", "senses": [{"type": "darkvision", "range": 60}]}},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert any("darkvision 60" in s for s in child["senses"])

    def test_add_skills(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"skill": {"mode": "addSkills", "perception": "+4"}},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert child["skill"]["perception"] == "+4"

    def test_remove_via_string_mod(self):
        child = {
            "name": "X", "source": "Y",
            "_copy": {
                "name": "Knight", "source": "MM",
                "_mod": {"reaction": "remove"},
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert "reaction" not in child


# ── Cross-file dependency loading ──────────────────────────────────────────


class TestCrossFileDependencies:
    def test_loads_pool_from_dep_index(self, tmp_path: Path):
        data = tmp_path / "data"
        bestiary = data / "bestiary"
        bestiary.mkdir(parents=True)
        # Source file (parent).
        (bestiary / "bestiary-mm.json").write_text(json.dumps({
            "_meta": {},
            "monster": [_knight()],
        }))
        # Index.
        (bestiary / "index.json").write_text(json.dumps({"MM": "bestiary-mm.json"}))

        # Child doc declares dep on MM.
        child_doc = {
            "_meta": {"dependencies": {"monster": ["MM"]}},
            "monster": [{
                "name": "Aljanor",
                "source": "OotA",
                "_copy": {"name": "Knight", "source": "MM"},
            }],
        }
        pool = load_dependency_pool(child_doc, prop="monster", data_root=data)
        assert any(p["name"] == "Knight" for p in pool)

    def test_missing_dep_index_returns_empty_with_warning(self, tmp_path: Path):
        warnings = []
        doc = {"_meta": {"dependencies": {"monster": ["MM"]}}}
        pool = load_dependency_pool(
            doc, prop="monster", data_root=tmp_path / "nonexistent",
            on_warning=warnings.append,
        )
        assert pool == []
        assert warnings


# ── Path helpers ──────────────────────────────────────────────────────────


class TestPathHelpers:
    def test_get_dotted(self):
        assert _path_get({"a": {"b": 1}}, ["a", "b"]) == 1
        assert _path_get({"a": {"b": 1}}, ["a", "missing"]) is None

    def test_set_creates_intermediate_dicts(self):
        d = {}
        _path_set(d, ["a", "b", "c"], 42)
        assert d == {"a": {"b": {"c": 42}}}


# ── Integration / regression: an OotA-shaped child ────────────────────────


class TestEndToEndAljanorShape:
    def test_replace_txt_star_renames_creature_in_actions(self):
        # The exact shape from bestiary-oota.json's "Aljanor Keenblade".
        child = {
            "name": "Aljanor Keenblade",
            "source": "OotA",
            "_copy": {
                "name": "Knight",
                "source": "MM",
                "_mod": {
                    "*": {
                        "mode": "replaceTxt",
                        "replace": "the knight",
                        "with": "Aljanor",
                        "flags": "i",
                    }
                },
            },
        }
        resolve_copies([child], prop="monster", extra_pool=[_knight()])
        assert child["name"] == "Aljanor Keenblade"
        assert child["cr"] == "3"
        # Every "the knight" reference in entries should have flipped.
        joined = json.dumps(child).lower()
        assert "the knight" not in joined
