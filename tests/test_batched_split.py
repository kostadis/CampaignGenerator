"""Tests for the batched-extraction wire protocol (013-batched-scene-extraction).

Covers `render_batched_user_prompt` (T008) and `split_batched_response`
(T009/T010) in `campaignlib/scenes.py`, per
`specs/013-batched-scene-extraction/contracts/wire-protocol.md`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaignlib
from campaignlib import load_agent_prompt
from campaignlib.scenes import (
    BATCHED_DUPLICATE_INDEX,
    BATCHED_NAME_MISMATCH,
    BATCHED_NESTED_SECTION,
    BATCHED_NO_SECTIONS,
    BATCHED_UNKNOWN_INDEX,
    render_batched_user_prompt,
    split_batched_response,
)


# The engine takes the template as a parameter — prompts belong to the CLI
# (see run_scene_extraction's system_prefix/extraction_instruction). Load the
# real on-disk prompt here so these tests exercise the shipped template.
_BATCHED_USER_TEMPLATE = load_agent_prompt("scene_extract_batched_user")


def _entry(i: int, name: str, body: str = "- bullet") -> dict:
    """A minimal stand-in for one `plan_scene_extraction` dict, mirroring
    the shape `tests/test_scene_extract.py::_plan_entry` uses for
    `group_scenes` — `split_batched_response` and `render_batched_user_prompt`
    only ever read `i`, `name` and `body`."""
    return {
        "i": i,
        "name": name,
        "body": body,
        "slug": f"scene_{i}",
        "custom_id": f"{i:02d}_scene_{i}",
        "path": Path(f"/tmp/{i:02d}_scene_{i}.md"),
        "exists": False,
    }


def _wrap(i: int, name: str, body: str) -> str:
    """Build one well-formed BEGIN/END marker pair around `body`."""
    return (
        f"<<<CG-SCENE {i:02d} BEGIN: {name}>>>\n"
        f"{body}\n"
        f"<<<CG-SCENE {i:02d} END>>>"
    )


# ── render_batched_user_prompt ─────────────────────────────────────────────────

def test_render_batched_user_prompt_includes_index_name_and_body():
    entries = [_entry(3, "The Margaster Hypothesis", "- clue one\n- clue two")]
    prompt = render_batched_user_prompt(entries, _BATCHED_USER_TEMPLATE)
    assert "### 03 — The Margaster Hypothesis" in prompt
    assert "Summary bullets (use as scope):" in prompt
    assert "- clue one" in prompt
    assert "- clue two" in prompt


def test_render_batched_user_prompt_uses_plan_index_never_position():
    """DM-1: a group built from a filtered, non-contiguous slice of the plan
    (scenes 2 and 5, with 1/3/4 already extracted and skipped) must still
    show the model each scene's REAL plan index — never a re-derived
    position like 01/02."""
    entries = [_entry(2, "Scene Two"), _entry(5, "Scene Five")]
    prompt = render_batched_user_prompt(entries, _BATCHED_USER_TEMPLATE)
    assert "### 02 — Scene Two" in prompt
    assert "### 05 — Scene Five" in prompt
    assert "### 01" not in prompt


def test_render_batched_user_prompt_multiple_entries_each_appear():
    entries = [_entry(1, "Alpha", "- a"), _entry(2, "Beta", "- b")]
    prompt = render_batched_user_prompt(entries, _BATCHED_USER_TEMPLATE)
    assert "### 01 — Alpha" in prompt
    assert "### 02 — Beta" in prompt
    assert prompt.index("Alpha") < prompt.index("Beta")


def test_render_batched_user_prompt_fills_the_template_placeholder():
    """The rendered prompt is the loaded template with {scene_blocks} filled
    in — the surrounding template text (from
    config/agents/scene_extract_batched_user.md) must still be present."""
    prompt = render_batched_user_prompt([_entry(1, "Scene One")], _BATCHED_USER_TEMPLATE)
    assert "Scenes to extract" in prompt
    assert "{scene_blocks}" not in prompt


# ── split_batched_response: the four section outcomes (§4) ────────────────────

def test_split_complete_section_has_stripped_body():
    entries = [_entry(1, "Scene One")]
    text = _wrap(1, "Scene One", "  **[GM]** — *context*\n> \"a line\"  ")
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert len(result["sections"]) == 1
    section = result["sections"][0]
    assert section["status"] == "complete"
    assert section["body"] == "**[GM]** — *context*\n> \"a line\""


def test_split_empty_section_closed_pair_blank_body():
    entries = [_entry(1, "Scene One")]
    text = _wrap(1, "Scene One", "   \n  ")  # whitespace-only body
    result = split_batched_response(text, entries)
    section = result["sections"][0]
    assert section["status"] == "empty"
    assert section["body"] is None


def test_split_incomplete_section_begin_with_no_end():
    entries = [_entry(1, "Scene One")]
    text = "<<<CG-SCENE 01 BEGIN: Scene One>>>\nsome partial content, cut off"
    result = split_batched_response(text, entries)
    section = result["sections"][0]
    assert section["status"] == "incomplete"
    assert section["body"] is None


def test_split_absent_section_no_begin_at_all():
    entries = [_entry(1, "Scene One"), _entry(2, "Scene Two")]
    text = _wrap(1, "Scene One", "content")  # scene 2 never opened
    result = split_batched_response(text, entries)
    by_i = {s["i"]: s for s in result["sections"]}
    assert by_i[1]["status"] == "complete"
    assert by_i[2]["status"] == "absent"
    assert by_i[2]["body"] is None


# ── T012: empty vs incomplete must stay distinguishable ────────────────────────

def test_empty_and_incomplete_are_not_the_same_outcome():
    """T012 / spec Edge Cases: `empty` (a closed pair with a blank body) is a
    FINISHED result — the transcript genuinely held nothing for that scene,
    and silence is the correct extraction. `incomplete` (an unmatched BEGIN)
    is UNFINISHED work. Conflating them is a real defect: writing an `empty`
    scene to disk would make the next run's skip-if-exists treat unfinished
    work as done, silently dropping a scene that was never actually
    extracted. This test asserts the two outcomes use different status
    strings and are never conflated by `split_batched_response`."""
    entries = [_entry(1, "Empty Scene"), _entry(2, "Truncated Scene")]
    text = (
        _wrap(1, "Empty Scene", "")  # closed, nothing to extract: FINISHED
        + "\n"
        + "<<<CG-SCENE 02 BEGIN: Truncated Scene>>>\nresponse cut off here"
        # scene 2: no END anywhere — UNFINISHED
    )
    result = split_batched_response(text, entries)
    by_i = {s["i"]: s for s in result["sections"]}

    assert by_i[1]["status"] == "empty"
    assert by_i[2]["status"] == "incomplete"
    assert by_i[1]["status"] != by_i[2]["status"]

    # Only "complete" carries a body to write; neither of these does, but a
    # caller distinguishing "nothing to write, done" from "nothing to write,
    # NOT done" must be able to do so from `status` alone.
    written = [s for s in result["sections"] if s["status"] == "complete"]
    assert written == []


# ── split_batched_response: reconciliation failures (§3) ───────────────────────

def test_unknown_index_fails_whole_group():
    entries = [_entry(1, "Scene One")]
    text = _wrap(1, "Scene One", "content") + "\n" + _wrap(9, "Ghost Scene", "boo")
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_UNKNOWN_INDEX
    assert result["sections"] == []


def test_duplicate_index_fails_whole_group():
    entries = [_entry(1, "Scene One")]
    text = _wrap(1, "Scene One", "first open") + "\n" + _wrap(1, "Scene One", "second open")
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_DUPLICATE_INDEX
    assert result["sections"] == []


def test_name_mismatch_fails_whole_group():
    entries = [_entry(1, "Scene One")]
    text = _wrap(1, "A Completely Different Name", "content")
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_NAME_MISMATCH
    assert result["sections"] == []


def test_name_mismatch_never_case_folds_or_fuzzy_matches():
    """DM-13: name comparison normalises ONLY leading/trailing/internal
    whitespace. A case difference or punctuation difference is a hard
    mismatch — never tolerated, never a re-assignment via similarity."""
    entries = [_entry(1, "The Margaster Hypothesis")]
    text = _wrap(1, "the margaster hypothesis", "content")  # case differs only
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_NAME_MISMATCH


def test_name_mismatch_whitespace_only_difference_is_tolerated():
    """DM-13's normalisation DOES cover whitespace: leading/trailing spaces
    and collapsed internal runs must NOT trigger a mismatch."""
    entries = [_entry(1, "The   Margaster Hypothesis")]  # double internal space
    text = _wrap(1, "  The Margaster Hypothesis  ", "content")  # single space + padding
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert result["sections"][0]["status"] == "complete"


def test_nested_section_fails_whole_group():
    """A BEGIN for scene 02 appears before scene 01's END — the two
    sections overlap instead of nesting cleanly, which would otherwise let
    01's "text between the markers" swallow 02's entire block."""
    entries = [_entry(1, "Scene One"), _entry(2, "Scene Two")]
    text = (
        "<<<CG-SCENE 01 BEGIN: Scene One>>>\n"
        "content one\n"
        "<<<CG-SCENE 02 BEGIN: Scene Two>>>\n"
        "content two\n"
        "<<<CG-SCENE 02 END>>>\n"
        "<<<CG-SCENE 01 END>>>"
    )
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_NESTED_SECTION
    assert result["sections"] == []


def test_no_sections_fails_when_scenes_were_requested():
    entries = [_entry(1, "Scene One")]
    text = "Sorry, I cannot help with that request."
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_NO_SECTIONS
    assert result["sections"] == []


def test_no_sections_does_not_fail_when_nothing_was_requested():
    result = split_batched_response("anything at all", [])
    assert result["failed"] is False
    assert result["sections"] == []


# ── Adversarial cases ────────────────────────────────────────────────────────

def test_scene_name_containing_the_sentinel_prefix_cannot_forge_a_marker():
    """A scene name containing the literal text '<<<CG-SCENE' must not be
    able to forge or split a marker: the embedded text sits mid-line, and
    only a line that STARTS with the sentinel is ever read as one."""
    tricky_name = "The <<<CG-SCENE Trap"
    entries = [_entry(3, tricky_name)]
    text = _wrap(3, tricky_name, "the trap is sprung")
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    section = result["sections"][0]
    assert section["status"] == "complete"
    assert section["body"] == "the trap is sprung"


def test_two_indices_with_identical_scene_names_attribute_correctly():
    """Duplicate scene NAMES (as opposed to duplicate indices) are harmless
    — this is exactly why attribution is by index, not by name."""
    entries = [_entry(1, "The Meeting"), _entry(2, "The Meeting")]
    text = (
        _wrap(1, "The Meeting", "first meeting's content")
        + "\n"
        + _wrap(2, "The Meeting", "second meeting's content")
    )
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    by_i = {s["i"]: s for s in result["sections"]}
    assert by_i[1]["status"] == "complete"
    assert by_i[1]["body"] == "first meeting's content"
    assert by_i[2]["status"] == "complete"
    assert by_i[2]["body"] == "second meeting's content"


def test_continuation_seam_mid_body_is_invisible_to_the_split():
    """`_claude_code_generate` concatenates auto-continued turns. A seam
    landing in the middle of a scene's body — an arbitrary string join, not
    on any marker line — must have zero effect on parsing."""
    entries = [_entry(1, "Scene One")]
    full_body = "**[GM]** — *context*\n> \"this is a long verbatim quote that keeps going\""
    whole_text = _wrap(1, "Scene One", full_body)

    # Simulate the continuation harness: split the whole response at an
    # arbitrary offset that lands inside the body, then concatenate the two
    # halves back together exactly as `_claude_code_generate` would.
    seam = whole_text.index("long verbatim") + 5
    part1, part2 = whole_text[:seam], whole_text[seam:]
    reassembled = part1 + part2
    assert reassembled == whole_text  # sanity: the seam changed nothing

    baseline = split_batched_response(whole_text, entries)
    seamed = split_batched_response(reassembled, entries)
    assert seamed == baseline
    assert seamed["sections"][0]["status"] == "complete"
    assert seamed["sections"][0]["body"] == full_body


def test_continuation_seam_inside_end_marker_degrades_to_incomplete():
    """A continuation seam landing INSIDE a sentinel line corrupts that
    line so it no longer matches the marker pattern — the section must
    degrade to `incomplete`, never mis-split or mis-attribute its content
    to a neighbouring scene."""
    entries = [_entry(1, "Scene One"), _entry(2, "Scene Two")]
    # Scene 2's END marker is corrupted mid-line, as if a continuation seam
    # dropped/garbled a character right inside the sentinel (e.g. the
    # digit run "02" became "0X2").
    text = (
        "<<<CG-SCENE 01 BEGIN: Scene One>>>\n"
        "content one\n"
        "<<<CG-SCENE 01 END>>>\n"
        "<<<CG-SCENE 02 BEGIN: Scene Two>>>\n"
        "content two\n"
        "<<<CG-SCENE 0X2 END>>>"
    )
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    by_i = {s["i"]: s for s in result["sections"]}

    # Scene one is completely unaffected by scene two's corrupted marker.
    assert by_i[1]["status"] == "complete"
    assert by_i[1]["body"] == "content one"

    # Scene two degrades safely to incomplete — its content is never
    # mis-attributed to scene one or silently treated as complete.
    assert by_i[2]["status"] == "incomplete"
    assert by_i[2]["body"] is None


def test_preamble_and_trailing_commentary_are_discarded():
    """Text outside any BEGIN/END pair — a preamble before the first BEGIN,
    commentary after the last END — is discarded, never appended to an
    adjacent scene."""
    entries = [_entry(1, "Scene One")]
    text = (
        "Sure, here is the extraction you asked for:\n\n"
        + _wrap(1, "Scene One", "the actual content")
        + "\n\nI hope that helps! Let me know if you need anything else."
    )
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    section = result["sections"][0]
    assert section["status"] == "complete"
    assert section["body"] == "the actual content"
    assert "Sure, here is" not in section["body"]
    assert "I hope that helps" not in section["body"]


def test_multi_scene_response_all_complete_in_request_order():
    entries = [_entry(1, "Alpha"), _entry(2, "Beta"), _entry(3, "Gamma")]
    text = "\n".join([
        _wrap(1, "Alpha", "alpha content"),
        _wrap(2, "Beta", "beta content"),
        _wrap(3, "Gamma", "gamma content"),
    ])
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert [s["i"] for s in result["sections"]] == [1, 2, 3]
    assert [s["status"] for s in result["sections"]] == ["complete"] * 3
    assert [s["body"] for s in result["sections"]] == [
        "alpha content", "beta content", "gamma content",
    ]


def test_sections_reported_in_request_order_even_if_response_order_differs():
    """DM-13: attribution is by index, so a caller shouldn't have to care
    what order the model happened to close its sections in."""
    entries = [_entry(1, "Alpha"), _entry(2, "Beta")]
    # Model answers scene 2 before scene 1.
    text = _wrap(2, "Beta", "beta content") + "\n" + _wrap(1, "Alpha", "alpha content")
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert [s["i"] for s in result["sections"]] == [1, 2]
    by_i = {s["i"]: s for s in result["sections"]}
    assert by_i[1]["body"] == "alpha content"
    assert by_i[2]["body"] == "beta content"


def test_split_batched_response_reachable_via_campaignlib_scenes():
    """Sanity: the new functions live in campaignlib.scenes, matching the
    module's existing convention (group_scenes, project_scene_output, …)."""
    assert campaignlib.scenes.split_batched_response is split_batched_response
    assert campaignlib.scenes.render_batched_user_prompt is render_batched_user_prompt


