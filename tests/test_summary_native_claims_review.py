from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from pipelines.summary_native.authority import (
    AudienceGrant, AuthorityLedger, Classification, EffectiveInterval, NoteRecord, Projection,
    SourceRef, SubjectRef,
)
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.claims.models import ClaimAnnotation, ClaimFinding, ClaimPredicate, SourceRole
from pipelines.summary_native.claims.review import (
    build_signoff_context, create_claim_review, prepare_finding_disposition,
    load_confirmed_annotations, validate_signoff_context,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.review.documents import DocumentReviewError, create_document_review, sign_document
from pipelines.summary_native.review.models import ReviewItem, ReviewManifest, SourceCustodyGeneration, canonical_bytes
from pipelines.summary_native.review.store import (
    CampaignReviewIdentity, ReviewStoreError, create_review, export_review,
    history, import_review_bundle, initialize_campaign, load_campaign_identity, save_decisions,
)


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _campaign(tmp_path: Path, *, action: str, details: dict | None = None) -> tuple[Path, ReviewItem]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config/config.yaml").write_text("{}\n", encoding="utf-8")
    source = root / "summaries/001.md"
    source.parent.mkdir(parents=True)
    source.write_text("Exact claim evidence.\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    initialize_ledger(root, AuthorityLedger(version=2, campaign="claims-review", revision=1), actor="test")
    identity = initialize_campaign(root)
    item = ReviewItem(
        item_id="claim-item", revision=1, campaign_id=identity.campaign_id,
        review_id="claims-review", domain="grounding_document",
        subject_ref={"subject_id": UUID(int=42), "kind": "claim"},
        occurrence_id=UUID(int=43), locator={"source_path": "summaries/001.md", "anchor": "bytes:0-20"},
        claim_text="Exact claim evidence.",
        evidence=({"source_id": "claim-source", "source_path": "summaries/001.md", "anchor": "bytes:0-20",
                   "exact_excerpt": "Exact claim evidence.", "selected_span_sha256": hashlib.sha256(b"Exact claim evidence.").hexdigest()},),
        diagnostics=({"diagnostic_id": "claims-rule", "legacy_code": "claim-review",
                      "message": "Review the exact interpretation.", "blocking": True},),
        categories={"citation_non_entailment"}, severity="needs_judgment",
        assignment_basis="gm_confirmed", rationale="Exact mapping requires review.",
        proposed_action={"action": action, "details": details or {}},
        scope={"kind": "evidence", "value": "claim-item"},
        rule_versions=({"rule_id": "grounding-claims", "version": "1"},),
        input_bindings=({"source_id": "claim-source", "path": "summaries/001.md",
                         "custody_sha256": digest, "semantic_sha256": digest},),
    )
    custody = SourceCustodyGeneration(
        campaign_id=identity.campaign_id, review_id="claims-review", generation=1,
        recorded_at=NOW, sources=({"source_id": "claim-source", "path": "summaries/001.md",
                                   "sha256": digest, "size": source.stat().st_size},),
    )
    manifest = ReviewManifest(
        campaign_id=identity.campaign_id, review_id="claims-review", kind="grounding_documents",
        generation=1, created_at=NOW, created_by="test", selection=({"kind": "document", "id": "claims"},),
        items=({"campaign_id": identity.campaign_id, "review_id": "claims-review", "item_id": item.item_id,
                "revision": 1, "review_digest": item.review_digest},),
        source_manifest={"campaign_id": identity.campaign_id, "review_id": "claims-review",
                         "generation": 1, "digest": custody.custody_digest},
        rule_versions=({"rule_id": "grounding-claims", "version": "1"},),
    )
    create_review(root, manifest, custody, (item,))
    return root, item


def _save(root: Path, item: ReviewItem, *, verdict: str, disposition: str) -> dict:
    return save_decisions(root, "claims-review", {
        "version": 1, "request_id": "claims-decision", "review_generation": 1,
        "reviewer": "GM", "decisions": [{"item_id": item.item_id, "item_revision": 1,
        "review_digest": item.review_digest, "expected_decision_revision": 0,
        "verdict": verdict, "disposition": disposition, "note": "Reviewed."}],
    })


@pytest.mark.parametrize(("action", "details", "verdict", "disposition"), [
    ("confirm_claim_mapping", {}, "approve", "document_signoff"),
    ("confirm_claim_mapping", {}, "approve", "source_correction"),
    ("resolve_claim_finding", {}, "approve", "accept_no_change"),
    ("dismiss_claim_finding", {"basis": "mechanical", "evidence_digest": "a" * 64,
                               "rationale_digest": "b" * 64}, "approve", "accept_no_change"),
    ("dismiss_claim_finding", {"basis": "gm_confirmed", "evidence_digest": "a" * 64,
                               "rationale_digest": "b" * 64}, "approve", "accept_no_change"),
    ("dismiss_claim_finding", {}, "approve", "accept_no_change"),
])
def test_shared_save_boundary_rejects_incompatible_claim_meanings(
    tmp_path: Path, action: str, details: dict, verdict: str, disposition: str,
) -> None:
    root, item = _campaign(tmp_path, action=action, details=details)
    with pytest.raises(ReviewStoreError) as caught:
        _save(root, item, verdict=verdict, disposition=disposition)
    assert caught.value.code == "REVIEW_ACTION_MISMATCH"
    assert not tuple((root / "docs/reviews/claims-review/events").glob("decision-*.json"))


def test_import_boundary_rejects_mapping_event_masquerading_as_document_signoff(tmp_path: Path) -> None:
    source, item = _campaign(tmp_path / "source", action="confirm_claim_mapping")
    replica = tmp_path / "replica"
    shutil.copytree(source, replica)
    identity = load_campaign_identity(source)
    (replica / "docs/reviews/campaign.json").write_bytes(
        CampaignReviewIdentity(1, identity.campaign_id, str(replica.resolve())).bytes()
    )
    _save(source, item, verdict="approve", disposition="accept_no_change")
    exported = export_review(source, "claims-review", [item.item_id])
    raw = json.loads((source / exported["path"]).read_bytes())
    raw["events"][0]["disposition"] = "document_signoff"
    unsigned = dict(raw); unsigned.pop("bundle_sha256")
    raw["bundle_sha256"] = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    bundle = tmp_path / "malicious-import.json"
    bundle.write_bytes(canonical_bytes(raw))

    with pytest.raises(ReviewStoreError) as caught:
        import_review_bundle(replica, bundle, expected_generation=1)
    assert caught.value.code == "REVIEW_ACTION_MISMATCH"
    assert not tuple((replica / "docs/reviews/claims-review/events").glob("decision-*.json"))


def test_cli_decide_uses_the_same_action_compatibility_boundary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root, item = _campaign(tmp_path, action="confirm_claim_mapping")
    request = {
        "version": 1, "request_id": "cli-invalid", "review_generation": 1, "reviewer": "GM",
        "decisions": [{"item_id": item.item_id, "item_revision": 1,
                       "review_digest": item.review_digest, "expected_decision_revision": 0,
                       "verdict": "approve", "disposition": "document_signoff", "note": "invalid"}],
    }
    request_path = tmp_path / "invalid.json"
    request_path.write_bytes(canonical_bytes(request))
    code = main(["review", "decide", "claims-review", "--decisions", str(request_path),
                 "--campaign-dir", str(root), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and payload["code"] == "REVIEW_ACTION_MISMATCH"
    assert not tuple((root / "docs/reviews/claims-review/events").glob("decision-*.json"))


def test_claim_adapter_creates_stable_exact_mapping_and_finding_items(tmp_path: Path) -> None:
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    source = root / "summaries/001.md"
    data = source.read_bytes(); span = b"Exact claim evidence."
    annotation = ClaimAnnotation(
        occurrence_id="occ-1", revision=1, source_id="claim-source",
        source_path="summaries/001.md", source_role=SourceRole.CLAIM, anchor="bytes:0-21",
        start_byte=0, end_byte=len(span), source_sha256=hashlib.sha256(data).hexdigest(),
        span_sha256=hashlib.sha256(span).hexdigest(), context_sha256=hashlib.sha256(data).hexdigest(),
        original_span=span.decode(), subject_id="subject-1", predicate=ClaimPredicate.STATUS,
        normalized_value="active", certainty="certain", audience="gm", origin="human_candidate",
        interpretation_state="candidate",
    )
    semantic = hashlib.sha256(b"finding").hexdigest()
    finding = ClaimFinding(
        finding_id="finding-1", revision=1, categories=("incompatible_state",),
        annotation_ids=("occ-1",), rule_id="claims", rule_version="1", audience="gm",
        effective_horizon="now", basis="semantic_candidate", severity="blocking",
        evidence=("occ-1",), rationale="The states conflict.", next_action="GM resolution required.",
        required_disposition=True, semantic_digest=semantic,
    )
    create_claim_review(root, "claims-review", annotations=(annotation,), findings=(finding,),
                        created_by="test", rule_versions=(("claims", "1"),))
    _manifest, custody, items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "claims-review")
    assert [item.item_id for item in items] == ["mapping-occ-1", "finding-finding-1"]
    assert items[0].evidence[0].exact_excerpt == span.decode()
    assert items[0].proposed_action.details["predicate"] == "status"
    assert items[0].proposed_action.details["normalized_value"] == "active"
    assert items[0].proposed_action.details["certainty"] == "certain"
    assert items[0].proposed_action.details["audience"] == "gm"
    assert items[1].proposed_action.details["finding_revision"] == 1
    assert custody.sources[0].sha256 == hashlib.sha256(data).hexdigest()


def test_paired_interpretations_of_one_span_share_evidence_without_losing_meaning(tmp_path: Path) -> None:
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    source = root / "summaries/001.md"; data = source.read_bytes(); span = b"Exact claim evidence."
    common = dict(
        revision=1, source_id="claim-source", source_path="summaries/001.md",
        source_role=SourceRole.CLAIM, anchor="bytes:0-21", start_byte=0, end_byte=len(span),
        source_sha256=hashlib.sha256(data).hexdigest(), span_sha256=hashlib.sha256(span).hexdigest(),
        context_sha256=hashlib.sha256(data).hexdigest(), original_span=span.decode(),
        subject_id="subject-1", predicate=ClaimPredicate.STATUS, normalized_value="active",
        certainty="certain", audience="gm", origin="human_candidate", interpretation_state="candidate",
    )
    known = ClaimAnnotation(occurrence_id="known", effective_from="chapter-1", effective_until="chapter-1", **common)
    unknown = ClaimAnnotation(occurrence_id="unknown", effective_from=None, effective_until=None, **common)
    finding = ClaimFinding(
        finding_id="scope-pair", revision=1, categories=("incompatible_state",),
        annotation_ids=("known", "unknown"), rule_id="scope", rule_version="1", audience="gm",
        effective_horizon="chapter-1", basis="semantic_candidate", severity="blocking",
        evidence=(known.original_span, unknown.original_span), rationale="Scope differs.",
        next_action="Review scope.", required_disposition=True,
        semantic_digest=hashlib.sha256(b"scope-pair").hexdigest(),
    )
    create_claim_review(root, "claims-review", annotations=(known, unknown), findings=(finding,),
                        created_by="test", rule_versions=(("claims", "1"),))
    from pipelines.summary_native.review.store import read_snapshot
    _manifest, _custody, items = read_snapshot(root, "claims-review")
    item = next(value for value in items if value.item_id == "finding-scope-pair")
    assert len(item.evidence) == 1
    interpretations = item.proposed_action.details["annotation_interpretations"]
    assert {value["occurrence_id"] for value in interpretations} == {"known", "unknown"}


def test_prepared_finding_alternatives_bind_revision_evidence_and_rationale(tmp_path: Path) -> None:
    root, item = _campaign(tmp_path, action="resolve_claim_finding", details={
        "basis": "semantic_candidate", "finding_revision": 1,
    })
    prepared = prepare_finding_disposition(
        item, alternative="dismiss", evidence=("occurrence:one",),
        rationale="The cited source supports the existing statement.", expected_decision_revision=3,
    )
    assert prepared.item_id == item.item_id and prepared.revision == 2
    assert prepared.proposed_action.action == "dismiss_claim_finding"
    assert prepared.proposed_action.details["expected_decision_revision"] == 3
    assert len(prepared.proposed_action.details["evidence_digest"]) == 64
    assert prepared.review_digest != item.review_digest

    revisited = item.model_copy(update={"revision": 3})
    reprepared = prepare_finding_disposition(
        revisited, alternative="accept_uncertainty", evidence=("occurrence:one",),
        rationale="The source leaves the effective period unresolved.", expected_decision_revision=4,
    )
    assert reprepared.revision == 4
    assert reprepared.proposed_action.details["finding_revision"] == 1

    mechanical = item.model_copy(update={"proposed_action": item.proposed_action.model_copy(
        update={"details": {"basis": "mechanical", "finding_revision": 1}})})
    with pytest.raises(PromotionError) as caught:
        prepare_finding_disposition(mechanical, alternative="accept_uncertainty", evidence=("x",),
                                    rationale="Uncertain.", expected_decision_revision=0)
    assert caught.value.code == "CLAIMS_SOURCE_CORRECTION_REQUIRED"

    malformed = item.model_copy(update={"proposed_action": item.proposed_action.model_copy(
        update={"details": {"basis": "semantic_candidate"}})})
    with pytest.raises(PromotionError) as caught:
        prepare_finding_disposition(malformed, alternative="dismiss", evidence=("x",),
                                    rationale="Reviewed.", expected_decision_revision=0)
    assert caught.value.code == "CLAIMS_DISPOSITION_INVALID"


def test_missing_counterpart_without_exact_source_stays_an_incomplete_diagnostic(tmp_path: Path) -> None:
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    finding = ClaimFinding(
        finding_id="missing-source", revision=1, categories=("direct_contradiction",),
        annotation_ids=(), missing_counterpart="No counterpart was selected.", rule_id="claims",
        rule_version="1", audience="gm", effective_horizon="now", basis="semantic_candidate",
        severity="blocking", evidence=(), rationale="Selection is incomplete.", next_action="Select evidence.",
        required_disposition=True, semantic_digest=hashlib.sha256(b"missing-source").hexdigest(),
    )
    with pytest.raises(PromotionError) as caught:
        create_claim_review(root, "missing-review", annotations=(), findings=(finding,), created_by="test",
                            rule_versions=(("claims", "1"),))
    assert caught.value.code == "CLAIMS_REVIEW_EVIDENCE_REQUIRED"
    assert not (root / "docs/reviews/missing-review").exists()


@pytest.mark.parametrize("change", ["predicate", "value", "audience"])
def test_changed_mapping_meaning_revises_item_and_stales_prior_authority(tmp_path: Path, change: str) -> None:
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    source = root / "summaries/001.md"; data = source.read_bytes(); span = b"Exact claim evidence."
    annotation = ClaimAnnotation(
        occurrence_id="meaning", revision=1, source_id="claim-source", source_path="summaries/001.md",
        source_role=SourceRole.CLAIM, anchor="bytes:0-21", start_byte=0, end_byte=len(span),
        source_sha256=hashlib.sha256(data).hexdigest(), span_sha256=hashlib.sha256(span).hexdigest(),
        context_sha256=hashlib.sha256(data).hexdigest(), original_span=span.decode(),
        predicate=ClaimPredicate.STATUS, normalized_value="active", certainty="certain", audience="gm",
        origin="human_candidate", interpretation_state="candidate",
    )
    create_claim_review(root, "meaning-review", annotations=(annotation,), findings=(), created_by="test",
                        rule_versions=(("claims", "1"),))
    manifest, _custody, items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "meaning-review")
    item = items[0]
    save_decisions(root, "meaning-review", {
        "version": 1, "request_id": f"meaning-{change}", "review_generation": manifest.generation,
        "reviewer": "GM", "decisions": [{"item_id": item.item_id, "item_revision": item.revision,
        "review_digest": item.review_digest, "expected_decision_revision": 0, "verdict": "approve",
        "disposition": "accept_no_change", "note": "Reviewed exact meaning."}],
    })
    updates = {
        "predicate": {"predicate": ClaimPredicate.LOCATION},
        "value": {"normalized_value": "inactive"},
        "audience": {"audience": "party"},
    }[change]
    changed = annotation.model_copy(update=updates)
    create_claim_review(root, "meaning-review", annotations=(changed,), findings=(), created_by="test",
                        rule_versions=(("claims", "1"),))
    manifest, _custody, items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "meaning-review")
    assert manifest.generation == 2 and items[0].revision == 2
    assert load_confirmed_annotations(root, "meaning-review", (changed,)) == ()


def test_active_ledger_record_can_enter_finding_review_without_fake_markdown_span(tmp_path: Path) -> None:
    root = tmp_path / "ledger-campaign"; (root / "config").mkdir(parents=True)
    (root / "config/config.yaml").write_text("{}\n")
    source = root / "docs/tracking/facts.md"; source.parent.mkdir(parents=True)
    source.write_text("# Facts\n\nThe exact authored source remains here.\n")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    note = NoteRecord(
        kind="note", id="active-status", revision=1, classification=Classification.CANON,
        subject=SubjectRef(kind="topic", id="bridge"), claim_key=ClaimPredicate.STATUS.value,
        normalized_value="closed", effective=EffectiveInterval(from_chapter=1, through_chapter=3),
        audience=AudienceGrant(grants=frozenset({"gm"})), projections=frozenset({Projection.WORLD_STATE}),
        recorded_at=NOW, recorded_by="gm", status="active",
        source=SourceRef(path="docs/tracking/facts.md", anchor="heading:facts"),
        content_digest=source_digest, selection_label="Bridge status",
    )
    note_two = note.model_copy(update={"id": "active-status-two", "normalized_value": "open",
                                      "selection_label": "Bridge status two"})
    initialize_ledger(root, AuthorityLedger(version=2, campaign="ledger-review", revision=1,
                                             records=[note, note_two]), actor="test")
    initialize_campaign(root)
    ledger_path = root / "docs/authority.yaml"
    ledger_digest = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    record_digest = hashlib.sha256(canonical_bytes(note)).hexdigest()
    annotation = ClaimAnnotation(
        occurrence_id="authority-active-status-r1", revision=1, source_id="authority-source",
        source_path="docs/authority.yaml", source_role=SourceRole.AUTHORITY,
        evidence_kind="authority_record", anchor="record:active-status", source_sha256=ledger_digest,
        span_sha256=record_digest, context_sha256=ledger_digest,
        original_span=canonical_bytes(note).decode().strip(), subject_id="bridge",
        predicate=ClaimPredicate.STATUS, normalized_value="closed", certainty="certain",
        effective_from="current", effective_until="current", audience="gm",
        authority_record_ids=(note.id,), authority_record_digests={note.id: record_digest},
        origin="structured_source", interpretation_state="candidate",
    )
    record_two_digest = hashlib.sha256(canonical_bytes(note_two)).hexdigest()
    annotation_two = annotation.model_copy(update={
        "occurrence_id": "authority-active-status-two-r1", "source_id": "authority-source-two",
        "anchor": "record:active-status-two", "span_sha256": record_two_digest,
        "original_span": canonical_bytes(note_two).decode().strip(), "normalized_value": "open",
        "authority_record_ids": (note_two.id,), "authority_record_digests": {note_two.id: record_two_digest},
    })
    finding = ClaimFinding(
        finding_id="ledger-finding", revision=1, categories=("incompatible_state",),
        annotation_ids=(annotation.occurrence_id, annotation_two.occurrence_id), rule_id="claims", rule_version="1", audience="gm",
        effective_horizon="current", basis="semantic_candidate", severity="blocking",
        evidence=(annotation.original_span,), rationale="Review structured authority against the draft.",
        next_action="Resolve.", required_disposition=True,
        semantic_digest=hashlib.sha256(b"ledger-finding").hexdigest(),
    )
    create_claim_review(root, "ledger-review", annotations=(annotation, annotation_two), findings=(finding,),
                        created_by="test", rule_versions=(("claims", "1"),))
    _manifest, custody, items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "ledger-review")
    assert len(items) == 3 and len(custody.sources) == 1 and custody.sources[0].path == "docs/authority.yaml"
    assert items[0].evidence[0].missing_reason.startswith("Meaning is projected")
    assert items[0].proposed_action.details["authority_record_digests"] == {note.id: record_digest}


