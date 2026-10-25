"""arc_triggers wing selection (CampaignGenerator #593 Part A)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.grounding import arc_triggers as at

SCORE_DOC = (
    "**Brew Score**\n\n**Score Increase Triggers:**\n"
    "* **Pours a drink:** Brew pours a drink for a stranger.\n"
)


def _campaign(tmp_path: Path, corpus: bool, mempalace: str = "") -> Path:
    camp = tmp_path / "camp"
    (camp / "config").mkdir(parents=True)
    (camp / "config" / "config.yaml").write_text(mempalace or "documents: []\n")
    (camp / "docs" / "tracking").mkdir(parents=True)
    (camp / "docs" / "tracking" / "brewbarry-score.md").write_text(SCORE_DOC)
    if corpus:
        (camp / ".mneme").mkdir()
        (camp / ".mneme" / "corpus.yaml").write_text("kinds: {}\n")
    return camp


@pytest.fixture
def calls(monkeypatch):
    log: list[tuple] = []

    def fake(query, wing=None, room=None, top=3):
        log.append((wing, room))
        return [{"rank": 1, "wing": wing, "room": "r", "source": f"{wing}.md",
                 "score": {"a": "0.5", "b": "0.9"}.get(wing, "0.1"), "content": ["x"]}]

    monkeypatch.setattr(at, "search_mempalace", fake)
    return log


def test_mp_bin_is_not_another_machines_path():
    assert "/home/kroussos" not in at.MP_BIN
    assert at.MP_BIN.endswith("mempalace")


def test_non_corpus_queries_hardcoded_wings(tmp_path, calls):
    camp = _campaign(tmp_path, corpus=False)
    out = at.search_triggers("brewbarry", campaign_dir=camp)
    assert calls == [("phandalin", "arcs"), ("chronicle", None)]
    assert "**Source wing:** chronicle (timeline facts)" in out


def test_non_corpus_with_canon_wing_still_uses_hardcoded_wings(tmp_path, calls):
    camp = _campaign(tmp_path, False, "mempalace:\n  canon_wing: toee\n  index_wings: [chronicle]\n")
    at.search_triggers("brewbarry", campaign_dir=camp)
    assert calls == [("phandalin", "arcs"), ("chronicle", None)]


def test_non_corpus_never_reads_config(tmp_path, calls):
    camp = _campaign(tmp_path, False, "mempalace: [this is: not: valid yaml\n")
    at.search_triggers("brewbarry", campaign_dir=camp)
    assert calls == [("phandalin", "arcs"), ("chronicle", None)]


def test_corpus_skips_score_doc_query_and_searches_each_canon_wing(tmp_path, calls):
    camp = _campaign(
        tmp_path, True, "mempalace:\n  canon_wings: [a, b]\n  index_wings: [npcs]\n"
    )
    out = at.search_triggers("brewbarry", top=1, campaign_dir=camp)
    assert calls == [("a", None), ("b", None)]  # no phandalin/arcs, no chronicle
    assert "**Source wing:** a, b (canon wings)" in out
    assert "Brew Score" in out  # read from docs/tracking
    assert "b.md" in out and "a.md" not in out  # merged by score, top 1


def test_corpus_empty_canon_wings_says_so_and_searches_nothing(tmp_path, calls):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: []\n  index_wings: []\n")
    out = at.search_triggers("brewbarry", campaign_dir=camp)
    assert calls == []
    assert "No canon wings are declared" in out


def test_corpus_missing_canon_wings_is_refused(tmp_path, calls, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wing: narrative\n")
    monkeypatch.setattr(at, "CAMPAIGN_DIR", camp)
    monkeypatch.setattr("sys.argv", ["arc_triggers", "--character", "brewbarry"])
    with pytest.raises(SystemExit) as ei:
        at.main()
    assert ei.value.code != 0
    assert "canon_wings" in capsys.readouterr().err
    assert calls == []
