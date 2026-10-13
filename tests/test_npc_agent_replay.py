"""Prototype 4 (replay) and Prototype 5 (forward): synthetic scenes and a FAKE model only."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipelines.npc_agent import agent, cli, corpus, dossier, forward, prep, replay_page, turns

SYLVIRA = """<!-- published -->
---
subject: Sylvira Savikas
type: npc
global: true
aliases_used: [Sylvira, Sylvira Savikas]
first_seen: 61
last_seen: 65
chapters: [61, 64, 65]
n_entries: 1
n_scenes: 3
n_moments: 0
---

## History with the Party
- Daz interviews her [ch 061 / 061.01].
- Tea [ch 064 / 064.01].
- Later [ch 065 / 065.01].
"""

CH61 = """# Chapter 61

## Scenes

### Interview

#### Daz visits Sylvira.

- Sylvira denies drinking honey.

## NPCs

### Sylvira

Bedridden with a plague.
"""

CH64 = """# Chapter 64

## Summary

Sylvira served tea in the Vault.

## Scenes

### Tea with Sylvira

#### Sylvira receives Daz in the Vault.

- Sylvira pours the tea. She asks Daz to sit.
- Daz asks where the key is.
- Asked about the key, Sylvira shrugs. Instead, she offers a map.
- Daral demands the map. Sylvira refuses.
  > "No."
- Sylvira's hand shakes.
- Daz sips the tea. Sylvira says he must hurry.
- Wick leaves.
"""

CH65 = """# Chapter 65

## Summary

The party left the Vault.

## Scenes

### Later

#### Sylvira waits in her study.

- Sylvira locks the door and burns the map. Asha arrives.
"""

PREP = """# Prep

## SCENE B

Sylvira keeps the key in her sleeve.

The vault is trapped with a glyph.
"""

PLAN = """# Next session

## Plan

