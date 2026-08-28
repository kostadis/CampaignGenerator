"""T023 — every LLM-bearing CLI accepts the uniform --batch parameter (FR-002).

Static source-level sweep rather than per-CLI --help subprocesses: a script-path
subprocess in this repo resolves `campaignlib` through the editable-install
.pth (main checkout), which makes --help smoke tests flaky in worktrees. The
live --help loop is quickstart.md §2 and runs as part of T030 validation.

Registrar users get --batch from add_backend_args.  The source inventory also
contains three hand-written ensemble dispatch parsers; only the plural-
endpoint facts_to_state parser and the top-level ensemble dispatcher own the
provider-message batch flag.  The other two are local fan-out dispatchers.
Wording sync for facts_to_state is asserted in tests/test_facts_to_state.py.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_backend_seam_guardrails import (
    _all_calls,
    _call_func_name,
    _parse,
    discover_backend_surfaces,
)

ROOT = Path(__file__).resolve().parent.parent


def _declares_flag(path: str, flag: str) -> bool:
    """Check an exact argparse option token in source AST."""
    return any(
        _call_func_name(node) == "add_argument"
        and node.args
        and getattr(node.args[0], "value", None) == flag
        for node in _all_calls(_parse(ROOT / path))
    )

def test_registrar_clis_use_add_backend_args():
    registrar_clis, _ = discover_backend_surfaces()
    missing = [p for p in registrar_clis
               if not any(
                   _call_func_name(node) == "add_backend_args"
                   for node in _all_calls(_parse(ROOT / p))
               )]
    assert not missing, (
        f"CLIs no longer using the shared registrar (they'd lose --batch): "
        f"{missing}")


def test_hand_rolled_clis_declare_batch():
    _, hand_rolled_clis = discover_backend_surfaces()
    # The plural-endpoint parser and the top-level ensemble dispatcher own
    # provider-message batching.  ensemble_batch and ensemble_extract are
    # local/fan-out dispatchers, so their --batch-shaped application controls
    # must not be mistaken for the provider batch flag.
    batch_owners = {
        p for p in hand_rolled_clis
        if _declares_flag(p, "--batch")
    }
    expected = {
        "pipelines/ensemble/facts_to_state.py",
        "pipelines/ensemble/ensemble.py",
    }
    missing = sorted(expected - batch_owners)
    unexpected = sorted(batch_owners - expected)
    assert not missing, f"hand-rolled vocabulary copies missing --batch: {missing}"
    assert not unexpected, f"unexpected hand-rolled --batch owners: {unexpected}"


def test_no_cli_registers_batch_twice():
    # add_backend_args owns --batch; a CLI that also declares it hand-rolled
    # would crash argparse with "conflicting option string" on every run.
    registrar_clis, _ = discover_backend_surfaces()
    doubled = [p for p in registrar_clis
               if _declares_flag(p, "--batch")]
    assert not doubled, f"duplicate --batch registration (argparse conflict): {doubled}"


def test_shared_client_rejects_codex_batch_before_client_construction(monkeypatch):
    """Provider-message batching is an Anthropic capability, not a generic
    backend flag. The shared seam must refuse Codex before ``make_client``
    (and therefore before an isolated Codex child could be started)."""
    from campaignlib.api import client as client_mod

    def _boom(*_args, **_kwargs):
        raise AssertionError("make_client must not run for Codex --batch")

    monkeypatch.setattr(client_mod, "make_client", _boom)
    args = SimpleNamespace(
        backend="codex-cli", model="gpt-5-codex", endpoint=None, batch=True,
    )
    with pytest.raises(SystemExit, match=r"--batch.*codex-cli"):
        client_mod.client_from_args(args)


def test_shared_client_keeps_anthropic_batch_path(monkeypatch):
    """The refusal is provider-specific; Anthropic still reaches the client
    factory when ``--batch`` is selected."""
    from campaignlib.api import client as client_mod

    sentinel = object()
    monkeypatch.setattr(client_mod, "make_client", lambda **_kwargs: sentinel)
    args = SimpleNamespace(
        backend="anthropic", model=None, endpoint=None, batch=True,
    )
    assert client_mod.client_from_args(args) is sentinel
