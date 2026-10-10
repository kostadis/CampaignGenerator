from __future__ import annotations

import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipelines.summary_native.claims.models import (
    AuthorityClass, ClaimAnnotation, ClaimFinding, ClaimPredicate, SourceRole, SourceSelection, validate_annotation_authority,
)
from pipelines.summary_native.claims.packets import assemble_packet, save_packet
from pipelines.summary_native.claims.cli import run as claims_run
from pipelines.summary_native.cli import main as summary_native_main
from pipelines.summary_native.claims.selection import (
    bundle_source_digest, confirm_selection, mandatory_source_closure, save_confirmed_selection,
    select_whole_source_chunks, validate_selection_against_bundle,
)
from pipelines.summary_native.claims.selection import _write_owner_only
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.review.models import canonical_bytes
from pipelines.summary_native.authority import (
    AudienceGrant, AuthorityLedger, Classification, EffectiveInterval, NoteRecord,
    Projection, ReviewDecisionRecord, SourceRef, SubjectRef, ledger_bytes,
)


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("claims_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FACTORY)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _selection(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    return root, bundle, mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",)
    )


def test_source_closure_contains_every_non_omittable_dependency_and_no_implicit_all(tmp_path: Path) -> None:
    _root, bundle, selection = _selection(tmp_path)
    assert {item.path for item in selection.sources} == {
        *(item.path for item in bundle.documents), bundle.timeline.path,
        *(item.path for item in bundle.references), *(item.path for item in bundle.retained_records),
        *(item.path for item in bundle.dependencies), bundle.config_identity.path,
    }
    assert all(item.required for item in selection.sources)
    assert selection.chunks == ()  # no model scope is selected implicitly


