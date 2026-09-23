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


# ── Contract R — the authored record ────────────────────────────────────────

from datetime import date  # noqa: E402

from session_doc.authored import (  # noqa: E402
    AuthoredBlock,
    AuthoredError,
    AuthoredRecord,
    load_record,
    record_path,
)
from session_doc.compose import (  # noqa: E402
    GENERATED_NOTE,
    ComposeError,
    compose,
    open_gap_ids,
)
from session_doc.review.export import digest  # noqa: E402


def _record(**kw) -> AuthoredRecord:
    kw.setdefault("narration", "response.md")
    kw.setdefault("generated_sha256", "sha256:abc")
    return AuthoredRecord(**kw)


def test_an_unrecognised_key_is_refused_naming_it():
    """R1."""
    with pytest.raises(Exception, match="surprise"):
        AuthoredRecord.model_validate({
            "narration": "x.md", "generated_sha256": "sha256:0", "surprise": 1})


def test_an_unknown_record_version_is_refused():
    """R2 — the same call `transcript_corrections` makes."""
    with pytest.raises(Exception, match="unknown record version"):
        AuthoredRecord.model_validate({
            "version": 7, "narration": "x.md", "generated_sha256": "sha256:0"})


def test_two_entries_for_one_block_are_refused():
    """R3. Which one wins would depend on file order — exactly why two
    corrections on one cue are refused one layer down."""
    with pytest.raises(Exception, match="more than one entry"):
        _record(blocks=[
            AuthoredBlock(id="gap-1", disposition="mine"),
            AuthoredBlock(id="gap-1", disposition="cut"),
        ])


def test_an_unknown_disposition_is_refused_and_says_unruled_has_no_entry():
    with pytest.raises(Exception, match="no entry at all"):
        AuthoredBlock(id="gap-1", disposition="unruled")


def test_mine_and_authored_are_distinct_stored_values():
    """R5, and the heart of the GM's workflow.

    "Ruled mine, not yet written" is the normal end state of a review done on a
    phone. Inferring the disposition from whether text is present would merge it
    with "wrote an empty string" and lose exactly what a triage pass produces.
    """
    mine = AuthoredBlock(id="gap-1", disposition="mine")
    assert mine.text is None
    with pytest.raises(Exception, match="carries no text"):
        AuthoredBlock(id="gap-2", disposition="authored")


def test_a_cut_block_may_not_also_carry_text():
    with pytest.raises(Exception, match="which one wins"):
        AuthoredBlock(id="gap-1", disposition="cut", text="something")


def test_an_unknown_critique_is_refused():
    with pytest.raises(Exception, match="critique must be one of"):
        AuthoredBlock(id="gap-1", disposition="mine", critique="dislike")


def test_has_authored_content_is_about_prose_not_rulings():
    """What a re-narrate must not destroy. Rulings are cheap to redo; prose is
    the only thing here a human wrote from scratch."""
    assert not _record(blocks=[AuthoredBlock(id="gap-1", disposition="mine")]).has_authored_content
    assert not _record(blocks=[AuthoredBlock(id="gap-1", disposition="cut")]).has_authored_content
    assert _record(blocks=[
        AuthoredBlock(id="gap-1", disposition="authored", text="x")]).has_authored_content


def test_a_record_round_trips_through_yaml(tmp_path):
    import yaml

    rec = _record(blocks=[AuthoredBlock(
        id="gap-1", disposition="authored", text="The door shuts.",
        critique="wrong-scope", anchor="a", recorded=date(2026, 9, 8))])
    p = tmp_path / "x.authored.yaml"
    p.write_text(yaml.safe_dump(rec.model_dump(mode="json"), sort_keys=False),
                 encoding="utf-8")
    assert load_record(p).by_id()["gap-1"].text == "The door shuts."


def test_a_malformed_record_names_the_file(tmp_path):
    p = tmp_path / "x.authored.yaml"
    p.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(AuthoredError, match="mapping"):
        load_record(p)


def test_the_record_sits_beside_the_narration():
    assert record_path(Path("a/session_doc_scene_01_x.md")).name == \
        "session_doc_scene_01_x.authored.yaml"


# ── Contract C — composing ──────────────────────────────────────────────────

