from pathlib import Path
import pytest
from pydantic import ValidationError
from session_doc.workflow.models import Workflow, Finding
from session_doc.workflow.storage import Store, WorkflowError, digest


def initialized(tmp_path):
    store = Store(tmp_path)
    with store.lock():
        store.save(Workflow(session_id="session", config="config.yaml"), expected_revision=0)
    return store


def test_worktree_import():
    import campaignlib
    assert Path(campaignlib.__file__).resolve().parents[1] == Path(__file__).resolve().parents[1]


def test_strict_contract_and_explicit_consequences():
    with pytest.raises(ValidationError):
        Workflow(session_id="s", config="c", assumed_approved=True)
    with pytest.raises(ValidationError):
        Finding(id="f", evidence={}, location="line 1", description="d", proposed_action="a", consequences={})


def test_snapshots_preserve_exact_bytes_and_detect_corruption(tmp_path):
    store = initialized(tmp_path)
    source = tmp_path / "tape.vtt"
    source.write_bytes(b"\xff\r\nquoted  words\r\n")
    evidence = store.preserve(source, label="source")
    source.write_bytes(b"changed")
    assert store.bytes(evidence) == b"\xff\r\nquoted  words\r\n"
    assert not store.fresh(evidence)
    store.contained(evidence.snapshot).write_bytes(b"corrupt")
    with pytest.raises(WorkflowError, match="hash mismatch"):
        store.bytes(evidence)


def test_revision_and_read_do_not_mutate(tmp_path):
    store = initialized(tmp_path)
    before = store.path.read_bytes()
    state = store.load()
    assert before == store.path.read_bytes()
    with pytest.raises(WorkflowError, match="stale"):
        store.save(state, expected_revision=0)


def test_replacement_failure_is_recoverable(tmp_path, monkeypatch):
    from session_doc.workflow import storage
    store = initialized(tmp_path)
    target = tmp_path / "narration.md"
    target.write_bytes(b"approved old version\r\n")
    before = store.preserve(target, label="generated")
    after = store.preserve_bytes(b"new draft", path="narration.md", label="generated")
    original_write = storage.atomic_write_bytes
    def fail_target(path, data):
        if Path(path) == target:
            raise OSError("injected interrupted replacement")
        original_write(path, data)
    monkeypatch.setattr(storage, "atomic_write_bytes", fail_target)
    with pytest.raises(OSError, match="interrupted"):
        store.publish(store.load(), {"narration.md": after}, expected_revision=1)
    assert target.read_bytes() == store.bytes(before)
    with pytest.raises(WorkflowError, match="interrupted"):
        store.save(store.load(), expected_revision=1)
    monkeypatch.setattr(storage, "atomic_write_bytes", original_write)
    assert store.recover()["recovered"]
    assert target.read_bytes() == b"new draft"
    assert store.bytes(before) == b"approved old version\r\n"
    assert store.recover() == {"recovered": False}


def test_recovery_refuses_external_change(tmp_path, monkeypatch):
    store = initialized(tmp_path)
    target = tmp_path / "out.md"
    target.write_text("old")
    after = store.preserve_bytes(b"new", path="out.md", label="generated")
    with monkeypatch.context() as m:
        m.setattr(store, "recover", lambda: None)
        store.publish(store.load(), {"out.md": after}, expected_revision=1)
    target.write_text("human edit")
    with pytest.raises(WorkflowError, match="source mismatch"):
        store.recover()
    assert target.read_text() == "human edit"


def test_path_escape_and_retired_state(tmp_path):
    store = initialized(tmp_path)
    with pytest.raises(WorkflowError, match="session-relative"):
        store.contained("../live/narration.md")
    store.path.write_text("schema_version: 0\nunknown: preserve me\n")
    before = store.path.read_bytes()
    with pytest.raises(WorkflowError, match="migrate.*--dry-run"):
        store.load()
    assert store.path.read_bytes() == before
