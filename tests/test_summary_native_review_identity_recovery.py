"""Identity dependency closure and journal-v2 recovery regressions."""
from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml

from campaignlib.registry import Entity, Registry, dump_registry, load_registry, save_registry
from pipelines.summary_native import corpus, duplicates, freshness, npc_slug, parse, schema, validate
from pipelines.summary_native import cli as summary_native_cli
from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, load_ledger
from pipelines.summary_native.authority_apply import (
    initialize_ledger,
    pending_transaction,
    recover_transaction,
)
from pipelines.summary_native.review import identity
from pipelines.summary_native.review.models import (
    IdentityProposal,
    ReviewItem,
    ReviewManifest,
    SourceCustodyGeneration,
)
from pipelines.summary_native.review.store import create_review, initialize_campaign, save_decisions


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_corpus(root: Path, registry: Registry, summary_path: Path) -> None:
    range_dir = root / "derived/summary-native/001-010"
    dossier_dir = range_dir / "dossiers"
    dossier_dir.mkdir(parents=True)
    parsed = [parse.parse_file(summary_path, root)]
    observations = corpus.build_observations(parsed, duplicates.make_grouper(registry))
    groups = corpus._group_dossiers(observations)
    artifacts = [{
        "consumer": "summary_native.build",
        "path": summary_path.relative_to(root).as_posix(),
        "sha256": _sha(summary_path.read_bytes()),
        "subject_ids": [],
        "ownership": "source",
    }]
    for (category, subject, members), filename in zip(groups, corpus.dossier_filenames(groups)):
        path = dossier_dir / filename
        data = corpus.render_dossier(category, subject, members).encode()
        path.write_bytes(data)
        artifacts.append({
            "consumer": "summary_native.build",
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(data),
            "subject_ids": [f"{schema.CATEGORY_REGISTRY_TYPE[category]}:{identity._slug(subject)}"],
            "ownership": "generated",
        })
    report = validate.scan(summary_path.parent, root, 1, 1, registry=registry)
    # Real CLI validation reports include the status of the then-current corpus.
    # A merge must rescan rather than carry this old status into advanced deps.
    report.existing_corpus = {"state": "matches"}
    report_json = report.to_json().encode()
    report_md = report.to_markdown().encode()
    report_subjects = ["npc:alice-vale", "npc:bob-stone"]
    for path, data in (
        (range_dir / "validation_report.json", report_json),
        (range_dir / "validation_report.md", report_md),
    ):
        path.write_bytes(data)
        artifacts.append({
            "consumer": "summary_native.validation",
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(data),
            "subject_ids": report_subjects,
            "ownership": "generated",
        })
    registry_bytes = (root / "docs/entity_registry.yaml").read_bytes()
    dependencies = corpus.build_dependency_manifest(
        registry=yaml.safe_load(registry_bytes),
        registry_sha256=_sha(registry_bytes),
        artifacts=artifacts,
        precision="subject",
    )
    manifest = {
        "kind": "summary_native",
        "schema": 1,
        "complete": True,
        "range": {"since": 1, "until": 10, "gaps": []},
        "files": [{
            "path": summary_path.relative_to(root).as_posix(),
            "chapter": 1,
            "sha256": _sha(summary_path.read_bytes()),
        }],
        "counts": {"files": 1, "dossiers": len(groups)},
        "canon": {"registry_sha256": _sha(registry_bytes), "canon_sha256": None},
        "identity_dependencies": dependencies,
    }
    (range_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _write_unrelated_range(root: Path, registry: Registry) -> Path:
    summary = root / "unrelated-summaries/011-summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        "# Chapter 11\n\n## Scenes\n\n### 011.01 Empty Road\n"
        "Rain fell on an empty road.\n"
    )
    range_dir = root / "derived/summary-native/011-011"
    range_dir.mkdir(parents=True)
    report = validate.scan(summary.parent, root, 11, 11, registry=registry)
    artifacts = []
    for path, data in (
        (range_dir / "validation_report.json", report.to_json().encode()),
        (range_dir / "validation_report.md", report.to_markdown().encode()),
    ):
        path.write_bytes(data)
        artifacts.append({
            "consumer": "summary_native.validation",
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(data),
            "subject_ids": [],
            "ownership": "generated",
        })
    artifacts.append({
        "consumer": "summary_native.build",
        "path": summary.relative_to(root).as_posix(),
        "sha256": _sha(summary.read_bytes()),
        "subject_ids": [],
        "ownership": "source",
    })
    registry_bytes = (root / "docs/entity_registry.yaml").read_bytes()
    manifest = {
        "kind": "summary_native",
        "schema": 1,
        "complete": True,
        "range": {"since": 11, "until": 11, "gaps": []},
        "files": [{
            "path": summary.relative_to(root).as_posix(),
            "chapter": 11,
            "sha256": _sha(summary.read_bytes()),
        }],
        "counts": {"files": 1, "dossiers": 0},
        "canon": {"registry_sha256": _sha(registry_bytes), "canon_sha256": None},
        "identity_dependencies": corpus.build_dependency_manifest(
            registry=yaml.safe_load(registry_bytes),
            registry_sha256=_sha(registry_bytes),
            artifacts=artifacts,
            precision="subject",
        ),
    }
    (range_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return range_dir


def _campaign(tmp_path: Path) -> tuple[Path, ReviewItem, bytes]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config/config.yaml").write_text("{}\n")
    (root / "config/grounding.yaml").write_text(
        "summary_native:\n  out_root: derived/summary-native\n  summaries_dir: summaries\n"
    )
    (root / "config/npc_dossiers.yaml").write_text(
        "npc_root: docs/npcs/summary_native\n"
    )
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="identity-recovery", revision=1),
        actor="test",
    )
    campaign = initialize_campaign(root)
    registry = Registry(
        version=1,
        campaign="identity-recovery",
        entities=[
            Entity(name="Alice Vale", type="npc", aliases=["Alice"], provenance="module", source="Fixture"),
            Entity(name="Bob Stone", type="npc", aliases=["Bobby"], provenance="supplement", source="Fixture"),
        ],
    )
    registry_path = root / "docs/entity_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    save_registry(registry, registry_path)

    summary = root / "summaries/001-summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text(
        "# Chapter 1\n\n## Scenes\n\n### 001.01 Meeting\n"
        "Alice Vale met Bob Stone.\n\n## NPCs\n\n### Alice Vale\n"
        "Alice watched the gate.\n\n### Bob Stone\nBob guarded the gate.\n"
    )
    summary_before = summary.read_bytes()
    _write_corpus(root, registry, summary)

    authored = root / "docs/npcs/authored/bob-stone.authored.yaml"
    authored.parent.mkdir(parents=True)
    authored.write_text("subject: Bob Stone\nmanual:\n  - Keeps the old authored fact.\n")
    published = root / f"{schema.NPCS_DIR}/{npc_slug.slug_for('Bob Stone')}.md"
    published.write_text("# Bob Stone\n\nPublished generated prose.\n")
    npc_range = root / "docs/npcs/summary_native/ch001-010"
    stem = npc_slug.stem_for("npc", "Bob Stone")
    for folder, text in (
        ("evidence", "---\nsubject: Bob Stone\n---\n\nEvidence.\n"),
        ("draft", "---\nsubject: Bob Stone\n---\n\nGenerated draft.\n"),
        ("gm", "<!-- npc: Bob Stone -->\n\nGenerated GM dossier.\n"),
    ):
        path = npc_range / folder / f"{stem}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (npc_range / "link_manifest.json").write_text(json.dumps({
        "kind": "npc_link",
        "evidence": {stem: _sha((npc_range / "evidence" / f"{stem}.md").read_bytes())},
    }, sort_keys=True) + "\n")
    nested = root / "derived/summary-native/001-010/npcs/drafts" / f"{stem}.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("---\nsubject: Bob Stone\n---\n\nNested generated draft.\n")

    excerpt = "Alice Vale met Bob Stone."
    item = ReviewItem(
        item_id="alice-bob",
        revision=1,
        campaign_id=campaign.campaign_id,
        review_id="identity-review",
        domain="duplicate_identity",
        subject_ref={
            "subject_id": UUID("10000000-0000-4000-8000-000000000001"),
            "kind": "pair",
            "registry_name": "Alice Vale / Bob Stone",
            "registry_type": "pair",
            "registry_snapshot_sha256": _sha(registry_path.read_bytes()),
        },
        occurrence_id=UUID("20000000-0000-4000-8000-000000000001"),
        locator={"source_path": "summaries/001-summary.md", "anchor": "meeting"},
        claim_text="Alice Vale and Bob Stone may be the same identity.",
        evidence=({
            "source_id": "summary-1",
            "source_path": "summaries/001-summary.md",
            "anchor": "meeting",
            "exact_excerpt": excerpt,
            "selected_span_sha256": _sha(excerpt.encode()),
            "citation_resolved": True,
        },),
        diagnostics=({
            "diagnostic_id": "duplicate-alice-bob",
            "legacy_code": "possible-duplicate",
            "message": "Explicit identity review required.",
            "blocking": False,
        },),
        categories={"unsupported_or_contradicted"},
        severity="needs_judgment",
        assignment_basis="advisory_candidate",
        rationale="The GM must select a canonical survivor.",
        proposed_action={
            "action": "adjudicate_identity",
            "details": {
                "pair_id": "alice-bob",
                "candidates": [
                    {
                        "subject_id": "30000000-0000-4000-8000-000000000001",
                        "registry_name": "Alice Vale",
                    },
                    {
                        "subject_id": "30000000-0000-4000-8000-000000000002",
                        "registry_name": "Bob Stone",
                    },
                ],
            },
        },
        scope={"kind": "global"},
        rule_versions=({"rule_id": "duplicate-review", "version": "1"},),
        input_bindings=({
            "source_id": "summary-1",
            "path": "summaries/001-summary.md",
            "custody_sha256": _sha(summary_before),
            "semantic_sha256": _sha(excerpt.encode()),
        },),
    )
    custody = SourceCustodyGeneration(
        campaign_id=campaign.campaign_id,
        review_id="identity-review",
        generation=1,
        recorded_at=NOW,
        sources=({
            "source_id": "summary-1",
            "path": "summaries/001-summary.md",
            "sha256": _sha(summary_before),
            "size": len(summary_before),
        },),
    )
    manifest = ReviewManifest(
        campaign_id=campaign.campaign_id,
        review_id="identity-review",
        kind="duplicate_identity",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=({"kind": "pair", "id": item.item_id},),
        items=({
            "campaign_id": campaign.campaign_id,
            "review_id": "identity-review",
            "item_id": item.item_id,
            "revision": item.revision,
            "review_digest": item.review_digest,
        },),
        source_manifest={
            "campaign_id": campaign.campaign_id,
            "review_id": "identity-review",
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "duplicate-review", "version": "1"},),
    )
    create_review(root, manifest, custody, [item])
    return root, item, summary_before