BREW = CORPUS / "brewbarry" / "response.md"


def _real_record(**kw) -> AuthoredRecord:
    text = BREW.read_text(encoding="utf-8")
    return AuthoredRecord(narration="response.md", generated_sha256=digest(text),
                          blocks=kw.get("blocks", []))


def test_composing_is_byte_identical_twice():
    """C1. A generated file that differs between runs cannot be reviewed by
    diff, which is the only way anyone checks one."""
    text = BREW.read_text(encoding="utf-8")
    rec = _real_record(blocks=[AuthoredBlock(id="gap-1", disposition="authored", text="X.")])
    assert compose(text, rec) == compose(text, rec)


def test_each_disposition_composes_per_the_data_model():
    """C2."""
    text = BREW.read_text(encoding="utf-8")
    rec = _real_record(blocks=[
        AuthoredBlock(id="gap-1", disposition="authored", text="The door shuts."),
        AuthoredBlock(id="gap-2", disposition="cut"),
        AuthoredBlock(id="gap-3", disposition="mine"),
    ])
    out = compose(text, rec)
    assert "The door shuts." in out                       # authored -> the prose
    assert "Aurelan Vance comes hurrying back" not in out  # cut -> nothing
    assert "pats himself down" in out                      # mine -> still a gap


def test_a_stale_record_refuses_naming_both_digests():
    """C3, and the whole of v1's staleness handling.

    Composing a record against a draft it was not authored for would place the
    GM's prose against text it was never written for — the failure `was` checking
    prevents on the tape.
    """
    rec = _real_record(blocks=[])
    with pytest.raises(ComposeError, match="authored against a different draft"):
        compose(BREW.read_text(encoding="utf-8") + "\n", rec)


def test_the_composed_document_says_it_is_generated():
    """C4. It is output; the record is the thing a human edits."""
    assert GENERATED_NOTE in compose(BREW.read_text(encoding="utf-8"), _real_record())


def test_an_empty_record_reproduces_the_narration_body():
    """C5. Composing nothing changes nothing — which is what makes the round
    trip in contract P worth having."""
    text = BREW.read_text(encoding="utf-8")
    from campaignlib.textproc import split_frontmatter

    _meta, body = split_frontmatter(text)
    assert compose(text, _real_record()).endswith(body)


def test_a_critique_alone_changes_nothing():
    """R6. It is feedback on the contract, not a decision about the chapter."""
    text = BREW.read_text(encoding="utf-8")
    plain = compose(text, _real_record())
    with_critique = compose(text, _real_record(blocks=[
        AuthoredBlock(id="gap-1", disposition="mine", critique="wrong-scope")]))
    assert plain == with_critique


def test_open_gaps_count_mine_and_unruled_alike():
    """The gate's question. A finished triage still has open gaps — that is
    success on a phone, and it is still not a chapter."""
    text = BREW.read_text(encoding="utf-8")
    rec = _real_record(blocks=[
        AuthoredBlock(id="gap-1", disposition="authored", text="X."),
        AuthoredBlock(id="gap-2", disposition="cut"),
        AuthoredBlock(id="gap-3", disposition="mine"),
    ])
    assert open_gap_ids(text, rec) == ["gap-3", "gap-4", "gap-5", "gap-6"]
    assert len(open_gap_ids(text, None)) == 6


# ── US3 — the model's prose, edited ─────────────────────────────────────────

def test_an_untouched_prose_block_produces_no_record_entry():
    """FR-004 / R4 — the record stores only what the human contributed."""
    rec = _real_record()
    assert rec.blocks == []


def test_an_edited_prose_block_carries_only_the_human_s_text():
    text = BREW.read_text(encoding="utf-8")
    rec = _real_record(blocks=[
        AuthoredBlock(id="prose-1", disposition="edited", text="She said nothing.")])
    out = compose(text, rec)
    assert "She said nothing." in out


def test_a_prose_block_edited_to_empty_is_still_an_edit():
    """Deleting the model's paragraph is a legitimate editorial act, and it must
    be distinguishable from never having touched it."""
    block = AuthoredBlock(id="prose-1", disposition="edited", text="")
    assert block.disposition == "edited"
    assert block.text == ""
