"""The speaker-label grammar — issue #453.

Every row of `specs/027-bracketed-speaker-labels/contracts/label-grammar.md`,
plus the guard the whole feature turns on.

Scene extractions do not agree on how a speaker label is written. Four
conventions appear across four sessions — `**GM**`, `**[GM]**`,
`**[GM, as the banker]**`, `**[GM / Brewbarry]**` — and the same bold-bracket
shape is also used for scene apparatus (`**[Reroll With Advantage]**`). The old
rule discarded every bracketed label, which cost one session 39 labelled turns
for a single character and emptied the narrator pool that `sd_plan` refuses to
run without.

A label's shape decides exactly one thing — whether the text is tokenised, so a
bare-convention session is structurally untouched. It decides no **identity**:
a piece names somebody iff it folds exactly onto a roster name or the
game-master label, and whether a piece is a second speaker or a qualifier is
settled by whether it resolves, not by the punctuation before it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaignlib.players_config import GM_LABEL, norm_name  # noqa: E402
from session_doc.plan_eligibility import (  # noqa: E402
    label_parts,
    read_label,
    scene_presence,
)

ROSTER = ["Brewbarry", "Soma", "Valphine Sotorra", "Vukradin"]
CANON = {norm_name(n): n for n in ROSTER}


def present(label: str) -> set[str]:
    """Which roster characters one label places in a scene."""
    return set(read_label(label, CANON).characters)


def moments(*labels: str) -> str:
    """A minimal moments body: one labelled turn per label given."""
    return "".join(f'**{lab}** — *note*\n> "line"\n\n' for lab in labels)


# ── Tokenisation is textual; identity is not ────────────────────────────────

def test_a_bare_label_is_never_tokenised():
    """The reason a bare-convention session is structurally unaffected."""
    assert label_parts("Valphine Sotorra") == ["Valphine Sotorra"]
    assert label_parts("Vukradin (David)") == ["Vukradin (David)"]


def test_a_bracketed_label_splits_on_the_separators_the_corpus_uses():
    assert label_parts("[GM / Brewbarry]") == ["GM", "Brewbarry"]
    assert label_parts("[GM, as the banker]") == ["GM", "as the banker"]
    assert label_parts("[GM / Brewbarry / Valphine]") == ["GM", "Brewbarry", "Valphine"]


def test_whitespace_inside_brackets_is_insignificant():
    assert read_label("[ GM ]", CANON).names_gm
    assert present("[  Vukradin  ]") == {"Vukradin"}


def test_an_empty_bracket_contributes_nothing_and_is_not_a_name():
    reading = read_label("[]", CANON)
    assert reading.characters == frozenset()
    assert not reading.names_gm
    assert label_parts("[]") == []


# ── US1: a bracketed name is a speaker ──────────────────────────────────────

def test_a_bracketed_character_is_present():
    assert present("[Vukradin]") == {"Vukradin"}
    assert present("[Soma]") == {"Soma"}


def test_a_bare_character_is_still_present():
    assert present("Brewbarry") == {"Brewbarry"}


def test_an_indented_label_is_not_a_label():
    """The anchor is load-bearing: a smoothed extraction could otherwise report
    turns for a character the eligibility set had excluded."""
    counts, _ = scene_presence('  **Vukradin** — *indented*\n> "hi"\n', CANON)
    assert counts == {}


def test_an_unknown_bracketed_name_places_nobody():
    assert present("[Ser Kaelen]") == set()


# ── THE guard: resolution is equality, never containment ────────────────────

def test_a_beat_marker_containing_a_roster_name_places_nobody():
    """THE test. `[scene tag — Vukradin demands a meeting]` is real, and it
    contains a roster name.

    Under containment it would place Vukradin in a scene on the strength of
    scene apparatus — a fabricated attribution, the most expensive failure this
    system produces. If this fails, the bug is worse than the one #453 fixed,
    however green the rest is.
    """
    assert "Vukradin" in "[scene tag — Vukradin demands a meeting]"
    assert present("[scene tag — Vukradin demands a meeting]") == set()
    assert present("[scene tag — Soma's Arcana check]") == set()


def test_a_short_form_name_does_not_resolve_to_a_longer_roster_name():
    """`[Valphine]` against roster `Valphine Sotorra`. Out of scope by ruling:
    folding is case and whitespace, never approximate matching. Reported, not
    resolved. Do not "fix" this without widening the spec."""
    assert present("[Valphine]") == set()
    assert present("[Valphine Sotorra]") == {"Valphine Sotorra"}


# ── US2: the game master, in every form ─────────────────────────────────────

def test_every_gm_form_is_recognised_as_the_game_master():
    for form in ("GM", "[GM]", "[ GM ]", "[GM, as the banker]"):
        reading = read_label(form, CANON)
        assert reading.names_gm, form
        assert reading.characters == frozenset(), form


def test_the_bare_and_bracketed_gm_are_treated_identically():
    bare, bracketed = read_label("GM", CANON), read_label("[GM]", CANON)
    assert (bare.names_gm, bare.characters) == (bracketed.names_gm, bracketed.characters)


def test_a_gm_voicing_an_npc_places_no_character():
    """Ten of sixteen GM turns in one scene are `**[GM, as the banker]**`. The
    qualifier resolves to nobody and is inert; no wording of it is special-cased."""
    counts, _ = scene_presence(moments("[GM, as the banker]") * 3, CANON)
    assert counts == {}


def test_the_gm_is_never_a_narrator_candidate():
    counts, _ = scene_presence(moments("GM", "[GM]", "[GM, as the innkeeper]"), CANON)
    assert GM_LABEL not in counts
    assert counts == {}


# ── US3: joint labels, per the GM's ruling of 2026-09-08 ────────────────────

def test_a_joint_label_with_the_gm_credits_the_character():
    assert present("[GM / Brewbarry]") == {"Brewbarry"}
    assert present("[Brewbarry / GM]") == {"Brewbarry"}
    assert present("[Vukradin / GM]") == {"Vukradin"}


def test_a_joint_label_of_two_characters_credits_both():
    """Option A, ruled by the GM over the conservative alternative. The
    permissive reading: a turn only one of them spoke makes both eligible."""
    assert present("[Brewbarry / Soma]") == {"Brewbarry", "Soma"}
    assert present("[Vukradin / Brewbarry]") == {"Vukradin", "Brewbarry"}


def test_a_three_party_joint_label_credits_every_character_named():
    assert present("[GM / Brewbarry / Valphine Sotorra]") == {"Brewbarry", "Valphine Sotorra"}


def test_a_character_named_twice_in_one_label_contributes_one_turn():
    counts, _ = scene_presence(moments("[Brewbarry / Brewbarry]"), CANON)
    assert counts == {"Brewbarry": 1}


def test_a_gm_part_suppresses_nothing():
    counts, _ = scene_presence(moments("[GM / Brewbarry]"), CANON)
    assert counts == {"Brewbarry": 1}


# ── US4: apparatus stays apparatus ──────────────────────────────────────────

def test_beat_markers_place_nobody():
    for marker in ("[Reroll With Advantage]", "[The Lead Established]",
                   "[scene tag — The roll]", "[Awareness Rolls]",
                   "[First Persuasion Fails]", "[The Silk Cosplayer]"):
        assert present(marker) == set(), marker


def test_a_beat_marker_beside_a_real_speaker_resolves_the_speaker():
    counts, _ = scene_presence(moments("[The Lead Established]", "[Vukradin]"), CANON)
    assert counts == {"Vukradin": 1}


def test_a_bracketed_unresolved_label_is_apparatus_and_a_bare_one_is_not():
    """The split that keeps the #385 notice readable. Both are inert for
    presence; only the report bucket differs."""
    assert read_label("[scene tag — The roll]", CANON).is_apparatus
    assert not read_label("Vukradin (David)", CANON).is_apparatus


def test_an_unresolved_label_is_surfaced_not_dropped():
    _, unresolved = scene_presence(
        moments("[The Lead Established]", "Vukradin (David)", "[Vukradin]"), CANON)
    assert {r.label for r in unresolved} == {"[The Lead Established]", "Vukradin (David)"}


def test_the_game_master_is_not_reported_as_unresolved():
    """Recognised, so it never reaches the GM's review queue as an unknown name."""
    _, unresolved = scene_presence(moments("GM", "[GM]", "[GM, as the banker]"), CANON)
    assert unresolved == []


