import pytest

from pipelines.summary_native.delta.errors import DeltaRefusal
from pipelines.summary_native.delta.run import (
    Artifact, Member, RunState, RunStatus, StageStatus, finish_stage, load_run, save_run,
    start_stage)


def test_roundtrip_via_scheduler_records(tmp_path):
    s = RunState(run_id="r1", plan_ref="plan-x-r1")
    start_stage(s, "prepare", "abc")
    finish_stage(s, "prepare", ok=True, artifacts=[Artifact(path="a.json", sha256="0" * 64)])
    s.members.append(Member(subject="npc_a", outcome="published", receipt_ref="r.json"))
    s.counts.parsed_new = 2
    path = tmp_path / "run.json"
    save_run(s, path)
    back = load_run(path)
    assert back == s and back.schema_version == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_failed_stage_never_success(tmp_path):
    s = RunState(run_id="r", plan_ref="p")
    start_stage(s, "verify")
    finish_stage(s, "verify", ok=False, artifacts=[Artifact(path="x", sha256="0" * 64)])
    assert s.stages[0].status is StageStatus.failed
    assert s.stages[0].artifacts == [] and s.status is RunStatus.failed


def test_restart_clears_prior_artifacts_and_rejects_unknown(tmp_path):
    s = RunState(run_id="r", plan_ref="p")
    start_stage(s, "a")
    finish_stage(s, "a", ok=True, artifacts=[Artifact(path="x", sha256="0" * 64)])
    start_stage(s, "a", "d2")
    assert s.stages[0].artifacts == [] and s.stages[0].status is StageStatus.running
    with pytest.raises(KeyError):
        finish_stage(s, "missing", ok=True)
    with pytest.raises(ValueError):
        Member(subject="x", outcome="weird")


def test_unsupported_schema_refused(tmp_path):
    s = RunState(run_id="r", plan_ref="p", schema_version=9)
    path = tmp_path / "run.json"
    save_run(s, path)
    with pytest.raises(DeltaRefusal):
        load_run(path)
