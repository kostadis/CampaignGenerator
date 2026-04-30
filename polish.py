"""polish.py — agentic review pass on an assembled session document.

Experiment in agent-loop construction. A single Claude call with tools drives
its own control flow: read sections, consult the GMassistant recap, edit
sections, insert missing-event sections, record critiques, then call finish().

Linear-pipeline equivalents would be ~3x cheaper. The goal here is to learn
how the loop machinery feels, not to ship cost-optimal polish.

Override of the global "humans decide scope" rule: the agent inserts missing
events directly. Cheap mitigation — every insert_section call must include a
recap_quote that is verified to appear in the recap text.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from campaignlib import (
    call_api_with_tools,
    find_default_config,
    load_config,
    make_client,
    save_log,
)
from session_doc import extract_character_roster, load_voice_files


DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_ITERATIONS = 40
SECTION_SEPARATOR = "\n\n---\n\n"


# ── WorkingDoc ────────────────────────────────────────────────────────────────

@dataclass
class Section:
    index: int           # 1-based; reassigned on insert
    narrator: str        # the "## <Narrator>" header
    text: str            # body, no header, no surrounding separators
    original_text: str   # snapshot at parse time, for diffs


@dataclass
class ChangelogEntry:
    turn: int
    tool: str
    section_index: int | None
    dimension: str | None
    reason: str
    recap_quote: str | None = None
    diff_summary: str | None = None


@dataclass
class WorkingDoc:
    title: str
    sections: list[Section] = field(default_factory=list)
    changelog: list[ChangelogEntry] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> "WorkingDoc":
        """Parse an assembled session-doc.md. Mirrors the shape produced by
        server/routers/scene_editor.py:333-334 and session_doc.py:1514-1516."""
        parts = text.split(SECTION_SEPARATOR)
        if not parts:
            raise ValueError("empty document")

        head = parts[0].strip()
        title_match = re.match(r"^#\s+(.+?)\s*$", head, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else head.lstrip("#").strip()

        sections: list[Section] = []
        for i, raw in enumerate(parts[1:], 1):
            block = raw.strip()
            if not block:
                continue
            m = re.match(r"^##\s+(.+?)\s*\n+(.*)\Z", block, re.DOTALL)
            if not m:
                raise ValueError(
                    f"section {i} does not start with '## <Narrator>': "
                    f"{block[:80]!r}"
                )
            narrator = m.group(1).strip()
            body = m.group(2).strip()
            sections.append(Section(
                index=i, narrator=narrator, text=body, original_text=body,
            ))

        return cls(title=title, sections=sections)

    def render(self) -> str:
        head = f"# {self.title}\n"
        body = SECTION_SEPARATOR.join(
            f"## {s.narrator}\n\n{s.text}" for s in self.sections
        )
        return f"{head}{SECTION_SEPARATOR}{body}\n"

    def get_section(self, index: int) -> Section:
        for s in self.sections:
            if s.index == index:
                return s
        raise ToolError(f"no section with index {index}")

    def renumber(self) -> None:
        for i, s in enumerate(self.sections, 1):
            s.index = i

    def section_table(self) -> list[dict]:
        return [
            {
                "index": s.index,
                "narrator": s.narrator,
                "char_count": len(s.text),
                "first_line": s.text.split("\n", 1)[0][:120],
            }
            for s in self.sections
        ]


# ── Tools ─────────────────────────────────────────────────────────────────────

class ToolError(Exception):
    """Raised by a tool to signal an error to the model (returns is_error: true)."""


@dataclass
class ToolContext:
    """Everything the tools need that isn't on WorkingDoc."""
    doc: WorkingDoc
    recap_text: str
    voices: dict[str, str]            # lowercased name → voice text
    context_docs: dict[str, str]      # basename → text (lazy-cached)
    context_paths: dict[str, Path]    # basename → path (for lazy load)
    roster_names: set[str]            # lowercased canonical names
    current_turn: int                 # mutated by loop driver before dispatch


