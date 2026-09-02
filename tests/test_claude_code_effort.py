"""CLI resolution, refusals, and run identity for the claude-code effort level.

Feature 021. The companion to ``tests/test_codex_reasoning_effort.py``, with
one structural difference that drives most of these tests: this backend
*already* sends an effort level today, hardcoded, so "omission" is two
distinguishable behaviours (a compatibility clamp, or true inheritance from
the operator's own settings.json) rather than one.
"""
from __future__ import annotations

import argparse

import pytest

from campaignlib.api import backends as be
from campaignlib.api.client import (
    add_backend_args,
    make_client,
    resolve_cli_claude_effort,
)
from tests.helpers.fake_claude_cli import FakeClaudeCli


CLAMP_MODEL = "claude-opus-5"          # thinking can be disabled -> clamp applies
ALWAYS_THINKING_MODEL = "claude-fable-5"  # thinking cannot be disabled -> no clamp


def _args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    add_backend_args(parser)
    parser.add_argument("--model", default=None)
    return parser.parse_args(argv)


@pytest.fixture
def fake(monkeypatch):
    with FakeClaudeCli() as f:
        # CLAUDE_CODE_CLI is read from CG_CLAUDE_CLI once, at import — so the
        # env var cannot reach an already-imported module. Patch the attribute.
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
# T011 — the option exists, and precedence resolves
# =========================================================================

def test_option_is_registered_by_add_backend_args():
    """Registered inside add_backend_args, so all 30 model-bearing CLIs
    inherit it. This is the whole of CLI parity."""
    args = _args(["--backend", "claude-code", "--claude-code-effort", "high"])
    assert args.claude_code_effort == "high"


def test_option_defaults_to_none_not_a_value():
    args = _args([])
    assert args.claude_code_effort is None


