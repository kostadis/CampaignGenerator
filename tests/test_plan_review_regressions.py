"""One test per defect found reviewing the #385 commit (371ba43).

Every one of these passed review only because the original tests exercised the
path being built and not the paths around it. They are grouped by finding so a
regression names the thing it broke.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from campaignlib.players_config import (  # noqa: E402
    Player,
    PlayersConfig,
    absent_characters,
    attendance_is_establishable,
    undetermined_characters,
)
from campaignlib.vtt import speaker_labels  # noqa: E402
from campaignlib.players_config import norm_name  # noqa: E402
from session_doc.plan_eligibility import scene_presence  # noqa: E402
from session_doc.plan_alternates import (  # noqa: E402
    ALTERNATE_KEYS,
    parse_treatments,
    plan_preamble,
)
import session_doc.sd_plan as sd_plan  # noqa: E402
from tests.helpers.eligibility_session import write_session  # noqa: E402

PLAN_5 = "".join(
    f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n\n"
    for i in range(1, 6)
)


def _argv(scene_dir, out, vtt, players, *extra):
    return [
        "sd_plan.py",
        "--scene-extractions", str(scene_dir),
        "--characters", "Vukradin, Valphine Sotorra, Soma, Brewbarry",
        "--vtt", str(vtt), "--players-config", str(players),
        "--out", str(out), *extra,
    ]


def _run(tmp_path, monkeypatch, responses, **kw):
    scene_dir, vtt, players = write_session(tmp_path, **kw)
    out = tmp_path / "narration" / "plan.md"
    queue = list(responses)
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(sd_plan, "stream_api",
                        lambda *a, **k: queue.pop(0))
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    sd_plan.main()
    return out


# ── F1: `--choose` never reached its own branch ─────────────────────────────

def test_choose_runs_without_scene_extractions_or_characters(tmp_path, monkeypatch, capsys):
    """The command every doc, router message and UI note prints is bare
    `sd_plan --choose b`. Both other flags were `required=True`, so argparse
    exited 2 first and the CLI escape hatch did not exist."""
    out = tmp_path / "plan.md"
    (tmp_path / "plan.b.md").write_text("## Scene 1\nnarrator: Soma\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["sd_plan.py", "--out", str(out), "--choose", "b"])
    sd_plan.main()
    assert out.read_text(encoding="utf-8") == "## Scene 1\nnarrator: Soma\n"


def test_a_planning_run_still_requires_both_flags(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sd_plan.py", "--out", str(tmp_path / "p.md")])
    with pytest.raises(SystemExit) as exc:
        sd_plan.main()
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "--scene-extractions" in err and "--characters" in err


# ── F2: a stale plan.md defeated the gate ───────────────────────────────────

def test_uncoverable_run_removes_a_superseded_plan_md(tmp_path, monkeypatch):
    """Re-planning after a scene loses its last PC label must not leave the
    previous plan.md standing — the missing file IS the gate, and Pass 5 would
    otherwise narrate the assignment this run was re-run to remove."""
    scene_dir, vtt, players = write_session(tmp_path, uncoverable=True)
    out = tmp_path / "narration" / "plan.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("## Scene 1\nnarrator: Brewbarry\nchunks: 1\nscene: stale\n",
                   encoding="utf-8")

    plan6 = "".join(
        f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n\n"
        for i in range(1, 7)
    )
    queue = [plan6, _TREATMENTS]
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(sd_plan, "stream_api", lambda *a, **k: queue.pop(0))
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    sd_plan.main()

    assert not out.exists(), "the superseded plan.md must be gone"
    assert (out.parent / "plan.a.md").exists()


def test_a_coverable_run_removes_stale_alternates(tmp_path, monkeypatch):
    """Otherwise last run's treatments resurface as this run's pending choice."""
    scene_dir, vtt, players = write_session(tmp_path)
    out = tmp_path / "narration" / "plan.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    for key in ALTERNATE_KEYS:
        (out.parent / f"plan.{key}.md").write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(sd_plan, "stream_api", lambda *a, **k: PLAN_5)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    sd_plan.main()
    assert out.exists()
    assert not list(out.parent.glob("plan.?.md"))


# ── F3: a dropped block shifted every later scene ───────────────────────────

def test_a_plan_missing_a_scene_is_refused(tmp_path, monkeypatch, capsys):
    """`parse_plan` drops a block with no `narrator:`/`chunks:`. Positional
    alignment is load-bearing in three places, so a count mismatch is fatal
    rather than silently narrated against the wrong entry."""
    short = "".join(
        f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n\n"
        for i in range(1, 5)
    )
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, monkeypatch, [short])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "4 scene(s)" in err and "5" in err


def test_the_prompt_asks_for_narrator_none_not_an_omitted_field():
    """The prompt used to invite exactly the unparseable block above."""
    text = (ROOT / "config/agents/session_doc/plan.md").read_text(encoding="utf-8")
    assert "`narrator: NONE`" in text
    assert "is dropped when the plan is parsed" in text


# ── F4: the roster was still offered under "Available narrators" ────────────

def test_available_narrators_lists_the_pool_not_the_roster(tmp_path, monkeypatch):
    seen = {}

    def fake(client, system, user, model, **kw):
        seen["user"] = user
        return PLAN_5

    scene_dir, vtt, players = write_session(tmp_path)
    out = tmp_path / "narration" / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(sd_plan, "stream_api", fake)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    sd_plan.main()

    header = seen["user"].split("Available narrators", 1)[1].split("##", 1)[0]
    assert "Brewbarry" not in header
    for present in ("Vukradin", "Soma", "Valphine Sotorra"):
        assert present in header


def test_brewbarry_appears_nowhere_in_the_whole_prompt(tmp_path, monkeypatch):
    """The original test split on "Session Scenes" first, so it asserted his
    absence from the checklist while he sat in the header above it."""
    seen = {}
    scene_dir, vtt, players = write_session(tmp_path)
    out = tmp_path / "narration" / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(
        sd_plan, "stream_api",
        lambda c, s, u, m, **k: (seen.__setitem__("user", u), PLAN_5)[1])
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    sd_plan.main()
    assert "Brewbarry" not in seen["user"]


# ── F5: every character marked unvoiced on a real campaign ──────────────────

def test_an_empty_players_yaml_marks_nobody_absent():
    """Hillsfar's config/players.yaml is literally `players: []`."""
    cfg = PlayersConfig(players=[])
    roster = ["Ayla", "Bram"]
    labels = speaker_labels("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nAnn: hi\n")
    assert absent_characters(cfg, roster, labels) == set()
    assert undetermined_characters(cfg, roster) == {"Ayla", "Bram"}
    assert attendance_is_establishable(cfg) is False


