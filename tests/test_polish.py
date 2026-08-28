"""Tests for polish.py — the agentic review pass."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipelines.ensemble import polish
from pipelines.ensemble.polish import (
    SECTION_SEPARATOR,
    ChangelogEntry,
    Section,
    ToolContext,
    ToolError,
    WorkingDoc,
    run_agent_loop,
    sanity_check,
    tool_apply_edit,
    tool_insert_section,
    tool_list_sections,
    tool_read_doc_section,
    tool_read_voice_file,
    tool_record_critique,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_DOC = (
    "# Session 12 — The Glacier\n"
    "\n---\n\n"
    "## Vukradin\n\n"
    "The wind cut through my cloak as we approached the ridge. I tightened my grip on the haft.\n\n"
    "Soma muttered something behind me — a prayer to the shell, perhaps."
    "\n\n---\n\n"
    "## Soma\n\n"
    "I felt the cold first in my plastron. Vukradin had stopped at the ridge, scanning the valley below."
    "\n\n---\n\n"
    "## Brewbarry\n\n"
    "Honestly, the view was rubbish. Snow, more snow, and the faint outline of something large."
    "\n"
)

SAMPLE_RECAP = (
    "# Session 12 Recap\n\n"
    "## Summary\n\n"
    "The party crossed the glacier and made first contact with the frost giants. "
    "After the goblin retreat, the party paused at the riverbank where Brewbarry first spotted the dragon scale.\n\n"
    "## Memorable Moments\n\n"
    "- Vukradin's standoff at the ridge.\n"
    "- Soma's prayer over the cracked shell.\n"
)


def make_ctx(doc: WorkingDoc, recap: str = SAMPLE_RECAP,
             roster=("vukradin", "soma", "brewbarry"),
             voices: dict[str, str] | None = None) -> ToolContext:
    return ToolContext(
        doc=doc,
        recap_text=recap,
        voices=voices if voices is not None else {},
        context_docs={},
        context_paths={},
        roster_names=set(roster),
        current_turn=1,
    )


# ── WorkingDoc parser ─────────────────────────────────────────────────────────

def test_workingdoc_parse_extracts_sections():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    assert doc.title == "Session 12 — The Glacier"
    assert [s.narrator for s in doc.sections] == ["Vukradin", "Soma", "Brewbarry"]
    assert [s.index for s in doc.sections] == [1, 2, 3]
    assert "wind cut through my cloak" in doc.sections[0].text
    assert doc.sections[0].original_text == doc.sections[0].text


def test_workingdoc_roundtrip_is_identity():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    rendered = doc.render()
    # Re-parse the rendered output — should parse identically
    doc2 = WorkingDoc.parse(rendered)
    assert doc.title == doc2.title
    assert [s.narrator for s in doc.sections] == [s.narrator for s in doc2.sections]
    assert [s.text for s in doc.sections] == [s.text for s in doc2.sections]


def test_workingdoc_render_matches_assembler_shape():
    """The rendered shape must match server/routers/scene_editor.py:333-334."""
    doc = WorkingDoc.parse(SAMPLE_DOC)
    rendered = doc.render()
    assert rendered.startswith("# Session 12 — The Glacier\n")
    assert "\n\n---\n\n## Vukradin\n\n" in rendered
    assert "\n\n---\n\n## Soma\n\n" in rendered
    assert rendered.endswith("\n")


# ── apply_edit ────────────────────────────────────────────────────────────────

def test_apply_edit_replaces_section_and_records_changelog():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    new_text = "The wind was sharp and the ridge unforgiving. I tightened my grip on the haft and stepped forward."
    result = tool_apply_edit({
        "section_index": 1,
        "new_text": new_text,
        "reason": "Tightening prose pacing in opening paragraph",
        "dimension": "prose",
    }, ctx)
    assert result["ok"] is True
    assert doc.sections[0].text == new_text
    assert len(doc.changelog) == 1
    entry = doc.changelog[0]
    assert entry.tool == "apply_edit"
    assert entry.section_index == 1
    assert entry.dimension == "prose"


def test_apply_edit_rejects_short_reason():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    with pytest.raises(ToolError, match="reason"):
        tool_apply_edit({
            "section_index": 1,
            "new_text": "x" * 200,
            "reason": "short",
            "dimension": "prose",
        }, ctx)


def test_apply_edit_rejects_50_percent_shrinkage():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    original_len = len(doc.sections[0].text)
    too_short = "x" * (original_len // 4)
    with pytest.raises(ToolError, match="shrinks"):
        tool_apply_edit({
            "section_index": 1,
            "new_text": too_short,
            "reason": "Cutting heavy section to a single sentence",
            "dimension": "prose",
        }, ctx)


def test_apply_edit_rejects_invalid_dimension():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    with pytest.raises(ToolError, match="dimension"):
        tool_apply_edit({
            "section_index": 1,
            "new_text": "x" * 200,
            "reason": "A perfectly reasonable explanation here",
            "dimension": "vibes",
        }, ctx)


# ── insert_section ────────────────────────────────────────────────────────────

def test_insert_section_renumbers_subsequent_indices():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    quote = "After the goblin retreat, the party paused at the riverbank where Brewbarry first spotted the dragon scale."
    result = tool_insert_section({
        "after_section_index": 2,
        "narrator": "Brewbarry",
        "new_text": "I crouched at the water's edge and saw it — a single scale, dragon-blue.",
        "reason": "Recap mentions the riverbank dragon-scale moment but no section covers it",
        "recap_quote": quote,
    }, ctx)
    assert result["ok"] is True
    assert result["new_index"] == 3
    assert [s.narrator for s in doc.sections] == ["Vukradin", "Soma", "Brewbarry", "Brewbarry"]
    assert [s.index for s in doc.sections] == [1, 2, 3, 4]
    # Original Brewbarry section is now index 4
    assert "view was rubbish" in doc.sections[3].text


def test_insert_section_rejects_empty_recap_quote():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    with pytest.raises(ToolError, match="recap_quote"):
        tool_insert_section({
            "after_section_index": 1,
            "narrator": "Soma",
            "new_text": "x" * 200,
            "reason": "Trying to add a moment that did not happen",
            "recap_quote": "",
        }, ctx)


def test_insert_section_rejects_quote_not_in_recap():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    with pytest.raises(ToolError, match="verbatim"):
        tool_insert_section({
            "after_section_index": 1,
            "narrator": "Soma",
            "new_text": "x" * 200,
            "reason": "Trying to ground an insertion in a fabricated recap line",
            "recap_quote": "This sentence does not appear in the recap at all.",
        }, ctx)


def test_insert_section_rejects_unknown_narrator():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    quote = "After the goblin retreat, the party paused at the riverbank"
    with pytest.raises(ToolError, match="not in roster"):
        tool_insert_section({
            "after_section_index": 1,
            "narrator": "Tolubb",
            "new_text": "x" * 200,
            "reason": "Trying to use a narrator not in the roster",
            "recap_quote": quote,
        }, ctx)


def test_insert_section_quote_check_tolerates_whitespace():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    # Quote with normalized whitespace — should still match the recap.
    quote = "  After   the goblin retreat,\n the party paused at the riverbank  "
    result = tool_insert_section({
        "after_section_index": 2,
        "narrator": "Brewbarry",
        "new_text": "x" * 200,
        "reason": "Whitespace differences should not block legitimate insertions",
        "recap_quote": quote,
    }, ctx)
    assert result["ok"] is True


# ── record_critique ───────────────────────────────────────────────────────────

def test_record_critique_does_not_modify_doc():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    before = doc.render()
    tool_record_critique({
        "section_index": 2,
        "dimension": "prose",
        "note": "Section uses 'cold' three times in two sentences — would polish if I had a clear cut",
    }, ctx)
    assert doc.render() == before
    assert len(doc.changelog) == 1
    assert doc.changelog[0].tool == "record_critique"


# ── list_sections / read_doc_section ──────────────────────────────────────────

def test_list_sections_returns_table():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    result = tool_list_sections({}, ctx)
    assert len(result["sections"]) == 3
    assert result["sections"][0]["narrator"] == "Vukradin"
    assert result["sections"][0]["index"] == 1


def test_read_doc_section_returns_text():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    result = tool_read_doc_section({"section_index": 2}, ctx)
    assert result["narrator"] == "Soma"
    assert "cold first in my plastron" in result["text"]


def test_read_doc_section_unknown_index_raises():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    with pytest.raises(ToolError):
        tool_read_doc_section({"section_index": 99}, ctx)


# ── read_voice_file — exact match on the character name, against the files the
#    roster DECLARES (feature 009). Must not warn: this tool can be called on
#    every model turn. ─────────────────────────────────────────────────────────

def test_tool_read_voice_file_resolves_a_declared_voice(capsys):
    """The map is keyed by CHARACTER NAME now, not by filename stem, because
    the roster names the file. Phandalin's real file is
    `brewbarry_new_pipeline.md`; under the rule this replaced, the filename's
    shape was load-bearing and a rename broke it silently."""
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc, voices={"brewbarry": "Blustery halfling voice."})

    result = tool_read_voice_file({"character": "Brewbarry"}, ctx)

    assert result == {"character": "Brewbarry", "text": "Blustery halfling voice."}
    assert capsys.readouterr().err == ""


def test_tool_read_voice_file_does_not_match_on_a_prefix(capsys):
    """`Brewbarry` must not resolve to a file declared for somebody else just
    because the names start alike (FR-025)."""
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc, voices={"brewbarry the bold": "Someone else."})

    result = tool_read_voice_file({"character": "Brewbarry"}, ctx)

    assert "error" in result
    assert capsys.readouterr().err == ""


def test_tool_read_voice_file_missing_returns_error_dict_not_raise(capsys):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc, voices={"vukradin": "Gruff."})

    result = tool_read_voice_file({"character": "Brewbarry"}, ctx)

    assert "error" in result
    assert "Brewbarry" in result["error"]
    assert "vukradin" in result["error"]
    # No stderr spam on a routine tool-call miss. The miss that matters is
    # reported once, by the pre-flight, before any tokens are spent.
    assert capsys.readouterr().err == ""


def test_tool_read_voice_file_ambiguous_returns_error_dict_not_raise(capsys):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc, voices={
        "brewbarry_new_pipeline": "New spec.",
        "brewbarry_old_pipeline": "Old spec.",
    })

    result = tool_read_voice_file({"character": "Brewbarry"}, ctx)

    assert "error" in result
    assert capsys.readouterr().err == ""


# ── Loop driver (mocked client) ───────────────────────────────────────────────

@dataclass
class MockBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict | None = None


@dataclass
class MockUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class MockResponse:
    content: list
    stop_reason: str
    usage: MockUsage


class MockClient:
    """Yields a pre-scripted sequence of responses, one per .messages.create() call."""

    def __init__(self, responses: list[MockResponse]):
        self._responses = list(responses)
        self.calls = 0
        self.requests = []

    @property
    def messages(self):
        return self

    def create(self, **_kwargs):
        if not self._responses:
            raise RuntimeError("MockClient ran out of scripted responses")
        # ``run_agent_loop`` appends the next assistant/tool-result messages
        # after the API call.  Snapshot the message list so assertions inspect
        # the exact request that was sent on each turn.
        request = dict(_kwargs)
        request["messages"] = list(_kwargs.get("messages", []))
        self.requests.append(request)
        self.calls += 1
        return self._responses.pop(0)


def _trace(tmp_path):
    return polish.TraceWriter(tmp_path / "trace.jsonl")


def test_loop_terminates_when_agent_calls_finish(tmp_path):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    client = MockClient([
        MockResponse(
            content=[
                MockBlock(type="text", text="Listing sections."),
                MockBlock(type="tool_use", id="t1", name="list_sections", input={}),
            ],
            stop_reason="tool_use", usage=MockUsage(),
        ),
        MockResponse(
            content=[
                MockBlock(type="tool_use", id="t2", name="finish",
                          input={"summary": "Reviewed all sections, no edits needed."}),
            ],
            stop_reason="tool_use", usage=MockUsage(),
        ),
    ])
    trace = _trace(tmp_path)
    finished, summary = run_agent_loop(
        client, system="(test)", ctx=ctx, model="test-model",
        max_iterations=10, trace=trace,
    )
    trace.close()
    assert finished is True
    assert "Reviewed all sections" in summary
    assert client.calls == 2


def test_loop_force_terminates_at_max_iterations(tmp_path):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    # Each turn just calls list_sections, never finish.
    response_template = lambda i: MockResponse(
        content=[MockBlock(type="tool_use", id=f"t{i}",
                           name="list_sections", input={})],
        stop_reason="tool_use", usage=MockUsage(),
    )
    client = MockClient([response_template(i) for i in range(5)])
    trace = _trace(tmp_path)
    finished, summary = run_agent_loop(
        client, system="(test)", ctx=ctx, model="test-model",
        max_iterations=3, trace=trace,
    )
    trace.close()
    assert finished is False
    assert "force-finished" in summary
    assert client.calls == 3
    # The forced-finish entry should be in the changelog.
    assert any(e.tool == "(forced)" for e in doc.changelog)


def test_loop_handles_double_end_turn_stall(tmp_path):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    # Two end_turn responses in a row → force-finish.
    end_turn = MockResponse(
        content=[MockBlock(type="text", text="Hmm.")],
        stop_reason="end_turn", usage=MockUsage(),
    )
    client = MockClient([end_turn, end_turn])
    trace = _trace(tmp_path)
    finished, summary = run_agent_loop(
        client, system="(test)", ctx=ctx, model="test-model",
        max_iterations=10, trace=trace,
    )
    trace.close()
    assert finished is False
    assert "stalled" in summary


def test_loop_returns_tool_error_to_model(tmp_path):
    """When a tool raises ToolError, the next prompt must include is_error: true
    so the model can self-correct. Verify by feeding a bad insert then a finish."""
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    client = MockClient([
        MockResponse(
            content=[MockBlock(type="tool_use", id="t1", name="insert_section",
                               input={
                                   "after_section_index": 1,
                                   "narrator": "Vukradin",
                                   "new_text": "x" * 200,
                                   "reason": "An attempted insert with a fake quote",
                                   "recap_quote": "This text is not in the recap.",
                               })],
            stop_reason="tool_use", usage=MockUsage(),
        ),
        MockResponse(
            content=[MockBlock(type="tool_use", id="t2", name="finish",
                               input={"summary": "Could not ground that insertion."})],
            stop_reason="tool_use", usage=MockUsage(),
        ),
    ])
    trace = _trace(tmp_path)
    finished, _ = run_agent_loop(
        client, system="(test)", ctx=ctx, model="test-model",
        max_iterations=10, trace=trace,
    )
    trace.close()
    assert finished is True
    # No section was inserted, no apply_edit-style changelog entry from the failed insert.
    assert len(doc.sections) == 3
    assert all(e.tool != "insert_section" for e in doc.changelog)


def _tool_response(*blocks: MockBlock) -> MockResponse:
    return MockResponse(
        content=list(blocks), stop_reason="tool_use", usage=MockUsage()
    )


def _finish_response(summary: str = "Finished after feedback.") -> MockResponse:
    return _tool_response(
        MockBlock(type="tool_use", id="finish", name="finish",
                  input={"summary": summary})
    )


def _run_tool_feedback(tmp_path, *blocks: MockBlock):
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc, voices={
        "brewbarry_new_pipeline": "New voice.",
        "brewbarry_old_pipeline": "Old voice.",
    })
    client = MockClient([_tool_response(*blocks), _finish_response()])
    trace = _trace(tmp_path)
    finished, summary = run_agent_loop(
        client, system="(codex-neutral test)", ctx=ctx, model="codex-model",
        max_iterations=10, trace=trace,
    )
    trace.close()
    return doc, ctx, client, finished, summary


@pytest.mark.parametrize(
    ("label", "block"),
    [
        (
            "malformed",
            MockBlock(type="tool_use", id="bad", name="apply_edit", input={}),
        ),
        (
            "unknown",
            MockBlock(type="tool_use", id="unknown", name="delete_everything", input={}),
        ),
        (
            "out-of-scope",
            MockBlock(
                type="tool_use", id="scope", name="insert_section",
                input={
                    "after_section_index": 1,
                    "narrator": "NotInRoster",
                    "new_text": "x" * 200,
                    "reason": "This operation must remain within the declared roster",
                    "recap_quote": "After the goblin retreat",
                },
            ),
        ),
        (
            "ambiguous",
            MockBlock(
                type="tool_use", id="ambiguous", name="read_voice_file",
                input={"character": "Brewbarry"},
            ),
        ),
    ],
)
def test_invalid_or_ambiguous_operations_return_feedback_without_edits(
    tmp_path, label, block
):
    """Codex action refusals are feedback, never successful edit entries."""
    doc, _ctx, client, finished, _summary = _run_tool_feedback(tmp_path, block)

    assert finished is True
    assert client.calls == 2
    # The second turn receives the host-generated result before it can finish.
    result_blocks = client.requests[1]["messages"][-1]["content"]
    assert result_blocks and any("error" in result["content"] for result in result_blocks)
    assert not any(entry.tool in {"apply_edit", "insert_section"}
                   for entry in doc.changelog)


def test_repeated_and_conflicting_invalid_operations_have_no_successful_edits(
    tmp_path,
):
    """Repeated/conflicting invalid actions remain errors, not partial edits."""
    repeated_bad_edit = MockBlock(
        type="tool_use", id="repeat", name="apply_edit",
        input={
            "section_index": 999,
            "new_text": "x" * 200,
            "reason": "This repeated edit targets no declared document section",
            "dimension": "prose",
        },
    )
    conflicting_bad_edit = MockBlock(
        type="tool_use", id="conflict", name="apply_edit",
        input={
            "section_index": "not-an-index",
            "new_text": "x" * 200,
            "reason": "This conflicting edit has malformed section scope",
            "dimension": "prose",
        },
    )
    doc, _ctx, client, finished, _summary = _run_tool_feedback(
        tmp_path, repeated_bad_edit, repeated_bad_edit, conflicting_bad_edit
    )

    assert finished is True
    result_blocks = client.requests[1]["messages"][-1]["content"]
    assert len(result_blocks) == 3
    assert all(result.get("is_error") is True for result in result_blocks)
    assert not any(entry.tool == "apply_edit" for entry in doc.changelog)


def test_finish_at_turn_40_is_clean_and_does_not_force_finish(tmp_path):
    """The documented 40-turn ceiling still permits a finish on turn 40."""
    responses = [
        _tool_response(MockBlock(type="tool_use", id=f"list-{i}",
                                 name="list_sections", input={}))
        for i in range(39)
    ] + [_finish_response("Completed on the final allowed turn.")]
    client = MockClient(responses)
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    trace = _trace(tmp_path)
    finished, summary = run_agent_loop(
        client, system="(codex-neutral test)", ctx=ctx, model="codex-model",
        max_iterations=40, trace=trace,
    )
    trace.close()

    assert finished is True
    assert "final allowed turn" in summary
    assert client.calls == 40
    assert not any(entry.tool == "(forced)" for entry in doc.changelog)


def test_finish_conflict_does_not_count_a_later_edit_as_success(tmp_path):
    """A finish plus an unsafe edit in one response cannot create an edit."""
    doc = WorkingDoc.parse(SAMPLE_DOC)
    ctx = make_ctx(doc)
    client = MockClient([
        _tool_response(
            MockBlock(type="tool_use", id="finish", name="finish",
                      input={"summary": "Stop now."}),
            MockBlock(type="tool_use", id="bad-edit", name="apply_edit",
                      input={"section_index": 1, "new_text": "A valid-looking replacement " * 10,
                             "reason": "This conflicting edit must not be applied after finish",
                             "dimension": "prose"}),
        ),
    ])
    trace = _trace(tmp_path)
    finished, _summary = run_agent_loop(
        client, system="(codex-neutral test)", ctx=ctx, model="codex-model",
        max_iterations=40, trace=trace,
    )
    trace.close()

    assert finished is True
    assert client.calls == 1
    assert not any(entry.tool == "apply_edit" for entry in doc.changelog)


# ── Sanity check ──────────────────────────────────────────────────────────────

def test_sanity_check_flags_unknown_narrator():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    doc.sections.append(Section(index=4, narrator="Xalvosh",
                                text="Some text", original_text=""))
    warnings = sanity_check(doc, {"vukradin", "soma", "brewbarry"})
    assert any("not in roster" in w for w in warnings)


def test_sanity_check_flags_non_contiguous_indices():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    doc.sections[2].index = 99
    warnings = sanity_check(doc, {"vukradin", "soma", "brewbarry"})
    assert any("not contiguous" in w for w in warnings)


def test_sanity_check_passes_clean_doc():
    doc = WorkingDoc.parse(SAMPLE_DOC)
    warnings = sanity_check(doc, {"vukradin", "soma", "brewbarry"})
    assert warnings == []


def test_party_config_is_declared_required(monkeypatch, tmp_path):
    """It is unconditionally mandatory since #265 (the roster call has no
    guard), so argparse must reject its absence at usage time — exit 2 —
    rather than letting the run parse the doc, read the recap and load the
    voice dir before dying on a late runtime exit."""
    import sys
    from pipelines.ensemble import polish
    doc = tmp_path / "doc.md"; doc.write_text("# t\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "polish", str(doc), "--recap", str(doc), "--party", str(doc),
        "--voice-dir", str(tmp_path), "--out", str(tmp_path / "o.md"),
    ])
    with pytest.raises(SystemExit) as exc:
        polish.main()
    assert exc.value.code == 2          # argparse usage error, not a late exit