VALID_DIMENSIONS = {"voice", "continuity", "prose", "missing_event"}
SHRINKAGE_THRESHOLD = 0.5    # apply_edit can't shrink below this fraction
MIN_REASON_CHARS = 20


def tool_list_sections(_args: dict, ctx: ToolContext) -> dict:
    return {"sections": ctx.doc.section_table()}


def tool_read_doc_section(args: dict, ctx: ToolContext) -> dict:
    idx = _require_int(args, "section_index")
    s = ctx.doc.get_section(idx)
    return {"index": s.index, "narrator": s.narrator, "text": s.text}


def tool_read_recap(args: dict, ctx: ToolContext) -> dict:
    section = (args or {}).get("section")
    if not section:
        return {"section": "FULL", "text": ctx.recap_text}
    # Find a markdown heading containing the requested string (case-insensitive).
    pattern = re.compile(
        rf"(?ms)^(#+)\s+.*?{re.escape(section)}.*?\s*$",
        re.IGNORECASE,
    )
    m = pattern.search(ctx.recap_text)
    if not m:
        return {"error": f"no heading matching {section!r} in recap; "
                          "call read_recap with no section to get the full text"}
    start = m.start()
    level = len(m.group(1))
    # End at the next heading of equal or shallower depth, or EOF.
    end_pattern = re.compile(rf"(?ms)^#{{1,{level}}}\s+.*?$")
    rest = ctx.recap_text[m.end():]
    e = end_pattern.search(rest)
    end = m.end() + (e.start() if e else len(rest))
    return {"section": section, "text": ctx.recap_text[start:end].strip()}


def tool_read_voice_file(args: dict, ctx: ToolContext) -> dict:
    name = _require_str(args, "character")
    key = name.lower().strip()
    if key not in ctx.voices:
        return {"error": f"no voice file for {name!r}; "
                         f"available: {sorted(ctx.voices)}"}
    return {"character": name, "text": ctx.voices[key]}


def tool_read_context_doc(args: dict, ctx: ToolContext) -> dict:
    name = _require_str(args, "name")
    if name in ctx.context_docs:
        return {"name": name, "text": ctx.context_docs[name]}
    if name not in ctx.context_paths:
        return {"error": f"no context doc named {name!r}; "
                         f"available: {sorted(ctx.context_paths)}"}
    text = ctx.context_paths[name].read_text(encoding="utf-8")
    ctx.context_docs[name] = text
    return {"name": name, "text": text}


def tool_apply_edit(args: dict, ctx: ToolContext) -> dict:
    idx = _require_int(args, "section_index")
    new_text = _require_str(args, "new_text").strip()
    reason = _require_str(args, "reason")
    dimension = _require_str(args, "dimension")
    if dimension not in VALID_DIMENSIONS:
        raise ToolError(f"dimension must be one of {sorted(VALID_DIMENSIONS)}")
    if len(reason.strip()) < MIN_REASON_CHARS:
        raise ToolError(f"reason must be at least {MIN_REASON_CHARS} characters")

    s = ctx.doc.get_section(idx)
    old_len = len(s.text)
    new_len = len(new_text)
    if old_len > 0 and new_len < old_len * SHRINKAGE_THRESHOLD:
        raise ToolError(
            f"edit shrinks section from {old_len} to {new_len} chars "
            f"(>{int((1 - SHRINKAGE_THRESHOLD) * 100)}% reduction). "
            "If a substantial cut is genuinely needed, use record_critique "
            "instead and let the user decide."
        )

    diff_summary = f"+{max(0, new_len - old_len)} chars / -{max(0, old_len - new_len)} chars"
    s.text = new_text
    ctx.doc.changelog.append(ChangelogEntry(
        turn=ctx.current_turn,
        tool="apply_edit",
        section_index=idx,
        dimension=dimension,
        reason=reason.strip(),
        diff_summary=diff_summary,
    ))
    return {"ok": True, "new_char_count": new_len, "diff": diff_summary}


