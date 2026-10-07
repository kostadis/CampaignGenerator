"""PROTOTYPE: world_state's Key NPCs rendered from the PUBLISHED NPC dossiers (docs/npcs/<slug>.md).

The dossier is the one authority for an NPC (verified by npc-verify, published by the GM, carrying the GM's
manual edits). world_state renders from it instead of re-deriving it, so fixing an NPC is done once, in the
dossier.

    code selects (published, in-range, verify: pass; ordered by last seen)
      -> code extracts ONLY "## Identity" and "## Last Observed State" (Secrets can never be read)
      -> model renders one line per NPC (no selection, no ordering)
      -> code verifies each line (exactly one per NPC, citations from that NPC's dossier, quotes verbatim)
         and falls back to the dossier's own first Last-Observed-State sentence when a line fails

    python npcs_from_dossiers.py --campaign DIR --run RUN_DIR [--base world_state.budgeted.md] [--budget 900]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from campaignlib import client_from_args  # noqa: E402
from pipelines.summary_native import npc_check  # noqa: E402
import chunked_state as cs  # noqa: E402

HERE = Path(__file__).resolve().parent
TAKE = ("## Identity", "## Last Observed State")  # the ONLY sections read; Secrets is structurally unreachable
PUB_RE = re.compile(r"<!-- published by summary_native npc-publish \| source: summary_native \| npc: (.+?) \| range: (ch\d{3}-\d{3}) .*?\| verify: ([a-z()]+)")
ENTRY_CITE_RE = re.compile(r"(ch \d{3} / )entry\b")


@dataclass
class Dossier:
    name: str
    path: Path
    last_seen: int
    n_entries: int
    identity: str
    state: str

    @property
    def source(self) -> str:
        return f"{self.identity}\n{self.state}"


def norm(text: str) -> str:
    """A dossier cites an NPC's own entry as `entry`; world_state calls the same section `npcs`."""
    return ENTRY_CITE_RE.sub(r"\1npcs", text)


def load_published(campaign: Path, rng: str) -> tuple[list[Dossier], list[str]]:
    out, skipped = [], []
    for p in sorted((campaign / "docs" / "npcs").glob("*.md")):
        text = p.read_text(encoding="utf-8")
        m = PUB_RE.search(text.split("\n", 1)[0])
        if not m:
            skipped.append(f"{p.name}: not a summary_native publication")
            continue
        name, r, verdict = m.groups()
        if r != rng:
            skipped.append(f"{p.name}: range {r}, not {rng}")
            continue
        if verdict != "pass":
            skipped.append(f"{p.name}: verify {verdict}")
            continue
        fm = re.search(r"^last_seen: (\d+)$", text, re.M)
        ne = re.search(r"^n_entries: (\d+)$", text, re.M)
        secs = npc_check.parse_sections(text)
        ident, state = (norm(npc_check.section_text(secs, h)) for h in TAKE)
        if not state:
            skipped.append(f"{p.name}: no Last Observed State")
            continue
        out.append(Dossier(name, p, int(fm.group(1)) if fm else 0, int(ne.group(1)) if ne else 0, ident, state))
    out.sort(key=lambda d: (-d.last_seen, -d.n_entries, d.name.casefold()))
    return out, skipped


def first_sentence(text: str) -> str:
    """The first sentence of ``text``, keeping the citation(s) that close it."""
    m = re.match(r"(.+?[.!?](?:\s*\[ch [^\]]+\])*)(?:\s|$)", text.strip(), re.S)
    s = (m.group(1) if m else text.strip()).replace("\n", " ")
    if not cs.cites(s):
        c = cs.CITE_BRACKET_RE.search(text)
        s = s.rstrip(".") + (f" {c.group(0)}." if c else ".")
    return s