def test_v2_signoff_context_is_complete_acyclic_and_required(tmp_path: Path) -> None:
    context = build_signoff_context(
        analysis_digest="a" * 64, resolution_digest="b" * 64, support_digest="c" * 64,
        audience="gm", rule_versions=(("claims", "2"),),
    )
    assert validate_signoff_context(context) == context
    unsigned = dict(context); unsigned.pop("signoff_context_digest")
    assert context["signoff_context_digest"] == hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    with pytest.raises(PromotionError) as caught:
        build_signoff_context(
            analysis_digest="a" * 64, resolution_digest="b" * 64, support_digest="c" * 64,
            audience="gm", rule_versions=(("claims", "2"),),
            unresolved_required_findings=("finding-1",),
        )
    assert caught.value.code == "CLAIMS_RESOLUTION_REQUIRED"

    root, _ = _campaign(tmp_path / "document", action="confirm_claim_mapping")
    draft = root / "docs/state/draft/document.md"; draft.parent.mkdir(parents=True)
    draft.write_text("# Document\n", encoding="utf-8")
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"documents": [{"id": "document", "path": "docs/state/draft/document.md"}]}))
    with pytest.raises(DocumentReviewError):
        create_document_review(root, "v2-missing", selection, created_by="test", signoff_rule_version=2)
    result = create_document_review(root, "v2-review", selection, created_by="test",
                                    signoff_rule_version=2, signoff_context=context)
    assert result["item_count"] == 1


