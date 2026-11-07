"""Spec 039 T007/T014: full-mode ``npc_verify.verify`` output is frozen against a golden.

The golden was captured from the verifier BEFORE the evidence-index refactor (T013) and must
never be regenerated to hide a diff. Run the fixture's real drafts and a synthetic draft that
carries every kind of citation through the real entry point in full mode.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipelines.summary_native import npc_link, npc_verify, parse

FIXTURE = Path(__file__).parent / "fixtures" / "delta"
CAMPAIGN = FIXTURE / "campaign"
GOLDEN = FIXTURE / "golden"
SUMMARIES = CAMPAIGN / "docs" / "summaries"
NPC_DIR = CAMPAIGN / "docs" / "npcs" / "summary_native"

# (label, draft path, subject, evidence keywords, last in-range chapter)
CASES = (
    ("brannoc (fixture draft)", NPC_DIR / "ch001-002/draft/npc_brannoc_ironvein.md", "Brannoc Ironvein", ("Brannoc", "Ironvein"), 2),
    ("sella (fixture draft)", NPC_DIR / "ch001-001/draft/npc_envoy_sella_marr.md", "Envoy Sella Marr", ("Sella",), 1),
    ("synthetic citation kinds", GOLDEN / "draft_citations.md", "Brannoc Ironvein", ("Brannoc", "Ironvein"), 2),
)


def _files(until: int):
    files = [parse.parse_file(p, CAMPAIGN) for p in sorted(SUMMARIES.glob("*.md"))]
    return [f for f in files if f.prefix_chapter is not None and f.prefix_chapter <= until]


def _evidence_body(files, subject: str, keywords) -> str:
    """The NPC's evidence dossier body, built from the fixture summaries by keyword."""
    parts = [f"---\nsubject: {subject}\n---\n\n# NPC - {subject}\n"]
    for pf in files:
        ch = pf.title_chapter if pf.title_chapter is not None else pf.prefix_chapter
        block = []
        for e in pf.entities:
            if e.heading == subject:
                block.append(f"\n### Entry - {e.heading}\n- Source: {pf.path} (line {e.line})\n\n{e.body.strip()}\n")
        for it in npc_link.iter_items(pf):
            if any(k in it.text for k in keywords):
                if it.kind == "scene":
                    block.append(f"\n### Scene {it.scene_id} - {it.title} (mentioned)\n- Source: {it.source_file} (line {it.line})\n\n{it.text}\n")
                else:
                    block.append(f"\n### Moment (mentioned)\n- Source: {it.source_file} (line {it.line})\n- Scene: none\n\n{it.text}\n")
        if block:
            parts.append(f"\n## Chapter {int(ch):03d}\n" + "".join(block))
    return "".join(parts)


def _normalise(text: str) -> str:
    # The report carries no timestamps; strip any absolute path defensively, identically every run.
    return re.sub(r"/[^\s]*?/tests/fixtures/delta", "<fixture>", text)


def render_golden() -> str:
    out = []
    for label, draft_path, subject, keywords, until in CASES:
        files = _files(until)
        index = npc_verify.CorpusIndex.from_parsed(files)
        summaries = npc_verify.load_summaries_text(pf_path for pf_path in sorted(SUMMARIES.glob("*.md"))[:until])
        draft = draft_path.read_text(encoding="utf-8")
        result = npc_verify.verify(draft, _evidence_body(files, subject, keywords), index, summaries, [])
        out.append(f"=== {label} ===\n{npc_verify.render_verify_md(result, subject)}")
    return _normalise("\n".join(out))


def test_full_mode_verifier_output_matches_golden():
    assert render_golden() == (GOLDEN / "verify_full.md").read_text(encoding="utf-8")


def test_golden_exercises_citation_check():
    text = (GOLDEN / "verify_full.md").read_text(encoding="utf-8")
    assert "invalid (" in text and "outside-evidence (" in text
    assert "- citations:" in text
