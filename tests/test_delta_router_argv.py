"""039 T019: the delta router only builds argv and shells out (Principle VI)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from server.routers import summary_native_delta as router_mod
from server.subprocess_runner import console_script

SRC = Path(router_mod.__file__)


def test_argv_exact_and_deterministic():
    argv = router_mod.build_delta_argv(
        ["npc", "publish"], force=True, json=True, preview_sha="abc", member=["b", "a"],
        source=["s1", "s2"], plan="P1", campaign_dir="/c")
    assert argv == [
        console_script("summary_native"), "delta", "npc", "publish",
        "--campaign-dir", "/c", "--plan", "P1", "--source", "s1", "--source", "s2",
        "--member", "b", "--member", "a", "--preview-sha", "abc", "--json", "--force",
    ]


def test_none_and_false_are_omitted():
    assert router_mod.build_delta_argv(["run", "status"], plan=None, force=False) == [
        console_script("summary_native"), "delta", "run", "status"]


def test_unknown_flag_rejected():
    with pytest.raises(ValueError):
        router_mod.build_delta_argv(["plan"], all=True)


def test_exit_code_mapping():
    assert router_mod._status_for(3) == 409
    assert router_mod._status_for(4) == 207
    assert router_mod._status_for(5) == 409


def test_empty_sources_is_400():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        router_mod._require_sources([])
    assert e.value.status_code == 400


def test_router_imports_no_pipeline_modules():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("pipelines"), node.module
        elif isinstance(node, ast.Import):
            assert not any(a.name.startswith("pipelines") for a in node.names)


def test_router_registered_in_main():
    import server.main as main_mod
    assert main_mod.summary_native_delta is router_mod
    text = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert 'include_router(summary_native_delta.router, prefix="/api/summary-native/delta"' in text


def test_rebase_flags_emit_in_contract_order():
    argv = router_mod.build_delta_argv(
        ["rebase", "decide"], plan="r1", source_decision=["3=reject"], member_decision=["A=held", "B=repaired"],
        reason="r", reviewer="gm", campaign_dir="/c", json=True)
    assert argv == [
        console_script("summary_native"), "delta", "rebase", "decide", "--campaign-dir", "/c", "--plan", "r1",
        "--reason", "r", "--source-decision", "3=reject", "--member-decision", "A=held",
        "--member-decision", "B=repaired", "--reviewer", "gm", "--json",
    ]


def test_rebase_pairs_and_reviewer_helpers():
    from fastapi import HTTPException
    assert router_mod._pairs({"3": "x", "4": "y"}) == ["3=x", "4=y"]
    assert router_mod._pairs({}) is None and router_mod._pairs(None) is None
    with pytest.raises(HTTPException) as e:
        router_mod._require_reviewer(None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        router_mod._require_reviewer("   ")
    assert router_mod._require_reviewer(" gm ") == "gm"
