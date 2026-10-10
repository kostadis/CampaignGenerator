from __future__ import annotations

import pytest

from pipelines.summary_native.authority import (
    AuthorityError,
    AuthorityLedger,
    AudienceGrant,
    Classification,
    EffectiveInterval,
    NoteRecord,
    Projection,
    RulingRecord,
    SubjectRef,
    dismiss_conflict,
    detect_conflicts,
    human_conflict_candidate,
    ledger_bytes,
    record_human_conflict,
    resolve_conflict,
)


def _note(identifier: str, *, supersedes: str | None = None) -> NoteRecord:
    return NoteRecord(
        id=identifier, kind="note", revision=1, classification=Classification.CANON,
        subject=SubjectRef(kind="topic", id="gate"), claim_key="gate-state", normalized_value=identifier,
        effective=EffectiveInterval(from_chapter=1, through_chapter=3), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.WORLD_STATE}, status="active", recorded_at="2026-10-09T00:00:00Z",
        recorded_by="GM", supersedes=supersedes, source={"path": f"notes/{identifier}.md", "anchor": "gate"},
        content_digest="a" * 64, selection_label=identifier,
    )


def _ruling(identifier: str, *, supersedes: str | None = None) -> RulingRecord:
    return RulingRecord(
        id=identifier, kind="ruling", revision=1, classification=Classification.RULED,
        subject=SubjectRef(kind="topic", id="gate"), claim_key="gate-state", normalized_value=identifier,
        effective=EffectiveInterval(from_chapter=1, through_chapter=3), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.WORLD_STATE}, status="applied", recorded_at="2026-10-09T00:00:00Z",
        recorded_by="GM", supersedes=supersedes, source={"path": f"docs/summaries/{identifier}.md", "anchor": "gate"},
        rejected_claim="old gate state", replacement_fact="new gate state", proposal_id=f"{identifier}-proposal",
        applied_receipt=f"{identifier}-receipt",
    )


def test_human_prose_candidate_has_no_machine_verdict_and_can_be_resolved_or_dismissed():
    candidate = human_conflict_candidate("prose-candidate", {"one", "two"})
    assert candidate.basis == "prose_candidate" and candidate.status == "open"
    resolved = candidate.model_copy(update={"status": "resolved", "resolution_record": "resolution"})
    dismissed = candidate.model_copy(update={"status": "dismissed"})
    assert resolved.status == "resolved" and dismissed.status == "dismissed"


def test_human_identified_conflict_is_distinct_from_a_prose_candidate():
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[_note("one"), _note("two")])
    updated = record_human_conflict(ledger, conflict_id="gm-identified", record_ids={"one", "two"})
    assert updated.conflicts[0].basis == "human_identified"
    assert ledger.conflicts == []
    candidate = human_conflict_candidate("prose-candidate", {"one", "two"})
    assert candidate.basis == "prose_candidate"


def test_resolution_is_immutable_and_rejects_a_stale_ledger_revision():
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[_note("one"), _note("two"), _ruling("resolution", supersedes="one")])
    identified = record_human_conflict(ledger, conflict_id="gm-identified", record_ids={"one", "two"})
    resolved = resolve_conflict(
        identified, "gm-identified", resolution_record="resolution", expected_revision=identified.revision
    )
    assert identified.conflicts[0].status == "open"
    assert resolved.conflicts[0].status == "resolved"
    assert resolved.conflicts[0].resolution_record == "resolution"
    assert b"status: open" in ledger_bytes(identified)
    assert b"status: resolved" in ledger_bytes(resolved)
    with pytest.raises(AuthorityError, match="AUTH_STALE"):
        resolve_conflict(resolved, "gm-identified", resolution_record="resolution", expected_revision=identified.revision)
    dismissed = dismiss_conflict(identified, "gm-identified", expected_revision=identified.revision)
    assert dismissed.conflicts[0].status == "dismissed"


def test_revising_compared_record_creates_a_new_open_finding_but_unchanged_inputs_keep_disposition():
    resolution = _ruling("resolution", supersedes="one").model_copy(update={"normalized_value": "two"})
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[_note("one"), _note("two"), resolution])
    conflict = detect_conflicts(ledger)[0]
    resolved = resolve_conflict(ledger, conflict.id, resolution_record="resolution", expected_revision=ledger.revision)
    assert [conflict.status for conflict in resolved.conflicts] == ["resolved"]
    assert [conflict.status for conflict in detect_conflicts(resolved)] == ["resolved"]

    revised_two = _note("two").model_copy(update={"revision": 2, "normalized_value": "two-revised"})
    revised = AuthorityLedger(
        version=2, campaign="x", revision=resolved.revision + 1,
        records=[_note("one"), revised_two, resolution],
        conflicts=resolved.conflicts,
    )
    refreshed = detect_conflicts(revised)
    assert any(conflict.status == "resolved" for conflict in refreshed)
    assert any(
        conflict.status == "open" and conflict.record_ids == frozenset({"one", "two"})
        for conflict in refreshed
    )


def test_supersession_cycles_and_unknown_conflict_resolution_records_are_refused():
    first = _note("first", supersedes="second")
    second = _note("second", supersedes="first")
    with pytest.raises(Exception, match="supersession cycle"):
        AuthorityLedger(version=2, campaign="x", revision=1, records=[first, second])
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[_note("one"), _note("two")])
    identified = record_human_conflict(ledger, conflict_id="gm-identified", record_ids={"one", "two"})
    with pytest.raises(AuthorityError, match="unknown resolution record"):
        resolve_conflict(identified, "gm-identified", resolution_record="gone", expected_revision=identified.revision)