def tool_insert_section(args: dict, ctx: ToolContext) -> dict:
    after = _require_int(args, "after_section_index")
    narrator = _require_str(args, "narrator").strip()
    new_text = _require_str(args, "new_text").strip()
    reason = _require_str(args, "reason")
    recap_quote = _require_str(args, "recap_quote").strip()

    if narrator.lower() not in ctx.roster_names:
        raise ToolError(
            f"narrator {narrator!r} not in roster: {sorted(ctx.roster_names)}"
        )
    if len(reason.strip()) < MIN_REASON_CHARS:
        raise ToolError(f"reason must be at least {MIN_REASON_CHARS} characters")
    if not recap_quote:
        raise ToolError("recap_quote is required and must not be empty")

    # Substring check: the recap_quote must appear verbatim somewhere in the recap.
    # Allow whitespace flexibility — collapse runs of whitespace before comparing.
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    if norm(recap_quote) not in norm(ctx.recap_text):
        raise ToolError(
            "recap_quote does not appear verbatim in the recap text. "
            "If the event is genuinely in the recap, copy a longer literal "
            "phrase. Otherwise this insertion is not grounded — use "
            "record_critique to flag it instead of inserting."
        )

    # Insert after the section with index `after` (0 = prepend before first).
    insert_pos = 0
    if after > 0:
        for i, s in enumerate(ctx.doc.sections):
            if s.index == after:
                insert_pos = i + 1
                break
        else:
            raise ToolError(f"no section with index {after}")

    new_section = Section(
        index=-1,          # renumber will fix
        narrator=narrator,
        text=new_text,
        original_text="",  # newly created — no original
    )
    ctx.doc.sections.insert(insert_pos, new_section)
    ctx.doc.renumber()
    new_index = new_section.index

    ctx.doc.changelog.append(ChangelogEntry(
        turn=ctx.current_turn,
        tool="insert_section",
        section_index=new_index,
        dimension="missing_event",
        reason=reason.strip(),
        recap_quote=recap_quote,
        diff_summary=f"new section ({len(new_text)} chars, narrator={narrator})",
    ))
    return {"ok": True, "new_index": new_index}


def tool_record_critique(args: dict, ctx: ToolContext) -> dict:
    section_index = (args or {}).get("section_index")
    if section_index is not None:
        section_index = int(section_index)
        ctx.doc.get_section(section_index)  # validate exists
    dimension = _require_str(args, "dimension")
    note = _require_str(args, "note")
    if len(note.strip()) < MIN_REASON_CHARS:
        raise ToolError(f"note must be at least {MIN_REASON_CHARS} characters")

    ctx.doc.changelog.append(ChangelogEntry(
        turn=ctx.current_turn,
        tool="record_critique",
        section_index=section_index,
        dimension=dimension,
        reason=note.strip(),
    ))
    return {"ok": True}


def tool_finish(args: dict, _ctx: ToolContext) -> dict:
    summary = _require_str(args, "summary")
    return {"summary": summary}


def _require_str(args: dict, key: str) -> str:
    if not args or key not in args or not isinstance(args[key], str):
        raise ToolError(f"missing required string argument: {key}")
    return args[key]


def _require_int(args: dict, key: str) -> int:
    if not args or key not in args:
        raise ToolError(f"missing required argument: {key}")
    try:
        return int(args[key])
    except (TypeError, ValueError):
        raise ToolError(f"argument {key} must be an integer")


