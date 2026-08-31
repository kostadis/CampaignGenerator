"""Codex-backed integration coverage for the brokered polish loop.

The fake ``codex`` executable is process-backed, so these tests exercise the
real adapter, including its isolated child and JSON output schema.  The model
may request operations, but only the parent-owned :class:`ToolContext` is
allowed to mutate the working document.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from campaignlib.api.codex_cli import _CodexCliClient
from pipelines.ensemble import polish
from pipelines.ensemble.polish import ToolContext, WorkingDoc, run_agent_loop
from tests.helpers.fake_codex_cli import FakeCodexCli


DOC = (
    "# Session 1\n\n---\n\n"
    "## Vukradin\n\n"
    "The wind cut through my cloak as we crossed the ridge. "
    "I tightened my grip and watched the valley below.\n\n"
    "---\n\n"
    "## Soma\n\n"
    "Soma raised the cracked shell and whispered a prayer before the party moved.\n"
)
RECAP = (
    "# Session 1 Recap\n\n"
    "## Memorable Moments\n\n"
    "The party paused at the riverbank where Brewbarry first spotted the dragon scale.\n"
)


def _tool(operation: str, **arguments: object) -> dict[str, str]:
    return {"name": operation, "arguments_json": json.dumps(arguments)}


def _ctx(tmp_path: Path) -> ToolContext:
    context = tmp_path / "world_state.md"
    context.write_text("The glacier lies north of the river.\n", encoding="utf-8")
    return ToolContext(
        doc=WorkingDoc.parse(DOC),
        recap_text=RECAP,
        voices={"vukradin": "Measured and watchful."},
        context_docs={},
        context_paths={"world_state": context},
        roster_names={"vukradin", "soma", "brewbarry"},
        current_turn=0,
    )


def _run(
    tmp_path: Path,
    monkeypatch,
    responses: list[dict],
    *,
    max_iterations: int = 10,
    reasoning_effort: str | None = None,
):
    fake = FakeCodexCli(tmp_path, responses=responses)
    fake.install(monkeypatch)
    ctx = _ctx(tmp_path)
    trace = polish.TraceWriter(tmp_path / "trace.jsonl")
    result = run_agent_loop(
        _CodexCliClient(
            reasoning_effort=reasoning_effort,
            reasoning_effort_source="explicit" if reasoning_effort else None,
        ),
        system="You are a careful editor.",
        ctx=ctx,
        model="gpt-5-codex",
        max_iterations=max_iterations,
        trace=trace,
    )
    trace.close()
    return result, ctx, fake


def test_codex_polish_supports_every_declared_operation(tmp_path, monkeypatch):
    """Every named operation is parent-dispatched and finish terminates cleanly."""
    changed = "The wind was sharp along the ridge, and I tightened my grip before moving."
    response = FakeCodexCli.structured(
        tool_calls=[
            _tool("list_sections"),
            _tool("read_doc_section", section_index=1),
            _tool("read_recap"),
            _tool("read_voice_file", character="Vukradin"),
            _tool("read_context_doc", name="world_state"),
            _tool(
                "apply_edit",
                section_index=1,
                new_text=changed,
                reason="Tighten the opening prose while preserving the scene details.",
                dimension="prose",
            ),
            _tool(
                "insert_section",
                after_section_index=1,
                narrator="Brewbarry",
                new_text="I watched the riverbank and kept the dragon scale in sight.",
                reason="The recap names a missing moment worth preserving in the draft.",
                recap_quote="The party paused at the riverbank where Brewbarry first spotted the dragon scale.",
            ),
            _tool(
                "record_critique",
                section_index=2,
                dimension="voice",
                note="Soma's prayer is clear, but the surrounding cadence could be more distinctive.",
            ),
            _tool("finish", summary="Reviewed all sections and recorded the grounded changes."),
        ]
    )
    (finished, summary), ctx, fake = _run(tmp_path, monkeypatch, [response])

    assert finished is True
    assert "grounded changes" in summary
    assert ctx.doc.sections[0].text == changed
    assert [entry.tool for entry in ctx.doc.changelog] == [
        "apply_edit", "insert_section", "record_critique",
    ]
    assert len(fake.calls) == 1
    assert fake.calls[0].structured is True


def test_codex_polish_replays_assistant_and_tool_result_turns(tmp_path, monkeypatch):
    """A later Codex turn receives ordered assistant and tool-result history."""
    responses = [
        FakeCodexCli.structured(tool_calls=[_tool("list_sections")]),
        FakeCodexCli.structured(
            tool_calls=[_tool("finish", summary="The review is complete.")]
        ),
    ]
    (finished, summary), _ctx_value, fake = _run(tmp_path, monkeypatch, responses)

    assert finished is True
    assert "complete" in summary
    assert len(fake.calls) == 2
    transcript = json.loads(fake.calls[1].stdin)
    messages = transcript["messages"]
    assert [message["role"] for message in messages[:3]] == [
        "user", "assistant", "user",
    ]
    assert any(block["type"] == "tool_use" for block in messages[1]["blocks"])
    assert any(block["type"] == "tool_result" for block in messages[2]["blocks"])


def test_codex_polish_returns_tool_errors_to_the_model(tmp_path, monkeypatch):
    """A rejected parent operation is an error tool-result, not a document edit."""
    responses = [
        FakeCodexCli.structured(
            tool_calls=[
                _tool(
                    "insert_section",
                    after_section_index=1,
                    narrator="Brewbarry",
                    new_text="An ungrounded addition.",
                    reason="This should be rejected because its evidence is absent.",
                    recap_quote="This sentence is not present in the recap.",
                )
            ]
        ),
        FakeCodexCli.structured(
            tool_calls=[_tool("finish", summary="I left the ungrounded draft unchanged.")]
        ),
    ]
    (finished, summary), ctx, fake = _run(tmp_path, monkeypatch, responses)

    assert finished is True
    assert "unchanged" in summary
    assert len(ctx.doc.sections) == 2
    trace_events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    failed_tools = [event for event in trace_events if event.get("event") == "tool_call" and event["is_error"]]
    assert failed_tools and failed_tools[0]["tool"] == "insert_section"
    assert len(fake.calls) == 2


def test_codex_polish_honors_loop_limit_and_trace_usage_is_null(tmp_path, monkeypatch):
    """The parent cap is authoritative and Codex's unavailable usage is explicit."""
    response = FakeCodexCli.structured(tool_calls=[_tool("list_sections")])
    (finished, summary), ctx, fake = _run(
        tmp_path, monkeypatch, [response], max_iterations=1
    )

    assert finished is False
    assert "force-finished after 1 iterations" in summary
    assert any(entry.tool == "(forced)" for entry in ctx.doc.changelog)
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    response_event = next(event for event in events if event.get("event") == "response")
    assert response_event["input_tokens"] is None
    assert response_event["output_tokens"] is None
    assert fake.calls[0].structured is True


