"""Regression tests for ``docs/config/platform-isolation.md`` Phase 5a.

Twelve router request-body ``model`` fields independently hardcoded
``model: str = "claude-sonnet-4-6"`` as their FastAPI default — five in
``grounding.py``, three in ``prep.py``, two in ``experimental.py``, one in
``session_workflow.py``, one in ``connections.py``'s ``ExtractRequest``
pydantic body. Because those were request-model *defaults*, a caller that
omitted ``model`` silently got the literal instead of the platform's
``runtime.default_model`` — the sidebar model picker was bypassed on every
one of those paths regardless of what the GM had selected.

Phase 5a's fix: every one of the twelve fields now defaults to ``None``,
and each handler resolves the value through
``server.platform_config_service.resolve_default_model`` (explicit request
``model`` > ``runtime.default_model`` > the ``campaignlib.constants.
DEFAULT_MODEL`` literal, used only when no live platform exists at all).

This file is the assertion the phase exists to make verifiable: a request
that OMITS ``model`` must reach the subprocess ``cmd``/API call with
``runtime.default_model``, not a hardcoded literal. Without a test like this
one, a regression that reintroduces a hardcoded default would pass
silently — ``"claude-sonnet-4-6"`` is still a legal model id, so nothing
would *look* wrong without explicitly checking the value's provenance. Every
assertion below therefore seeds the platform with a SENTINEL_MODEL that is
deliberately NOT the old literal, so a pass can't be a false positive.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from campaignlib.constants import DEFAULT_MODEL
from server.main import app
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME

client = TestClient(app)

# A current, legal model id (present in the refreshed server.config.MODELS)
# that was never the old hardcoded literal — see module docstring.
SENTINEL_MODEL = "claude-opus-5"


def _platform(tmp_path: Path) -> PlatformConfigService:
    """A real PlatformConfigService in tmp_path with runtime.default_model
    pinned to SENTINEL_MODEL, mirroring tests/test_platform_config_service.py
    and tests/test_grounding_backend.py's harness."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    platform = PlatformConfigService(tmp_path)
    platform.update_runtime({"default_model": SENTINEL_MODEL})
    return platform


def _capture_cmd(monkeypatch, module_path: str) -> dict:
    """Patch ``stream_subprocess`` in the given router module; the returned
    dict is populated with the captured ``cmd`` list once the route runs."""
    captured: dict = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(f"{module_path}.stream_subprocess", fake_stream_subprocess)
    return captured


def _flag_value(cmd: list[str], flag: str) -> str | None:
    """Return the argument following the LAST occurrence of ``flag``."""
    if flag not in cmd:
        return None
    idx = len(cmd) - 1 - cmd[::-1].index(flag)
    return cmd[idx + 1] if idx + 1 < len(cmd) else None


def _run(monkeypatch, tmp_path, module_path: str, path: str, params: dict) -> dict:
    platform = _platform(tmp_path)
    monkeypatch.setattr(app.state, "platform", platform, raising=False)
    captured = _capture_cmd(monkeypatch, module_path)
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text  # drain the SSE generator so the fake subprocess actually runs
    return captured


# ── grounding.py — 5 sites ───────────────────────────────────────────────

GROUNDING_ROUTES = [
    ("/api/grounding/run/campaign-state", {"input": "docs/x.md"}),
    ("/api/grounding/run/distill", {"input": "docs/x.md"}),
    ("/api/grounding/run/party", {"output": "docs/party.md"}),
    ("/api/grounding/run/planning", {"output": "docs/planning.md"}),
    ("/api/grounding/run/build-dossiers", {"summaries": "docs/s"}),
]


@pytest.mark.parametrize("path,params", GROUNDING_ROUTES)
def test_grounding_routes_omitted_model_uses_platform_default(monkeypatch, tmp_path, path, params):
    captured = _run(monkeypatch, tmp_path, "server.routers.grounding", path, params)
    assert _flag_value(captured["cmd"], "--model") == SENTINEL_MODEL


# ── prep.py — 3 sites ─────────────────────────────────────────────────────

PREP_ROUTES = [
    ("/api/prep/run/session-prep", {"beat": "The party enters the dungeon"}),
    ("/api/prep/run/npc-table", {}),
    ("/api/prep/run/query", {"input": "docs/summaries.md", "query": "who is Xalvosh"}),
]


