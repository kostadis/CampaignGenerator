"""Layering guard — the CLI engine must not import the web server.

Phase 1 of ``docs/config/grounding-isolation.md``. The architecture is "disk is
truth, CLI is the engine, the server is a thin router" (``docs/config/
subsystems.md``), but two CLIs had inverted it: ``pipelines/grounding/party.py``
did ``from server.party_config_shared import …`` and
``pipelines/grounding/planning.py`` did the same for its own config module.

The shared models moved to ``campaignlib``, so the arrow points one way now:
``server/`` and ``pipelines/`` both depend on ``campaignlib``, and neither
depends on the other. This test exists so the next person to need a model in
both places reaches for ``campaignlib`` instead of re-importing ``server``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Packages that make up the engine/library layer. Nothing here may import the
#: web-server layer. ``server/`` itself is deliberately absent — it is allowed
#: (and expected) to import ``campaignlib``.
ENGINE_PACKAGES = (
    "campaignlib",
    "pipelines",
    "session_doc",
    "entity_registry",
    "provenance",
)


def _engine_modules() -> list[Path]:
    files: list[Path] = []
    for pkg in ENGINE_PACKAGES:
        pkg_dir = REPO_ROOT / pkg
        if pkg_dir.is_dir():
            files.extend(
                p for p in pkg_dir.rglob("*.py") if "__pycache__" not in p.parts
            )
    return sorted(files)


def _imports_server(tree: ast.AST) -> list[str]:
    """Return the offending statements, rendered, or [] if clean."""
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `from . import x` inside a package has module=None, level>0 —
            # never a reference to the top-level `server` package.
            if node.level == 0 and node.module and (
                node.module == "server" or node.module.startswith("server.")
            ):
                names = ", ".join(a.name for a in node.names)
                bad.append(f"from {node.module} import {names}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "server" or alias.name.startswith("server."):
                    bad.append(f"import {alias.name}")
    return bad


def test_engine_layer_does_not_import_server():
    """No module under campaignlib/pipelines/session_doc/entity_registry may
    import from the ``server`` package."""
    offenders: dict[str, list[str]] = {}
    for path in _engine_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if bad := _imports_server(tree):
            offenders[str(path.relative_to(REPO_ROOT))] = bad

    assert not offenders, (
        "engine-layer modules must not import the web server "
        "(move the shared piece into campaignlib instead):\n"
        + "\n".join(f"  {f}: {'; '.join(v)}" for f, v in sorted(offenders.items()))
    )


def test_guard_detects_a_violation():
    """The guard above is only meaningful if it can actually fail."""
    tree = ast.parse("from server.party_config_shared import load_party_config")
    assert _imports_server(tree)
    tree = ast.parse("import server.config")
    assert _imports_server(tree)
    # ...and does not fire on the legitimate cases.
    assert not _imports_server(ast.parse("from campaignlib.party_config import x"))
    assert not _imports_server(ast.parse("from .planning_config import x"))
    assert not _imports_server(ast.parse("import observer"))


def test_engine_packages_exist():
    """Guard against the guard silently covering nothing after a move."""
    missing = [p for p in ENGINE_PACKAGES if not (REPO_ROOT / p).is_dir()]
    assert not missing, f"ENGINE_PACKAGES lists nonexistent dirs: {missing}"
    assert len(_engine_modules()) > 20


def test_narration_bundle_helpers_stay_in_the_engine_layer():
    for rel in ("session_doc/narrate.py", "session_doc/sd_narrate.py"):
        path = REPO_ROOT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not _imports_server(tree), f"{rel} must not import the server layer"