def test_explicit_beats_environment(monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", "low")
    intent = resolve_cli_claude_effort(
        _args(["--backend", "claude-code", "--claude-code-effort", "high"])
    )
    assert (intent.effective_effort, intent.source) == ("high", "explicit")


def test_environment_used_when_nothing_explicit(monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", "medium")
    intent = resolve_cli_claude_effort(_args(["--backend", "claude-code"]))
    assert (intent.effective_effort, intent.source) == ("medium", "environment")


def test_omission_when_neither(monkeypatch):
    monkeypatch.delenv("CG_CLAUDE_CODE_EFFORT", raising=False)
    intent = resolve_cli_claude_effort(_args(["--backend", "claude-code"]))
    assert intent.effective_effort is None
    assert intent.source == "omitted"
    assert intent.emit_override is False


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_whitespace_environment_is_omission_not_an_empty_override(monkeypatch, raw):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", raw)
    intent = resolve_cli_claude_effort(_args(["--backend", "claude-code"]))
    assert intent.effective_effort is None
    assert intent.source == "omitted"


@pytest.mark.parametrize("raw", [" high", "high\n", "\thigh "])
def test_padded_environment_value_is_stripped_and_accepted(monkeypatch, raw):
    """Mirrors the Codex resolver: the env var is stripped before validation,
    so a stray newline from `export`-in-a-script is not a hard failure. Only
    whitespace-ONLY is omission, and a padded CLI value is rejected by
    argparse's own choices= before this code runs."""
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", raw)
    intent = resolve_cli_claude_effort(_args(["--backend", "claude-code"]))
    assert (intent.effective_effort, intent.source) == ("high", "environment")


def test_ambient_environment_on_another_backend_is_omission_not_a_refusal(monkeypatch):
    """An exported convenience must not break every unrelated command."""
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", "high")
    intent = resolve_cli_claude_effort(_args(["--backend", "dgx"]))
    assert intent.effective_effort is None
    assert intent.source == "omitted"


# =========================================================================
# T012 — every refusal fires before a child process exists
# =========================================================================

def test_rejects_value_outside_vocabulary():
    with pytest.raises(SystemExit):
        _args(["--backend", "claude-code", "--claude-code-effort", "ultra"])


def test_rejects_minimal_which_is_codex_only():
    with pytest.raises(SystemExit):
        _args(["--backend", "claude-code", "--claude-code-effort", "minimal"])


def test_refuses_on_another_backend_rather_than_ignoring():
    with pytest.raises(ValueError) as exc:
        resolve_cli_claude_effort(
            _args(["--backend", "dgx", "--claude-code-effort", "high"])
        )
    assert "claude-code" in str(exc.value)
    assert "dgx" in str(exc.value)


@pytest.mark.parametrize("raw", ["ultra", "minimal", "HIGH"])
def test_rejects_bad_environment_value(monkeypatch, raw):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", raw)
    with pytest.raises(ValueError) as exc:
        resolve_cli_claude_effort(_args(["--backend", "claude-code"]))
    assert "CG_CLAUDE_CODE_EFFORT" in str(exc.value)


@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_conflict_refused_before_any_child_spawns(fake, level):
    """FR-009. Thinking is off by default here, and the provider refuses the
    top two levels without it. Refuse — do not enable thinking, do not quietly
    lower the level, do not spawn and let the provider reject it."""
    with pytest.raises(ValueError) as exc:
        _run(claude_code_effort=level, claude_code_effort_source="explicit")
    message = str(exc.value)
    assert level in message
    assert "CG_CLAUDE_CODE_THINKING" in message      # the only reachable remedy
    assert "thinking" in message.lower()
    assert fake.spawned == 0                          # nothing ran


def test_conflict_message_offers_both_remedies(fake):
    with pytest.raises(ValueError) as exc:
        _run(claude_code_effort="max", claude_code_effort_source="explicit")
    message = str(exc.value).lower()
    assert "lower" in message or "high" in message   # remedy 1: lower the effort
    assert "cg_claude_code_thinking=1" in message    # remedy 2: enable thinking


@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_conflict_does_not_arise_once_thinking_is_on(fake, monkeypatch, level):
    monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", "1")
    _run(claude_code_effort=level, claude_code_effort_source="explicit")
    assert fake.invocations[0].effort() == level


# =========================================================================
# T013 — FR-009a: no conflict on always-thinking families
# =========================================================================

@pytest.mark.parametrize("level", ["xhigh", "max"])
def test_top_levels_accepted_on_always_thinking_model(fake, level):
    _run(model=ALWAYS_THINKING_MODEL,
         claude_code_effort=level, claude_code_effort_source="explicit")
    assert fake.invocations[0].effort() == level


def test_always_thinking_model_is_never_clamped(fake):
    """Omission on fable sends no --effort at all: the operator's own
    settings.json governs, and clamping would downgrade a level they chose to
    dodge an error that cannot occur."""
    _run(model=ALWAYS_THINKING_MODEL)
    assert fake.invocations[0].has_effort_flag() is False


# =========================================================================
# T032/T033 — the four sources, and the honesty rule
# =========================================================================

def test_explicit_replaces_the_clamp(fake):
    _run(claude_code_effort="low", claude_code_effort_source="explicit")
    assert fake.invocations[0].effort() == "low"


def test_omission_still_clamps_exactly_as_before(fake):
    """FR-005/SC-005. The clamp is not incidental: with thinking off the
    provider refuses the top two levels, and this operator's settings.json
    pins xhigh — so 'omission means send nothing' would fail every default
    run."""
    _run()
    assert fake.invocations[0].effort() == be.CLAUDE_CODE_NO_THINKING_EFFORT == "high"


def test_omission_with_thinking_on_sends_no_override(fake, monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_THINKING", "1")
    _run()
    assert fake.invocations[0].has_effort_flag() is False


@pytest.mark.parametrize(
    "kwargs,thinking,model,expected_source,expected_effort",
    [
        (dict(claude_code_effort="max", claude_code_effort_source="explicit"),
         True, CLAMP_MODEL, "explicit", "max"),
        (dict(claude_code_effort="low", claude_code_effort_source="environment"),
         False, CLAMP_MODEL, "environment", "low"),
        ({}, False, CLAMP_MODEL, "clamp", "high"),
        ({}, True, CLAMP_MODEL, "inherited", None),
        ({}, False, ALWAYS_THINKING_MODEL, "inherited", None),
    ],
)
def test_all_four_sources_classify(kwargs, thinking, model, expected_source, expected_effort):
    identity = be.claude_code_run_identity(
        model=model, thinking_on=thinking,
        effort=kwargs.get("claude_code_effort"),
        source=kwargs.get("claude_code_effort_source"),
    )
    assert identity.source == expected_source
    assert identity.effort_sent == expected_effort


def test_inherited_never_claims_a_value():
    """We do not read ~/.claude/settings.json, so we must not print a level
    from it. Asserting a value we did not send is the Optimistic Lie this
    reporting exists to end."""
    identity = be.claude_code_run_identity(
        model=CLAMP_MODEL, thinking_on=True, effort=None, source=None)
    assert identity.effort_sent is None
    assert identity.override_sent is False
    banner = identity.banner()
    assert "inherited" in banner
    for level in ("low", "medium", "xhigh", "max"):
        assert f"effort={level}" not in banner


def test_clamp_banner_states_its_reason():
    """FR-020. Reporting a bare 'high' would attribute the engine's
    compatibility decision to the human."""
    identity = be.claude_code_run_identity(
        model=CLAMP_MODEL, thinking_on=False, effort=None, source=None)
    assert identity.source == "clamp"
    banner = identity.banner().lower()
    assert "clamp" in banner
    assert "thinking" in banner
    assert "settings.json" in banner


def test_banner_always_shows_thinking_state():
    for thinking in (True, False):
        identity = be.claude_code_run_identity(
            model=CLAMP_MODEL, thinking_on=thinking, effort="high", source="explicit")
        assert f"thinking={'on' if thinking else 'off'}" in identity.banner()


def test_always_thinking_model_reports_thinking_on_always():
    """We did not request thinking, but it cannot be disabled here — which is
    why `max` is legal and the clamp is skipped. A bare "off" beside
    "effort=max" would read as a refusal that should have fired and didn't."""
    identity = be.claude_code_run_identity(
        model=ALWAYS_THINKING_MODEL, thinking_on=False,
        effort="max", source="explicit")
    assert "thinking=on (always)" in identity.banner()
    assert identity.as_dict()["thinking"] is True


# =========================================================================
# T034 — one banner per run, not one per call
# =========================================================================

def test_one_banner_per_client_not_per_call(fake, capsys):
    client = make_client(backend="claude-code")
    for _ in range(3):
        client.messages.create(
            model=CLAMP_MODEL, max_tokens=512, system="s",
            messages=[{"role": "user", "content": "hi"}],
        )
    assert fake.spawned == 3
    assert capsys.readouterr().err.count("claude-code run:") == 1


# =========================================================================
# T060 — the isolation guarantees this feature must not weaken
# =========================================================================

def test_isolation_guarantees_survive_an_explicit_effort(fake):
    _run(claude_code_effort="low", claude_code_effort_source="explicit")
    inv = fake.invocations[0]
    assert inv.env["ANTHROPIC_API_KEY_present"] is False   # billing stays on the subscription
    assert "--disallowed-tools" in inv.argv and "*" in inv.argv
    assert "--strict-mcp-config" in inv.argv
    assert "--output-format" in inv.argv and "stream-json" in inv.argv
    assert inv.env["MAX_THINKING_TOKENS"] == "0"
    assert inv.argv.count("--effort") == 1                 # never doubled
