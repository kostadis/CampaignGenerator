"""arc_triggers wing selection (CampaignGenerator #593 Part A)."""

from __future__ import annotations

from pathlib import Path

import json
import subprocess

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


class FakeMneme:
    """Stands in for subprocess.run of `mneme corpus toc`; never runs a binary."""

    def __init__(self):
        self.cmds: list[list[str]] = []
        self.returncode = 0
        self.stdout = ""
        self.stderr = ""

    def serve_arcs(self, paths):
        self.stdout = json.dumps(
            {"valid": True, "kinds": {"arcs": {"files": [{"path": p} for p in paths]}}}
        )

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def mneme(monkeypatch):
    fake = FakeMneme()
    monkeypatch.setattr(at.subprocess, "run", fake)
    return fake


def _arcs_doc(camp: Path, rel: str = "arcs/brewbarry-score.md") -> str:
    f = camp / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(SCORE_DOC)
    return rel


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


def test_non_corpus_queries_hardcoded_wings(tmp_path, calls, mneme):
    camp = _campaign(tmp_path, corpus=False)
    out = at.search_triggers("brewbarry", campaign_dir=camp)
    assert mneme.cmds == []  # a non-corpus campaign never asks mneme
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


def test_corpus_takes_score_doc_from_toc_and_searches_each_canon_wing(tmp_path, calls, mneme):
    camp = _campaign(
        tmp_path, True, "mempalace:\n  canon_wings: [a, b]\n  index_wings: [npcs]\n"
    )
    mneme.serve_arcs([_arcs_doc(camp)])
    out = at.search_triggers("brewbarry", top=1, campaign_dir=camp)
    assert mneme.cmds == [[
        at.MNEME_BIN, "corpus", "toc", "camp", "--dir", str(camp),
        "--kind", "arcs", "--json",
    ]]
    assert calls == [("a", None), ("b", None)]  # no phandalin/arcs, no chronicle
    assert "**Source wing:** a, b (canon wings)" in out
    assert "**Score file:** brewbarry-score.md" in out
    assert "b.md" in out and "a.md" not in out  # merged by score, top 1


def test_corpus_ignores_docs_tracking_file_absent_from_toc(tmp_path, calls, mneme):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")
    # docs/tracking/brewbarry-score.md exists (decoy) but the TOC omits it
    mneme.serve_arcs([_arcs_doc(camp, "arcs/other-score.md")])
    out = at.search_triggers("brewbarry", campaign_dir=camp)
    assert "Could not find a score tracking document" in out
    assert "corpus kind 'arcs'" in out and "other-score.md" in out
    assert "brewbarry-score.md" not in out
    assert calls == []


def test_corpus_empty_canon_wings_says_so_and_searches_nothing(tmp_path, calls, mneme):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: []\n  index_wings: []\n")
    out = at.search_triggers("brewbarry", campaign_dir=camp)
    assert calls == []
    assert "No canon wings are declared" in out


def _run_main(monkeypatch, camp, *argv):
    monkeypatch.setattr(at, "CAMPAIGN_DIR", camp)
    monkeypatch.setattr("sys.argv", ["arc_triggers", *argv])
    with pytest.raises(SystemExit) as ei:
        at.main()
    return ei.value.code


def test_corpus_kind_not_declared_is_refused(tmp_path, calls, mneme, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")
    mneme.returncode = 2
    mneme.stderr = "error: kind 'arcs' is not declared for this campaign\n"
    code = _run_main(monkeypatch, camp, "--character", "brewbarry")
    assert code not in (0, None)
    err = capsys.readouterr().err
    assert "arc_triggers: error: kind 'arcs' is not declared for this campaign" in err
    assert calls == []


def test_corpus_invalid_is_refused(tmp_path, calls, mneme, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")
    mneme.returncode = 1
    mneme.stderr = "error: corpus.yaml: unknown kind\n"
    code = _run_main(monkeypatch, camp, "--character", "brewbarry")
    assert code not in (0, None)
    assert "arc_triggers: error: corpus.yaml: unknown kind" in capsys.readouterr().err
    assert calls == []


def test_corpus_valid_false_json_is_refused(tmp_path, calls, mneme, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")
    mneme.stdout = json.dumps({"valid": False, "kinds": {"arcs": {"files": []}}})
    assert _run_main(monkeypatch, camp, "--character", "brewbarry") not in (0, None)
    assert "arc_triggers:" in capsys.readouterr().err
    assert calls == []


def test_corpus_missing_mneme_binary_is_refused(tmp_path, calls, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")

    def boom(cmd, **kw):
        raise FileNotFoundError(2, "No such file", cmd[0])

    monkeypatch.setattr(at.subprocess, "run", boom)
    assert _run_main(monkeypatch, camp, "--character", "brewbarry") not in (0, None)
    assert "arc_triggers:" in capsys.readouterr().err
    assert calls == []


def test_corpus_toc_without_arcs_kind_is_refused(tmp_path, calls, mneme, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wings: [a]\n")
    mneme.stdout = json.dumps({"valid": True, "kinds": {}})
    assert _run_main(monkeypatch, camp, "--character", "brewbarry") not in (0, None)
    assert "arc_triggers:" in capsys.readouterr().err


def test_corpus_missing_canon_wings_is_refused(tmp_path, calls, mneme, monkeypatch, capsys):
    camp = _campaign(tmp_path, True, "mempalace:\n  canon_wing: narrative\n")
    monkeypatch.setattr(at, "CAMPAIGN_DIR", camp)
    monkeypatch.setattr("sys.argv", ["arc_triggers", "--character", "brewbarry"])
    with pytest.raises(SystemExit) as ei:
        at.main()
    assert ei.value.code != 0
    assert "canon_wings" in capsys.readouterr().err
    assert calls == []