def test_a_player_with_no_display_names_is_undetermined():
    cfg = PlayersConfig(players=[Player(id="a", name="Ann", plays=["Ayla"])])
    labels = speaker_labels("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nAnn: hi\n")
    assert absent_characters(cfg, ["Ayla"], labels) == set()


def test_sd_plan_refuses_when_attendance_is_unknowable(tmp_path, monkeypatch, capsys):
    """Refuse, rather than conclude that everybody was absent."""
    scene_dir, vtt, players = write_session(tmp_path)
    players.write_text("players: []\n", encoding="utf-8")
    out = tmp_path / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(
        sd_plan, "stream_api",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no API")))
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    with pytest.raises(SystemExit) as exc:
        sd_plan.main()
    assert exc.value.code != 0
    assert "no display names" in capsys.readouterr().err
    assert not out.exists()


# ── F6: two label rules could disagree ──────────────────────────────────────

def test_counts_and_presence_come_from_one_rule():
    """An indented label was counted by the old `_count_lines` and rejected by
    the presence scan, so a GM could read twelve turns for a character the
    eligibility set had excluded.

    Since #453 the invariant is structural — presence is the key set of the
    counts, from one reading — but it is asserted rather than assumed, because
    a second parse is exactly how it broke the first time."""
    canonical = {norm_name(n): n for n in ("Vukradin", "Soma")}
    moments = '  **Vukradin** — *indented*\n> "hi"\n**Soma**\n> "there"\n'
    counts, _ = scene_presence(moments, canonical)
    assert set(counts) == {"Soma"}
    assert counts == {"Soma": 1}


# ── F7: NPC labels buried the notice that matters ───────────────────────────

def test_npc_labels_do_not_bury_a_mis_normalised_pc(tmp_path, monkeypatch, capsys):
    scene_dir, vtt, players = write_session(tmp_path)
    target = scene_dir / "03_encounter_in_the_sewers.md"
    body = target.read_text(encoding="utf-8").replace("**Vukradin**", "**Vukradin (David)**", 1)
    body += '\n**Toblen Stonehill**\n> "Evening."\n\n**Sildar**\n> "Quiet."\n'
    target.write_text(body, encoding="utf-8")
    out = tmp_path / "narration" / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **k: object())
    monkeypatch.setattr(sd_plan, "stream_api", lambda *a, **k: PLAN_5)
    monkeypatch.setattr(sys, "argv", _argv(scene_dir, out, vtt, players))
    try:
        sd_plan.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out
    assert "Vukradin (David)" in printed
    assert "Toblen Stonehill" not in printed
    assert "further non-roster label" in printed


