"""Principle V guard (spec 039): nothing under pipelines/summary_native/delta/
imports the anthropic SDK. Model calls go through campaignlib only.

AST-based, so a mention in a docstring or comment cannot trip it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DELTA = ROOT / "pipelines" / "summary_native" / "delta"


def anthropic_imports(source: str) -> list[str]:
    """Return every `import anthropic...` / `from anthropic... import` in source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name == "anthropic" or a.name.startswith("anthropic.")]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == "anthropic" or mod.startswith("anthropic.")):
                found.append(mod)
    return found


def test_detector_flags_synthetic_imports():
    assert anthropic_imports("import anthropic\n") == ["anthropic"]
    assert anthropic_imports("from anthropic import Anthropic\n") == ["anthropic"]
    assert anthropic_imports("import anthropic.types as t\n") == ["anthropic.types"]
    assert anthropic_imports("# import anthropic\nx = 'from anthropic import X'\n") == []
    assert anthropic_imports("from campaignlib import make_client\n") == []


def test_delta_package_never_imports_anthropic():
    if not DELTA.is_dir():
        pytest.skip("pipelines/summary_native/delta/ does not exist yet")
    offenders = {}
    for path in sorted(DELTA.rglob("*.py")):
        hits = anthropic_imports(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert not offenders, f"Principle V: anthropic imported in delta: {offenders}"
