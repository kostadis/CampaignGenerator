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


def test_standalone_review_import_requires_exact_explicit_bindings(engine):
    run = check(engine, draft(engine), True)
    export = engine.export(run.id)
    doc = {"schemaVersion": 1, "reviewId": "old-page", "decisions": {"old-1": "discuss", "old-2": "pending"}}
    mapping = {"legacy_id": "old-1", "legacy_decision": "discuss", "finding_id": "f1", "finding_sha256": export["findings"][0]["finding_sha256"], "decision": "discuss"}
    mutate(engine, "import-legacy", run_id=run.id, draft_binding=binding(run), document=doc, bindings=[mapping], actor="fixture human", rationale="Validated against current source")
    assert engine.status()["runs"][0]["unresolved_findings"] == ["f1"]
    current = engine.store.load().runs[0]
    assert current.approval is None
    mapping.update(legacy_id="old-2", legacy_decision="pending", decision="approve")
    with pytest.raises(WorkflowError, match="unmarked"):
        mutate(engine, "import-legacy", run_id=run.id, draft_binding=binding(current), document=doc, bindings=[mapping], actor="fixture human", rationale="Cannot import pending")


@pytest.mark.parametrize("target_kind", ["managed", "original", "internal"])
def test_transcript_application_versions_only_managed_derived_outputs(engine, target_kind):
    mutate(engine, "start", stage="capture", selection=["scene-1"], inputs=["source.md"], generation=GEN, dependencies=[], required_checks=[])
    run = engine.store.load().runs[-1]
    path = {"managed": f".session-workflow/work/{run.id}/outputs/transcript.derived.vtt", "original": "source.vtt", "internal": ".session-workflow/private.vtt"}[target_kind]
    target = engine.store.session / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nGM: garbled and mistaken.\n")
    original = target.read_bytes()
    mutate(engine, "submit", run_id=run.id, outputs=[path], generation=GEN)
    run = engine.store.load().runs[-1]
    evidence = run.outputs[0].model_dump()
    findings = [{"id": fid, "evidence": evidence, "location": "cue 1", "description": "Spelling", "proposed_action": "Correct this derived cue", "consequences": {"approve": "Apply", "reject": "Retain", "discuss": "Unresolved"}, "change": {"source": evidence, "target": path, "before": before, "after": after}} for fid, before, after in [("f1", "garbled", "correct"), ("f2", "mistaken", "verified")]]
    mutate(engine, "check", run_id=run.id, check={"name": "capture-integrity", "status": "complete", "sources": [evidence], "findings": findings, "producer": "fixture", "at": now()})
    mutate(engine, "decide", run_id=run.id, decisions=[{"finding_id": f["id"], "finding_sha256": f["finding_sha256"], "decision": "approve", "actor": "GM", "rationale": "Reviewed", "at": now()} for f in engine.export(run.id)["findings"]])
    if target_kind != "managed":
        with pytest.raises(WorkflowError, match="originals cannot"):
            mutate(engine, "apply", run_id=run.id, finding_ids=["f1", "f2"])
        assert target.read_bytes() == original
        return
    mutate(engine, "apply", run_id=run.id, finding_ids=["f1", "f2"])
    state = engine.store.load()
    revised = state.runs[-1]
    assert revised.outputs[0].path == f".session-workflow/work/{revised.id}/outputs/transcript.derived.vtt"
    assert engine.store.bytes(revised.outputs[0]) == original.replace(b"garbled", b"correct").replace(b"mistaken", b"verified")
    assert target.read_bytes() == engine.store.bytes(run.outputs[0]) == original
    assert revised.approval is None and revised.checks == []
    assert engine.status()["runs"][0]["stale_reasons"] == []
    mutate(engine, "apply", run_id=run.id, finding_ids=["f2", "f1"])
    assert engine.store.load().revision == state.revision
    check(engine, revised)
    assert engine.status()["runs"][-1]["status"] == "generated"
    from session_doc.workflow.execution import resume
    pending = resume(engine)["pending"]
    assert [item["run_id"] for item in pending] == [revised.id]
    assert pending[0]["next_action"] == "explicit human draft approval"


def test_single_user_decisions_and_approval_need_no_identity_or_reason(engine):
    run = check(engine, draft(engine), True)
    finding = engine.export(run.id)["findings"][0]
    for decision in ["discuss", "reject"]:
        mutate(engine, "decide", run_id=run.id, decisions=[{
            "finding_id": finding["id"], "finding_sha256": finding["finding_sha256"],
            "decision": decision, "at": now(),
        }])
        saved = engine.store.load().runs[-1]
        assert saved.decisions[-1].actor == "local user"
        assert saved.decisions[-1].rationale
        assert saved.approval is None
        if decision == "discuss":
            with pytest.raises(WorkflowError, match="unresolved"):
                mutate(engine, "approve", run_id=run.id, draft_binding=binding(saved))
    mutate(engine, "approve", run_id=run.id, draft_binding=binding(saved))
    approved = engine.store.load().runs[-1]
    assert approved.approval.actor == "local user"
    assert approved.approval.rationale == "Approved this draft."
    assert approved.decisions[0].decision == "discuss"
    assert engine.status()["runs"][-1]["status"] == "approved"
