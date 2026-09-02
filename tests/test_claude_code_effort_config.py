"""Config-tier tests for the claude-code effort level (feature 021).

The headline test here is the ``is_empty()`` trap. A profile whose only
content is an effort selection *has something to say*; if any of the three
``is_empty()`` implementations does not know the field, that profile reads as
"no override at all" and the save paths that gate on emptiness drop it — the
operator's choice vanishes on reload with no error. That is the same failure
``ModelSelection``'s ``batch`` field documents, and it is the most likely way
this feature fails quietly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from campaignlib.selection import (
    CLAUDE_CODE_EFFORTS,
    CLAUDE_CODE_THINKING_ONLY_EFFORTS,
    ModelSelection,
)
from server.ensemble_config_shared import (
    EnsembleBackend,
    EnsembleConfig,
    load_ensemble_config,
    save_ensemble_config,
)
from server.session_editor_config_shared import (
    BackendProfile,
    SessionEditorConfig,
    load_session_editor_config,
    save_session_editor_config,
)


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

def test_vocabulary_is_five_values_without_minimal():
    """`claude --effort` accepts five levels. `minimal` is Codex-only; putting
    it here would list a value in --help that fails at the call."""
    assert CLAUDE_CODE_EFFORTS == ("low", "medium", "high", "xhigh", "max")
    assert "minimal" not in CLAUDE_CODE_EFFORTS


def test_thinking_only_efforts_are_the_top_two():
    assert CLAUDE_CODE_THINKING_ONLY_EFFORTS == ("xhigh", "max")
    for level in CLAUDE_CODE_THINKING_ONLY_EFFORTS:
        assert level in CLAUDE_CODE_EFFORTS


# --------------------------------------------------------------------------
# T010 — the is_empty() trap, on all three shapes
# --------------------------------------------------------------------------

def test_model_selection_effort_only_is_not_empty():
    assert ModelSelection().is_empty()
    assert not ModelSelection(claude_code_effort="high").is_empty()


def test_backend_profile_effort_only_is_not_empty():
    assert BackendProfile().is_empty()
    assert not BackendProfile(claude_code_effort="xhigh").is_empty()


def test_ensemble_backend_effort_only_is_not_empty():
    assert EnsembleBackend().is_empty()
    assert not EnsembleBackend(claude_code_effort="low").is_empty()


def test_effort_survives_session_doc_round_trip(tmp_path: Path):
    """The trap in its real clothing: write a profile carrying only an effort,
    read it back, and confirm the level is still there."""
    path = tmp_path / "session_doc.yaml"
    cfg = SessionEditorConfig()
    cfg.backends.claude_code.claude_code_effort = "xhigh"
    save_session_editor_config(path, cfg)

    assert "claude_code_effort: xhigh" in path.read_text(encoding="utf-8")
    assert load_session_editor_config(path).backends.claude_code.claude_code_effort == "xhigh"


def test_effort_survives_ensemble_round_trip(tmp_path: Path):
    path = tmp_path / "ensemble.yaml"
    cfg = EnsembleConfig()
    cfg.extract.claude_code_effort = "medium"
    cfg.synthesize.claude_code_effort = "high"
    save_ensemble_config(path, cfg)
    back = load_ensemble_config(path)
    # The two stages carry independent selections — a per-stage override must
    # not be flattened into one campaign-wide value.
    assert back.extract.claude_code_effort == "medium"
    assert back.synthesize.claude_code_effort == "high"


# --------------------------------------------------------------------------
# T042 — isolation from the Codex selection
# --------------------------------------------------------------------------

def test_setting_claude_effort_does_not_touch_codex_effort():
    sel = ModelSelection(codex_reasoning_effort="minimal")
    sel = sel.model_copy(update={"claude_code_effort": "high"})
    assert sel.codex_reasoning_effort == "minimal"
    assert sel.claude_code_effort == "high"


def test_both_efforts_persist_simultaneously(tmp_path: Path):
    """Each backend's profile is keyed separately; a Claude Code selection and
    a Codex selection coexist and neither clobbers the other."""
    path = tmp_path / "session_doc.yaml"
    cfg = SessionEditorConfig()
    cfg.backends.claude_code.claude_code_effort = "high"
    cfg.backends.codex_cli.codex_reasoning_effort = "minimal"
    save_session_editor_config(path, cfg)

    back = load_session_editor_config(path)
    assert back.backends.claude_code.claude_code_effort == "high"
    assert back.backends.codex_cli.codex_reasoning_effort == "minimal"
    # ...and neither leaked into the other's profile
    assert back.backends.claude_code.codex_reasoning_effort is None
    assert back.backends.codex_cli.claude_code_effort is None


def test_rejects_a_value_outside_the_vocabulary():
    with pytest.raises(Exception):
        ModelSelection(claude_code_effort="minimal")
    with pytest.raises(Exception):
        ModelSelection(claude_code_effort="ultra")


# --------------------------------------------------------------------------
# T058 — omission rewrites nothing
# --------------------------------------------------------------------------

def test_loading_a_config_without_the_field_leaves_the_file_untouched(tmp_path: Path):
    path = tmp_path / "session_doc.yaml"
    path.write_text("backends:\n  active: claude-code\n", encoding="utf-8")
    before = path.read_bytes()
    cfg = load_session_editor_config(path)
    assert cfg.backends.claude_code.claude_code_effort is None
    assert path.read_bytes() == before


# --------------------------------------------------------------------------
# T041/T043 — server tier precedence, CLI formatting, and refusals
# --------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from server.platform_config_service import (  # noqa: E402
    resolve_selection,
    selection_cli_args,
)
from server.platform_config_shared import PlatformRuntime  # noqa: E402
from server.routers.config_routes import get_models  # noqa: E402


def _request(runtime: PlatformRuntime):
    platform = SimpleNamespace(runtime=runtime)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(platform=platform)))


def _claude_runtime(**kw):
    return PlatformRuntime(
        default_backend="claude-code", default_model="claude-opus-5", **kw
    )


def test_platform_runtime_round_trips_the_optional_effort():
    runtime = PlatformRuntime(default_claude_code_effort="xhigh")
    payload = runtime.model_dump(mode="json")
    assert payload["default_claude_code_effort"] == "xhigh"
    assert PlatformRuntime.model_validate(payload) == runtime
    assert PlatformRuntime().default_claude_code_effort is None


@pytest.mark.parametrize(
    ("request_effort", "service_effort", "platform_effort", "expected", "origin"),
    [
        ("max", "high", "medium", "max", "request"),
        (None, "high", "medium", "high", "service"),
        (None, None, "medium", "medium", "platform"),
    ],
)
def test_tier_precedence_and_cli_formatting(
    request_effort, service_effort, platform_effort, expected, origin
):
    resolved = resolve_selection(
        _request(_claude_runtime(default_claude_code_effort=platform_effort)),
        request_claude_code_effort=request_effort,
        service=ModelSelection(
            backend="claude-code", model="claude-opus-5",
            claude_code_effort=service_effort,
        ),
    )
    assert resolved.claude_code_effort == expected
    assert resolved.claude_code_effort_origin == origin
    assert resolved.claude_code_effort_override is True
    args = selection_cli_args(resolved)
    assert args[args.index("--claude-code-effort") + 1] == expected


def test_environment_is_the_last_tier(monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", "low")
    resolved = resolve_selection(_request(_claude_runtime()))
    assert resolved.claude_code_effort == "low"
    assert resolved.claude_code_effort_origin == "environment"
    # Environment-derived is NOT an override the CLI re-emits: the child would
    # read the same variable itself, and emitting it would make an ambient
    # value indistinguishable from an operator's explicit pick.
    assert resolved.claude_code_effort_override is False
    assert "--claude-code-effort" not in selection_cli_args(resolved)


def test_omission_emits_no_flag(monkeypatch):
    monkeypatch.delenv("CG_CLAUDE_CODE_EFFORT", raising=False)
    resolved = resolve_selection(_request(_claude_runtime()))
    assert resolved.claude_code_effort is None
    assert resolved.claude_code_effort_origin == "omitted"
    assert "--claude-code-effort" not in selection_cli_args(resolved)


def test_effort_on_another_backend_is_refused_not_ignored():
    resolved = resolve_selection(
        _request(PlatformRuntime(default_backend="dgx", default_model="Qwen-X")),
        request_claude_code_effort="high",
        raise_on_incompatible=False,
    )
    assert resolved.compatible is False
    assert "claude-code" in resolved.refusal
    assert "dgx" in resolved.refusal


def test_bad_environment_value_is_refused(monkeypatch):
    monkeypatch.setenv("CG_CLAUDE_CODE_EFFORT", "minimal")
    resolved = resolve_selection(
        _request(_claude_runtime()), raise_on_incompatible=False)
    assert resolved.compatible is False
    assert "CG_CLAUDE_CODE_EFFORT" in resolved.refusal


def test_a_dormant_codex_selection_does_not_leak_into_a_claude_run(monkeypatch):
    """Both may be stored at once; only the active backend's is resolved."""
    monkeypatch.delenv("CG_CLAUDE_CODE_EFFORT", raising=False)
    monkeypatch.delenv("CG_CODEX_REASONING_EFFORT", raising=False)
    resolved = resolve_selection(
        _request(_claude_runtime()),
        service=ModelSelection(
            backend="claude-code", model="claude-opus-5",
            claude_code_effort="high", codex_reasoning_effort="minimal",
        ),
    )
    assert resolved.claude_code_effort == "high"
    assert resolved.codex_reasoning_effort is None
    args = selection_cli_args(resolved)
    assert "--codex-reasoning-effort" not in args
    assert args[args.index("--claude-code-effort") + 1] == "high"