@pytest.mark.parametrize("path,params", PREP_ROUTES)
def test_prep_routes_omitted_model_uses_platform_default(monkeypatch, tmp_path, path, params):
    captured = _run(monkeypatch, tmp_path, "server.routers.prep", path, params)
    assert _flag_value(captured["cmd"], "--model") == SENTINEL_MODEL


# ── experimental.py — 2 sites ────────────────────────────────────────────

EXPERIMENTAL_ROUTES = [
    ("/api/experimental/run/enhance-recap", {"recap": "docs/recap.md"}),
    ("/api/experimental/run/narrative", {}),
]


@pytest.mark.parametrize("path,params", EXPERIMENTAL_ROUTES)
def test_experimental_routes_omitted_model_uses_platform_default(monkeypatch, tmp_path, path, params):
    captured = _run(monkeypatch, tmp_path, "server.routers.experimental", path, params)
    assert _flag_value(captured["cmd"], "--model") == SENTINEL_MODEL


# ── setup.py — 2 sites ───────────────────────────────────────────────────
# These two are the same defect as the twelve above, but they defaulted to
# the imported ``DEFAULT_MODEL`` constant rather than a bareword
# ``"claude-sonnet-4-6"`` — so the grep that found the other twelve could
# not see them, and they were fixed only after a multi-form audit turned
# them up. They are covered here so the constant-shaped variant of the bug
# is guarded too, not just the literal-shaped one.

SETUP_ROUTES = [
    ("/api/setup/run/dnd-sheet", {"pdfs": ["sheet.pdf"], "output": "out.md"}),
    ("/api/setup/run/make-tracking", {"input": "docs/module.md"}),
]


@pytest.mark.parametrize("path,params", SETUP_ROUTES)
def test_setup_routes_omitted_model_uses_platform_default(monkeypatch, tmp_path, path, params):
    captured = _run(monkeypatch, tmp_path, "server.routers.setup", path, params)
    assert _flag_value(captured["cmd"], "--model") == SENTINEL_MODEL


# ── session_workflow.py — 1 site ─────────────────────────────────────────

def test_vtt_summary_omitted_model_uses_platform_default(monkeypatch, tmp_path):
    captured = _run(
        monkeypatch, tmp_path, "server.routers.session_workflow",
        "/api/workflow/run/vtt-summary", {"vtt_input": "session.vtt"},
    )
    assert _flag_value(captured["cmd"], "--model") == SENTINEL_MODEL


# ── connections.py — 1 site (ExtractRequest.model, a pydantic body field) ──

def test_connections_extract_omitted_model_uses_platform_default(monkeypatch, tmp_path):
    doc = tmp_path / "world_state.md"
    doc.write_text("# World\nXalvosh rules the deep.", encoding="utf-8")

    platform = _platform(tmp_path)
    monkeypatch.setattr(app.state, "platform", platform, raising=False)

    captured: dict = {}

    def fake_stream_api(client_obj, system, user, model, **kwargs):
        captured["model"] = model
        return '{"entities": [], "edges": []}'

    monkeypatch.setattr("server.routers.connections.client_from_args", lambda req: object())
    monkeypatch.setattr("server.routers.connections.stream_api", fake_stream_api)

    r = client.post("/api/connections/extract", json={"files": [str(doc)]})
    assert r.status_code == 200, r.text
    assert captured["model"] == SENTINEL_MODEL


# ── Precedence: an explicit request model still wins over the platform ─────

def test_explicit_model_overrides_platform_default(monkeypatch, tmp_path):
    captured = _run(
        monkeypatch, tmp_path, "server.routers.grounding",
        "/api/grounding/run/campaign-state",
        {"input": "docs/x.md", "model": "claude-haiku-4-5"},
    )
    assert _flag_value(captured["cmd"], "--model") == "claude-haiku-4-5"


# ── Final fallback: no live platform at all → the DEFAULT_MODEL literal,   ──
# ── not a crash — mirrors _backend_flags' "no config service" tolerance.  ──

def test_missing_platform_falls_back_to_default_model_literal(monkeypatch, tmp_path):
    monkeypatch.setattr(app.state, "platform", None, raising=False)
    captured = _capture_cmd(monkeypatch, "server.routers.grounding")
    r = client.get("/api/grounding/run/campaign-state", params={"input": "docs/x.md"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert _flag_value(captured["cmd"], "--model") == DEFAULT_MODEL
