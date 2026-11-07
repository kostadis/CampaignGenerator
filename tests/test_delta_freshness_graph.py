"""Spec 039 T017: per-item dependency graph (SC-005 B/A case). Pure, no I/O."""

import json

import pytest

from pipelines.summary_native.freshness import DependencyGraph, DepNode

A_DRAFT = DepNode("draft", "A")
A_EV = DepNode("evidence", "A")
B_EV = DepNode("evidence", "B")
SHARED = DepNode("shared_source", "chapter-75")
OTHER = DepNode("rule", "unrelated")


def build() -> DependencyGraph:
    g = DependencyGraph()
    g.add("A", A_DRAFT, "d1")
    g.add("A", A_EV, "e1")
    g.add("A", SHARED, "s1")
    g.add("B", B_EV, "e2")
    g.add("B", SHARED, "s1")
    return g


def current() -> dict:
    return {A_DRAFT: "d1", A_EV: "e1", B_EV: "e2", SHARED: "s1", OTHER: "x"}


def test_consumers_and_dependencies():
    g = build()
    assert g.consumers(SHARED) == frozenset({"A", "B"})
    assert g.consumers(B_EV) == frozenset({"B"})
    assert g.consumers(OTHER) == frozenset()
    assert g.dependencies("B") == {B_EV: "e2", SHARED: "s1"}


def test_affected_by_is_exact_union():
    g = build()
    assert g.affected_by([B_EV]) == frozenset({"B"})
    assert g.affected_by([SHARED]) == frozenset({"A", "B"})
    assert g.affected_by([OTHER]) == frozenset()
    assert g.affected_by([A_EV, B_EV]) == frozenset({"A", "B"})


def test_unchanged_is_not_stale():
    assert build().stale_items(current()) == {}


def test_b_evidence_change_stales_only_b():
    cur = current() | {B_EV: "e2b"}
    assert build().stale_items(cur) == {"B": ["evidence:B changed"]}


def test_shared_change_stales_both():
    cur = current() | {SHARED: "s2"}
    assert set(build().stale_items(cur)) == {"A", "B"}


def test_unrelated_change_stales_neither():
    assert build().stale_items(current() | {OTHER: "y"}) == {}


def test_draft_change_names_draft():
    stale = build().stale_items(current() | {A_DRAFT: "d2"})
    assert list(stale) == ["A"]
    assert stale["A"] == ["draft:A changed"]


def test_missing_node_counts_as_changed():
    cur = current()
    del cur[B_EV]
    assert build().stale_items(cur) == {"B": ["evidence:B missing"]}


def test_item_stale():
    g = build()
    assert g.item_stale("A", current()) == []
    assert g.item_stale("A", current() | {A_DRAFT: "d2"}) == ["draft:A changed"]
    assert "no recorded dependencies" in g.item_stale("Z", current())[0]


def test_round_trip_and_deterministic():
    g = build()
    d = g.to_dict()
    assert d["schema_version"] == 1
    assert DependencyGraph.from_dict(json.loads(json.dumps(d))) == g
    other = DependencyGraph()  # insertion order differs
    for item, node, dig in [("B", SHARED, "s1"), ("B", B_EV, "e2"), ("A", SHARED, "s1"),
                            ("A", A_EV, "e1"), ("A", A_DRAFT, "d1")]:
        other.add(item, node, dig)
    assert json.dumps(other.to_dict()) == json.dumps(g.to_dict())


def test_bad_kind_and_schema_refused():
    with pytest.raises(ValueError):
        DepNode("bogus", "x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DependencyGraph.from_dict({"schema_version": 99, "items": {}})
