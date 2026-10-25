"""Tests for the canon/index wing resolver (CampaignGenerator #593 Part A).

One test per row of the issue's "Must not change" table, plus the refusal and
precedence rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaignlib.mempalace_wings import MempalaceWingsError, resolve_mempalace_wings


def _campaign(tmp_path: Path, name: str, corpus: bool = False) -> Path:
    d = tmp_path / name
    d.mkdir()
    if corpus:
        (d / ".mneme").mkdir()
        (d / ".mneme" / "corpus.yaml").write_text("kinds: {}\n")
    return d


def test_toee_reads_canon_wing_as_today(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wing": "toee", "index_wings": ["chronicle", "prep"]},
        _campaign(tmp_path, "toee"),
    )
    assert (w.canon_wings, w.index_wings, w.is_corpus) == (
        ["toee"], ["chronicle", "prep"], False,
    )


def test_obelisk_reads_canon_wing_as_today(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wing": "narrative", "index_wings": ["notes", "summaries"]},
        _campaign(tmp_path, "obelisk"),
    )
    assert w.canon_wings == ["narrative"]
    assert w.index_wings == ["notes", "summaries"]
    assert not w.is_corpus


def test_out_of_the_abyss_explicit_index_wings_win(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wing": "narrative", "index_wings": ["chronicle", "abyss"]},
        _campaign(tmp_path, "out-of-the-abyss"),
    )
    assert w.canon_wings == ["narrative"]
    assert w.index_wings == ["chronicle", "abyss"]


@pytest.mark.parametrize("section", [None, {}])
def test_phandalin_no_section_keeps_defaults(tmp_path, section):
    w = resolve_mempalace_wings(section, _campaign(tmp_path, "Phandalin"))
    assert w.canon_wings == ["narrative"]
    assert w.index_wings == ["chronicle", "Phandalin"]
    assert not w.is_corpus


def test_default_index_wing_replaces_dashes(tmp_path):
    w = resolve_mempalace_wings(None, _campaign(tmp_path, "lost-mine"))
    assert w.index_wings == ["chronicle", "lost_mine"]


def test_migrated_campaign_searches_every_canon_wing(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wings": ["summaries", "grounding"], "index_wings": ["npcs", "prep"]},
        _campaign(tmp_path, "migrated", corpus=True),
    )
    assert w.canon_wings == ["summaries", "grounding"]
    assert w.index_wings == ["npcs", "prep"]
    assert w.is_corpus


def test_corpus_with_only_canon_wing_is_refused(tmp_path):
    camp = _campaign(tmp_path, "bad", corpus=True)
    with pytest.raises(MempalaceWingsError) as ei:
        resolve_mempalace_wings({"canon_wing": "narrative"}, camp)
    msg = str(ei.value)
    assert str(camp / "config" / "config.yaml") in msg
    assert "canon_wings" in msg and "mneme mp refresh" in msg


def test_corpus_with_no_section_is_refused(tmp_path):
    with pytest.raises(MempalaceWingsError):
        resolve_mempalace_wings(None, _campaign(tmp_path, "bad", corpus=True))


def test_canon_wings_wins_without_corpus(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wings": ["a", "b"], "canon_wing": "old"},
        _campaign(tmp_path, "plain"),
    )
    assert w.canon_wings == ["a", "b"]
    assert not w.is_corpus


def test_empty_canon_wings_on_corpus_is_empty_not_refused(tmp_path):
    w = resolve_mempalace_wings(
        {"canon_wings": [], "index_wings": ["npcs"]},
        _campaign(tmp_path, "empty", corpus=True),
    )
    assert w.canon_wings == []
    assert w.is_corpus


def test_corpus_marker_must_be_a_file(tmp_path):
    camp = _campaign(tmp_path, "dirmarker")
    (camp / ".mneme" / "corpus.yaml").mkdir(parents=True)
    w = resolve_mempalace_wings({"canon_wing": "x"}, camp)
    assert not w.is_corpus and w.canon_wings == ["x"]
