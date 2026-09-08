"""The two deterministic filters behind issue #385.

`sd_plan` assigned Brewbarry as the first-person narrator of a scene he speaks
zero lines in, three runs running, because his player was not at the table and
the prompt was told to give every roster character a scene. These are the
filters that make that impossible. Every one of them is a pure function over
strings: no API key, no network, no model call.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.players_config import (  # noqa: E402
    absent_characters,
    attending_players,
    load_players_config,
)
from campaignlib.players_config import norm_name  # noqa: E402
from campaignlib.vtt import speaker_labels  # noqa: E402
from session_doc.io import (  # noqa: E402
    load_scene_extractions,
    scene_speaker_labels,
)
from session_doc.plan_eligibility import (  # noqa: E402
    Eligibility,
    compute_eligibility,
    scene_presence,
)

#: The fixture roster. Presence is decided against it rather than against the
#: shape of a label (#453), so these tests need one where they used not to.
FIXTURE_ROSTER = ["Vukradin", "Soma", "Valphine Sotorra", "Brewbarry"]


def scene_speakers(moments: str, roster: list[str] | None = None) -> set[str]:
    """Filter B's answer for one scene: who has a labelled turn in it.

    A test-local wrapper. The rule moved from ``session_doc.io`` — which could
    not see a roster and therefore guessed from the label's shape — into
    ``plan_eligibility.scene_presence``, which resolves against one. The
    assertions below are unchanged; only where they are aimed has moved.
    """
    canonical = {norm_name(n): n for n in (roster or FIXTURE_ROSTER)}
    counts, _ = scene_presence(moments, canonical)
    return set(counts)
from tests.helpers.eligibility_session import (  # noqa: E402
    MOMENTS_03,
    MOMENTS_05,
    MOMENTS_UNCOVERABLE,
    ROSTER,
    SCENE_05,
    VTT,
    VTT_GM_ONLY,
    write_session,
)


# ── T003: speaker_labels ────────────────────────────────────────────────────

def test_speaker_labels_reads_the_name_prefix():
    assert speaker_labels(VTT) == {
        "Kostadis Roussos",
        "David Mendenhall",
        "Wade Brown",
        "Gary Young",
    }


def test_speaker_labels_ignores_a_colon_inside_dialogue():
    text = 'WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nWade Brown: I say: no.\n'
    assert speaker_labels(text) == {"Wade Brown"}


def test_speaker_labels_ignores_timing_lines():
    """A cue timing contains colons but is not a speaker."""
    assert not any(lbl.startswith("00") for lbl in speaker_labels(VTT))


def test_speaker_labels_matches_the_normalise_shape():
    """A label only counts at the start of a line, as a literal prefix.

    This is the same shape ``normalize_vtt_speakers`` rewrites. If the two
    disagree, "the check says present" and "the rewrite will find it" mean
    different things — the defect ``_read_vtt_speakers`` was written to avoid.
    """
    text = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nand then Wade Brown: hi\n"
    assert "Wade Brown" not in speaker_labels(text)


# ── T004: scene_speakers ────────────────────────────────────────────────────

def test_scene_speakers_reads_labels():
    assert scene_speakers(MOMENTS_05) == {"Vukradin", "Soma", "Valphine Sotorra"}


def test_scene_speakers_does_not_count_a_prose_mention():
    """THE test. Brewbarry is named three times in scene 5 and labelled zero.

    A substring search marks him present in exactly the scene this feature
    exists to fix. If this fails, the bug is back however green the rest is.
    """
    assert "Brewbarry" in MOMENTS_05                    # he is named in the text
    assert "Brewbarry" not in scene_speakers(MOMENTS_05)  # he never speaks


def test_scene_speakers_drops_the_gm():
    assert "GM" not in scene_speakers(MOMENTS_05)


def test_reading_the_whole_scene_file_would_leak_the_summary():
    """Why the reader takes moments and not the document.

    A gm-assist summary carries its own **bold** headers. Handed the whole
    file, the label scan returns one of them as a label — so this asserts the
    wrong reading really is wrong, rather than trusting the docstring.

    Asserted at the *reader*, not at presence. Since #453 the roster is what
    decides who a label names, and this particular header resolves to nobody,
    so presence no longer shows the leak. The leak is still real: a bold
    summary header that happened to equal a character's name would reach the
    resolver. Testing the reader keeps the guarantee where it still holds.
    """
    leaked = set(scene_speaker_labels(SCENE_05)) - set(scene_speaker_labels(MOMENTS_05))
    assert leaked == {"Brewbarry enters the House of a Thousand Faces"}


def test_scene_speakers_skips_bracketed_action_beats():
    """``**[The Long Road North]**`` is a scene tag, not a person.

    Unchanged in meaning, and it now holds for the right reason: the tag is
    read like any other label and resolves to nobody, rather than being
    discarded for beginning with ``[``. That discard is what cost
    ``**[Vukradin]**`` its 39 turns (#453).
    """
    assert scene_speakers(MOMENTS_UNCOVERABLE) == set()


def test_scene_speakers_excludes_a_character_absent_from_this_scene():
    """Valphine is at the session but says nothing in scene 3."""
    assert scene_speakers(MOMENTS_03) == {"Vukradin", "Soma"}


def test_scene_speakers_keeps_a_character_with_only_two_lines():
    """Eligibility is presence, not volume (FR-009)."""
    assert "Soma" in scene_speakers(MOMENTS_03)


# ── T005: attendance ────────────────────────────────────────────────────────

def _players(tmp_path):
    _sx, _vtt, players = write_session(tmp_path)
    return load_players_config(players)


def test_attending_players_is_exact_on_display_names(tmp_path):
    cfg = _players(tmp_path)
    assert attending_players(cfg, speaker_labels(VTT)) == {
        "kostadis", "david", "wade", "gary",
    }


def test_absent_player_yields_an_absent_character(tmp_path):
    cfg = _players(tmp_path)
    assert absent_characters(cfg, ROSTER, speaker_labels(VTT)) == {"Brewbarry"}


def test_a_character_nobody_plays_is_undetermined_not_absent(tmp_path):
    """Reversed after review. An unbound character is a gap in players.yaml,
    which `players check` already reports — not evidence that nobody played
    them. Absence is a claim about evidence, so it needs evidence."""
    from campaignlib.players_config import undetermined_characters

    cfg = _players(tmp_path)
    roster = ROSTER + ["Boney"]
    assert "Boney" not in absent_characters(cfg, roster, speaker_labels(VTT))
    assert "Boney" in undetermined_characters(cfg, roster)


def test_an_inactive_player_is_not_counted_as_attending(tmp_path):
    """`active: false` already drops out of the prompt roster; an archived
    label must not quietly put them back at the table."""
    _sx, _vtt, players = write_session(tmp_path)
    players.write_text(
        players.read_text(encoding="utf-8").replace(
            "  plays:\n  - Soma", "  active: false\n  plays:\n  - Soma"
        ),
        encoding="utf-8",
    )
    cfg = load_players_config(players)
    assert "wade" not in attending_players(cfg, speaker_labels(VTT))


def test_gm_only_tape_leaves_nobody_attending(tmp_path):
    cfg = _players(tmp_path)
    assert absent_characters(cfg, ROSTER, speaker_labels(VTT_GM_ONLY)) == set(ROSTER)


def test_an_inactive_players_character_is_undetermined_not_absent(tmp_path):
    """`active: false` means the person left the campaign, so the tape has
    nothing to say about them — and Filter A must not claim it does."""
    from campaignlib.players_config import undetermined_characters

    _sx, _vtt, players = write_session(tmp_path)
    players.write_text(
        players.read_text(encoding="utf-8").replace(
            "  plays:\n  - Soma", "  active: false\n  plays:\n  - Soma"
        ),
        encoding="utf-8",
    )
    cfg = load_players_config(players)
    assert "Soma" in undetermined_characters(cfg, ROSTER)


# ── T006: the composed result ───────────────────────────────────────────────

def _eligibility(tmp_path, **kw) -> Eligibility:
    scene_dir, vtt, players = write_session(tmp_path, **kw)
    return compute_eligibility(
        scenes=load_scene_extractions(scene_dir),
        roster=ROSTER,
        players=load_players_config(players),
        vtt_text=vtt.read_text(encoding="utf-8"),
    )


def test_pool_excludes_the_absent_players_character(tmp_path):
    e = _eligibility(tmp_path)
    assert e.pool == {"Vukradin", "Valphine Sotorra", "Soma"}
    assert "Brewbarry" not in e.pool


def test_candidates_per_scene(tmp_path):
    e = _eligibility(tmp_path)
    by_scene = {s.name: s.candidates for s in e.scenes}
    three = {"Vukradin", "Valphine Sotorra", "Soma"}
    assert by_scene["Rumors and Preparations at the Common Chord"] == three
    assert by_scene["The Sewer Stakeout"] == three
    assert by_scene["Encounter in the Sewers"] == {"Vukradin", "Soma"}
    assert by_scene["The Stakeout of Denvar"] == three
    assert by_scene["The Dead Drop at the House of a Thousand Faces"] == three


def test_brewbarry_is_a_candidate_for_no_scene(tmp_path):
    e = _eligibility(tmp_path)
    assert all("Brewbarry" not in s.candidates for s in e.scenes)


def test_uncoverable_scene_is_reported(tmp_path):
    e = _eligibility(tmp_path, uncoverable=True)
    assert e.uncoverable == ["Three Days on the Road"]


def test_no_uncoverable_scene_in_the_ordinary_session(tmp_path):
    assert _eligibility(tmp_path).uncoverable == []


def test_exclusions_carry_their_cause(tmp_path):
    e = _eligibility(tmp_path)
    assert any(
        x.character == "Brewbarry" and x.player == "Stéphane Bourdeaud"
        for x in e.absent_exclusions
    )
    assert any(
        x.character == "Valphine Sotorra" and x.scene == "Encounter in the Sewers"
        for x in e.scene_exclusions
    )


def test_empty_pool_is_visible_not_silent(tmp_path):
    e = _eligibility(tmp_path, gm_only_vtt=True)
    assert e.pool == set()
    assert e.scenes and all(s.candidates == set() for s in e.scenes)
