"""T024: the delta lineage record vs the complete-bundle gate (spec 039 FR-016, R6, R8)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipelines.summary_native.delta.lineage import (
    BaselineRef, CustodyRef, DeltaLineageRecord, LineageMember, custody_dependencies, delta_record_complete,
    delta_record_problems,
)
from pipelines.summary_native.promotion import gates, manifest
from pipelines.summary_native.promotion.errors import PromotionPathError
from pipelines.summary_native.promotion.models import StrictPromotionModel

SHA = "a" * 64


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _record(campaign: Path, *, inherit_ok=True, produced_status="passed", extra=()) -> dict:
    rel = "docs/summaries/ch001-002/world_state.md"
    path = campaign / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"baseline world state\n")
    digest = _sha(b"baseline world state\n")
    members = [
        LineageMember(name="world_state", mode="inherited", sha256=digest if inherit_ok else SHA,
                      custody_ref=CustodyRef(path=rel, sha256=digest)),
        LineageMember(name="party", mode="produced", sha256=SHA, check_ref="checks/party.json",
                      check_status=produced_status),
        *extra,
    ]
    return DeltaLineageRecord(plan_ref="plan-1", baseline=BaselineRef(generation_id="g1", manifest_sha256=SHA),
                              members=members).model_dump(mode="json")


def test_complete_when_inherited_with_custody_and_produced_checked(tmp_path):
    record = _record(tmp_path)
    assert delta_record_complete(record, tmp_path)
    assert gates.record_complete(record, tmp_path)


def test_produced_without_passing_check_is_incomplete(tmp_path):
    record = _record(tmp_path, produced_status="failed")
    problems = delta_record_problems(record, tmp_path)
    assert any("party" in p and "failed" in p for p in problems)
    assert not gates.record_complete(record, tmp_path)


def test_inherited_digest_mismatch_and_changed_bytes_are_incomplete(tmp_path):
    assert not delta_record_complete(_record(tmp_path, inherit_ok=False), tmp_path)
    record = _record(tmp_path)
    (tmp_path / "docs/summaries/ch001-002/world_state.md").write_bytes(b"edited\n")
    assert any("changed" in p for p in delta_record_problems(record, tmp_path))


def test_inherited_without_custody_and_produced_without_check_ref(tmp_path):
    bad = [
        LineageMember(name="planning", mode="inherited", sha256=SHA),
        LineageMember(name="campaign_state", mode="produced", sha256=SHA, check_status="passed"),
    ]
    problems = delta_record_problems(_record(tmp_path, extra=bad), tmp_path)
    assert any("planning" in p and "custody" in p for p in problems)
    assert any("campaign_state" in p and "check reference" in p for p in problems)


def test_optional_member_does_not_block(tmp_path):
    opt = [LineageMember(name="extra", mode="produced", sha256=SHA, required=False)]
    assert delta_record_complete(_record(tmp_path, extra=opt), tmp_path)


def test_synth_record_complete_unchanged():
    assert gates.synth_record_complete({"step": "synth", "check": "passed"})
    assert gates.synth_record_complete({"step": "synth", "check": {"complete": True, "problems": []}})
    assert not gates.synth_record_complete({"step": "synth", "check": {"complete": False}})
    assert not gates.synth_record_complete({"step": "other"})
    assert gates.record_complete({"step": "synth", "check": "passed"})
    assert not gates.record_complete({"step": "synth", "check": "not run"})
    # a delta-shaped record is never judged by the synth rule
    assert not gates.synth_record_complete({"kind": "delta"})


def test_manifest_reads_delta_record_by_pointer(tmp_path):
    root = tmp_path
    record = _record(root)
    state = root / "docs/summaries/ch001-003/state"
    (state / "runs").mkdir(parents=True)
    (state / "runs/delta.json").write_text(json.dumps(record))
    draft = state / "world_state.draft.md"
    draft.write_text("range: ch001-003\nrecord: runs/delta.json | end\n")
    identity, deps = manifest._record_and_dependencies(root, draft, state)
    assert identity.path.endswith("runs/delta.json")
    assert [d.path for d in deps] == ["docs/summaries/ch001-002/world_state.md"]
    assert custody_dependencies(record)[0][0] == deps[0].path
    (root / "docs/summaries/ch001-002/world_state.md").write_bytes(b"changed\n")
    with pytest.raises(PromotionPathError, match="stale"):
        manifest._record_and_dependencies(root, draft, state)


def test_no_strict_model_gained_a_delta_field():
    assert issubclass(DeltaLineageRecord, object) and not issubclass(DeltaLineageRecord, StrictPromotionModel)
    assert not issubclass(DeltaLineageRecord, gates._GateModel)
    for cls in (StrictPromotionModel, gates._GateModel):
        assert not any("delta" in f or "lineage" in f for f in cls.model_fields)
