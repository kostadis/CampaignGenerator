"""spec 039: the delta record layer makes no model call.

Each listed module may call a model only inside the function(s) named in
ALLOWED_MODEL_FUNCTIONS; everywhere else a call to stream_api / call_api /
make_client is a failure. Imports are fine; calls are what matter. Modules that
do not exist fail: the map must name every ``delta/*.py`` (a new module cannot slip in unchecked) and
every name in it must exist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DELTA = ROOT / "pipelines" / "summary_native" / "delta"

# module file -> names of the functions allowed to make a model call.
# An empty set means the module must never call a model.
ALLOWED_MODEL_FUNCTIONS: dict[str, frozenset[str]] = {
    "plan.py": frozenset(),
    "sources.py": frozenset(),
    "census.py": frozenset({"propose_triage_hints"}),
    "client.py": frozenset(),
    "associations.py": frozenset({"propose"}),
    "attest.py": frozenset(),
    "npc_baseline.py": frozenset(),
    "lineage.py": frozenset(),
    "outline_contract.py": frozenset(),
    "grounding_publish.py": frozenset(),
    "run.py": frozenset(),
    "receipt.py": frozenset(),
    "grounding_recovery.py": frozenset(),
    "cli_run.py": frozenset(),
    "npc_update.py": frozenset(),  # the model call is npc_draft.run_draft's, reached through its hook
    "cli_npc_publish.py": frozenset(),
    "review_binding.py": frozenset(),
    "diff_view.py": frozenset(),
    "cli_review.py": frozenset(),
    "transfer.py": frozenset(),
    "cli_transfer.py": frozenset(),
    # the bounded consistency call is the only model use in the grounding check
    "grounding_check.py": frozenset({"propose_consistency_findings"}),
    # the model proposes numbered-line edits; the host validates every one and the GM decides each
    "grounding_edits.py": frozenset({"propose_edits"}),
    "__init__.py": frozenset(),
    "baseline.py": frozenset(),
    "cli.py": frozenset(),
    "cli_grounding.py": frozenset(),
    "cli_grounding_publish.py": frozenset(),
    "cli_npc.py": frozenset(),
    "cli_plan.py": frozenset(),
    "errors.py": frozenset(),
    "evidence.py": frozenset(),
    "grounding_candidates.py": frozenset(),
    "records_io.py": frozenset(),
    # spec 040: custody and the rebase CLI surface never call a model (rebase propose's own module will be
    # added with its handler)
    "custody_store.py": frozenset(),
    "cli_rebase.py": frozenset(),
    "rebase_inspect.py": frozenset(),
    "rebase_impact.py": frozenset(),
    "rebase.py": frozenset(),
    "rebind.py": frozenset(),
    # the one drafting call of the rebase family; the host validates every repair and the GM decides each
    "rebase_propose.py": frozenset({"propose"}),
}
FORBIDDEN_CALLS = frozenset({"stream_api", "call_api", "make_client"})


def _called_name(node: ast.Call) -> str:
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def model_calls_outside(source: str, allowed: frozenset[str]) -> list[str]:
    """Forbidden calls not lexically inside an allowed function."""
    tree = ast.parse(source)
    offenders: list[str] = []

    def visit(node: ast.AST, inside_allowed: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in allowed:
            inside_allowed = True
        if isinstance(node, ast.Call) and not inside_allowed:
            name = _called_name(node)
            if name in FORBIDDEN_CALLS:
                offenders.append(f"{name} (line {node.lineno})")
        for child in ast.iter_child_nodes(node):
            visit(child, inside_allowed)

    visit(tree, False)
    return offenders


def test_detector_flags_synthetic_calls():
    src = (
        "def a(c):\n    return stream_api(c, 's', 'u')\n"
        "def b(c):\n    return campaignlib.call_api(c)\n"
        "def d():\n    return make_client()\n"
        "def propose_triage_hints(c):\n    return call_api(c)\n"
    )
    assert len(model_calls_outside(src, frozenset())) == 4
    flagged = model_calls_outside(src, frozenset({"propose_triage_hints"}))
    assert len(flagged) == 3 and all("line 8" not in f for f in flagged)
    assert model_calls_outside("from campaignlib import stream_api\n", frozenset()) == []


@pytest.mark.parametrize("name", sorted(ALLOWED_MODEL_FUNCTIONS))
def test_record_module_makes_no_model_call(name):
    path = DELTA / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it from the map or create it"
    offenders = model_calls_outside(path.read_text(encoding="utf-8"), ALLOWED_MODEL_FUNCTIONS[name])
    assert not offenders, f"{name} calls a model outside {sorted(ALLOWED_MODEL_FUNCTIONS[name])}: {offenders}"


def test_the_map_covers_every_delta_module():
    on_disk = {p.name for p in DELTA.glob("*.py")}
    assert on_disk == set(ALLOWED_MODEL_FUNCTIONS), (
        f"unlisted: {sorted(on_disk - set(ALLOWED_MODEL_FUNCTIONS))}; "
        f"listed but missing: {sorted(set(ALLOWED_MODEL_FUNCTIONS) - on_disk)}")


def test_only_the_named_functions_may_call_a_model():
    assert {n: sorted(f) for n, f in ALLOWED_MODEL_FUNCTIONS.items() if f} == {
        "associations.py": ["propose"], "census.py": ["propose_triage_hints"],
        "grounding_check.py": ["propose_consistency_findings"], "grounding_edits.py": ["propose_edits"],
        "rebase_propose.py": ["propose"]}
