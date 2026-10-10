from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import cli as summary_native_cli
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.promotion.review_bindings import load_signoff_bindings
from pipelines.summary_native.review.documents import (
    DocumentReviewError,
    create_document_review,
    prepare_document_promotion,
    promote_document_bundle,
    sign_document,
)
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.store import (
    CampaignReviewIdentity, export_review, import_review_bundle, load_campaign_identity,
    read_snapshot, retract_decision,
)
from pipelines.summary_native.claims.review import build_signoff_context


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("promotion_signoff_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)


def _signed(tmp_path: Path, *, context_update: dict | None = None):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    initial = build_bundle_selection(
        root,
        out_root="docs/summary_native",
        since=1,
        until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID),
        review_id="promotion-v2",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    context = {
        "support_digest": canonical_digest([
            item.model_dump(mode="json") for item in sorted(
                (initial.timeline, *initial.references, *initial.retained_records, *initial.dependencies),
                key=lambda value: value.path,
            )
        ]),
        "authority_digest": canonical_digest([]),
        "authority_record_ids": [],
        "audience_digest": canonical_digest({"audience": "gm"}),
        "rule_digest": canonical_digest({"rule_versions": sorted(initial.rule_versions)}),
    }
    context.update(context_update or {})
    create_document_review(
        root,
        "promotion-v2",
        root / "selections/promotion-documents.json",
        created_by="fixture-test",
        signoff_rule_version=2,
        signoff_context=context,
    )
    _manifest, _custody, items = read_snapshot(root, "promotion-v2")
    events = []
    for item in items:
        result = sign_document(
            root,
            "promotion-v2",
            document_item_id=item.item_id,
            item_sha256=item.proposed_action.details["document_sha256"],
            expected_decision_revision=0,
            reviewer="fixture-gm",
        )
        events.extend(result["events"])
    bundle = build_bundle_selection(
        root,
        out_root="docs/summary_native",
        since=1,
        until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID),
        review_id="promotion-v2",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    return root, bundle, events


def test_four_real_v2_decisions_survive_their_authority_ledger_appends(tmp_path: Path) -> None:
    root, bundle, _events = _signed(tmp_path)
    signoffs = load_signoff_bindings(root, bundle)
    assert {binding.document_id.value for binding in signoffs.bindings} == set(FACTORY.DOCUMENTS)


def test_legacy_v1_document_approvals_cannot_authorize_bundle(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    create_document_review(root, "promotion-v2", root / "selections/promotion-documents.json",
                           created_by="fixture-test", signoff_rule_version=1)
    _manifest, _custody, items = read_snapshot(root, "promotion-v2")
    for item in items:
        sign_document(root, "promotion-v2", document_item_id=item.item_id,
                      item_sha256=item.proposed_action.details["document_sha256"],
                      expected_decision_revision=0, reviewer="fixture-gm")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="promotion-v2",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    with pytest.raises(PromotionError, match="four distinct current"):
        load_signoff_bindings(root, bundle)


@pytest.mark.parametrize("changed", ["analysis", "resolution"])
def test_new_claim_analysis_or_finding_resolution_invalidates_signoff(tmp_path: Path, changed: str) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="promotion-v2",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    support = canonical_digest([item.model_dump(mode="json") for item in sorted(
        (bundle.timeline, *bundle.references, *bundle.retained_records, *bundle.dependencies),
        key=lambda value: value.path,
    )])
    context = build_signoff_context(
        analysis_digest="a" * 64, resolution_digest="b" * 64, support_digest=support,
        audience=bundle.audience,
        rule_versions=tuple(tuple(value.rsplit("/", 1)) for value in bundle.rule_versions),
    )
    create_document_review(root, "promotion-v2", root / "selections/promotion-documents.json",
                           created_by="fixture-test", signoff_rule_version=2, signoff_context=context)
    _manifest, _custody, items = read_snapshot(root, "promotion-v2")
    for item in items:
        sign_document(root, "promotion-v2", document_item_id=item.item_id,
                      item_sha256=item.proposed_action.details["document_sha256"],
                      expected_decision_revision=0, reviewer="fixture-gm")
    assert len(load_signoff_bindings(root, bundle, analysis_digest="a" * 64,
                                     resolution_digest="b" * 64).bindings) == 4
    kwargs = {"analysis_digest": "a" * 64, "resolution_digest": "b" * 64}
    kwargs[f"{changed}_digest"] = "f" * 64
    with pytest.raises(PromotionError, match="changed"):
        load_signoff_bindings(root, bundle, **kwargs)


def test_exact_imported_four_item_v2_bundle_is_accepted_by_production_loader(tmp_path: Path) -> None:
    source = FACTORY.create_campaign(tmp_path / "source/campaign", baseline="legacy")
    bundle = build_bundle_selection(
        source, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="promotion-v2",
        rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"),
    )
    context = {
        "support_digest": canonical_digest([item.model_dump(mode="json") for item in sorted(
            (bundle.timeline, *bundle.references, *bundle.retained_records, *bundle.dependencies),
            key=lambda value: value.path,
        )]),
        "authority_digest": canonical_digest([]), "authority_record_ids": [],
        "audience_digest": canonical_digest({"audience": "gm"}),
        "rule_digest": canonical_digest({"rule_versions": sorted(bundle.rule_versions)}),
    }
    create_document_review(source, "promotion-v2", source / "selections/promotion-documents.json",
                           created_by="fixture-test", signoff_rule_version=2, signoff_context=context)
    replica = tmp_path / "replica"
    shutil.copytree(source, replica)
    identity = load_campaign_identity(source)
    (replica / "docs/reviews/campaign.json").write_bytes(
        CampaignReviewIdentity(1, identity.campaign_id, str(replica.resolve())).bytes()
    )
    _manifest, _custody, items = read_snapshot(source, "promotion-v2")
    for item in items:
        sign_document(source, "promotion-v2", document_item_id=item.item_id,
                      item_sha256=item.proposed_action.details["document_sha256"],
                      expected_decision_revision=0, reviewer="fixture-gm")
    exported = export_review(source, "promotion-v2", [item.item_id for item in items])
    imported = import_review_bundle(replica, source / exported["path"], expected_generation=1)
    assert imported["imported_events"] == 4
    replica_bundle = bundle.model_copy(update={})
    assert len(load_signoff_bindings(replica, replica_bundle).bindings) == 4


def test_unrelated_review_creation_preserves_exact_v2_approvals(tmp_path: Path) -> None:
    root, bundle, _events = _signed(tmp_path)
    create_document_review(root, "unrelated-review", root / "selections/promotion-documents.json",
                           created_by="fixture-test", signoff_rule_version=1)
    assert len(load_signoff_bindings(root, bundle).bindings) == 4


def test_withdrawn_document_decision_is_not_current(tmp_path: Path) -> None:
    root, bundle, events = _signed(tmp_path)
    retract_decision(
        root,
        "promotion-v2",
        event_id=events[0]["event_id"],
        expected_revision=events[0]["decision_revision"],
        reason="fixture withdrawal",
    )
    with pytest.raises(PromotionError, match="four distinct current"):
        load_signoff_bindings(root, bundle)


@pytest.mark.parametrize("changed", ["support", "rules"])
def test_real_signoff_context_changes_are_stale(tmp_path: Path, changed: str) -> None:
    root, bundle, _events = _signed(tmp_path)
    if changed == "support":
        reference = root / bundle.references[0].path
        reference.write_text(reference.read_text() + "\nchanged\n", encoding="utf-8")
        bundle = build_bundle_selection(
            root, out_root="docs/summary_native", since=1, until=3,
            campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="promotion-v2",
            rule_versions=bundle.rule_versions,
        )
    else:
        bundle = bundle.model_copy(update={"rule_versions": (*bundle.rule_versions, "new-rule/1")})
    with pytest.raises(PromotionError, match="changed"):
        load_signoff_bindings(root, bundle)


@pytest.mark.parametrize("field", ["authority_digest", "audience_digest"])
def test_persisted_authority_or_audience_mismatch_is_stale(tmp_path: Path, field: str) -> None:
    root, bundle, _events = _signed(tmp_path, context_update={field: "f" * 64})
    with pytest.raises(PromotionError, match="changed"):
        load_signoff_bindings(root, bundle)


def test_individual_document_publication_is_retired_with_replacement_command(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    for operation in (
        lambda: prepare_document_promotion(root, "promotion-check", document_ids=["party"]),
        lambda: promote_document_bundle(root, "promotion-check", proposals=[]),
    ):
        with pytest.raises(DocumentReviewError) as caught:
            operation()
        assert caught.value.code == "PROMOTION_WHOLE_BUNDLE_REQUIRED"
        assert "summary_native promote --since N --until N" in str(caught.value)


def test_cli_preview_uses_persisted_current_v2_context(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _bundle, _events = _signed(tmp_path)
    FACTORY.initialize_managed(root)
    argv = [
        "promote", "--config", str(root / "config/config.yaml"),
        "--since", "1", "--until", "3", "--review", "promotion-v2",
        "--check-report", "claims-unavailable", "--dry-run", "--json",
    ]
    assert summary_native_cli.main(argv) == 5
    payload = __import__("json").loads(capsys.readouterr().out)
    gates = payload["data"]["preview"]["gates"]
    assert any(gate["gate"] == "document-signoffs" and gate["state"] == "passed" for gate in gates)
    reference = root / "docs/summary_native/ch001-003/state/drafts/reference/factions.md"
    reference.write_text(reference.read_text() + "\nchanged after signoff\n", encoding="utf-8")
    assert summary_native_cli.main(argv) == 5
    changed = __import__("json").loads(capsys.readouterr().out)
    assert "PROMOTION_SIGNOFF_STALE" in changed["data"]["preview"]["refusal_codes"]