# ── Tool schemas (sent to the SDK) ────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "list_sections",
        "description": "Return the table of sections in the working doc: index, narrator, char count, first line. Cheap — call any time to re-orient.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_doc_section",
        "description": "Fetch the full text of one section by index.",
        "input_schema": {
            "type": "object",
            "properties": {"section_index": {"type": "integer", "minimum": 1}},
            "required": ["section_index"],
        },
    },
    {
        "name": "read_recap",
        "description": "Fetch the GMassistant recap. Omit `section` for the full text. Provide `section` to fetch a heading-bounded slice (e.g. 'Memorable Moments', 'Scenes', 'Summary').",
        "input_schema": {
            "type": "object",
            "properties": {"section": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "read_voice_file",
        "description": "Fetch a player's voice notes for a character. Use this BEFORE judging voice fidelity or rewriting any character's prose.",
        "input_schema": {
            "type": "object",
            "properties": {"character": {"type": "string"}},
            "required": ["character"],
        },
    },
    {
        "name": "read_context_doc",
        "description": "Fetch a campaign grounding doc by basename (e.g. 'campaign_state', 'world_state'). Use only when continuity-checking requires it — these are large.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "apply_edit",
        "description": "Replace the text of an existing section. Use sparingly. The new text replaces the section body entirely. Edits that shrink a section by more than 50% are rejected — use record_critique for cuts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_index": {"type": "integer", "minimum": 1},
                "new_text": {"type": "string"},
                "reason": {
                    "type": "string",
                    "description": "1-3 sentences. For voice edits, name the voice-file rule the original violated. For continuity, name the contradicting section.",
                },
                "dimension": {
                    "type": "string",
                    "enum": ["voice", "continuity", "prose", "missing_event"],
                },
            },
            "required": ["section_index", "new_text", "reason", "dimension"],
        },
    },
    {
        "name": "insert_section",
        "description": "Insert a new narrated section after an existing one (use after_section_index=0 to prepend). Only for events the recap describes that the doc is missing. recap_quote MUST appear verbatim in the recap or the call is rejected.",
        "input_schema": {
            "type": "object",
            "properties": {
                "after_section_index": {"type": "integer", "minimum": 0},
                "narrator": {
                    "type": "string",
                    "description": "Must be one of the canonical roster names.",
                },
                "new_text": {"type": "string"},
                "reason": {"type": "string"},
                "recap_quote": {
                    "type": "string",
                    "description": "Verbatim line(s) from the recap that ground this insertion. Substring-checked against the recap.",
                },
            },
            "required": ["after_section_index", "narrator", "new_text", "reason", "recap_quote"],
        },
    },
    {
        "name": "record_critique",
        "description": "Add a note to the changelog without modifying the doc. Use for stylistic preferences, observations the user should review, or cases where you would otherwise rewrite something but the existing prose is voice-faithful.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section_index": {"type": ["integer", "null"], "minimum": 1},
                "dimension": {
                    "type": "string",
                    "enum": ["voice", "continuity", "prose", "missing_event", "other"],
                },
                "note": {"type": "string"},
            },
            "required": ["dimension", "note"],
        },
    },
    {
        "name": "finish",
        "description": "Terminate the review loop. Call this when you have completed all four review dimensions for every section, OR when no further productive edits are possible.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Free-form reflection on what you did and why. Goes at the top of the changelog.",
                },
            },
            "required": ["summary"],
        },
    },
]

TOOL_DISPATCH = {
    "list_sections": tool_list_sections,
    "read_doc_section": tool_read_doc_section,
    "read_recap": tool_read_recap,
    "read_voice_file": tool_read_voice_file,
    "read_context_doc": tool_read_context_doc,
    "apply_edit": tool_apply_edit,
    "insert_section": tool_insert_section,
    "record_critique": tool_record_critique,
    "finish": tool_finish,
}


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are an editor doing a final polish pass on a D&D session document. The document has been assembled from per-scene first-person narrations written by different player characters in rotation. Your job is to review and improve it across four dimensions, then call finish().

# Review dimensions

1. **Missing events.** The GMassistant recap is the authoritative account of what happened in the session. If the recap describes an event (especially in the Summary or Memorable Moments sections) that no narrated section in the doc covers, insert a new section narrated by an appropriate character. Use read_recap to consult it.

2. **Continuity.** Adjacent and distant sections must not contradict each other on facts, timeline, who-was-where, or who-knows-what. Use read_doc_section to compare. Use read_context_doc only if the doc itself is ambiguous and you need a grounding doc to adjudicate.

