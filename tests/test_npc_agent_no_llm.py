"""No model call anywhere in pipelines/npc_agent (Prototype 1 is deterministic).

Walks the AST, so a name in a docstring cannot fool it. Every module in the
package is checked; a model step added later must be listed in MODEL_STEPS here,
deliberately, rather than slipping past.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "pipelines" / "npc_agent"
MODEL_STEPS: set[str] = set()  # none yet
FORBIDDEN_MODULES = ("anthropic", "campaignlib.api", "openai", "pipelines.ensemble")
FORBIDDEN_CALLS = ("make_client", "stream_api", "call_api", "client_from_args")


def _modules():
    return [(p.stem, p) for p in sorted(PKG.glob("*.py")) if p.stem not in MODEL_STEPS]


def test_the_package_exists_and_is_covered():
    assert {"corpus", "dossier", "presence", "rulings", "horizon", "report", "cli"} <= {n for n, _ in _modules()}


@pytest.mark.parametrize("name,path", _modules(), ids=lambda v: v if isinstance(v, str) else "")
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
            assert not any(m == f or m.startswith(f + ".") for f in FORBIDDEN_MODULES), f"{path.name} imports {m}"
        if isinstance(node, ast.Call):
            f = node.func
            called = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert called not in FORBIDDEN_CALLS, f"{path.name} calls {called}"
