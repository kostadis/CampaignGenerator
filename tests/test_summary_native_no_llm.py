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
GUARDED = ["parse", "validate", "corpus", "duplicates", "select", "context", "compare"]
FORBIDDEN_MODULES = ("anthropic", "campaignlib.api", "openai", "pipelines.ensemble")
FORBIDDEN_CALLS = ("make_client", "stream_api", "call_api", "client_from_args")


def _existing():
    return [(n, PKG / f"{n}.py") for n in GUARDED if (PKG / f"{n}.py").is_file()]


def test_guard_covers_the_modules_that_exist():
    names = {n for n, _ in _existing()}
    assert {"parse", "validate", "corpus"} <= names


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
