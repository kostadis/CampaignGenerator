"""Parser and model-intent guardrails for the production CLI family.

The production commands are intentionally not imported here.  Most of them
parse ``sys.argv`` at module import time and a few transitively load optional
DGX dependencies.  AST inspection gives this contract test the same coverage
without running command bodies or requiring a local model installation.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import pytest

from campaignlib.api import client as client_mod
from campaignlib.api.codex_cli import CodexCliError
from tests.helpers.fake_codex_cli import FakeCodexCli
from test_backend_seam_guardrails import (
    _all_calls,
    _backend_choices,
    _call_func_name,
    _parse,
    discover_backend_surfaces,
    discover_runtime_dispatchers,
)


ROOT = Path(__file__).resolve().parent.parent
REGISTRARS, HAND_WRITTEN = discover_backend_surfaces()
DISPATCHERS = discover_runtime_dispatchers(REGISTRARS, HAND_WRITTEN)
DIRECT_COMMANDS = tuple(sorted((REGISTRARS | HAND_WRITTEN) - DISPATCHERS))


def _calls(tree, name: str):
    return [node for node in _all_calls(tree) if _call_func_name(node) == name]


def _model_arguments(tree: ast.Module):
    return [
        node
        for node in _all_calls(tree)
        if _call_func_name(node) == "add_argument"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "--model"
    ]


def _has_omission_default(node: ast.Call) -> bool:
    """Whether an argparse model option defaults to the omission sentinel.

    An absent argparse ``default`` and ``default=None`` are equivalent, and
    both preserve the distinction from a command's legacy non-Codex default,
    which is supplied later to ``resolve_cli_model``.
    """
    defaults = [keyword.value for keyword in node.keywords if keyword.arg == "default"]
    return not defaults or (
        isinstance(defaults[0], ast.Constant) and defaults[0].value is None
    )


def test_direct_inventory_contains_26_model_bearing_commands():
    """The four dispatchers are excluded from the 30-surface direct set."""
    assert len(REGISTRARS) == 26
    assert len(HAND_WRITTEN) == 4
    assert len(DISPATCHERS) == 4
    assert len(DIRECT_COMMANDS) == 26


@pytest.mark.parametrize("relative_path", DIRECT_COMMANDS)
def test_direct_command_has_model_option_with_omission_default(relative_path: str):
    """Every direct command lets the shared resolver restore legacy defaults."""
    tree = _parse(ROOT / relative_path)
    model_args = _model_arguments(tree)
    assert model_args, f"{relative_path} has no --model parser option"
    assert all(_has_omission_default(node) for node in model_args), (
        f"{relative_path} gives --model a literal default; omitted Codex "
        "model intent must remain distinguishable from explicit input"
    )


@pytest.mark.parametrize("relative_path", DIRECT_COMMANDS)
def test_direct_command_adopts_shared_model_resolver(relative_path: str):
    """No direct command may resolve model provenance in a private dialect."""
    tree = _parse(ROOT / relative_path)
    assert _calls(tree, "resolve_cli_model"), (
        f"{relative_path} does not call campaignlib.api.client.resolve_cli_model"
    )


def test_shared_backend_help_mentions_canonical_codex_once():
    """The shared registrar emits one, and only one, Codex help spelling."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    client_mod.add_backend_args(parser)
    help_text = parser.format_help()
    backend_action = next(action for action in parser._actions if action.dest == "backend")

    # argparse repeats choices in usage and option-detail lines; the semantic
    # vocabulary itself must contain one canonical entry, and help must expose
    # it rather than silently hiding the subscription backend.
    assert tuple(backend_action.choices).count("codex-cli") == 1
    assert "codex-cli" in help_text


def test_direct_hand_written_backend_choice_has_canonical_codex_once():
    """The plural-endpoint direct parser cannot drift from shared vocabulary."""
    hand_direct = HAND_WRITTEN - DISPATCHERS
    assert hand_direct == {"pipelines/ensemble/facts_to_state.py"}
    for relative_path in hand_direct:
        choices = _backend_choices(_parse(ROOT / relative_path))
        assert choices == set(client_mod.BACKENDS), (
            f"{relative_path} drifts from canonical BACKENDS in --backend choices"
        )


