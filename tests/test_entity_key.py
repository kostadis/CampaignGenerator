"""#213 Phase 1.2 — lens prompts ask for `entity`; the pipeline keeps `subject`.

The A/B/C/D experiment on the ch41 boar chunk showed the filing failure
(deaths recorded only under event headlines) is closed by the dual-write
rule, with the entity rename improving its reliability. The rename lives in
the prompts; parse_facts_block normalises at the single parse boundary so
merged.json and every downstream consumer are unchanged.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipelines.ensemble.extract_facts import parse_facts_block  # noqa: E402

AGENTS = REPO / "config" / "agents"


def test_entity_key_normalised_to_subject():
    raw = json.dumps([
        {"type": "monster", "entity": "boar", "fact": "The boar is dead.",
         "source_quote": "finishes the boar"},
        {"type": "event", "subject": "boar killed", "fact": "Killed.",
         "source_quote": ""},   # old key still accepted (caches, old prompts)
    ])
    facts = parse_facts_block(raw)
    assert facts[0]["subject"] == "boar"
    assert "entity" not in facts[0]
    assert facts[1]["subject"] == "boar killed"


def test_subject_wins_when_both_keys_present():
    raw = json.dumps([{"type": "npc", "subject": "Prutha", "entity": "wrong",
                       "fact": "x", "source_quote": ""}])
    assert parse_facts_block(raw)[0]["subject"] == "Prutha"


def test_lens_prompts_ask_for_entity_not_subject():
    for name in ("extract_facts.md", "extract_facts_sweep.md",
                 "extract_facts_temporal.md", "extract_facts_interiority.md"):
        text = (AGENTS / name).read_text(encoding="utf-8")
        assert "`entity`" in text, name
        assert "subject" not in text.lower(), name


def test_factual_lenses_carry_dual_write_rule():
    for name in ("extract_facts.md", "extract_facts_sweep.md",
                 "extract_facts_temporal.md"):
        text = (AGENTS / name).read_text(encoding="utf-8")
        assert "State changes write twice" in text, name
    # interiority is inner-life only — no dual-write rule on purpose
    assert "State changes write twice" not in (
        AGENTS / "extract_facts_interiority.md").read_text(encoding="utf-8")
