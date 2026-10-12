"""Renderers for the candidate list and the dossier check. Byte-deterministic.

No model call (guarded by ``tests/test_npc_agent_no_llm.py``).
"""

from __future__ import annotations

import json

from pipelines.npc_agent.dossier import Dossier
from pipelines.npc_agent.presence import SIGNALS, Candidate, Check


def candidates_json(d: Dossier, cands: list[Candidate]) -> str:
    rows = [
        {
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
        for c in cands
    ]
    doc = {"subject": d.subject, "dossier": d.stem, "forms": list(d.forms), "candidates": rows}
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _quote(text: str) -> str:
    return "\n".join(f"> {ln}" if ln else ">" for ln in text.splitlines())


def candidates_md(d: Dossier, cands: list[Candidate], check: Check) -> str:
    counts = {s: sum(1 for c in cands if s in c.signals) for s in SIGNALS}
    kinds: dict[str, int] = {}
    for c in cands:
        kinds[c.item.kind] = kinds.get(c.item.kind, 0) + 1
    out = [
        f"# Presence candidates — {d.subject}",
        "",
        "Every item that names this NPC, by the dossier's exact forms "
        f"({', '.join(d.forms)}). **A candidate is a mention, never presence**: "
        "the signals are evidence for the GM's ruling, not a ruling.",
        "",
        f"- Candidates: {len(cands)} ({', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))})",
        f"- Signals: {', '.join(f'{s} {counts[s]}' for s in SIGNALS)}",
        f"- Check against `{d.path.name}`: {'ok' if check.ok else 'MISMATCH'}",
        "",
    ]
    out += [f"  - {ln}" for ln in check.lines]
    chapter = None
    for c in cands:
        it = c.item
        if it.chapter != chapter:
            chapter = it.chapter
            out += ["", f"## Chapter {chapter:03d} — {it.source_file}"]
        head = f"### {it.item_id} · {it.kind}"
        if it.title:
            head += f" · {it.title}"
        out += [
            "",
            head,
            "",
            f"signals: {', '.join(c.signals)} · forms: {', '.join(c.forms_matched)} · "
            f"lines: {', '.join(map(str, c.match_lines))}",
            "",
            _quote(it.text),
        ]
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