def _proposal(root: Path) -> IdentityProposal:
    proposals = identity.prepare_identity_alternatives(
        root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )
    return next(proposal for proposal in proposals if proposal.canonical_registry_name == "Alice Vale")


def _approve(root: Path, item: ReviewItem, proposal: IdentityProposal) -> None:
    save_decisions(root, "identity-review", {
        "version": 1,
        "request_id": "approve-alice",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": 0,
            "verdict": "approve",
            "disposition": "merge",
            "note": "Retain Alice Vale as the canonical identity.",
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
        }],
    })


def _apply(root: Path, proposal: IdentityProposal):
    return identity.apply_identity_proposal(
        root,
        "identity-review",
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal.proposal_digest,
    )


def test_complete_closure_stages_create_replace_delete_and_pending_generation(tmp_path: Path):
    root, item, summary_before = _campaign(tmp_path)
    proposal = _proposal(root)

    operations = {(target.path, target.operation.value) for target in proposal.targets}
    assert ("docs/entity_registry.yaml", "replace") in operations
    assert ("docs/npcs/authored/alice-vale.authored.yaml", "create") in operations
    assert ("docs/npcs/authored/bob-stone.authored.yaml", "delete") in operations
    assert ("derived/summary-native/001-010/dossiers/npc_alice_vale.md", "replace") in operations
    assert ("derived/summary-native/001-010/dossiers/npc_bob_stone.md", "delete") in operations
    assert "summaries/001-summary.md" in proposal.inspected_paths
    expected_generation = {
        "docs/npcs/bob-stone.md",
        "docs/npcs/summary_native/ch001-010/evidence/npc_bob_stone.md",
        "docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md",
        "docs/npcs/summary_native/ch001-010/gm/npc_bob_stone.md",
        "docs/npcs/summary_native/ch001-010/link_manifest.json",
        "derived/summary-native/001-010/npcs/drafts/npc_bob_stone.md",
    }
    assert expected_generation <= set(proposal.generative_rebuilds)
    assert any(target.path.endswith("validation_report.json") for target in proposal.targets)
    assert any(target.path.endswith("validation_report.md") for target in proposal.targets)
    assert "derived/summary-native/001-010/validation_report.json" in proposal.affected_paths

    _approve(root, item, proposal)
    receipt = _apply(root, proposal)

    assert (root / "summaries/001-summary.md").read_bytes() == summary_before
    assert not (root / "docs/npcs/authored/bob-stone.authored.yaml").exists()
    assert "subject: Alice Vale" in (root / "docs/npcs/authored/alice-vale.authored.yaml").read_text()
    assert (root / "docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md").is_file()
    assert {
        value.removeprefix("regenerate and review ")
        for value in receipt.remaining_review_work
    } >= expected_generation
    manifest = json.loads((root / "derived/summary-native/001-010/manifest.json").read_text())
    report_dependencies = [
        artifact for artifact in manifest["identity_dependencies"]["artifacts"]
        if artifact["consumer"] == "summary_native.validation"
    ]
    assert len(report_dependencies) == 2
    for artifact in report_dependencies:
        assert artifact["sha256"] == _sha((root / artifact["path"]).read_bytes())
    registry = load_registry(root / "docs/entity_registry.yaml")
    assert [entity.name for entity in registry.entities] == ["Alice Vale"]
    assert _apply(root, proposal) == receipt


