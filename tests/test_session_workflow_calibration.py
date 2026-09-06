"""Native review persists before generation without bypassing draft gates."""
from copy import deepcopy

import pytest

from session_doc.workflow.calibration import export
from session_doc.workflow.engine import Engine, binding
from session_doc.workflow.execution import resume
from session_doc.workflow.models import Generation, Run
from session_doc.workflow.storage import WorkflowError, now
from test_session_workflow_review import GEN, engine, mutate


@pytest.fixture
def calibration(engine):
    source = engine.store.session / "01.md"
    source.write_text("So, hello. Another, um, sentence.")
    second = engine.store.session / "02.md"
    second.write_text("Second scene.")
    voice = engine.store.session / "voice.md"
    voice.write_text("Speak plainly.")
    refs = [engine.store.preserve(p, label="source") for p in (source, second, voice)]
    state = engine.store.load()
    run = Run(id="native", stage="voice-smooth", selection=["01.md", "02.md"], inputs=refs, dependencies=[], required_checks=["voice-smooth"], generation=Generation.model_validate(GEN), status="pending_agent", started_at=now(), task={})
    state.runs.append(run)
    engine.store.save(state, expected_revision=state.revision)
    sample = engine.store.session / ".session-workflow/work/native/review/01.md"
    sample.parent.mkdir(parents=True)
    sample.write_text("Hello. Another sentence.")
    evidence = engine.store.preserve(sample, label="derived")
    report = {"title": "Voice smoothing calibration", "method": "A deterministic test example", "authorities": [refs[2].model_dump()], "cards": [
        {"id": "c1", "category": "Filler removal", "scene": "01", "speaker": "GM", "location": "Line 1", "source": refs[0].model_dump(), "sample": evidence.model_dump(), "before": "So, hello.", "after": "Hello.", "rationale": "Remove filler."},
        {"id": "c2", "category": "Filler removal", "scene": "01", "speaker": "GM", "location": "Line 1", "source": refs[0].model_dump(), "sample": evidence.model_dump(), "before": "Another, um, sentence.", "after": "Another sentence.", "rationale": "Remove hesitation."},
    ]}
    mutate(engine, "calibration-register", run_id=run.id, report=report)
    return engine, run.id, report


def decide(engine, run_id, verdict="approve", ids=None):
    current = export(engine, run_id)["calibration"]
    ids = ids if ids is not None else [c["id"] for c in current["cards"]]
    mutate(engine, "calibration-decide", run_id=run_id, decisions=[{"finding_id": c["id"], "finding_sha256": c["finding_sha256"], "decision": verdict} for c in current["cards"] if c["id"] in ids])


def approve(engine, run_id):
    mutate(engine, "calibration-approve", run_id=run_id, calibration_binding=export(engine, run_id)["calibration"]["binding"])


def test_calibration_is_not_generation_or_draft_approval(calibration):
    engine, run_id, _ = calibration
    assert "human calibration review" in resume(engine)["pending"][0]["next_action"]
    with pytest.raises(WorkflowError, match="unresolved"):
        approve(engine, run_id)
    decide(engine, run_id, ids=["c1"])
    decide(engine, run_id, "discuss", ["c2"])
    with pytest.raises(WorkflowError, match="unresolved"):
        approve(engine, run_id)
    reloaded = Engine(engine.store.session, engine.campaign)
    assert export(reloaded, run_id)["calibration"]["unresolved"] == ["c2"]
    decide(reloaded, run_id, "reject", ["c2"])
    approve(reloaded, run_id)
    run = reloaded.store.load().runs[0]
    assert run.status == "pending_agent" and run.outputs == [] and run.approval is None
    assert "continue native skill" in resume(reloaded)["pending"][0]["next_action"]
    with pytest.raises(WorkflowError, match="draft is not generated"):
        mutate(reloaded, "approve", run_id=run_id, draft_binding=binding(run))
    with pytest.raises(WorkflowError, match="every explicitly selected"):
        mutate(reloaded, "submit", run_id=run_id, outputs=["01.md"], generation=GEN)
    outputs = engine.store.session / "derived"
    outputs.mkdir()
    (outputs / "01.md").write_text("Hello. Another, um, sentence.")
    (outputs / "02.md").write_text("Second scene.")
    mutate(reloaded, "submit", run_id=run_id, outputs=["derived/01.md", "derived/02.md"], generation=GEN)
    run = reloaded.store.load().runs[0]
    assert run.status == "generated" and run.approval is None
    assert run.checks == []
    assert (engine.store.session / "01.md").read_text() == "So, hello. Another, um, sentence."


