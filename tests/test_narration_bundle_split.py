"""Deterministic response reconciliation for bundled narration."""

from pathlib import Path

import pytest

from session_doc.narrate import NarrationScene, split_bundled_narration


FIXTURES = Path(__file__).parent / "fixtures" / "narration_bundle"


def _scene(index: int, name: str) -> NarrationScene:
    return NarrationScene(
        index=index, scene_name=name, narrator="Alice", focus="focus",
        source_path=Path(f"{index:02d}.md"), source_kind="base",
        scene_events="events", moments="moments", voice_note=None,
        character_examples=None, previous_narrator=None,
        previous_voice_sample=None, estimated_output_tokens=500,
        output_path=Path(f"out-{index}.md"), output_existed=False,
    )


SCENES = (_scene(1, "Arrival"), _scene(2, "The Bargain"), _scene(3, "Departure"))


def test_complete_response_is_split_in_requested_order_without_markers():
    result = split_bundled_narration(
        (FIXTURES / "complete_response.txt").read_text(encoding="utf-8"), SCENES
    )

    assert result["failed"] is False
    assert [part["status"] for part in result["sections"]] == ["complete"] * 3
    assert [part["i"] for part in result["sections"]] == [1, 2, 3]
    assert all("<<<CG-SCENE" not in part["body"] for part in result["sections"])


def test_valid_short_response_classifies_empty_incomplete_and_complete():
    result = split_bundled_narration(
        (FIXTURES / "partial_response.txt").read_text(encoding="utf-8"), SCENES
    )

    assert result["failed"] is False
    assert [part["status"] for part in result["sections"]] == [
        "complete", "empty", "incomplete"
    ]


def test_recognized_subset_classifies_unreturned_scenes_as_absent():
    text = """<<<CG-SCENE 02 BEGIN: The Bargain>>>
I paid the ferryman.
<<<CG-SCENE 02 END>>>"""
    result = split_bundled_narration(text, SCENES)

    assert result["failed"] is False
    assert [part["status"] for part in result["sections"]] == [
        "absent", "complete", "absent"
    ]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("plain prose without sentinels", "NO_SECTIONS"),
        ("<<<CG-SCENE 01 BEGIN: Arrival>>>\na\n<<<CG-SCENE 01 END>>>\n"
         "<<<CG-SCENE 01 BEGIN: Arrival>>>\nb\n<<<CG-SCENE 01 END>>>",
         "DUPLICATE_INDEX"),
        ("<<<CG-SCENE 09 BEGIN: Unknown>>>\na\n<<<CG-SCENE 09 END>>>",
         "UNKNOWN_INDEX"),
        ("<<<CG-SCENE 01 BEGIN: Arrival>>>\na\n"
         "<<<CG-SCENE 02 BEGIN: The Bargain>>>\nb\n<<<CG-SCENE 02 END>>>",
         "NESTED_SECTION"),
        ("<<<CG-SCENE 01 BEGIN: Arrival>>>\na\n<<<CG-SCENE 02 END>>>",
         "MISMATCHED_END"),
        ("<<<CG-SCENE 01 END>>>", "MISMATCHED_END"),
        ("<<<CG-SCENE 01 BEGIN: Wrong name>>>\na\n<<<CG-SCENE 01 END>>>",
         "NAME_MISMATCH"),
    ],
)
def test_unsafe_marker_shapes_are_unreconcilable(text, reason):
    result = split_bundled_narration(text, SCENES)

    assert result["failed"] is True
    assert result["failure_reason"] == reason
    assert result["sections"] == []


def test_raw_out_of_order_response_is_rejected_before_shared_splitter_normalizes_it():
    result = split_bundled_narration(
        (FIXTURES / "malformed_response.txt").read_text(encoding="utf-8"), SCENES
    )

    assert result["failed"] is True
    assert result["failure_reason"] == "OUT_OF_ORDER"


def test_duplicate_scene_names_remain_safe_because_index_is_identity():
    repeated = (_scene(1, "Same Name"), _scene(2, "Same Name"))
    text = """<<<CG-SCENE 01 BEGIN: Same Name>>>
first
<<<CG-SCENE 01 END>>>
<<<CG-SCENE 02 BEGIN: Same Name>>>
second
<<<CG-SCENE 02 END>>>"""

    result = split_bundled_narration(text, repeated)
    assert [part["body"] for part in result["sections"]] == ["first", "second"]


def test_whitespace_only_name_normalization_is_allowed():
    text = """<<<CG-SCENE 01 BEGIN:  Arrival  >>>
body
<<<CG-SCENE 01 END>>>"""
    result = split_bundled_narration(text, SCENES[:1])
    assert result["failed"] is False


def test_corrupted_end_marker_at_continuation_seam_is_incomplete_not_misattributed():
    text = """<<<CG-SCENE 01 BEGIN: Arrival>>>
body
<<<CG-SCENE 01 EN"""
    result = split_bundled_narration(text, SCENES[:1])
    assert result["failed"] is False
    assert result["sections"][0]["status"] == "incomplete"