def test_interrupted_identity_apply_recovers_forward_and_replays(tmp_path: Path, monkeypatch):
    root, item, summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)

    def stop_after_prepare(*_args, **_kwargs):
        raise RuntimeError("simulated identity apply interruption")

    monkeypatch.setattr(identity, "recover_transaction", stop_after_prepare)
    with pytest.raises(RuntimeError, match="simulated"):
        _apply(root, proposal)
    pending = pending_transaction(root)
    assert pending is not None

    recover_transaction(root, pending["id"])
    monkeypatch.undo()
    receipt = _apply(root, proposal)

    assert receipt.proposal_digest == proposal.proposal_digest
    assert (root / "summaries/001-summary.md").read_bytes() == summary_before
    assert load_registry(root / "docs/entity_registry.yaml").entities[0].name == "Alice Vale"
    assert not (root / "docs/npcs/authored/bob-stone.authored.yaml").exists()
    assert (root / "docs/npcs/authored/alice-vale.authored.yaml").is_file()
    assert _apply(root, proposal) == receipt


def test_recovery_refuses_unexpected_bytes_before_writing_any_other_target(tmp_path: Path, monkeypatch):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)

    monkeypatch.setattr(
        identity,
        "recover_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("stop")),
    )
    with pytest.raises(RuntimeError, match="stop"):
        _apply(root, proposal)
    pending = pending_transaction(root)
    assert pending is not None
    registry_path = root / "docs/entity_registry.yaml"
    registry_path.write_bytes(registry_path.read_bytes() + b"\n# unexpected\n")
    destination = root / "docs/npcs/authored/alice-vale.authored.yaml"
    loser = root / "docs/npcs/authored/bob-stone.authored.yaml"
    loser_before = loser.read_bytes()

    with pytest.raises(AuthorityError, match="AUTH_UNEXPECTED_RECOVERY_BYTES"):
        recover_transaction(root, pending["id"])

    assert not destination.exists()
    assert loser.read_bytes() == loser_before


