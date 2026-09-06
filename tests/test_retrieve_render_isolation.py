"""Static assertion for the Phase 3 "retrieval ≠ render" invariant.

The RLM integration plan requires that render pipelines consume a
human-approved ``docs/dossier_proposal.md`` rather than raw
``rpg_retriever`` / ``mempalace_search_hierarchical`` output. Enforced
mechanically: no function body in the repository may contain BOTH a
retrieval call and a render call.

This test walks every top-level ``.py`` module in the CampaignGenerator
worktree (ignoring the venv, third-party dirs, tests themselves) and
fails loudly if any single function body calls both an ingredient from
each list.

Retrieval sentinels (any call within the body):
  * rpg_retriever.retrieve / .retrieve_scoped / any attribute on the imported module
  * mempalace_search_hierarchical (MCP tool name)
  * MempalaceClient.search_hierarchical / .search

Render sentinels (any call within the body):
  * stream_api / call_api  (campaignlib.py)
  * run_batch / run_single_batch  (campaignlib/api/batch.py — blocking Message
    Batches render entry points, spec 004-claude-api-batch)

The check is lexical (name-based) — good enough in practice because
CampaignGenerator scripts use the shared names verbatim.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


from repo_sources import repo_python_files  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# Directory exclusion lives in tests/repo_sources.py — git-tracked files only,
# so a nested worktree under .claude/ cannot be reported as a violation.
SKIP_DIRS = {"tests"}

RETRIEVAL_NAMES = frozenset(
    {
        "retrieve",
        "retrieve_scoped",
        "search_within",
        "search_hierarchical",
        "mempalace_search_hierarchical",
        "rpg_search",
    }
)
RENDER_NAMES = frozenset({"stream_api", "call_api", "run_batch", "run_single_batch"})

# Modules that ARE allowed to mix — they implement the plumbing or
# explicitly own the MCP surface. The rule applies to higher-level
# orchestration and script-level code.
ALLOWED_FILES = {
    "pipelines/rlm/mempalace_client.py",   # the client exposes both surfaces by design
    "pipelines/rlm/rpg_retriever.py",      # pure retrieval; we still want the test to run on it
    "pipelines/rlm/dossier_proposer.py",   # slotting only, never calls render
    "campaignlib/api/client.py",  # defines stream_api / call_api themselves
    "server/subprocess_runner.py",  # transport layer for CLIs
}


def _is_candidate_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    if any(part in SKIP_DIRS for part in parts):
        return False
    if str(rel).replace("\\", "/") in ALLOWED_FILES:
        return False
    return True


def _collect_call_names(node: ast.AST) -> set[str]:
    """Return every attribute / free-name that appears in a Call's func."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _function_bodies(module: ast.Module):
    """Yield (qualname, node) for every def / async def in the module."""
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield (node.name, node)


def _iter_candidate_files():
    for path in repo_python_files(REPO_ROOT):
        if _is_candidate_file(path):
            yield path


@pytest.mark.parametrize("path", list(_iter_candidate_files()), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_retrieve_render_colocation(path: Path):
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"{path}: could not parse: {exc}")

    offenders: list[str] = []
    for name, node in _function_bodies(tree):
        calls = _collect_call_names(node)
        has_retrieve = bool(calls & RETRIEVAL_NAMES)
        has_render = bool(calls & RENDER_NAMES)
        if has_retrieve and has_render:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}::{name} "
                f"(retrieve+render in one body: {sorted(calls & (RETRIEVAL_NAMES | RENDER_NAMES))})"
            )

    if offenders:
        joined = "\n  ".join(offenders)
        pytest.fail(
            "Phase 3 isolation violated — retrieval and render co-located:\n  "
            + joined
            + "\n\nSplit the function: retrieve in one, render in another, "
            "with the human-reviewed dossier_proposal.md as the handoff."
        )


def test_narration_bundle_helpers_are_pure_prompt_and_reconciliation_code():
    """Bundle preparation must not grow a second model or retrieval boundary."""
    path = REPO_ROOT / "session_doc/narrate.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = _collect_call_names(tree)
    assert not calls & RETRIEVAL_NAMES
    assert not calls & RENDER_NAMES
