"""Renderers for the events to answer, the NPC's state and context, and the dossier check.

Byte-deterministic.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json

from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent.presence import SIGNALS, Candidate, Check, context, events, snapshots


def _row(c: Candidate) -> dict:
    return {
        "item_id": c.item.item_id,
        "kind": c.item.kind,
        "chapter": c.item.chapter,
        "source_file": c.item.source_file,
        "line": c.item.line,
        "title": c.item.title,
        "signals": list(c.signals),
        "forms_matched": list(c.forms_matched),
        "match_lines": list(c.match_lines),
        "text": c.item.text,
    }


def candidates_json(d: Dossier, ms: list[Candidate]) -> str:
    """``ms`` is every mention; the JSON separates what is answered from what is not."""
    doc = {
        "subject": d.subject,
        "dossier": d.stem,
        "forms": list(d.forms),
        "events": [_row(c) for c in events(ms)],
        "snapshots": [_row(c) for c in snapshots(ms)],
        "context": [_row(c) for c in context(ms)],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _quote(text: str) -> str:
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def candidates_md(d: Dossier, ms: list[Candidate], check: Check) -> str:
    evs, snaps, ctx = events(ms), snapshots(ms), context(ms)
    counts = {s: sum(1 for c in evs if s in c.signals) for s in SIGNALS}
    out = [
        f"# Events to answer — {d.subject}",
        "",
        f"Every scene that names this NPC, by the dossier's exact forms ({', '.join(d.forms)}). "
        "A scene is an event; the GM answers each one *physically present*, *mentioned* or "
        "*neither / unsure*. Under each chapter, the NPC's own entry (state) and the summary "
        "prose and memorable moments that name them (context) are shown and never answered.",
        "",
        f"- Events to answer: {len(evs)} (signals: "
        f"{', '.join(f'{s} {counts[s]}' for s in SIGNALS if counts[s])})",
        f"- State entries: {len(snaps)} · context elements: {len(ctx)}",
        f"- Check against `{d.path.name}`: {'ok' if check.ok else 'MISMATCH'}",
        "",
    ]
    out += [f"  - {ln}" for ln in check.lines]
    for chapter in sorted({c.item.chapter for c in ms}):
        here = [c for c in evs if c.item.chapter == chapter]
        out += ["", f"## Chapter {chapter:03d} — {next(c.item.source_file for c in ms if c.item.chapter == chapter)}"]
        for c in here:
            out += ["", f"### {c.item.item_id} · {c.item.title}", "",
                    f"signals: {', '.join(c.signals)} · lines: {', '.join(map(str, c.match_lines))}",
                    "", _quote(c.item.text)]
        if not here:
            out += ["", "_No scene in this chapter names them._"]
        for label, group in (("State (their entry, not answered)", snaps), ("Context (not answered)", ctx)):
            g = [c for c in group if c.item.chapter == chapter]
            if g:
                out += ["", f"#### {label}", ""]
                out += [f"- {c.item.item_id} · {c.item.kind}: {c.item.text.splitlines()[0][:140]}" for c in g]
    return "\n".join(out).rstrip() + "\n"


def check_report_md(checks: list[Check], findings: tuple[str, ...]) -> str:
    bad = [c for c in checks if not c.ok]
    out = [
        "# Candidate check against the published dossiers",
        "",
        f"{len(checks)} NPC(s) checked; {len(bad)} mismatch(es).",
    ]
    if findings:
        out += ["", "## Corpus findings", ""] + [f"- {f}" for f in findings]
    for c in checks:
        out += ["", f"## {c.subject} — {'ok' if c.ok else 'MISMATCH'}", ""]
        out += [f"- {ln}" for ln in c.lines]
    return "\n".join(out).rstrip() + "\n"
