"""Synthetic ground truth. Entity IDs have no location/name semantics.

Queries contain no expected entity IDs. The evaluator alone sees gold answers.
All four creature labels are identical; duplicate level/room labels also occur.
The world is an annotated fixture, not an automatic extraction from prose.
"""
from copy import deepcopy

A, B, C, D = "e_7c2f", "e_91d0", "e_a340", "e_6f18"


def make_world():
    entities = [{"id": eid, "campaign": "game", "kind": "creature", "labels": ["bugbear"]}
                for eid in (A, B, C, D)]
    locations = [
        {"id": "d1", "campaign": "game", "label": "dungeon", "parent": None},
        {"id": "d2", "campaign": "game", "label": "dungeon", "parent": None},
        *[{"id": f"d1-l{i}", "campaign": "game", "label": f"level {i}", "parent": "d1"}
          for i in (1, 2, 3)],
        {"id": "d2-l1", "campaign": "game", "label": "level 1", "parent": "d2"},
        {"id": "d1-l1-cell", "campaign": "game", "label": "room 12", "parent": "d1-l1"},
        {"id": "d1-l2-cell", "campaign": "game", "label": "room 12", "parent": "d1-l2"},
        {"id": "d1-l2-stairs", "campaign": "game", "label": "stairs", "parent": "d1-l2"},
        {"id": "d1-l3-cave", "campaign": "game", "label": "cave", "parent": "d1-l3"},
    ]
    facts, sources = [], []

    def add(entity, prop, value, start, end, quote):
        source = f"s{len(sources)+1:02}"
        sources.append({"id": source, "campaign": "game", "text": quote,
                        "class": "synthetic hand-annotated tracking evidence"})
        facts.append({"entity_id": entity, "property": prop, "value": value,
                      "valid_from": start, "valid_until": end,
                      "evidence": {"source": source, "quote": quote}})

    add(A, "location", "d1-l1-cell", 0, 10, "The torn-eared bugbear occupies room 12 on level one until turn 10.")
    add(A, "location", "d1-l2-stairs", 10, 20, "At turn 10 the same torn-eared bugbear moves to the level-two stairs, tracked through turn 20.")
    add(B, "location", "d1-l2-cell", 0, 100, "A different bugbear guards room 12 on level two throughout the observation window.")
    add(C, "location", "d1-l3", 0, 100, "The third bugbear stays on level three throughout the observation window.")
    add(D, "location", "d2-l1", 0, 100, "Another bugbear stays on level one of the other dungeon throughout the observation window.")
    for entity in (A, B, C, D):
        add(entity, "torn_ear", "yes" if entity == A else "no", 0, 100,
            f"Tracking observation for {entity}: torn ear is {'present' if entity == A else 'absent'}.")
    add(A, "life", "alive", 0, 15, "The torn-eared bugbear is alive before turn 15.")
    add(A, "life", "dead", 15, 100, "The torn-eared bugbear dies at turn 15; its corpse remains the same tracked individual.")
    for entity in (B, C, D):
        add(entity, "life", "alive", 0, 100, f"Tracking observation for {entity}: alive during the observation window.")
        add(entity, "role", "guard", 0, 100, f"Tracking observation for {entity}: ordinary guard during the observation window.")
    add(A, "role", "leader", 10, 100, "The torn-eared bugbear becomes the leader at turn 10; earlier rank is unrecorded.")
    return {"schema": 1, "synthetic": True, "entities": entities, "locations": locations,
            "sources": sources, "facts": facts}


def make_cases():
    cases = []

    def add(name, status, ids, **context):
        mention = {"id": name, "text": "the bugbear", "label": "bugbear", "campaign": "game", "at": 5}
        mention.update(context)
        cases.append({"mention": mention, "expected_status": status, "expected_candidates": sorted(ids)})

    add("level_one", "supported_candidate", [A], scene_location="d1-l1")
    add("level_two", "supported_candidate", [B], scene_location="d1-l2")
    add("level_three", "supported_candidate", [C], scene_location="d1-l3")
    add("no_location", "ambiguous", [A, B, C, D])
    add("dungeon_only", "ambiguous", [A, B, C], scene_location="d1")
    add("same_level_number_other_dungeon", "supported_candidate", [D], scene_location="d2-l1")
    add("same_room_number_level_one", "supported_candidate", [A], scene_location="d1-l1-cell")
    add("same_room_number_level_two", "supported_candidate", [B], scene_location="d1-l2-cell")
    add("moving_individual_keeps_id", "supported_candidate", [A], at=12,
        scene_location="d1-l2", features={"torn_ear": "yes"})
    add("two_bugbears_on_level_two", "ambiguous", [A, B], at=12, scene_location="d1-l2")
    add("room_separates_same_level", "supported_candidate", [B], at=12, scene_location="d1-l2-cell")
    add("stairs_separate_same_level", "supported_candidate", [A], at=12, scene_location="d1-l2-stairs")
    add("plural_is_a_group", "candidate_group", [A, B], at=12, scene_location="d1-l2", number="plural")
    add("reference_overrides_speaker_location", "supported_candidate", [C], scene_location="d1-l2",
        referent_locations=["d1-l3"], text="the bugbear on level three")
    add("historical_reference_uses_historical_time", "supported_candidate", [A], at=16, referent_at=5,
        scene_location="d1-l2", referent_locations=["d1-l1"], text="the bugbear we met on level one earlier")
    add("no_future_role_leak", "insufficient_evidence", [A], features={"role": "leader"})
    add("later_role_supports_identity", "supported_candidate", [A], at=12, features={"role": "leader"})
    add("alive_vs_corpse", "supported_candidate", [B], at=16, scene_location="d1-l2", features={"life": "alive"})
    add("corpse_keeps_individual_id", "supported_candidate", [A], at=16, scene_location="d1-l2", features={"life": "dead"})
    add("expired_location_does_not_persist", "insufficient_evidence", [A], at=30, scene_location="d1-l1")
    add("unknown_competitor_blocks_unique", "ambiguous", [A, C], at=30, scene_location="d1-l3")
    add("coarse_location_cannot_prove_specific_room", "insufficient_evidence", [C], scene_location="d1-l3-cave")
    add("incompatible_description_no_new_entity", "no_supported_candidate", [], scene_location="d1-l3", features={"torn_ear": "yes"})
    add("unknown_time_abstains", "ambiguous", [A, B, C, D], at=None, scene_location="d1-l1")
    add("contradictory_referent_scopes", "conflicting_context", [], referent_locations=["d1-l1", "d1-l2"])
    add("compatible_parent_child_scopes", "supported_candidate", [B], referent_locations=["d1-l2", "d1-l2-cell"])
    return cases


def missing_location_world():
    world = deepcopy(make_world())
    world["facts"] = [f for f in world["facts"] if not (f["entity_id"] == A and f["property"] == "location")]
    return world


def conflicting_location_world():
    world = deepcopy(make_world())
    world["sources"].append({"id": "conflict", "campaign": "game", "text": "A conflicting tracker places the torn-eared individual on level two at turn 5."})
    world["facts"].append({"entity_id": A, "property": "location", "value": "d1-l2-stairs",
                           "valid_from": 0, "valid_until": 10,
                           "evidence": {"source": "conflict", "quote": world["sources"][-1]["text"]}})
    return world
