"""Static UI reachability guardrails for Codex reasoning effort."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_store_hydrates_server_published_effort_vocabulary():
    source = _source("frontend/src/stores/config.ts")
    assert "codex_reasoning_efforts" in source
    assert "codexReasoningEfforts" in source


def test_every_selector_owner_exposes_codex_effort():
    owners = (
        "frontend/src/components/layout/AppSidebar.vue",
        "frontend/src/components/shared/SelectionPanel.vue",
        "frontend/src/components/scene-editor/KnobDrawer.vue",
        "frontend/src/views/session/SessionDocEditor.vue",
        "frontend/src/views/ensemble/EnsembleSetup.vue",
        "frontend/src/views/ensemble/useEnsembleRun.ts",
    )
    for relative in owners:
        source = _source(relative)
        assert "codexReasoning" in source, f"{relative} has no Codex effort path"


def test_selectors_use_fixed_selects_not_free_text():
    owners = (
        "frontend/src/components/layout/AppSidebar.vue",
        "frontend/src/components/shared/SelectionPanel.vue",
        "frontend/src/components/scene-editor/KnobDrawer.vue",
        "frontend/src/views/ensemble/EnsembleSetup.vue",
    )
    for relative in owners:
        source = _source(relative)
        assert "Codex default" in source
        assert "<select" in source


def test_connection_graph_and_streamed_results_expose_identity():
    connection_graph = _source("frontend/src/views/prep/ConnectionGraph.vue")
    api_client = _source("frontend/src/api/client.ts")
    assert "run_identity" in connection_graph
    assert "e instanceof ApiError" in connection_graph
    assert "payload?.run_identity" in connection_graph
    assert "class ApiError" in api_client
    assert "Codex run:" in _source("frontend/src/components/shared/StreamOutput.vue")
    review = _source("frontend/src/views/session/ReviewAssemble.vue")
    assert 'class="polish-stream"' in review
    assert "max-height: 120px" in review
    assert "polishRunIdentity" not in review