def test_apply_refuses_changed_unchanged_summary_dependency(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    registry_before = (root / "docs/entity_registry.yaml").read_bytes()
    summary = root / "summaries/001-summary.md"
    summary.write_text(summary.read_text() + "\nLater evidence edit.\n")

    with pytest.raises(identity.IdentityReviewError, match="REVIEW_STALE_IDENTITY"):
        _apply(root, proposal)

    assert (root / "docs/entity_registry.yaml").read_bytes() == registry_before
    assert not (root / "docs/npcs/authored/alice-vale.authored.yaml").exists()


def test_historical_loser_references_remain_readable_after_merge(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    loser_subject_id = proposal.loser_subject_id
    _approve(root, item, proposal)

    receipt = _apply(root, proposal)
    stored = IdentityProposal.model_validate_json(
        (root / f"docs/reviews/identity-review/proposals/{proposal.proposal_id}.json").read_bytes()
    )
    ledger = load_ledger(root)

    assert stored.loser_subject_id == loser_subject_id
    assert receipt.loser_subject_id == loser_subject_id
    assert any(
        getattr(record, "proposal", None) is not None
        and record.proposal.id == proposal.proposal_id
        for record in ledger.records
    )


def test_regeneration_selection_is_receipt_bound_affected_only_and_pending_review(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    selected = [
        "docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md",
        "docs/npcs/bob-stone.md",
    ]

    plan = identity.prepare_identity_regeneration(
        root, "identity-review", receipt_id=receipt.receipt_id, selected_paths=selected
    )

    assert plan["selected_paths"] == selected
    assert plan["publication_state"] == "pending_review"
    assert all(job["requires_review_signoff"] for job in plan["jobs"])
    assert [job["stage"] for job in plan["jobs"]] == ["npc-draft"]
    assert plan["pending_signoff_paths"] == ["docs/npcs/bob-stone.md"]
    assert plan["jobs"][0]["input_paths"] == [selected[0]]
    assert plan["jobs"][0]["selected_outputs"] == [
        "docs/npcs/summary_native/ch001-010/draft/npc_alice_vale.md"
    ]
    assert plan["jobs"][0]["stale_cleanup_paths"] == [selected[0]]
    assert plan["jobs"][0]["argv"][-3:] == ["--name", "Alice Vale", "--force"]
    assert all("npc-publish" not in job["argv"] for job in plan["jobs"])
    assert identity.prepare_identity_regeneration(
        root, "identity-review", receipt_id=receipt.receipt_id, selected_paths=selected
    ) == plan
    with pytest.raises(identity.IdentityReviewError, match="empty"):
        identity.prepare_identity_regeneration(
            root, "identity-review", receipt_id=receipt.receipt_id, selected_paths=[]
        )


def test_regeneration_executes_parser_compatible_argv_outside_writer_lock_and_persists_failure(
    tmp_path: Path, monkeypatch,
):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    selected = ["docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md"]
    held = False
    original_lock = identity.authority_lock

    @contextmanager
    def tracked_lock(*args, **kwargs):
        nonlocal held
        with original_lock(*args, **kwargs):
            held = True
            try:
                yield
            finally:
                held = False

    calls = []

    def failed_runner(argv, cwd):
        assert held is False
        calls.append((argv, cwd))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(identity, "authority_lock", tracked_lock)
    result = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=selected,
        runner=failed_runner,
    )

    assert len(calls) == 1
    assert calls[0][0][1] == "npc-draft"
    assert result["results"][0]["state"] == "failed"
    assert result["complete"] is False
    persisted = list((root / "docs/reviews/identity-review/runs/identity-regeneration").glob("*.result.json"))
    assert len(persisted) == 1
    assert json.loads(persisted[0].read_text())["returncode"] == 7
    replay = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=selected,
        runner=lambda *_args: pytest.fail("durable failed job must not run implicitly"),
    )
    assert replay == result


def test_partial_npc_link_selection_refuses_broadening(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)

    with pytest.raises(identity.IdentityReviewError, match="npc-link would broaden"):
        identity.prepare_identity_regeneration(
            root,
            "identity-review",
            receipt_id=receipt.receipt_id,
            selected_paths=["docs/npcs/summary_native/ch001-010/link_manifest.json"],
        )


def test_successful_bounded_draft_runner_writes_canonical_output_and_cleans_loser(
    tmp_path: Path,
):
    root, item, summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    loser = "docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md"
    canonical = root / "docs/npcs/summary_native/ch001-010/draft/npc_alice_vale.md"
    calls = []

    def producer(argv, cwd):
        calls.append(argv)
        assert argv[1] == "npc-draft"
        assert argv[-3:] == ["--name", "Alice Vale", "--force"]
        canonical.write_text("---\nsubject: Alice Vale\n---\n\nRegenerated.\n")
        return SimpleNamespace(returncode=0)

    result = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=[loser],
        runner=producer,
    )

    assert len(calls) == 1
    assert canonical.is_file()
    assert not (root / loser).exists()
    assert (root / "summaries/001-summary.md").read_bytes() == summary_before
    assert result["results"][0]["selected_outputs"] == [canonical.relative_to(root).as_posix()]
    assert result["pending_review_signoff"] == [canonical.relative_to(root).as_posix()]
    identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=[loser],
        runner=lambda *_args: pytest.fail("successful model job must replay without rerun"),
    )


