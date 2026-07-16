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

from campaignlib import annotate_chunks_with_pov, prepare_chunks  # noqa: E402


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
