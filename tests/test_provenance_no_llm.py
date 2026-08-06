"""FR-033: no LLM call anywhere in ``provenance/``.

The provenance seam answers "what does disk actually say, and how much should
you trust it." Every answer it gives must be checkable by reading the same files
the caller could read. One ``stream_api`` call inside it — to rank hits more
cleverly, to summarise an excerpt, to guess which alias was meant — would turn a
verifiable claim into an unverifiable one, and the caller would have no way to
tell which kind they were holding.

That is not a style preference, it is the feature's whole premise, so it is
guarded statically rather than by review. A grep would be fooled by a name in a
docstring; this walks the AST.

Sibling guard: ``tests/test_retrieve_render_isolation.py`` keeps retrieval and
render apart *within* a function. This one keeps render out of the package
entirely.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG = REPO_ROOT / "provenance"

#: Importing any of these means an API client is reachable from this package.
FORBIDDEN_MODULES = ("anthropic", "campaignlib.api", "openai")

#: Calling any of these means a model was asked to decide something.
FORBIDDEN_CALLS = (
    "make_client",
    "stream_api",
    "call_api",
    "run_batch",
    "messages",  # anthropic's client.messages.create surface
)


def _package_modules() -> list[Path]:
    if not PKG.is_dir():
        return []
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _forbidden_imports(tree: ast.AST) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and any(
                mod == f or mod.startswith(f + ".") for f in FORBIDDEN_MODULES
            ):
                names = ", ".join(a.name for a in node.names)
                bad.append(f"from {mod} import {names}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(
                    alias.name == f or alias.name.startswith(f + ".")
                    for f in FORBIDDEN_MODULES
                ):
                    bad.append(f"import {alias.name}")
    return bad


def _forbidden_calls(tree: ast.AST) -> list[str]:
    """Any reference to an API-calling name, whether called or merely bound.

    Checks references rather than call sites specifically: assigning
    ``fn = stream_api`` and calling ``fn()`` later would slip past a
    call-site-only check, and the point is that the name must not be reachable
    from this package at all.
    """
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            bad.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
            bad.append(f".{node.attr}")
    return bad


def test_provenance_package_exists() -> None:
    """Guard the guard: an empty package would make every test below vacuous."""
    assert PKG.is_dir(), "provenance/ package is missing"
    assert _package_modules(), "provenance/ contains no Python modules"


@pytest.mark.parametrize("path", _package_modules(), ids=lambda p: p.name)
def test_no_llm_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = _forbidden_imports(tree)
    assert not bad, (
        f"{path.relative_to(REPO_ROOT)} imports an LLM client: {bad}. "
        "FR-033: the provenance seam makes no LLM call. If a task seems to "
        "need one, the structure is wrong — fix the structure."
    )


@pytest.mark.parametrize("path", _package_modules(), ids=lambda p: p.name)
def test_no_llm_calls(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = _forbidden_calls(tree)
    assert not bad, (
        f"{path.relative_to(REPO_ROOT)} references an API-calling name: "
        f"{sorted(set(bad))}. FR-033."
    )
