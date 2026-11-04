from copy import deepcopy
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from contextual_identity import ContextIndex
from fixtures import A, B, C, D, make_cases, make_world, missing_location_world, conflicting_location_world


@pytest.mark.parametrize("case", make_cases(), ids=lambda case: case["mention"]["id"])
def test_held_out_mentions(case):
    result = ContextIndex(make_world()).resolve(case["mention"])
    assert result["status"] == case["expected_status"]
    assert result["candidate_ids"] == case["expected_candidates"]
    assert (result["proposed_entity_id"] is not None) == (result["status"] == "supported_candidate")


def test_same_label_does_not_collapse_instances():
    graph = ContextIndex(make_world())
    assert graph.db.execute("SELECT count(*) FROM labels WHERE label='bugbear'").fetchone()[0] == 4
    assert graph.db.execute("SELECT count(DISTINCT id) FROM entities").fetchone()[0] == 4


def test_resolution_does_not_depend_on_the_word_bugbear():
    world = make_world()
    for entity in world["entities"]:
        entity["labels"] = ["sentinel"]
    graph = ContextIndex(world)
    for case in make_cases():
        mention = deepcopy(case["mention"])
        mention["label"] = "sentinel"
        result = graph.resolve(mention)
        assert result["status"] == case["expected_status"]
        assert result["candidate_ids"] == case["expected_candidates"]


def test_missing_observation_keeps_unknown_competitor():
    result = ContextIndex(missing_location_world()).resolve({"id": "unknown", "label": "bugbear", "campaign": "game", "at": 5, "scene_location": "d1-l2"})
    assert result["status"] == "ambiguous" and result["candidate_ids"] == [A, B]


def test_conflicting_observations_block_unique_proposal():
    result = ContextIndex(conflicting_location_world()).resolve({"id": "conflict", "label": "bugbear", "campaign": "game", "at": 5, "scene_location": "d1-l1"})
    assert result["status"] == "conflicting_evidence"
    assert result["proposed_entity_id"] is None
    assert result["candidate_ids"] == [A]


def test_opaque_ids_can_be_replaced_without_changing_answers():
    original = make_world()
    changed = deepcopy(original)
    permutation = dict(zip((A, B, C, D), ("z8", "k1", "j3", "b2")))
    for entity in changed["entities"]:
        entity["id"] = permutation[entity["id"]]
    for fact in changed["facts"]:
        fact["entity_id"] = permutation[fact["entity_id"]]
    for case in make_cases():
        result = ContextIndex(changed).resolve(case["mention"])
        assert result["status"] == case["expected_status"]
        assert result["candidate_ids"] == sorted(permutation[e] for e in case["expected_candidates"])


def test_import_order_does_not_choose_first_match():
    changed = make_world()
    random.Random(73).shuffle(changed["entities"])
    random.Random(91).shuffle(changed["facts"])
    for case in make_cases():
        result = ContextIndex(changed).resolve(case["mention"])
        assert result["status"] == case["expected_status"]
        assert result["candidate_ids"] == case["expected_candidates"]


def test_gold_ids_cannot_be_passed_to_resolver():
    with pytest.raises(ValueError, match="unexpected mention fields"):
        ContextIndex(make_world()).resolve({"id": "leak", "label": "bugbear", "campaign": "game", "expected_id": A})


def test_campaign_is_an_identity_boundary():
    world = make_world()
    world["entities"].append({"id": "other", "campaign": "another-game", "kind": "creature", "labels": ["bugbear"]})
    graph = ContextIndex(world)
    result = graph.resolve({"id": "scoped", "label": "bugbear", "campaign": "another-game", "at": 5})
    assert result["candidate_ids"] == ["other"] and result["status"] == "insufficient_evidence"
    with pytest.raises(ValueError, match="cross-campaign query scope"):
        graph.resolve({"id": "leak", "label": "bugbear", "campaign": "another-game", "at": 5, "scene_location": "d1-l1"})


def test_unknown_type_does_not_create_an_entity():
    result = ContextIndex(make_world()).resolve({"id": "none", "label": "unregistered-creature", "campaign": "game", "at": 5})
    assert result["status"] == "not_found" and not result["candidate_ids"]


def test_evidence_must_match_source():
    world = make_world()
    world["facts"][0]["evidence"]["quote"] = "invented evidence"
    with pytest.raises(ValueError, match="exact source span"):
        ContextIndex(world)


def test_location_cycles_refused():
    world = make_world()
    world["locations"][0]["parent"] = "d1-l1"
    with pytest.raises(ValueError, match="cycle"):
        ContextIndex(world)


def test_future_fact_does_not_resolve_past_mention():
    case = next(c for c in make_cases() if c["mention"]["id"] == "no_future_role_leak")
    result = ContextIndex(make_world()).resolve(case["mention"])
    assert result["status"] == "insufficient_evidence"
    for candidate in result["evaluated"]:
        for checked in candidate["matches"] + candidate["contradictions"]:
            assert all(e["valid_from"] <= 5 < e["valid_until"] for e in checked["evidence"])


def test_resolution_does_not_mutate_world():
    world = make_world()
    before = deepcopy(world)
    graph = ContextIndex(world)
    for case in make_cases():
        graph.resolve(case["mention"])
    assert world == before


def test_current_registry_schema_cannot_represent_duplicate_labels():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from campaignlib.registry import Entity, Registry, validate
    with pytest.raises(ValueError, match="identity collision"):
        validate(Registry(version=1, campaign="synthetic", entities=[Entity(name="bugbear", type="npc"),
                                             Entity(name="bugbear", type="npc")]))
