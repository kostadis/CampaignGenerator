"""The block model — parsing, the authored record, and composing (#455).

Contracts P, R and C from `specs/029-block-document-model/contracts/block-model.md`.

The corpus is four real narrations with markers in them, and the GM's rulings on
all 31 of their gaps, committed under
`experiments/20260907-phandalin-gm-gaps-confirm/`. Parsing is asserted against
those rather than against a fixture: a fixture is written to suit the parser,
and the failure this layer must not have is one that only appears on real text.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.blocks import (  # noqa: E402
    GAP_MARKER,
    Block,
    gap_text,
    has_open_gap,
    join_blocks,
    parse_blocks,
)

CORPUS = ROOT / "experiments/20260907-phandalin-gm-gaps-confirm"

# Committed with the feature. A missing corpus is a real breakage, not a reason
# to skip — the same call `tests/test_speaker_label_corpus.py` makes.
if not CORPUS.is_dir():
    raise AssertionError(f"the #455 corpus is missing: {CORPUS}")

#: Measured, and recorded in research D1. Pinned so a parser change that alters
#: granularity has to come here and say so.
EXPECTED = {
    "brewbarry": (13, 6),
    "soma": (25, 12),
    "valphine": (9, 4),
    "vukradin": (18, 9),
}


def narration(arm: str) -> str:
    return (CORPUS / arm / "response.md").read_text(encoding="utf-8")


# ── Contract P — parsing ────────────────────────────────────────────────────

@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_parsing_round_trips_on_a_real_narration(arm):
    """P1, and the load-bearing test of the whole feature.

    Composing writes a document from these blocks. A parser that loses a blank
    line makes every composed document differ from its narration *everywhere*,
    and the diff reads as the compose step misbehaving rather than as a parse
    bug — so this is asserted before anything is built on top of it.
    """
    text = narration(arm)
    assert join_blocks(parse_blocks(text)) == text


@pytest.mark.parametrize("arm,expected", sorted(EXPECTED.items()))
def test_block_and_gap_counts_are_what_was_measured(arm, expected):
    blocks = parse_blocks(narration(arm))
    assert (len(blocks), sum(1 for b in blocks if b.is_gap)) == expected


@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_ids_are_stable_across_two_parses(arm):
    """P3. The id is what an authored record refers to; if it moved between
    parses, a record would attach to a different block on the next run."""
    text = narration(arm)
    assert [b.id for b in parse_blocks(text)] == [b.id for b in parse_blocks(text)]


@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_ids_are_unique_and_ordinal_within_kind(arm):
    blocks = parse_blocks(narration(arm))
    ids = [b.id for b in blocks]
    assert len(set(ids)) == len(ids)
    for kind in ("prose", "gap"):
        got = [b.id for b in blocks if b.kind == kind]
        assert got == [f"{kind}-{i}" for i in range(1, len(got) + 1)]


def test_a_narration_with_no_markers_is_one_prose_block():
    """P4. A scene with no GM description in it is not an error, and marker
    count is not a quality measure."""
    text = "She turned toward the door.\n\n\"After you,\" she said.\n"
    blocks = parse_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].kind == "prose"
    assert join_blocks(blocks) == text


def test_empty_input_yields_no_blocks():
    assert parse_blocks("") == []


def test_a_paragraph_that_merely_mentions_the_marker_is_prose():
    """A gap is a paragraph that is *solely* a marker.

    Treating a paragraph that mentions one as a gap would delete the prose the
    model wrote around it at compose time. The contract emits the marker on its
    own line, so requiring it to stand alone costs nothing and refuses to guess.
    """
    text = f'She read it aloud: "{GAP_MARKER} something]" — and laughed.\n'
    blocks = parse_blocks(text)
    assert [b.kind for b in blocks] == ["prose"]


def test_consecutive_gaps_do_not_invent_an_empty_prose_block_between_them():
    """Two markers in a row is real — brewbarry's opening recap is two GM turns
    and the ported prompt gapped each. The whitespace between them belongs to
    the document, but it is not a block a human would rule on."""
    text = (
        f"{GAP_MARKER} the party leaves the Spire]\n\n"
        f"{GAP_MARKER} Cullen Sharpe still grates]\n\n"
        '"That\'s dicks," Soma says.\n'
    )
    blocks = parse_blocks(text)
    assert [b.kind for b in blocks] == ["gap", "gap", "prose"]
    assert join_blocks(blocks) == text


def test_a_gap_is_reported_as_open_by_the_gate_predicate():
    """What `assemble`'s gate asks — a property of the document, never of a
    record (research D3)."""
    assert has_open_gap(f"prose\n\n{GAP_MARKER} something]\n")
    assert not has_open_gap("prose only\n")


def test_gap_text_strips_the_marker_and_its_bracket():
    block = Block("gap-1", "gap", "", f"{GAP_MARKER} Aurelan arrives out of breath.]\n\n")
    assert gap_text(block) == "Aurelan arrives out of breath."


@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_every_gap_carries_a_readable_statement(arm):
    """A marker with nothing in it would be a gap the GM cannot rule on."""
    for block in parse_blocks(narration(arm)):
        if block.is_gap:
            assert gap_text(block).strip()


@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_anchors_are_normalised_and_bounded(arm):
    from session_doc.blocks import ANCHOR_CHARS

    for block in parse_blocks(narration(arm)):
        assert len(block.anchor) <= ANCHOR_CHARS
        assert "\n" not in block.anchor
        assert block.anchor == block.anchor.strip()