# ── Partial resolution: the case that used to vanish ────────────────────────

def test_an_unresolved_slot_is_reported_even_when_the_label_resolved_somebody():
    """`[GM / Brewbarry / Valphine]` against a roster spelling her
    `Valphine Sotorra`. Brewbarry resolves, the GM resolves, and `Valphine`
    named nobody — so the label credited Brewbarry and dropped her with no
    trace at all: not counted, not reported, absent from
    `plan.eligibility.json`. A partially-resolved label is where a roster
    character goes missing standing next to a name that worked."""
    reading = read_label("[GM / Brewbarry / Valphine]", CANON)
    assert reading.characters == {"Brewbarry"}
    assert reading.names_gm
    assert reading.unresolved == {"Valphine"}

    counts, unresolved = scene_presence(
        moments("[GM / Brewbarry / Valphine]"), CANON)
    assert counts == {"Brewbarry": 1}
    assert [r.label for r in unresolved] == ["[GM / Brewbarry / Valphine]"]


def test_a_qualifier_is_not_an_unresolved_speaker():
    """`as the banker` describes the GM's turn; it does not fail to name one.
    A piece after the first in its slot that resolves to nobody is a
    qualifier, so a fully-understood label is not reported as a mystery."""
    reading = read_label("[GM, as the banker]", CANON)
    assert reading.names_gm
    assert reading.unresolved == frozenset()