# ── F8: the alternates path dropped a preamble ──────────────────────────────

def test_plan_preamble_is_preserved():
    text = "# Session 46\n\n## Scene 1\nnarrator: Soma\nchunks: 1\n"
    assert plan_preamble(text) == "# Session 46\n\n"
    assert plan_preamble("## Scene 1\nnarrator: Soma\n") == ""


# ── F9: two scenes sharing a name collapsed into one ────────────────────────

def test_duplicate_scene_names_stay_separate(tmp_path):
    from campaignlib.players_config import load_players_config
    from session_doc.io import load_scene_extractions
    from session_doc.plan_eligibility import compute_eligibility

    scene_dir, vtt, players = write_session(tmp_path)
    for stem in ("01_rumors_and_preparations", "02_the_sewer_stakeout"):
        f = scene_dir / f"{stem}.md"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                f.read_text(encoding="utf-8").split("scene: ", 1)[1].split("\n", 1)[0],
                "Back at the Common Chord", 1),
            encoding="utf-8")
    e = compute_eligibility(
        scenes=load_scene_extractions(scene_dir), roster=["Vukradin", "Soma"],
        players=load_players_config(players),
        vtt_text=vtt.read_text(encoding="utf-8"))
    names = [s.name for s in e.scenes]
    assert names.count("Back at the Common Chord") == 2
    assert len(e.scenes) == 5


# ── F10: a case variant was fatal, not a warning ────────────────────────────

def test_a_case_variant_narrator_is_not_a_fatal_error(tmp_path, monkeypatch):
    lowered = PLAN_5.replace("narrator: Vukradin", "narrator: vukradin")
    out = _run(tmp_path, monkeypatch, [lowered])
    assert out.exists(), "a case variant folds, as norm_name does everywhere else"


# ── F11: a treatment could produce an unparseable block ─────────────────────

def test_a_treatment_without_chunks_is_rejected():
    bad = _TREATMENTS.replace("chunks: 6\nscene: Three Days on the Road\ntreatment: ensemble",
                              "scene: Three Days on the Road\ntreatment: ensemble", 1)
    assert len(parse_treatments(bad)) == 2, "the malformed one is dropped, not written"


def test_a_short_treatment_set_refuses(tmp_path, monkeypatch, capsys):
    plan6 = "".join(
        f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n\n"
        for i in range(1, 7)
    )
    bad = _TREATMENTS.replace("chunks: 6\nscene: Three Days on the Road\ntreatment: ensemble",
                              "scene: Three Days on the Road\ntreatment: ensemble", 1)
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, monkeypatch, [plan6, bad], uncoverable=True)
    assert exc.value.code != 0
    assert "expected 3 treatments" in capsys.readouterr().err


_TREATMENTS = """## Treatment A
label: fold into the dead drop
rationale: nobody speaks on the road
narrator: Vukradin
chunks: 6
scene: Three Days on the Road
treatment: absorbed-into "The Dead Drop"
pov: carried inside the scene he does narrate
focus: the road as the gap between two investigations

## Treatment B
label: ensemble register
rationale: keeps the scene, drops the single pair of eyes
narrator: Soma
chunks: 6
scene: Three Days on the Road
treatment: ensemble
pov: the party observed as a group
focus: three days measured in what nobody said

## Treatment C
label: second-hand from Soma
rationale: a voice, at the cost of admitting she is reporting
narrator: Soma
chunks: 6
scene: Three Days on the Road
treatment: second-hand
pov: recounted afterwards, at a remove
focus: the road as she was later told it went
"""