# ── T041: the SC-005 partial shape at the wire-protocol level ─────────────────

def test_split_batched_response_five_complete_one_incomplete_two_absent_sc005():
    """SC-005's exact shape: a response covering only the first 6 of 8
    requested scenes, one of which (06) is cut off mid-body with no closing
    marker, and two (07, 08) never opened at all. This is the mixed batch
    `split_batched_response` has to classify correctly for
    `run_batched_scene_extraction`'s partial-response path (T035-T039) to
    have anything trustworthy to act on."""
    entries = [_entry(i, f"Scene {i}") for i in range(1, 9)]
    parts = [_wrap(i, f"Scene {i}", f"moments {i}") for i in range(1, 6)]
    parts.append("<<<CG-SCENE 06 BEGIN: Scene 6>>>\ncut off here, no closing marker")
    # Scenes 07 and 08: no BEGIN at all.
    text = "\n".join(parts)

    result = split_batched_response(text, entries)
    assert result["failed"] is False
    by_i = {s["i"]: s for s in result["sections"]}

    for i in range(1, 6):
        assert by_i[i]["status"] == "complete"
        assert by_i[i]["body"] == f"moments {i}"
    assert by_i[6]["status"] == "incomplete"
    assert by_i[6]["body"] is None
    assert by_i[7]["status"] == "absent"
    assert by_i[7]["body"] is None
    assert by_i[8]["status"] == "absent"
    assert by_i[8]["body"] is None

    complete = [s for s in result["sections"] if s["status"] == "complete"]
    unfinished = [s for s in result["sections"] if s["status"] in ("incomplete", "absent")]
    assert len(complete) == 5
    assert len(unfinished) == 3
    assert {s["i"] for s in unfinished} == {6, 7, 8}


