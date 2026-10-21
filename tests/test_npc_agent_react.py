"""Prototype 6 (react): an NPC who was never present, told of events by reports. Synthetic text and a FAKE model only."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipelines.npc_agent import agent, cli, corpus, prep, react, react_page

CH51 = """# Chapter 51

## Scenes

### The Contract

#### A contract is posted for Daz.

- The Duskryn courier names a price.
- Vizeran was unaware that the party plotted at the Spire.
- The courier leaves by night.

### The Blade

#### A noble house sends a blade.

- The assassin fails at the inn.
"""

CH53 = """# Chapter 53

## Scenes

### The Aftermath

#### The inn is searched.

- A signet ring is found.
"""

CH55 = """# Chapter 55

## Scenes

### The Betrayal

#### Zorgath reveals everything.

- FUTURE-MARKER the vault falls.
"""

PREP = """# Prep

## Vizeran prep

Vizeran keeps a ledger of every contract.

Vizeran fears the drow more than the party.
"""

KEY = "CANON-ONLY-MARKER Vizeran schemes with the Spire </script><b>x</b> forever."


@pytest.fixture
def camp(tmp_path: Path) -> Path:
    c = tmp_path / "camp"
    (c / "summaries").mkdir(parents=True)
    (c / "summaries" / "051-contract.md").write_text(CH51)
    (c / "summaries" / "053-aftermath.md").write_text(CH53)
    (c / "summaries" / "055-betrayal.md").write_text(CH55)
    return c


def _prep(tmp_path: Path, ruled: str = "all") -> tuple[Path, Path]:
    d = tmp_path / "private"
    d.mkdir(exist_ok=True)
    pf = d / "prep.md"
    pf.write_text(PREP)
    ps = prep.extract(PREP, ("Vizeran",), "Vizeran prep", file=str(pf))
    passages = {ps[0].pid: "hers"} if ruled == "some" else {ps[0].pid: "hers", ps[1].pid: "gm"}
    pj = d / "prep.json"
    pj.write_text(json.dumps({"version": 1, "npc": "Vizeran DeVir", "targets": {
        "m1": {"source": "prep.md", "section": "Vizeran prep", "passages": passages}}}))
    (d / "canon.md").write_text(KEY)
    return pf, pj


GOOD = json.dumps({"reaction": "Vizeran sets down his cup. \"A blade, and it failed.\" He thinks of Zorgath.",
                   "assessment": "A noble house moves against Daz. That is useful to me.",
                   "decisions": [{"decision": "Offer the house a quiet bargain.", "why": "It costs me nothing."},
                                 {"decision": "Burn the ledger.", "why": "Safety."}]})


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def play(args, system, user):
        calls.append((system, user))
        return GOOD

    monkeypatch.setattr(agent, "play", play)
    return calls


def _react(camp, tmp_path, *extra, reported=("051.01", "051.02", "053.01"), freeze="53", out="out", ruled="all"):
    pf, pj = _prep(tmp_path, ruled)
    argv = ["react", "--campaign-dir", str(camp), "--subject", "Vizeran DeVir", "--form", "Vizeran",
            "--moment", "m1", "--question", "What do you decide?", "--freeze", freeze, "--via", "your cutouts",
            "--prep", str(pf), "--section", "Vizeran prep", "--prep-rulings", str(pj),
            "--answer-key", str(pf.parent / "canon.md"), "--out-dir", str(tmp_path / out), *extra]
    for r in reported:
        argv += ["--reported", r]
    return cli.main(argv), tmp_path / out


def test_refuses_a_future_reported_scene_and_writes_nothing(camp, tmp_path, fake, capsys):
    rc, out = _react(camp, tmp_path, reported=("051.01", "055.01"))
    assert rc == 2 and "after the freeze chapter 53" in capsys.readouterr().err
    assert not out.exists() and not fake


def test_refuses_an_unknown_scene(camp, tmp_path, fake, capsys):
    rc, out = _react(camp, tmp_path, reported=("051.09",))
    assert rc == 2 and "not a scene in the summaries" in capsys.readouterr().err
    assert not out.exists()
    rc, _ = _react(camp, tmp_path, reported=("51.1",))
    assert rc == 2


def test_refuses_while_the_prep_is_unruled(camp, tmp_path, fake, capsys):
    rc, out = _react(camp, tmp_path, ruled="some")
    assert rc == 2 and "not ruled yet" in capsys.readouterr().err
    assert not fake


def test_reports_exclude_hidden_beats_and_nothing_after_the_freeze(camp, tmp_path, fake):
    rc, out = _react(camp, tmp_path)
    assert rc == 0
    user = (out / "m1" / "prompt.user.md").read_text()
    assert "The Duskryn courier names a price." in user and "A signet ring is found." in user
    assert "party plotted at the Spire" not in user  # hidden from Vizeran
    assert "FUTURE-MARKER" not in user and "Zorgath reveals" not in user
    assert "Reported to you via your cutouts; you were not there." in user
    heads = re.findall(r"^## .*$", user, re.M)
    assert heads == ["## Who you are and what you hold privately", "## What has reached you", "## The question"]
    assert "Vizeran keeps a ledger" in user and "fears the drow" not in user  # only 'hers'


def test_reports_are_in_corpus_order(camp):
    c = corpus.load_corpus(camp / "summaries")
    rs = react.reports(c, ["053.01", "051.02", "051.01"], 53)
    assert [r.scene_id for r in rs] == ["051.01", "051.02", "053.01"]


def test_answer_key_text_is_never_in_a_prompt_but_reaches_the_bundle(camp, tmp_path, fake):
    rc, out = _react(camp, tmp_path)
    assert rc == 0
    for f in ("prompt.system.md", "prompt.user.md"):
        assert "CANON-ONLY-MARKER" not in (out / "m1" / f).read_text()
    assert all("CANON-ONLY-MARKER" not in s and "CANON-ONLY-MARKER" not in u for s, u in fake)
    b = json.loads((out / "m1" / "bundle.json").read_text())
    assert b["answer_keys"] == [{"name": "canon.md", "text": KEY}]


def test_writes_the_run_files_and_flags_a_future_name(camp, tmp_path, fake):
    rc, out = _react(camp, tmp_path)
    m = out / "m1"
    for name in ("prompt.system.md", "prompt.user.md", "answer.raw.md", "answer.json", "flags.json", "run.json", "bundle.json"):
        assert (m / name).is_file(), name
    assert (out / "react.html").is_file()
    ans = json.loads((m / "answer.json").read_text())
    assert len(ans["decisions"]) == 2 and ans["assessment"].startswith("A noble house")
    flags = json.loads((m / "flags.json").read_text())
    assert any(f["kind"] == "name" and f["future"] for f in flags["reaction"])
    assert json.loads((m / "run.json").read_text())["reported"] == ["051.01", "051.02", "053.01"]


@pytest.mark.parametrize("raw,parsed,n", [
    (GOOD, True, 2),
    ("```json\n" + GOOD + "\n```", True, 2),
    ("Here you go: " + GOOD + " done", True, 2),
    ('{"reaction": "Hm.", "decisions": ["Wait."]}', True, 1),
    ('{"reaction": "Hm."}', True, 0),
    ("not json at all", False, 0),
    ('{"assessment": "no reaction"}', False, 0),
    ("[1, 2]", False, 0),
])
def test_parse_reaction(raw, parsed, n):
    got, ok = react.parse_reaction(raw)
    assert ok is parsed and len(got.decisions) == n
    if not parsed:
        assert got.reaction == raw.strip()


def test_a_reply_that_is_not_json_is_kept_raw(camp, tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "play", lambda a, s, u: "He frowns and says nothing.")
    rc, out = _react(camp, tmp_path)
    assert rc == 0
    b = json.loads((out / "m1" / "bundle.json").read_text())
    assert b["parsed"] is False and b["reaction"] == "He frowns and says nothing." and b["decisions"] == []


def test_answer_is_reused_for_the_same_prompt(camp, tmp_path, fake):
    assert _react(camp, tmp_path)[0] == 0 and len(fake) == 1
    assert _react(camp, tmp_path)[0] == 0 and len(fake) == 1
    assert _react(camp, tmp_path, "--force")[0] == 0 and len(fake) == 2
    assert _react(camp, tmp_path, "--dry-run")[0] == 0 and len(fake) == 2
    assert _react(camp, tmp_path, "--model", "other-model")[0] == 0 and len(fake) == 3


def test_dry_run_writes_prompts_and_no_page(camp, tmp_path, fake):
    rc, out = _react(camp, tmp_path, "--dry-run")
    assert rc == 0 and not fake
    assert (out / "m1" / "prompt.user.md").is_file() and not (out / "m1" / "answer.raw.md").exists()
    assert not (out / "react.html").exists()


def test_refuses_an_output_inside_the_sources(camp, tmp_path, fake, capsys):
    rc, _ = _react(camp, tmp_path, out="camp/summaries/x")
    assert rc == 2 and "never writes into its sources" in capsys.readouterr().err


def test_the_page_embeds_data_safely_and_loads_nothing_but_fonts(camp, tmp_path, fake):
    rc, out = _react(camp, tmp_path)
    html = (out / "react.html").read_text()
    template = react_page.TEMPLATE.read_text()
    assert html.count("</script") == template.count("</script")  # the canon's </script> is escaped
    assert "<\\/script><b>x<\\/b>" in html
    assert "CANON-ONLY-MARKER" in html
    assert "<title>Reactions</title>" in html
    urls = set(re.findall(r"https?://[^/\"')\s]+", html))
    assert urls <= {"https://fonts.googleapis.com", "https://fonts.gstatic.com"}
    assert "Your canon (answer key)" in html and "Matches your canon?" in html and "In character?" in html
    assert '"react/"' in html or "react/" in html
    data = re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</")
    d = json.loads(data)
    assert d["version"] == react_page.BUNDLE_VERSION and d["moments"][0]["moment"] == "m1"


def test_the_page_is_rebuilt_from_every_moment(camp, tmp_path, fake):
    _react(camp, tmp_path)
    pf, pj = _prep(tmp_path)
    raw = json.loads(pj.read_text())
    raw["targets"]["m2"] = raw["targets"]["m1"]
    pj.write_text(json.dumps(raw))
    cli.main(["react", "--campaign-dir", str(camp), "--subject", "Vizeran DeVir", "--form", "Vizeran", "--moment", "m2",
              "--question", "Again?", "--freeze", "53", "--reported", "051.01", "--via", "x", "--prep", str(pf),
              "--section", "Vizeran prep", "--prep-rulings", str(pj), "--out-dir", str(tmp_path / "out")])
    html = (tmp_path / "out" / "react.html").read_text()
    assert '"moment":"m1"' in html and '"moment":"m2"' in html


def test_react_modules_are_no_model_and_agent_is_the_only_model_step():
    import test_npc_agent_no_llm as guard
    assert guard.MODEL_STEPS == {"agent"}
    names = {n for n, _ in guard._modules()}
    assert {"react", "react_page"} <= names