3. **Voice fidelity.** Each section is narrated by a specific character. Each character has a player-written voice file describing their speech patterns, interiority, and quirks. BEFORE editing or judging any section, call read_voice_file for that character. If the existing prose matches the voice file, do not rewrite it — even if you would write it differently.

4. **Prose quality.** Repetition (the same phrase twice in three paragraphs), clichés, pacing dead-spots, dropped imagery. These edits should be small and surgical, not wholesale rewrites.

# Edit policy

You may apply edits directly. You do not need to ask permission. BUT:

- Every apply_edit and insert_section call must include a `reason` of at least 20 characters.
- insert_section requires `recap_quote` — a verbatim line from the recap text. The dispatcher substring-checks this. If you cannot quote the recap, do NOT insert; use record_critique to flag the gap.
- apply_edit that shrinks a section by more than 50% is rejected — use record_critique for cuts.
- Voice fidelity: do not rewrite for personal taste. If the existing prose matches the voice file, leave it alone.
- Use record_critique when you have an observation but no concrete edit you are confident in.

# Character roster (canonical narrators)

{roster}

Inserted sections must use one of these names exactly. Names are case-insensitive at the dispatcher.

# Available context docs

{context_doc_names}

# Termination contract

Call finish(summary) when you have completed the review of every section across all four dimensions, or when no further productive edits are possible. The loop is force-terminated after {max_iterations} iterations — at that point any pending notes are appended to the changelog as forced/incomplete.

Begin by calling list_sections to see what you are working with."""


def build_system_prompt(roster_text: str, context_doc_names: list[str], max_iters: int) -> str:
    names_block = "\n".join(f"- {n}" for n in context_doc_names) if context_doc_names \
        else "(none provided — read_context_doc will fail)"
    return SYSTEM_PROMPT_TEMPLATE.format(
        roster=roster_text or "(none — party.md was empty or unparseable)",
        context_doc_names=names_block,
        max_iterations=max_iters,
    )


# ── Trace writer ──────────────────────────────────────────────────────────────

class TraceWriter:
    """Append JSONL events to a trace file. One file per run."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", encoding="utf-8")

    def emit(self, event: dict) -> None:
        event["ts"] = datetime.now().isoformat(timespec="seconds")
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()

    def log_response(self, turn: int, response) -> None:
        blocks = []
        for block in response.content:
            if block.type == "text":
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            else:
                blocks.append({"type": block.type})
        self.emit({
            "event": "response",
            "turn": turn,
            "stop_reason": response.stop_reason,
            "input_tokens": getattr(response.usage, "input_tokens", None),
            "output_tokens": getattr(response.usage, "output_tokens", None),
            "blocks": blocks,
        })

    def log_tool_call(self, turn: int, name: str, args: dict,
                      result: str, is_error: bool) -> None:
        self.emit({
            "event": "tool_call",
            "turn": turn,
            "tool": name,
            "input": args,
            "result": result[:4000],   # truncate huge results in trace
            "result_truncated": len(result) > 4000,
            "is_error": is_error,
        })


# ── Loop driver ───────────────────────────────────────────────────────────────