def test_models_endpoint_publishes_the_vocabulary():
    body = get_models(_request(PlatformRuntime()))
    assert body["claude_code_efforts"] == list(CLAUDE_CODE_EFFORTS)
    assert "minimal" not in body["claude_code_efforts"]
    # ...and the Codex list is untouched beside it
    assert "minimal" in body["codex_reasoning_efforts"]


# --------------------------------------------------------------------------
# Thinking selection, server tiers (issue #365)
# --------------------------------------------------------------------------

def test_platform_runtime_round_trips_the_optional_thinking_choice():
    for value in (True, False):
        runtime = PlatformRuntime(default_claude_code_thinking=value)
        payload = runtime.model_dump(mode="json")
        assert payload["default_claude_code_thinking"] is value
        assert PlatformRuntime.model_validate(payload) == runtime
    assert PlatformRuntime().default_claude_code_thinking is None


@pytest.mark.parametrize(
    ("request_t", "service_t", "platform_t", "expected", "origin"),
    [
        (True, False, False, True, "request"),
        (None, True, False, True, "service"),
        (None, None, True, True, "platform"),
        (None, False, True, False, "service"),   # sticky off beats platform on
        (None, None, None, None, "omitted"),
    ],
)
def test_thinking_tier_precedence(request_t, service_t, platform_t, expected, origin):
    resolved = resolve_selection(
        _request(_claude_runtime(default_claude_code_thinking=platform_t)),
        request_claude_code_thinking=request_t,
        service=ModelSelection(
            backend="claude-code", model="claude-opus-5",
            claude_code_thinking=service_t,
        ),
    )
    assert resolved.claude_code_thinking is expected
    assert resolved.claude_code_thinking_origin == origin


