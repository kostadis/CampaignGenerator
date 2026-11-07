"""039 T020 / Principle XII: the delta router declares no literal default for a backend, model or path."""

from __future__ import annotations

import ast
from pathlib import Path

from server.routers import summary_native_delta as router_mod

SRC = Path(router_mod.__file__)
NAMES = ("backend", "model", "path", "dir", "config", "out_root", "endpoint")


def _is_str_literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value != ""


def _hits(name: str) -> bool:
    return any(k in name.lower() for k in NAMES)


def test_no_string_default_for_backend_model_or_path_in_signatures():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = fn.args
        pos = a.posonlyargs + a.args
        for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults):
            if _hits(arg.arg) and _is_str_literal(d):
                offenders.append((fn.name, arg.arg))
        for arg, d in zip(a.kwonlyargs, a.kw_defaults):
            if d is not None and _hits(arg.arg) and _is_str_literal(d):
                offenders.append((fn.name, arg.arg))
    assert not offenders, offenders


def test_no_string_default_in_model_fields_or_field_calls():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
            if _hits(node.target.id):
                v = node.value
                if _is_str_literal(v):
                    offenders.append(node.target.id)
                if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "Field":
                    for kw in v.keywords:
                        if kw.arg == "default" and _is_str_literal(kw.value):
                            offenders.append(node.target.id)
    assert not offenders, offenders


def test_no_backend_or_path_literals_anywhere():
    src = SRC.read_text(encoding="utf-8")
    for lit in ('"anthropic"', '"claude-code"', '"dgx"', "docs/", "config.yaml"):
        assert lit not in src, lit


def test_models_resolve_through_the_owning_config():
    src = SRC.read_text(encoding="utf-8")
    assert "resolve_selection(" in src and ".summary_native" in src
