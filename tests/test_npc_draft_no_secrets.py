"""Secrets never reach a model (spec 032 T020, FR-018a)."""

from __future__ import annotations

import ast
from pathlib import Path

from pipelines.summary_native import npc_draft, synth
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli

PKG = Path(__file__).resolve().parents[1] / "pipelines" / "summary_native"
CANARY = "SECRET-CANARY-7731"


def _tree():
    return ast.parse((PKG / "npc_draft.py").read_text(encoding="utf-8"))


def test_npc_draft_reads_authored_data_only_through_load_manual():
    tree = _tree()
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "npc_authored":
            used.add(node.attr)
        if isinstance(node, (ast.Name, ast.Attribute)):
            ident = node.id if isinstance(node, ast.Name) else node.attr
            assert ident not in {"load_secrets", "_load", "read_handbuilt", "init_authored"}, ident
    assert used <= {"load_manual", "AuthoredError"}, used
    assert "load_manual" in used


def test_npc_draft_never_opens_files_or_parses_yaml_itself():
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert "yaml" not in mods, "npc_draft must not parse YAML"
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            assert name not in {"open", "safe_load", "load"}, name
    # no string literal in code (docstrings aside) names the authored file shape
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            assert ".authored" not in node.value and "authored/" not in node.value, node.value


def test_canary_reaches_only_the_gm_dossier(tmp_path, monkeypatch):
    root = npc_campaign(tmp_path)
    shared = [
        "--config", str(root / "config/config.yaml"), "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL),
    ]
    assert run_cli(["npc-link", *shared])[0] == 0
    d = root / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text(
        f"subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\nsecrets: |\n  {CANARY} owes a fence\n", encoding="utf-8")
    body = "\n".join(f"{h}\n\n- ok [ch 002 / 002.01]\n" for h in synth.load_outline("npc_dossier"))
    monkeypatch.setattr(npc_draft, "render_part", lambda *a, **k: body)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    assert run_cli(["npc-draft", *shared, "--mode", "one-shot", "--all"])[0] == 0
    assert run_cli(["npc-draft", *shared, "--all", "--dump-only"])[0] == 0
    out = root / "docs/npcs/summary_native/ch002-006"
    leaks = [
        p for sub in ("runs", "draft", "evidence") for p in (out / sub).rglob("*")
        if p.is_file() and CANARY in p.read_text(encoding="utf-8")
    ]
    assert not leaks, leaks
    assert any((out / "runs").rglob("*.user.md")) and any((out / "draft").glob("npc_*.md"))
    gm = (out / "gm/npc_jimjar.md").read_text(encoding="utf-8")
    assert gm.count(CANARY) == 1 and gm.endswith(f"## Secrets\n{CANARY} owes a fence\n")
    for other in (out / "gm").glob("*.md"):
        if other.name != "npc_jimjar.md":
            assert CANARY not in other.read_text(encoding="utf-8")


def test_canary_never_reaches_a_map_or_reduce_file(tmp_path, monkeypatch):
    """T060: the chunked run files (mapNN/reduce system, user and out, drops) carry no Secrets."""
    from tests.conftest_npc import REDUCE_BODY, kind_of, map_output

    root = npc_campaign(tmp_path)
    shared = [
        "--config", str(root / "config/config.yaml"), "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL),
    ]
    assert run_cli(["npc-link", *shared])[0] == 0
    d = root / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text(
        f"subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\nsecrets: |\n  {CANARY} owes a fence\n", encoding="utf-8")
    calls = []

    def render(client, system, user, model, max_tokens):
        calls.append(kind_of(system))
        return map_output(user) if kind_of(system) == "map" else REDUCE_BODY

    monkeypatch.setattr(npc_draft, "render_part", render)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    assert run_cli(["npc-draft", *shared, "--all", "--chunk-chars", "1"])[0] == 0
    assert run_cli(["npc-draft", *shared, "--all", "--chunk-chars", "1", "--dump-only"])[0] == 0
    assert "map" in calls and "reduce" in calls
    out = root / "docs/npcs/summary_native/ch002-006"
    files = [p for p in (out / "runs").rglob("*") if p.is_file()]
    assert any(".map01." in p.name for p in files) and any(".reduce.user" in p.name for p in files)
    assert any(".drops." in p.name for p in files)
    leaks = [p for sub in ("runs", "draft", "evidence") for p in (out / sub).rglob("*")
             if p.is_file() and CANARY in p.read_text(encoding="utf-8")]
    assert not leaks, leaks
