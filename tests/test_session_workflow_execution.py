import argparse
import importlib
from pathlib import Path
import sys
import pytest
from session_doc.workflow.execution import build_command
from session_doc.workflow.models import Run
from session_doc.workflow.storage import now
from test_session_workflow_review import engine


def test_partial_narration_uses_existing_resolver_and_boolean_flags(engine, monkeypatch):
    files = {
        "02_return.md": "---\nscene: Return\n---\n# Return\nA genuine quote.",
        "plan.md": "## Scene 1\nnarrator: Alice\nchunks: 1\nscene: Departure\n\n## Scene 2\nnarrator: Bob\nchunks: 2\nscene: Return\n",
        "recap.md": "The party returned.",
        "genre.md": "Keep in-world magic.",
    }
    for name, content in files.items():
        (engine.store.session / name).write_text(content)
    refs = [engine.store.preserve(name, label="derived") for name in files]
    run = Run(id="partial", stage="narrate", selection=["02_return.md"], inputs=refs,
        generation={"backend":"codex-cli","model":"fixture-model","effort":"high","producer":"sd_narrate"},
        started_at=now(), task={"options":{"recap":"recap.md","plan":"plan.md","prose-mode":True}, "output_dir":".session-workflow/work/partial/outputs", "context":{"paths":{"narration-genre-file":str(engine.store.session / "genre.md")}}})
    cmd = build_command(engine, engine.store.load(), run)
    assert cmd[cmd.index("--scene") + 1] == "2"
    assert "--scene-extraction-file" in cmd
    assert "True" not in cmd
    assert "--prose-mode" in cmd
    assert "--codex-reasoning-effort" in cmd
    # Exercise the existing CLI's real parser; stop before any model call.
    real_parse = argparse.ArgumentParser.parse_args
    class Parsed(Exception): pass
    def parse(parser, *args, **kwargs):
        result = real_parse(parser, *args, **kwargs)
        assert result.scene == [2]
        assert result.prose_mode is True
        raise Parsed()
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse)
    monkeypatch.setattr(sys, "argv", cmd)
    with pytest.raises(Parsed):
        importlib.import_module("session_doc.sd_narrate").main()


def test_generation_effort_is_resolved_once_and_persisted(engine, monkeypatch):
    from test_session_workflow_review import mutate
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "high")
    mutate(engine, "start", stage="capture", selection=["source.md"], inputs=["source.md"], dependencies=[], required_checks=[], generation={"backend":"codex-cli","model":"fixture-model","producer":"fixture"})
    assert engine.store.load().runs[0].generation.effort == "high"
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "low")
    assert engine.store.load().runs[0].generation.effort == "high"


@pytest.mark.parametrize("stage, options", [("events", {"input": "input.vtt", "gmassist": "summary.md"}), ("extract", {"input": "input.vtt", "summary": "summary.md"})])
def test_selected_party_reaches_speaker_preflight(engine, stage, options):
    files = ["input.vtt", "summary.md", "party.md"]
    for name in files:
        (engine.store.session / name).write_text("fixture")
    refs = [engine.store.preserve(name, label="source") for name in files]
    run = Run(id="preflight", stage=stage, selection=files, inputs=refs,
        generation={"backend": "codex-cli", "model": "fixture-model", "producer": "fixture"}, started_at=now(),
        task={"options": {**options, "party": "party.md"}, "output_dir": ".session-workflow/work/preflight/outputs", "context": {"paths": {"party-config": "party.yaml", "players-config": "players.yaml"}}})
    cmd = build_command(engine, engine.store.load(), run)
    assert cmd[cmd.index("--party") + 1] == str(engine.store.session / "party.md")
    assert "--party-config" in cmd and "--players-config" in cmd
    run.inputs = [e for e in run.inputs if e.path != "party.md"]
    from session_doc.workflow.storage import WorkflowError
    with pytest.raises(WorkflowError, match="explicitly selected"):
        build_command(engine, engine.store.load(), run)


def test_next_stage_prompt_requires_fresh_approval_and_does_not_start_work(engine):
    from session_doc.workflow.engine import binding
    from session_doc.workflow.execution import resume
    from test_session_workflow_review import check, draft, mutate

    run = check(engine, draft(engine))
    assert resume(engine)["continuations"] == []
    mutate(engine, "approve", run_id=run.id, draft_binding=binding(run))
    original = engine.store.path.read_bytes()
    result = resume(engine)
    handoff = result["continuations"][0]
    assert handoff["run_id"] == run.id
    assert handoff["next_stage"] == "identify"
    assert str(engine.store.session) in handoff["prompt"]
    assert result["state"]["config"] in handoff["prompt"]
    assert "stop at human review" in handoff["prompt"]
    assert "instead of creating a duplicate" in handoff["prompt"]
    assert engine.store.path.read_bytes() == original
    (engine.store.session / "source.md").write_text("changed source")
    assert resume(engine)["continuations"] == []