def test_cleanup_refuses_concurrent_loser_edit_without_any_cleanup_write(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    loser = root / "docs/npcs/summary_native/ch001-010/draft/npc_bob_stone.md"
    canonical = root / "docs/npcs/summary_native/ch001-010/draft/npc_alice_vale.md"

    def racing_producer(_argv, _cwd):
        canonical.write_text("---\nsubject: Alice Vale\n---\n\nGenerated.\n")
        loser.write_text("human edit during generation\n")
        return SimpleNamespace(returncode=0)

    with pytest.raises(identity.IdentityReviewError, match="cleanup target changed"):
        identity.execute_identity_regeneration(
            root,
            "identity-review",
            receipt_id=receipt.receipt_id,
            selected_paths=[loser.relative_to(root).as_posix()],
            runner=racing_producer,
        )

    assert loser.read_text() == "human edit during generation\n"
    assert canonical.is_file()
    results = list(
        (root / "docs/reviews/identity-review/runs/identity-regeneration").glob("*.result.json")
    )
    assert len(results) == 1
    assert json.loads(results[0].read_text())["state"] == "generated_pending_cleanup"
    with pytest.raises(identity.IdentityReviewError, match="cleanup target changed"):
        identity.execute_identity_regeneration(
            root,
            "identity-review",
            receipt_id=receipt.receipt_id,
            selected_paths=[loser.relative_to(root).as_posix()],
            runner=lambda *_args: pytest.fail("producer must not rerun before cleanup resumes"),
        )


def test_actual_compose_producer_writes_only_canonical_selected_output(tmp_path: Path):
    root, item, summary_before = _campaign(tmp_path)
    old_gm = root / "docs/npcs/summary_native/ch001-001/gm/npc_bob_stone.md"
    old_gm.parent.mkdir(parents=True)
    old_gm.write_text("<!-- old generated Bob dossier -->\n")
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    canonical_draft = root / "docs/npcs/summary_native/ch001-001/draft/npc_alice_vale.md"
    canonical_draft.parent.mkdir(parents=True)
    canonical_draft.write_text("---\nsubject: Alice Vale\n---\n\n# Alice Vale\n\nCurrent draft.\n")
    unrelated = root / "docs/npcs/summary_native/ch001-001/gm/unrelated.md"
    unrelated.write_text("unchanged\n")

    def actual_cli(argv, cwd):
        return SimpleNamespace(returncode=summary_native_cli.main(argv[1:]))

    result = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=[old_gm.relative_to(root).as_posix()],
        runner=actual_cli,
    )
    canonical_gm = root / "docs/npcs/summary_native/ch001-001/gm/npc_alice_vale.md"

    assert result["results"][0]["returncode"] == 0
    assert canonical_gm.is_file()
    assert "npc: Alice Vale" in canonical_gm.read_text()
    assert not old_gm.exists()
    assert unrelated.read_text() == "unchanged\n"
    assert (root / "summaries/001-summary.md").read_bytes() == summary_before
    with pytest.raises(identity.IdentityReviewError, match="broaden"):
        identity.prepare_identity_regeneration(
            root,
            "identity-review",
            receipt_id=receipt.receipt_id,
            selected_paths=["docs/npcs/unrelated.md"],
        )


