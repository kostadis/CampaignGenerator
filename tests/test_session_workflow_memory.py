import pytest

from session_doc.workflow.engine import binding
from session_doc.workflow.memory import memory_plan
from session_doc.workflow.models import Approval, Check, Run
from session_doc.workflow.storage import WorkflowError, now
from test_session_workflow_review import engine, GEN, mutate


def test_explicit_notes_persist_and_empty_chapters_refuse(engine):
    (engine.campaign / "docs").mkdir()
    (engine.campaign / "docs/chapter_01.md").write_text("# Chapter 1")
    (engine.campaign / "note.md").write_text("An unresolved lead")
    mutate(engine, "memory-scope", chapters=["docs/chapter_01.md"], notes=["note.md"])
    assert engine.store.load().notes_selected == ["note.md"]
    plan = memory_plan(engine)
    assert plan["notes"] == ["note.md"]
    assert plan["event_spine"]["selected_corpus"] == []
    assert plan["chapters"][0]["lineage"]["kind"] == "chapter"
    mutate(engine, "memory-scope", chapters=["docs/chapter_01.md"], notes=[])
    assert memory_plan(engine)["notes"] == []
    with pytest.raises(WorkflowError, match="nonempty"):
        mutate(engine, "memory-scope", chapters=[], notes=[])
    (engine.campaign / "docs/chapter_01.md").write_text("new chapter")
    assert memory_plan(engine)["stale_selection"]


def memory_draft(engine):
    # A test fixture isolates publication from the independently tested upstream gates.
    (engine.campaign / "docs").mkdir(exist_ok=True)
    (engine.campaign / "docs/world_state.md").write_text("previous approved state")
    (engine.store.session / "memory.md").write_text("reviewed updated state")
    evidence = engine.store.preserve("memory.md", label="generated")
    run = Run(id="memory-fixture", stage="memory", selection=["chapter-1"], inputs=[engine.store.preserve("source.md", label="source")], generation=GEN, outputs=[evidence], status="generated", started_at=now())
    state = engine.store.load(); state.runs.append(run)
    engine.store.save(state, expected_revision=state.revision)
    return run


def test_promotion_requires_scoped_human_approval_and_is_idempotent(engine):
    run = memory_draft(engine)
    mutate(engine, "promotion-scope", run_id=run.id, promotions={"memory.md": "docs/world_state.md"})
    with pytest.raises(WorkflowError, match="human draft approval"):
        mutate(engine, "promote", run_id=run.id)
    run = engine.store.load().runs[0]
    mutate(engine, "approve", run_id=run.id, actor="fixture human", rationale="reviewed exact draft and target", draft_binding=binding(run))
    mutate(engine, "promote", run_id=run.id)
    state = engine.store.load()
    assert (engine.campaign / "docs/world_state.md").read_text() == "reviewed updated state"
    mutate(engine, "promote", run_id=run.id)
    assert engine.store.load().revision == state.revision
    assert any(p.read_bytes() == b"previous approved state" for p in (engine.store.archive / "objects").iterdir())


def test_promotion_refuses_changed_target_and_outside_docs(engine):
    run = memory_draft(engine)
    with pytest.raises(WorkflowError, match="promotion targets"):
        mutate(engine, "promotion-scope", run_id=run.id, promotions={"memory.md": "../live.md"})
    mutate(engine, "promotion-scope", run_id=run.id, promotions={"memory.md": "docs/world_state.md"})
    run = engine.store.load().runs[0]
    mutate(engine, "approve", run_id=run.id, actor="fixture human", rationale="read draft", draft_binding=binding(run))
    (engine.campaign / "docs/world_state.md").write_text("new human edit")
    with pytest.raises(WorkflowError, match="target changed"):
        mutate(engine, "promote", run_id=run.id)
    assert (engine.campaign / "docs/world_state.md").read_text() == "new human edit"
