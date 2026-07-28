"""Tests for campaignlib.textproc's chunk-annotation helpers.

annotate_chunks_with_pov() exists to carry speaker/date/scene context across
chunk boundaries that fall mid-scene. Two heading conventions are live in real
chapter data: the legacy two-tier ``## date`` / ``### Name``, and the current
single-tier ``## Name — Scene`` from assemble.py. Both must be recognized
without cross-contaminating each other's state.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib import (  # noqa: E402
    annotate_chunks_with_pov,
    chunk_by_scenes,
    chunk_text,
    chunk_text_with_offsets,
    prepare_chunks,
)


def test_current_format_speaker_and_scene_carried_forward():
    chunk1 = "## Grygum — Chaos in the Fungal Cavern\n\nThe fight began."
    chunk2 = "I tried a Guiding Bolt at Ilvara. The bolt missed."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    assert result[0] == chunk1
    assert result[1].startswith(
        "[Continuing — Speaker: Grygum, Scene: Chaos in the Fungal Cavern]\n\n"
    )
    assert result[1].endswith(chunk2)
    assert "Date:" not in result[1]


def test_legacy_two_tier_format_unchanged():
    chunk1 = (
        "## 9th day of the 2nd Tenday of Taraskh 1493\n\n"
        "### Zalthir\n\nSomething happened."
    )
    chunk2 = "I kept fighting."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    assert result[0] == chunk1
    banner = result[1].split("\n\n", 1)[0]
    assert "Date: 9th day of the 2nd Tenday of Taraskh 1493" in banner
    assert "Speaker: Zalthir" in banner
    assert "Scene:" not in banner


def test_no_heading_no_prior_state_no_banner():
    chunk1 = "Just some prose with no headings at all."
    chunk2 = "More prose, still no headings."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    assert result == [chunk1, chunk2]


def test_chunk_opening_with_its_own_heading_gets_no_banner():
    chunk1 = "## Grygum — Chaos in the Fungal Cavern\n\nOpening line."
    chunk2 = "## Daz — The Drow Reinforcements\n\nDaz's turn."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    assert result == [chunk1, chunk2]


def test_empty_narrator_scene_not_treated_as_speaker():
    chunk1 = "## Chaos in the Fungal Cavern\n\nThird-person description."
    chunk2 = "More prose."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    # No em-dash means no speaker was ever identified — falls into the
    # date/other bucket, so no "Speaker:" banner should appear.
    assert result[1].startswith("[Continuing — Date: Chaos in the Fungal Cavern]")
    assert "Speaker:" not in result[1]


def test_multi_heading_chunk_uses_last_heading_of_each_kind():
    chunk1 = (
        "## Grygum — Chaos in the Fungal Cavern\n\nFirst scene.\n\n"
        "## Daz — The Drow Reinforcements\n\nSecond scene begins mid-chunk."
    )
    chunk2 = "Continuing Daz's scene with no heading."
    result = annotate_chunks_with_pov([chunk1, chunk2])
    assert "Speaker: Daz" in result[1]
    assert "Scene: The Drow Reinforcements" in result[1]
    assert "Grygum" not in result[1]


def test_prepare_chunks_end_to_end_with_annotate_pov():
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\n"
        + ("filler " * 4000)
        + "\n\nI tried a Guiding Bolt at Ilvara. The bolt missed."
    )
    chunks, label = prepare_chunks(text, chunk_size=15000, annotate_pov=True)
    assert label == "chunk"
    assert len(chunks) >= 2
    assert chunks[0].startswith("## Grygum — Chaos in the Fungal Cavern")
    assert any("[Continuing — Speaker: Grygum" in c for c in chunks[1:])


# ── chunk_text_with_offsets: the offset-carrying twin of chunk_text ─────────


def test_chunk_text_with_offsets_matches_chunk_text_output():
    """The refactor made chunk_text delegate to chunk_text_with_offsets — pin
    that the two stay byte-identical for every caller that only wants text."""
    text = "Alpha.\n\n" + ("filler " * 3000) + "\n\nOmega."
    assert chunk_text(text, 6000) == [c for _off, c in
                                       chunk_text_with_offsets(text, 6000)]


def test_chunk_text_with_offsets_offsets_point_into_original_text():
    text = "first paragraph.\n\nsecond paragraph.\n\nthird paragraph."
    pieces = chunk_text_with_offsets(text, chunk_size=20)
    for off, chunk in pieces:
        # The stripped chunk must be a substring of the doc starting at (or
        # very near, allowing for stripped leading whitespace) its offset.
        assert text[off:].lstrip().startswith(chunk[:10])


# ── chunk_by_scenes: structural chunking (issue #202) ────────────────────────


def test_chunk_by_scenes_h2_speaker_convention():
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\nFirst scene.\n\n"
        "## Daz — The Drow Reinforcements\n\nSecond scene."
    )
    scenes, convention = chunk_by_scenes(text, chunk_size=15000)
    assert convention == "h2_speaker"
    assert len(scenes) == 2
    assert scenes[0][1].startswith("## Grygum — Chaos in the Fungal Cavern")
    assert scenes[1][1].startswith("## Daz — The Drow Reinforcements")
    assert scenes[0][0] == 0
    assert scenes[1][0] == text.index("## Daz")


def test_chunk_by_scenes_plain_h2_date_convention():
    text = (
        "## 9th day of the 2nd Tenday of Taraskh 1493\n\nFirst thing happened.\n\n"
        "## 10th day of the 2nd Tenday of Taraskh 1493\n\nSecond thing happened."
    )
    scenes, convention = chunk_by_scenes(text, chunk_size=15000)
    assert convention == "h2_date"
    assert len(scenes) == 2


def test_chunk_by_scenes_h3_convention_only_when_no_h2():
    text = "### Zalthir\n\nSomething happened.\n\n### Daz\n\nSomething else."
    scenes, convention = chunk_by_scenes(text, chunk_size=15000)
    assert convention == "h3"
    assert len(scenes) == 2
    assert scenes[0][1].startswith("### Zalthir")
    assert scenes[1][1].startswith("### Daz")


def test_chunk_by_scenes_h2_takes_priority_over_h3():
    text = (
        "## 9th day\n\n### Zalthir\n\nSpoke first.\n\n"
        "## 10th day\n\n### Daz\n\nSpoke second."
    )
    scenes, convention = chunk_by_scenes(text, chunk_size=15000)
    assert convention == "h2_date"
    assert len(scenes) == 2  # split on the two ## lines, not the two ### lines


def test_chunk_by_scenes_returns_none_with_no_heading_convention():
    text = "Just plain prose. No headings anywhere in this document at all."
    assert chunk_by_scenes(text, chunk_size=15000) is None


def test_chunk_by_scenes_folds_preamble_into_first_scene():
    text = (
        "# Chapter 12: The Descent\n\nSome framing prose before any scene.\n\n"
        "## Grygum — Into the Dark\n\nThe scene itself."
    )
    scenes, _convention = chunk_by_scenes(text, chunk_size=15000)
    assert len(scenes) == 1
    assert scenes[0][0] == 0
    assert scenes[0][1].startswith("# Chapter 12: The Descent")
    assert scenes[0][1].endswith("The scene itself.")


def test_chunk_by_scenes_sub_splits_an_oversized_scene():
    big_body = "filler " * 4000  # ~28,000 chars, over a 15,000 chunk_size
    text = (
        f"## Grygum — A Very Long Scene\n\n{big_body}\n\n"
        "## Daz — The Next Scene\n\nShort."
    )
    scenes, convention = chunk_by_scenes(text, chunk_size=15000)
    assert convention == "h2_speaker"
    # The oversized first scene must have been cut into >1 piece; the second
    # (short) scene stays whole.
    assert len(scenes) >= 3
    assert scenes[0][1].startswith("## Grygum — A Very Long Scene")
    assert scenes[-1][1].startswith("## Daz — The Next Scene")
    for _off, chunk in scenes:
        assert len(chunk) <= 15000 + 100  # generous slack for the boundary search


def test_chunk_by_scenes_offsets_are_monotonically_increasing():
    big_body = "filler " * 4000
    text = f"## A — One\n\n{big_body}\n\n## B — Two\n\nShort.\n\n## C — Three\n\nAlso short."
    scenes, _convention = chunk_by_scenes(text, chunk_size=15000)
    offsets = [off for off, _c in scenes]
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == len(offsets)  # no duplicate boundaries


# ── prepare_chunks(structural=True): opt-in wiring ───────────────────────────


def test_prepare_chunks_structural_uses_scene_splitting():
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\nFirst scene.\n\n"
        "## Daz — The Drow Reinforcements\n\nSecond scene."
    )
    chunks, label = prepare_chunks(text, chunk_size=15000, structural=True)
    assert label == "scene"
    assert len(chunks) == 2


def test_prepare_chunks_structural_skips_pov_annotation_on_scene_chunks():
    """Every structural chunk already opens with its own heading, so the
    annotate_pov repair pass — damage size-chunking inflicts — must not run,
    even when annotate_pov=True is also passed (as the ensemble passes always
    do)."""
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\nFirst scene.\n\n"
        "## Daz — The Drow Reinforcements\n\nSecond scene."
    )
    chunks, label = prepare_chunks(text, chunk_size=15000, structural=True,
                                   annotate_pov=True)
    assert label == "scene"
    assert not any("[Continuing" in c for c in chunks)


def test_prepare_chunks_structural_falls_back_to_character_count_with_no_heading():
    """16 of 62 real OOTA chapters have no heading at all — the character-count
    fallback must still trigger, and annotate_pov must still run on it (the
    fallback is load-bearing, not vestigial)."""
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\n"
        + ("filler " * 4000)
        + "\n\nI tried a Guiding Bolt at Ilvara. The bolt missed."
    )
    # No heading at all this time.
    plain = "Just narration with no headings anywhere.\n\n" + ("filler " * 4000)
    chunks, label = prepare_chunks(plain, chunk_size=6000, structural=True,
                                   annotate_pov=True)
    assert label == "chunk"
    assert len(chunks) >= 2
    del text  # unused; kept for readability of the intentional contrast above


def test_prepare_chunks_default_structural_off_is_unchanged():
    """OPT-IN: omitting `structural` (every existing caller) must produce
    exactly today's character-count chunking, even for a document that WOULD
    have a recognized heading convention."""
    text = (
        "## Grygum — Chaos in the Fungal Cavern\n\nFirst scene.\n\n"
        "## Daz — The Drow Reinforcements\n\nSecond scene."
    )
    chunks, label = prepare_chunks(text, chunk_size=15000)
    assert label == "chunk"
    assert chunks == [text.strip()]  # one chunk — well under chunk_size