def test_complete_npc_link_range_executes_without_name_broadening(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)
    selected = [
        "docs/npcs/summary_native/ch001-010/evidence/npc_bob_stone.md",
        "docs/npcs/summary_native/ch001-010/link_manifest.json",
    ]
    calls = []

    def deterministic_link(argv, cwd):
        calls.append(argv)
        assert argv[1] == "npc-link"
        assert "--name" not in argv
        assert argv[-1] == "--force"
        range_dir = root / "docs/npcs/summary_native/ch001-010"
        (range_dir / "evidence/npc_alice_vale.md").write_text(
            "---\nsubject: Alice Vale\n---\n\nRelinked evidence.\n"
        )
        for name in ("link_manifest.json", "link_report.json", "link_report.md"):
            (range_dir / name).write_text("{}\n" if name.endswith(".json") else "# Link report\n")
        return SimpleNamespace(returncode=0)

    result = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=selected,
        runner=deterministic_link,
    )

    assert len(calls) == 1
    assert result["results"][0]["selected_outputs"] == [
        "docs/npcs/summary_native/ch001-010/evidence/npc_alice_vale.md",
        "docs/npcs/summary_native/ch001-010/link_manifest.json",
        "docs/npcs/summary_native/ch001-010/link_report.json",
        "docs/npcs/summary_native/ch001-010/link_report.md",
    ]
    assert result["results"][0]["state"] == "generated_pending_review"
    assert not (root / selected[0]).exists()


