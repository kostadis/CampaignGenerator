"""Tests for polish.py — the agentic review pass."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import polish
from polish import (
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
             roster=("vukradin", "soma", "brewbarry")) -> ToolContext:
    return ToolContext(
        doc=doc,
        recap_text=recap,
        voices={},
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

    @property
    def messages(self):
        return self

    def create(self, **_kwargs):
        if not self._responses:
            raise RuntimeError("MockClient ran out of scripted responses")
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