def test_changed_decision_invalidates_calibration(calibration):
    engine, run_id, _ = calibration
    decide(engine, run_id)
    approve(engine, run_id)
    decide(engine, run_id, "discuss", ["c1"])
    assert not export(engine, run_id)["calibration"]["approved"]
    with pytest.raises(WorkflowError, match="human calibration"):
        mutate(engine, "submit", run_id=run_id, outputs=["01.md", "02.md"], generation=GEN)


@pytest.mark.parametrize("target", ["01.md", "voice.md", ".session-workflow/work/native/review/01.md"])
def test_stale_evidence_refuses_saved_rulings(calibration, target):
    engine, run_id, _ = calibration
    decide(engine, run_id)
    (engine.store.session / target).write_text("Changed bytes")
    assert engine.status()["runs"][0]["status"] == "stale"
    with pytest.raises(WorkflowError, match="stale"):
        approve(engine, run_id)
    with pytest.raises(WorkflowError, match="stale"):
        decide(engine, run_id, "reject")


def test_import_preserves_notes_and_refuses_modified_evidence(calibration):
    engine, run_id, _ = calibration
    document = export(engine, run_id)
    card = document["calibration"]["cards"][0]
    document["calibration"]["decisions"] = [{"finding_id": card["id"], "finding_sha256": card["finding_sha256"], "decision": "discuss", "rationale": "Please keep this uncertain."}]
    bad = deepcopy(document)
    bad["calibration"]["report"]["cards"][0]["after"] = "Invented"
    with pytest.raises(WorkflowError, match="altered"):
        mutate(engine, "calibration-import", document=bad)
    mutate(engine, "calibration-import", document=document)
    assert export(engine, run_id)["calibration"]["decisions"][0]["rationale"] == "Please keep this uncertain."
    with pytest.raises(WorkflowError, match="stale"):
        mutate(engine, "calibration-import", document=document)


def test_register_refuses_scope_expansion_and_preserves_replaced_review(calibration):
    engine, run_id, report = calibration
    decide(engine, run_id)
    old = export(engine, run_id)["calibration"]
    bad = deepcopy(report)
    bad["cards"][0]["source"] = bad["authorities"][0]
    with pytest.raises(WorkflowError, match="explicitly selected"):
        mutate(engine, "calibration-register", run_id=run_id, report=bad, replaces_binding=old["binding"])
    assert export(engine, run_id)["calibration"] == old
    report["cards"][0]["rationale"] = "Updated explanation, requiring fresh review."
    mutate(engine, "calibration-register", run_id=run_id, report=report, replaces_binding=old["binding"])
    assert export(engine, run_id)["calibration"]["decisions"] == []
    assert engine.store.load().events[-2]["calibration"]["decisions"]


def test_stale_revision_and_card_hash_refused(calibration):
    engine, run_id, _ = calibration
    revision = engine.store.load().revision
    decide(engine, run_id)
    with pytest.raises(WorkflowError, match="stale workspace"):
        engine.mutate("calibration-decide", {"run_id": run_id, "decisions": []}, revision)
    with pytest.raises(WorkflowError, match="unknown calibration decision"):
        mutate(engine, "calibration-decide", run_id=run_id, decisions=[{"finding_id": "c1", "finding_sha256": "0" * 64, "decision": "approve"}])