def test_a_comma_can_still_join_two_speakers():
    """Resolution decides, not punctuation. `[Vukradin, Brewbarry]` reads as
    two speakers because both pieces resolve — treating every comma tail as a
    qualifier would silently lose the second, the same defect one level down."""
    assert present("[Vukradin, Brewbarry]") == {"Vukradin", "Brewbarry"}


def test_a_beat_marker_is_still_inert_when_it_contains_a_roster_name():
    """The guard, restated at the slot level: reporting unresolved *pieces*
    must not become containment by another route."""
    reading = read_label("[scene tag — Vukradin demands a meeting]", CANON)
    assert reading.characters == frozenset()
    assert reading.is_apparatus
    assert reading.unresolved == {"scene tag — Vukradin demands a meeting"}


# ── #460: a shortened name is surfaced, never resolved ──────────────────────

def test_a_short_form_is_still_not_resolved():
    """The rule below changes what is *printed*, never who anybody is.
    `[Valphine]` places nobody, exactly as before."""
    assert present("[Valphine]") == set()


def test_a_short_form_piece_is_recorded_as_unresolved():
    """What the report needs: the piece with its brackets already removed, so
    a substring test against the roster is possible without one."""
    assert read_label("[Valphine]", CANON).unresolved == {"Valphine"}
    assert read_label("Valphine", CANON).unresolved == {"Valphine"}


def test_a_beat_marker_is_longer_than_any_name_it_mentions():
    """Why the containment direction is safe. The roster name sits inside the
    beat marker, never the other way round — so a rule testing *piece inside
    name* can never promote apparatus, however many roster names it mentions."""
    piece = next(iter(read_label(
        "[scene tag — Vukradin demands a meeting]", CANON).unresolved))
    assert "vukradin" in norm_name(piece)
    assert not any(norm_name(piece) in norm_name(n) for n in ROSTER)
