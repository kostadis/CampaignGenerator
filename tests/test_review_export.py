"""The scene export — the reviewer's input (#455).

Asserted against the four real narrations in
`experiments/20260907-phandalin-gm-gaps-confirm/`, because size and GM-turn
counts are properties of real scenes and a fixture would be written to suit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from session_doc.blocks import parse_blocks  # noqa: E402
from session_doc.review.export import build_export, digest, read_source_gm_turns  # noqa: E402
from session_doc.review.schema import EXPORT_VERSION, SceneExport  # noqa: E402

CORPUS = ROOT / "experiments/20260907-phandalin-gm-gaps-confirm"
if not CORPUS.is_dir():
    raise AssertionError(f"the #455 corpus is missing: {CORPUS}")

#: `gm_turns_in_source` from the confirmation experiment's own summary.json —
#: an independent figure this reader must reproduce.
ARMS = {"brewbarry": 41, "soma": 47, "valphine": 16, "vukradin": 40}


def export_for(arm: str) -> SceneExport:
    narration = CORPUS / arm / "response.md"
    return build_export(
        narration_path=narration,
        narration_text=narration.read_text(encoding="utf-8"),
        extraction_text=(CORPUS / "inputs" / f"{arm}_source.md").read_text(encoding="utf-8"),
    )


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_the_export_carries_what_the_reviewer_renders(arm):
    e = export_for(arm)
    assert e.version == EXPORT_VERSION
    assert e.narration == "response.md"
    assert e.generated_sha256.startswith("sha256:")
    assert e.blocks and e.gap_count > 0
    assert e.word_count > 0


@pytest.mark.parametrize("arm,expected", sorted(ARMS.items()))
def test_the_gm_turn_reader_reproduces_the_experiment_s_own_count(arm, expected):
    """Cross-check against a number this code did not produce.

    The confirmation run counted GM turns independently, in its own `run.py`,
    before any of this existed. Matching it is evidence the reader handles all
    the label conventions in the corpus — bare `**GM**`, bracketed `**[GM]**`,
    qualified and joint — rather than only the one it was written against.
    """
    assert export_for(arm).gm_turn_count == expected


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_export_block_ids_are_the_ids_the_record_will_use(arm):
    """FR-018. If the export and the record numbered blocks differently, a
    review could not be reconciled with the draft it was made against, and the
    mismatch would show up as prose landing in the wrong place."""
    narration = (CORPUS / arm / "response.md").read_text(encoding="utf-8")
    from campaignlib.textproc import split_frontmatter

    _meta, body = split_frontmatter(narration)
    assert [b.id for b in export_for(arm).blocks] == [b.id for b in parse_blocks(body)]


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_one_scene_stays_pasteable_on_a_phone(arm):
    """FR-013 / SC-003, against the band measured in research D9.

    The upper bound is the point: a whole session is ~82 KB, and a paste that
    silently truncates renders half a scene as though it were whole.
    """
    size_kb = len(export_for(arm).model_dump_json()) / 1024
    assert 5 < size_kb < 40, f"{arm} export is {size_kb:.1f} KB"


def test_a_gm_turn_carries_its_line_note_and_quote():
    """What makes the foot table usable: the GM finds the turn in the source
    afterwards, and rules the gap against the quote rather than from memory."""
    turns = read_source_gm_turns(
        (CORPUS / "inputs" / "brewbarry_source.md").read_text(encoding="utf-8"))
    first = turns[0]
    assert first.line == 24
    assert first.label == "GM"
    assert "opening recap" in first.note
    assert "Spire of the Morninglord" in first.quote


def test_a_non_gm_label_is_not_listed():
    """The table is the GM's turns. A player's line in it would invite ruling a
    gap against something the GM never said."""
    turns = read_source_gm_turns(
        '**Soma**\n> "That\'s dicks."\n\n**GM** — *recap*\n> "You have left."\n')
    assert [t.label for t in turns] == ["GM"]


def test_a_joint_or_qualified_gm_label_is_listed():
    """`**[GM, as the banker]**` and `**[GM / Brewbarry]**` are both real in the
    corpus. This is a display filter for a reference table and asserts nothing
    about who spoke — the identity rules live in plan_eligibility (#453)."""
    turns = read_source_gm_turns(
        '**[GM, as the banker]**\n> "Well?"\n\n**[GM / Brewbarry]**\n> "Both."\n')
    assert len(turns) == 2


def test_an_unknown_version_is_refused_rather_than_ignored():
    with pytest.raises(Exception):
        SceneExport.model_validate({
            "version": 99, "narration": "x.md", "generated_sha256": "sha256:0",
            "scene_index": 1, "scene_name": "x", "narrator": "y",
            "word_count": 1, "gap_count": 0, "gm_turn_count": 0, "blocks": [],
        })


def test_an_unrecognised_key_is_refused():
    with pytest.raises(Exception):
        SceneExport.model_validate({
            "version": EXPORT_VERSION, "narration": "x.md",
            "generated_sha256": "sha256:0", "scene_index": 1, "scene_name": "x",
            "narrator": "y", "word_count": 1, "gap_count": 0, "gm_turn_count": 0,
            "blocks": [], "surprise": True,
        })


def test_the_digest_changes_when_the_narration_does():
    """The record's staleness check rests on this."""
    assert digest("a") != digest("a ")


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_the_export_is_json_serialisable_and_reloads(arm):
    """It is pasted through a clipboard, so it must survive a round trip."""
    raw = export_for(arm).model_dump_json()
    assert SceneExport.model_validate(json.loads(raw)).gap_count == export_for(arm).gap_count


# ── The clipboard is a lossy channel, so the payload defends itself ─────────

@pytest.mark.parametrize("arm", sorted(ARMS))
def test_the_export_written_to_disk_is_pure_ascii(arm, tmp_path):
    """Found in the field, on the first real review off this page.

    Served as `application/json` with no charset, a phone browser guessed
    Windows-1252 and every em dash came back as `â€”` — into the anchors, and
    into any passage the GM had typed. The file on disk was fine; the transport
    mangled it.

    Fixing one server's headers would not have been enough: this document's
    channel is a mobile clipboard by way of whatever happens to render it, and
    that is not under our control. Escaping every non-ASCII character makes the
    payload immune to a charset guess, and it parses back to the identical text.
    """
    import json as _json
    import subprocess

    out = tmp_path / "scene.json"
    narration = CORPUS / arm / "response.md"
    rc = subprocess.run(
        [sys.executable, "-m", "session_doc.sd_review", "export",
         "--scene", str(narration),
         "--extraction", str(CORPUS / "inputs" / f"{arm}_source.md"),
         "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT)
    assert rc.returncode == 0, rc.stderr

    raw = out.read_bytes()
    assert raw.isascii(), "the export must survive a charset guess"
    assert b"\xe2\x80\x94" not in raw          # no raw em-dash bytes
    # …and the escapes must decode back to the real characters, not to hyphens.
    assert "—" in _json.loads(raw)["blocks"][0]["text"] or export_for(arm).gap_count == 0
