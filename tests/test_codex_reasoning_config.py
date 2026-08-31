"""Server persistence and command-builder contracts for Codex effort."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from campaignlib.selection import ModelSelection
from server.ensemble_config_shared import EnsembleBackend
from server.platform_config_service import (
    PlatformConfigService,
    ResolvedSelection,
    resolve_selection,
    selection_cli_args,
)
from server.platform_config_shared import PlatformRuntime
from server.routers.config_routes import get_models
from server.session_editor_config_shared import BackendProfile


def _request(runtime: PlatformRuntime):
    platform = SimpleNamespace(runtime=runtime)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(platform=platform))
    )


def _resolved(**overrides):
    values = {
        "model": "gpt-5.6-sol",
        "backend": "codex-cli",
        "model_origin": "service",
        "backend_origin": "service",
    }
    values.update(overrides)
    return ResolvedSelection(**values)


def test_platform_runtime_round_trips_optional_codex_effort():
    runtime = PlatformRuntime(default_codex_reasoning_effort="max")
    payload = runtime.model_dump(mode="json")
    assert payload["default_codex_reasoning_effort"] == "max"
    assert PlatformRuntime.model_validate(payload) == runtime
    assert PlatformRuntime().default_codex_reasoning_effort is None


@pytest.mark.parametrize(
    ("request_effort", "service_effort", "platform_effort", "expected", "origin"),
    [
        ("max", "high", "medium", "max", "request"),
        (None, "high", "medium", "high", "service"),
        (None, None, "medium", "medium", "platform"),
    ],
)
def test_server_effort_precedence_and_cli_formatting(
    request_effort, service_effort, platform_effort, expected, origin
):
    runtime = PlatformRuntime(
        default_backend="codex-cli",
        default_model="gpt-5.6-sol",
        default_codex_reasoning_effort=platform_effort,
    )
    service = ModelSelection(
        backend="codex-cli",
        model="gpt-5.6-sol",
        codex_reasoning_effort=service_effort,
    )
    resolved = resolve_selection(
        _request(runtime),
        request_codex_reasoning_effort=request_effort,
        service=service,
    )

    assert resolved.codex_reasoning_effort == expected
    assert resolved.codex_reasoning_effort_origin == origin
    assert resolved.codex_reasoning_override is True
    args = selection_cli_args(resolved)
    assert args[args.index("--codex-reasoning-effort") + 1] == expected


def test_environment_preview_is_not_converted_to_explicit_flag(monkeypatch):
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "high")
    runtime = PlatformRuntime(
        default_backend="codex-cli", default_model="gpt-5.6-sol"
    )
    resolved = resolve_selection(_request(runtime))

    assert resolved.codex_reasoning_effort == "high"
    assert resolved.codex_reasoning_effort_origin == "environment"
    assert resolved.codex_reasoning_override is False
    assert "--codex-reasoning-effort" not in selection_cli_args(resolved)


def test_non_codex_runtime_keeps_memory_dormant(monkeypatch):
    monkeypatch.setenv("CG_CODEX_REASONING_EFFORT", "high")
    runtime = PlatformRuntime(
        default_backend="anthropic",
        default_codex_reasoning_effort="max",
    )
    resolved = resolve_selection(_request(runtime))
    assert resolved.codex_reasoning_effort is None
    assert resolved.codex_reasoning_effort_origin == "omitted"
    assert "--codex-reasoning-effort" not in selection_cli_args(resolved)


def test_effort_only_selection_subclasses_are_not_empty():
    assert not ModelSelection(codex_reasoning_effort="max").is_empty()
    assert not BackendProfile(
        name="codex-cli", codex_reasoning_effort="max"
    ).is_empty()
    assert not EnsembleBackend(codex_reasoning_effort="max").is_empty()


def test_formatter_adaptation_retains_validated_effort():
    resolved = _resolved(
        codex_reasoning_effort="max",
        codex_reasoning_effort_origin="service",
        codex_reasoning_override=True,
    )
    adapted = replace(resolved, backend="anthropic")
    args = selection_cli_args(adapted)
    assert args[args.index("--codex-reasoning-effort") + 1] == "max"


def test_models_endpoint_publishes_canonical_values():
    response = get_models(_request(PlatformRuntime()))
    assert response["codex_reasoning_efforts"] == [
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]

