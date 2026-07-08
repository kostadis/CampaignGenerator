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


def test_import_dedup_rejected_cluster_excludes_confirmed_subpair(tmp_path):
    # The real OOTA bug: a rejected CLUSTER {aliinka, plinki, pliinki} whose
    # reason is "Aliinka is separate; only plinki/pliinki are duplicates" — with
    # a confirmed cluster {plinki, pliinki} — must NOT produce a guard that
    # forbids the confirmed Plinki<->Pliinki merge. It must keep only the real
    # distinction (Aliinka vs the plinki/pliinki entity).
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [
            {"files": ["plinki.md", "pliinki.md"], "canonical": "plinki.md",
             "aliases_recorded": []},
        ],
        "clusters_rejected": [
            {"files": ["aliinka.md", "plinki.md", "pliinki.md"],
             "reason": "Aliinka is a separate NPC; only plinki/pliinki are duplicates"},
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    assert registry.main(["import-dedup", str(campaign_dir), str(json_path)]) == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    groups = [set(g) for g in reg.rejected_aliases]
    # Aliinka kept apart from the (merged) Plinki entity...
    assert {"Aliinka", "Plinki"} in groups
    # ...but NO guard forbids Plinki<->Pliinki (the confirmed duplicate pair).
    assert not any({"Plinki", "Pliinki"} <= g for g in groups)
    # And Plinki really did absorb Pliinki as an alias (the confirmed merge held).
    plinki = next(e for e in reg.entities if e.name == "Plinki")
    assert "Pliinki" in plinki.aliases


def test_import_dedup_rejected_collapses_by_registry_identity(tmp_path):
    # A rejected cluster {ilvara, ilvara_mizzrym, ulnara} where Ilvara and
    # Ilvara Mizzrym are ALREADY one entity in the registry (e.g. aliased by an
    # earlier import-inventory) — even with no confirmed dedup cluster, the
    # guard must collapse them and keep only Ulnara apart.
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara", "--yes",
    ]) == 0
    data = {
        "clusters_rejected": [
            {"files": ["ilvara.md", "ilvara_mizzrym.md", "ulnara.md"],
             "reason": "Ulnara is a separate NPC from Ilvara/Ilvara Mizzrym"},
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    assert registry.main(["import-dedup", str(campaign_dir), str(json_path)]) == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    groups = [set(g) for g in reg.rejected_aliases]
    assert {"Ilvara Mizzrym", "Ulnara"} in groups
    assert not any({"Ilvara", "Ilvara Mizzrym"} <= g for g in groups)


def test_import_dedup_rejected_all_confirmed_adds_no_guard(tmp_path):
    # Degenerate: a rejected cluster whose members ALL collapse to one entity
    # (contradictory / already merged) — no guard is recorded (warned).
    campaign_dir = _init(tmp_path)
    data = {
        "clusters_confirmed": [
            {"files": ["plinki.md", "pliinki.md"], "canonical": "plinki.md",
             "aliases_recorded": []},
        ],
        "clusters_rejected": [
            {"files": ["plinki.md", "pliinki.md"], "reason": "n/a"},
        ],
    }
    json_path = _dedup_json(tmp_path, data)

    assert registry.main(["import-dedup", str(campaign_dir), str(json_path)]) == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    groups = [set(g) for g in reg.rejected_aliases]
    assert not any({"Plinki", "Pliinki"} <= g for g in groups)


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

def _write_dossier(dossier_dir: Path, filename: str, name: str, aliases: "list[str]") -> None:
    alias_lines = "".join(f"  - {a}\n" for a in aliases)
    aliases_block = f"aliases:\n{alias_lines}" if aliases else ""
    (dossier_dir / filename).write_text(
        f"---\nname: {name}\n{aliases_block}---\n\nBody text.\n",
        encoding="utf-8",
    )


# ── import-frontmatter ───────────────────────────────────────────────────────

def test_import_frontmatter_adds_entities_and_aliases(tmp_path):
    campaign_dir = _init(tmp_path)
    dossier_dir = campaign_dir / "docs" / "npcs"
    dossier_dir.mkdir(parents=True)
    _write_dossier(dossier_dir, "asha.md", "Asha Vandree", ["Asha"])
    _write_dossier(dossier_dir, "byrtyn.md", "Byrtyn Fey", [])

    rc = registry.main(["import-frontmatter", str(campaign_dir), str(dossier_dir)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert by_name["Asha Vandree"].type == "npc"
    assert by_name["Asha Vandree"].aliases == ["Asha"]
    assert "Byrtyn Fey" in by_name


def test_import_frontmatter_singleton_dossier_not_in_dedup_cluster_is_added(tmp_path):
    """A singleton dossier no dedup cluster ever grouped still gets registered —
    import-frontmatter fills the gap dedup import leaves behind."""
    campaign_dir = _init(tmp_path)
    dossier_dir = campaign_dir / "docs" / "npcs"
    dossier_dir.mkdir(parents=True)
    _write_dossier(dossier_dir, "hollow_singleton.md", "Hollow Singleton", ["Hollow"])

    rc = registry.main(["import-frontmatter", str(campaign_dir), str(dossier_dir)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert "Hollow Singleton" in by_name
    assert by_name["Hollow Singleton"].aliases == ["Hollow"]


def test_import_frontmatter_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    dossier_dir = tmp_path / "npcs"
    dossier_dir.mkdir()
    rc = registry.main(["import-frontmatter", str(campaign_dir), str(dossier_dir)])
    assert rc == 1


# ── import-alias-decisions ───────────────────────────────────────────────────

def _decisions_json(tmp_path, decisions: "list[dict]", name=".alias_decisions.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps({"decisions": decisions}), encoding="utf-8")
    return p


def test_import_alias_decisions_approved_registered_canonical_enriches(tmp_path):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "House Margaster", "--type", "faction",
    ]) == 0

    decisions = [
        {"candidates": ["House Margaster", "House Maragaster"], "canonical": "House Margaster", "status": "approved"},
    ]
    json_path = _decisions_json(tmp_path, decisions)

    rc = registry.main(["import-alias-decisions", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    by_name = {e.name: e for e in reg.entities}
    assert by_name["House Margaster"].aliases == ["House Maragaster"]
    assert by_name["House Margaster"].type == "faction"


def test_import_alias_decisions_approved_unregistered_canonical_not_created(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    decisions = [
        {"candidates": ["giants", "stone giants"], "canonical": "stone giants", "status": "approved"},
    ]
    json_path = _decisions_json(tmp_path, decisions)

    rc = registry.main(["import-alias-decisions", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    assert reg.entities == []

    err = capsys.readouterr().err
    assert "stone giants" in err
    assert "Unmatched" in err


def test_import_alias_decisions_rejected_group_recorded(tmp_path):
    campaign_dir = _init(tmp_path)
    decisions = [
        {"candidates": ["Cult of Talos", "Talosians", "Talos"], "canonical": None, "status": "rejected"},
    ]
    json_path = _decisions_json(tmp_path, decisions)

    rc = registry.main(["import-alias-decisions", str(campaign_dir), str(json_path)])
    assert rc == 0

    reg = load_registry(campaign_dir / "docs" / "entity_registry.yaml")
    groups = [set(g) for g in reg.rejected_aliases]
    assert {"Cult of Talos", "Talosians", "Talos"} in groups


def test_import_alias_decisions_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    json_path = _decisions_json(tmp_path, [])
    rc = registry.main(["import-alias-decisions", str(campaign_dir), str(json_path)])
    assert rc == 1


def test_import_alias_decisions_tolerates_missing_decisions_key(tmp_path):
    campaign_dir = _init(tmp_path)
    json_path = tmp_path / "empty.json"
    json_path.write_text(json.dumps({}), encoding="utf-8")
    rc = registry.main(["import-alias-decisions", str(campaign_dir), str(json_path)])
    assert rc == 0


# ── check ────────────────────────────────────────────────────────────────────

def test_check_clean_registry_returns_zero(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", "Asha Vandree", "--type", "npc", "--yes"]) == 0

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "0 grouping-drift" in out


def test_check_missing_registry_errors(tmp_path):
    campaign_dir = tmp_path / "no-registry"
    campaign_dir.mkdir()
    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1


def test_check_dedup_grouping_drift_detected(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    # Registry has A and B as SEPARATE entities...
    assert registry.main(["add", str(campaign_dir), "--name", "Asha Vandree", "--type", "npc", "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Shoor", "--type", "npc", "--yes"]) == 0

    # ...but the dedup state file says they were confirmed as ONE cluster.
    npcs_dir = campaign_dir / "docs" / "npcs"
    npcs_dir.mkdir(parents=True)
    dedup_data = {
        "clusters_confirmed": [
            {"files": ["asha_vandree.md", "shoor.md"], "canonical": "asha_vandree.md", "aliases_recorded": []},
        ],
    }
    (npcs_dir / ".dedup_state.json").write_text(json.dumps(dedup_data), encoding="utf-8")

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "dedup groups" in out
    assert "Asha Vandree" in out
    assert "Shoor" in out


def test_check_dedup_grouping_drift_when_entirely_unimported(tmp_path, capsys):
    """A confirmed dedup cluster whose members are ALL absent from the
    registry (not just split across different entities) is still grouping
    drift, per spec: 'or some are missing'."""
    campaign_dir = _init(tmp_path)  # empty registry — nothing imported yet
    npcs_dir = campaign_dir / "docs" / "npcs"
    npcs_dir.mkdir(parents=True)
    dedup_data = {
        "clusters_confirmed": [
            {"files": ["asha_vandree.md", "asha.md"], "canonical": "asha_vandree.md", "aliases_recorded": []},
        ],
    }
    (npcs_dir / ".dedup_state.json").write_text(json.dumps(dedup_data), encoding="utf-8")

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "dedup groups" in out
    assert "MISSING" in out


def test_check_malformed_registry_yaml_reports_and_returns_one(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    reg_path = campaign_dir / "docs" / "entity_registry.yaml"
    reg_path.write_text("not: [valid, yaml: :::", encoding="utf-8")

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Error" in err


def test_check_fuzzy_near_duplicate_flagged_then_suppressed_once_distinct(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", "Khalessa Draga", "--type", "npc", "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Khelessa Draga", "--type", "npc", "--yes"]) == 0

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "possible fragmentation" in out
    assert "Khalessa Draga" in out
    assert "Khelessa Draga" in out

    # GM rules them distinct — re-running check must SUPPRESS the pair.
    reg_path = campaign_dir / "docs" / "entity_registry.yaml"
    reg = load_registry(reg_path)
    reg.distinct.append(["Khalessa Draga", "Khelessa Draga"])
    save_registry(reg, reg_path)

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "possible fragmentation" not in out
    assert "0 fuzzy-near-dup" in out


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


# ── check: (a4) dossier frontmatter grouping drift ──────────────────────────

def test_check_frontmatter_grouping_drift_detected(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    # Registry has canonical and alias as SEPARATE entities...
    assert registry.main(["add", str(campaign_dir), "--name", "Asha Vandree", "--type", "npc", "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Asha", "--type", "npc", "--yes"]) == 0

    # ...but a dossier's frontmatter declares them as one entity (canonical + alias).
    dossier_dir = campaign_dir / "docs" / "npcs"
    dossier_dir.mkdir(parents=True)
    _write_dossier(dossier_dir, "asha.md", "Asha Vandree", ["Asha"])
    _write_dossier(dossier_dir, "byrtyn.md", "Byrtyn Fey", [])  # unrelated, singleton — no drift of its own

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "dossier frontmatter groups" in out
    assert "Asha Vandree" in out
    assert "Asha" in out


def test_check_frontmatter_grouping_no_drift_when_registry_agrees(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    # Registry already has "Asha" as an alias of "Asha Vandree" — no drift.
    assert registry.main([
        "add", str(campaign_dir), "--name", "Asha Vandree", "--type", "npc",
        "--aliases", "Asha", "--yes",
    ]) == 0

    dossier_dir = campaign_dir / "docs" / "npcs"
    dossier_dir.mkdir(parents=True)
    _write_dossier(dossier_dir, "asha.md", "Asha Vandree", ["Asha"])

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dossier frontmatter groups" not in out
    assert "0 grouping-drift" in out


# ── check: (a5) aliases.json grouping drift ─────────────────────────────────

def test_check_aliases_json_grouping_drift_detected(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    # Registry has canonical and alias as SEPARATE entities...
    assert registry.main(["add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc", "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Ilvara", "--type", "npc", "--yes"]) == 0

    ensemble_dir = campaign_dir / "docs" / "ensemble"
    ensemble_dir.mkdir(parents=True)
    (ensemble_dir / "aliases.json").write_text(
        json.dumps({"Ilvara Mizzrym": ["Ilvara"]}), encoding="utf-8",
    )

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "aliases.json groups" in out
    assert "Ilvara Mizzrym" in out
    assert "Ilvara" in out


def test_check_aliases_json_grouping_no_drift_when_registry_agrees(tmp_path, capsys):
    campaign_dir = _init(tmp_path)
    assert registry.main([
        "add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc",
        "--aliases", "Ilvara", "--yes",
    ]) == 0

    ensemble_dir = campaign_dir / "docs" / "ensemble"
    ensemble_dir.mkdir(parents=True)
    (ensemble_dir / "aliases.json").write_text(
        json.dumps({"Ilvara Mizzrym": ["Ilvara"]}), encoding="utf-8",
    )

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "aliases.json groups" not in out
    assert "0 grouping-drift" in out


def test_check_aliases_json_fallback_path_scanned_when_ensemble_absent(tmp_path, capsys):
    """docs/aliases.json must be scanned when docs/ensemble/aliases.json is absent."""
    campaign_dir = _init(tmp_path)
    assert registry.main(["add", str(campaign_dir), "--name", "Ilvara Mizzrym", "--type", "npc", "--yes"]) == 0
    assert registry.main(["add", str(campaign_dir), "--name", "Ilvara", "--type", "npc", "--yes"]) == 0

    docs_dir = campaign_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "aliases.json").write_text(
        json.dumps({"Ilvara Mizzrym": ["Ilvara"]}), encoding="utf-8",
    )

    rc = registry.main(["check", str(campaign_dir)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "aliases.json groups" in out
