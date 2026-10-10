"""T039 identity proposal, application, and refusal contracts."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

import pytest
import yaml

from campaignlib.registry import Entity, Registry, load_registry, save_registry
from pipelines.summary_native import corpus, duplicates
from pipelines.summary_native.authority import (
    AuthorityLedger,
    ReviewDecisionRecord,
    load_ledger,
    validate_record_identity,
)
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review.models import (
    IdentityProposal,
    IdentityReceipt,
    ReviewItem,
    ReviewManifest,
    SourceCustodyGeneration,
)
from pipelines.summary_native.review.store import (
    create_review,
    history,
    initialize_campaign,
    read_snapshot,
    review_status,
    save_decisions,
)


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "summary_native_review" / "duplicates.json"
PAIR_NAMESPACE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _identity_module():
    try:
        return importlib.import_module("pipelines.summary_native.review.identity")
    except ModuleNotFoundError:
        pytest.fail("implement pipelines.summary_native.review.identity", pytrace=False)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _subject_id(pair_id: str, side: str) -> UUID:
    return uuid5(PAIR_NAMESPACE, f"{pair_id}:{side}")


def _pair_scope(pair: dict) -> dict[str, str]:
    if pair["case"] == "scoped_alias":
        return {"kind": "chapter", "value": "2"}
    return {"kind": "global"}


def _duplicate_observations(pair: dict, excerpt: str):
    return [
        corpus.Observation(
            pair["type"],
            name,
            name,
            (),
            1,
            "summaries/001/session-summary.md",
            None,
            index,
            excerpt,
        )
        for index, name in enumerate((pair["a"], pair["b"]), 1)
    ]


@pytest.fixture
def identity_campaign(tmp_path: Path) -> tuple[Path, list[dict], tuple[ReviewItem, ...]]:
    pairs = json.loads(FIXTURE.read_text())["pairs"]
    assert len(pairs) == 38
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n")
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="identity-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(root)

    entities: list[Entity] = []
    distinct: list[list[str]] = []
    rejected: list[list[str]] = []
    summary_lines = ["# Identity evidence", ""]
    for pair in pairs:
        a_type = pair["type"]
        b_type = (
            ("npc" if a_type == "location" else "location")
            if pair["case"] == "type_mismatch"
            else a_type
        )
        b_scope = "chapter-2" if pair["case"] == "nonpersistent_entity" else "persistent"
        entities.extend((
            Entity(
                name=pair["a"], type=a_type, aliases=[f"{pair['a']} Alias"],
                provenance="module", source="Fixture", scope="persistent",
                note=f"review subject {pair['id']} A",
            ),
            Entity(
                name=pair["b"], type=b_type, aliases=[f"{pair['b']} Alias"],
                provenance="supplement", source="Fixture", scope=b_scope,
                note=f"review subject {pair['id']} B",
            ),
        ))
        if pair["case"] == "distinct_guard":
            distinct.append([pair["a"], pair["b"]])
        if pair["case"] == "rejected_alias_guard":
            rejected.append([pair["a"], pair["b"]])
        summary_lines.append(
            f"{pair['a']} met {pair['b']}; {pair['b']} betrayed {pair['a']}."
        )

        if pair["case"] == "path_collision":
            published = root / "docs" / "npcs" / "published"
            published.mkdir(parents=True, exist_ok=True)
            (published / f"{_slug(pair['a'])}.md").write_text(f"# {pair['a']}\n\nA record.\n")
            (published / f"{_slug(pair['b'])}.md").write_text(f"# {pair['b']}\n\nDifferent record.\n")
        if pair["case"] == "authored_conflict":
            authored = root / "docs" / "npcs" / "authored"
            authored.mkdir(parents=True, exist_ok=True)
            (authored / f"{_slug(pair['a'])}.md").write_text(f"# {pair['a']}\n\nAuthored A.\n")
            (authored / f"{_slug(pair['b'])}.md").write_text(f"# {pair['b']}\n\nAuthored B.\n")

    registry_path = root / "docs" / "entity_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    save_registry(
        Registry(
            version=1,
            campaign="identity-fixture",
            entities=entities,
            distinct=distinct,
            rejected_aliases=rejected,
        ),
        registry_path,
    )
    registry_sha256 = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    summary_bytes = ("\n".join(summary_lines) + "\n").encode()
    summary = root / "summaries" / "001" / "session-summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_bytes(summary_bytes)
    source_sha256 = hashlib.sha256(summary_bytes).hexdigest()

    items: list[ReviewItem] = []
    for pair in pairs:
        excerpt = f"{pair['a']} met {pair['b']}; {pair['b']} betrayed {pair['a']}."
        evidence_digest = duplicates.duplicate_evidence_digest(
            pair["type"],
            pair["a"],
            pair["b"],
            _duplicate_observations(pair, excerpt),
            {"kind": "global", "value": None},
        )
        item = ReviewItem(
            item_id=pair["id"],
            revision=1,
            campaign_id=identity.campaign_id,
            review_id="duplicate-review",
            domain="duplicate_identity",
            subject_ref={
                "subject_id": uuid5(PAIR_NAMESPACE, pair["id"]),
                "kind": "pair",
                "registry_name": f"{pair['a']} / {pair['b']}",
                "registry_type": "pair",
                "registry_snapshot_sha256": registry_sha256,
            },
            occurrence_id=uuid5(PAIR_NAMESPACE, f"occurrence:{pair['id']}"),
            locator={
                "source_path": "summaries/001/session-summary.md",
                "anchor": pair["id"],
            },
            claim_text=f"{pair['a']} and {pair['b']} may be the same identity.",
            evidence=({
                "source_id": "summary-1",
                "source_path": "summaries/001/session-summary.md",
                "anchor": pair["id"],
                "exact_excerpt": excerpt,
                "selected_span_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                "citation_resolved": True,
            },),
            diagnostics=({
                "diagnostic_id": f"duplicate-{pair['id']}",
                "legacy_code": "possible-duplicate",
                "message": "Explicit GM identity review required.",
                "blocking": False,
                "details": {"fixture_case": pair["case"]},
            },),
            categories={"unsupported_or_contradicted"},
            severity="needs_judgment",
            assignment_basis="advisory_candidate",
            rationale="Similarity is a candidate, not merge authority.",
            proposed_action={
                "action": "adjudicate_identity",
                "details": {
                    "pair_id": pair["id"],
                    "category": pair["type"],
                    "evidence_digest": evidence_digest,
                    "candidates": [
                        {"subject_id": str(_subject_id(pair["id"], "a")), "registry_name": pair["a"]},
                        {"subject_id": str(_subject_id(pair["id"], "b")), "registry_name": pair["b"]},
                    ],
                },
            },
            scope={"kind": "global"},
            rule_versions=({"rule_id": "duplicate-review", "version": "1"},),
            input_bindings=({
                "source_id": "summary-1",
                "path": "summaries/001/session-summary.md",
                "custody_sha256": source_sha256,
                "semantic_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            },),
        )
        items.append(item)

    custody = SourceCustodyGeneration(
        campaign_id=identity.campaign_id,
        review_id="duplicate-review",
        generation=1,
        recorded_at=NOW,
        sources=({
            "source_id": "summary-1",
            "path": "summaries/001/session-summary.md",
            "sha256": source_sha256,
            "size": len(summary_bytes),
        },),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id,
        review_id="duplicate-review",
        kind="duplicate_identity",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=tuple({"kind": "pair", "id": pair["id"]} for pair in pairs),
        items=tuple({
            "campaign_id": identity.campaign_id,
            "review_id": "duplicate-review",
            "item_id": item.item_id,
            "revision": item.revision,
            "review_digest": item.review_digest,
        } for item in items),
        source_manifest={
            "campaign_id": identity.campaign_id,
            "review_id": "duplicate-review",
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "duplicate-review", "version": "1"},),
    )
    create_review(root, manifest, custody, items)
    return root, pairs, tuple(items)


def _alternatives(root: Path, item_id: str, scope: dict[str, str]) -> tuple[IdentityProposal, ...]:
    module = _identity_module()
    prepare = getattr(module, "prepare_identity_alternatives", None)
    assert callable(prepare), "implement identity.prepare_identity_alternatives"
    return tuple(prepare(
        root,
        "duplicate-review",
        item_id,
        expected_decision_revision=0,
        requested_scope=scope,
    ))


def _apply(root: Path, proposal: IdentityProposal) -> IdentityReceipt:
    module = _identity_module()
    apply = getattr(module, "apply_identity_proposal", None)
    assert callable(apply), "implement identity.apply_identity_proposal"
    return apply(
        root,
        "duplicate-review",
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal.proposal_digest,
    )


def _approve(root: Path, item: ReviewItem, proposal: IdentityProposal) -> None:
    save_decisions(root, "duplicate-review", {
        "version": 1,
        "request_id": f"approve-{item.item_id}",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": 0,
            "verdict": "approve",
            "disposition": "merge",
            "note": f"Use {proposal.canonical_registry_name} as the canonical identity.",
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
        }],
    })


def _decide_distinct(root: Path, item: ReviewItem, *, expected_revision: int = 0) -> None:
    save_decisions(root, "duplicate-review", {
        "version": 1,
        "request_id": f"distinct-{item.item_id}-{expected_revision}",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": expected_revision,
            "verdict": "approve",
            "disposition": "distinct",
            "note": "Distinct within this exact reviewed scope and evidence.",
            "proposal_id": None,
            "proposal_digest": None,
        }],
    })


def test_all_38_selected_pairs_have_two_bounded_canonical_alternatives(identity_campaign):
    root, pairs, items = identity_campaign
    manifest, _, stored_items = read_snapshot(root, "duplicate-review")
    assert len(manifest.selection) == len(stored_items) == len(items) == 38
    assert [entry.id for entry in manifest.selection] == [pair["id"] for pair in pairs]

    for pair in pairs:
        alternatives = _alternatives(root, pair["id"], _pair_scope(pair))
        assert len(alternatives) == 2
        assert {proposal.canonical_registry_name for proposal in alternatives} == {pair["a"], pair["b"]}
        assert {proposal.survivor_subject_id for proposal in alternatives} == {
            _subject_id(pair["id"], "a"),
            _subject_id(pair["id"], "b"),
        }
        assert all(proposal.kind == "identity_merge" for proposal in alternatives)
        assert all(len(proposal.decision_bindings) == 1 for proposal in alternatives)
        assert all(proposal.decision_bindings[0].item_id == pair["id"] for proposal in alternatives)


@pytest.mark.parametrize(("pair_id", "reason"), [
    ("pair-02", "REVIEW_SCOPED_ALIAS_UNSUPPORTED"),
    ("pair-03", "REVIEW_NONPERSISTENT_IDENTITY"),
    ("pair-04", "REVIEW_IDENTITY_TYPE_MISMATCH"),
    ("pair-05", "REVIEW_DISTINCT_GUARD"),
    ("pair-06", "REVIEW_REJECTED_ALIAS_GUARD"),
])
def test_unsafe_identity_choices_are_blocked_and_apply_changes_nothing(
    identity_campaign, pair_id: str, reason: str,
):
    root, pairs, _ = identity_campaign
    pair = next(candidate for candidate in pairs if candidate["id"] == pair_id)
    proposals = _alternatives(root, pair_id, _pair_scope(pair))
    assert all(not proposal.applicable for proposal in proposals)
    assert all(reason in proposal.blocked_reasons for proposal in proposals)
    assert all(proposal.targets == () for proposal in proposals)
    protected = [
        root / "docs" / "entity_registry.yaml",
        root / "summaries" / "001" / "session-summary.md",
    ]
    before = {path: path.read_bytes() for path in protected}
    module = _identity_module()
    error = getattr(module, "IdentityReviewError", Exception)
    with pytest.raises(error, match=reason):
        _apply(root, proposals[0])
    assert {path: path.read_bytes() for path in protected} == before


@pytest.mark.parametrize("pair_id", ["pair-05", "pair-06", "pair-07", "pair-08"])
def test_guard_and_conflict_resolution_is_separate_and_requires_fresh_preview(
    identity_campaign, pair_id: str,
):
    root, pairs, _ = identity_campaign
    pair = next(candidate for candidate in pairs if candidate["id"] == pair_id)
    proposal = _alternatives(root, pair_id, _pair_scope(pair))[0]
    resolution = _identity_module().identity_resolution_instructions(proposal)

    assert resolution is not None
    assert resolution["applicable"] is False
    assert resolution["mutations"] == []
    assert resolution["requires_new_identity_preview"] is True
    assert resolution["blocked_proposal_digest"] == proposal.proposal_digest


def test_exact_reviewed_guard_resolution_changes_only_guard_and_requires_new_preview(
    identity_campaign,
):
    root, pairs, _ = identity_campaign
    pair = next(candidate for candidate in pairs if candidate["id"] == "pair-05")
    blocked = _alternatives(root, pair["id"], {"kind": "global"})[0]
    module = _identity_module()
    resolution = module.prepare_guard_resolution(
        root,
        "duplicate-review",
        blocked_proposal_id=blocked.proposal_id,
        reviewer="GM",
        note="The earlier distinct ruling was entered against the wrong pair.",
    )

    event = module.apply_guard_resolution(
        root,
        "duplicate-review",
        resolution_id=resolution["resolution_id"],
        resolution_digest=resolution["resolution_digest"],
    )
    revised = load_registry(root / "docs/entity_registry.yaml")
    fresh = _alternatives(root, pair["id"], {"kind": "global"})

    assert event["requires_new_identity_preview"] is True
    assert all({value.casefold() for value in guard} != {pair["a"].casefold(), pair["b"].casefold()} for guard in revised.distinct)
    assert {proposal.proposal_id for proposal in fresh}.isdisjoint({blocked.proposal_id})
    assert all(proposal.applicable for proposal in fresh)
    assert review_status(root, "duplicate-review")["review_id"] == "duplicate-review"
    assert all(entry.get("kind") != "identity_guard_resolution" for entry in history(root, "duplicate-review"))
    item = next(value for value in read_snapshot(root, "duplicate-review")[2] if value.item_id == pair["id"])
    _approve(root, item, fresh[0])
    assert history(root, "duplicate-review", item_id=pair["id"])[-1]["verdict"] == "approve"


def test_guard_resolution_preserves_opaque_registry_metadata(identity_campaign):
    root, pairs, _ = identity_campaign
    pair = next(candidate for candidate in pairs if candidate["id"] == "pair-05")
    registry_path = root / "docs/entity_registry.yaml"
    raw = yaml.safe_load(registry_path.read_text())
    raw["operator_metadata"] = {"keep": "original"}
    raw["entities"][0]["operator_tag"] = "keep"
    registry_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    blocked = _alternatives(root, pair["id"], {"kind": "global"})[0]
    module = _identity_module()
    resolution = module.prepare_guard_resolution(
        root,
        "duplicate-review",
        blocked_proposal_id=blocked.proposal_id,
        reviewer="GM",
        note="Correct the exact obsolete guard.",
    )
    module.apply_guard_resolution(
        root,
        "duplicate-review",
        resolution_id=resolution["resolution_id"],
        resolution_digest=resolution["resolution_digest"],
    )
    after = yaml.safe_load(registry_path.read_text())
    assert after["operator_metadata"] == {"keep": "original"}
    assert after["entities"][0]["operator_tag"] == "keep"


def test_distinct_decision_suppresses_only_exact_scope_and_evidence(identity_campaign):
    root, pairs, items = identity_campaign
    pair, item = pairs[0], items[0]
    excerpt = f"{pair['a']} met {pair['b']}; {pair['b']} betrayed {pair['a']}."
    observations = _duplicate_observations(pair, excerpt)
    registry_path = root / "docs" / "entity_registry.yaml"
    registry_before = registry_path.read_bytes()
    legacy_distinct_before = tuple(
        tuple(group) for group in load_registry(registry_path).distinct
    )

    _decide_distinct(root, item)
    module = _identity_module()
    current = module.current_distinct_decisions(root)
    assert len(current) == 1
    assert current[0].names == frozenset({pair["a"].casefold(), pair["b"].casefold()})
    assert current[0].scope_kind == "global"
    assert current[0].evidence_digest == item.proposed_action.details["evidence_digest"]

    registry = load_registry(registry_path)
    assert duplicates.find_possible_duplicates(
        observations, registry, duplicates.Rulings(), 0.8
    ) == [], "the registry source path discovers the current reviewed distinct decision"

    wrong_scope = duplicates.find_possible_duplicates(
        observations,
        registry,
        duplicates.Rulings(),
        0.8,
        scope={"kind": "chapter", "value": "1"},
    )
    assert len(wrong_scope) == 1

    changed = list(observations)
    changed[1] = replace(
        changed[1], body=changed[1].body + " New relevant evidence."
    )
    reopened = duplicates.find_possible_duplicates(
        changed, registry, duplicates.Rulings(), 0.8
    )
    assert len(reopened) == 1
    assert reopened[0].code == "possible-duplicate"

    # Review-owned scope/evidence cannot be represented in registry v1.  The
    # decision therefore changes neither its global guards nor any other bytes.
    assert registry_path.read_bytes() == registry_before
    assert tuple(tuple(group) for group in load_registry(registry_path).distinct) == legacy_distinct_before

    save_decisions(root, "duplicate-review", {
        "version": 1,
        "request_id": f"discuss-{item.item_id}",
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [{
            "item_id": item.item_id,
            "item_revision": item.revision,
            "review_digest": item.review_digest,
            "expected_decision_revision": 1,
            "verdict": "discuss",
            "disposition": "defer",
            "note": "Reopen the identity question.",
            "proposal_id": None,
            "proposal_digest": None,
        }],
    })
    assert module.current_distinct_decisions(root) == ()
    assert len(duplicates.find_possible_duplicates(
        observations, load_registry(registry_path), duplicates.Rulings(), 0.8
    )) == 1


def test_global_same_type_merge_preserves_factual_summary_and_historical_loser_audit(
    identity_campaign,
):
    root, pairs, items = identity_campaign
    pair = pairs[0]
    item = items[0]
    alternatives = _alternatives(root, item.item_id, {"kind": "global"})
    proposal = next(
        candidate for candidate in alternatives
        if candidate.canonical_registry_name == pair["a"]
    )
    assert proposal.applicable
    assert set(proposal.retained_aliases) >= {
        pair["b"], f"{pair['a']} Alias", f"{pair['b']} Alias",
    }
    summary = root / "summaries" / "001" / "session-summary.md"
    summary_before = summary.read_bytes()
    _approve(root, item, proposal)

    receipt = _apply(root, proposal)

    assert isinstance(receipt, IdentityReceipt)
    assert receipt.proposal_id == proposal.proposal_id
    assert receipt.proposal_digest == proposal.proposal_digest
    assert "summaries/001/session-summary.md" not in receipt.changed_paths
    assert summary.read_bytes() == summary_before
    assert pair["b"] in summary.read_text()
    registry = load_registry(root / "docs" / "entity_registry.yaml")
    survivor = next(entity for entity in registry.entities if entity.name == pair["a"])
    assert not any(entity.name == pair["b"] for entity in registry.entities)
    assert set(survivor.aliases) >= {
        pair["b"], f"{pair['a']} Alias", f"{pair['b']} Alias",
    }
    assert "Merged identity metadata:" in (survivor.note or "")
    assert f"name={pair['b']}" in (survivor.note or "")
    assert "provenance=supplement" in (survivor.note or "")
    assert "source=Fixture" in (survivor.note or "")

    record = next(
        record for record in load_ledger(root).records
        if isinstance(record, ReviewDecisionRecord) and record.item_id == item.item_id
    )
    assert record.proposal is not None and record.proposal.id == proposal.proposal_id
    assert record.receipt is not None and record.receipt.id == receipt.receipt_id
    assert receipt.loser_subject_id == proposal.loser_subject_id
    validate_record_identity(root, record)