def verify_line(line: str, d: Dossier, hay: str, max_words: int) -> str | None:
    if not line.startswith(f"- **{d.name}**"):
        return "does not start with the NPC's exact name"
    src = {(c, t) for _, c, t in cs.cites(d.source)}
    got = [(b, c, t) for b, c, t in cs.cites(line)]
    if not got:
        return "uncited"
    bad = [b for b, c, t in got if (c, t) not in src]
    if bad:
        return f"citation not in this NPC's dossier: {bad[0]}"
    for span in npc_check.SPAN_RE.findall(line):
        inner = npc_check.strip_quote_marks(span)
        if len(inner) >= 4 and npc_check._contains(d.source, inner) is None and npc_check._contains(hay, inner) is None:
            return f"quotation not verbatim: {span}"
    words = len(re.sub(r"\[ch [^\]]*\]", "", line).split())
    if words > 2 * max_words:
        return f"too long ({words} words)"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--base", default="world_state.budgeted.md")
    ap.add_argument("--range", default="ch002-070")
    ap.add_argument("--budget", type=int, default=900, help="words for the whole Key NPCs section")
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V4-Flash-0731")
    ap.add_argument("--endpoint", default=cs.ENDPOINT)
    ap.add_argument("--max-tokens", type=int, default=8000)
    args = ap.parse_args()
    cs.MODEL = args.model

    dossiers, skipped = load_published(args.campaign, args.range)
    if not dossiers:
        print("Error: no published, verified dossiers for this range", file=sys.stderr)
        return 2
    per = max(15, args.budget // len(dossiers))
    hay = "\n".join(c.text for c in cs.load_chapters(args.campaign / "docs" / "summaries", 2, 70))
    blocks = "\n\n".join(f"### {d.name} (last seen ch {d.last_seen:03d})\nIDENTITY: {d.identity}\nLAST OBSERVED STATE: {d.state}"
                         for d in dossiers)
    system = (HERE / "prompts" / "npc_lines.system.md").read_text(encoding="utf-8")
    user = (f"{len(dossiers)} NPCs, in this order. At most {per} words per line (citations not counted).\n\n{blocks}\n\n"
            "Write exactly one line per NPC, in the same order, each starting `- **<name exactly as given>** — `.\n")
    problem = cs.preflight([args.endpoint])
    if problem:
        print(f"Error: {problem}", file=sys.stderr)
        return 2
    client = client_from_args(argparse.Namespace(backend="dgx", endpoint=args.endpoint, model=args.model))
    raw, secs = cs.call(client, system, user, args.max_tokens)
    cs.dump(args.run / "npc_lines.raw.md", raw)

    got = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("- **")]
    lines, report = [], []
    for d in dossiers:
        cand = next((ln for ln in got if ln.startswith(f"- **{d.name}**")), None)
        why = "missing from the model's output" if cand is None else verify_line(cand, d, hay, per)
        if why:
            fb = first_sentence(d.state)
            if not cs.cites(fb):  # e.g. "Status not established in the summaries." — lead with cited identity
                fb = f"{first_sentence(d.identity)} {fb}"
            lines.append(f"- **{d.name}** — {fb}")
            report.append(f"- {d.name}: fallback to the dossier's own sentence ({why})")
        else:
            lines.append(cand)
    extra = [ln for ln in got if not any(ln.startswith(f"- **{d.name}**") for d in dossiers)]
    report += [f"- discarded (not a published NPC): {ln[:100]}" for ln in extra]

    body = ("\n".join(lines) + "\n\n_Source: the published NPC dossiers in `docs/npcs/` "
            f"({len(dossiers)}, verified, ordered by last seen). Fix an NPC in its dossier, not here._")
    base = (args.run / args.base).read_text(encoding="utf-8")
    head, rest = base.split("## Key NPCs\n", 1)
    tail = rest[rest.index("\n## "):] if "\n## " in rest else ""
    out = head + "## Key NPCs\n" + body + "\n" + tail
    cs.dump(args.run / "world_state.dossiers.md", out)
    rep = ["# Key NPCs from dossiers", "", f"{len(dossiers)} published dossiers used, {per} words/line, render {secs:.0f}s.",
           f"{len(dossiers) - sum(1 for r in report if 'fallback' in r)} lines from the model, "
           f"{sum(1 for r in report if 'fallback' in r)} fallbacks.", "", "## Used (order)", ""]
    rep += [f"- {d.name} (last seen ch {d.last_seen:03d}) — {d.path.name}" for d in dossiers]
    rep += ["", "## Fallbacks and discards", ""] + (report or ["(none)"])
    rep += ["", "## Not used", ""] + ([f"- {s}" for s in skipped] or ["(none)"])
    cs.dump(args.run / "npc_lines_report.md", "\n".join(rep) + "\n")
    print(f"wrote world_state.dossiers.md ({len(dossiers)} NPCs; {len(report)} fallbacks/discards; {len(skipped)} not used)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