FAST_COMMANDS = tuple(
    sorted(
        relative_path
        for relative_path in DIRECT_COMMANDS
        if any(
            _call_func_name(node) == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "--fast"
            for node in _all_calls(_parse(ROOT / relative_path))
        )
    )
)


@pytest.mark.parametrize("relative_path", FAST_COMMANDS)
def test_codex_rejects_explicit_fast_claude_mapping(relative_path: str):
    """Fast mode's explicit Claude mapping must fail closed for Codex."""
    args = argparse.Namespace(backend="codex-cli", model="claude-haiku-4-5")
    with pytest.raises((ValueError, RuntimeError, SystemExit), match="incompatible|Claude"):
        client_mod.resolve_cli_model(args, legacy_default="claude-sonnet-4-6")


# One import-safe representative per direct command family.  The source files
# are deliberately inspected instead of imported: some direct CLIs load
# optional DGX modules at import time.  The real client seam below is then
# exercised with the process-backed fake, so this checks both halves of the
# contract without requiring a live backend or a family-specific CLI setup.
FAMILY_REPRESENTATIVES = (
    ("session-document", "session_doc/check_consistency.py"),
    ("prep-ingest-search", "pipelines/session_prep/prep.py"),
    ("grounding", "pipelines/grounding/planning.py"),
    ("ensemble", "pipelines/ensemble/extract_facts.py"),
)


@pytest.mark.parametrize("family,relative_path", FAMILY_REPRESENTATIVES)
@pytest.mark.parametrize("explicit_model", [True, False], ids=["explicit", "omitted"])
def test_four_family_codex_selection_reaches_fake_child(
    monkeypatch, tmp_path, family, relative_path, explicit_model
):
    """Representative family paths reach one isolated Codex child.

    This intentionally combines source inspection with the shared adapter
    harness.  It remains import-safe for the direct CLIs while proving that
    explicit model intent is forwarded and omitted intent stays omitted.
    """
    tree = _parse(ROOT / relative_path)
    assert _calls(tree, "resolve_cli_model"), (
        f"{relative_path} must resolve selection through the shared seam"
    )

    fake = FakeCodexCli(
        tmp_path,
        response=FakeCodexCli.direct(f"fake {family} response"),
    )
    fake.install(monkeypatch)
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.setenv(key, f"metered-{key.lower()}")

    requested = "gpt-5-codex" if explicit_model else None
    args = argparse.Namespace(
        backend="codex-cli", endpoint=None, batch=False, model=requested
    )
    intent = client_mod.resolve_cli_model(args, legacy_default="claude-sonnet-4-6")
    args.model = intent.effective_model
    client = client_mod.client_from_args(args)
    response = client.messages.create(
        model=intent.effective_model,
        max_tokens=64,
        system=f"System for {family}",
        messages=[{"role": "user", "content": "Return a short acceptance response."}],
    )

    assert response.content[0].text == f"fake {family} response"
    invocation = fake.last_call
    assert invocation is not None
    if explicit_model:
        model_position = invocation.argv.index("--model")
        assert invocation.argv[model_position + 1] == "gpt-5-codex"
    else:
        assert "--model" not in invocation.argv


def test_four_family_codex_failure_does_not_fallback_to_provider(
    monkeypatch, tmp_path
):
    """A failed subscription child is surfaced, never retried via a provider."""
    fake = FakeCodexCli(
        tmp_path,
        response=FakeCodexCli.direct(
            "partial output", returncode=23, stderr="codex child failed"
        ),
    )
    fake.install(monkeypatch)
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    args = argparse.Namespace(
        backend="codex-cli", endpoint=None, batch=False, model=None
    )
    client = client_mod.client_from_args(args)
    with pytest.raises(CodexCliError, match="exited 23"):
        client.messages.create(
            model=None,
            max_tokens=64,
            system="No fallback",
            messages=[{"role": "user", "content": "fail once"}],
        )

    assert len(fake.calls) == 1
    assert fake.last_call is not None
