"""``delta rebase propose``: the ONLY model call in the rebase family (spec 040, T014, research R5, R7).

The model drafts a replacement for each affected baseline line.  It sees exactly three things, and the
record says so: the affected lines, the changed or removed entries of the selected chapters (old and current
text), and the affected retained annotations.  It is never shown the other lines of the documents, the other
chapters, or any other source.

Its output is parsed into DRAFT ``source_correction`` proposals (origin ``model``) through the existing
grounding edit model, which validates every one (an unknown line id, a duplicate target or a stale line is
rejected and recorded).  Nothing is approved here: the GM decides each with ``delta grounding decide``.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path

from types import SimpleNamespace

from campaignlib import stream_api
from campaignlib.api.client import client_from_args

from . import custody_store, grounding_edits
from .errors import EXIT_REFUSAL, DeltaRefusal
from .rebase import RebaseState, baseline_docs, build_repair, load_state, require_fresh
from .rebase_impact import AffectedLine, find_line
from .records_io import write_json

SYSTEM_PROMPT = """You draft replacement lines for a campaign's grounding documents after a session summary \
was corrected. You are shown ONLY: the grounding lines that cite a corrected entry (each with a line id), \
the old and corrected text of the changed entries, and any affected claim annotations. You decide nothing: a \
person approves, rejects or holds every line you draft.

Rules:
- Reply about a line only by its line id, exactly as shown.
- after_text is ONE line that replaces the line, keeps its `[ch NNN / entry]` citation, and states only what \
the corrected text supports. Do not add facts, numbers or names that are not in the corrected text.
- If the corrected text no longer supports the line at all, still draft the closest supported wording and say so \
in the reason.
Reply with ONE JSON object and nothing else:
{"repairs":[{"line_id":"...","after_text":"...","reason":"..."}],"empty_justification":null}"""


def _entry_text(data: bytes, span: tuple[int, int] | None) -> str:
    return data[span[0]:span[1]].decode("utf-8", "replace") if span else ""


def _entry_diffs(state: RebaseState, chapters: set[int]) -> tuple[str, list[int]]:
    parts: list[str] = []
    used: list[int] = []
    for s in state.impact.sources:
        if s.chapter not in chapters:
            continue
        old = custody_store.get(state.root, state.snapshot(s.chapter, "old").sha256) or b""
        new = custody_store.get(state.root, state.snapshot(s.chapter, "current").sha256) or b""
        for e in s.entries:
            if e.status not in ("changed", "removed"):
                continue
            used.append(s.chapter)
            diff = "".join(difflib.unified_diff(
                _entry_text(old, e.old_span).splitlines(keepends=True),
                _entry_text(new, e.new_span).splitlines(keepends=True), "old", "corrected"))
            parts.append(f"### ch {s.chapter:03d} / {e.entry} ({e.status})\n{diff or '(entry removed)'}")
    return "\n".join(parts), sorted(set(used))


def build_prompt(state: RebaseState, docs, lines: list[AffectedLine]) -> tuple[str, dict]:
    """The model's whole input and the record of its sources."""
    ids = {l.line_id for l in lines}
    chapters = {a.chapter for a in state.impact.affected_lines if a.line_id in ids}
    body = ["## Affected grounding lines (line id <TAB> text)\n"]
    for l in lines:
        found = find_line(docs, l.line_id)
        text = found[2].decode("utf-8", "replace").rstrip("\r\n") if found else ""
        body.append(f"{l.line_id}\t{text}\t[affected: {l.reason}, cites {l.citation}]")
    diffs, diffed = _entry_diffs(state, chapters)
    body += ["", "## Changed entries (old -> corrected)\n", diffs]
    notes = [a for a in state.impact.affected_annotations if a.chapter in chapters]
    if notes:
        body += ["", "## Affected claim annotations\n"] + [
            f"{a.annotation_id}\tspan {a.span}\tchapter {a.chapter}" for a in notes]
    sources = {"affected_lines": [l.line_id for l in lines], "entry_diffs": diffed,
               "annotations": [a.annotation_id for a in notes]}
    return "\n".join(body), sources


