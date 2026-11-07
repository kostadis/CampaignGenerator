"""T041: one deterministic disposition per subject (N1, FR-011)."""

from __future__ import annotations

import pytest
import yaml

from _delta_us2 import copy_fixture, make_plan
from pipelines.summary_native.delta import census as cs


@pytest.fixture
def env(tmp_path):
    root = copy_fixture(tmp_path)
    return root, make_plan(root)


def _disp(env):
    return cs.build_census(*env).by_subject()


def test_fixture_dispositions(env):
    d = _disp(env)
    assert d["Brannoc Ironvein"].disposition == "changed"
    assert d["Envoy Sella Marr"].disposition == "mentioned_unchanged"
    assert d["Tobin Fenwick"].disposition == "new"
    assert d["Old Marrow Pike"].disposition == "unresolved"
    assert d["Old Marrow Pike"].needs_review and d["Old Marrow Pike"].evidence
    assert all(e.evidence for e in d.values() if e.disposition in ("changed", "new"))


def test_player_characters_are_never_subjects(env):
    c = cs.build_census(*env)
    assert "Ruck Halloway" not in c.by_subject() and "Sister Ines" not in c.by_subject()
    assert c.skipped_player_characters == ["Ruck Halloway", "Sister Ines"]


def test_one_entry_per_subject(env):
    names = [e.subject for e in cs.build_census(*env).entries]
    assert len(names) == len(set(names))


def test_unregistered_vs_deliberate_exclusion_are_distinct(env):
    root, plan = env
    r = root / cs.RULINGS_REL
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(yaml.safe_dump({"excluded": {"Old Marrow Pike": "a messenger, not an NPC"}}), encoding="utf-8")
    e = cs.build_census(root, plan).by_subject()["Old Marrow Pike"]
    assert e.disposition == "excluded" and e.ruling == "rulings.excluded" and not e.needs_review


def test_deferred_and_absent(env):
    root, plan = env
    r = root / cs.RULINGS_REL
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(yaml.safe_dump({"deferred": {"Tobin Fenwick": "wait"}}), encoding="utf-8")
    c = cs.build_census(root, plan).by_subject()
    assert c["Tobin Fenwick"].disposition == "deferred"
    # a second selection with only the baseline chapters: Tobin is not present
    plan2 = make_plan(root, ("001-the-cold-forge.md",))
    assert cs.build_census(root, plan2).by_subject()["Tobin Fenwick"].disposition in ("absent_from_selected", "deferred")


def test_absent_from_selected(env):
    root, _ = env
    plan = make_plan(root, ("001-the-cold-forge.md",))
    d = cs.build_census(root, plan).by_subject()
    assert d["Tobin Fenwick"].disposition == "absent_from_selected"


def test_indirect_reference_flagged_not_presence(env):
    root, plan = env
    (root / "docs/summaries/003-the-new-fire.md").write_text(
        (root / "docs/summaries/003-the-new-fire.md").read_text(encoding="utf-8")
        .replace("Envoy Sella Marr mentioned", "The envoy mentioned"), encoding="utf-8")
    plan = make_plan(root)
    r = root / cs.RULINGS_REL
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text(yaml.safe_dump({"indirect_references": {"Envoy Sella Marr": ["the envoy"]}}), encoding="utf-8")
    e = cs.build_census(root, plan).by_subject()["Envoy Sella Marr"]
    assert e.disposition == "absent_from_selected" and e.needs_review
    assert any(r.startswith("indirect_reference") for r in e.reasons)


def test_census_makes_no_model_call(env, monkeypatch):
    import campaignlib

    def boom(*a, **k):
        raise AssertionError("model call in census")

    monkeypatch.setattr(campaignlib, "call_api", boom)
    monkeypatch.setattr(campaignlib, "stream_api", boom)
    monkeypatch.setattr(campaignlib, "make_client", boom)
    cs.build_census(*env)


def test_triage_hints_never_assign_disposition(env):
    c = cs.build_census(*env)
    before = c.model_dump()
    hints = cs.propose_triage_hints(c, caller=lambda client, s, u, m: "likely a messenger, noise")
    assert [h["name"] for h in hints] == ["Old Marrow Pike"]
    assert c.model_dump() == before


def test_save_and_load_roundtrip(env):
    root, plan = env
    c, path = cs.run_census(root, plan)
    assert path.is_file() and cs.load_census(root, plan.plan_id) == c