def test_one_review_id_evolves_from_mapping_to_findings_and_four_signoffs(tmp_path: Path) -> None:
    root, _ = _campaign(tmp_path, action="confirm_claim_mapping")
    shutil.rmtree(root / "docs/reviews/claims-review")
    source = root / "summaries/001.md"; data = source.read_bytes(); span = b"Exact claim evidence."
    annotation = ClaimAnnotation(
        occurrence_id="occ-stage", revision=1, source_id="claim-source",
        source_path="summaries/001.md", source_role=SourceRole.CLAIM, anchor="bytes:0-21",
        start_byte=0, end_byte=len(span), source_sha256=hashlib.sha256(data).hexdigest(),
        span_sha256=hashlib.sha256(span).hexdigest(), context_sha256=hashlib.sha256(data).hexdigest(),
        original_span=span.decode(), predicate=ClaimPredicate.STATUS, normalized_value="active",
        certainty="certain", audience="gm", origin="human_candidate", interpretation_state="candidate",
    )
    create_claim_review(root, "one-review", annotations=(annotation,), findings=(), created_by="test",
                        rule_versions=(("claims", "1"),))
    _manifest, _custody, mapping_items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "one-review")
    mapping = mapping_items[0]
    saved = save_decisions(root, "one-review", {
        "version": 1, "request_id": "mapping-stage", "review_generation": 1, "reviewer": "GM",
        "decisions": [{"item_id": mapping.item_id, "item_revision": mapping.revision,
                       "review_digest": mapping.review_digest, "expected_decision_revision": 0,
                       "verdict": "approve", "disposition": "accept_no_change", "note": "Exact mapping."}],
    })
    confirmed = load_confirmed_annotations(root, "one-review", (annotation,))
    assert len(confirmed) == 1
    assert confirmed[0].interpretation_state == "mapping_confirmed"
    assert confirmed[0].mapping_event_id == saved["events"][0]["event_id"]
    assert annotation.interpretation_state == "candidate"  # authority is interpretation-only and derived

    finding = ClaimFinding(
        finding_id="stage-finding", revision=1, categories=("incompatible_state",),
        annotation_ids=("occ-stage",), rule_id="claims", rule_version="1", audience="gm",
        effective_horizon="now", basis="semantic_candidate", severity="warning", evidence=("occ-stage",),
        rationale="Review this comparison.", next_action="Resolve.", required_disposition=True,
        semantic_digest=hashlib.sha256(b"stage-finding").hexdigest(),
    )
    create_claim_review(root, "one-review", annotations=(annotation,), findings=(finding,), created_by="test",
                        rule_versions=(("claims", "1"),))

    documents = []
    for name in ("world_state", "campaign_state", "party", "planning"):
        path = root / f"docs/state/drafts/{name}.md"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
        documents.append({"id": name, "path": str(path.relative_to(root))})
    selection = tmp_path / "four-documents.json"; selection.write_text(json.dumps({"documents": documents}))
    context = build_signoff_context(
        analysis_digest="a" * 64, resolution_digest="b" * 64, support_digest="c" * 64,
        audience="gm", rule_versions=(("claims", "1"),),
    )
    result = create_document_review(root, "one-review", selection, created_by="test",
                                    signoff_rule_version=2, signoff_context=context)
    manifest, _custody, items = __import__(
        "pipelines.summary_native.review.store", fromlist=["read_snapshot"]
    ).read_snapshot(root, "one-review")
    assert result["generation"] == manifest.generation == 3
    assert len(items) == 6
    assert {item.item_id for item in items if item.proposed_action.action == "signoff_document"} == {
        "document-world_state", "document-campaign_state", "document-party", "document-planning",
    }
    document_items = [item for item in items if item.proposed_action.action == "signoff_document"]
    for item in document_items:
        sign_document(root, "one-review", document_item_id=item.item_id,
                      item_sha256=item.proposed_action.details["document_sha256"],
                      expected_decision_revision=0, reviewer="GM")
    assert all(history(root, "one-review", item_id=item.item_id)[-1]["disposition"] == "document_signoff"
               for item in document_items)
    assert history(root, "one-review", item_id=mapping.item_id)[0]["event_id"] == saved["events"][0]["event_id"]
