"""npc_slug: the published slug and the corpus stem for one NPC (spec 032 R6)."""

from __future__ import annotations

import pytest

from pipelines.summary_native import corpus, npc_slug


@pytest.mark.parametrize(
    "canonical,slug",
    [
        ("Ilvara Mizzrym", "ilvara-mizzrym"),
        ("Jimjar", "jimjar"),
        ("  Eelrich  Vane ", "eelrich-vane"),
        ("Sarith (the Elder)", "sarith-the-elder"),
        ("Old Mother's Stool", "old-mother-s-stool"),
        ("---", "unnamed"),
    ],
)
def test_slug_for(canonical, slug):
    assert npc_slug.slug_for(canonical) == slug


def test_stem_for_matches_corpus_semantics():
    assert npc_slug.stem_for("npc", "Ilvara Mizzrym") == "npc_ilvara_mizzrym"
    expected = corpus.dossier_filenames([("npc", "Ilvara Mizzrym", [])])[0].removesuffix(".md")
    assert npc_slug.stem_for("npc", "Ilvara Mizzrym") == expected


def test_stems_for_hash_suffixes_a_colliding_stem():
    stems = npc_slug.stems_for([("npc", "Old-Mother"), ("npc", "Old Mother"), ("npc", "Jimjar")])
    assert stems[("npc", "Jimjar")] == "npc_jimjar"
    a, b = stems[("npc", "Old-Mother")], stems[("npc", "Old Mother")]
    assert a != b and a.startswith("npc_old_mother_") and b.startswith("npc_old_mother_")


def test_slug_collisions_names_both():
    got = npc_slug.slug_collisions(["Old Mother", "Old-Mother", "Jimjar", "Jimjar"])
    assert got == {"old-mother": ["Old Mother", "Old-Mother"]}


def test_slug_collisions_empty_when_none():
    assert npc_slug.slug_collisions(["Jimjar", "Eldeth"]) == {}