def test_confirmation_refuses_ambiguous_horizon_or_identity_scope(tmp_path: Path) -> None:
    _root, _bundle, selection = _selection(tmp_path)
    values = selection.model_dump(mode="python")
    values["unresolved_scope"] = ("Which Petra agreement defines the effective horizon?",)
    values["selection_digest"] = "0" * 64
    provisional = selection.__class__.model_construct(**values)
    from pipelines.summary_native.review.models import canonical_digest
    values["selection_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}))
    ambiguous = selection.__class__.model_validate(values)
    with pytest.raises(Exception, match="unresolved scope"):
        confirm_selection(ambiguous, reviewer="gm", confirmed_at=NOW)


def test_saved_selection_and_packet_are_owner_only_and_packet_is_exact(tmp_path: Path) -> None:
    root, _bundle, proposed = _selection(tmp_path)
    proposed = select_whole_source_chunks(root, proposed, (proposed.sources[0].source_id,))
    confirmed = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    selection_path = save_confirmed_selection(root, confirmed)
    packet = assemble_packet(root, confirmed)
    packet_path = save_packet(root, confirmed, packet)
    assert selection_path.stat().st_mode & 0o777 == 0o600
    assert packet_path.stat().st_mode & 0o777 == 0o600
    assert selection_path.parent.stat().st_mode & 0o777 == 0o700
    assert packet_path.parent.stat().st_mode & 0o777 == 0o700
    assert not packet.incomplete_inputs
    assert tuple(item.chunk_id for item in packet.chunks) == tuple(item.chunk_id for item in confirmed.chunks)
    assert all(item.source_audience == "gm" and item.target_audience == "gm" for item in packet.chunks)
    assert all(item.authority_class is AuthorityClass.OPEN for item in packet.chunks)


def test_packet_discloses_changed_or_missing_selected_input(tmp_path: Path) -> None:
    root, _bundle, proposed = _selection(tmp_path)
    proposed = select_whole_source_chunks(root, proposed, (proposed.sources[0].source_id,))
    confirmed = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    source = confirmed.sources[0]
    (root / source.path).write_text("changed", encoding="utf-8")
    packet = assemble_packet(root, confirmed)
    expected = {chunk.chunk_id for chunk in confirmed.chunks if chunk.source_id == source.source_id}
    assert expected <= set(packet.incomplete_inputs)


def test_raw_symlink_source_is_refused_even_when_it_resolves_inside_campaign(tmp_path: Path) -> None:
    root, bundle, _selection_value = _selection(tmp_path)
    target = root / bundle.timeline.path
    copy = target.with_name("timeline-real.md")
    copy.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(copy.name)
    with pytest.raises(Exception, match="symlink"):
        mandatory_source_closure(
            root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",)
        )


def test_private_selection_write_refuses_parent_symlink(tmp_path: Path) -> None:
    root, _bundle, proposed = _selection(tmp_path)
    confirmed = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    private_parent = root / confirmed.out_root / "ch001-003/state/promotion"
    private_parent.mkdir(parents=True)
    outside = root / "outside-selections"
    outside.mkdir()
    (private_parent / "selections").symlink_to(outside)
    with pytest.raises(Exception, match="unsafe component"):
        save_confirmed_selection(root, confirmed)
    assert not tuple(outside.iterdir())


def test_confirmation_revalidation_refuses_omitted_required_source(tmp_path: Path) -> None:
    root, bundle, proposed = _selection(tmp_path)
    omitted = proposed.sources[-1]
    values = proposed.model_dump(mode="python")
    values["sources"] = tuple(item for item in proposed.sources if item.source_id != omitted.source_id)
    values["chunks"] = tuple(item for item in proposed.chunks if item.source_id != omitted.source_id)
    values["selection_digest"] = "0" * 64
    from pipelines.summary_native.review.models import canonical_digest
    provisional = proposed.__class__.model_construct(**values)
    values["selection_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}))
    shortened = proposed.__class__.model_validate(values)
    with pytest.raises(Exception, match="mandatory sources"):
        validate_selection_against_bundle(root, shortened, bundle)


def test_active_authority_source_is_discovered_with_real_metadata_and_is_required(tmp_path: Path) -> None:
    root, bundle, _proposed = _selection(tmp_path)
    note_path = root / "docs/tracking/fixture.txt"
    import hashlib
    note = NoteRecord(
        kind="note", id="canon-note", revision=1, classification=Classification.CANON,
        subject=SubjectRef(kind="topic", id="lantern-road"), claim_key="status",
        normalized_value="safe", effective=EffectiveInterval(through_chapter=3),
        audience=AudienceGrant(grants=frozenset({"gm", "players"})),
        projections=frozenset({Projection.WORLD_STATE}), recorded_at=NOW, recorded_by="gm",
        status="active", source=SourceRef(path="docs/tracking/fixture.txt", anchor="heading:canon"),
        content_digest=hashlib.sha256(note_path.read_bytes()).hexdigest(), selection_label="Canon note",
    )
    (root / "docs/authority.yaml").write_bytes(ledger_bytes(AuthorityLedger(
        version=2, campaign="promotion-fixture", revision=2, records=[note], conflicts=[]
    )))
    selection = mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",)
    )
    source = next(item for item in selection.sources if item.authority_record_ids)
    assert source.required and source.authority_class is AuthorityClass.CANON
    assert source.applicability == "fact_authority"
    assert source.source_audience == "players"
    assert source.authority_record_ids == ("canon-note",)
    assert source.path == "docs/authority.yaml"
    assert source.anchor == "authority-record:canon-note:r1"

    decisions = [ReviewDecisionRecord(
        kind="review_decision", id=f"decision-{index}", revision=1,
        classification=Classification.RULED, subject=SubjectRef(kind="topic", id="review"),
        effective=EffectiveInterval(horizon="open"), audience=AudienceGrant(grants=frozenset({"gm"})),
        projections=frozenset({Projection.PLANNING}), recorded_at=NOW, recorded_by="gm",
        status="accepted", campaign_id=FACTORY.CAMPAIGN_ID, review_id="claims-review",
        item_id=f"item-{index}", item_revision=1, event_id=f"event-{index}", decision_revision=1,
        event_digest=f"{index + 1:064x}", review_digest=f"{index + 11:064x}",
        domain="grounding_document", disposition="accept_no_change" if index == 0 else "document_signoff",
    ) for index in range(5)]
    (root / "docs/authority.yaml").write_bytes(ledger_bytes(AuthorityLedger(
        version=2, campaign="promotion-fixture", revision=3, records=[note, *decisions], conflicts=[]
    )))
    validate_selection_against_bundle(root, selection, bundle)


def test_future_prep_link_is_mapping_evidence_and_requires_scope_confirmation(tmp_path: Path) -> None:
    root, bundle, _proposed = _selection(tmp_path)
    import hashlib
    note_path = root / "docs/tracking/fixture.txt"
    note = NoteRecord(
        kind="note", id="future-prep", revision=1, classification=Classification.PREP,
        subject=SubjectRef(kind="topic", id="lantern-road"), claim_key="status",
        normalized_value="threatened", effective=EffectiveInterval(horizon="future"),
        audience=AudienceGrant(grants=frozenset({"gm"})),
        projections=frozenset({Projection.PLANNING}), recorded_at=NOW, recorded_by="gm",
        status="active", source=SourceRef(path="docs/tracking/fixture.txt", anchor="prep:future"),
        content_digest=hashlib.sha256(note_path.read_bytes()).hexdigest(), selection_label="Future prep",
        planning_date="2026-10-11",
    )
    (root / "docs/authority.yaml").write_bytes(ledger_bytes(AuthorityLedger(
        version=2, campaign="promotion-fixture", revision=2, records=[note], conflicts=[]
    )))
    selection = mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",)
    )
    source = next(item for item in selection.sources if item.authority_record_ids == ("future-prep",))
    assert source.authority_class is AuthorityClass.PREP
    assert source.applicability == "mapping_evidence"
    assert selection.unresolved_scope and "future-prep" in selection.unresolved_scope[0]
    with pytest.raises(Exception, match="unresolved scope"):
        confirm_selection(selection, reviewer="gm", confirmed_at=NOW)


