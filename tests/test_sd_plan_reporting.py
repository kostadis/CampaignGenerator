"""Every exclusion is reported, before the model call.

The GM ruled that attendance is read from the tape with no override. That
knowingly gets one case wrong — a player covering an absent player's character
has their own label on those lines, so the covered character reads as absent —
and the only correction path is the GM editing the plan by hand. A wrong
exclusion nobody was told about is therefore unfixable, which makes this
reporting load-bearing rather than cosmetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import session_doc.sd_plan as sd_plan  # noqa: E402
from session_doc.plan_eligibility import ELIGIBILITY_RECORD  # noqa: E402
from tests.helpers.eligibility_session import write_session  # noqa: E402

PLAN = "".join(
    f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n"
    for i in range(1, 6)
)


def _run(tmp_path, monkeypatch, **kw):
    scene_dir, vtt, players = write_session(tmp_path, **kw)
    out = tmp_path / "narration" / "plan.md"
    order = []

    def fake_stream(client, system, user, model, **kwargs):
        order.append("api")
        return PLAN

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw2: object())
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
    return out


def test_absent_exclusion_names_character_player_and_tape(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "Brewbarry" in out
    assert "Stéphane Bourdeaud" in out
    assert "session.transcript.vtt" in out


def test_scene_exclusion_names_scene_and_the_eligible_set(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "Encounter in the Sewers" in out
    line = next(
        ln for ln in out.splitlines()
        if "Encounter in the Sewers" in ln and "eligible here" in ln
    )
    assert "Valphine Sotorra" in line          # who was excluded
    assert "Soma" in line and "Vukradin" in line  # who was eligible


def test_exclusions_print_before_the_api_call(tmp_path, monkeypatch, capsys):
    """Reporting after the spend is reporting too late."""
    _run(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert out.index("[eligibility]") < out.index("[sd_plan: Pass 3")


def test_record_is_written_beside_the_plan(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch)
    record = out.parent / ELIGIBILITY_RECORD
    assert record.exists()
    data = json.loads(record.read_text(encoding="utf-8"))
    assert sorted(data["pool"]) == ["Soma", "Valphine Sotorra", "Vukradin"]
    assert data["attendance"]["Stéphane Bourdeaud"]["present"] is False
    assert data["attendance"]["Wade Brown"]["matched_label"] == "Wade Brown"
    # A list, not a name-keyed object: two scenes may share a `scene:` value.
    sewers = next(s for s in data["scenes"] if s["name"] == "Encounter in the Sewers")
    assert sewers["eligible"] == ["Soma", "Vukradin"]
    assert sewers["index"] == 2
    assert any(x["character"] == "Brewbarry"
               for x in data["exclusions"]["absent_players"])


def test_line_counts_are_evidence_not_a_gate(tmp_path, monkeypatch):
    """Soma has one labelled turn in scene 3 and stays eligible (FR-009)."""
    out = _run(tmp_path, monkeypatch)
    data = json.loads((out.parent / ELIGIBILITY_RECORD).read_text(encoding="utf-8"))
    scene3 = next(s for s in data["scenes"] if s["name"] == "Encounter in the Sewers")
    assert scene3["line_counts"]["Soma"] < scene3["line_counts"]["Vukradin"]
    assert "Soma" in scene3["eligible"]


def test_unrecognised_label_is_surfaced(tmp_path, monkeypatch, capsys):
    """A label scene_extract failed to normalise costs a character their
    eligibility; it must not do so silently."""
    scene_dir, vtt, players = write_session(tmp_path)
    target = scene_dir / "03_encounter_in_the_sewers.md"
    target.write_text(
        target.read_text(encoding="utf-8").replace("**Vukradin**", "**Vukradin (David)**"),
        encoding="utf-8",
    )
    out = tmp_path / "narration" / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "stream_api", lambda *a, **kw: PLAN)
    monkeypatch.setattr(
        sys, "argv",
        [
            "sd_plan.py",
            "--scene-extractions", str(scene_dir),
            "--characters", "Vukradin, Valphine Sotorra, Soma, Brewbarry",
            "--vtt", str(vtt), "--players-config", str(players),
            "--out", str(out),
        ],
    )
    try:
        sd_plan.main()
    except SystemExit:
        pass
    printed = capsys.readouterr().out
    assert "Vukradin (David)" in printed
    # The wording changed when NPC labels were split out of this notice: dozens
    # of them per session were burying the one line the GM must read.
    assert "look like a roster character" in printed
