"""Filter B over the frozen four-session corpus — issue #453.

`tests/test_speaker_label_grammar.py` proves the rule on constructed labels.
This proves it on the real thing: four sessions, four narrators, two label
conventions, committed to this repo under
`experiments/20260907-phandalin-gm-gaps-confirm/inputs/`.

Two of the four used to produce nothing at all. `vukradin_source.md` has 39
labelled turns for Vukradin and 21 for Soma; Filter B counted none of them, so
every character was ruled ineligible for every scene and `sd_plan` refused an
empty pool. Narrator selection did not degrade on those sessions — it stopped.

The baseline these assert against is `specs/027-bracketed-speaker-labels/
baseline.json`, captured before any source edit.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaignlib.players_config import PlayersConfig, norm_name  # noqa: E402
from session_doc.plan_eligibility import (  # noqa: E402
    _stranger_buckets,
    compute_eligibility,
    scene_presence,
)

CORPUS = ROOT / "experiments/20260907-phandalin-gm-gaps-confirm/inputs"
BASELINE_PATH = ROOT / "specs/027-bracketed-speaker-labels/baseline.json"

pytestmark = pytest.mark.skipif(
    not CORPUS.is_dir() or not BASELINE_PATH.is_file(),
    reason="frozen corpus or its baseline is not present",
)

BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8")) if BASELINE_PATH.is_file() else {}
ROSTER = BASELINE.get("roster", [])
CANON = {norm_name(n): n for n in ROSTER}
FILES = ["brewbarry_source.md", "soma_source.md", "valphine_source.md", "vukradin_source.md"]
BARE = ["brewbarry_source.md", "soma_source.md"]
BRACKETED = ["valphine_source.md", "vukradin_source.md"]


def eligibility_for(name: str):
    text = (CORPUS / name).read_text(encoding="utf-8")
    return text, compute_eligibility(
        scenes=[{"name": Path(name).stem, "moments": text}],
        roster=ROSTER,
        players=PlayersConfig(players=[]),
        vtt_text="",
    )


# ── SC-001 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", FILES)
def test_every_session_yields_a_narrator_pool(name):
    """Two of these four used to yield nothing, and `sd_plan` refuses an empty
    pool rather than falling back to the roster."""
    _, e = eligibility_for(name)
    assert e.scenes[0].candidates, f"{name} has no eligible narrator"


# ── SC-002 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("vukradin_source.md", {"Vukradin": 39, "Soma": 21, "Brewbarry": 13}),
    ("valphine_source.md", {"Brewbarry": 18, "Vukradin": 3, "Soma": 1}),
])
def test_bracketed_sessions_count_their_turns(name, expected):
    """`Valphine` is deliberately absent from both: these files write the short
    form against a roster that declares `Valphine Sotorra`. Folding is not
    approximate matching, so it stays unresolved and is reported — out of scope
    by ruling, documented in the spec's Assumptions."""
    text, _ = eligibility_for(name)
    counts, _ = scene_presence(text, CANON)
    assert counts == expected


# ── SC-004 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", BARE)
def test_bare_convention_sessions_are_unchanged(name):
    """Structural, not incidental: tokenisation never touches a bare label."""
    text, _ = eligibility_for(name)
    counts, _ = scene_presence(text, CANON)
    assert counts == BASELINE["scene_speaker_counts"][name]


# ── SC-005 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", FILES)
def test_no_character_is_credited_with_a_gm_turn(name):
    """`vukradin_source.md` carries 40 `**[GM]**` turns and `brewbarry_source.md`
    41 bare `**GM**` ones. Neither may place anybody."""
    text, _ = eligibility_for(name)
    counts, _ = scene_presence(text, CANON)
    assert "GM" not in counts
    assert set(counts) <= set(ROSTER)


# ── SC-007 ──────────────────────────────────────────────────────────────────

def test_the_joint_turns_credit_each_character_named():
    """Ten joint turns in `valphine_source.md`, three of them naming more than
    one roster character. Brewbarry's 18 turns are 7 solo plus 11 joint — he is
    ineligible for the scene without them."""
    text, _ = eligibility_for("valphine_source.md")
    counts, _ = scene_presence(text, CANON)
    assert counts["Brewbarry"] == 18
    assert counts["Soma"] == 1          # only from [Brewbarry / Soma]
    assert counts["Vukradin"] == 3      # [Vukradin], [Vukradin / GM], [Vukradin / Brewbarry]


# ── SC-003 and SC-008 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", FILES)
def test_the_loud_report_bucket_did_not_grow(name):
    """The channel #385 built says "each one costs that character a scene", and
    the covering-player workflow depends on the GM reading it. Reading
    bracketed labels put 22 beat markers in reach of it, two of which contain a
    roster name outright."""
    _, e = eligibility_for(name)
    suspects, _ = _stranger_buckets(e)
    loud = sum(len(v) for v in suspects.values())
    assert loud <= BASELINE["eligibility"][name]["loud_count"]


def test_the_two_scene_tags_naming_a_character_stay_quiet():
    """The concrete pair this rule exists for."""
    _, e = eligibility_for("vukradin_source.md")
    suspects, _ = _stranger_buckets(e)
    listed = {label for labels in suspects.values() for label in labels}
    assert "[scene tag — Vukradin demands a meeting]" not in listed
    assert "[scene tag — Soma's Arcana check]" not in listed


@pytest.mark.parametrize("name", FILES)
def test_nothing_is_dropped_silently(name):
    """Every label that resolved to nobody reaches one bucket or the other."""
    _, e = eligibility_for(name)
    suspects, other = _stranger_buckets(e)
    loud = sum(len(v) for v in suspects.values())
    assert loud + other == sum(len(s.strangers) for s in e.scenes)
