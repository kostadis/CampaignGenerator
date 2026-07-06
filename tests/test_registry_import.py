"""Tests for the import-inventory / import-dedup subcommands in registry.py,
plus the shared _merge_entity hardening (save_registry never persists a
broken registry; second-writer alias conflicts are skipped and reported).

Fixtures below faithfully copy the real on-disk shapes of a module inventory
markdown file and a .dedup_state.json produced by dossier dedup review.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import registry  # noqa: E402
from campaignlib.registry import Entity, Registry, load_registry, save_registry  # noqa: E402


def _init(tmp_path, campaign="test-campaign") -> Path:
    campaign_dir = tmp_path / campaign
    campaign_dir.mkdir()
    assert registry.main(["init", str(campaign_dir)]) == 0
    return campaign_dir


INVENTORY_MD = """\
## NPCs
- **Ilvara Mizzrym** / **Ilvara** — senior drow priestess
- **Yeenoghu** — demon lord
## Deities
- **Lolth** / **Spider Queen** — drow goddess
## Outside Candlekeep
- **Somewhere** — a place
"""


# ── import-inventory ─────────────────────────────────────────────────────────

def test_import_inventory_npcs_and_deities(tmp_path):
    campaign_dir = _init(tmp_path)
    md_path = tmp_path / "inventory.md"
    md_path.write_text(INVENTORY_MD, encoding="utf-8")

    rc = registry.main(["import-inventory", str(campaign_dir), str(md_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}

    assert by_name["Ilvara Mizzrym"].type == "npc"
    assert by_name["Ilvara Mizzrym"].aliases == ["Ilvara"]
    assert by_name["Ilvara Mizzrym"].note == "senior drow priestess"

    assert by_name["Yeenoghu"].type == "npc"
    assert by_name["Yeenoghu"].note == "demon lord"

    assert by_name["Lolth"].type == "deity"
    assert by_name["Lolth"].aliases == ["Spider Queen"]
    assert by_name["Lolth"].note == "drow goddess"


def test_import_inventory_unmapped_heading_skipped_with_warning(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    md_path = tmp_path / "inventory.md"
    md_path.write_text(INVENTORY_MD, encoding="utf-8")

    rc = registry.main(["import-inventory", str(campaign_dir), str(md_path)])
    assert rc == 0

    err = capsys.readouterr().err
    assert "Outside Candlekeep" in err
    assert "WARNING" in err

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    names = {e.name for e in reg.entities}
    assert "Somewhere" not in names


def test_import_inventory_heading_type_override_imports_skipped_section(tmp_path):
    campaign_dir = _init(tmp_path)
    md_path = tmp_path / "inventory.md"
    md_path.write_text(INVENTORY_MD, encoding="utf-8")

    rc = registry.main([
        "import-inventory", str(campaign_dir), str(md_path),
        "--heading-type", "Outside Candlekeep=location",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert by_name["Somewhere"].type == "location"
    assert by_name["Somewhere"].note == "a place"


def test_import_inventory_provenance_and_source_applied(tmp_path):
    campaign_dir = _init(tmp_path)
    md_path = tmp_path / "inventory.md"
    md_path.write_text(INVENTORY_MD, encoding="utf-8")

    rc = registry.main([
        "import-inventory", str(campaign_dir), str(md_path),
        "--provenance", "module", "--source", "OotA",
    ])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert by_name["Yeenoghu"].provenance == "module"
    assert by_name["Yeenoghu"].source == "OotA"


def test_import_inventory_round_trips_through_real_producer(tmp_path):
    """The real producer (Registry.inventory_markdown, used by `registry.py
    project`) must feed straight back into import-inventory: same dash
    (U+2014), same bold-span/note conventions, same type-heading names."""
    source_dir = _init(tmp_path, campaign="source")
    assert registry.main([
        "add", str(source_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara", "Mistress Ilvara", "--note", "senior drow priestess",
    ]) == 0
    assert registry.main([
        "add", str(source_dir), "--name", "Gracklstugh", "--type", "location",
    ]) == 0
    assert registry.main(["project", str(source_dir)]) == 0

    inventory_md = source_dir / "docs" / "entity_inventory.md"
    assert inventory_md.is_file()

    dest_dir = _init(tmp_path, campaign="dest")
    rc = registry.main(["import-inventory", str(dest_dir), str(inventory_md)])
    assert rc == 0

    reg = load_registry(dest_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}

    assert by_name["Ilvara Mizzrym"].type == "npc"
    assert set(by_name["Ilvara Mizzrym"].aliases) == {"Ilvara", "Mistress Ilvara"}
    assert by_name["Ilvara Mizzrym"].note == "senior drow priestess"
    assert by_name["Gracklstugh"].type == "location"


def test_import_inventory_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    md_path = tmp_path / "inventory.md"
    md_path.write_text(INVENTORY_MD, encoding="utf-8")

    rc = registry.main(["import-inventory", str(campaign_dir), str(md_path)])
    assert rc == 1


# ── import-dedup ─────────────────────────────────────────────────────────────

def _dedup_json(tmp_path, data: dict) -> Path:
    p = tmp_path / ".dedup_state.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_import_dedup_normal_cluster(tmp_path):
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [
            {
                "files": ["asha_vandree.md", "asha.md"],
                "canonical": "asha_vandree.md",
                "aliases_recorded": ["First Daughter"],
            }
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert "Asha Vandree" in by_name
    entity = by_name["Asha Vandree"]
    assert entity.type == "npc"
    assert set(entity.aliases) == {"Asha", "First Daughter"}


def test_import_dedup_split_cluster(tmp_path):
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [
            {
                "files": ["topsy.md", "turvy.md", "topsy_and_turvy.md"],
                "canonical": "topsy.md+turvy.md (split)",
                "aliases_recorded": [],
            }
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    names = {e.name for e in reg.entities}
    assert "Topsy" in names
    assert "Turvy" in names

    pairs = [set(p) for p in reg.distinct]
    assert {"Topsy", "Turvy"} in pairs


def test_import_dedup_rejected_cluster(tmp_path):
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_rejected": [
            {
                "files": ["shoor.md", "stool.md"],
                "reason": "different races — Shoor is duergar, Stool is myconid sprout",
            }
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    groups = [set(g) for g in reg.rejected_aliases]
    assert {"Shoor", "Stool"} in groups


def test_import_dedup_absent_pc_files_skipped_does_not_crash(tmp_path):
    campaign_dir = _init(tmp_path)
    # Real .dedup_state.json shape: no pc_files_skipped key at all, plus
    # some ignored metadata keys.
    data = {
        "clusters_confirmed": [],
        "clusters_rejected": [],
        "clusters_deferred": [{"files": ["maybe.md"], "reason": "unsure"}],
        "some_metadata_key": "whatever",
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.entities == []


def test_import_dedup_pc_files_skipped_present_is_ignored(tmp_path):
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [],
        "pc_files_skipped": ["some_pc.md"],
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    names = {e.name for e in reg.entities}
    assert "Some Pc" not in names
    assert names == set()


def test_import_dedup_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    json_path = _dedup_json(tmp_path, {"clusters_confirmed": []})

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 1


def test_import_dedup_3way_split_synthetic(tmp_path):
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [
            {
                "files": ["a.md", "b.md", "c.md"],
                "canonical": "a.md+b.md+c.md (split)",
                "aliases_recorded": [],
            }
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    rc = registry.main(["import-dedup", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    names = {e.name for e in reg.entities}
    assert {"A", "B", "C"} <= names

    pairs = [set(p) for p in reg.distinct]
    assert {"A", "B"} in pairs
    assert {"A", "C"} in pairs
    assert {"B", "C"} in pairs
    assert len(pairs) == 3


# ── hardening ────────────────────────────────────────────────────────────────

def test_save_registry_rejects_duplicate_name_and_writes_nothing(tmp_path):
    reg = Registry(
        version=1,
        campaign="c",
        entities=[
            Entity(name="Harbin Wester", type="npc"),
            Entity(name="HARBIN WESTER", type="npc"),
        ],
    )
    path = tmp_path / "entity_registry.yaml"
    assert not path.exists()

    with pytest.raises(ValueError):
        save_registry(reg, path)

    assert not path.exists()


def test_save_registry_rejects_and_leaves_existing_file_unchanged(tmp_path):
    reg = Registry(version=1, campaign="c", entities=[Entity(name="Someone", type="npc")])
    path = tmp_path / "entity_registry.yaml"
    save_registry(reg, path)
    before = path.read_text(encoding="utf-8")

    broken = Registry(
        version=1,
        campaign="c",
        entities=[
            Entity(name="Someone", type="npc"),
            Entity(name="someone", type="npc"),
        ],
    )
    with pytest.raises(ValueError):
        save_registry(broken, path)

    after = path.read_text(encoding="utf-8")
    assert before == after


# ── merge conflicts stay valid ───────────────────────────────────────────────

def test_merge_conflict_same_alias_different_typed_sections(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    md = """\
## NPCs
- **Someone** / **SharedAlias**
## Locations
- **Elsewhere** / **SharedAlias**
"""
    md_path = tmp_path / "inventory.md"
    md_path.write_text(md, encoding="utf-8")

    rc = registry.main(["import-inventory", str(campaign_dir), str(md_path)])
    assert rc == 0

    err = capsys.readouterr().err
    assert "conflict" in err
    assert "SharedAlias" in err

    reg_path = campaign_dir / "docs" / "entity_registry.yaml"
    reg = load_registry(reg_path)  # raises if invalid — this is the assertion

    by_name = {e.name: e for e in reg.entities}
    assert by_name["Someone"].aliases == ["SharedAlias"]
    assert by_name["Elsewhere"].aliases == []
