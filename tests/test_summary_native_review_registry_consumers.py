"""Regression coverage for every registry consumer affected by reviewed identity changes.

These tests exercise the public consumer seams named by the dependency inventory.  They
deliberately use an alias whose spelling differs from its canonical name, so merely
loading a registry (without consuming its projection) cannot make the assertions pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from campaignlib.npc import load_alias_map
from campaignlib.registry import load_registry
from entity_registry import registry_mcp
from entity_registry import resolve as registry_resolve
from pipelines.ensemble import (
    facts_to_state,
    synthesise_facts,
    synthesise_polish,
    synthesise_world_state,
)
from pipelines.grounding import normalize_bible_headings, planning
from pipelines.summary_native import (
    annotate,
    corpus,
    duplicates,
    key_npcs,
    npc_draft,
    npc_forms,
    npc_link,
    state_sections,
)
from provenance import identity as provenance_identity
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli


EXPECTED_CONSUMERS = {
    "summary_native.duplicates",
    "summary_native.npc_selection",
    "summary_native.npc_forms",
    "summary_native.npc_link",
    "summary_native.annotate",
    "summary_native.state_sections",
    "summary_native.key_npcs",
    "entity_registry.resolve",
    "entity_registry.mcp",
    "provenance.identity",
    "provenance.expansion",
    "ensemble.facts_to_state",
    "ensemble.synthesise_facts",
    "ensemble.synthesise_world_state",
    "ensemble.synthesise_polish",
    "ensemble.known_names",
    "campaignlib.npc",
    "campaignlib.grounding_planning",
    "normalize_bible_headings",
}


def _write_registry(root: Path) -> Path:
    path = root / "docs" / "entity_registry.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "campaign": "consumer-fixture",
                "entities": [
                    {
                        "name": "Eldeth Feldrun",
                        "type": "npc",
                        "aliases": ["Eldeth"],
                        "scope": "persistent",
                    },
                    {
                        "name": "The Black Network",
                        "type": "faction",
                        "aliases": ["Zhentarim"],
                        "scope": "persistent",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_dependency_inventory_has_a_real_regression_for_every_remaining_consumer():
    """Keep this matrix synchronized with the production dependency inventory."""
    assert EXPECTED_CONSUMERS == set(corpus.DEPENDENCY_CONSUMERS) - {
        "summary_native.build",
        "summary_native.validation",
    }


def test_summary_native_consumers_use_registry_aliases_and_scope(tmp_path):
    root = npc_campaign(tmp_path)
    registry_path = root / "docs" / "entity_registry.yaml"
    players_path = root / "config" / "players.yaml"
    registry = load_registry(registry_path)
    range_dir = root / "docs" / "summary_native" / f"ch{SINCE:03d}-{UNTIL:03d}"

    # summary_native.duplicates
    assert duplicates.make_grouper(registry)("npc", "Eldeth") == (
        "Eldeth Feldrun",
        ["registry"],
    )

    # summary_native.npc_forms
    dossiers = npc_forms.read_corpus_dossiers(range_dir)
    words, _ = npc_forms.load_wordlist()
    form_index = npc_forms.build_form_index(registry, dossiers, words, {})
    eldeth_form = form_index.forms["Eldeth"]
    assert eldeth_form.owner == ("npc", "Eldeth Feldrun")
    assert eldeth_form.sources == ("registry",)

    # summary_native.npc_link: drive the command's real linking path and observe
    # the registry-only alias in the generated evidence.
    rc, _out, err = run_cli(
        [
            "npc-link",
            "--config",
            str(root / "config" / "config.yaml"),
            "--summaries-dir",
            str(root / "docs" / "summaries"),
            "--since",
            str(SINCE),
            "--until",
            str(UNTIL),
        ]
    )
    assert rc == 0, err
    evidence = npc_link.read_evidence_files(
        root / "docs" / "npcs" / "summary_native" / f"ch{SINCE:03d}-{UNTIL:03d}"
    )
    eldeth = next(item for item in evidence if item.subject == "Eldeth Feldrun")
    assert "Eldeth takes the rear." in eldeth.body

    # summary_native.npc_selection: the CLI selection helper accepts the exact
    # registered alias and selects the canonical evidence dossier.
    aliases = {form.casefold(): canonical for form, canonical in registry.alias_to_canonical().items()}
    selection = npc_draft.select_global(
        evidence,
        named=("Eldeth",),
        range_until=UNTIL,
        range_text=f"{SINCE}-{UNTIL}",
        registry_npcs=tuple(e.name for e in registry.entities if e.type == "npc"),
        registry_aliases=aliases,
    )
    assert [item["subject"] for item in selection.included] == ["Eldeth Feldrun"]

    # summary_native.state_sections and summary_native.annotate both read the
    # identity files themselves rather than receiving a preflattened test map.
    forms, pcs, ambiguous = state_sections.load_identity(registry_path, players_path)
    assert forms["eldeth"] == "Eldeth Feldrun"
    assert "Thorin" in pcs
    assert ambiguous == {}
    annotation_evidence = annotate.load_evidence([], [], registry_path, players_path)
    assert annotation_evidence.canon("Eldeth") == "Eldeth Feldrun"
    assert annotation_evidence.mentioned_in("Eldeth takes the rear") == {"Eldeth Feldrun"}

    # summary_native.key_npcs consumes registry scope, which decides whether an
    # NPC is eligible for the global selection pool.
    scopes = key_npcs.registry_npc_scopes(registry_path)
    assert scopes["Eldeth Feldrun"] == "persistent"


def test_registry_resolve_mcp_and_provenance_read_the_same_alias(tmp_path):
    registry_path = _write_registry(tmp_path)
    registry_resolve.clear_cache()

    # entity_registry.resolve
    resolved = registry_resolve.resolve_name(tmp_path, "Eldeth")
    assert resolved["status"] == "resolved"
    assert resolved["canonical"] == "Eldeth Feldrun"
    assert resolved["tier"] == 3

    # entity_registry.mcp runs the actual registry CLI adapter and preserves its
    # typed JSON result for read-only resolution.
    mcp_result = json.loads(registry_mcp.registry_resolve_name(tmp_path, "Eldeth"))
    assert mcp_result["status"] == "resolved"
    assert mcp_result["canonical"] == "Eldeth Feldrun"

    campaign = SimpleNamespace(
        name="consumer-fixture",
        identity=SimpleNamespace(registry="docs/entity_registry.yaml", aliases=None),
    )

    # provenance.identity and provenance.expansion
    identity = provenance_identity.resolve(campaign, tmp_path, "Eldeth")
    assert identity.status is provenance_identity.IdentityStatus.RESOLVED
    assert identity.canonical == "Eldeth Feldrun"
    assert provenance_identity.expansion_forms(campaign, tmp_path, "Eldeth") == (
        "Eldeth",
        "Eldeth Feldrun",
    )
    assert registry_path.is_file()


def test_ensemble_consumers_canonicalize_registry_aliases(tmp_path):
    registry_path = _write_registry(tmp_path)
    registry = load_registry(registry_path)
    aliases = registry.alias_to_canonical()
    facts = [
        {
            "type": "npc",
            "subject": "Eldeth",
            "fact": "She guards the rear",
            "passes": ["plot"],
            "source_quote": "I will take the rear.",
        }
    ]

    # ensemble.synthesise_facts
    facts_markdown = synthesise_facts.synthesise(facts, aliases)
    assert "**Eldeth Feldrun**" in facts_markdown
    assert "also: Eldeth" in facts_markdown

    # ensemble.synthesise_world_state
    state_markdown = synthesise_world_state.render_facts(facts, aliases, with_quotes=True)
    assert "**Eldeth Feldrun**" in state_markdown
    assert '"I will take the rear."' in state_markdown

    # ensemble.synthesise_polish
    polish_input = synthesise_polish.build_input(facts, aliases)
    assert "## Eldeth Feldrun" in polish_input
    assert "## Eldeth\n" not in polish_input

    # ensemble.known_names consumes the registry's real inventory projection.
    inventory = tmp_path / "registry-inventory.md"
    inventory.write_text(registry.inventory_markdown(), encoding="utf-8")
    known = facts_to_state.load_known_names([inventory])
    assert {"eldeth", "eldethfeldrun"} <= known

    # ensemble.facts_to_state consumes both projections: the alias chooses the
    # canonical bundle display and known-names keeps the bundle global.
    merged = tmp_path / "chapter_007" / "merged.json"
    merged.parent.mkdir()
    merged.write_text(json.dumps(facts), encoding="utf-8")
    bundles = facts_to_state.load_bundles(
        [merged], aliases, ["npc"], known_names=known
    )
    assert len(bundles) == 1
    (bundle,) = bundles.values()
    assert bundle.display == "Eldeth Feldrun"
    assert bundle.known is True


def test_campaignlib_and_grounding_planning_seed_from_registry(
    tmp_path, monkeypatch
):
    registry_path = _write_registry(tmp_path)
    dossier_dir = tmp_path / "docs" / "npcs" / "distilled"
    dossier_dir.mkdir(parents=True)

    # campaignlib.npc: registry data replaces any legacy dossier-frontmatter map.
    (dossier_dir / "legacy.md").write_text(
        "---\nname: Wrong Legacy Name\naliases: [Wrong]\n---\n\nbody\n",
        encoding="utf-8",
    )
    alias_map = load_alias_map(dossier_dir, registry_path=registry_path)
    assert alias_map["Eldeth Feldrun"] == ["Eldeth"]
    assert "Wrong Legacy Name" not in alias_map

    # campaignlib.grounding_planning: run the real extraction setup through its
    # model boundary and capture the registry-derived roster appended to the prompt.
    captured = {}

    def fake_extract_pipeline(*_args, **kwargs):
        captured["system_suffix"] = kwargs["system_suffix"]

    monkeypatch.setattr(planning, "run_extract_pipeline", fake_extract_pipeline)
    monkeypatch.chdir(tmp_path)
    result = planning.run_build_dossiers(
        object(),
        "summary text",
        1000,
        "unused-model",
        tmp_path / "docs" / "planning_extractions",
        dossier_dir,
        extract_only=True,
    )
    assert result == []
    assert "Eldeth Feldrun (also: Eldeth)" in captured["system_suffix"]
    assert "Wrong Legacy Name" not in captured["system_suffix"]


def test_heading_normalizer_loads_registered_names_and_aliases(tmp_path):
    registry_path = _write_registry(tmp_path)
    bible = tmp_path / "docs" / "Bible.md"
    bible.write_text(
        "# Chapter 7 The Rear Guard\n\n## Eldeth\n\nShe takes the rear.\n",
        encoding="utf-8",
    )

    known = normalize_bible_headings.load_known_names(bible, None, None)
    assert {"eldeth", "eldethfeldrun"} <= known
    demotions = normalize_bible_headings.find_demotions(bible.read_text(encoding="utf-8"), known)
    assert [name for _start, _end, name in demotions] == ["Eldeth"]
    assert "### Eldeth" in normalize_bible_headings.apply_demotions(
        bible.read_text(encoding="utf-8"), demotions
    )
    assert registry_path.is_file()
