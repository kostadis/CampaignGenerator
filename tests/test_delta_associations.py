"""T042: only approved associations reach drafting; the registry is never written (N4)."""

from __future__ import annotations

import json

import pytest

from _delta_us2 import copy_fixture, make_plan
from pipelines.summary_native.delta import associations as asc
from pipelines.summary_native.delta.errors import DeltaRefusal

QUOTE = "the Lantern Guild would buy every blade the forge could make"


def _caller(items):
    return lambda client, system, user, model: json.dumps(items)


@pytest.fixture
def env(tmp_path):
    root = copy_fixture(tmp_path)
    plan = make_plan(root)
    items = [
        {"name": "Old Marrow Pike", "canonical_id": "The Lantern Guild", "scene": "003.02",
         "relationship_support": QUOTE, "rationale": "relays the offer", "scope": "faction offer"},
        {"name": "Pike", "canonical_id": "Nobody Registered", "scene": "003.02",
         "relationship_support": QUOTE, "scope": "x"},
        {"name": "Pike", "canonical_id": "The Lantern Guild", "scene": "003.02",
         "relationship_support": "a quote that is not in the source", "scope": "x"},
    ]
    store = asc.propose(root, plan, [{"name": "Old Marrow Pike", "evidence": []}], caller=_caller(items),
                        client=object())
    return root, plan, store


def test_proposals_start_unresolved_and_bad_ones_are_dropped(env):
    _, _, store = env
    assert len(store.associations) == 1 and store.associations[0].decision == "unresolved"
    assert {d["reason"] for d in store.dropped} == {"canonical_id_not_in_registry",
                                                    "support_not_verbatim_in_selected_source"}
    a = store.associations[0]
    assert a.scope == "faction offer" and a.source.scene == "003.02" and len(a.source.revision) == 64


def test_only_approved_enter_drafting(env):
    root, plan, store = env
    aid = store.associations[0].id
    assert asc.approved_associations(root, plan.plan_id) == []
    for d in ("reject", "discuss"):
        asc.decide(root, plan.plan_id, aid, d, "gm")
        assert asc.approved_associations(root, plan.plan_id) == []
        with pytest.raises(DeltaRefusal):
            asc.require_approved(root, plan.plan_id, aid)
    a = asc.decide(root, plan.plan_id, aid, "approve", "gm")
    assert a.decision_revision == 3 and [h["decision"] for h in a.history] == ["rejected", "discuss", "approved"]
    assert [x.id for x in asc.approved_associations(root, plan.plan_id)] == [aid]
    assert asc.require_approved(root, plan.plan_id, aid).id == aid


def test_decide_requires_reviewer_and_known_id(env):
    root, plan, store = env
    with pytest.raises(DeltaRefusal):
        asc.decide(root, plan.plan_id, store.associations[0].id, "approve", " ")
    with pytest.raises(DeltaRefusal):
        asc.decide(root, plan.plan_id, "assoc-nope", "approve", "gm")
    with pytest.raises(DeltaRefusal):
        asc.decide(root, plan.plan_id, store.associations[0].id, "maybe", "gm")


def test_registry_bytes_unchanged_and_no_alias_added(env):
    root, plan, store = env
    reg = root / "docs" / "entity_registry.yaml"
    before = reg.read_bytes()
    asc.decide(root, plan.plan_id, store.associations[0].id, "approve", "gm")
    assert reg.read_bytes() == before
    assert "Old Marrow Pike" not in reg.read_text(encoding="utf-8")


def test_repropose_keeps_decisions(env):
    root, plan, store = env
    aid = store.associations[0].id
    asc.decide(root, plan.plan_id, aid, "approve", "gm")
    items = [{"name": "Old Marrow Pike", "canonical_id": "The Lantern Guild", "scene": "003.02",
              "relationship_support": QUOTE, "scope": "faction offer"}]
    again = asc.propose(root, plan, [], caller=_caller(items), client=object())
    assert len(again.associations) == 1 and again.associations[0].decision == "approved"
