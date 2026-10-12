from __future__ import annotations

from pipelines.summary_native.authority import (
    AuthorityLedger, AudienceGrant, Classification, EffectiveInterval, NoteRecord, Projection, RulingRecord, SourceRef, SubjectRef,
    detect_conflicts,
)


def _note(ident: str, value: str, *, start: int = 1, end: int = 3, classification=Classification.CANON):
    return NoteRecord(
        id=ident, kind="note", revision=1, classification=classification,
        subject=SubjectRef(kind="topic", id="gate"), claim_key="gate-state", normalized_value=value,
        effective=EffectiveInterval(from_chapter=start, through_chapter=end), audience=AudienceGrant(grants={"gm"}),
        projections={Projection.WORLD_STATE, Projection.PLANNING}, status="active",
        recorded_at="2026-10-09T00:00:00Z", recorded_by="GM",
        source={"path": f"notes/{ident}.md", "anchor": "gate"}, content_digest="a" * 64,
        planning_date="chapter-1" if classification is Classification.OVERLAY else None,
        selection_label=ident,
    )


def _ruling(ident: str, replacement: str) -> RulingRecord:
    return RulingRecord(
        id=ident, kind="ruling", revision=1, classification=Classification.RULED,
        subject=SubjectRef(kind="topic", id="gate"), effective=EffectiveInterval(from_chapter=1, through_chapter=3),
        audience=AudienceGrant(grants={"gm"}), projections={Projection.WORLD_STATE}, status="applied",
        recorded_at="2026-10-09T00:00:00Z", recorded_by="GM",
        source={"path": "docs/summaries/gate.md", "anchor": "gate"}, rejected_claim="The gate was open.",
        replacement_fact=replacement, proposal_id=f"{ident}-proposal", applied_receipt=f"{ident}-receipt",
    )


def test_structured_conflict_requires_claim_value_interval_and_projection_overlap():
    left, right = _note("gate-open", "open"), _note("gate-closed", "closed")
    ledger = AuthorityLedger(version=2, campaign="x", revision=1, records=[left, right])
    conflict = detect_conflicts(ledger)
    assert len(conflict) == 1 and conflict[0].basis == "structured_value"
    assert conflict[0].record_ids == frozenset({"gate-open", "gate-closed"})
    assert not detect_conflicts(AuthorityLedger(version=2, campaign="x", revision=1, records=[left, _note("later", "closed", start=4, end=5)]))
    no_projection = _note("other-projection", "closed").model_copy(
        update={"projections": frozenset({Projection.PARTY})}
    )
    no_claim = _note("unstructured", "closed").model_copy(
        update={"claim_key": None, "normalized_value": None}
    )
    assert not detect_conflicts(AuthorityLedger(
        version=2, campaign="x", revision=1, records=[left, no_projection, no_claim]
    ))


def test_equal_overlay_and_exact_anchor_conflict_without_recency_winner():
    one = _note("overlay-one", "wait", classification=Classification.OVERLAY)
    two = _note("overlay-two", "act", classification=Classification.OVERLAY)
    anchor_one = _ruling("anchor-one", "The gate was closed.")
    anchor_two = _ruling("anchor-two", "The gate was destroyed.")
    conflicts = detect_conflicts(AuthorityLedger(
        version=2, campaign="x", revision=1, records=[one, two, anchor_one, anchor_two]
    ))
    assert {c.basis for c in conflicts} == {"structured_value", "source_anchor"}
    assert all(c.status == "open" for c in conflicts)


def test_conflict_detection_only_considers_active_or_applied_records():
    active = _note("active", "open")
    retired = _note("retired", "closed").model_copy(update={"status": "retired"})
    assert not detect_conflicts(AuthorityLedger(
        version=2, campaign="x", revision=1, records=[active, retired]
    ))


def test_same_public_anchor_with_compatible_evidence_and_distinct_audiences_is_not_a_conflict():
    player = _note("player-npcs", "friendly").model_copy(update={
        "audience": AudienceGrant(grants={"players"}),
        "source": SourceRef(path="notes/public-npcs.md", anchor="public-npcs"),
    })
    ara = _note("ara-npcs", "friendly").model_copy(update={
        "audience": AudienceGrant(grants={"character:ara"}),
        "source": player.source,
    })
    assert not detect_conflicts(AuthorityLedger(version=2, campaign="x", revision=1, records=[player, ara]))


def _future(ident: str, value: str, classification=Classification.OVERLAY):
    return _note(ident, value, classification=classification).model_copy(
        update={"effective": EffectiveInterval(horizon="future")}
    )


def test_a_horizon_overlaps_bounded_records_for_conflicts_supersession_and_precedence():
    """One overlap rule: a future/open horizon has no bounds to compare, so it overlaps."""
    from pipelines.summary_native.authority_inputs import _effective_for_range, resolve_planning_precedence

    bounded, future = _note("gate-open", "open"), _future("gate-plan", "closed")
    assert bounded.effective.overlaps(future.effective) and future.effective.overlaps(bounded.effective)
    conflicts = detect_conflicts(AuthorityLedger(version=2, campaign="x", revision=1, records=[bounded, future]))
    assert [c.basis for c in conflicts] == ["structured_value"]
    assert conflicts[0].overlap == bounded.effective  # the bounded side is the precise overlap
    # Planning precedence drops the lower-precedence overlay for the same reason.
    resolved, _ = resolve_planning_precedence([bounded, future])
    assert [r.id for r in resolved] == ["gate-open"]
    # A horizon record may supersede the bounded claim it replaces.
    successor = future.model_copy(update={"supersedes": "gate-open"})
    AuthorityLedger(version=2, campaign="x", revision=1, records=[bounded, successor])
    # Range filtering is unchanged: horizons always apply, bounded records must meet the range.
    assert _effective_for_range(future.effective, 10, 12)
    assert _effective_for_range(bounded.effective, 3, 5) and not _effective_for_range(bounded.effective, 4, 5)
