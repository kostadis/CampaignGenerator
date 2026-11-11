"""Approved generic-name support selects only its exact quote, never the whole scene."""
import json

import pytest
import yaml

from _delta_us2 import copy_fixture, make_plan
from pipelines.summary_native.delta import associations as asc, census as cs, npc_update
from pipelines.summary_native.delta.errors import DeltaRefusal

QUOTE = "Snarl catches fire and extinguishes it."


def setup_scoped(tmp_path):
    root = copy_fixture(tmp_path)
    reg = root / "docs/entity_registry.yaml"
    data = yaml.safe_load(reg.read_text())
    data["entities"].append({"name": "Snarl", "type": "npc"})
    reg.write_text(yaml.safe_dump(data))
    src = root / "docs/summaries/003-the-new-fire.md"
    src.write_text(src.read_text().replace("#### A stranger", QUOTE + "\n\nAn unrelated secret in the same scene.\n\n#### A stranger"))
    plan = make_plan(root)
    store = asc.propose(root, plan, [], client=object(), caller=lambda *a: json.dumps([
        {"name": "Snarl", "canonical_id": "Snarl", "scene": "003.02",
         "relationship_support": QUOTE, "scope": "extinguishes fire"}]))
    return root, plan, store.associations[0].id


@pytest.mark.parametrize("decision", [None, "reject", "discuss"])
def test_unapproved_generic_is_not_selected(tmp_path, decision):
    root, plan, aid = setup_scoped(tmp_path)
    if decision:
        asc.decide(root, plan.plan_id, aid, decision, "GM")
    census = cs.build_census(root, plan)
    assert "Snarl" not in [e.subject for e in npc_update.select_members(census)]


def test_approved_generic_selects_only_scoped_support(tmp_path):
    root, plan, aid = setup_scoped(tmp_path)
    reg_before = (root / "docs/entity_registry.yaml").read_bytes()
    asc.decide(root, plan.plan_id, aid, "approve", "GM")
    census = cs.build_census(root, plan)
    assert any(w["form"] == "snarl" for w in census.withheld_forms)
    members = npc_update.build_members(root, plan, census, ["Snarl"])
    assert len(members) == 1
    assert [(s.id, s.span) for s in members[0].spans] == [("003.02", QUOTE)]
    assert [a.id for a in members[0].assocs] == [aid]
    assert (root / "docs/entity_registry.yaml").read_bytes() == reg_before
    asc.decide(root, plan.plan_id, aid, "reject", "GM")
    with pytest.raises(DeltaRefusal, match="no longer approved"):
        npc_update.build_members(root, plan, census, ["Snarl"])


def test_stale_support_refuses(tmp_path):
    root, plan, aid = setup_scoped(tmp_path)
    asc.decide(root, plan.plan_id, aid, "approve", "GM")
    src = root / "docs/summaries/003-the-new-fire.md"
    src.write_text(src.read_text() + "\nchanged\n")
    with pytest.raises(DeltaRefusal, match="source changed"):
        cs.build_census(root, plan)


def test_deferred_ruling_still_wins(tmp_path):
    root, plan, aid = setup_scoped(tmp_path)
    asc.decide(root, plan.plan_id, aid, "approve", "GM")
    p = root / cs.RULINGS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"deferred": {"Snarl": "wait"}}))
    assert npc_update.build_members(root, plan, cs.build_census(root, plan), ["Snarl"]) == []


def test_approved_generic_entry_has_one_census_row(tmp_path):
    root, _, _ = setup_scoped(tmp_path)
    src = root / "docs/summaries/003-the-new-fire.md"
    src.write_text(src.read_text().replace("## Locations", "### Snarl\n\n" + QUOTE + "\n\n## Locations"))
    plan = make_plan(root)
    store = asc.propose(root, plan, [], client=object(), caller=lambda *a: json.dumps([
        {"name": "Snarl", "canonical_id": "Snarl", "scene": "entry",
         "relationship_support": QUOTE, "scope": "extinguishes fire"}]))
    asc.decide(root, plan.plan_id, store.associations[0].id, "approve", "GM")
    census = cs.build_census(root, plan)
    assert [e.disposition for e in census.entries if e.subject == "Snarl"] == ["new"]
    m, = npc_update.build_members(root, plan, census, ["Snarl"])
    assert [(s.id, s.span) for s in m.spans] == [("entry", QUOTE)]