def test_actual_npc_link_producer_relinks_complete_receipt_bound_range(tmp_path: Path):
    root, item, summary_before = _campaign(tmp_path)
    source_range = root / "derived/summary-native/001-010"
    range_dir = root / "derived/summary-native/ch001-001"
    shutil.copytree(source_range, range_dir)
    manifest_path = range_dir / "manifest.json"
    manifest = json.loads(
        manifest_path.read_text().replace(
            "derived/summary-native/001-010/", "derived/summary-native/ch001-001/"
        )
    )
    manifest["range"] = {"since": 1, "until": 1, "gaps": []}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    npc_range = root / "docs/npcs/summary_native/ch001-001"
    evidence = npc_range / "evidence/npc_bob_stone.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("---\nsubject: Bob Stone\n---\n\nBob Stone guarded the gate.\n")
    link_manifest = npc_range / "link_manifest.json"
    link_manifest.write_text('{"kind":"npc_link","evidence":{"npc_bob_stone":"old"}}\n')
    proposal = _proposal(root)
    _approve(root, item, proposal)
    receipt = _apply(root, proposal)

    result = identity.execute_identity_regeneration(
        root,
        "identity-review",
        receipt_id=receipt.receipt_id,
        selected_paths=[
            evidence.relative_to(root).as_posix(),
            link_manifest.relative_to(root).as_posix(),
        ],
        runner=lambda argv, cwd: SimpleNamespace(
            returncode=summary_native_cli.main(argv[1:])
        ),
    )

    assert result["results"][0]["returncode"] == 0
    assert (npc_range / "evidence/npc_alice_vale.md").is_file()
    assert not evidence.exists()
    assert (npc_range / "link_report.json").is_file()
    assert (npc_range / "link_report.md").is_file()
    assert (root / "summaries/001-summary.md").read_bytes() == summary_before


def test_concurrent_legacy_registry_edit_refuses_with_zero_partial_writes(tmp_path: Path):
    root, item, _summary_before = _campaign(tmp_path)
    proposal = _proposal(root)
    _approve(root, item, proposal)
    authored = root / "docs/npcs/authored/bob-stone.authored.yaml"
    authored_before = authored.read_bytes()
    registry = root / "docs/entity_registry.yaml"
    registry.write_bytes(registry.read_bytes() + b"\n# concurrent legacy writer\n")

    with pytest.raises(identity.IdentityReviewError, match="REVIEW_STALE_IDENTITY"):
        _apply(root, proposal)

    assert authored.read_bytes() == authored_before
    assert not (root / "docs/npcs/authored/alice-vale.authored.yaml").exists()
    assert not (root / "docs/reviews/identity-review/receipts" / f"receipt-{proposal.proposal_id}.json").exists()


def test_incomplete_manifest_and_symlink_alias_block_bounded_alternatives(tmp_path: Path):
    malformed_root, _item, _summary = _campaign(tmp_path / "malformed")
    manifest = malformed_root / "derived/summary-native/001-010/manifest.json"
    raw = json.loads(manifest.read_text())
    raw.pop("identity_dependencies")
    manifest.write_text(json.dumps(raw, sort_keys=True) + "\n")

    malformed = identity.prepare_identity_alternatives(
        malformed_root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )
    assert all(not proposal.applicable for proposal in malformed)
    assert all(
        "REVIEW_IDENTITY_INVENTORY_INCOMPLETE" in proposal.blocked_reasons
        for proposal in malformed
    )

    symlink_root, _item, _summary = _campaign(tmp_path / "symlink")
    authored = symlink_root / "docs/npcs/authored"
    (authored / "bob-alias.authored.yaml").symlink_to("bob-stone.authored.yaml")
    symlinked = identity.prepare_identity_alternatives(
        symlink_root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )
    assert all(not proposal.applicable for proposal in symlinked)
    assert all("REVIEW_IDENTITY_SYMLINK_ALIAS" in proposal.blocked_reasons for proposal in symlinked)


