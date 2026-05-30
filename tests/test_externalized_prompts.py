"""Phase 3 regression guard for externalised prompts across all scripts.

Phase 3 moves 24 prompt constants out of 9 scripts into
config/agents/*.md. This test asserts every constant resolves to the
exact byte contents of its on-disk markdown file. Any drift between
the script's constant assignment and the file content (e.g. someone
edits the .md but the script still points at the wrong path) trips
this test.

For Phase 2's session_doc.py prompts, see test_session_doc_prompts.py
(which guards composition matrix, not just identity).
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CASES = [
    ("enhance_summary",  "ENHANCE_SYSTEM_PREFIX",            "enhance_summary"),
    ("enhance_summary",  "ENHANCE_USER_TEMPLATE",            "enhance_summary_user"),
    ("scene_extract",    "SCENE_EXTRACT_SYSTEM_PREFIX",      "scene_extract"),
    ("scene_extract",    "SCENE_EXTRACT_USER_TEMPLATE",      "scene_extract_user"),
    ("distill",          "EXTRACT_SYSTEM",                   "distill_extract"),
    ("distill",          "SYNTHESIZE_SYSTEM",                "distill_synthesize"),
    ("planning",         "EXTRACT_SYSTEM",                   "planning_extract"),
    ("planning",         "SYNTHESIZE_SYSTEM",                "planning_synthesize"),
    ("planning",         "BUILD_EXTRACT_SYSTEM",             "planning_build_extract"),
    ("planning",         "BUILD_SYNTHESIZE_SYSTEM",          "planning_build_synthesize"),
    ("party",            "EXTRACT_SYSTEM",                   "party_extract"),
    ("party",            "SYNTHESIZE_SYSTEM",                "party_synthesize"),
    ("campaign_state",   "EXTRACT_SYSTEM_BASE",              "campaign_state_extract"),
    ("campaign_state",   "EXTRACT_TRACKED_SECTION",          "campaign_state_extract_tracked"),
    ("campaign_state",   "SYNTHESIZE_SYSTEM_BASE",           "campaign_state_synthesize"),
    ("campaign_state",   "SYNTHESIZE_TRACKED_SECTION",       "campaign_state_synthesize_tracked"),
    ("narrative",        "PLAN_SYSTEM",                      "narrative/plan"),
    ("narrative",        "PLAN_SCENE_SYSTEM",                "narrative/plan_scene"),
    ("narrative",        "CHAR_EXTRACT_SYSTEM",              "narrative/char_extract"),
    ("narrative",        "NARRATE_SYSTEM_BASE",              "narrative/narrate_base"),
    ("narrative",        "EXAMPLES_BLOCK",                   "narrative/examples_block"),
    ("polish",           "SYSTEM_PROMPT_TEMPLATE",           "polish"),
    ("enhance_recap",    "CONSISTENCY_SYSTEM",               "enhance_recap_consistency"),
    ("enhance_recap",    "ENHANCE_SYSTEM",                   "enhance_recap_enhance"),
]


@pytest.mark.parametrize("module_name,const_name,prompt_path", CASES)
def test_constant_matches_markdown_file(module_name, const_name, prompt_path):
    mod = importlib.import_module(module_name)
    value = getattr(mod, const_name)
    on_disk = (ROOT / "config" / "agents" / f"{prompt_path}.md").read_text(
        encoding="utf-8"
    )
    assert value == on_disk, (
        f"{module_name}.{const_name} diverges from "
        f"config/agents/{prompt_path}.md"
    )


def test_all_externalised_prompts_listed():
    """Sanity: the CASES table covers every config/agents/*.md file we ship
    *except* the session_doc/ subtree (that lives in
    test_session_doc_prompts.py).
    """
    expected = {
        case[2] + ".md" for case in CASES
    }
    actual = {
        str(p.relative_to(ROOT / "config" / "agents")).replace("\\", "/")
        for p in (ROOT / "config" / "agents").rglob("*.md")
    }
    # Exclude prompts that scripts load dynamically by name (via
    # load_agent_prompt / load_file) instead of binding to a module-level
    # constant — the CASES identity check above structurally cannot apply to
    # them, there is no constant to compare against:
    #   - session_doc/ subtree (guarded by test_session_doc_prompts.py)
    #   - prep.py agents (lore_oracle, encounter_architect, voice_keeper)
    #   - the fact-extraction ensemble lenses (extract_facts*.md), loaded via
    #     `extract_facts.py --agent`.
    session_doc_files = {p for p in actual if p.startswith("session_doc/")}
    prep_files = {"lore_oracle.md", "encounter_architect.md", "voice_keeper.md"}
    ensemble_files = {p for p in actual if p.startswith("extract_facts")}
    relevant = actual - session_doc_files - prep_files - ensemble_files
    assert expected == relevant, (
        f"Phase-3 CASES table out of sync with config/agents/.\n"
        f"  in CASES but not on disk: {sorted(expected - relevant)}\n"
        f"  on disk but not in CASES: {sorted(relevant - expected)}"
    )
