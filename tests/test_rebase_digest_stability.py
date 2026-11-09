"""T005 / research R10: pre-feature plan and lineage digests are byte-identical after spec 040.

The expected hex values were computed from the code at HEAD ``fbb15dc`` (before ``kind``/``rebase_id`` and
the lineage ``rebase`` block existed).  Do not regenerate them to make a failure go away.
"""

from __future__ import annotations

import hashlib
import json

from pipelines.summary_native.delta import grounding_publish as gp, plan as dplan
from pipelines.summary_native.delta.lineage import (
    BaselineRef, CustodyRef, DeltaLineageRecord, LineageMember,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
MODEL = {"backend": "claude-code", "model": "m"}


def build() -> dict[str, str]:
    sources = (dplan.PlanSource(path="docs/summaries/006-x.md", sha256=SHA_A, chapter=6, kind="new"),)
    plan = dplan.DeltaPlan(
        plan_id=dplan._derive_plan_id("golden", ["grounding"], "apply", sources),
        campaign_identity="golden", products=("grounding",), stopping_point="apply", sources=sources,
        models=dplan.PlanModels(generation=MODEL, consistency=MODEL),
        grounding_baseline_ref="gen-1", npc_baselines={"alice": SHA_B}, census={},
        created_at="2026-01-01T00:00:00+00:00")
    lineage = DeltaLineageRecord(
        plan_ref=plan.plan_id, baseline=BaselineRef(generation_id="gen-1", manifest_sha256=SHA_A),
        members=[
            LineageMember(name="world_state", mode="produced", sha256=SHA_B, check_ref="c.json",
                          check_status="passed"),
            LineageMember(name="party", mode="inherited", sha256=SHA_A,
                          custody_ref=CustodyRef(path="docs/p.md", sha256=SHA_A)),
        ])
    return {
        "plan_id": plan.plan_id,
        "plan_digest": dplan.plan_digest(plan),
        "lineage_sha": hashlib.sha256(gp.lineage_bytes(lineage)).hexdigest(),
        "lineage_json": json.dumps(lineage.model_dump(mode="json"), sort_keys=True),
    }


GOLDEN = {
    "plan_id": "plan-9520ac98adb93bd4",
    "plan_digest": "fd9c497372f7291317ba663f6f8d3938f3f010578fa529ff87446a3e022046c4",
    "lineage_sha": "2a4590f6f9b44b90e3b6b922125803e552931c00d99488e651e29e352b142f06",
}


def _plan(**extra):
    sources = (dplan.PlanSource(path="a/006-x.md", sha256=SHA_A, chapter=6),)
    return dplan.DeltaPlan(plan_id="p", campaign_identity="g", products=("grounding",), stopping_point="plan",
                           sources=sources, models=dplan.PlanModels(generation=MODEL, consistency=MODEL),
                           created_at="t", **extra)


def test_pre_feature_digests_are_byte_identical():
    got = build()
    assert {k: got[k] for k in GOLDEN} == GOLDEN


def test_defaults_are_omitted_from_serialization():
    assert '"rebase"' not in build()["lineage_json"]
    plan = _plan()
    dumped = plan.model_dump(mode="json")
    assert "kind" not in dumped and "rebase_id" not in dumped
    assert plan.kind == "delta" and plan.rebase_id is None


def test_non_default_kind_changes_digest_and_round_trips():
    base, rebase = _plan(), _plan(kind="rebase", rebase_id="rb-1")
    assert dplan.plan_digest(base) != dplan.plan_digest(rebase)
    again = dplan.DeltaPlan.model_validate(rebase.model_dump(mode="json"))
    assert again.kind == "rebase" and again.rebase_id == "rb-1"
    assert dplan.revise(rebase).kind == "rebase"
