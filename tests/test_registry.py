"""Tests for campaignlib/registry.py — the entity registry loader.

Covers the deterministic parse/validate logic (no API / no model calls) plus
round-trip checks against the REAL consumer loaders this registry is meant
to eventually replace: synthesise_world_state.load_aliases, npc.load_alias_map
(shape), and spell_canon.inventory_tokens / facts_to_state's bold-span
extraction (the formatting invariant that a name and its alias must never
share one bold span).
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.registry import load_registry, find_registry  # noqa: E402
from synthesise_world_state import load_aliases  # noqa: E402
from entity_registry.spell_canon import inventory_tokens  # noqa: E402


# ── shared sample registry ──────────────────────────────────────────────────

SAMPLE_YAML = """
version: 1
campaign: out-of-the-abyss
entities:
  - name: Ilvara Mizzrym
    type: npc
    aliases: [Ilvara, Mistress Ilvara]
    provenance: module
    source: OotA
    scope: persistent
    note: senior drow priestess
  - name: Adabra Gwynn
    type: npc
    provenance: module
    source: OotA
    scope: persistent
  - name: Gracklstugh
    type: location
    provenance: module
    source: OotA
    scope: persistent
distinct:
  - [Topsy, Turvy]
rejected_aliases:
  - [Shoor, Stool]
"""


def _write(tmp_path: Path, text: str, name: str = "entity_registry.yaml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── happy path ───────────────────────────────────────────────────────────────

def test_happy_path_load(tmp_path):
    path = _write(tmp_path, SAMPLE_YAML)
    reg = load_registry(path)

    assert reg.version == 1
    assert reg.campaign == "out-of-the-abyss"
    assert reg.source_path == path
    assert len(reg.entities) == 3

    ilvara = reg.entities[0]
    assert ilvara.name == "Ilvara Mizzrym"
    assert ilvara.type == "npc"
    assert ilvara.aliases == ["Ilvara", "Mistress Ilvara"]
    assert ilvara.provenance == "module"
    assert ilvara.source == "OotA"
    assert ilvara.scope == "persistent"
    assert ilvara.note == "senior drow priestess"

    adabra = reg.entities[1]
    assert adabra.name == "Adabra Gwynn"
    assert adabra.aliases == []
    assert adabra.note is None

    assert reg.distinct == [["Topsy", "Turvy"]]
    assert reg.rejected_aliases == [["Shoor", "Stool"]]


def test_find_registry(tmp_path):
    campaign_dir = tmp_path / "my-campaign"
    (campaign_dir / "docs").mkdir(parents=True)
    (campaign_dir / "docs" / "entity_registry.yaml").write_text(SAMPLE_YAML, encoding="utf-8")

    found = find_registry(campaign_dir)
    assert found == campaign_dir / "docs" / "entity_registry.yaml"

    empty_dir = tmp_path / "no-registry-here"
    empty_dir.mkdir()
    assert find_registry(empty_dir) is None


# ── invariant failures ───────────────────────────────────────────────────────

def test_duplicate_normalized_name_raises(tmp_path):
    yaml_text = """
version: 1
entities:
  - name: Harbin Wester
    type: npc
  - name: HARBIN WESTER
    type: npc
"""
    path = _write(tmp_path, yaml_text)
    with pytest.raises(ValueError):
        load_registry(path)


def test_alias_claimed_by_two_canonicals_raises(tmp_path):
    yaml_text = """
version: 1
entities:
  - name: Entity One
    type: npc
    aliases: [Shared Alias]
  - name: Entity Two
    type: npc
    aliases: [Shared Alias]
"""
    path = _write(tmp_path, yaml_text)
    with pytest.raises(ValueError):
        load_registry(path)


def test_distinct_pair_also_aliased_raises(tmp_path):
    yaml_text = """
version: 1
entities:
  - name: Sarith Kzekarit
    type: npc
    aliases: [Sarith]
distinct:
  - [Sarith Kzekarit, Sarith]
"""
    path = _write(tmp_path, yaml_text)
    with pytest.raises(ValueError):
        load_registry(path)


def test_bad_type_raises(tmp_path):
    yaml_text = """
version: 1
entities:
  - name: Some Monster
    type: monster
"""
    path = _write(tmp_path, yaml_text)
    with pytest.raises(ValueError):
        load_registry(path)


# ── round trip against real consumer loaders ────────────────────────────────

def test_alias_to_canonical_matches_load_aliases(tmp_path):
    reg = load_registry(_write(tmp_path, SAMPLE_YAML))

    aliases_json = tmp_path / "aliases.json"
    aliases_json.write_text(json.dumps(reg.canonical_to_aliases()), encoding="utf-8")

    loaded = load_aliases(aliases_json)
    assert loaded == reg.alias_to_canonical()


def test_canonical_to_aliases_shape_matches_load_alias_map(tmp_path):
    reg = load_registry(_write(tmp_path, SAMPLE_YAML))
    shape = reg.canonical_to_aliases()

    # Same shape as campaignlib.npc.load_alias_map: {canonical: [aliases]}.
    assert shape == {
        "Ilvara Mizzrym": ["Ilvara", "Mistress Ilvara"],
        "Adabra Gwynn": [],
        "Gracklstugh": [],
    }
    for canonical, aliases in shape.items():
        assert isinstance(canonical, str)
        assert isinstance(aliases, list)


def test_inventory_tokens_round_trip(tmp_path):
    reg = load_registry(_write(tmp_path, SAMPLE_YAML))

    md_path = tmp_path / "inventory.md"
    md_path.write_text(reg.inventory_markdown(), encoding="utf-8")

    canon = inventory_tokens(md_path, min_len=3)

    # Each canonical name's tokens map back to their cased spelling.
    assert canon["ilvara"] == "Ilvara"
    assert canon["mizzrym"] == "Mizzrym"
    assert canon["mistress"] == "Mistress"
    assert canon["adabra"] == "Adabra"
    assert canon["gwynn"] == "Gwynn"
    assert canon["gracklstugh"] == "Gracklstugh"


def test_inventory_markdown_bold_spans_never_contain_slash(tmp_path):
    reg = load_registry(_write(tmp_path, SAMPLE_YAML))
    md = reg.inventory_markdown()

    _BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
    spans = _BOLD_RE.findall(md)

    assert spans, "expected at least one bold span"
    for span in spans:
        assert "/" not in span, f"bold span {span!r} must not contain a slash"

    # Every canonical name and alias appears as its own whole span.
    expected = {
        "Ilvara Mizzrym", "Ilvara", "Mistress Ilvara",
        "Adabra Gwynn",
        "Gracklstugh",
    }
    assert expected <= set(spans)


def test_known_names(tmp_path):
    reg = load_registry(_write(tmp_path, SAMPLE_YAML))

    known = reg.known_names(extra=["Sirac"])

    from campaignlib.textproc import norm_subject

    # Whole names/aliases, normalized.
    assert norm_subject("Ilvara Mizzrym") in known
    assert norm_subject("Ilvara") in known
    assert norm_subject("Mistress Ilvara") in known
    assert norm_subject("Adabra Gwynn") in known
    assert norm_subject("Gracklstugh") in known

    # First-token rule: "Adabra Gwynn" -> also registers "Adabra".
    assert norm_subject("Adabra") in known

    # extra= adds out-of-band known names (e.g. PC names from party.yaml).
    assert norm_subject("Sirac") in known