def run_agent_loop(client, *, system: str, ctx: ToolContext, model: str,
                   max_iterations: int, trace: TraceWriter,
                   verbose: bool = False) -> tuple[bool, str]:
    """Run the tool-use loop. Returns (finished_cleanly, finish_summary)."""
    messages: list[dict] = [{
        "role": "user",
        "content": "Begin the review. Start by calling list_sections to see what you are working with.",
    }]

    finish_summary = ""
    last_was_end_turn = False

    for turn in range(1, max_iterations + 1):
        ctx.current_turn = turn
        trace.emit({"event": "turn_start", "turn": turn,
                    "messages_so_far": len(messages)})
        if verbose:
            print(f"\n=== Turn {turn} ===")

        response = call_api_with_tools(
            client, system=system, messages=messages,
            tools=TOOL_SCHEMAS, model=model, max_tokens=8192,
        )
        trace.log_response(turn, response)

        for block in response.content:
            if block.type == "text" and block.text.strip():
                if verbose:
                    print(f"[text] {block.text}")
                else:
                    snippet = block.text.strip().split("\n", 1)[0][:120]
                    print(f"  turn {turn}: {snippet}")

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            if last_was_end_turn:
                trace.emit({"event": "force_finish", "reason": "two end_turns in a row"})
                finish_summary = "(force-finished: model stalled with no tool call twice)"
                ctx.doc.changelog.append(ChangelogEntry(
                    turn=turn, tool="(forced)", section_index=None,
                    dimension=None, reason=finish_summary,
                ))
                return False, finish_summary
            messages.append({"role": "user",
                             "content": "Continue the review. Call finish(summary) if you are done."})
            last_was_end_turn = True
            continue
        last_was_end_turn = False

        if response.stop_reason != "tool_use":
            trace.emit({"event": "loop_abort",
                        "stop_reason": response.stop_reason})
            finish_summary = f"(loop aborted: stop_reason={response.stop_reason})"
            ctx.doc.changelog.append(ChangelogEntry(
                turn=turn, tool="(aborted)", section_index=None,
                dimension=None, reason=finish_summary,
            ))
            return False, finish_summary

        # Dispatch every tool_use block in this turn.
        finished_this_turn = False
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input or {}

            if tool_name == "finish":
                try:
                    result = tool_finish(tool_input, ctx)
                    finish_summary = result["summary"]
                    finished_this_turn = True
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": "Acknowledged. Loop terminating.",
                    })
                    trace.log_tool_call(turn, "finish", tool_input,
                                        f"summary len={len(finish_summary)}", False)
                except ToolError as e:
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": block.id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True,
                    })
                    trace.log_tool_call(turn, "finish", tool_input, str(e), True)
                continue

            fn = TOOL_DISPATCH.get(tool_name)
            if fn is None:
                err = f"unknown tool: {tool_name}"
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": json.dumps({"error": err}),
                    "is_error": True,
                })
                trace.log_tool_call(turn, tool_name, tool_input, err, True)
                continue

            try:
                result = fn(tool_input, ctx)
                content = json.dumps(result, ensure_ascii=False)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": content,
                })
                trace.log_tool_call(turn, tool_name, tool_input, content, False)
            except ToolError as e:
                err_payload = json.dumps({"error": str(e)})
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id,
                    "content": err_payload, "is_error": True,
                })
                trace.log_tool_call(turn, tool_name, tool_input, err_payload, True)

        messages.append({"role": "user", "content": tool_results})

        if finished_this_turn:
            trace.emit({"event": "loop_end", "turn": turn,
                        "finished": True, "summary": finish_summary})
            return True, finish_summary

    # Hit max iterations.
    trace.emit({"event": "force_finish", "reason": f"hit max_iterations={max_iterations}"})
    finish_summary = (f"(force-finished after {max_iterations} iterations — "
                      "agent did not call finish)")
    ctx.doc.changelog.append(ChangelogEntry(
        turn=max_iterations, tool="(forced)", section_index=None,
        dimension=None, reason=finish_summary,
    ))
    return False, finish_summary


# ── Changelog rendering & sanity checks ───────────────────────────────────────

def render_changelog(doc: WorkingDoc, finish_summary: str, *,
                     model: str, turns_used: int, finished_cleanly: bool,
                     warnings: list[str]) -> str:
    lines = [
        f"# {doc.title} — Polish Changelog",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by polish.py",
        f"Model: {model} | Turns used: {turns_used} | "
        f"Finished cleanly: {finished_cleanly}",
    ]
    if warnings:
        lines += ["", "## ⚠ Warnings", ""]
        lines += [f"- {w}" for w in warnings]
    lines += ["", "## Agent's final summary", "", f"> {finish_summary}" if finish_summary else "(none)", ""]

    if not doc.changelog:
        lines += ["## Edits", "", "(no edits or critiques recorded)", ""]
        return "\n".join(lines)

    lines += ["## Edits & critiques", ""]
    for i, e in enumerate(doc.changelog, 1):
        header_bits = [f"### #{i} — turn {e.turn} — {e.tool}"]
        if e.section_index is not None:
            header_bits.append(f"section {e.section_index}")
        if e.dimension:
            header_bits.append(e.dimension)
        lines.append(" — ".join(header_bits))
        if e.diff_summary:
            lines.append(f"_{e.diff_summary}_")
        if e.recap_quote:
            lines.append("")
            lines.append(f"**Recap quote:** > {e.recap_quote}")
        lines.append("")
        lines.append(e.reason)
        lines.append("")
    return "\n".join(lines)


