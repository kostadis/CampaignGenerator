"""Guardrails for the unified LLM backend-selection seam (campaignlib.api.client).

Before this test existed, backend selection fragmented three ways: some
scripts had bespoke --dgx-endpoint/--dgx-model flags, some had no backend
flag at all (env-only), and three server routers each independently
reimplemented a backend->env translator (two of which silently dropped the
"openrouter" choice). This test enforces the two invariants that keep it
from re-fragmenting:

1. No script outside campaignlib/api/client.py may call make_client(
   directly — every caller goes through client_from_args (optionally with
   its `endpoint=` override for fan-out callers), which is the one place
   that resolves --backend/--endpoint/--model into a client.
2. Every script that declares a --model argparse flag must also call
   add_backend_args( — a model choice without a backend choice is exactly
   the shape of the bug this seam exists to prevent. The ensemble
   dispatcher family (ensemble.py / ensemble_batch.py / ensemble_extract.py)
   is exempted: they never build a client themselves, only forward a bare
   --backend down a subprocess chain, so add_backend_args's --endpoint
   (singular) would be a redundant third endpoint-shaped flag alongside
   their existing --endpoints (plural, fan-out).

Both checks use AST (not substring/regex): a substring scan on "make_client("
false-positives on prose that merely mentions it (a comment did, at the time
this test was written), and a same-line regex on --model would miss the
common multi-line `parser.add_argument(\\n    "--model", ...)` form while
false-positiving on "--model" appearing as a subprocess-argv string literal
in the server routers.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

from campaignlib.api import client as client_mod


REPO_ROOT = Path(__file__).resolve().parent.parent
SEAM_FILE = "campaignlib/api/client.py"
SKIP_DIRS = {
    "venv", ".venv", "__pycache__", "node_modules", "frontend",
    ".git", "logs", "tests",
}

# Dispatcher scripts that intentionally use a bare --backend instead of
# add_backend_args (see module docstring) — never build a client themselves.
ALLOWED_DISPATCHER_FILES = {"ensemble.py", "ensemble_batch.py", "ensemble_extract.py"}

# Files that define their OWN unrelated make_client( — a name collision, not
# a seam bypass. kanka_mcp.py's make_client() builds a KankaClient (the
# Kanka wiki API), never touches an LLM backend at all.
ALLOWED_NAME_COLLISION_FILES = {"kanka_mcp.py"}


def _is_candidate_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    rel = path.relative_to(REPO_ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    if ".specify" in rel.parts:
        return False
    return True


def _iter_candidate_files():
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if _is_candidate_file(path):
            yield path


def _parse(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"{path}: could not parse: {exc}")


def _call_func_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _all_calls(tree: ast.Module):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


_CANDIDATE_FILES = list(_iter_candidate_files())
_CANDIDATE_IDS = [str(p.relative_to(REPO_ROOT)) for p in _CANDIDATE_FILES]


# ── Check 1: make_client( only inside the seam ──────────────────────────────

@pytest.mark.parametrize("path", _CANDIDATE_FILES, ids=_CANDIDATE_IDS)
def test_no_out_of_seam_make_client(path: Path):
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel == SEAM_FILE:
        pytest.skip("make_client is defined and legitimately called here")
    if path.name in ALLOWED_NAME_COLLISION_FILES:
        pytest.skip("defines its own unrelated make_client( — see ALLOWED_NAME_COLLISION_FILES")

    tree = _parse(path)
    offenders = [
        node.lineno for node in _all_calls(tree)
        if _call_func_name(node) == "make_client"
    ]
    assert not offenders, (
        f"{rel} calls make_client( directly at line(s) {offenders} — "
        "route through campaignlib.api.client.client_from_args instead "
        "(pass endpoint= for fan-out callers)."
    )


# ── Check 2: every --model flag comes with add_backend_args ─────────────────

def _declares_model_flag(tree: ast.Module) -> bool:
    for node in _all_calls(tree):
        if _call_func_name(node) != "add_argument":
            continue
        if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "--model":
            return True
    return False


@pytest.mark.parametrize("path", _CANDIDATE_FILES, ids=_CANDIDATE_IDS)
def test_model_flag_implies_backend_args(path: Path):
    rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    if rel == SEAM_FILE:
        pytest.skip("defines add_backend_args itself")

    tree = _parse(path)
    if not _declares_model_flag(tree):
        pytest.skip("no --model flag declared")
    if path.name in ALLOWED_DISPATCHER_FILES:
        pytest.skip("dispatcher script — forwards --backend without add_backend_args")

    source = path.read_text(encoding="utf-8")
    assert "add_backend_args(" in source, (
        f"{rel} declares --model but never calls add_backend_args( — "
        "every script with a model choice must also expose --backend/--endpoint."
    )


# ── Check 3: --batch is uniform (spec 004-claude-api-batch) ─────────────────

def test_add_backend_args_registers_batch_flag():
    """Every registrar CLI gets --batch spelled and defaulted identically
    (FR-001/FR-002) — a store_true defaulting to False, byte-identical
    behavior when omitted (FR-011)."""
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="claude-sonnet-4-6")
    client_mod.add_backend_args(p)
    ns = p.parse_args([])
    assert ns.batch is False
    ns_on = p.parse_args(["--batch"])
    assert ns_on.batch is True


@pytest.mark.parametrize("backend", ["dgx", "openrouter", "claude-code"])
def test_client_from_args_rejects_batch_for_non_anthropic_backend(backend, monkeypatch):
    """--batch requires the real Anthropic client — none of the façades
    implement messages.batches, so this must fail before construction."""
    def _boom(*a, **kw):
        raise AssertionError("make_client must not be called before the --batch rejection")

    monkeypatch.setattr(client_mod, "make_client", _boom)
    ns = argparse.Namespace(backend=backend, endpoint=None, model="m", batch=True)

    with pytest.raises(SystemExit) as exc_info:
        client_mod.client_from_args(ns)

    assert f"backend '{backend}' has no batch support" in str(exc_info.value)
    assert "--batch requires the Claude API backend (--backend anthropic)" in str(exc_info.value)


def test_client_from_args_rejects_batch_via_cg_backend_env(monkeypatch):
    """--backend anthropic (the default) + CG_BACKEND=openrouter + --batch
    must still be rejected — the env-driven resolution, not just the
    explicit --backend flag, decides what --batch is validated against."""
    def _boom(*a, **kw):
        raise AssertionError("make_client must not be called before the --batch rejection")

    monkeypatch.setattr(client_mod, "make_client", _boom)
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    ns = argparse.Namespace(backend="anthropic", endpoint=None, model="m", batch=True)

    with pytest.raises(SystemExit) as exc_info:
        client_mod.client_from_args(ns)

    assert "backend 'openrouter' has no batch support" in str(exc_info.value)


def test_client_from_args_allows_batch_for_anthropic(monkeypatch):
    """The default (anthropic, no CG_BACKEND) must not be rejected."""
    monkeypatch.delenv("CG_BACKEND", raising=False)
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend) or "client")
    ns = argparse.Namespace(backend="anthropic", endpoint=None, model="m", batch=True)

    out = client_mod.client_from_args(ns)

    assert out == "client"
    assert seen == {"backend": None}


def test_client_from_args_batch_absent_is_unaffected(monkeypatch):
    """No --batch attribute at all (an older/unrelated caller's Namespace)
    must not trip the check — getattr(..., False) is the guard."""
    seen = {}
    monkeypatch.setattr(client_mod, "make_client",
                        lambda backend=None, endpoint=None, model_override=None:
                        seen.update(backend=backend) or "client")
    ns = argparse.Namespace(backend="dgx", endpoint=None, model="m")  # no .batch

    out = client_mod.client_from_args(ns)

    assert out == "client"


# ── Check 4: messages.batches only referenced inside the seam ───────────────

def test_no_out_of_seam_messages_batches_reference():
    """The Message Batches API surface (client.messages.batches.*) is only
    ever touched from campaignlib/api/ — every other CLI/pipeline goes
    through run_batch / run_single_batch / submit_batch / poll_batch /
    collect_batch instead (spec 004-claude-api-batch contract)."""
    offenders = []
    seam = (REPO_ROOT / "campaignlib" / "api").resolve()
    for py in REPO_ROOT.rglob("*.py"):
        rp = py.resolve()
        if seam in rp.parents or rp.parent == seam:
            continue
        if "/tests/" in str(rp) or rp.name.startswith("test_"):
            continue
        if ".specify" in rp.parts or "node_modules" in rp.parts or ".venv" in rp.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if "messages.batches" in text:
            offenders.append(str(rp.relative_to(REPO_ROOT)))
    assert not offenders, f"messages.batches referenced outside campaignlib/api/: {offenders}"
