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
    ("session_doc.enhance_summary",  "ENHANCE_SYSTEM_PREFIX",            "enhance_summary"),
    ("session_doc.enhance_summary",  "ENHANCE_USER_TEMPLATE",            "enhance_summary_user"),
    ("session_doc.scene_extract",    "SCENE_EXTRACT_SYSTEM_PREFIX",      "scene_extract"),
    ("session_doc.scene_extract",    "SCENE_EXTRACT_USER_TEMPLATE",      "scene_extract_user"),
    ("pipelines.grounding.distill",          "EXTRACT_SYSTEM_BASE",              "distill_extract"),
    ("pipelines.grounding.distill",          "SYNTHESIZE_SYSTEM_BASE",           "distill_synthesize"),
    ("pipelines.grounding.planning",         "EXTRACT_SYSTEM_BASE",              "planning_extract"),
    ("pipelines.grounding.planning",         "SYNTHESIZE_SYSTEM_BASE",           "planning_synthesize"),
    ("pipelines.grounding.planning",         "BUILD_EXTRACT_SYSTEM",             "planning_build_extract"),
    ("pipelines.grounding.planning",         "BUILD_SYNTHESIZE_SYSTEM",          "planning_build_synthesize"),
    ("pipelines.grounding.party",            "EXTRACT_SYSTEM_BASE",              "party_extract"),
    ("pipelines.grounding.party",            "SYNTHESIZE_SYSTEM_BASE",           "party_synthesize"),
    ("pipelines.grounding.campaign_state",   "EXTRACT_SYSTEM_BASE",              "campaign_state_extract"),
    ("pipelines.grounding.campaign_state",   "EXTRACT_TRACKED_SECTION",          "campaign_state_extract_tracked"),
    ("pipelines.grounding.campaign_state",   "SYNTHESIZE_SYSTEM_BASE",           "campaign_state_synthesize"),
    ("pipelines.grounding.campaign_state",   "SYNTHESIZE_TRACKED_SECTION",       "campaign_state_synthesize_tracked"),
    ("pipelines.ensemble.facts_to_state",   "AGGREGATE_SYSTEM",                 "state_aggregate"),
    ("pipelines.ensemble.polish",           "SYSTEM_PROMPT_TEMPLATE",           "polish"),
    ("campaignlib.citations", "CITATION_RULES_EXTRACT",      "citation_rules_extract"),
    ("campaignlib.citations", "CITATION_RULES_SYNTHESIZE",   "citation_rules_synthesize"),
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
    #   - narrate_scene.md, loaded the same way via `narrate_chapter.py
    #     --agent` (issue #202 part 2 — the narrative pass is a sibling
    #     artifact, not a sixth extraction lens, but it borrows the same
    #     load-by-name convention).
    #   - the #213 grounding-projection prompts, each read at its call site
    #     with load_agent_prompt(<name>) and never bound to a module-level
    #     constant, so the identity check above has nothing to compare:
    #       planning_npc_outlook -> grounding_sections.render_outlook_block
    #       tracking_completion  -> grounding_sections.render_tracking
    #       thread_speculate     -> thread_registry (speculation surface)
    session_doc_files = {p for p in actual if p.startswith("session_doc/")}
    prep_files = {"lore_oracle.md", "encounter_architect.md", "voice_keeper.md"}
    ensemble_files = {p for p in actual if p.startswith("extract_facts")}
    narrate_files = {"narrate_scene.md"}
    projection_files = {"planning_npc_outlook.md", "tracking_completion.md",
                        "thread_speculate.md"}
    relevant = (actual - session_doc_files - prep_files - ensemble_files
                - narrate_files - projection_files)
    assert expected == relevant, (
        f"Phase-3 CASES table out of sync with config/agents/.\n"
        f"  in CASES but not on disk: {sorted(expected - relevant)}\n"
        f"  on disk but not in CASES: {sorted(relevant - expected)}"
    )


def test_every_load_by_name_prompt_resolves_to_a_file():
    """The load-by-name prompts excluded above still have to exist.

    ``load_agent_prompt("thread_speculate")`` is a bare runtime string: no
    import, no constant, no reference the CASES identity check can follow. So
    renaming or deleting the .md is invisible to every other test here and
    surfaces only when a GM runs the pipeline and pays for the trip.

    Rather than hard-code a second list that would drift out of sync the same
    way CASES did, scan the source for literal load_agent_prompt("...") calls
    and assert each one resolves. Non-literal calls (``--agent`` dispatch,
    where the name is a CLI argument) are skipped — there is no static name to
    check.
    """
    import ast

    agents_dir = ROOT / "config" / "agents"
    missing, checked = [], 0
    for py in ROOT.rglob("*.py"):
        rel = py.relative_to(ROOT).as_posix()
        if rel.startswith((".claude/", "tests/", "build/")):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name != "load_agent_prompt" or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue  # dynamic --agent dispatch; nothing static to verify
            checked += 1
            if not (agents_dir / f"{first.value}.md").is_file():
                missing.append(f"{rel}:{node.lineno} -> config/agents/{first.value}.md")

    assert checked, "found no literal load_agent_prompt(...) calls — scan is broken"
    assert not missing, "load_agent_prompt names with no file on disk:\n  " + "\n  ".join(missing)
