"""A scene nobody can narrate becomes the GM's choice, not the planner's guess.

The alternates are *constructed*, not sampled: three independent planner runs on
the session behind #385 produced a byte-identical narrator distribution while
rewording every title, so re-running diversifies nothing. One call plans the
coverable scenes, a second proposes three treatments, and the files are
assembled deterministically — which is also what makes them comparable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import session_doc.sd_plan as sd_plan  # noqa: E402
from session_doc.plan_alternates import (  # noqa: E402
    ALTERNATE_KEYS,
    assemble_alternates,
    parse_treatments,
    split_plan_blocks,
)
from tests.helpers.eligibility_session import write_session  # noqa: E402

BASE_PLAN = "".join(
    f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f{i}\n\n"
    for i in range(1, 7)
)

TREATMENTS = """## Treatment A
label: fold into the dead drop
rationale: nobody speaks on the road; the beat belongs to the scene before it
narrator: Vukradin
chunks: 6
scene: Three Days on the Road
treatment: absorbed-into "The Dead Drop"
pov: carried inside the scene he does narrate
focus: the road as the gap between two investigations

## Treatment B
label: ensemble register
rationale: keeps the scene but drops the single pair of eyes it never had
narrator: Soma
chunks: 6
scene: Three Days on the Road
treatment: ensemble
pov: the party observed as a group rather than through one character
focus: three days measured in what nobody said

