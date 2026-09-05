import json
from pathlib import Path

import pytest

from session_doc.workflow.engine import Engine, binding
from session_doc.workflow.storage import WorkflowError, fingerprint, now
from session_doc.workflow.migrate import migrate


GEN = {"backend": "native-agent", "model": "test-model", "producer": "fixture"}


@pytest.fixture
def engine(tmp_path):
    (tmp_path / "config.yaml").write_text("{}")
    (tmp_path / "session").mkdir()
    (tmp_path / "session" / "source.md").write_text("source")
    engine = Engine(tmp_path / "session", tmp_path)
    engine.initialize(str(tmp_path / "config.yaml"))
    return engine


def mutate(engine, op, **payload):
    return engine.mutate(op, payload, engine.store.load().revision)


def draft(engine):
    mutate(engine, "start", stage="capture", selection=["scene-1"], inputs=["source.md"], generation=GEN, dependencies=[], required_checks=["capture-integrity"])
    run = engine.store.load().runs[-1]
    (engine.store.session / "draft.md").write_text("A garbled name.")
    mutate(engine, "submit", run_id=run.id, outputs=["draft.md"], generation=GEN)
    return engine.store.load().runs[-1]


def check(engine, run, with_finding=False):
    e = run.outputs[0].model_dump()
    finding = {"id": "f1", "evidence": e, "location": "line 1", "description": "Misspelling", "proposed_action": "correct derived text", "consequences": {"approve": "Apply the correction after selection", "reject": "Retain original spelling", "discuss": "Keep unresolved"}, "change": {"source": e, "target": "draft.md", "before": "garbled", "after": "correct"}}
    mutate(engine, "check", run_id=run.id, check={"name": "capture-integrity", "status": "complete", "sources": [e], "findings": [finding] if with_finding else [], "producer": "fixture", "at": now()})
    return engine.store.load().runs[-1]


def test_clean_audit_never_approves_draft(engine):
    run = check(engine, draft(engine))
    assert engine.status()["runs"][0]["status"] == "generated"
    with pytest.raises(WorkflowError, match="human draft approval"):
        mutate(engine, "start", stage="prepare", selection=["1"], inputs=["draft.md"], generation=GEN, dependencies=[run.id], required_checks=[])
    mutate(engine, "approve", run_id=run.id, actor="GM", rationale="Read this draft", draft_binding=binding(run))
    assert engine.status()["runs"][0]["status"] == "approved"


def test_decisions_survive_reload_and_import_is_bound(engine):
    run = check(engine, draft(engine), True)
    exported = engine.export(run.id)
    d = {"finding_id": "f1", "finding_sha256": exported["findings"][0]["finding_sha256"], "decision": "discuss", "actor": "GM", "rationale": "Need source clarification", "at": now(), "group": "names"}
    exported["decisions"] = [d]
    mutate(engine, "import", document=exported)
    reloaded = Engine(engine.store.session, engine.campaign)
    assert reloaded.store.load().runs[0].decisions[0].group == "names"
    assert reloaded.status()["runs"][0]["unresolved_findings"] == ["f1"]
    with pytest.raises(WorkflowError, match="stale imported"):
        mutate(engine, "import", document=exported)


def test_approved_application_is_idempotent_and_creates_unapproved_derivative(engine):
    run = check(engine, draft(engine), True)
    f = engine.export(run.id)["findings"][0]
    mutate(engine, "decide", run_id=run.id, decisions=[{"finding_id": "f1", "finding_sha256": f["finding_sha256"], "decision": "approve", "actor": "GM", "rationale": "Checked source", "at": now()}])
    mutate(engine, "apply", run_id=run.id, finding_ids=["f1"])
    state = engine.store.load()
    assert state.runs[-1].approval is None
    assert state.runs[-1].outputs[0].label == "derived"
    assert state.runs[-1].checks == []
    assert engine.store.bytes(run.outputs[0]) == b"A garbled name."
    assert (engine.store.session / "draft.md").read_text() == "A correct name."
    mutate(engine, "apply", run_id=run.id, finding_ids=["f1"])
    assert engine.store.load().revision == state.revision


def test_stale_source_and_unmarked_findings_refuse_approval(engine):
    run = check(engine, draft(engine), True)
    with pytest.raises(WorkflowError, match="unresolved"):
        mutate(engine, "approve", run_id=run.id, actor="GM", rationale="reviewed", draft_binding=binding(run))
    (engine.store.session / "source.md").write_text("changed")
    with pytest.raises(WorkflowError, match="stale run"):
        mutate(engine, "decide", run_id=run.id, decisions=[])
    assert engine.status()["runs"][0]["status"] == "stale"


def test_check_coverage_and_empty_selection(engine):
    run = draft(engine)
    with pytest.raises(WorkflowError, match="coverage"):
        mutate(engine, "check", run_id=run.id, check={"name": "capture-integrity", "status": "complete", "sources": [], "producer": "x", "at": now()})
    with pytest.raises(WorkflowError, match="nonempty"):
        mutate(engine, "apply", run_id=run.id, finding_ids=[])


def test_migration_dry_run_preserves_every_file(engine):
    engine.store.path.unlink()
    (engine.store.session / "old.reviewed").write_text("legacy marker")
    (engine.store.session / "review.html").write_text("old page")
    before = {str(p): p.read_bytes() for p in engine.campaign.rglob("*") if p.is_file()}
    report = migrate(engine.campaign, "session", "config.yaml", dry_run=True)
    assert "review.html" in report["files"]
    assert before == {str(p): p.read_bytes() for p in engine.campaign.rglob("*") if p.is_file()}
    migrate(engine.campaign, "session", "config.yaml", artifacts=["review.html", "old.reviewed"])
    state = engine.store.load()
    assert state.runs == []
    assert not state.events[0]["approval_imported"]


def test_unknown_legacy_fields_are_reported_and_refused(engine):
    engine.store.path.write_text("schema_version: 0\nsecret_field: preserve\n")
    report = migrate(engine.campaign, "session", "config.yaml", dry_run=True)
    assert report["unknown_fields"] == ["secret_field"]
    with pytest.raises(WorkflowError, match="unsupported legacy"):
        migrate(engine.campaign, "session", "config.yaml", artifacts=["source.md"], force=True)
    assert "secret_field" in engine.store.path.read_text()


def test_cli_and_router_request_parity():
    from server.routers.session_workflow import WorkflowRequest, _build_workflow_cmd
    from session_doc.workflow.cli import OPERATIONS, build_parser
    for op in OPERATIONS:
        request = WorkflowRequest(operation=op, session_dir="summaries/001", config="config/config.yaml", expected_revision=7, payload={"selection": ["x"]})
        command = _build_workflow_cmd(request)
        parsed = build_parser().parse_args(command[1:])
        assert parsed.operation == op
        assert parsed.expected_revision == 7
        assert parsed.config == request.config
        assert json.loads(parsed.request_json) == request.payload
