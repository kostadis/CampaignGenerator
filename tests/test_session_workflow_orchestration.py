from pathlib import Path
import pytest

from session_doc.workflow.engine import Engine, binding
from session_doc.workflow.context import narrator_selection, transcript_identity
from session_doc.workflow.execution import execute, resume
from session_doc.workflow.storage import WorkflowError, now
from session_doc.workflow.versions import historical_bytes, write_narration
from test_session_workflow_review import GEN, draft, check, mutate, engine


def test_mandatory_stage_dependencies_and_checks_cannot_be_omitted(engine):
    with pytest.raises(WorkflowError, match="missing approved stage"):
        mutate(engine, "start", stage="extract", selection=["1"], inputs=["source.md"], generation=GEN, dependencies=[], required_checks=[])
    mutate(engine, "start", stage="capture", selection=["1"], inputs=["source.md"], generation=GEN, dependencies=[], required_checks=[])
    assert engine.store.load().runs[0].required_checks == ["capture-integrity"]
    assert execute(engine, engine.store.load().runs[0].id, engine.store.load().revision)["pending_agent"]
    assert "native" in resume(engine)["pending"][0]["next_action"]


def test_resume_requires_human_after_zero_findings(engine):
    run = check(engine, draft(engine))
    assert resume(engine)["pending"][0]["next_action"] == "explicit human draft approval"
    mutate(engine, "approve", run_id=run.id, actor="fixture human", rationale="fixture reviewed", draft_binding=binding(run))
    assert resume(engine)["pending"] == []


def test_narrator_roster_and_explicit_subset(tmp_path):
    party = tmp_path / "party.yaml"
    party.write_text("characters:\n  - name: Alice\n    sheet: docs/alice.md\n  - name: Bob\n    sheet: docs/bob.md\n")
    assert narrator_selection(party, tmp_path, None)[1] == ["Alice", "Bob"]
    assert narrator_selection(party, tmp_path, ["Bob"])[1] == ["Bob"]
    with pytest.raises(WorkflowError, match="exactly match"):
        narrator_selection(party, tmp_path, ["Bbo"])
    with pytest.raises(WorkflowError, match="nonempty"):
        narrator_selection(party, tmp_path, [])


def test_cue_identity_keeps_player_and_character_separate():
    data = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nWade: I cast a spell.\n\n2\n00:00:03.000 --> 00:00:04.000\nUnknown: Hello.\n"
    players = [{"id": "wade", "display_names": ["Wade"], "plays": ["Alice", "Sidekick"]}]
    cues = transcript_identity(data, players)
    assert cues[0]["player_id"] == "wade"
    assert cues[0]["character"] is None
    assert cues[1]["player_id"] is None
    with pytest.raises(WorkflowError, match="duplicate cue"):
        transcript_identity(data + "\n1\n00:00:05.000 --> 00:00:06.000\nWade: Again\n", players)


def test_narration_versions_preserve_previous_metadata_and_bytes(tmp_path, monkeypatch):
    from session_doc.workflow import versions
    target = tmp_path / "scene.md"
    write_narration(target, "old\r\n", {"backend": "codex-cli", "model": "one"})
    from session_doc.workflow.storage import digest
    old_hash = digest(target.read_bytes())
    target.with_suffix(".knobs.json").write_text('{"effort":"high"}')
    write_narration(target, "new", {"backend": "claude-code", "model": "two"})
    assert historical_bytes(target, old_hash) == b"old\r\n"
    assert list((tmp_path / ".versions" / target.name).glob("*-knobs-*.json"))
    real = versions.atomic_write_bytes
    def fail(path, data):
        if path == target:
            raise OSError("interrupted")
        real(path, data)
    monkeypatch.setattr(versions, "atomic_write_bytes", fail)
    with pytest.raises(OSError):
        write_narration(target, "third", {"model": "three"})
    assert target.read_text() == "new"
    assert historical_bytes(target, old_hash) == b"old\r\n"