## Treatment C
label: second-hand from Soma
rationale: gives it a voice at the cost of admitting she is reporting, not seeing
narrator: Soma
chunks: 6
scene: Three Days on the Road
treatment: second-hand
pov: recounted afterwards, explicitly at a remove
focus: the road as she was later told it went
"""


def _run(tmp_path, monkeypatch, *, uncoverable, plan=BASE_PLAN):
    scene_dir, vtt, players = write_session(tmp_path, uncoverable=uncoverable)
    out = tmp_path / "narration" / "plan.md"
    responses = [plan, TREATMENTS]

    def fake_stream(client, system, user, model, **kw):
        return responses.pop(0)

    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(sd_plan, "stream_api", fake_stream)
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
    sd_plan.main()
    return out


# ── T026: inert on an ordinary session ──────────────────────────────────────

def test_no_uncoverable_scene_writes_exactly_one_plan(tmp_path, monkeypatch):
    plan = "".join(
        f"## Scene {i}\nnarrator: Vukradin\nchunks: 1\nscene: S{i}\nfocus: f\n\n"
        for i in range(1, 6)
    )
    out = _run(tmp_path, monkeypatch, uncoverable=False, plan=plan)
    assert out.exists()
    assert not list(out.parent.glob("plan.?.md")), "no choice should be requested"


# ── T025: the three plans ───────────────────────────────────────────────────

def test_uncoverable_scene_writes_three_plans_and_no_plan_md(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    assert not out.exists(), "the missing plan.md IS the gate"
    for key in ALTERNATE_KEYS:
        assert (out.parent / f"plan.{key}.md").exists()


def test_the_three_differ_only_in_the_disputed_scene(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    texts = {k: (out.parent / f"plan.{k}.md").read_text(encoding="utf-8")
             for k in ALTERNATE_KEYS}
    bodies = {k: [b for _h, b in split_plan_blocks(v)] for k, v in texts.items()}
    # Scenes 1-5 are settled and identical across all three.
    for i in range(5):
        assert bodies["a"][i] == bodies["b"][i] == bodies["c"][i]
    # Scene 6 is the disputed one and differs in all three.
    assert len({bodies["a"][5], bodies["b"][5], bodies["c"][5]}) == 3


def test_each_plan_says_what_was_disputed_and_how_it_answers(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    for key, label in zip(ALTERNATE_KEYS,
                          ["fold into the dead drop", "ensemble register",
                           "second-hand from Soma"]):
        text = (out.parent / f"plan.{key}.md").read_text(encoding="utf-8")
        assert "Three Days on the Road" in text
        assert label in text
        assert "no honest" in text or "no player character speaks" in text


def test_treatments_are_materially_different(tmp_path, monkeypatch):
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    kinds = set()
    for key in ALTERNATE_KEYS:
        text = (out.parent / f"plan.{key}.md").read_text(encoding="utf-8")
        for kind in ("absorbed-into", "ensemble", "second-hand"):
            if f"treatment: {kind}" in text:
                kinds.add(kind)
    assert kinds == {"absorbed-into", "ensemble", "second-hand"}


# ── T029: choosing ──────────────────────────────────────────────────────────

def test_choose_writes_the_pick_to_plan_md(tmp_path, monkeypatch, capsys):
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    expected = (out.parent / "plan.b.md").read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["sd_plan.py", "--scene-extractions", str(tmp_path / "scene_extractions"),
         "--characters", "Vukradin", "--out", str(out), "--choose", "b"],
    )
    sd_plan.main()
    assert out.exists()
    assert out.read_text(encoding="utf-8") == expected
    # The alternates are spent once chosen. Left on disk they resurface as a
    # pending choice the next time plan.md is absent.
    assert not list(out.parent.glob("plan.?.md"))


def test_choose_is_equivalent_to_a_copy(tmp_path, monkeypatch):
    """Constitution IX: the GM can do this with `cp` and lose nothing."""
    out = _run(tmp_path, monkeypatch, uncoverable=True)
    expected = (out.parent / "plan.c.md").read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["sd_plan.py", "--scene-extractions", str(tmp_path / "scene_extractions"),
         "--characters", "Vukradin", "--out", str(out), "--choose", "c"],
    )
    sd_plan.main()
    assert out.read_text(encoding="utf-8") == expected


def test_choose_needs_no_tape_or_roster(tmp_path, monkeypatch):
    """Resolving a choice is a file copy, not a planning run."""
    out = _run(tmp_path, monkeypatch, uncoverable=True)

    def boom(*a, **kw):
        raise AssertionError("--choose must not reach the API")
    monkeypatch.setattr(sd_plan, "stream_api", boom)
    monkeypatch.setattr(
        sys, "argv",
        ["sd_plan.py", "--scene-extractions", str(tmp_path / "scene_extractions"),
         "--characters", "Vukradin", "--out", str(out), "--choose", "a"],
    )
    sd_plan.main()
    assert out.exists()


def test_choose_without_an_alternate_refuses(tmp_path, monkeypatch, capsys):
    out = tmp_path / "narration" / "plan.md"
    out.parent.mkdir(parents=True)
    monkeypatch.setattr(
        sys, "argv",
        ["sd_plan.py", "--scene-extractions", str(tmp_path),
         "--characters", "Vukradin", "--out", str(out), "--choose", "a"],
    )
    with pytest.raises(SystemExit) as exc:
        sd_plan.main()
    assert exc.value.code != 0
    assert "plan.a.md" in capsys.readouterr().err


# ── T027: every scene uncoverable ───────────────────────────────────────────

def test_every_scene_uncoverable_refuses(tmp_path, monkeypatch, capsys):
    scene_dir, vtt, players = write_session(tmp_path)
    for f in scene_dir.glob("*.md"):
        f.write_text(
            "---\nscene: Silent\n---\n\n## Verbatim moments\n\n"
            '**GM**\n> "Nothing is said."\n',
            encoding="utf-8",
        )
    out = tmp_path / "plan.md"
    monkeypatch.setattr(sd_plan, "client_from_args", lambda *a, **kw: object())
    monkeypatch.setattr(
        sd_plan, "stream_api",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not call API")),
    )
    monkeypatch.setattr(
        sys, "argv",
        ["sd_plan.py", "--scene-extractions", str(scene_dir),
         "--characters", "Vukradin, Soma", "--vtt", str(vtt),
         "--players-config", str(players), "--out", str(out)],
    )
    with pytest.raises(SystemExit) as exc:
        sd_plan.main()
    assert exc.value.code != 0
    assert "no scene" in capsys.readouterr().err.lower()
    assert not out.exists()


# ── the parser and assembler, directly ──────────────────────────────────────

def test_parse_treatments_strips_label_and_rationale_from_the_body():
    ts = parse_treatments(TREATMENTS)
    assert [t.label for t in ts] == [
        "fold into the dead drop", "ensemble register", "second-hand from Soma"]
    assert all("label:" not in t.body and "rationale:" not in t.body for t in ts)
    assert "narrator: Vukradin" in ts[0].body


def test_assemble_preserves_every_other_block_byte_for_byte():
    ts = parse_treatments(TREATMENTS)
    alts = assemble_alternates(BASE_PLAN, scene_indexes=[5], treatments=ts,
                               uncoverable_names=["Three Days on the Road"])
    base_bodies = [b for _h, b in split_plan_blocks(BASE_PLAN)]
    for key in ALTERNATE_KEYS:
        bodies = [b for _h, b in split_plan_blocks(alts[key])]
        assert bodies[:5] == base_bodies[:5]
