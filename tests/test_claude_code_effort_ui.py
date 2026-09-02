"""Static UI reachability guardrails for the claude-code effort level.

Constitution Principle XI: every CLI capability ships its UI face in the same
feature, and a new claude-code-capable surface must not appear without one.

**What this proves and what it does not.** There is no frontend component-test
harness in this repo (issue #345), so these are source-level assertions: they
prove a control is present in the file, not that it renders, persists, or
round-trips. The quickstart's §7 manual steps cover that. The gap is stated
here rather than counted as coverage.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# The entry-point inventory FR-025 requires, in its UI half.
SELECTOR_OWNERS = (
    "frontend/src/components/layout/AppSidebar.vue",
    "frontend/src/components/shared/SelectionPanel.vue",
    "frontend/src/components/scene-editor/KnobDrawer.vue",
    "frontend/src/views/session/SessionDocEditor.vue",
    "frontend/src/views/ensemble/EnsembleSetup.vue",
    "frontend/src/views/ensemble/useEnsembleRun.ts",
)

FIXED_CHOICE_SURFACES = (
    "frontend/src/components/layout/AppSidebar.vue",
    "frontend/src/components/shared/SelectionPanel.vue",
    "frontend/src/components/scene-editor/KnobDrawer.vue",
    "frontend/src/views/ensemble/EnsembleSetup.vue",
)


def test_store_hydrates_server_published_effort_vocabulary():
    source = _source("frontend/src/stores/config.ts")
    assert "claude_code_efforts" in source
    assert "claudeCodeEfforts" in source


def test_store_does_not_hardcode_the_vocabulary():
    """The five levels are the server's to publish. A literal list here would
    be a second declaration of a vocabulary that already has an owner, and it
    drifts silently the day a level is added (Principle XII)."""
    source = _source("frontend/src/stores/config.ts")
    assert "'low', 'medium', 'high', 'xhigh', 'max'" not in source
    assert '"low", "medium", "high", "xhigh", "max"' not in source


@pytest.mark.parametrize("relative", SELECTOR_OWNERS)
def test_every_selector_owner_exposes_claude_code_effort(relative):
    assert "claudeCodeEffort" in _source(relative), (
        f"{relative} offers claude-code but has no effort path — "
        "Principle XI, the orphaned capability"
    )


@pytest.mark.parametrize("relative", FIXED_CHOICE_SURFACES)
def test_selectors_use_fixed_selects_not_free_text(relative):
    source = _source(relative)
    assert "Claude Code default" in source
    assert "<select" in source


@pytest.mark.parametrize("relative", FIXED_CHOICE_SURFACES)
def test_selectors_warn_about_the_thinking_requirement(relative):
    """FR-014. `xhigh`/`max` are refused without thinking, and thinking has no
    control of its own — so the help text must name the environment variable,
    or it points at a remedy the operator cannot find (research R7)."""
    assert "CG_CLAUDE_CODE_THINKING" in _source(relative)


def test_no_surface_offers_codex_effort_without_the_claude_code_one():
    """The parity sweep proper: any file that learned about one subscription
    backend's effort must know about the other's."""
    for relative in SELECTOR_OWNERS:
        source = _source(relative)
        if "codexReasoning" in source:
            assert "claudeCodeEffort" in source, (
                f"{relative} exposes Codex effort but not Claude Code effort"
            )


def test_selection_panel_shows_resolved_state_and_origin():
    source = _source("frontend/src/components/shared/SelectionPanel.vue")
    assert "claude_code_effort_origin" in source
    assert "resolved.backend === 'claude-code'" in source


def test_selection_panel_sends_both_efforts_on_every_save():
    """PUT replaces the whole stored selection, so both fields must always
    travel. Sending only the one being edited is how one backend's stored
    choice would clobber the other's (FR-015)."""
    source = _source("frontend/src/components/shared/SelectionPanel.vue")
    save = source.split("async function save()")[1].split("async function")[0]
    assert "codex_reasoning_effort:" in save
    assert "claude_code_effort:" in save


def test_session_editor_persists_to_its_own_backend_profile():
    """Isolation is structural: the PUT names 'claude-code', so it cannot
    reach into the codex-cli profile."""
    source = _source("frontend/src/views/session/SessionDocEditor.vue")
    assert "'claude-code': {" in source
    assert "claude_code_effort: claudeCodeEffort.value || null" in source


def test_streamed_results_and_graph_expose_the_run_identity():
    assert "claude-code run:" in _source(
        "frontend/src/components/shared/StreamOutput.vue")
    graph = _source("frontend/src/views/prep/ConnectionGraph.vue")
    assert "ClaudeCodeRunIdentity" in graph
    assert "claude_code_effort_source" in graph