def test_codex_polish_response_trace_records_actual_effort_provenance(tmp_path, monkeypatch):
    response = FakeCodexCli.structured(
        tool_calls=[_tool("finish", summary="Reviewed without edits.")],
    )
    _run(tmp_path, monkeypatch, [response], reasoning_effort="max")

    events = [
        json.loads(line)
        for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    response_event = next(event for event in events if event.get("event") == "response")
    assert response_event["model"] == "gpt-5-codex"
    assert response_event["codex_reasoning_effort"] == "max"
    assert response_event["codex_reasoning_effort_source"] == "explicit"
    assert response_event["codex_reasoning_override"] is True


def test_polish_run_start_uses_effective_backend_for_reasoning_metadata():
    source = inspect.getsource(polish.main)
    assert 'if reasoning.backend == "codex-cli":' in source
    assert 'if getattr(args, "backend", None) == "codex-cli":' not in source


def test_non_codex_response_trace_schema_is_unchanged(tmp_path):
    trace = polish.TraceWriter(tmp_path / "non-codex.jsonl")
    trace.log_response(
        1,
        SimpleNamespace(
            content=[],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
        ),
    )
    trace.close()
    event = json.loads((tmp_path / "non-codex.jsonl").read_text(encoding="utf-8"))
    assert "codex_reasoning_effort" not in event
    assert "model_source" not in event


def test_codex_polish_mutates_only_parent_working_document(tmp_path, monkeypatch):
    """An accepted edit changes ToolContext.doc; the child has no file target."""
    original = _ctx(tmp_path).doc.render()
    changed = "The wind cut through my cloak, and I watched the valley in silence."
    response = FakeCodexCli.structured(
        tool_calls=[
            _tool(
                "apply_edit",
                section_index=1,
                new_text=changed,
                reason="Make the opening sentence quieter without changing its events.",
                dimension="prose",
            ),
            _tool("finish", summary="Applied one parent-validated prose edit."),
        ]
    )
    (_finished, _summary), ctx, fake = _run(tmp_path, monkeypatch, [response])

    assert ctx.doc.render() != original
    assert ctx.doc.sections[0].text == changed
    assert len(ctx.doc.changelog) == 1
    assert ctx.doc.changelog[0].tool == "apply_edit"
    assert not any(
        "new_text" in part
        for part in fake.calls[0].argv
        if not part.startswith("developer_instructions=")
    )
