"""No model call anywhere in the deterministic layer of summary_native (T011).

Walks the AST, so a name in a docstring cannot fool it. Modules that do not
exist yet are skipped by name, but the ones that exist are asserted checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "pipelines" / "summary_native"
GUARDED = [
    "parse", "validate", "corpus", "duplicates", "select", "context", "compare", "resolve",
    # spec 032: every NPC module except npc_draft, which is the one model step.
    "npc_forms", "npc_link", "npc_verify", "npc_compose", "npc_publish", "npc_slug", "npc_authored",
    "freshness",
    # chunked drafting's deterministic half and the shared quote/citation primitives (T062)
    "npc_check", "npc_chunked", "npc_config",
    # spec 033: the deterministic half of the chunked state documents. `extract`, `synth` and
    # `audit` are the model steps (map, prose, judge) and are deliberately not listed.
    "notes", "state_sections", "key_npcs", "annotate", "audit_select", "pointers",
    # spec 034: party attribution, the level line and the party reference files are code, not a model step.
    "party_notes",
    # spec 034 US3: attaching thread notes to ratified threads and checking a model's groupings are code.
    # `thread_propose` is the model step around them and is deliberately not listed.
    "thread_attach", "thread_check",
    # spec 034 US4: checking a model's arc-score candidates is code; the calls are made in `synth`.
    "arc_check",
]
FORBIDDEN_MODULES = ("anthropic", "campaignlib.api", "openai", "pipelines.ensemble")
FORBIDDEN_CALLS = ("make_client", "stream_api", "call_api", "client_from_args")


def _existing():
    return [(n, PKG / f"{n}.py") for n in GUARDED if (PKG / f"{n}.py").is_file()]


def test_guard_covers_the_modules_that_exist():
    names = {n for n, _ in _existing()}
    assert {"parse", "validate", "corpus", "select", "context", "compare"} <= names
    # Modules from spec 032 that exist are checked; those still to come are skipped by name.
    assert {"npc_slug", "npc_authored", "freshness", "npc_check", "npc_chunked", "npc_config", "npc_verify"} <= names
    assert "npc_draft" not in GUARDED  # the model step, deliberately not guarded
    # Spec 033: every deterministic module of the chunked state documents exists and is checked.
    assert {"notes", "state_sections", "key_npcs", "annotate", "audit_select"} <= names
    # The model steps are not guarded: they are where the calls are made.
    assert {"extract", "synth", "audit", "thread_propose"}.isdisjoint(GUARDED)
    assert {"party_notes", "thread_attach", "thread_check", "arc_check"} <= names


@pytest.mark.parametrize("name,path", _existing(), ids=lambda v: v if isinstance(v, str) else "")
def test_module_makes_no_model_call(name, path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
            if node.module == "campaignlib":
                mods += [f"campaignlib.{a.name}" for a in node.names]
        for m in mods:
            assert not any(m == f or m.startswith(f + ".") for f in FORBIDDEN_MODULES), (
                f"{path.name} imports {m}"
            )
        if isinstance(node, ast.Call):
            f = node.func
            called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert called not in FORBIDDEN_CALLS, f"{path.name} calls {called}"
