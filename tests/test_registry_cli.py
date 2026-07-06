"""Tests for registry.py — the entity registry write-side CLI, and for
campaignlib.registry's serialization helpers (dump_registry/save_registry).

Covers: init/add/project subcommands, the fuzzy typo guard on add (near-miss
prompt + --yes bypass), the aliases.json / entity_inventory.md projections
against their REAL consumers (synthesise_world_state.load_aliases,
spell_canon.inventory_tokens), and the save/load round trip.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import registry  # noqa: E402
from campaignlib.registry import (  # noqa: E402
    Entity,
    Registry,
    dump_registry,
    load_registry,
    save_registry,
)
from synthesise_world_state import load_aliases  # noqa: E402
from spell_canon import inventory_tokens  # noqa: E402


# ── init ─────────────────────────────────────────────────────────────────────

def test_init_creates_skeleton(tmp_path):
    campaign_dir = tmp_path / "my-campaign"
    campaign_dir.mkdir()

    rc = registry.main(["init", str(campaign_dir)])
    assert rc == 0

    path = campaign_dir / "docs" / "entity_registry.yaml"
    assert path.is_file()

    reg = load_registry(path)
    assert reg.version == 1
    assert reg.campaign == "my-campaign"
    assert reg.entities == []


def test_init_with_explicit_campaign_name(tmp_path):
    campaign_dir = tmp_path / "some-dir"
    campaign_dir.mkdir()

    rc = registry.main(["init", str(campaign_dir), "--campaign", "out-of-the-abyss"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.campaign == "out-of-the-abyss"


def test_init_refuses_if_exists(tmp_path):
    campaign_dir = tmp_path / "my-campaign"
    campaign_dir.mkdir()

    assert registry.main(["init", str(campaign_dir)]) == 0
    rc = registry.main(["init", str(campaign_dir)])
    assert rc == 1


# ── add ──────────────────────────────────────────────────────────────────────

def _init(tmp_path, campaign="test-campaign") -> Path:
    campaign_dir = tmp_path / campaign
    campaign_dir.mkdir()
    assert registry.main(["init", str(campaign_dir)]) == 0
    return campaign_dir


def test_add_brand_new_entity_no_prompt(tmp_path, monkeypatch):
    campaign_dir = _init(tmp_path)

    def _no_input(*a):
        raise AssertionError("input() should not be called for a non-near-miss add")

    monkeypatch.setattr("builtins.input", _no_input)

    rc = registry.main([
        "add", str(campaign_dir),
        "--name", "Ilvara Mizzrym",
        "--type", "npc",
        "--aliases", "Ilvara",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Ilvara Mizzrym"
    assert reg.entities[0].aliases == ["Ilvara"]


def test_add_yes_on_near_miss_adds_as_new(tmp_path, monkeypatch):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    def _no_input(*a):
        raise AssertionError("--yes must skip the prompt")

    monkeypatch.setattr("builtins.input", _no_input)

    # Near-miss (typo) of "Ilvara Mizzrym", but --yes bypasses the prompt.
    rc = registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizrym", "--type", "npc", "--yes",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 2
    names = {e.name for e in reg.entities}
    assert names == {"Ilvara Mizzrym", "Ilvara Mizrym"}


def test_add_interactive_near_miss_choice_1_adds_alias(tmp_path, monkeypatch):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    monkeypatch.setattr("builtins.input", lambda *a: "1")

    rc = registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizrym", "--type", "npc",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    # No new entity was created; the near-miss became an alias of the existing one.
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Ilvara Mizzrym"
    assert "Ilvara Mizrym" in reg.entities[0].aliases


def test_add_interactive_choice_3_aborts_unchanged(tmp_path, monkeypatch):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    path = campaign_dir / "docs" / "entity_registry.yaml"
    before = path.read_text(encoding="utf-8")

    monkeypatch.setattr("builtins.input", lambda *a: "3")

    rc = registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizrym", "--type", "npc",
    ])
    assert rc == 1

    after = path.read_text(encoding="utf-8")
    assert before == after


def test_add_exact_collision_refuses(tmp_path, monkeypatch):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    def _no_input(*a):
        raise AssertionError("exact collision must be refused before any prompt")

    monkeypatch.setattr("builtins.input", _no_input)

    rc = registry.main([
        "add", str(campaign_dir), "--name", "ILVARA MIZZRYM", "--type", "npc",
    ])
    assert rc == 1

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1


def test_add_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()

    rc = registry.main([
        "add", str(campaign_dir), "--name", "Someone", "--type", "npc",
    ])
    assert rc == 1


# ── project ──────────────────────────────────────────────────────────────────

def test_project_writes_aliases_and_inventory(tmp_path):
    campaign_dir = _init(tmp_path, campaign="out-of-the-abyss")
    assert registry.main([
        "add", str(campaign_dir),
        "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara", "Mistress Ilvara",
        "--note", "senior drow priestess",
    ]) == 0
    assert registry.main([
        "add", str(campaign_dir), "--name", "Gracklstugh", "--type", "location",
    ]) == 0

    rc = registry.main(["project", str(campaign_dir)])
    assert rc == 0

    docs = campaign_dir / "docs"
    reg = load_registry(docs / "entity_registry.yaml")

    aliases_path = docs / "aliases.json"
    raw = json.loads(aliases_path.read_text(encoding="utf-8"))
    assert raw == reg.canonical_to_aliases()

    loaded = load_aliases(aliases_path)
    assert loaded == reg.alias_to_canonical()

    inventory_path = docs / "entity_inventory.md"
    md = inventory_path.read_text(encoding="utf-8")
    assert md.startswith("<!-- GENERATED from docs/entity_registry.yaml")

    tokens = inventory_tokens(inventory_path, min_len=3)
    assert tokens["ilvara"] == "Ilvara"
    assert tokens["mizzrym"] == "Mizzrym"
    assert tokens["gracklstugh"] == "Gracklstugh"


def test_project_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()

    rc = registry.main(["project", str(campaign_dir)])
    assert rc == 1


# ── serialization round trip ─────────────────────────────────────────────────

def test_dump_and_load_round_trip(tmp_path):
    reg = Registry(
        version=1,
        campaign="out-of-the-abyss",
        entities=[
            Entity(
                name="Ilvara Mizzrym",
                type="npc",
                aliases=["Ilvara", "Mistress Ilvara"],
                provenance="module",
                source="OotA",
                scope="persistent",
                note="senior drow priestess",
            ),
            Entity(name="Adabra Gwynn", type="npc"),
            Entity(name="Gracklstugh", type="location", scope="chapter-3"),
        ],
        distinct=[["Topsy", "Turvy"]],
        rejected_aliases=[["Shoor", "Stool"]],
    )

    path = tmp_path / "entity_registry.yaml"
    save_registry(reg, path)
    loaded = load_registry(path)

    assert loaded.version == reg.version
    assert loaded.campaign == reg.campaign
    assert loaded.entities == reg.entities
    assert loaded.distinct == reg.distinct
    assert loaded.rejected_aliases == reg.rejected_aliases


def test_dump_preserves_field_order(tmp_path):
    reg = Registry(
        version=1,
        campaign="c",
        entities=[
            Entity(
                name="Ilvara Mizzrym",
                type="npc",
                aliases=["Ilvara"],
                provenance="module",
                source="OotA",
                scope="chapter-3",
                note="senior drow priestess",
            ),
        ],
    )
    text = dump_registry(reg)
    assert (
        text.index("name:")
        < text.index("type:")
        < text.index("aliases:")
        < text.index("provenance:")
        < text.index("source:")
        < text.index("scope:")
        < text.index("note:")
    )


def test_dump_omits_default_scope_and_round_trips_to_persistent(tmp_path):
    reg = Registry(
        version=1,
        campaign="c",
        entities=[Entity(name="Someone", type="npc", scope="persistent")],
    )
    text = dump_registry(reg)
    assert "scope" not in text

    path = tmp_path / "entity_registry.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_registry(path)
    assert loaded.entities[0].scope == "persistent"


def test_dump_omits_none_and_empty_fields(tmp_path):
    reg = Registry(version=1, campaign=None, entities=[Entity(name="Bare", type="npc")])
    text = dump_registry(reg)
    assert "aliases" not in text
    assert "provenance" not in text
    assert "source" not in text
    assert "note" not in text
    assert "distinct" not in text
    assert "rejected_aliases" not in text

    path = tmp_path / "entity_registry.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_registry(path)
    assert loaded.entities[0] == Entity(name="Bare", type="npc")
