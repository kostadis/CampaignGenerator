from __future__ import annotations

import pytest

from pipelines.summary_native.authority import AuthorityError, Classification, EffectiveInterval, Projection
from pipelines.summary_native.authority_inputs import resolve_planning_precedence
from tests.test_summary_native_authority_audience import _note


def _record(identifier: str, classification: Classification, value: str):
    return _note().model_copy(update={
        "id": identifier, "classification": classification,
        "projections": frozenset({Projection.PLANNING}), "claim_key": "commission",
        "normalized_value": value,
    })


def test_overlay_wins_over_prep_and_open_remains_a_warning():
    prep = _record("commission-prep", Classification.PREP, "wait")
    overlay = _record("commission-overlay", Classification.OVERLAY, "act")
    selected, warnings = resolve_planning_precedence([prep, overlay])
    assert [record.id for record in selected] == ["commission-overlay"]
    opened = _record("commission-open", Classification.OPEN, "question").model_copy(
        update={"claim_key": "other"}
    )
    _, warnings = resolve_planning_precedence([opened])
    assert "open planning question" in warnings[0]


def test_equal_overlay_conflict_refuses():
    with pytest.raises(AuthorityError, match="equal OVERLAY"):
        resolve_planning_precedence([
            _record("commission-one", Classification.OVERLAY, "one"),
            _record("commission-two", Classification.OVERLAY, "two"),
        ])


def test_canon_then_table_supersession_and_disjoint_intervals_are_deterministic():
    canon = _record("commission-canon", Classification.CANON, "canon").model_copy(
        update={"effective": EffectiveInterval(from_chapter=1, through_chapter=10)}
    )
    table = _record("commission-table", Classification.TABLE, "table").model_copy(
        update={"effective": EffectiveInterval(from_chapter=11, through_chapter=20)}
    )
    selected, _ = resolve_planning_precedence([canon, table])
    assert [record.id for record in selected] == ["commission-canon", "commission-table"]


def test_overlapping_canon_supersedes_table():
    canon = _record("commission-canon-overlap", Classification.CANON, "canon").model_copy(
        update={"effective": EffectiveInterval(from_chapter=1, through_chapter=20)}
    )
    table = _record("commission-table-overlap", Classification.TABLE, "table").model_copy(
        update={"effective": EffectiveInterval(from_chapter=10, through_chapter=30)}
    )
    selected, _ = resolve_planning_precedence([table, canon])
    assert [record.id for record in selected] == ["commission-canon-overlap"]
