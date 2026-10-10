import json
import hashlib
import importlib.util
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipelines.summary_native.claims.check import check_claims
from pipelines.summary_native.claims.imports import bind_candidates, import_candidates
from pipelines.summary_native.claims.models import (AuthorityClass, ClaimAnnotation, ClaimPredicate,
                                                    SelectedChunk, SourceEntry, SourceRole, SourceSelection)
from pipelines.summary_native.claims.models import SourceKind
from pipelines.summary_native.claims.packets import assemble_packet
from pipelines.summary_native.claims.review import create_claim_review, load_confirmed_annotations
from pipelines.summary_native.claims.selection import confirm_selection, mandatory_source_closure
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.review.models import canonical_digest
from pipelines.summary_native.review.store import read_snapshot, save_decisions


ROOT = Path(__file__).parent / "fixtures/summary_native/promotion/phandalin_shapes"
FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("phandalin_claim_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(FACTORY)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _selection(tmp_path: Path):
    campaign = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        campaign, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="phandalin-review",
        rule_versions=("claims/1",), config_path=campaign / "config/grounding.yaml",
    )
    return mandatory_source_closure(
        campaign, bundle, effective_horizon="chapter-3", audience="gm",
        rule_versions=("claims/1",),
    )


def _claim(selection, occurrence: str, *, predicate: ClaimPredicate, value: str,
           role: SourceRole, supersedes: str | None = None,
           certainty: str = "certain") -> ClaimAnnotation:
    source = selection.sources[0]
    evidence = f"{occurrence}:{value}"
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    return ClaimAnnotation(
        occurrence_id=occurrence, revision=1, source_id=source.source_id,
        source_path=source.path, source_role=role, anchor=f"fixture:{occurrence}",
        start_byte=0, end_byte=len(evidence), source_sha256=source.sha256,
        span_sha256=digest, context_sha256=digest, original_span=evidence,
        subject_id=f"topic-{occurrence.split('-')[0]}", subject_identity_kind="topic",
        predicate=predicate, normalized_value=value, certainty=certainty,
        effective_from="chapter-1", effective_until="chapter-3", audience="gm",
        origin="human_candidate", interpretation_state="mapping_confirmed",
        mapping_event_id=f"event-{occurrence}", supersedes_occurrence_id=supersedes,
    )


def test_manifest_honestly_labels_reconstruction_and_unavailable_replay() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["historical_replay"] == "unavailable"
    assert "not recovered original" in manifest["warning"]
    assert len(manifest["cases"]) == 5
    for case in manifest["cases"]:
        assert case["surviving_sources"]
        assert "do not recover" in case["provenance_limit"]
        assert all(row["fingerprint_kind"] == "2026-10-10 surviving-source fingerprint" for row in case["surviving_sources"])
        assert all(len(row["source_sha256"]) == 64 and row["spike_locator"] for row in case["surviving_sources"])


@pytest.mark.parametrize("case", ["earthstone", "eastern-heart", "sridar", "petra", "leilon"])
def test_every_shape_has_a_labeled_negative_and_positive_control(case: str) -> None:
    negative = (ROOT / case / "negative.md").read_text()
    positive = (ROOT / case / "positive.md").read_text()
    assert "RECONSTRUCTED" in negative and "RECONSTRUCTED" in positive
    assert "Synthetic" in negative and "Synthetic" in positive


def test_petra_is_the_newer_error_control() -> None:
    assert "newer erroneous assertion" in (ROOT / "petra/negative.md").read_text()


@pytest.mark.parametrize("case", ["eastern-heart", "sridar"])
def test_semantic_controls_explicitly_require_gm_review(case: str) -> None:
    assert "requires GM review" in (ROOT / case / "positive.md").read_text()


@pytest.mark.parametrize(
    ("case", "negative", "positive", "category"),
    [
        ("earthstone", (ClaimPredicate.ACTOR, "Toren", "party"),
         (ClaimPredicate.ACTOR, "party", "party"), "direct_contradiction"),
        ("eastern-heart", (ClaimPredicate.POSTURE, "hostile", "non-hostile"),
         (ClaimPredicate.POSTURE, "non-hostile", "non-hostile"), "incompatible_state"),
        ("sridar", (ClaimPredicate.CERTAINTY, "certain", "possible"),
         (ClaimPredicate.CERTAINTY, "possible", "possible"), "suspicion_as_fact"),
        ("leilon", (ClaimPredicate.STATUS, "active", "resolved"),
         (ClaimPredicate.STATUS, "resolved", "resolved"), "resolved_as_active"),
    ],
)
def test_reconstructed_pair_outcomes_are_mechanically_checked(
    tmp_path: Path, case: str, negative, positive, category: str,
) -> None:
    selection = _selection(tmp_path)
    predicate, bad, authority = negative
    negative_rows = (
        _claim(selection, f"{case}-draft", predicate=predicate, value=bad, role=SourceRole.CLAIM),
        _claim(selection, f"{case}-authority", predicate=predicate, value=authority,
               role=SourceRole.COUNTERPART),
    )
    assert any(category in item.categories for item in check_claims(selection, negative_rows).findings)
    predicate, good, authority = positive
    positive_rows = (
        _claim(selection, f"{case}-draft", predicate=predicate, value=good, role=SourceRole.CLAIM),
        _claim(selection, f"{case}-authority", predicate=predicate, value=authority,
               role=SourceRole.COUNTERPART),
    )
    assert not any(category in item.categories for item in check_claims(selection, positive_rows).findings)