Sylvira will betray Daz to the Avowed.
"""


@pytest.fixture
def camp(tmp_path: Path) -> Path:
    c = tmp_path / "camp"
    (c / "summaries").mkdir(parents=True)
    (c / "npcs").mkdir()
    (c / "summaries" / "061-session-interview.md").write_text(CH61)
    (c / "summaries" / "064-session-tea.md").write_text(CH64)
    (c / "summaries" / "065-session-later.md").write_text(CH65)
    (c / "npcs" / "sylvira-savikas.md").write_text(SYLVIRA)
    return c


def _scene(camp, sid="064.01"):
    c = corpus.load_corpus(camp / "summaries")
    d = dossier.select(dossier.read_dossiers(camp / "npcs"), ["Sylvira"])[0]
    return next(i for i in c.items() if i.item_id == sid), d


def _rulings(tmp_path: Path, items=("064.01", "065.01")) -> Path:
    f = tmp_path / "r.yaml"
    f.write_text("version: 3\nnpcs:\n  Sylvira Savikas:\n    default: mentioned\n    items:\n"
                 + "".join(f'      "{i}": present\n' for i in items))
    return f


def _prep(tmp_path: Path, ruled: str = "all") -> tuple[Path, Path]:
    """``(prep.md, prep.json)`` in a directory of their own; ``ruled="some"`` leaves one passage unruled."""
    d = tmp_path / "private"
    d.mkdir(exist_ok=True)
    pf = d / "prep.md"
    pf.write_text(PREP)
    ps = prep.extract(PREP, ("Sylvira", "Sylvira Savikas"), "SCENE B", file=str(pf))
    passages = {ps[0].pid: "hers"} if ruled == "some" else {ps[0].pid: "hers", ps[1].pid: "gm"}
    pj = d / "prep.json"
    pj.write_text(json.dumps({"version": 1, "npc": "Sylvira Savikas", "targets": {
        "064.01": {"source": "prep.md", "section": "SCENE B", "passages": passages}}}))
    return pf, pj


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def play(args, system, user):
        calls.append((system, user))
        if "between sessions" in system:
            return '[{"move": "Sylvira burns the map.", "why": "It names the Vault."}, {"move": "She writes to Asha.", "why": "She trusts her."}]'
        return "Sylvira pours more tea. \"Sit,\" she says, and mentions Asha."

    monkeypatch.setattr(agent, "play", play)
    return calls


def _replay(camp, tmp_path, *extra, ruled="all", out="out"):
    pf, pj = _prep(tmp_path, ruled)
    argv = ["replay", "--campaign-dir", str(camp), "--npc", "Sylvira", "--rulings", str(_rulings(tmp_path)),
            "--target", "064.01", "--prep", str(pf), "--section", "SCENE B", "--prep-rulings", str(pj),
            "--out-dir", str(tmp_path / out), *extra]
    return cli.main(argv), tmp_path / out


def _forward(camp, tmp_path, *extra, out="out", plan=True):
    pf, pj = _prep(tmp_path)
    argv = ["forward", "--campaign-dir", str(camp), "--npc", "Sylvira", "--rulings", str(_rulings(tmp_path)),
            "--chapter", "64", "--next", "065.01", "--prep", str(pf), "--section", "SCENE B", "--prep-rulings", str(pj),
            "--prep-target", "064.01", "--out-dir", str(tmp_path / out), *extra]
    if plan:
        plf = tmp_path / "private" / "plan.md"
        plf.write_text(PLAN)
        argv += ["--plan", str(plf), "--plan-section", "Plan"]
    return cli.main(argv), tmp_path / out


# ── split_turns ─────────────────────────────────────────────────────────────


def test_a_scene_splits_into_turns_with_prompts_and_beats(camp):
    scene, d = _scene(camp)
    ts = turns.split_turns(scene, d)
    assert [t.prompt for t in ts] == [
        "", "Daz asks where the key is. Asked about the key, Instead,", "Daral demands the map.",
        "Daz sips the tea."]
    assert [t.actual for t in ts] == [
        "Sylvira pours the tea. She asks Daz to sit.", "Sylvira shrugs. She offers a map.",
        'Sylvira refuses.\n> "No." Sylvira\'s hand shakes.', "Sylvira says he must hurry."]
    assert [t.beat_ids for t in ts] == [("064.01.b02",), ("064.01.b04",), ("064.01.b05", "064.01.b06"), ("064.01.b07",)]


def test_her_possessive_and_a_subject_she_shares_are_hers(camp):
    _, d = _scene(camp)
    rx, about = turns._subject_rx(d), turns._about_her_rx(d)
    assert turns.hers("Her son was born in the Abyss.", rx, about) == ("", "Her son was born in the Abyss.")
    assert turns.hers("She and Janussi discussed a library.", rx, about)
    assert turns.hers("Daz and Sylvira talk.", rx, about) is None


def test_a_trailing_non_hers_sentence_is_not_a_turn(camp):
    scene, d = _scene(camp)
    assert "Wick leaves." not in " ".join(t.prompt + t.actual for t in turns.split_turns(scene, d))


def test_leading_clauses_and_subjects():
    d = dossier.Dossier("Sylvira Savikas", "s", Path("s.md"), ("Sylvira", "Sylvira Savikas"), (1,), 1, 1, 0, 0, 0, ())
    rx = turns._subject_rx(d)
    assert turns.hers("Instead, she explains the rule.", rx) == ("Instead,", "She explains the rule.")
    assert turns.hers("On reflection, however, she names Bookwyrm.", rx) == ("On reflection, however,", "She names Bookwyrm.")
    assert turns.hers("Regarding Kalan, Sylvira Savikas calls him insane.", rx)[0] == "Regarding Kalan,"
    assert turns.hers("When Daz presses for a name, Sylvira is startled.", rx)[0] == "When Daz presses for a name,"
    assert turns.hers("Sylvira initially welcomes the search.", rx) == ("", "Sylvira initially welcomes the search.")
    # not hers: someone else's subject, a possessive, a conjoined subject, a run-on that is not a leading clause
    for s in ("Daz asks whether Sylvira has a plan.", "Sylvira's hand shakes.", "She and Janussi instead talked.",
              "Daz shows her the list, Sylvira laughs.", "Her skin is pale.", "Sylvira"):
        assert turns.hers(s, rx) is None, s


def test_quote_lines_stay_with_the_sentence_before_them():
    assert turns._sentences('- Daz reads it:\n\n  > "Feed the quill."\n  > "Tread the steps."\n- Sylvira laughs.') == [
        'Daz reads it:\n> "Feed the quill."\n> "Tread the steps."', "Sylvira laughs."]
    assert turns._sentences("- Daz bows. Sylvira nods.\n  > “Yes.”") == ["Daz bows.", "Sylvira nods.\n> “Yes.”"]


# ── replay ──────────────────────────────────────────────────────────────────


def test_turns_only_prints_the_split_and_needs_nothing_else(camp, capsys, fake):
    rc = cli.main(["replay", "--campaign-dir", str(camp), "--npc", "Sylvira", "--target", "064.01", "--turns-only"])
    out = capsys.readouterr().out
    assert rc == 0 and not fake and "064.01: 4 turn(s)" in out and "(she acts first)" in out and "b04" in out


def test_each_turn_sees_earlier_real_answers_and_never_later_ones(camp, tmp_path, fake):
    rc, out = _replay(camp, tmp_path)
    assert rc == 0 and len(fake) == 4
    ts = turns.split_turns(*_scene(camp))
    users = [(out / "064.01" / "turns" / f"{n:02d}" / "prompt.user.md").read_text() for n in range(1, 5)]
    for k, user in enumerate(users):
        so_far = user.split("## So far in this scene")[1].split("## Now")[0]
        for j, t in enumerate(ts):
            assert (t.actual in so_far) == (j < k), (k, j)
        assert ts[k].actual not in user  # never the answer being asked for
        assert user.split("## Now")[1].strip() == (ts[k].prompt or "(Nothing is put to you: the moment is yours.)")
    assert "Sylvira pours the tea." in users[1] and "Sylvira says he must hurry." not in users[2]
    assert "## Your private knowledge\n\n### SCENE B\n\nSylvira keeps the key in her sleeve." in users[0]
    assert "glyph" not in "".join(users) and "40 to 150 words" in fake[0][0]
    # the order of the six sections
    heads = [h for h in re.findall(r"^## .*$", users[0], re.M) if h != "## Tea with Sylvira"]  # the situation's own heading
    assert heads == ["## Who you are", "## What you know", "## Your private knowledge", "## The scene",
                     "## So far in this scene", "## Now"]


def test_replay_writes_the_per_turn_files_and_leak_checks_against_the_whole_message(camp, tmp_path, fake):
    rc, out = _replay(camp, tmp_path)
    t = out / "064.01"
    assert (t / "prompt.system.md").is_file() and (t / "run.json").is_file()
    n2 = t / "turns" / "02"
    for name in ("prompt.user.md", "answer.md", "actual.md", "flags.json"):
        assert (n2 / name).is_file(), name
    assert (n2 / "actual.md").read_text() == "Sylvira shrugs. She offers a map.\n"
    flags = json.loads((n2 / "flags.json").read_text())
    assert [f["name"] for f in flags if f["kind"] == "name"] == ["Asha"]  # Daz and Daral are in what she was given
    run = json.loads((t / "run.json").read_text())
    assert run["freeze_chapter"] == 63 and set(run["turns"]) == {"01", "02", "03", "04"}
    page = (out / "replay.html").read_text()
    assert replay_page.DATA_SLOT not in page and "Same substance" in page


def test_replay_refuses_while_the_prep_is_unruled(camp, tmp_path, fake, capsys):
    rc, out = _replay(camp, tmp_path, ruled="some")
    assert rc == 2 and "not ruled yet" in capsys.readouterr().err and not fake and not out.exists()


def test_replay_refuses_a_target_she_did_not_attend(camp, tmp_path, fake, capsys):
    pf, pj = _prep(tmp_path)
    rc = cli.main(["replay", "--campaign-dir", str(camp), "--npc", "Sylvira", "--rulings", str(_rulings(tmp_path, ("065.01",))),
                   "--target", "064.01", "--prep", str(pf), "--prep-rulings", str(pj), "--out-dir", str(tmp_path / "o")])
    assert rc == 2 and "do not answer 'present'" in capsys.readouterr().err and not fake


def test_replay_reuses_answers_by_prompt_model_and_backend(camp, tmp_path, fake):
    _replay(camp, tmp_path)
    assert len(fake) == 4
    assert _replay(camp, tmp_path)[0] == 0 and len(fake) == 4
    assert _replay(camp, tmp_path, "--force")[0] == 0 and len(fake) == 8
    assert _replay(camp, tmp_path, "--model", "other-model")[0] == 0 and len(fake) == 12
    assert _replay(camp, tmp_path, "--dry-run")[0] == 0 and len(fake) == 12


def test_replay_dry_run_writes_prompts_and_no_answer_or_page(camp, tmp_path, fake):
    rc, out = _replay(camp, tmp_path, "--dry-run")
    assert rc == 0 and not fake
    assert (out / "064.01" / "turns" / "01" / "prompt.user.md").is_file()
    assert not (out / "064.01" / "turns" / "01" / "answer.md").exists() and not (out / "replay.html").exists()


def test_replay_refuses_to_write_into_the_private_prep_directory(camp, tmp_path, fake):
    pf, pj = _prep(tmp_path)
    rc = cli.main(["replay", "--campaign-dir", str(camp), "--npc", "Sylvira", "--rulings", str(_rulings(tmp_path)),
                   "--target", "064.01", "--prep", str(pf), "--prep-rulings", str(pj), "--out-dir", str(pf.parent / "x")])
    assert rc == 2 and not fake


# ── forward ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,moves,parsed", [
    ('[{"move": "A", "why": "b"}, {"move": "C", "why": "d"}]', [("A", "b"), ("C", "d")], True),
    ('Here you go:\n```json\n[{"move": "A", "why": "b"}]\n```', [("A", "b")], True),
    ('Sure. [{"move": "A"}] Done.', [("A", "")], True),
    ('{"move": "A", "why": "b"}', [("A", "b")], True),
    ('{"moves": [{"move": "A", "why": "b"}]}', [("A", "b")], True),
    ('["Just a string"]', [("Just a string", "")], True),
    ("She will burn the map because it is dangerous.", [("She will burn the map because it is dangerous.", "")], False),
    ('[{"why": "no move"}]', [('[{"why": "no move"}]', "")], False),
    ("[]", [("[]", "")], False),
    ('[{"move": "A", "why": ', [('[{"move": "A", "why":', "")], False),
])
def test_forward_replies_parse_leniently_and_never_lose_text(raw, moves, parsed):
    got, ok = forward.parse_moves(raw)
    assert ([(m.move, m.why) for m in got], ok) == (moves, parsed)


def test_forward_standing_is_the_chapters_prose_only_if_she_attended(camp):
    c = corpus.load_corpus(camp / "summaries")
    assert forward.standing(c, 64, True) == "Sylvira served tea in the Vault."
    assert forward.standing(c, 64, False) == ""


def test_forward_writes_moves_flags_comparison_and_plan(camp, tmp_path, fake):
    rc, out = _forward(camp, tmp_path)
    f = out / "forward-64"
    assert rc == 0 and len(fake) == 1
    moves = json.loads((f / "answer.json").read_text())
    assert [m["move"] for m in moves] == ["Sylvira burns the map.", "She writes to Asha."]
    flags = json.loads((f / "flags.json").read_text())
    assert [x["index"] for x in flags] == [0, 1]
    assert [g["name"] for g in flags[1]["flags"] if g["kind"] == "name"] == ["Asha"]
    assert "burns the map" in (f / "actual.md").read_text()
    assert "betray Daz" in (f / "plan.md").read_text() and "GM's plan" in (f / "plan.md").read_text()
    user = (f / "prompt.user.md").read_text()
    assert [h for h in re.findall(r"^## .*$", user, re.M)] == [
        "## Who you are", "## What you know", "## Your private knowledge", "## Where things stand"]
    assert "Sylvira served tea in the Vault." in user and "glyph" not in user
    assert json.loads((f / "run.json").read_text())["parsed"] is True
    page = (out / "replay.html").read_text()
    assert "betray Daz" in page and "burns the map" in page


def test_the_plan_never_reaches_any_prompt(camp, tmp_path, fake):
    rc, out = _forward(camp, tmp_path)
    assert rc == 0
    for p in out.rglob("prompt.*"):
        assert "betray" not in p.read_text() and "GM's plan" not in p.read_text(), p
    assert all("betray" not in s + u for s, u in fake)


def test_forward_keeps_a_raw_reply_that_is_not_json(camp, tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "play", lambda a, s, u: "She would simply wait.")
    rc, out = _forward(camp, tmp_path)
    assert rc == 0
    f = out / "forward-64"
    assert json.loads((f / "answer.json").read_text()) == [{"move": "She would simply wait.", "why": ""}]
    assert json.loads((f / "run.json").read_text())["parsed"] is False and "not valid JSON" in (out / "replay.html").read_text()


def test_forward_reuses_the_answer_for_the_same_prompt(camp, tmp_path, fake):
    _forward(camp, tmp_path)
    assert _forward(camp, tmp_path)[0] == 0 and len(fake) == 1
    assert _forward(camp, tmp_path, "--force")[0] == 0 and len(fake) == 2
    assert _forward(camp, tmp_path, "--dry-run")[0] == 0 and len(fake) == 2


def test_forward_without_a_plan_writes_no_plan_file(camp, tmp_path, fake):
    rc, out = _forward(camp, tmp_path, plan=False)
    assert rc == 0 and not (out / "forward-64" / "plan.md").exists()


def test_forward_refuses_a_next_scene_she_did_not_attend_or_that_is_not_after_the_freeze(camp, tmp_path, fake, capsys):
    pf, pj = _prep(tmp_path)
    base = ["forward", "--campaign-dir", str(camp), "--npc", "Sylvira", "--prep", str(pf), "--prep-rulings", str(pj),
            "--prep-target", "064.01", "--out-dir", str(tmp_path / "o")]
    assert cli.main([*base, "--rulings", str(_rulings(tmp_path, ("064.01",))), "--chapter", "64", "--next", "065.01"]) == 2
    assert "do not answer 'present'" in capsys.readouterr().err
    assert cli.main([*base, "--rulings", str(_rulings(tmp_path)), "--chapter", "65", "--next", "065.01"]) == 2
    assert "not after the freeze" in capsys.readouterr().err and not fake


def test_forward_refuses_while_the_prep_is_unruled(camp, tmp_path, fake, capsys, monkeypatch):
    pf, pj = _prep(tmp_path, "some")
    rc = cli.main(["forward", "--campaign-dir", str(camp), "--npc", "Sylvira", "--rulings", str(_rulings(tmp_path)),
                   "--chapter", "64", "--next", "065.01", "--prep", str(pf), "--section", "SCENE B", "--prep-rulings", str(pj),
                   "--prep-target", "064.01", "--out-dir", str(tmp_path / "o")])
    assert rc == 2 and "not ruled yet" in capsys.readouterr().err and not fake


# ── the page ────────────────────────────────────────────────────────────────


def test_replay_and_forward_share_one_page(camp, tmp_path, fake):
    _replay(camp, tmp_path)
    _forward(camp, tmp_path)
    page = (tmp_path / "out" / "replay.html").read_text()
    assert "Sylvira shrugs." in page and "burns the map" in page
    m = re.search(r"const DATA = (.*?);\n", page)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert [t["target"] for t in data["replay"]] == ["064.01"] and [f["freeze"] for f in data["forward"]] == [64]
    assert data["forward"][0]["sha"] and data["forward"][0]["doc_prefix"] == ""
    assert all(len(u["sha"]) == 64 for u in data["replay"][0]["turns"])


def test_replay_page_embeds_its_data_safely_loads_nothing_but_fonts_and_names_its_documents():
    b = {"version": 1, "npc": "S", "run_id": "r", "model": "m",
         "replay": [{"target": "064.01", "freeze": 63, "scene_title": "T", "situation": "x </script> y", "turns": [{
             "n": 1, "prompt": "</script><b>", "actual": "a", "answer": "b", "sha": "0" * 64, "beat_ids": ["064.01.b02"], "flags": []}]}],
         "forward": [{"freeze": 64, "next": "065.01", "next_title": "N", "actual": "</script>", "plan": "p", "sha": "1" * 64,
                      "parsed": True, "doc_prefix": "", "moves": [{"move": "m</script>", "why": "w", "flags": []}]}]}
    page = replay_page.render(b)
    assert replay_page.DATA_SLOT not in page and page.count("</script>") == 1
    assert set(re.findall(r"https?://([^/\"' ]+)", page)) <= {"fonts.googleapis.com", "fonts.gstatic.com"}
    assert "<title>Replay</title>" in page and "replay/" in page and "forward/" in page
    assert "Same substance" in page and "Approve" in page and "Your plan for her" in page and "What she actually did" in page
    assert "max-width: 700px" in page and "overflow-x" not in page.replace("overflow-x: hidden", "")


def test_the_scores_a_page_exports_keep_the_move_text_and_prompt_sha():
    page = (Path(replay_page.__file__).parent / "review" / "replay_review.html").read_text()
    for needle in ("prompt_sha256: f.sha", "move: m.move", "why: m.why", "verdict:", "scores.json"):
        assert needle in page