# ── Marker lines survive a line ending and trailing blanks ──────────────────
#
# The `claude -p` subprocess path can hand back CRLF, and a model can leave a
# trailing space on a sentinel line. With `$` sitting hard against `>>>`,
# neither marker matched at all: no BEGIN anywhere means NO_SECTIONS, which
# fails the WHOLE group and discards a response the GM already paid for.

def test_crlf_markers_are_still_read():
    entries = [_entry(3, "The Margaster Hypothesis")]
    text = ("<<<CG-SCENE 03 BEGIN: The Margaster Hypothesis>>>\r\n"
            "moments 3\r\n"
            "<<<CG-SCENE 03 END>>>\r\n")
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert result["sections"][0]["status"] == "complete"
    assert result["sections"][0]["body"] == "moments 3"


def test_trailing_blanks_on_marker_lines_are_tolerated():
    entries = [_entry(1, "Scene 1")]
    text = ("<<<CG-SCENE 01 BEGIN: Scene 1>>>   \n"
            "moments 1\n"
            "<<<CG-SCENE 01 END>>>\t\n")
    result = split_batched_response(text, entries)
    assert result["failed"] is False
    assert result["sections"][0]["status"] == "complete"
    assert result["sections"][0]["body"] == "moments 1"


def test_crlf_does_not_leak_a_carriage_return_into_the_body():
    """The body is written to disk, so a stray \\r would land in the file."""
    entries = [_entry(2, "Scene 2")]
    text = ("<<<CG-SCENE 02 BEGIN: Scene 2>>>\r\n"
            "moments 2\r\n"
            "<<<CG-SCENE 02 END>>>\r\n")
    body = split_batched_response(text, entries)["sections"][0]["body"]
    assert body == "moments 2"


def test_tolerating_blanks_does_not_let_a_mid_line_marker_be_forged():
    """Column-0 anchoring is what stops a scene name forging a marker (D5);
    allowing trailing whitespace must not weaken the OPENING anchor."""
    entries = [_entry(3, "The Margaster Hypothesis")]
    text = ("prose <<<CG-SCENE 03 BEGIN: The Margaster Hypothesis>>>\n"
            "moments\n")
    result = split_batched_response(text, entries)
    assert result["failed"] is True
    assert result["failure_reason"] == BATCHED_NO_SECTIONS


def test_text_after_the_closing_marker_is_still_not_body():
    entries = [_entry(4, "Scene 4")]
    text = ("<<<CG-SCENE 04 BEGIN: Scene 4>>>\r\n"
            "moments 4\r\n"
            "<<<CG-SCENE 04 END>>>  \r\n"
            "trailing commentary the model added\r\n")
    section = split_batched_response(text, entries)["sections"][0]
    assert section["body"] == "moments 4"