def test_petra_supersession_blocks_stale_draft_but_preserves_source_history(tmp_path: Path) -> None:
    selection = _selection(tmp_path)
    stale = (
        _claim(selection, "petra-old", predicate=ClaimPredicate.OBLIGATION_STATUS,
               value="active", role=SourceRole.CLAIM),
        _claim(selection, "petra-new", predicate=ClaimPredicate.OBLIGATION_STATUS,
               value="superseded", role=SourceRole.COUNTERPART, supersedes="petra-old"),
    )
    assert any("stale_superseded" in item.categories for item in check_claims(selection, stale).findings)
    history = tuple(item.model_copy(update={"source_role": SourceRole.COUNTERPART}) for item in stale)
    assert not any("stale_superseded" in item.categories for item in check_claims(selection, history).findings)


CASES = {
    "earthstone": ("actor_assignment", "Toren", "party", "direct_contradiction"),
    "eastern-heart": ("faction_posture", "hostile", "non-hostile", "incompatible_state"),
    "sridar": ("certainty", "certain", "possible", "suspicion_as_fact"),
    "petra": ("obligation_status", "active", "superseded", "incompatible_state"),
    "leilon": ("status", "active", "resolved", "resolved_as_active"),
}


def _persisted_pair(tmp_path: Path, case: str, *, positive: bool):
    root = FACTORY.create_campaign(tmp_path / ("positive" if positive else "negative"), baseline="legacy")
    rows = []
    for label in ("negative", "positive"):
        source = ROOT / case / f"{label}.md"
        target = root / f"summaries/reconstructed-{case}-{label}.md"
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        data = target.read_bytes(); digest = hashlib.sha256(data).hexdigest()
        rows.append((label, target.relative_to(root).as_posix(), data, digest))
    predicate, bad, good, _category = CASES[case]
    chosen = rows[1] if positive else rows[0]
    sources, chunks, proposals = [], [], []
    selected_rows = (chosen,) if positive else (chosen, rows[1])
    for index, (label, path, data, digest) in enumerate(selected_rows):
        source_id = f"{case}-{label}-{index}"
        chunk_id = f"chunk-{source_id}"
        sources.append(SourceEntry(
            source_id=source_id, path=path, sha256=digest, source_kind=SourceKind.SUMMARY,
            role=SourceRole.CLAIM if index == 0 else SourceRole.COUNTERPART,
            source_audience="gm", authority_class=AuthorityClass.OPEN,
            applicability="mapping_evidence", anchor="whole-file", excerpt_sha256=digest,
            context_sha256=digest, required=True,
        ))
        chunks.append(SelectedChunk(chunk_id=chunk_id, source_id=source_id, start_byte=0,
                                    end_byte=len(data), sha256=digest, locator="whole-file"))
        evidence_line = next(line for line in data.splitlines() if b"assertion:" in line)
        start = data.index(evidence_line); end = start + len(evidence_line)
        value = good if positive or index == 1 else bad
        proposals.append({"occurrence_id": f"{case}-{label}-{index}", "chunk_id": chunk_id,
                          "start_byte": start, "end_byte": end, "original_span": evidence_line.decode(),
                          "subject_id": f"reconstructed-{case}", "subject_kind": "topic",
                          "predicate": predicate, "normalized_value": value,
                          "certainty": "certain", "audience": "gm"})
    raw = dict(schema_version=1, campaign_id=str(FACTORY.CAMPAIGN_ID), bundle_digest="1" * 64,
               out_root="docs/summary_native", range_since=1, range_until=3,
               effective_horizon="chapter-3", audience="gm", sources=tuple(sources),
               suggested_sources=(), chunks=tuple(chunks), unresolved_scope=(),
               rule_versions=("claims/1",), selection_digest="0" * 64)
    provisional = SourceSelection.model_construct(**raw)
    raw["selection_digest"] = canonical_digest(provisional, exclude_fields=frozenset(
        {"selection_digest", "confirmed_by", "confirmed_at", "confirmed_digest"}))
    selection = confirm_selection(SourceSelection.model_validate(raw), reviewer="GM", confirmed_at=NOW)
    packet = assemble_packet(root, selection)
    payload = {"annotations": proposals}
    artifact = import_candidates(root, selection, packet, payload)
    assert artifact.is_file() and json.loads(artifact.read_text())["approved"] is False
    candidates = bind_candidates(selection, packet, payload, origin="human_candidate", campaign_dir=root)
    review_id = f"reconstructed-{case}-{'positive' if positive else 'negative'}"
    create_claim_review(root, review_id, annotations=candidates, findings=(), created_by="test",
                        rule_versions=(("claims", "1"),))
    manifest, _custody, items = read_snapshot(root, review_id)
    save_decisions(root, review_id, {"version": 1, "request_id": f"approve-{review_id}",
        "review_generation": manifest.generation, "reviewer": "GM", "decisions": [
            {"item_id": item.item_id, "item_revision": item.revision,
             "review_digest": item.review_digest, "expected_decision_revision": 0,
             "verdict": "approve", "disposition": "accept_no_change", "note": "Exact mapping approved."}
            for item in items]})
    confirmed = load_confirmed_annotations(root, review_id, candidates)
    assert len(confirmed) == len(selected_rows) and all(row.mapping_event_id for row in confirmed)
    return check_claims(selection, confirmed)


@pytest.mark.parametrize("case", tuple(CASES))
def test_reconstructed_fixture_bytes_flow_through_import_exact_review_and_check(
    tmp_path: Path, case: str,
) -> None:
    negative = _persisted_pair(tmp_path / case, case, positive=False)
    positive = _persisted_pair(tmp_path / case, case, positive=True)
    assert negative.findings
    assert all(finding.required_disposition for finding in negative.findings)
    assert positive.findings == ()