def sanity_check(doc: WorkingDoc, roster_names: set[str]) -> list[str]:
    warnings: list[str] = []
    seen_indices = []
    for s in doc.sections:
        seen_indices.append(s.index)
        if not s.narrator:
            warnings.append(f"section {s.index}: empty narrator")
        elif s.narrator.lower() not in roster_names:
            warnings.append(
                f"section {s.index}: narrator {s.narrator!r} not in roster"
            )
        if not s.text.strip():
            warnings.append(f"section {s.index}: empty body")
    expected = list(range(1, len(doc.sections) + 1))
    if seen_indices != expected:
        warnings.append(
            f"section indices not contiguous 1..N: got {seen_indices}, "
            f"expected {expected}"
        )
    return warnings


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agentic review/polish pass on an assembled session document.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("doc", help="Assembled session-doc.md to review")
    parser.add_argument("--recap", required=True,
                        help="GMassistant recap (authoritative source of events)")
    parser.add_argument("--voice-dir", required=True,
                        help="Directory containing per-character voice files")
    parser.add_argument("--party", required=True,
                        help="party.md (used to extract canonical narrator roster)")
    parser.add_argument("--context", nargs="*", default=[],
                        help="Optional grounding docs (loaded lazily on demand)")
    parser.add_argument("--output", required=True,
                        help="Path to write the rewritten v2 doc")
    parser.add_argument("--changelog", required=True,
                        help="Path to write the structured changelog")
    parser.add_argument("--trace", default=None,
                        help="Directory for the JSONL trace file (default: <output_dir>/logs/)")
    parser.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS,
                        help=f"Hard cap on agent loop turns (default {DEFAULT_MAX_ITERATIONS})")
    parser.add_argument("--config", default=find_default_config(__file__))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--no-log", action="store_true",
                        help="Skip the run-summary log in <output_dir>/logs/")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every turn's text blocks as they arrive")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the system prompt and tool inventory, then exit")
    args = parser.parse_args()

    # Load config (not strictly needed but matches every other CLI's UX)
    try:
        load_config(args.config)
    except FileNotFoundError:
        pass  # OK — polish.py doesn't require config.yaml content

    doc_path = Path(args.doc).expanduser().resolve()
    recap_path = Path(args.recap).expanduser().resolve()
    voice_dir = Path(args.voice_dir).expanduser().resolve()
    party_path = Path(args.party).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    changelog_path = Path(args.changelog).expanduser().resolve()

    for p, label in [(doc_path, "doc"), (recap_path, "recap"),
                     (party_path, "party")]:
        if not p.exists():
            print(f"Error: {label} not found: {p}", file=sys.stderr)
            sys.exit(1)
    if not voice_dir.is_dir():
        print(f"Error: voice-dir is not a directory: {voice_dir}", file=sys.stderr)
        sys.exit(1)

    context_paths: dict[str, Path] = {}
    for c in args.context:
        cp = Path(c).expanduser().resolve()
        if not cp.exists():
            print(f"Error: context doc not found: {cp}", file=sys.stderr)
            sys.exit(1)
        context_paths[cp.stem] = cp

    # Parse the input doc.
    doc = WorkingDoc.parse(doc_path.read_text(encoding="utf-8"))
    if not doc.sections:
        print(f"Error: no sections found in {doc_path}", file=sys.stderr)
        sys.exit(1)

    recap_text = recap_path.read_text(encoding="utf-8")
    voices = load_voice_files(voice_dir)
    party_text = party_path.read_text(encoding="utf-8")
    roster_text = extract_character_roster(party_text)
    roster_names = {
        m.group(1).lower()
        for line in roster_text.splitlines()
        for m in [re.match(r"^- ([^(:]+?)\s*[\(:]", line)] if m
    }
    if not roster_names:
        # Fallback: every "## Name" header in party.md
        roster_names = {
            m.group(1).strip().lower()
            for m in re.finditer(r"^## (.+)$", party_text, re.MULTILINE)
        }

    system = build_system_prompt(roster_text, sorted(context_paths), args.max_iterations)

    print(f"Polish run — model: {args.model} | max_iter: {args.max_iterations}")
    print(f"  doc:       {doc_path}  ({len(doc.sections)} sections)")
    print(f"  recap:     {recap_path}  ({len(recap_text):,} chars)")
    print(f"  voice-dir: {voice_dir}  ({len(voices)} voice files)")
    print(f"  party:     {party_path}  (roster: {sorted(roster_names)})")
    print(f"  context:   {sorted(context_paths) or '(none)'}")
    print(f"  output:    {output_path}")
    print(f"  changelog: {changelog_path}")

    if args.dry_run:
        print("\n=== SYSTEM PROMPT ===")
        print(system)
        print("\n=== TOOL INVENTORY ===")
        for t in TOOL_SCHEMAS:
            print(f"  - {t['name']}: {t['description'][:80]}")
        print("\n(dry-run — exiting before API call)")
        return

    # Set up trace.
    trace_dir = Path(args.trace).expanduser().resolve() if args.trace \
        else output_path.parent / "logs"
    trace_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    trace_path = trace_dir / f"{timestamp}_polish_trace.jsonl"
    trace = TraceWriter(trace_path)
    trace.emit({
        "event": "run_start",
        "model": args.model,
        "max_iterations": args.max_iterations,
        "doc": str(doc_path), "recap": str(recap_path),
        "section_count": len(doc.sections),
        "voice_files": len(voices),
        "roster": sorted(roster_names),
    })

    ctx = ToolContext(
        doc=doc, recap_text=recap_text, voices=voices,
        context_docs={}, context_paths=context_paths,
        roster_names=roster_names, current_turn=0,
    )

    client = make_client()

    print(f"\nTrace: {trace_path}")
    print("=" * 60)

    finished, finish_summary = run_agent_loop(
        client, system=system, ctx=ctx, model=args.model,
        max_iterations=args.max_iterations, trace=trace, verbose=args.verbose,
    )

    print("=" * 60)
    print(f"Loop ended — finished_cleanly={finished}")
    print(f"Edits/critiques recorded: {len(doc.changelog)}")

    # Sanity check the rewritten doc before writing.
    warnings = sanity_check(doc, roster_names)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc.render(), encoding="utf-8")
    print(f"v2 doc:    {output_path}")

    changelog_path.parent.mkdir(parents=True, exist_ok=True)
    changelog_md = render_changelog(
        doc, finish_summary, model=args.model,
        turns_used=ctx.current_turn,
        finished_cleanly=finished, warnings=warnings,
    )
    changelog_path.write_text(changelog_md, encoding="utf-8")
    print(f"changelog: {changelog_path}")

    if warnings:
        print(f"\n⚠ {len(warnings)} structural warning(s) — see top of changelog")
        for w in warnings:
            print(f"  - {w}")

    trace.emit({"event": "run_end", "finished_cleanly": finished,
                "edits": len(doc.changelog), "warnings": warnings})
    trace.close()

    if not args.no_log:
        log_sections = [
            ("System Prompt", system),
            ("Final Summary", finish_summary or "(none)"),
            ("Changelog", changelog_md),
        ]
        log_file = save_log(str(output_path.parent / "logs"), log_sections, stem="polish")
        print(f"log:       {log_file}")


if __name__ == "__main__":
    main()