def parse_output(text: str) -> dict:
    body = text.strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*?)\n```$", body, re.S)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except ValueError as exc:
        raise DeltaRefusal(f"the model's repair output is not valid JSON ({exc}); nothing was saved",
                           EXIT_REFUSAL) from exc
    if not isinstance(value, dict) or not isinstance(value.get("repairs", []), list):
        raise DeltaRefusal("the model's repair output has no 'repairs' list; nothing was saved", EXIT_REFUSAL)
    return value


def propose(root: Path | str, plan_id: str, *, backend: str | None, model: str, client=None,
            max_tokens: int = 8000) -> dict:
    """One model call over the affected baseline lines; saves DRAFT proposals and a ``propose-r<N>.json`` record."""
    state = load_state(root, plan_id)
    require_fresh(state)
    docs = baseline_docs(state)
    existing = grounding_edits.live_target_ids(state.root, plan_id)
    candidates: list[AffectedLine] = []
    skipped: list[dict] = []
    offered: set[str] = set()  # a line citing two corrected chapters has one impact record per chapter
    for l in state.impact.affected_lines:
        if l.origin != "baseline" or l.line_id in offered:
            continue
        offered.add(l.line_id)
        found = find_line(docs, l.line_id)
        tid = grounding_edits.line_target_id(found[0], found[1], found[2]) if found else None
        if tid in existing:
            skipped.append({"line_id": l.line_id, "reason": "already has a proposal"})
            continue
        candidates.append(l)
    if not candidates:
        raise DeltaRefusal("no affected baseline line without a proposal; nothing to draft "
                           "(`delta rebase show` lists the lines and their state)", EXIT_REFUSAL)
    user, sources = build_prompt(state, docs, candidates)
    if client is None:
        client = client_from_args(SimpleNamespace(backend=backend, model=model, endpoint=None))
    raw = stream_api(client, SYSTEM_PROMPT, user, model, max_tokens=max_tokens, silent=True)
    value = parse_output(raw)
    allowed = {l.line_id: l for l in candidates}
    drafts, rejected = [], []
    seen: set[str] = set()
    for item in value.get("repairs", []):
        lid = str(item.get("line_id", "?")) if isinstance(item, dict) else "?"
        try:
            text = str(item["after_text"]).rstrip("\r\n")
            reason = str(item.get("reason", "")).strip() or "model draft (no reason given)"
        except (KeyError, TypeError, AttributeError):
            rejected.append({"line_id": lid, "reason": "malformed repair"})
            continue
        if lid not in allowed:
            rejected.append({"line_id": lid, "reason": "not an affected line offered to the model"})
        elif lid in seen:
            rejected.append({"line_id": lid, "reason": "duplicate line id"})
        elif not text.strip() or "\n" in text:
            rejected.append({"line_id": lid, "reason": "after_text must be one non-empty line"})
        else:
            seen.add(lid)
            drafts.append(build_repair(docs, state, allowed[lid], text, reason, origin="model", author=None))
    saved = None
    if drafts:
        saved = grounding_edits.append_proposals(
            state.root, plan_id, state.plan.grounding_baseline_ref or "", docs, drafts, supersede_rejected=True,
            generated_by={"backend": backend or "", "model": model})
    revision = (_latest_revision(state) or 0) + 1
    record = {"rebase_id": state.rebase_id, "plan_id": plan_id, "revision": revision,
              "backend": backend, "model": model, "model_calls": 1, "model_input_sources": sources,
              "prompt_sha256": hashlib.sha256((SYSTEM_PROMPT + "\n" + user).encode("utf-8")).hexdigest(),
              "proposals": [d.proposal_id for d in drafts], "rejected": rejected, "skipped": skipped,
              "approved": 0}
    write_json(state.directory / f"propose-r{revision}.json", record)
    return {**record, "call_counts": {"model": 1}, "status": "draft",
            "proposals_revision": saved.revision if saved else None}


def _latest_revision(state: RebaseState) -> int | None:
    found = []
    for p in state.directory.glob("propose-r*.json"):
        m = re.fullmatch(r"propose-r(\d+)\.json", p.name)
        if m:
            found.append(int(m.group(1)))
    return max(found) if found else None
