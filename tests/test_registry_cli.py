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

from entity_registry import registry  # noqa: E402
from campaignlib.registry import (  # noqa: E402
    Entity,
    Registry,
    dump_registry,
    load_registry,
    save_registry,
)
from pipelines.ensemble.synthesise_world_state import load_aliases  # noqa: E402
from entity_registry.spell_canon import inventory_tokens  # noqa: E402


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


# ── alias ────────────────────────────────────────────────────────────────────

def test_alias_attach_by_canonical_name(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    rc = registry.main(["alias", str(campaign_dir), "--to", "Ilvara Mizzrym", "Ilvarra"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert "Ilvarra" in reg.entities[0].aliases
    assert reg.alias_to_canonical()["Ilvarra"] == "Ilvara Mizzrym"


def test_alias_attach_by_existing_alias(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara",
    ]) == 0

    # --to targets an existing ALIAS, not the canonical spelling.
    rc = registry.main(["alias", str(campaign_dir), "--to", "Ilvara", "Mistress Ilvara"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Ilvara Mizzrym"
    assert set(reg.entities[0].aliases) == {"Ilvara", "Mistress Ilvara"}


def test_alias_attach_multiple_variants_one_call(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    rc = registry.main([
        "alias", str(campaign_dir), "--to", "Ilvara Mizzrym",
        "Ilvarra", "Mistress Ilvara", "Ilvara",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert set(reg.entities[0].aliases) == {"Ilvarra", "Mistress Ilvara", "Ilvara"}


def test_alias_to_matches_nothing_errors_and_writes_nothing(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0

    path = campaign_dir / "docs" / "entity_registry.yaml"
    before = path.read_text(encoding="utf-8")

    rc = registry.main(["alias", str(campaign_dir), "--to", "Nobody Here", "Whoever"])
    assert rc == 1

    after = path.read_text(encoding="utf-8")
    assert before == after


def test_alias_variant_owned_by_different_entity_is_atomic(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0
    assert registry.main([
        "add", str(campaign_dir), "--name", "Asha", "--type", "npc",
    ]) == 0

    path = campaign_dir / "docs" / "entity_registry.yaml"
    before = path.read_text(encoding="utf-8")

    # "Brand New" would be a valid new alias, but "Asha" already belongs to a
    # different entity — the whole call must fail and write nothing, even
    # though "Brand New" alone would have been fine.
    rc = registry.main([
        "alias", str(campaign_dir), "--to", "Ilvara Mizzrym", "Brand New", "Asha",
    ])
    assert rc == 1

    after = path.read_text(encoding="utf-8")
    assert before == after

    reg = load_registry(path)
    assert reg.entities[0].aliases == []


def test_alias_already_attached_is_idempotent(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara",
    ]) == 0

    rc = registry.main(["alias", str(campaign_dir), "--to", "Ilvara Mizzrym", "Ilvara"])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.entities[0].aliases == ["Ilvara"]  # no duplicate


def test_alias_round_trip_still_validates(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
    ]) == 0
    assert registry.main([
        "alias", str(campaign_dir), "--to", "Ilvara Mizzrym", "Ilvarra",
    ]) == 0

    # load_registry calls validate() internally; a broken registry would raise.
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.entities[0].name == "Ilvara Mizzrym"


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


# ── merge ──────────────────────────────────────────────────────────────────
#
# `merge` folds one or more EXISTING entities into a target (the positive
# counterpart to mark-distinct). Anti-merge guards win; target wins on a type
# mismatch; the call is atomic (all-or-nothing) and re-validates.

def _seed_two(tmp_path, a="Plinki", b="Pliinki", atype="npc", btype="npc"):
    """Two near-miss spellings registered as SEPARATE entities (via --yes)."""
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", a, "--type", atype, "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", b, "--type", btype, "--yes"]) == 0
    return campaign_dir


def test_merge_folds_other_into_target(tmp_path):
    campaign_dir = _seed_two(tmp_path)
    assert registry.main(["merge", str(campaign_dir), "--into", "Plinki", "Pliinki"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Plinki"
    assert "Pliinki" in reg.entities[0].aliases
    assert reg.alias_to_canonical()["Pliinki"] == "Plinki"


def test_merge_carries_others_aliases(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", "Jadgar", "--type", "npc", "--yes"]) == 0
    assert registry.main([
        "add", str(campaign_dir), "--name", "Burrow Warden Jadger", "--type", "npc",
        "--aliases", "Jadger", "Uth-Jadgar", "--yes",
    ]) == 0
    assert registry.main(["merge", str(campaign_dir), "--into", "Jadgar", "Burrow Warden Jadger"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Jadgar"
    assert set(reg.entities[0].aliases) == {"Burrow Warden Jadger", "Jadger", "Uth-Jadgar"}


def test_merge_resolves_into_and_other_by_alias(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Nym Duskryn", "--type", "npc",
        "--aliases", "Duskryn", "--yes",
    ]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Nym", "--type", "npc", "--yes"]) == 0
    # --into targets an ALIAS of the survivor; other by its canonical name.
    assert registry.main(["merge", str(campaign_dir), "--into", "Duskryn", "Nym"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].name == "Nym Duskryn"
    assert "Nym" in reg.entities[0].aliases


def test_merge_multiple_others_one_call(tmp_path):
    campaign_dir = _init(tmp_path)
    for n in ("Jadgar", "Jadger", "Uth Jadgar"):
        assert registry.main(["add", str(campaign_dir), "--name", n, "--type", "npc", "--yes"]) == 0
    assert registry.main(["merge", str(campaign_dir), "--into", "Jadgar", "Jadger", "Uth Jadgar"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert set(reg.entities[0].aliases) == {"Jadger", "Uth Jadgar"}


def test_merge_missing_into_errors_and_writes_nothing(tmp_path):
    campaign_dir = _seed_two(tmp_path)
    assert registry.main(["merge", str(campaign_dir), "--into", "Nobody Here", "Plinki"]) == 1
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 2  # unchanged


def test_merge_one_missing_other_is_atomic(tmp_path):
    campaign_dir = _seed_two(tmp_path)
    # The 2nd 'other' does not exist → the whole call refuses; nothing folded.
    assert registry.main(["merge", str(campaign_dir), "--into", "Plinki", "Pliinki", "Ghost"]) == 1
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 2
    plinki = next(e for e in reg.entities if e.name == "Plinki")
    assert plinki.aliases == []  # Pliinki was NOT folded


def test_merge_refuses_distinct_pair(tmp_path):
    campaign_dir = _seed_two(tmp_path, a="Entemoch", b="Entomoch")
    assert registry.main(["mark-distinct", str(campaign_dir), "Entemoch", "Entomoch"]) == 0
    assert registry.main(["merge", str(campaign_dir), "--into", "Entemoch", "Entomoch"]) == 1
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 2  # guard held; nothing merged


def test_merge_refuses_rejected_group(tmp_path):
    campaign_dir = _seed_two(tmp_path, a="Circle of Sowers", b="Circle of Sporers")
    assert registry.main([
        "mark-rejected", str(campaign_dir), "Circle of Sowers", "Circle of Sporers",
    ]) == 0
    assert registry.main([
        "merge", str(campaign_dir), "--into", "Circle of Sowers", "Circle of Sporers",
    ]) == 1
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 2


def test_merge_type_mismatch_target_wins_with_warning(tmp_path, capsys):
    campaign_dir = _seed_two(tmp_path, a="Araumycos", b="Aramycos", atype="npc", btype="location")
    assert registry.main(["merge", str(campaign_dir), "--into", "Araumycos", "Aramycos"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].type == "npc"  # target's type wins
    err = capsys.readouterr().err
    assert "warning" in err.lower()
    assert "location" in err


def test_merge_folds_provenance_and_note_when_target_blank(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", "Plinki", "--type", "npc", "--yes"]) == 0
    assert registry.main([
        "add", str(campaign_dir), "--name", "Pliinki", "--type", "npc",
        "--provenance", "module", "--note", "mad derro savant", "--yes",
    ]) == 0
    assert registry.main(["merge", str(campaign_dir), "--into", "Plinki", "Pliinki"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.entities[0].provenance == "module"
    assert reg.entities[0].note == "mad derro savant"


def test_merge_other_already_part_of_target_is_noop(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Plinki", "--type", "npc", "--aliases", "Plink", "--yes",
    ]) == 0
    # 'Plink' already resolves to Plinki → nothing to do, unchanged, rc 0.
    assert registry.main(["merge", str(campaign_dir), "--into", "Plinki", "Plink"]) == 0
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert len(reg.entities) == 1
    assert reg.entities[0].aliases == ["Plink"]


def test_merge_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    assert registry.main(["merge", str(campaign_dir), "--into", "X", "Y"]) == 1


def test_merge_round_trip_still_validates(tmp_path):
    campaign_dir = _seed_two(tmp_path)
    assert registry.main(["merge", str(campaign_dir), "--into", "Plinki", "Pliinki"]) == 0
    # load_registry runs validate(); a colliding/broken registry would raise here.
    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.alias_to_canonical()["Pliinki"] == "Plinki"
