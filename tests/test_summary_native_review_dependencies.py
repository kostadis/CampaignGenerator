"""T040 per-subject dependency, freshness, and adoption contracts.

The production seam is deliberately introduced by T043.  These tests define
the smallest public contract needed by identity preview/application without
coupling it to a particular index implementation:

* ``corpus.DEPENDENCY_CONSUMERS`` is the complete registered consumer set;
* ``corpus.build_dependency_manifest`` emits versioned forward and reverse
  dependency indexes from current artifacts only;
* ``freshness.dependency_invalidation`` distinguishes current, exact-subject,
  and conservative global invalidation; and
* ``review.migrate.plan_dependency_adoption`` / ``apply_dependency_adoption``
  perform explicit, digest-bound migration of legacy coarse manifests.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import corpus, freshness
from pipelines.summary_native import duplicates
from pipelines.summary_native.review import migrate
from pipelines.summary_native.validate import scan
from campaignlib.registry import load_registry


EXPECTED_CONSUMERS = {
    "summary_native.duplicates",
    "summary_native.validation",
    "summary_native.build",
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _registry(
    *,
    alice_alias: str = "Al",
    manshoon_alias: str = "Lord Manshoon",
    opaque_revision: int = 7,
) -> dict:
    return {
        "version": 1,
        "campaign": "dependency-fixture",
        "entities": [
            {
                "name": "Alice Vale",
                "type": "npc",
                "aliases": [alice_alias],
                "provenance": "module",
                "source": "Fixture",
                "note": "keep this exact authored note",
            },
            {
                "name": "Bob Stone",
                "type": "npc",
                "aliases": ["Bobby"],
                "provenance": "supplement",
                "source": "Fixture",
            },
            {
                "name": "Manshoon",
                "type": "npc",
                "aliases": [manshoon_alias],
                "provenance": "module",
                "source": "Fixture",
            },
        ],
        "distinct": [["Alice Vale", "Bob Stone"]],
        "rejected_aliases": [],
        # Registry v1 readers do not understand extension payloads.  Migration
        # treats the registry as evidence bytes and must never round-trip it
        # through a lossy typed Registry model.
        "x-campaign-extension": {
            "revision": opaque_revision,
            "nested": ["preserve", {"bytes": "verbatim"}],
        },
    }


def _artifact(
    consumer: str,
    path: str,
    subjects: list[str],
    *,
    ownership: str = "generated",
    body: bytes | None = None,
) -> dict:
    content = body if body is not None else f"artifact:{consumer}:{path}\n".encode()
    return {
        "consumer": consumer,
        "path": path,
        "sha256": _sha(content),
        "subject_ids": subjects,
        "ownership": ownership,
    }


def _builder():
    function = getattr(corpus, "build_dependency_manifest", None)
    assert callable(function), "implement corpus.build_dependency_manifest"
    return function


def _invalidator():
    function = getattr(freshness, "dependency_invalidation", None)
    assert callable(function), "implement freshness.dependency_invalidation"
    return function


def _adoption_api():
    plan = getattr(migrate, "plan_dependency_adoption", None)
    apply = getattr(migrate, "apply_dependency_adoption", None)
    assert callable(plan), "implement migrate.plan_dependency_adoption"
    assert callable(apply), "implement migrate.apply_dependency_adoption"
    return plan, apply


def _all_consumer_artifacts() -> list[dict]:
    return [
        _artifact(
            consumer,
            f"derived/{index:02d}-{consumer.replace('.', '-')}.json",
            ["npc:alice-vale"] if index % 2 == 0 else ["npc:bob-stone"],
        )
        for index, consumer in enumerate(sorted(EXPECTED_CONSUMERS))
    ]


def test_registered_dependency_consumers_are_complete_and_manifested():
    registered = getattr(corpus, "DEPENDENCY_CONSUMERS", None)
    assert registered is not None, "define corpus.DEPENDENCY_CONSUMERS"
    assert set(registered) == EXPECTED_CONSUMERS

    artifacts = _all_consumer_artifacts()
    manifest = _builder()(registry=_registry(), artifacts=artifacts)

    assert manifest["version"] == 2
    assert {entry["consumer"] for entry in manifest["artifacts"]} == EXPECTED_CONSUMERS
    assert set(manifest["reverse_dependencies"]) == {"npc:alice-vale", "npc:bob-stone"}
    indexed = {
        path
        for paths in manifest["reverse_dependencies"].values()
        for path in paths
    }
    assert indexed == {entry["path"] for entry in artifacts}


def test_reverse_dependencies_are_deterministic_and_clean_stale_entries():
    build = _builder()
    alice = _artifact(
        "summary_native.build", "ranges/001-010/dossiers/npc_alice_vale.md",
        ["npc:alice-vale"],
    )
    bob = _artifact(
        "summary_native.npc_link", "ranges/001-010/npcs/link_manifest.json",
        ["npc:bob-stone"],
    )
    prior = build(registry=_registry(), artifacts=[alice, bob])
    # A rebuild is a complete current inventory.  It must not union old index
    # entries back in after an artifact or subject disappeared.
    rebuilt = build(registry=_registry(), artifacts=[bob], previous_manifest=prior)

    assert [entry["path"] for entry in rebuilt["artifacts"]] == [bob["path"]]
    assert rebuilt["reverse_dependencies"] == {"npc:bob-stone": [bob["path"]]}
    assert "npc:alice-vale" not in rebuilt.get("subjects", {})

    reordered = build(registry=_registry(), artifacts=list(reversed([bob])))
    assert json.dumps(rebuilt, sort_keys=True) == json.dumps(reordered, sort_keys=True)


def test_external_read_only_sources_stay_bound_but_never_enter_mutation_inventory(tmp_path: Path):
    root = tmp_path / "campaign"
    output = root / "derived" / "summary-native" / "001-010"
    output.mkdir(parents=True)
    generated = output / "chronology.md"
    generated.write_text("# Chronology\n", encoding="utf-8")
    local = root / "summaries" / "001.md"
    local.parent.mkdir(parents=True)
    local.write_text("# Local\n", encoding="utf-8")
    external = tmp_path / "external" / "002.md"
    external.parent.mkdir(parents=True)
    external.write_text("# External\n", encoding="utf-8")
    external_binding = "../external/002.md"
    manifest = {
        "files": [
            {"path": "summaries/001.md", "sha256": corpus.sha256_file(local)},
            {"path": external_binding, "sha256": corpus.sha256_file(external)},
        ]
    }

    artifacts = corpus._corpus_dependency_artifacts(
        campaign_root=root,
        range_dir=output,
        manifest=manifest,
        observations=[],
    )

    # The ordinary corpus manifest remains the exact read-only freshness
    # binding. Only its campaign-local member enters the mutable dependency
    # graph used by identity review/application.
    assert manifest["files"][1]["path"] == external_binding
    source_paths = {
        entry["path"] for entry in artifacts if entry["ownership"] == "source"
    }
    assert source_paths == {"summaries/001.md"}
    assert all(not Path(entry["path"]).is_absolute() and ".." not in Path(entry["path"]).parts
               for entry in artifacts)
    validated = corpus.build_dependency_manifest(
        registry=None,
        registry_sha256=None,
        artifacts=artifacts,
        precision="coarse",
    )
    assert validated["inventory_complete"] is True


def test_exact_change_invalidates_only_reverse_closure_and_flags_authored_conflicts():
    generated = _artifact(
        "summary_native.build", "ranges/001-010/dossiers/npc_alice_vale.md",
        ["npc:alice-vale"],
    )
    authored = _artifact(
        "campaignlib.npc", "docs/npcs/authored/alice-vale.md",
        ["npc:alice-vale"], ownership="authored",
    )
    unrelated = _artifact(
        "summary_native.npc_link", "ranges/001-010/npcs/bob.json",
        ["npc:bob-stone"],
    )
    manifest = _builder()(
        registry=_registry(), artifacts=[generated, authored, unrelated]
    )

    report = _invalidator()(
        manifest,
        current_registry=_registry(alice_alias="Allie"),
        current_artifacts={
            entry["path"]: entry["sha256"]
            for entry in (generated, authored, unrelated)
        },
    )

    assert report["state"] == "stale"
    assert report["changed_subjects"] == ["npc:alice-vale"]
    assert report["stale_paths"] == [generated["path"]]
    assert report["authored_conflicts"] == [authored["path"]]
    assert unrelated["path"] in report["preserved_paths"]


def test_semantic_no_op_is_current_but_opaque_change_invalidates_globally():
    artifacts = _all_consumer_artifacts()
    registry = _registry()
    manifest = _builder()(registry=registry, artifacts=artifacts)
    current = {entry["path"]: entry["sha256"] for entry in artifacts}

    # Mapping and entity order are presentation details; they do not stale an
    # otherwise identical dependency graph.
    reordered = {
        "x-campaign-extension": registry["x-campaign-extension"],
        "rejected_aliases": [],
        "distinct": registry["distinct"],
        "entities": list(reversed(registry["entities"])),
        "campaign": registry["campaign"],
        "version": 1,
    }
    no_op = _invalidator()(
        manifest, current_registry=reordered, current_artifacts=current
    )
    assert no_op == {
        "state": "current",
        "changed_subjects": [],
        "stale_paths": [],
        "authored_conflicts": [],
        "preserved_paths": sorted(current),
    }

    # An unknown top-level registry extension cannot safely be attributed to
    # one subject.  Preserve it, and fall back to the complete closure.
    opaque_change = _invalidator()(
        manifest,
        current_registry=_registry(opaque_revision=8),
        current_artifacts=current,
    )
    assert opaque_change["state"] == "global"
    assert opaque_change["changed_subjects"] == []
    assert set(opaque_change["stale_paths"]) == set(current)
    assert opaque_change["preserved_paths"] == []


def _legacy_campaign(root: Path, *, malformed: bool = False) -> tuple[Path, Path, bytes]:
    config_path = root / "config" / "grounding.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "summary_native:\n"
        "  out_root: derived/summary-native\n"
        "  registry: docs/entity_registry.yaml\n",
        encoding="utf-8",
    )
    registry_path = root / "docs" / "entity_registry.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_bytes = yaml.safe_dump(_registry(), sort_keys=False).encode()
    registry_path.write_bytes(registry_bytes)

    range_dir = root / "derived" / "summary-native" / "001-010"
    dossier = range_dir / "dossiers" / "npc_alice_vale.md"
    dossier.parent.mkdir(parents=True)
    dossier.write_text(
        "---\nsubject: Alice Vale\ntype: npc\n---\n\n# NPCs — Alice Vale\n",
        encoding="utf-8",
    )
    manifest_path = range_dir / "manifest.json"
    source_path = root / "summaries" / "001" / "session-summary.md"
    source_path.parent.mkdir(parents=True)
    source_bytes = b"# Chapter 1\n\nPinned migration input.\n"
    source_path.write_bytes(source_bytes)
    legacy = {
        "kind": "summary_native",
        "schema": 1,
        "complete": True,
        "range": {"since": 1, "until": 10, "gaps": []},
        "files": [] if malformed else [{
            "path": "summaries/001/session-summary.md",
            "chapter": 1,
            "sha256": _sha(source_bytes),
        }],
        "counts": {"files": 1, "dossiers": 1},
        "canon": {"registry_sha256": _sha(registry_bytes), "canon_sha256": None},
    }
    manifest_path.write_text(json.dumps(legacy, sort_keys=True) + "\n")
    return manifest_path, dossier, registry_bytes


def test_legacy_coarse_metadata_adoption_is_explicit_digest_bound_and_preserves_payload(
    tmp_path: Path,
):
    manifest_path, dossier, registry_before = _legacy_campaign(tmp_path)
    dossier_before = dossier.read_bytes()
    plan, apply = _adoption_api()

    proposal = plan(tmp_path)
    assert proposal["kind"] == "identity_dependency_adoption"
    assert proposal["no_op"] is False
    assert proposal["changed_paths"] == [str(manifest_path.relative_to(tmp_path))]
    assert proposal["rebuild_required"] == []
    assert len(proposal["plan_sha256"]) == 64

    result = apply(tmp_path, plan_sha256=proposal["plan_sha256"])
    adopted = json.loads(manifest_path.read_text())
    assert result["plan_sha256"] == proposal["plan_sha256"]
    assert adopted["identity_dependencies"]["version"] == 2
    assert adopted["identity_dependencies"]["reverse_dependencies"] == {
        "npc:alice-vale": [str(dossier.relative_to(tmp_path))]
    }
    assert (tmp_path / "docs" / "entity_registry.yaml").read_bytes() == registry_before
    assert dossier.read_bytes() == dossier_before

    rerun = plan(tmp_path)
    assert rerun["no_op"] is True
    assert rerun["changed_paths"] == []


def test_dependency_adoption_reports_unprovable_legacy_input_and_refuses_stale_plan(
    tmp_path: Path,
):
    manifest_path, _dossier, _registry = _legacy_campaign(tmp_path, malformed=True)
    plan, apply = _adoption_api()

    blocked = plan(tmp_path)
    assert blocked["changed_paths"] == []
    assert blocked["rebuild_required"] == [{
        "path": str(manifest_path.relative_to(tmp_path)),
        "command": "summary_native build --force",
        "reason": "legacy dependencies cannot be reconstructed from pinned inputs",
    }]

    # A reviewed migration digest never authorizes a different set of bytes.
    manifest_path, _dossier, _registry = _legacy_campaign(tmp_path / "stale")
    proposal = plan(tmp_path / "stale")
    raw = json.loads(manifest_path.read_text())
    raw["files"][0]["sha256"] = "b" * 64
    manifest_path.write_text(json.dumps(raw, sort_keys=True) + "\n")
    with pytest.raises(Exception, match="DEPENDENCY_MIGRATION_STALE"):
        apply(tmp_path / "stale", plan_sha256=proposal["plan_sha256"])


def test_real_corpus_writer_and_freshness_adopt_configured_subject_dependencies(
    tmp_path: Path,
):
    root = tmp_path / "campaign"
    summaries = root / "summaries"
    shutil.copytree(
        Path(__file__).parent / "fixtures" / "summary_native" / "clean",
        summaries,
    )
    registry_path = root / "canon" / "entities.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(yaml.safe_dump(_registry(), sort_keys=False), encoding="utf-8")
    config_path = root / "config" / "grounding.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "summary_native:\n"
        "  out_root: generated/review-corpus\n"
        "  registry: canon/entities.yaml\n",
        encoding="utf-8",
    )

    registry = load_registry(registry_path)
    report = scan(summaries, root, None, None, registry=registry)
    assert report.blocking_count == 0
    range_dir = root / "generated" / "review-corpus" / "ch002-005"
    range_dir.mkdir(parents=True)
    (range_dir / "validation_report.md").write_text(report.to_markdown(), encoding="utf-8")
    (range_dir / "validation_report.json").write_text(report.to_json(), encoding="utf-8")
    manifest = corpus.build_corpus(
        summaries,
        root,
        report,
        range_dir,
        grouper=duplicates.make_grouper(registry),
        registry_sha256=_sha(registry_path.read_bytes()),
    )

    dependencies = manifest["identity_dependencies"]
    assert dependencies["version"] == 2
    assert dependencies["precision"] == "coarse"
    assert dependencies["inventory_complete"] is True
    paths = {entry["path"] for entry in dependencies["artifacts"]}
    assert "generated/review-corpus/ch002-005/dossiers/npc_manshoon.md" in paths
    assert not any(path.startswith("derived/summary-native/") for path in paths)
    assert freshness.check_fresh(report, range_dir, root, manifest, registry_path) is None

    # A normal build has only the historical registry digest, so any registry
    # change remains a conservative coarse invalidation before adoption.
    registry_path.write_text(
        yaml.safe_dump(_registry(alice_alias="Allie"), sort_keys=False),
        encoding="utf-8",
    )
    assert "entity registry changed" in freshness.check_fresh(
        report, range_dir, root, manifest, registry_path
    )
    registry_path.write_text(yaml.safe_dump(_registry(), sort_keys=False), encoding="utf-8")

    decoy = root / "docs" / "summary_native" / "ch999-999" / "manifest.json"
    decoy.parent.mkdir(parents=True)
    decoy.write_text('{"kind":"summary_native","files":[]}\n', encoding="utf-8")
    proposal = migrate.plan_dependency_adoption(root)
    assert proposal["changed_paths"] == [
        "generated/review-corpus/ch002-005/manifest.json"
    ]
    migrate.apply_dependency_adoption(root, plan_sha256=proposal["plan_sha256"])
    adopted = json.loads((range_dir / "manifest.json").read_text(encoding="utf-8"))
    precise = adopted["identity_dependencies"]
    assert precise["precision"] == "subject"
    assert precise["reverse_dependencies"]["npc:manshoon"] == [
        "generated/review-corpus/ch002-005/dossiers/npc_manshoon.md",
        "generated/review-corpus/ch002-005/validation_report.json",
        "generated/review-corpus/ch002-005/validation_report.md",
    ]
    assert decoy.read_text(encoding="utf-8") == '{"kind":"summary_native","files":[]}\n'

    # A caller cannot preload one committed generation and then combine it
    # with a newer live manifest during its later registry/dependency reads.
    newer = json.loads(json.dumps(adopted))
    newer["identity_dependencies"]["registry_sha256"] = "f" * 64
    (range_dir / "manifest.json").write_text(
        json.dumps(newer, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert "manifest changed during freshness check" in freshness.check_fresh(
        report, range_dir, root, adopted, registry_path
    )
    (range_dir / "manifest.json").write_text(
        json.dumps(adopted, sort_keys=True) + "\n", encoding="utf-8"
    )

    malformed = json.loads(json.dumps(adopted))
    malformed["identity_dependencies"]["reverse_dependencies"]["npc:manshoon"].append(
        "generated/review-corpus/ch002-005/not-in-artifacts.md"
    )
    assert "dependency metadata is unreadable" in freshness.check_fresh(
        report, range_dir, root, malformed, registry_path
    )

    # Adoption captured the exact registry bytes, so an unrelated subject can
    # remain fresh while a used subject invalidates its reverse closure.
    registry_path.write_text(
        yaml.safe_dump(_registry(alice_alias="Allie"), sort_keys=False),
        encoding="utf-8",
    )
    assert freshness.check_fresh(report, range_dir, root, adopted, registry_path) is None
    registry_path.write_text(
        yaml.safe_dump(
            _registry(alice_alias="Allie", manshoon_alias="The Manyfaced"),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    assert "entity registry changed" in freshness.check_fresh(
        report, range_dir, root, adopted, registry_path
    )


def test_new_alias_capturing_an_unregistered_heading_invalidates_its_built_dossier(
    tmp_path: Path,
):
    """Subject precision compares grouping results, not only canonical entity keys."""
    root = tmp_path / "campaign"
    summaries = root / "summaries"
    shutil.copytree(
        Path(__file__).parent / "fixtures" / "summary_native" / "clean",
        summaries,
    )
    old_registry = _registry()
    old_registry["entities"] = [
        entity for entity in old_registry["entities"] if entity["name"] != "Manshoon"
    ]
    registry_path = root / "canon" / "entities.yaml"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(yaml.safe_dump(old_registry, sort_keys=False), encoding="utf-8")
    config_path = root / "config" / "grounding.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "summary_native:\n"
        "  out_root: generated/review-corpus\n"
        "  registry: canon/entities.yaml\n",
        encoding="utf-8",
    )

    old_loaded = load_registry(registry_path)
    assert duplicates.make_grouper(old_loaded)("npc", "Manshoon") == ("Manshoon", [])
    report = scan(summaries, root, None, None, registry=old_loaded)
    range_dir = root / "generated" / "review-corpus" / "ch002-005"
    range_dir.mkdir(parents=True)
    (range_dir / "validation_report.md").write_text(report.to_markdown(), encoding="utf-8")
    (range_dir / "validation_report.json").write_text(report.to_json(), encoding="utf-8")
    corpus.build_corpus(
        summaries,
        root,
        report,
        range_dir,
        grouper=duplicates.make_grouper(old_loaded),
        registry_sha256=_sha(registry_path.read_bytes()),
    )
    proposal = migrate.plan_dependency_adoption(root)
    migrate.apply_dependency_adoption(root, plan_sha256=proposal["plan_sha256"])
    adopted = json.loads((range_dir / "manifest.json").read_text(encoding="utf-8"))
    dependencies = adopted["identity_dependencies"]
    manshoon_path = "generated/review-corpus/ch002-005/dossiers/npc_manshoon.md"
    assert dependencies["reverse_dependencies"]["npc:manshoon"] == [
        manshoon_path,
        "generated/review-corpus/ch002-005/validation_report.json",
        "generated/review-corpus/ch002-005/validation_report.md",
    ]

    new_registry = json.loads(json.dumps(old_registry))
    new_registry["entities"][0]["aliases"].append("Manshoon")
    registry_path.write_text(yaml.safe_dump(new_registry, sort_keys=False), encoding="utf-8")
    assert duplicates.make_grouper(load_registry(registry_path))(
        "npc", "Manshoon"
    ) == ("Alice Vale", ["registry"])

    current_artifacts = {
        entry["path"]: entry["sha256"] for entry in dependencies["artifacts"]
    }
    invalidation = freshness.dependency_invalidation(
        dependencies,
        current_registry=new_registry,
        current_artifacts=current_artifacts,
        subject_headings={"npc:manshoon": [("npc", "Manshoon")]},
    )
    assert invalidation["state"] == "stale"
    assert invalidation["changed_subjects"] == ["npc:alice-vale", "npc:manshoon"]
    assert manshoon_path in invalidation["stale_paths"]
    assert "entity registry changed" in freshness.check_fresh(
        report, range_dir, root, adopted, registry_path
    )
