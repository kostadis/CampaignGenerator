"""`max_tokens` means different things per backend; the run must say which (#414).

One argument, three behaviours:

    codex-cli           discarded — `codex exec` exposes no output-token flag
    claude-code         forwarded as CLAUDE_CODE_MAX_OUTPUT_TOKENS
    dgx / openrouter    passed to the OpenAI-compatible server
    anthropic           the API's own ceiling

Each is correct on its own. The defect was that a caller could not tell them
apart and nothing downstream recorded it: replaying one experiment across three
renderers with `max_tokens=32000` held "constant", the number was ignored on
one arm and enforced on two, so a generation-length difference between arms was
partly the harness — discoverable only by reading three adapters.

This is the second bug of that shape. #108 was the same failure on the
claude-code path and was fixed by making that path honour the ceiling; the
general case — *the argument's meaning is backend-dependent and unrecorded* —
stayed open, and codex-cli reintroduced it. So these tests are written against
the general case: the two run identities must answer the same question in the
same words, whatever each one answers.

Only the two subscription backends have run identities to carry the record.
The SDK-shaped backends (anthropic, dgx, openrouter) enforce the ceiling
directly and have no identity object; giving them one is a larger change than
#414 asks for, and their behaviour is not in doubt.
"""
from __future__ import annotations

import pytest

from campaignlib.api import backends as be
from campaignlib.api import client as client_mod
from campaignlib.api.codex_cli import CodexRunIdentity, _CodexCliClient
from campaignlib.selection import MAX_TOKENS_EFFECTS
from tests.helpers.fake_claude_cli import FakeClaudeCli
from tests.helpers.fake_codex_cli import FakeCodexCli


CEILING = 32000
MODEL = "claude-fable-5"          # thinking always on -> no clamp in the way
CODEX_MODEL = "gpt-5.6-sol"

#: The three keys both identities must carry, in both dialects.
RECORD_KEYS = {"max_tokens_requested", "max_tokens_effect", "max_tokens_channel"}


@pytest.fixture
def fake_claude(monkeypatch):
    with FakeClaudeCli() as f:
        # CG_CLAUDE_CLI is read once at import, so patch the attribute.
        monkeypatch.setattr(be, "CLAUDE_CODE_CLI", f.path)
        yield f


def _codex(monkeypatch, tmp_path, *, responses=None):
    fake = FakeCodexCli(
        tmp_path, responses=responses or [FakeCodexCli.direct("ok")])
    fake.install(monkeypatch)
    return fake


# =========================================================================
# The cross-backend contract — the point of the issue
# =========================================================================

def test_both_identities_answer_the_same_question_in_the_same_words():
    """A comparison across backends is only possible if the records line up.

    `ClaudeCodeRunIdentity.as_dict` already promises to mirror the Codex
    contract "so one consumer can handle both without a second code path".
    The ceiling has to join that promise, not sit beside it in a private shape.
    """
    claude = be.claude_code_run_identity(
        model=MODEL, thinking_on=True, effort="medium",
        source="explicit", max_tokens=CEILING).as_dict()
    codex = CodexRunIdentity(
        backend="codex-cli", model=CODEX_MODEL, model_source="explicit",
        codex_reasoning_effort="medium", codex_reasoning_effort_source="explicit",
        codex_reasoning_override=True,
        max_tokens_requested=CEILING, max_tokens_effect="ignored",
        max_tokens_channel=None).as_dict()

    assert RECORD_KEYS <= set(claude)
    assert RECORD_KEYS <= set(codex)
    # Same question, different answers — which is exactly what has to be
    # visible for a cross-backend comparison to be trustworthy.
    assert claude["max_tokens_requested"] == codex["max_tokens_requested"] == CEILING
    assert claude["max_tokens_effect"] == "enforced"
    assert codex["max_tokens_effect"] == "ignored"


@pytest.mark.parametrize("effect", MAX_TOKENS_EFFECTS)
def test_the_effect_vocabulary_is_shared_not_per_adapter(effect):
    """Both dataclasses accept the same three values from one vocabulary, so a
    consumer can switch on it without knowing which backend wrote the record."""
    assert be.ClaudeCodeRunIdentity(
        effective_model=MODEL, effort_sent=None, source="inherited",
        override_sent=False, thinking_on=True,
        max_tokens_effect=effect).max_tokens_effect == effect
    assert CodexRunIdentity(
        backend="codex-cli", model=CODEX_MODEL, model_source="explicit",
        codex_reasoning_effort="medium", codex_reasoning_effort_source="explicit",
        codex_reasoning_override=True,
        max_tokens_effect=effect).max_tokens_effect == effect


# =========================================================================
# claude-code — enforced, and the record names the channel it went through
# =========================================================================

def test_claude_code_records_enforced_and_actually_sets_the_variable(fake_claude):
    """Record and behaviour asserted together: a record that says "enforced"
    while the child got no ceiling would be the same class of bug again."""
    client = client_mod.make_client(backend="claude-code")
    client.messages.create(
        model=MODEL, max_tokens=CEILING, system="s",
        messages=[{"role": "user", "content": "hi"}])

    recorded = client.last_run_identity.as_dict()
    assert recorded["max_tokens_requested"] == CEILING
    assert recorded["max_tokens_effect"] == "enforced"
    assert recorded["max_tokens_channel"] == be.CLAUDE_CODE_MAX_TOKENS_CHANNEL

    sent = fake_claude.invocations[0].env[be.CLAUDE_CODE_MAX_TOKENS_CHANNEL]
    assert sent == str(CEILING), "the record claims a ceiling the child never got"