def test_revalidation_rejects_reclassified_or_reaudienced_required_source(tmp_path: Path) -> None:
    root, bundle, proposed = _selection(tmp_path)
    values = proposed.model_dump(mode="python")
    source_values = proposed.sources[0].model_dump(mode="python")
    source_values["source_audience"] = "players"
    source_values["authority_class"] = AuthorityClass.CANON
    values["sources"] = (proposed.sources[0].__class__.model_validate(source_values), *proposed.sources[1:])
    values["selection_digest"] = "0" * 64
    from pipelines.summary_native.review.models import canonical_digest
    provisional = proposed.__class__.model_construct(**values)
    values["selection_digest"] = canonical_digest(provisional, exclude_fields=frozenset({"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}))
    altered = proposed.__class__.model_validate(values)
    with pytest.raises(Exception, match="mandatory sources"):
        validate_selection_against_bundle(root, altered, bundle)


def test_missing_cited_chapter_refuses_instead_of_silently_narrowing_scope(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    draft = root / "docs/summary_native/ch001-003/state/drafts/world_state.draft.md"
    draft.write_text(draft.read_text() + "\nMissing evidence [ch 999 / lost].\n", encoding="utf-8")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    with pytest.raises(Exception, match="absent from the selected corpus"):
        mandatory_source_closure(root, bundle, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",))


def test_explicit_later_links_are_followed_recursively_and_become_required(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    notes = root / "docs/linked"
    notes.mkdir()
    (notes / "later.md").write_text("Later evidence links [again](final.md).\n", encoding="utf-8")
    (notes / "final.md").write_text("Final explicit evidence.\n", encoding="utf-8")
    draft = root / "docs/summary_native/ch001-003/state/drafts/world_state.draft.md"
    draft.write_text(draft.read_text() + "\n[Later evidence](../../../../linked/later.md)\n", encoding="utf-8")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
        rule_versions=("claims/1",), config_path=root / "config/grounding.yaml",
    )
    selection = mandatory_source_closure(root, bundle, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",))
    linked = {item.path: item for item in selection.sources}
    assert linked["docs/linked/later.md"].required
    assert linked["docs/linked/final.md"].required
    assert linked["docs/linked/later.md"].applicability == "mapping_evidence"


def test_source_bundle_identity_does_not_depend_on_later_review_id(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    kwargs = dict(
        campaign_dir=root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), rule_versions=("claims/1",),
        config_path=root / "config/grounding.yaml",
    )
    first = build_bundle_selection(review_id="claims-selection", **kwargs)
    later = build_bundle_selection(review_id="MY-ID", **kwargs)
    a = mandatory_source_closure(root, first, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",))
    b = mandatory_source_closure(root, later, effective_horizon="chapter-3", audience="gm", rule_versions=("claims/1",))
    assert a.bundle_digest == b.bundle_digest
    assert a.selection_digest == b.selection_digest


def test_unknown_semantics_remain_unknown_and_strict_models_reject_extra_fields() -> None:
    values = dict(
        occurrence_id="occurrence-1", revision=1, source_id="source-1", source_path="docs/source.md",
        source_role=SourceRole.CLAIM, anchor="line:1", start_byte=0, end_byte=4,
        source_sha256="a" * 64, span_sha256="b" * 64, context_sha256="c" * 64,
        original_span="Maybe", subject_id=None, predicate=None, normalized_value=None,
        certainty="unknown", audience="gm", origin="human_candidate", interpretation_state="candidate",
    )
    annotation = ClaimAnnotation.model_validate(values)
    assert annotation.predicate is None and annotation.normalized_value is None
    with pytest.raises(ValidationError):
        ClaimAnnotation.model_validate({**values, "invented_truth": True})


def test_structured_origin_cannot_forge_fact_authority() -> None:
    values = dict(
        occurrence_id="structured-1", revision=1, source_id="source-1", source_path="docs/source.md",
        source_role=SourceRole.AUTHORITY, anchor="record:1", start_byte=0, end_byte=4,
        source_sha256="a" * 64, span_sha256="b" * 64, context_sha256="c" * 64,
        original_span="Fact", subject_id="subject-1", predicate=ClaimPredicate.STATUS, normalized_value="active",
        certainty="certain", audience="gm", origin="structured_source", interpretation_state="candidate",
    )
    with pytest.raises(ValidationError, match="authority record"):
        ClaimAnnotation.model_validate(values)
    with pytest.raises(ValidationError, match="exact authority record digests"):
        ClaimAnnotation.model_validate({**values, "authority_record_ids": ("authority-1",)})
    annotation = ClaimAnnotation.model_validate({
        **values, "authority_record_ids": ("authority-1",),
        "authority_record_digests": {"authority-1": "d" * 64},
    })
    with pytest.raises(ValueError, match="inactive, or stale"):
        validate_annotation_authority(annotation, frozenset())
    validate_annotation_authority(annotation, {"authority-1": "d" * 64})
    with pytest.raises(ValueError, match="payload is stale"):
        validate_annotation_authority(annotation, {"authority-1": "e" * 64})


@pytest.mark.parametrize("category", [
    "direct_contradiction", "stale_superseded", "suspicion_as_fact",
    "audience_leak", "resolved_as_active", "incompatible_state",
])
def test_six_categories_require_paired_evidence_for_mechanical_findings(category: str) -> None:
    base = dict(
        finding_id=f"finding-{category}", revision=1, categories=(category,),
        rule_id="claims", rule_version="1", audience="gm", effective_horizon="chapter-3",
        basis="mechanical", severity="blocking", evidence=("left", "right"), rationale="Conflict.",
        next_action="Correct and regenerate.", required_disposition=True, semantic_digest="d" * 64,
    )
    finding = ClaimFinding.model_validate({**base, "annotation_ids": ("left", "right")})
    assert len(finding.annotation_ids) == 2
    with pytest.raises(ValidationError, match="both compared"):
        ClaimFinding.model_validate({**base, "annotation_ids": ("left",), "missing_counterpart": "unknown"})


def test_equal_authority_conflict_is_retained_without_a_chosen_winner() -> None:
    finding = ClaimFinding(
        finding_id="equal-authority", revision=1, categories=("direct_contradiction",),
        annotation_ids=("claim-a", "claim-b"), rule_id="claims", rule_version="1",
        audience="gm", effective_horizon="chapter-3", basis="mechanical", severity="blocking",
        evidence=("equally authoritative A", "equally authoritative B"), rationale="No precedence relation exists.",
        next_action="Adjudicate authority; do not choose by filename or date.", required_disposition=True,
        semantic_digest="e" * 64,
    )
    assert finding.decision_event_id is None
    assert "do not choose" in finding.next_action.lower()


def test_select_cli_resolves_configured_out_root_relative_to_config(tmp_path: Path, capsys) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    assert claims_run([
        "select", "--config", str(root / "config/grounding.yaml"),
        "--since", "1", "--until", "3", "--json",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["data"]["selection"]["out_root"] == "docs/summary_native"


def test_bundle_rule_order_is_canonical_for_select_then_save(tmp_path: Path) -> None:
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    kwargs = dict(out_root="docs/summary_native", since=1, until=3,
                  campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="claims-selection",
                  config_path=root / "config/grounding.yaml")
    forward = build_bundle_selection(root, **kwargs, rule_versions=("grounding-claims/1", "grounding-bundle-signoff/2"))
    reversed_rules = build_bundle_selection(root, **kwargs, rule_versions=("grounding-bundle-signoff/2", "grounding-claims/1"))
    assert forward.rule_versions == reversed_rules.rule_versions
    assert bundle_source_digest(forward) == bundle_source_digest(reversed_rules)


def test_selection_save_requires_reviewer_for_unconfirmed_input(tmp_path: Path, capsys) -> None:
    root, _bundle_value, proposed = _selection(tmp_path)
    selection_file = tmp_path / "unconfirmed.json"; selection_file.write_bytes(canonical_bytes(proposed))
    config = root / "config/grounding.yaml"
    argv = ["claims", "selection", "save", "--config", str(config), "--input", str(selection_file), "--json"]
    assert summary_native_main(argv) == 2
    refused = json.loads(capsys.readouterr().out)
    assert refused["code"] == "CLAIMS_SELECTION_UNCONFIRMED"
    assert summary_native_main([*argv[:-1], "--reviewer", "Browser GM", "--json"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["ok"] is True and saved["data"]["confirmed_digest"]
    persisted = SourceSelection.model_validate_json((root / saved["data"]["path"]).read_bytes())
    assert persisted.confirmed_by == "Browser GM"
    # A browser refresh retries the same explicit confirmation. Preserve the
    # immutable first timestamp/digest instead of manufacturing a conflict.
    assert summary_native_main([*argv[:-1], "--reviewer", "Browser GM", "--json"]) == 0
    retried = json.loads(capsys.readouterr().out)
    assert retried["data"]["path"] == saved["data"]["path"]
    assert retried["data"]["confirmed_digest"] == saved["data"]["confirmed_digest"]


@pytest.mark.parametrize("code", ["CLAIMS_SELECTION_CONFLICT", "CLAIMS_REPORT_CONFLICT"])
def test_immutable_private_write_has_atomic_no_replace_publication(tmp_path: Path, code: str) -> None:
    root = tmp_path / "campaign"; root.mkdir()
    destination = root / "private/current.json"
    barrier = threading.Barrier(2)

    def publish(data: bytes):
        barrier.wait()
        try:
            _write_owner_only(root, destination, data, conflict_code=code)
            return "saved"
        except PromotionError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, (b"first", b"second")))
    assert sorted(outcomes) == sorted(["saved", code])
    assert destination.read_bytes() in {b"first", b"second"}


def test_claims_cli_import_review_check_and_show_use_chosen_review(tmp_path: Path, capsys) -> None:
    root, _bundle_value, proposed = _selection(tmp_path)
    nonempty = next(item for item in proposed.sources if (root / item.path).stat().st_size)
    chosen = select_whole_source_chunks(root, proposed, (nonempty.source_id,))
    confirmed = confirm_selection(chosen, reviewer="gm", confirmed_at=NOW)
    selection_file = tmp_path / "selection.json"
    selection_file.write_bytes(canonical_bytes(confirmed))
    save_confirmed_selection(root, confirmed)
    packet = assemble_packet(root, confirmed); chunk = packet.chunks[0]
    word = chunk.text.encode("utf-8")[:4].decode("utf-8")
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"annotations": [{
        "occurrence_id": "cli-candidate", "chunk_id": chunk.chunk_id,
        "start_byte": 0, "end_byte": len(word.encode()), "original_span": word,
        "subject_id": "cli-topic", "subject_kind": "topic", "predicate": "status",
        "normalized_value": "active", "certainty": "certain", "audience": "gm",
        "effective_from": "chapter-1", "effective_until": "chapter-3",
    }]}))
    config = root / "config/grounding.yaml"
    assert summary_native_main(["claims", "import", "--config", str(config), "--selection", str(selection_file), "--candidates", str(candidates), "--json"]) == 0
    imported = json.loads(capsys.readouterr().out)["data"]["path"]
    assert summary_native_main(["claims", "review", "--config", str(config), "--selection", str(selection_file), "--candidates", imported, "--review", "MY-ID", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["review"] == "MY-ID"
    assert summary_native_main(["claims", "check", "--config", str(config), "--selection", str(selection_file), "--review", "MY-ID", "--json"]) == 5
    checked = json.loads(capsys.readouterr().out)
    report_path = checked["data"]["paths"][0]
    assert summary_native_main(["claims", "show", "--config", str(config), "--report", report_path, "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)["data"]
    assert shown["report"]["outcome"] == "blocked"
    assert shown["freshness"]["state"] == "current"
    second = tmp_path / "second-candidates.json"
    second.write_text(json.dumps({"annotations": [{
        "occurrence_id": "cli-new-required", "chunk_id": chunk.chunk_id,
        "start_byte": 0, "end_byte": len(word.encode()), "original_span": word,
        "subject_id": "cli-topic", "subject_kind": "topic", "predicate": "status",
        "normalized_value": "needs-review", "certainty": "certain", "audience": "gm",
        "effective_from": "chapter-1", "effective_until": "chapter-3",
    }]}))
    assert summary_native_main(["claims", "import", "--config", str(config), "--selection", str(selection_file),
                                "--candidates", str(second), "--json"]) == 0
    second_import = json.loads(capsys.readouterr().out)["data"]["path"]
    assert summary_native_main(["claims", "review", "--config", str(config), "--selection", str(selection_file),
                                "--candidates", second_import, "--review", "MY-ID", "--json"]) == 0
    capsys.readouterr()
    assert summary_native_main(["claims", "show", "--config", str(config), "--report", report_path, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["freshness"]["state"] == "stale"
    from pipelines.summary_native.claims.report import load_current_report
    current_bundle = build_bundle_selection(
        root, out_root=confirmed.out_root, since=confirmed.range_since, until=confirmed.range_until,
        campaign_id=confirmed.campaign_id, review_id="MY-ID", rule_versions=confirmed.rule_versions,
        config_path=config,
    )
    with pytest.raises(PromotionError, match="stale under current review inputs"):
        load_current_report(root, report_path, current_bundle)


def test_claims_cli_no_mapping_flow_creates_coverage_then_four_signoffs(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import campaignlib
    model_calls = {"count": 0}

    def forbidden_model_call(*_args, **_kwargs):
        model_calls["count"] += 1
        raise AssertionError("deterministic claims review/check invoked the model seam")

    monkeypatch.setattr(campaignlib, "stream_api", forbidden_model_call)
    monkeypatch.setattr(campaignlib, "client_from_args", forbidden_model_call)
    root, _bundle_value, proposed = _selection(tmp_path)
    confirmed = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    selection_file = tmp_path / "selection.json"; selection_file.write_bytes(canonical_bytes(confirmed))
    config = root / "config/grounding.yaml"
    assert summary_native_main(["claims", "review", "--config", str(config), "--selection", str(selection_file),
                                "--review", "NO-MODEL", "--json"]) == 0
    capsys.readouterr()
    assert summary_native_main(["claims", "check", "--config", str(config), "--selection", str(selection_file),
                                "--review", "NO-MODEL", "--json"]) == 0
    capsys.readouterr()
    from pipelines.summary_native.review.store import read_snapshot
    _manifest, _custody, items = read_snapshot(root, "NO-MODEL")
    assert {item.item_id for item in items if item.proposed_action.action == "signoff_document"} == {
        "document-world_state", "document-campaign_state", "document-party", "document-planning",
    }
    assert model_calls["count"] == 0
