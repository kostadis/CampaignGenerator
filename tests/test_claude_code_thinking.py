"""Tri-state thinking control for the claude-code backend (issue #365).

Before this, `thinking` had no CLI flag and no UI toggle — the only reachable
lever was CG_CLAUDE_CODE_THINKING. That made two of the five effort levels
(`xhigh`, `max`) selectable everywhere but usable only by an operator who also
exported a shell variable.

The control is deliberately tri-state rather than boolean. `None` defers to the
environment; `False` is a sticky "off" that beats it. Collapsing the two would
make a deliberate "off" indistinguishable from silence, and an exported
variable would then quietly override the operator.
"""
from __future__ import annotations

import argparse

import pytest

from campaignlib.api import backends as be
from campaignlib.api.client import (
    add_backend_args,
    make_client,
    resolve_cli_claude_thinking,
)
from tests.helpers.fake_claude_cli import FakeClaudeCli


CLAMP_MODEL = "claude-opus-5"
ALWAYS_THINKING_MODEL = "claude-fable-5"


def _args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_backend_args(parser)
    parser.add_argument("--model", default=None)
    return parser.parse_args(argv)


@pytest.fixture
def fake(monkeypatch):
    with FakeClaudeCli() as f:
        monkeypatch.setattr(be, "CLAUDE_CODE_CLI", f.path)
        monkeypatch.delenv("CG_CLAUDE_CODE_THINKING", raising=False)
        monkeypatch.delenv("CG_CLAUDE_CODE_EFFORT", raising=False)
        monkeypatch.delenv("CG_BACKEND", raising=False)
        yield f


def _run(model=CLAMP_MODEL, **client_kwargs):
    client = make_client(backend="claude-code", **client_kwargs)
    client.messages.create(
        model=model, max_tokens=1024, system="s",
        messages=[{"role": "user", "content": "hi"}],
    )
    return client


# =========================================================================
# The flag exists, everywhere, and is genuinely tri-state
# =========================================================================

def test_both_spellings_come_from_one_declaration():
    assert _args(["--backend", "claude-code", "--claude-code-thinking"]).claude_code_thinking is True
    assert _args(["--backend", "claude-code", "--no-claude-code-thinking"]).claude_code_thinking is False


def test_absent_is_none_not_false():
    """The whole point of the tri-state: absent must not look like an
    explicit off, or 'defer to the environment' becomes unreachable."""
    assert _args([]).claude_code_thinking is None


def test_registered_by_add_backend_args_beside_the_effort_options():
    parser = argparse.ArgumentParser()
    add_backend_args(parser)
    flags = {a.option_strings[0] for a in parser._actions if a.option_strings}
    assert "--claude-code-thinking" in flags
    assert "--claude-code-effort" in flags


def test_refused_on_another_backend():
    with pytest.raises(ValueError) as exc:
        resolve_cli_claude_thinking(
            _args(["--backend", "dgx", "--claude-code-thinking"]))
    assert "claude-code" in str(exc.value)
    assert "dgx" in str(exc.value)


def test_resolver_does_not_read_the_environment(monkeypatch):
    """The seam owns the environment fallback. Reading it here too is how the
    two tiers would come to disagree."""
    monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", "1")
    assert resolve_cli_claude_thinking(_args(["--backend", "claude-code"])) is None


# =========================================================================
# Precedence at the seam: per-call > selection > environment > off
# =========================================================================

@pytest.mark.parametrize(
    "call,selection,env,expected",
    [
        (None,  None,  None, False),   # the unchanged default
        (None,  None,  "1",  True),    # the pre-#365 lever still works
        (None,  True,  None, True),    # the new control
        (None,  False, "1",  False),   # sticky off BEATS the environment
        (None,  True,  "",   True),
        (True,  False, None, True),    # a per-call argument wins over both
        (False, True,  "1",  False),
    ],
)
def test_three_tier_precedence(monkeypatch, call, selection, env, expected):
    monkeypatch.delenv("CG_CLAUDE_CODE_THINKING", raising=False)
    if env is not None:
        monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", env)
    assert be._claude_code_thinking(call, selection=selection) is expected


def test_default_is_still_off(monkeypatch):
    """#365 makes thinking selectable; it does not re-decide the default.
    Changing that deserves a fresh measurement, not a side effect."""
    monkeypatch.delenv("CG_CLAUDE_CODE_THINKING", raising=False)
    assert be._claude_code_thinking(None) is False


# =========================================================================
# What the child actually receives
# =========================================================================

def test_selection_on_suppresses_nothing(fake):
    _run(claude_code_thinking=True)
    assert fake.invocations[0].env["MAX_THINKING_TOKENS"] is None
    # ...and with thinking on there is no clamp to apply
    assert fake.invocations[0].has_effort_flag() is False


def test_selection_off_suppresses_and_clamps(fake):
    _run(claude_code_thinking=False)
    assert fake.invocations[0].env["MAX_THINKING_TOKENS"] == "0"
    assert fake.invocations[0].effort() == "high"


def test_sticky_off_beats_an_exported_variable(fake, monkeypatch):
    """The failure this tri-state exists to prevent: an operator stores 'off',
    an unrelated shell export says on, and the run silently thinks anyway."""
    monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", "1")
    _run(claude_code_thinking=False)
    assert fake.invocations[0].env["MAX_THINKING_TOKENS"] == "0"


def test_deferring_still_follows_the_environment(fake, monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", "1")
    _run()
    assert fake.invocations[0].env["MAX_THINKING_TOKENS"] is None


# =========================================================================
# The reason #365 exists: xhigh/max become reachable without an env var
# =========================================================================

@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_top_levels_now_reachable_with_the_flag_alone(fake, level):
    _run(claude_code_effort=level, claude_code_effort_source="explicit",
         claude_code_thinking=True)
    assert fake.invocations[0].effort() == level
    assert fake.invocations[0].env["MAX_THINKING_TOKENS"] is None


@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_top_levels_still_refused_when_thinking_is_explicitly_off(fake, level):
    with pytest.raises(ValueError) as exc:
        _run(claude_code_effort=level, claude_code_effort_source="explicit",
             claude_code_thinking=False)
    assert fake.spawned == 0
    assert level in str(exc.value)


def test_refusal_now_names_the_flag_first():
    """The message used to point only at an environment variable, because
    that was the only remedy. It must name the flag now that one exists."""
    message = be.claude_code_effort_conflict(
        "max", thinking_on=False, model=CLAMP_MODEL)
    assert "--claude-code-thinking" in message
    assert "CG_CLAUDE_CODE_THINKING=1" in message   # still true, still offered
    assert "UI" in message


def test_banner_reports_the_resolved_thinking_state(fake, capsys):
    _run(claude_code_thinking=True)
    assert "thinking=on" in capsys.readouterr().err


# =========================================================================
# Always-thinking families: the flag is accepted and inert
# =========================================================================

def test_off_is_accepted_but_inert_on_an_always_thinking_model(fake):
    """MAX_THINKING_TOKENS=0 is a documented no-op there. Refusing the flag
    would be pedantry; misreporting the result would be a lie, so the banner
    says 'on (always)' regardless of what was asked."""
    client = _run(model=ALWAYS_THINKING_MODEL, claude_code_thinking=False)
    assert client.last_run_identity.banner().count("thinking=on (always)") == 1
    assert fake.invocations[0].has_effort_flag() is False   # never clamped


def test_max_on_an_always_thinking_model_needs_no_thinking_flag(fake):
    _run(model=ALWAYS_THINKING_MODEL,
         claude_code_effort="max", claude_code_effort_source="explicit")
    assert fake.invocations[0].effort() == "max"
