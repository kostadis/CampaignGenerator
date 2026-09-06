"""Guardrails for the unified LLM backend-selection seam (campaignlib.api.client).

Before this test existed, backend selection fragmented three ways: some
scripts had bespoke --dgx-endpoint/--dgx-model flags, some had no backend
flag at all (env-only), and three server routers each independently
reimplemented a backend->env translator (two of which silently dropped the
"openrouter" choice). This test enforces the two invariants that keep it
from re-fragmenting:

1. No script outside campaignlib/api/client.py may call make_client(
   directly — every caller goes through client_from_args (optionally with
   its `endpoint=` override for fan-out callers), which is the one place
   that resolves --backend/--endpoint/--model into a client.
2. Every script that declares a --model argparse flag must also call
   add_backend_args( — a model choice without a backend choice is exactly
   the shape of the bug this seam exists to prevent. The ensemble
   dispatcher family (ensemble.py / ensemble_batch.py / ensemble_extract.py)
   is exempted: they never build a client themselves, only forward a bare
   --backend down a subprocess chain, so add_backend_args's --endpoint
   (singular) would be a redundant third endpoint-shaped flag alongside
   their existing --endpoints (plural, fan-out).

Both checks use AST (not substring/regex): a substring scan on "make_client("
false-positives on prose that merely mentions it (a comment did, at the time
this test was written), and a same-line regex on --model would miss the
common multi-line `parser.add_argument(\\n    "--model", ...)` form while
false-positiving on "--model" appearing as a subprocess-argv string literal
in the server routers.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
from dataclasses import dataclass
from pathlib import Path

import pytest

from campaignlib.api import client as client_mod
from repo_sources import repo_python_files


REPO_ROOT = Path(__file__).resolve().parent.parent
SEAM_FILE = "campaignlib/api/client.py"
# Directory exclusion is NOT maintained here — see tests/repo_sources.py.
# `repo_python_files` returns git-TRACKED files only, so a nested worktree
# under .claude/ (a full second copy of the repo) can never be reported as a
# seam violation. `tests` is still filtered, but by path role rather than by
# a denylist that has to be remembered.
def _is_test_file(rel: pathlib.PurePath) -> bool:
    return "tests" in rel.parts

# Dispatcher scripts that intentionally use a bare --backend instead of
# add_backend_args (see module docstring) — never build a client themselves.
ALLOWED_DISPATCHER_FILES = {"ensemble.py", "ensemble_batch.py", "ensemble_extract.py"}

# The production inventory is deliberately discovered from source below.  The
# expected sets are the contract's baseline, rather than a hand-maintained
# list of parser call sites: changing a command's parser shape changes the
# discovered category and fails loudly at the inventory boundary.
EXPECTED_REGISTRAR_FILES = frozenset(
    {
        "session_doc/check_consistency.py",
        "session_doc/enhance_summary.py",
        "session_doc/scene_extract.py",
        "session_doc/sd_agent.py",
        "session_doc/sd_consistency.py",
        "session_doc/sd_narrate.py",
        "session_doc/sd_plan.py",
        "session_doc/vtt_voice_compare.py",
        "pipelines/session_prep/prep.py",
        "pipelines/session_prep/transform.py",
        "pipelines/content_ingest/dnd_sheet.py",
        "pipelines/rlm/query.py",
        "pipelines/grounding/planning.py",
        "pipelines/grounding/party.py",
        "pipelines/grounding/make_tracking.py",
        "pipelines/grounding/distill.py",
        "pipelines/grounding/campaign_state.py",
        "pipelines/grounding/npc_table.py",
        "pipelines/grounding/grounding_sections.py",
        "pipelines/grounding/thread_registry.py",
        "pipelines/ensemble/synthesise_world_state.py",
        "pipelines/ensemble/synthesise_polish.py",
        "pipelines/ensemble/extract_facts.py",
        "pipelines/ensemble/narrate_chapter.py",
        "pipelines/ensemble/polish.py",
        "scabard_sdk/scabard_sync.py",
    }
)
EXPECTED_HAND_WRITTEN_FILES = frozenset(
    {
        "pipelines/ensemble/facts_to_state.py",
        "pipelines/ensemble/ensemble.py",
        "pipelines/ensemble/ensemble_batch.py",
        "pipelines/ensemble/ensemble_extract.py",
    }
)
EXPECTED_DISPATCHER_FILES = frozenset(
    {
        "session_doc/sd_agent.py",
        "pipelines/ensemble/ensemble.py",
        "pipelines/ensemble/ensemble_batch.py",
        "pipelines/ensemble/ensemble_extract.py",
    }
)

# Files that define their OWN unrelated make_client( — a name collision, not
# a seam bypass. kanka_mcp.py's make_client() builds a KankaClient (the
# Kanka wiki API), never touches an LLM backend at all.
ALLOWED_NAME_COLLISION_FILES = {"kanka_mcp.py"}


def _is_candidate_file(path: Path) -> bool:
    return not _is_test_file(path.relative_to(REPO_ROOT))


def _iter_candidate_files():
    for path in repo_python_files(REPO_ROOT):
        if _is_candidate_file(path):
            yield path


def _parse(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"{path}: could not parse: {exc}")


def _call_func_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _all_calls(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _has_call(tree: ast.Module, name: str) -> bool:
    return any(_call_func_name(node) == name for node in _all_calls(tree))


def _declares_backend_flag(tree: ast.Module) -> bool:
    """Return whether source registers an exact ``--backend`` option."""
    return any(
        _call_func_name(node) == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "--backend"
        for node in _all_calls(tree)
    )


def _backend_choices(tree: ast.Module) -> set[str]:
    """Extract canonical or literal choices from a backend flag.

    Hand-written parsers may not use ``add_backend_args`` when they own a
    plural endpoint, but they must still bind ``choices`` to the canonical
    imported ``BACKENDS`` vocabulary.  A private literal remains inspectable
    so a drifted or incomplete copy fails the exact-vocabulary assertion.
    """
    canonical_imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "campaignlib.selection"
        and any(
            alias.name == "BACKENDS"
            and (alias.asname is None or alias.asname == "BACKENDS")
            for alias in node.names
        )
        for node in tree.body
    )
    for node in _all_calls(tree):
        if not (
            _call_func_name(node) == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--backend"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "choices":
                continue
            value = keyword.value
            if (
                canonical_imported
                and isinstance(value, ast.Name)
                and value.id == "BACKENDS"
            ):
                return set(client_mod.BACKENDS)
            if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
                return {
                    element.value
                    for element in value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                }
    return set()


def _source_tree(path: Path) -> ast.Module:
    return _parse(path)


def discover_backend_surfaces() -> tuple[frozenset[str], frozenset[str]]:
    """Discover registrar and hand-written backend parsers from production AST.

    This is intentionally based on call structure, not a substring search:
    comments/docstrings and subprocess argv strings must not make a command an
    inventory member.  Tests and the shared registrar implementation itself
    are excluded from the production surface.
    """
    registrars: set[str] = set()
    hand_written: set[str] = set()
    for path in repo_python_files(REPO_ROOT):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _is_test_file(path.relative_to(REPO_ROOT)) or rel == SEAM_FILE:
            continue
        tree = _source_tree(path)
        if _has_call(tree, "add_backend_args"):
            registrars.add(rel)
        elif _declares_backend_flag(tree):
            hand_written.add(rel)
    return frozenset(registrars), frozenset(hand_written)


def _has_process_execution(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
        for node in ast.walk(tree)
    )


def discover_runtime_dispatchers(
    registrars: frozenset[str], hand_written: frozenset[str]
) -> frozenset[str]:
    """Classify the four backend-forwarding runtime dispatchers.

    Hand-written ensemble parsers are dispatchers only when they also execute
    a child process; ``facts_to_state`` is a direct plural-endpoint parser.
    Among shared registrars, ``sd_agent`` is the session-document forwarding
    dispatcher.  The grounding sections module also invokes a child, but it
    is a workflow caller, not one of the four dispatcher surfaces defined by
    ``contracts/cli-family.md``.
    """
    candidates = {
        rel
        for rel in hand_written
        if rel.startswith("pipelines/ensemble/")
    }
    candidates.update(
        rel for rel in registrars if rel == "session_doc/sd_agent.py"
    )
    return frozenset(
        rel
        for rel in candidates
        if _has_process_execution(_source_tree(REPO_ROOT / rel))
    )


_CANDIDATE_FILES = list(_iter_candidate_files())
_CANDIDATE_IDS = [str(p.relative_to(REPO_ROOT)) for p in _CANDIDATE_FILES]


# ── Production inventory (spec 016) ────────────────────────────────────────

def test_production_backend_surface_inventory_is_exact():
    """All and only the 30 production backend surfaces are parser-discovered.

    The old guardrail listed 22 registrar paths and silently let newly moved
    commands disappear from coverage.  Discovering parser calls from tracked
    source catches both omissions and accidental duplicate vocabularies.
    """
    registrars, hand_written = discover_backend_surfaces()

    assert len(registrars) == 26, sorted(registrars)
    assert registrars == EXPECTED_REGISTRAR_FILES
    assert len(hand_written) == 4, sorted(hand_written)
    assert hand_written == EXPECTED_HAND_WRITTEN_FILES
    assert len(registrars | hand_written) == 30


def test_runtime_dispatcher_inventory_is_exact():
    """The four forwarding dispatchers preserve backend selection to children."""
    registrars, hand_written = discover_backend_surfaces()
    dispatchers = discover_runtime_dispatchers(registrars, hand_written)

    assert dispatchers == EXPECTED_DISPATCHER_FILES
    assert len(dispatchers) == 4


def test_hand_written_backend_choices_include_canonical_codex_cli():
    """Each explicit backend vocabulary must equal the canonical vocabulary."""
    _, hand_written = discover_backend_surfaces()
    missing = {
        rel
        for rel in hand_written
        if _backend_choices(_source_tree(REPO_ROOT / rel)) != set(client_mod.BACKENDS)
    }
    assert not missing, (
        f"hand-written backend choices drift from canonical BACKENDS: "
        f"{sorted(missing)}"
    )


# ── UI reachability (spec 016, contract/ui-selection.md) ───────────────────

@dataclass(frozen=True)
class _UIReachability:
    """Evidence required for one production capability's visible UI face.

    ``direct`` rows point at a route command builder. ``transitive`` rows
    name the owning workflow and every known dispatch hop. ``new-face`` rows
    are the seven explicit UI/server faces required by the contract. Keeping
    this as data makes a newly inventoried CLI fail the mapping assertion
    rather than disappearing from reachability coverage.
    """

    kind: str
    production: tuple[str, ...]
    ui: tuple[str, ...]
    # Most faces use one marker tuple for every listed file.  A composed face
    # (for example Scabard's view, mounted route, and sidebar entry) can supply
    # file-specific evidence so each file proves its own visible seam rather
    # than requiring unrelated labels to be copied into it.
    ui_markers: tuple[str, ...] | dict[str, tuple[str, ...]]


_UI_REACHABILITY: dict[str, _UIReachability] = {
    # Session-document direct builders and their visible editor controls.
    "enhance_summary": _UIReachability(
        "direct", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/enhance",),
    ),
    "scene_extract": _UIReachability(
        "direct", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/extract",),
    ),
    "sd_consistency": _UIReachability(
        "direct", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/plan",),
    ),
    "sd_plan": _UIReachability(
        "direct", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/plan",),
    ),
    "sd_narrate": _UIReachability(
        "direct", ("server/routers/scene_editor.py",),
        (
            "frontend/src/views/session/SessionDocEditor.vue",
            "frontend/src/components/scene-editor/ExtractionEditor.vue",
        ),
        {
            "frontend/src/views/session/SessionDocEditor.vue": (
                "/api/editor/narrate", "/api/editor/narrate-bundle",
            ),
            "frontend/src/components/scene-editor/ExtractionEditor.vue": (
                "Narrate all in one call",
            ),
        },
    ),

    # Prep, setup, grounding and projection builders.
    "prep": _UIReachability(
        "direct", ("server/routers/prep.py",),
        ("frontend/src/views/prep/SessionPrep.vue",),
        ("/api/prep/run/session-prep",),
    ),
    "dnd_sheet": _UIReachability(
        "direct", ("server/routers/setup.py",),
        ("frontend/src/views/setup/DndSheet.vue",),
        ("/api/setup/run/dnd-sheet",),
    ),
    "query": _UIReachability(
        "direct", ("server/routers/prep.py",),
        ("frontend/src/views/prep/QuerySummaries.vue",),
        ("/api/prep/run/query",),
    ),
    "planning": _UIReachability(
        "direct", ("server/routers/grounding.py",),
        ("frontend/src/views/grounding/PlanningDocument.vue",),
        ("/api/grounding/run/planning",),
    ),
    "party": _UIReachability(
        "direct", ("server/routers/grounding.py",),
        ("frontend/src/views/grounding/PartyDocument.vue",),
        ("/api/grounding/run/party",),
    ),
    "make_tracking": _UIReachability(
        "direct", ("server/routers/setup.py",),
        ("frontend/src/views/setup/MakeTracking.vue",),
        ("/api/setup/run/make-tracking",),
    ),
    "distill": _UIReachability(
        "direct", ("server/routers/grounding.py",),
        ("frontend/src/views/grounding/DistillWorldState.vue",),
        ("/api/grounding/run/distill",),
    ),
    "campaign_state": _UIReachability(
        "direct", ("server/routers/grounding.py",),
        ("frontend/src/views/grounding/CampaignState.vue",),
        ("/api/grounding/run/campaign-state",),
    ),
    "npc_table": _UIReachability(
        "direct", ("server/routers/prep.py",),
        ("frontend/src/views/prep/NpcTable.vue",),
        ("/api/prep/run/npc-table",),
    ),
    "grounding_sections": _UIReachability(
        "direct", ("server/routers/projections.py",),
        ("frontend/src/views/grounding/ProjectionSections.vue",),
        ("/api/projections/run/build",),
    ),
    "thread_registry": _UIReachability(
        "direct", ("server/routers/projections.py",),
        ("frontend/src/views/grounding/Threads.vue",),
        ("/api/projections/threads/run/propose",),
    ),

    # Ensemble direct builder faces.
    "synthesise_world_state": _UIReachability(
        "direct", ("server/routers/ensemble.py",),
        ("frontend/src/views/ensemble/EnsembleSynthesize.vue",),
        ("/api/ensemble/run/synthesize",),
    ),
    "facts_to_state": _UIReachability(
        "direct", ("server/routers/ensemble.py",),
        ("frontend/src/views/ensemble/EnsembleBundle.vue",),
        ("/api/ensemble/run/bundle",),
    ),

    # Document and ensemble dispatchers: the listed paths are the visible
    # owning workflow plus the child forwarding hop(s), not merely imports.
    "sd_agent": _UIReachability(
        "transitive",
        ("session_doc/sd_agent.py", "server/routers/scene_editor.py"),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/extract",),
    ),
    "ensemble": _UIReachability(
        "transitive", ("server/routers/ensemble.py",),
        ("frontend/src/views/ensemble/EnsembleExtract.vue",),
        ("/api/ensemble/run/extract",),
    ),
    "ensemble_batch": _UIReachability(
        "transitive", ("server/routers/ensemble.py", "pipelines/ensemble/ensemble_batch.py"),
        ("frontend/src/views/ensemble/EnsembleExtract.vue",),
        ("/api/ensemble/run/extract",),
    ),
    "ensemble_extract": _UIReachability(
        "transitive", ("server/routers/ensemble.py", "pipelines/ensemble/ensemble_extract.py"),
        ("frontend/src/views/ensemble/EnsembleExtract.vue",),
        ("/api/ensemble/run/extract",),
    ),
    "extract_facts": _UIReachability(
        "transitive",
        ("server/routers/ensemble.py", "pipelines/ensemble/ensemble_extract.py", "pipelines/ensemble/extract_facts.py"),
        ("frontend/src/views/ensemble/EnsembleExtract.vue",),
        ("/api/ensemble/run/extract",),
    ),

    # Contract-mandated new invocation faces. Their rows intentionally fail
    # until the corresponding visible route/control lands in US4.
    "check_consistency": _UIReachability(
        "new-face", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/consistency", "Check Consistency"),
    ),
    "transform": _UIReachability(
        "new-face", ("server/routers/prep.py",),
        ("frontend/src/views/prep/SessionPrep.vue",),
        ("transform",),
    ),
    "vtt_voice_compare": _UIReachability(
        "new-face", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/SessionDocEditor.vue",),
        ("/api/editor/voice-compare", "Compare Voice"),
    ),
    "scabard_sync": _UIReachability(
        "new-face", ("server/routers/integrations.py",),
        (
            "frontend/src/views/integrations/ScabardSync.vue",
            "frontend/src/router.ts",
            "frontend/src/components/layout/AppSidebar.vue",
        ),
        {
            "frontend/src/views/integrations/ScabardSync.vue": (
                "/api/integrations/scabard", "Scabard Sync",
            ),
            "frontend/src/router.ts": (
                "/integrations/scabard", "scabard-sync",
            ),
            "frontend/src/components/layout/AppSidebar.vue": (
                "/integrations/scabard", "Scabard Sync",
            ),
        },
    ),
    "synthesise_polish": _UIReachability(
        "new-face", ("server/routers/ensemble.py",),
        ("frontend/src/views/ensemble/EnsembleSynthesize.vue",),
        ("/api/ensemble/run/synthesise-polish", "synthesisePolish"),
    ),
    "narrate_chapter": _UIReachability(
        "new-face", ("server/routers/ensemble.py",),
        ("frontend/src/views/ensemble/EnsembleExtract.vue",),
        ("/api/ensemble/run/narrate-chapter", "narrateChapter"),
    ),
    "polish": _UIReachability(
        "new-face", ("server/routers/scene_editor.py",),
        ("frontend/src/views/session/ReviewAssemble.vue",),
        ("polish",),
    ),
}


def _inventory_command_names() -> frozenset[str]:
    return frozenset(
        Path(rel).stem
        for rel in EXPECTED_REGISTRAR_FILES | EXPECTED_HAND_WRITTEN_FILES
    )


def _has_console_script(tree: ast.Module, command: str) -> bool:
    return any(
        _call_func_name(node) == "console_script"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == command
        for node in _all_calls(tree)
    )


def test_every_canonical_inventory_row_has_ui_reachability_mapping():
    """The 30-row capability inventory cannot silently lose a UI mapping."""
    assert len(_inventory_command_names()) == 30
    assert set(_UI_REACHABILITY) == set(_inventory_command_names())
    assert {row.kind for row in _UI_REACHABILITY.values()} == {
        "direct", "transitive", "new-face"
    }
    assert sum(row.kind == "new-face" for row in _UI_REACHABILITY.values()) == 7


@pytest.mark.parametrize(
    "command,row", list(_UI_REACHABILITY.items()), ids=list(_UI_REACHABILITY)
)
def test_each_inventory_row_has_executable_ui_reachability(command, row):
    """Require source and visible UI evidence for every inventory row.

    Direct rows must point at an actual ``console_script(command)`` builder;
    transitive rows must retain every dispatch source and their owner control;
    new-face rows require both the route marker and the visible control. The
    failure names the exact missing face so US4 implementation work cannot
    satisfy the inventory merely by adding an unmounted endpoint.
    """
    missing: list[str] = []
    for rel in row.production:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(f"production file {rel}")
            continue
        tree = _parse(path)
        if row.kind == "direct" and not _has_console_script(tree, command):
            missing.append(f"console_script({command!r}) in {rel}")
        if row.kind == "new-face" and not _has_console_script(tree, command):
            missing.append(f"new route marker {command!r} in {rel}")

    for rel in row.ui:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(f"visible UI file {rel}")
            continue
        source = path.read_text(encoding="utf-8")
        if isinstance(row.ui_markers, dict):
            if rel not in row.ui_markers:
                missing.append(f"UI marker evidence for {rel}")
                continue
            markers = row.ui_markers[rel]
        else:
            markers = row.ui_markers
        missing.extend(
            f"UI marker {marker!r} in {rel}"
            for marker in markers
            if marker not in source
        )

    assert not missing, (
        f"{command} ({row.kind}) has no complete visible reachability: "
        + "; ".join(missing)
    )


def test_sd_narrate_bundle_reuses_the_cli_and_subprocess_seams():
    """The new face must remain an explicit argv/SSE adapter around sd_narrate."""
    route = (REPO_ROOT / "server/routers/scene_editor.py").read_text(encoding="utf-8")
    assert '"/narrate-bundle"' in route
    assert '"--batch-scenes"' in route
    assert "stream_subprocess" in route
    assert "emit_done=False" in route


# ── Check 1: make_client( only inside the seam ──────────────────────────────

@pytest.mark.parametrize("path", _CANDIDATE_FILES, ids=_CANDIDATE_IDS)
def test_no_out_of_seam_make_client(path: Path):
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel == SEAM_FILE:
        pytest.skip("make_client is defined and legitimately called here")
    if path.name in ALLOWED_NAME_COLLISION_FILES:
        pytest.skip("defines its own unrelated make_client( — see ALLOWED_NAME_COLLISION_FILES")

    tree = _parse(path)
    offenders = [
        node.lineno for node in _all_calls(tree)
        if _call_func_name(node) == "make_client"
    ]
    assert not offenders, (
        f"{rel} calls make_client( directly at line(s) {offenders} — "
        "route through campaignlib.api.client.client_from_args instead "
        "(pass endpoint= for fan-out callers)."
    )


# ── Check 2: every --model flag comes with add_backend_args ─────────────────

def _declares_model_flag(tree: ast.Module) -> bool:
    for node in _all_calls(tree):
        if _call_func_name(node) != "add_argument":
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--model":
            return True
    return False


@pytest.mark.parametrize("path", _CANDIDATE_FILES, ids=_CANDIDATE_IDS)
def test_model_flag_implies_backend_args(path: Path):
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel == SEAM_FILE:
        pytest.skip("defines add_backend_args itself")

    tree = _parse(path)
    if not _declares_model_flag(tree):
        pytest.skip("no --model flag declared")
    if path.name in ALLOWED_DISPATCHER_FILES:
        pytest.skip("dispatcher script — forwards --backend without add_backend_args")

    source = path.read_text(encoding="utf-8")
    assert "add_backend_args(" in source, (
        f"{rel} declares --model but never calls add_backend_args( — "
        "every script with a model choice must also expose --backend/--endpoint."
    )


# ── Check 3: --batch is uniform (spec 004-claude-api-batch) ─────────────────

def test_add_backend_args_registers_batch_flag():
    """Every registrar CLI gets --batch spelled and defaulted identically
    (FR-001/FR-002) — a store_true defaulting to False, byte-identical
    behavior when omitted (FR-011)."""
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    client_mod.add_backend_args(p)
    ns = p.parse_args([])
    assert ns.batch is False
    ns_on = p.parse_args(["--batch"])
    assert ns_on.batch is True


@pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code", "codex-cli"])
def test_client_from_args_rejects_batch_for_non_anthropic_backend(backend, monkeypatch):
    """--batch requires the real Anthropic client — none of the façades
    implement messages.batches, so this must fail before construction."""
    def _boom(*a, **kw):
        raise AssertionError("make_client must not be called before the --batch rejection")

    monkeypatch.setattr(client_mod, "make_client", _boom)
    ns = argparse.Namespace(backend=backend, endpoint=None, model="m", batch=True)

    with pytest.raises(SystemExit) as exc_info:
        client_mod.client_from_args(ns)

    assert f"backend '{backend}' has no batch support" in str(exc_info.value)
    assert "--batch requires the Claude API backend (--backend anthropic)" in str(exc_info.value)


def test_client_from_args_rejects_batch_via_cg_backend_env(monkeypatch):
    """--backend anthropic (the default) + CG_BACKEND=openrouter + --batch
    must still be rejected — the env-driven resolution, not just the
    explicit --backend flag, decides what --batch is validated against."""
    def _boom(*a, **kw):
        raise AssertionError("make_client must not be called before the --batch rejection")

    monkeypatch.setattr(client_mod, "make_client", _boom)
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    ns = argparse.Namespace(backend="anthropic", endpoint=None, model="m", batch=True)

    with pytest.raises(SystemExit) as exc_info:
        client_mod.client_from_args(ns)

    assert "backend 'openrouter' has no batch support" in str(exc_info.value)


def test_client_from_args_allows_batch_for_anthropic(monkeypatch):
    """The default (anthropic, no CG_BACKEND) must not be rejected."""
    monkeypatch.delenv("CG_BACKEND", raising=False)
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend) or "client")
    ns = argparse.Namespace(backend="anthropic", endpoint=None, model="m", batch=True)

    out = client_mod.client_from_args(ns)

    assert out == "client"
    assert seen == {"backend": None}


def test_client_from_args_batch_absent_is_unaffected(monkeypatch):
    """No --batch attribute at all (an older/unrelated caller's Namespace)
    must not trip the check — getattr(..., False) is the guard."""
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend) or "client")
    ns = argparse.Namespace(backend="dgx", endpoint=None, model="m")  # no .batch

    out = client_mod.client_from_args(ns)

    assert out == "client"


# ── Check 3b: --backend dgx never silently becomes Anthropic ────────────────
#
# make_client had branches for "claude-code" and "openrouter" but none for
# "dgx": the local path was reached only via a truthy `endpoint`, so
# `--backend dgx` with no --endpoint/DGX_ENDPOINT fell through to
# `anthropic.Anthropic()`. Four call sites (extract_facts, narrate_chapter,
# scene_editor, platform_config_service) each pre-resolved wiring's
# dgx_endpoint to dodge it; every CLI that did not — enhance_summary, and so
# sd_agent — silently billed the metered API for a run the GM asked to keep
# local. That is the "obscured swap-back to Anthropic" make_client's own
# docstring forbids, and it is silent: the flag is accepted, no warning is
# printed, and only the invoice disagrees.


def test_backend_dgx_never_falls_back_to_anthropic(monkeypatch):
    """--backend dgx with nothing naming a box must RAISE, not quietly
    return a metered Anthropic client."""
    monkeypatch.delenv("DGX_ENDPOINT", raising=False)
    monkeypatch.delenv("CG_BACKEND", raising=False)
    monkeypatch.setattr(client_mod, "wiring_get", lambda key, default=None: default)

    with pytest.raises(SystemExit) as exc_info:
        client_mod.make_client(backend="dgx")

    msg = str(exc_info.value)
    assert "--backend dgx" in msg
    assert "Refusing to fall back to the Anthropic API" in msg


def test_backend_dgx_resolves_endpoint_from_wiring(monkeypatch):
    """With no --endpoint and no env var, the mneme-rendered dgx_endpoint is
    what makes `--backend dgx` work — resolved in the seam, so a CLI does not
    have to re-derive it to get a local client."""
    monkeypatch.delenv("DGX_ENDPOINT", raising=False)
    monkeypatch.setattr(client_mod, "wiring_get",
                        lambda key, default=None:
                        "http://wired-box:8001/v1" if key == "dgx_endpoint" else default)

    out = client_mod.make_client(backend="dgx", model_override="some/model")

    assert isinstance(out, client_mod._OpenAICompatClient)


@pytest.mark.parametrize("source", ["arg", "env"])
def test_backend_dgx_endpoint_precedence_over_wiring(monkeypatch, source):
    """An explicit --endpoint (or DGX_ENDPOINT) outranks wiring — a fan-out
    caller pinning one box of a pool must not be redirected to the wired
    default."""
    monkeypatch.setattr(client_mod, "wiring_get",
                        lambda key, default=None: "http://wired-box:8001/v1")
    kwargs = {"backend": "dgx", "model_override": "m"}
    if source == "arg":
        monkeypatch.delenv("DGX_ENDPOINT", raising=False)
        kwargs["endpoint"] = "http://chosen-box:8001/v1"
    else:
        monkeypatch.setenv("DGX_ENDPOINT", "http://chosen-box:8001/v1")

    out = client_mod.make_client(**kwargs)

    assert "chosen-box" in out.oai.base_url.host or "chosen-box" in str(out.oai.base_url)


def test_backend_anthropic_still_reaches_anthropic(monkeypatch):
    """The fix must not change the default path: no backend, no endpoint,
    still a real Anthropic client."""
    monkeypatch.delenv("DGX_ENDPOINT", raising=False)
    monkeypatch.delenv("CG_BACKEND", raising=False)
    import anthropic

    assert isinstance(client_mod.make_client(), anthropic.Anthropic)


# ── Check 4: messages.batches only referenced inside the seam ───────────────

def test_no_out_of_seam_messages_batches_reference():
    """The Message Batches API surface (client.messages.batches.*) is only
    ever touched from campaignlib/api/ — every other CLI/pipeline goes
    through run_batch / run_single_batch / submit_batch / poll_batch /
    collect_batch instead (spec 004-claude-api-batch contract)."""
    offenders = []
    seam = (REPO_ROOT / "campaignlib" / "api").resolve()
    for py in repo_python_files(REPO_ROOT):
        rp = py.resolve()
        if seam in rp.parents or rp.parent == seam:
            continue
        if "/tests/" in str(rp) or rp.name.startswith("test_"):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "messages.batches" in text:
            offenders.append(str(rp.relative_to(REPO_ROOT)))
    assert not offenders, f"messages.batches referenced outside campaignlib/api/: {offenders}"


# ── Check 5: --batch is only ever built by selection_cli_args (spec 005) ────
#
# 005-ui-batch-selection's resolution seam
# (server/platform_config_service.py::resolve_selection +
# selection_cli_args) is the one place a router may learn whether a run
# should carry --batch, and selection_cli_args is the one place that flag is
# ever built (mirrors Check 4's messages.batches guard for the equivalent
# 004 seam, one layer up the stack).
#
# The Session Doc Editor's bespoke batch checkbox (KnobDrawer.vue's
# `?batch=1` -> scene_editor.py's own `cmd.append("--batch")` in
# _build_enhance_cmd/_build_reextract_cmd) predated the unified selection
# seam and was this guard's one narrowly-scoped exception until
# 005-ui-batch-selection's T029 (FR-011) retired it: scene_editor.py now
# routes through selection_cli_args like every other router (via
# _selection_args), so no exception remains.


# ``--batch`` as a COMPLETE flag token: an exact string constant. Feature
# 013's ``--batch-scenes`` / ``--no-batch-scenes`` / ``--batch-max-tokens``
# are different constants and simply do not compare equal, so the prefix
# they share needs no special case here.
_BATCH_FLAG = "--batch"


def _batch_flags_built(tree: ast.Module) -> list[int]:
    """Line numbers where ``"--batch"`` is BUILT rather than merely read.

    A membership test (``if "--batch" in cmd``) is a read: it asks what the
    seam already emitted. Everything else — an append, a list element, a
    call argument — is construction, which is what this guard forbids.
    """
    read_only = {
        id(node.left)
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
        and isinstance(node.left, ast.Constant)
        and node.left.value == _BATCH_FLAG
    }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == _BATCH_FLAG
        and id(node) not in read_only
    ]


def test_batch_flag_only_built_by_selection_cli_args():
    """No module under server/routers/ may build the literal ``"--batch"``
    itself — every occurrence must originate in
    ``platform_config_service.selection_cli_args``, so a run's command line
    can never disagree with what the resolved selection says (Constitution
    V/VI).

    Like Checks 1 and 2, this walks the AST rather than the file text, for
    the reason the module docstring already gives: a text scan fires on prose
    that merely mentions what it guards. Two earlier shapes of this check
    both did. A plain ``"--batch" in text`` substring test tripped on feature
    013's ``--batch-scenes`` family, which share the prefix; replacing it
    with a whole-token regex then tripped on 013's *comments*, which discuss
    ``--batch`` at length to explain why Message Batches wins over batched
    scenes — and on the membership test that implements that ruling
    (``scene_editor.py``'s ``if "--batch" in cmd``), which reads the flag off
    the args just emitted rather than resolving the selection a second time.
    That read is the seam working, not a second place the flag is built.

    So: an exact constant, and a membership test is allowed while
    construction is not. ``cmd.append("--batch")`` and ``cmd += ["--batch"]``
    both still fail. Do not put this back to a text scan — a guard that
    fires on comments pushes the next author toward deleting the explanation
    rather than fixing the code, which is how a guard starts distorting what
    it protects.
    """
    offenders = []
    routers_dir = (REPO_ROOT / "server" / "routers").resolve()
    for py in sorted(routers_dir.glob("*.py")):
        offenders += [
            f"{py.relative_to(REPO_ROOT)}:{lineno}"
            for lineno in _batch_flags_built(_parse(py))
        ]
    assert not offenders, (
        f"server/routers/*.py builds '--batch' directly: {offenders} — "
        "route it through selection_cli_args instead."
    )


def test_all_30_codex_surfaces_share_reasoning_effort_registration():
    registrars, hand_written = discover_backend_surfaces()
    dispatchers = discover_runtime_dispatchers(registrars, hand_written)
    assert len(registrars | hand_written) == 30
    assert len(dispatchers) == 4

    for relative_path in sorted(hand_written):
        tree = _parse(REPO_ROOT / relative_path)
        calls = {
            _call_func_name(node)
            for node in _all_calls(tree)
        }
        assert "add_codex_reasoning_arg" in calls, (
            f"{relative_path} bypasses the shared Codex effort registrar"
        )


def test_all_30_claude_code_surfaces_share_effort_registration():
    """Feature 021's half of the same inventory.

    The registrars get the option for free, because `add_backend_args` calls
    `add_claude_code_effort_arg` — that is the whole of CLI parity, and a CLI
    added tomorrow inherits it. The hand-written surfaces are the ones that
    can drift: they build their own backend arguments (facts_to_state cannot
    call add_backend_args without colliding on --endpoint/--endpoints), so
    each must register the option explicitly or one CLI in the family
    silently speaks a different dialect (Principle XII).
    """
    registrars, hand_written = discover_backend_surfaces()
    dispatchers = discover_runtime_dispatchers(registrars, hand_written)
    assert len(registrars | hand_written) == 30
    assert len(dispatchers) == 4

    for relative_path in sorted(hand_written):
        tree = _parse(REPO_ROOT / relative_path)
        calls = {_call_func_name(node) for node in _all_calls(tree)}
        assert "add_claude_code_effort_arg" in calls, (
            f"{relative_path} bypasses the shared Claude Code effort registrar"
        )


def test_all_30_claude_code_surfaces_share_thinking_registration():
    """Issue #365. The effort control offers two levels (`xhigh`, `max`) that
    only a thinking-enabled run can use, so a CLI that accepts effort without
    thinking hands the operator a choice that always fails there."""
    registrars, hand_written = discover_backend_surfaces()
    assert len(registrars | hand_written) == 30
    for relative_path in sorted(hand_written):
        tree = _parse(REPO_ROOT / relative_path)
        calls = {_call_func_name(node) for node in _all_calls(tree)}
        assert "add_claude_code_thinking_arg" in calls, (
            f"{relative_path} bypasses the shared Claude Code thinking registrar"
        )


def test_no_dispatcher_forwards_effort_without_thinking():
    offenders = []
    for relative_path in sorted(discover_runtime_dispatchers(
            *discover_backend_surfaces())):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if ("--claude-code-effort" in source
                and "--claude-code-thinking" not in source):
            offenders.append(relative_path)
    assert not offenders, (
        f"dispatchers forward Claude Code effort but not thinking: {offenders}"
    )


def test_thinking_is_forwarded_in_both_directions():
    """A resolved False must reach the child as an explicit
    --no-claude-code-thinking. Forwarding only the True case would let the
    child read CG_CLAUDE_CODE_THINKING from the inherited environment and
    override the operator's stored 'off' — the exact failure the tri-state
    exists to prevent."""
    for relative_path in sorted(discover_runtime_dispatchers(
            *discover_backend_surfaces())):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if "--claude-code-thinking" in source:
            assert "--no-claude-code-thinking" in source, (
                f"{relative_path} forwards thinking on but never off"
            )


def test_add_backend_args_registers_both_subscription_effort_options():
    """The structural claim the test above depends on: the two registrars are
    called from the one shared helper, so the 30 CLIs cannot diverge."""
    import argparse

    from campaignlib.api.client import add_backend_args

    parser = argparse.ArgumentParser()
    add_backend_args(parser)
    flags = {action.option_strings[0] for action in parser._actions
             if action.option_strings}
    assert "--codex-reasoning-effort" in flags
    assert "--claude-code-effort" in flags
    assert "--claude-code-thinking" in flags


def test_no_dispatcher_forwards_codex_effort_without_the_claude_code_one():
    """A dispatcher that learned to forward one subscription backend's effort
    to its children must forward the other's too, or a fan-out silently drops
    the operator's selection for half the family."""
    offenders = []
    for relative_path in sorted(discover_runtime_dispatchers(
            *discover_backend_surfaces())):
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if ("--codex-reasoning-effort" in source
                and "--claude-code-effort" not in source):
            offenders.append(relative_path)
    assert not offenders, (
        f"dispatchers forward Codex effort but not Claude Code effort: {offenders}"
    )