def test_the_recorded_channel_is_the_variable_that_is_actually_set(fake_claude):
    """One constant for both, so the record cannot drift from the mechanism.

    Reads the env var by the name the record gives, rather than by a literal
    repeated in this file — a hardcoded literal here would keep passing if the
    two ever diverged, which is the failure it is meant to catch.
    """
    client = client_mod.make_client(backend="claude-code")
    client.messages.create(
        model=MODEL, max_tokens=CEILING, system="s",
        messages=[{"role": "user", "content": "hi"}])

    channel = client.last_run_identity.max_tokens_channel
    assert fake_claude.invocations[0].env.get(channel) == str(CEILING)


@pytest.mark.parametrize("ceiling", (None, 0))
def test_claude_code_reports_unset_when_no_ceiling_was_asked_for(ceiling):
    """"unset" is a third state, not a synonym for "ignored". `_claude_code_generate`
    sets the variable under `if max_tokens:`, so 0 and None both mean the child
    was given nothing — and neither is a backend refusing a request."""
    identity = be.claude_code_run_identity(
        model=MODEL, thinking_on=True, effort="medium",
        source="explicit", max_tokens=ceiling)
    assert identity.max_tokens_effect == "unset"
    assert identity.max_tokens_requested is None
    assert identity.max_tokens_channel is None


# =========================================================================
# codex-cli — still discarded, no longer silently
# =========================================================================

def test_codex_records_ignored_on_the_direct_surface(monkeypatch, tmp_path):
    fake = _codex(monkeypatch, tmp_path)
    client = _CodexCliClient(reasoning_effort="medium",
                             reasoning_effort_source="explicit")
    client.messages.create(
        model=CODEX_MODEL, max_tokens=CEILING, system="s",
        messages=[{"role": "user", "content": "hi"}])

    recorded = client.last_run_identity.as_dict()
    assert recorded["max_tokens_requested"] == CEILING
    assert recorded["max_tokens_effect"] == "ignored"
    assert recorded["max_tokens_channel"] is None
    assert fake.call_count == 1


def test_codex_records_ignored_on_the_streaming_surface(monkeypatch, tmp_path):
    _codex(monkeypatch, tmp_path, responses=[FakeCodexCli.direct("stream")])
    client = _CodexCliClient(reasoning_effort="medium",
                             reasoning_effort_source="explicit")
    with client.messages.stream(
        model=CODEX_MODEL, max_tokens=CEILING, system="s",
        messages=[{"role": "user", "content": "hi"}],
    ) as stream:
        list(stream.text_stream)

    assert client.last_run_identity.max_tokens_effect == "ignored"
    assert client.last_run_identity.max_tokens_requested == CEILING


def test_codex_records_ignored_on_the_brokered_surface(monkeypatch, tmp_path):
    _codex(monkeypatch, tmp_path, responses=[FakeCodexCli.structured("brokered")])
    client = _CodexCliClient(reasoning_effort="medium",
                             reasoning_effort_source="explicit")
    client_mod.call_api_with_tools(
        client, system="broker", messages=[{"role": "user", "content": "b"}],
        tools=[], model=CODEX_MODEL, max_tokens=CEILING)

    assert client.last_run_identity.max_tokens_effect == "ignored"
    assert client.last_run_identity.max_tokens_requested == CEILING


def test_recording_the_ceiling_does_not_start_sending_it(monkeypatch, tmp_path):
    """The discard is correct and stays. #414 asks for a record, not a
    behaviour change — `codex exec` has no flag to forward this to, so a fix
    that started passing something would be inventing an interface."""
    fake = _codex(monkeypatch, tmp_path)
    client = _CodexCliClient(reasoning_effort="medium",
                             reasoning_effort_source="explicit")
    client.messages.create(
        model=CODEX_MODEL, max_tokens=CEILING, system="s",
        messages=[{"role": "user", "content": "hi"}])

    argv = " ".join(fake.calls[0].command)
    assert str(CEILING) not in argv, argv
    for flag in ("--max-tokens", "--max-output-tokens", "max_output_tokens"):
        assert flag not in argv, argv


def test_codex_reports_unset_rather_than_ignored_when_none_was_asked_for():
    """Nothing was discarded, so nothing should be reported as discarded."""
    identity = CodexRunIdentity(
        backend="codex-cli", model=CODEX_MODEL, model_source="explicit",
        codex_reasoning_effort="medium", codex_reasoning_effort_source="explicit",
        codex_reasoning_override=True)
    assert identity.max_tokens_effect == "unset"
    assert "IGNORED" not in identity.status_line()


def test_the_status_line_says_so_when_a_ceiling_is_being_ignored():
    """The forensic record answers "what happened"; this answers it while the
    operator is still watching. An operator turning `--narrate-tokens` on this
    backend is moving a knob that does nothing."""
    identity = CodexRunIdentity(
        backend="codex-cli", model=CODEX_MODEL, model_source="explicit",
        codex_reasoning_effort="medium", codex_reasoning_effort_source="explicit",
        codex_reasoning_override=True,
        max_tokens_requested=CEILING, max_tokens_effect="ignored")
    line = identity.status_line()
    assert str(CEILING) in line
    assert "IGNORED" in line
    assert "no output-token limit" in line
