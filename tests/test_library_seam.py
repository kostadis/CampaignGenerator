"""Principle V: only pipelines/rlm/mempalace_client.py talks to mempalace."""

import ast
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "pipelines" / "library"


def violations(source: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out += [f"import {a.name}" for a in node.names if a.name.split(".")[0] == "mempalace"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "mempalace":
                out.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            f = node.func
            owner = getattr(getattr(f, "value", None), "id", None)
            if owner in ("subprocess", "os") or getattr(f, "id", "") in ("Popen", "run", "system"):
                strings = [
                    c.value for c in ast.walk(node)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                ]
                if any("mempalace" in s for s in strings):
                    out.append("subprocess call naming mempalace")
    return out


def test_detector_catches_violations():
    assert violations("import mempalace.searcher")
    assert violations("from mempalace.searcher import x")
    assert violations("import subprocess\nsubprocess.run(['mempalace','mine'])")
    assert not violations("from pipelines.rlm.mempalace_client import mine")
    assert not violations("import subprocess\nsubprocess.run(['git','status'])")


def test_library_never_touches_mempalace_directly():
    files = sorted(LIB.glob("*.py"))
    assert files
    bad = {f.name: v for f in files if (v := violations(f.read_text(encoding="utf-8")))}
    assert not bad, bad