@pytest.mark.parametrize(
    ("value", "flag"),
    [(True, "--claude-code-thinking"), (False, "--no-claude-code-thinking")],
)
def test_both_spellings_reach_the_command_line(value, flag):
    """A resolved False must be forwarded explicitly. Emitting nothing would
    let the child read CG_CLAUDE_CODE_THINKING from the inherited environment
    and turn thinking back on, overriding the operator's stored off."""
    resolved = resolve_selection(
        _request(_claude_runtime(default_claude_code_thinking=value)))
    args = selection_cli_args(resolved)
    assert flag in args
    other = "--claude-code-thinking" if not value else "--no-claude-code-thinking"
    assert other not in args


def test_omission_emits_no_thinking_flag():
    resolved = resolve_selection(_request(_claude_runtime()))
    assert resolved.claude_code_thinking is None
    args = selection_cli_args(resolved)
    assert "--claude-code-thinking" not in args
    assert "--no-claude-code-thinking" not in args


def test_thinking_on_another_backend_is_refused():
    resolved = resolve_selection(
        _request(PlatformRuntime(default_backend="dgx", default_model="Qwen-X")),
        request_claude_code_thinking=True,
        raise_on_incompatible=False,
    )
    assert resolved.compatible is False
    assert "claude-code" in resolved.refusal


def test_thinking_only_selection_is_not_empty():
    """The is_empty trap again, for the field whose False is meaningful."""
    assert not ModelSelection(claude_code_thinking=False).is_empty()
    assert not BackendProfile(claude_code_thinking=False).is_empty()
    assert not EnsembleBackend(claude_code_thinking=False).is_empty()


def test_thinking_survives_a_session_doc_round_trip(tmp_path: Path):
    path = tmp_path / "session_doc.yaml"
    cfg = SessionEditorConfig()
    cfg.backends.claude_code.claude_code_thinking = False
    save_session_editor_config(path, cfg)
    back = load_session_editor_config(path)
    # False, not None — the distinction is the whole point of the tri-state.
    assert back.backends.claude_code.claude_code_thinking is False