def test_new_decision_revision_gets_new_immutable_preview_ids(tmp_path: Path):
    root, item, _summary = _campaign(tmp_path)
    first = identity.prepare_identity_alternatives(
        root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )
    selected = next(
        proposal for proposal in first if proposal.canonical_registry_name == "Alice Vale"
    )
    _approve(root, item, selected)

    second = identity.prepare_identity_alternatives(
        root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=1,
        requested_scope={"kind": "global"},
    )

    assert {proposal.proposal_id for proposal in first}.isdisjoint(
        proposal.proposal_id for proposal in second
    )
    proposal_dir = root / "docs/reviews/identity-review/proposals"
    assert {path.stem for path in proposal_dir.glob("identity-*.json")} == {
        *(proposal.proposal_id for proposal in first),
        *(proposal.proposal_id for proposal in second),
    }


def test_unchanged_prepare_retry_returns_same_immutable_proposals(tmp_path: Path):
    root, _item, _summary = _campaign(tmp_path)
    first = identity.prepare_identity_alternatives(
        root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )
    proposal_dir = root / "docs/reviews/identity-review/proposals"
    before = {path.name: path.read_bytes() for path in proposal_dir.glob("identity-*.json")}

    second = identity.prepare_identity_alternatives(
        root,
        "identity-review",
        "alice-bob",
        expected_decision_revision=0,
        requested_scope={"kind": "global"},
    )

    assert second == first
    assert {path.name: path.read_bytes() for path in proposal_dir.glob("identity-*.json")} == before


def test_configured_registry_path_is_the_only_registry_mutation_target(tmp_path: Path):
    root, _item, _summary = _campaign(tmp_path)
    default = root / "docs/entity_registry.yaml"
    configured = root / "campaign-data/canonical-entities.yaml"
    configured.parent.mkdir(parents=True)
    configured.write_bytes(default.read_bytes())
    default.unlink()
    (root / "config/grounding.yaml").write_text(
        "summary_native:\n"
        "  out_root: derived/summary-native\n"
        "  summaries_dir: summaries\n"
        "  registry: campaign-data/canonical-entities.yaml\n"
    )

    proposal = _proposal(root)

    operations = {(target.path, target.operation.value) for target in proposal.targets}
    assert ("campaign-data/canonical-entities.yaml", "replace") in operations
    assert all(target.path != "docs/entity_registry.yaml" for target in proposal.targets)


def test_merge_preserves_opaque_registry_and_survivor_entity_metadata(tmp_path: Path):
    root, item, _summary = _campaign(tmp_path)
    registry_path = root / "docs/entity_registry.yaml"
    raw = yaml.safe_load(registry_path.read_text())
    raw["operator_metadata"] = {"keep": "original"}
    next(entity for entity in raw["entities"] if entity["name"] == "Alice Vale")[
        "operator_tag"
    ] = {"keep": True}
    registry_path.write_text(yaml.safe_dump(raw, sort_keys=False))

    proposal = _proposal(root)
    _approve(root, item, proposal)
    _apply(root, proposal)
    after = yaml.safe_load(registry_path.read_text())

    assert after["operator_metadata"] == {"keep": "original"}
    assert after["entities"][0]["operator_tag"] == {"keep": True}


def test_unrelated_precise_range_remains_byte_identical_and_current(tmp_path: Path):
    root, item, _summary = _campaign(tmp_path)
    registry = load_registry(root / "docs/entity_registry.yaml")
    unrelated = _write_unrelated_range(root, registry)
    before = {path.relative_to(unrelated): path.read_bytes() for path in unrelated.rglob("*") if path.is_file()}
    proposal = _proposal(root)
    _approve(root, item, proposal)
    _apply(root, proposal)
    after = {path.relative_to(unrelated): path.read_bytes() for path in unrelated.rglob("*") if path.is_file()}
    report = validate.scan(root / "unrelated-summaries", root, 11, 11, registry=load_registry(root / "docs/entity_registry.yaml"))
    manifest = json.loads((unrelated / "manifest.json").read_text())

    assert after == before
    assert freshness.check_fresh(
        report, unrelated, root, manifest, root / "docs/entity_registry.yaml"
    ) is None
