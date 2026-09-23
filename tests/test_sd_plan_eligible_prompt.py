"""The plan prompt carries per-scene candidates, not bare scene titles.

`sd_plan` built its checklist as `### <scene name>` lines and threw away the
extraction bodies `load_scene_extractions()` had already returned — so the model
chose a first-person narrator for "The Dead Drop at the House of a Thousand
Faces" from the title, a party document, and an instruction to rotate. Given
that evidence, picking the character who could never have afforded the tavern is
a *reasonable* inference. The model was not wrong; it was under-informed.

These tests pin the evidence that reaches it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import session_doc.sd_plan as sd_plan  # noqa: E402
from tests.helpers.eligibility_session import write_session  # noqa: E402

PLAN = (
    "## Scene 1\nnarrator: Vukradin\nchunks: 1\nscene: Rumors\nfocus: f\n"
    "## Scene 2\nnarrator: Soma\nchunks: 1\nscene: Stakeout\nfocus: f\n"
    "## Scene 3\nnarrator: Vukradin\nchunks: 1\nscene: Sewers\nfocus: f\n"
    "## Scene 4\nnarrator: Soma\nchunks: 1\nscene: Denvar\nfocus: f\n"
    "## Scene 5\nnarrator: Valphine Sotorra\nchunks: 1\nscene: Dead Drop\nfocus: f\n"
)


def _run(tmp_path, monkeypatch, plan_text=PLAN):
    scene_dir, vtt, players = write_session(tmp_path)
    out = tmp_path / "plan.md"
    seen = {}

    def fake_stream(client, system, user, model, **kw):
        seen["system"] = system
        seen["user"] = user
        return plan_text

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "stream_api", fake_stream)
    monkeypatch.setattr(
        sys, "argv",
        [
            "sd_plan.py",
            "--scene-extractions", str(scene_dir),
            "--characters", "Vukradin, Valphine Sotorra, Soma, Brewbarry",
            "--vtt", str(vtt),
            "--players-config", str(players),
            "--out", str(out),
        ],
    )
    sd_plan.main()
    return seen, out


def test_prompt_names_the_eligible_narrators_per_scene(tmp_path, monkeypatch):
    seen, _out = _run(tmp_path, monkeypatch)
    user = seen["user"]
    assert "The Dead Drop at the House of a Thousand Faces" in user
    # The scene's candidates ride with the scene, not just its title.
    dead_drop = user.split("The Dead Drop at the House of a Thousand Faces", 1)[1]
    first_block = dead_drop.split("###", 1)[0]
    assert "Vukradin" in first_block
    assert "Soma" in first_block


def test_an_absent_players_character_is_never_offered(tmp_path, monkeypatch):
    """Brewbarry must not appear as a candidate for any scene."""
    seen, _out = _run(tmp_path, monkeypatch)
    checklist = seen["user"].split("Session Scenes", 1)[1]
    assert "Brewbarry" not in checklist


def test_scene_three_offers_exactly_two_names(tmp_path, monkeypatch):
    """Valphine says nothing in scene 3; Soma's two lines still count (SC-003)."""
    seen, _out = _run(tmp_path, monkeypatch)
    body = seen["user"].split("Encounter in the Sewers", 1)[1].split("###", 1)[0]
    assert "Vukradin" in body and "Soma" in body
    assert "Valphine" not in body


def test_plan_is_written(tmp_path, monkeypatch):
    _seen, out = _run(tmp_path, monkeypatch)
    assert out.exists() and "narrator: Vukradin" in out.read_text(encoding="utf-8")


def test_a_narrator_outside_the_candidates_is_refused(tmp_path, monkeypatch, capsys):
    """FR-006: the plan may not assign a narrator who was not in the scene."""
    bad = PLAN.replace(
        "## Scene 3\nnarrator: Vukradin", "## Scene 3\nnarrator: Valphine Sotorra"
    )
    try:
        _seen, out = _run(tmp_path, monkeypatch, plan_text=bad)
    except SystemExit as exc:
        assert exc.code != 0
        err = capsys.readouterr().err
        assert "Valphine Sotorra" in err
        assert "Encounter in the Sewers" in err
        return
    raise AssertionError("an ineligible narrator must be refused, not written")


def test_pov_line_survives_plan_parsing(tmp_path, monkeypatch):
    """T019: `parse_plan` is line-oriented and ignores keys it does not know,
    so adding `pov:` to the output format needs no parser change. Asserted
    rather than assumed."""
    from session_doc.io import parse_plan
    text = (
        "## Scene 1\nnarrator: Vukradin\nchunks: 1\nscene: Rumors\n"
        "pov: present throughout; 89 labelled turns\nfocus: f\n"
    )
    sections = parse_plan(text, 1)
    assert sections[0]["narrator"] == "Vukradin"
    assert sections[0]["focus"] == "f"
