"""The grounding routes (campaign_state / distill / party / planning /
build-dossiers) must forward the campaign's global backend choice to the
subprocess, exactly like scene_editor and ensemble do.

Regression guard for the bug where a "subscription" (claude-code) or
"openrouter" selection in the sidebar was silently dropped by
server/routers/grounding.py, so every grounding run billed the metered
Anthropic API. **That guarantee is unchanged.** What changed with feature 003
is who owns the value being forwarded.

Before 003 the sidebar's backend lived in ``session_doc.yaml``'s
``backends.active`` — the Session Doc Editor's own service config — and
``grounding.py::_backend_flags`` constructed a ``SessionEditorConfigService``
to read it. That cross-service read is what FR-005 removes: editing the
Session Doc Editor silently re-targeted every Grounding run, and because the
model came from the platform tier while the backend came from the editor's, a
single command could carry two ``--model`` flags from two owners (argparse
last-wins made it "work"; with no editor model stored, a claude-* id went to
a DGX endpoint and the adapter substituted its own default).

The app-wide backend now lives beside the app-wide model, in
``platform.yaml``'s ``runtime.default_backend``. The harness below therefore
seeds the **platform** rather than the editor, and every forwarding assertion
survives — same guarantee, one owner.

The dgx *endpoint* has no platform field and resolves from ``wiring.yaml``
(the platform's established source for external endpoints), so the wiring
monkeypatch targets ``server.platform_config_service.wiring_get``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from server.backend_forwarding import backend_cli_args
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.main import app

client = TestClient(app)


def _capture_cmd(monkeypatch):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        captured["env_extra"] = env_extra
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    return captured


def _set_selection(monkeypatch, tmp_path: Path, selection: dict | None):
    """Point app.state.platform at a real PlatformConfigService seeded with
    the given app-wide selection. Pass None to simulate no config service.

    ``selection`` takes ``backend`` and (optionally) ``model`` — the two
    ``runtime`` fields the sidebar now writes. Compare with the pre-003
    version of this helper, which seeded ``SessionEditorConfigService``
    instead; that indirection was the defect, not the setup.
    """
    if selection is None:
        monkeypatch.setattr(app.state, "platform", None, raising=False)
        return
    config_subdir = tmp_path / "config"
    config_subdir.mkdir(parents=True, exist_ok=True)
    (config_subdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    platform = PlatformConfigService(tmp_path)
    runtime_update = {"default_backend": selection.get("backend", "anthropic")}
    if selection.get("model"):
        runtime_update["default_model"] = selection["model"]
    platform.update_runtime(runtime_update)
    monkeypatch.setattr(app.state, "platform", platform, raising=False)


def _run(monkeypatch, tmp_path: Path, path: str, selection: dict | None, params: dict) -> dict:
    """Call a grounding route with a seeded platform + fake subprocess, and
    return the captured {"cmd", "env_extra"} (draining the SSE body so the
    fake subprocess actually runs)."""
    captured = _capture_cmd(monkeypatch)
    _set_selection(monkeypatch, tmp_path, selection)
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text  # drain the SSE generator so fake_stream_subprocess runs
    return captured


def _flag_value(cmd: list[str], flag: str) -> str | None:
    """Return the argument following the LAST occurrence of `flag` in cmd.

    Pre-003 this helper's comment explained that a backend override's own
    --model was "always the later of the two occurrences". There is no longer
    a second occurrence to disambiguate — guarantee C1 is exactly one --model
    per command, asserted directly by test_exactly_one_model_flag below. The
    last-occurrence search is kept only so the helper stays total.
    """
    if flag not in cmd:
        return None
    idx = len(cmd) - 1 - cmd[::-1].index(flag)
    return cmd[idx + 1] if idx + 1 < len(cmd) else None


ALL_ROUTES = [
    ("/api/grounding/run/campaign-state", {"input": "docs/x.md", "output": "docs/cs.md"}),
    ("/api/grounding/run/distill", {"input": "docs/x.md", "output": "docs/ws.md"}),
    ("/api/grounding/run/party", {"output": "docs/party.md"}),
    ("/api/grounding/run/planning", {"output": "docs/planning.md"}),
    ("/api/grounding/run/build-dossiers", {"summaries": "docs/s"}),
]

_WIRED_ENDPOINT = "http://box:8001"


def _wire_dgx_endpoint(monkeypatch, endpoint: str = _WIRED_ENDPOINT):
    monkeypatch.setattr(
        "server.platform_config_service.wiring_get",
        lambda key, default=None: {"dgx_endpoint": endpoint}.get(key, default),
    )


# ── claude-code (subscription) is forwarded as --backend on every route ─────

@pytest.mark.parametrize("path,params", ALL_ROUTES)
def test_all_routes_forward_subscription_flag(monkeypatch, tmp_path, path, params):
    captured = _run(monkeypatch, tmp_path, path, {"backend": "claude-code"}, params)
    assert _flag_value(captured["cmd"], "--backend") == "claude-code"
    # no more env-var channel — the router never populates env_extra now.
    assert captured["env_extra"] is None


# ── openrouter is forwarded as --backend + --model. This was the actual bug:
# the old env-only translator silently dropped "openrouter" entirely, so a
# GM's openrouter pick quietly ran against the metered Anthropic API. ───────

@pytest.mark.parametrize("path,params", [ALL_ROUTES[0], ALL_ROUTES[2]])
def test_routes_forward_openrouter_flag(monkeypatch, tmp_path, path, params):
    captured = _run(
        monkeypatch, tmp_path, path,
        {"backend": "openrouter", "model": "anthropic/claude-sonnet-4"},
        params,
    )
    assert _flag_value(captured["cmd"], "--backend") == "openrouter"
    assert _flag_value(captured["cmd"], "--model") == "anthropic/claude-sonnet-4"


# ── dgx is forwarded as --backend/--endpoint/--model ─────────────────────────

def test_campaign_state_forwards_dgx_flags(monkeypatch, tmp_path):
    """The dgx model comes from the platform's own pick; the endpoint comes
    from wiring, the platform's source for external endpoints.

    Pre-003 both came from the Session Doc Editor's dgx profile — the
    cross-service read this feature deletes.
    """
    _wire_dgx_endpoint(monkeypatch)
    captured = _run(
        monkeypatch, tmp_path, "/api/grounding/run/campaign-state",
        {"backend": "dgx", "model": "Qwen-X"},
        {"input": "docs/x.md"},
    )
    expected = backend_cli_args("dgx", model="Qwen-X", endpoint=_WIRED_ENDPOINT)
    assert captured["cmd"][-len(expected):] == expected
    assert _flag_value(captured["cmd"], "--endpoint") == _WIRED_ENDPOINT
    assert _flag_value(captured["cmd"], "--model") == "Qwen-X"


def test_dgx_endpoint_falls_back_to_wiring(monkeypatch, tmp_path):
    """No endpoint pinned anywhere → wiring supplies it, never a hardcoded
    literal (the old "Qwen/Qwen2.5-14B-Instruct-AWQ" default is long gone).

    The *model* deliberately does NOT fall back to wiring's ``dgx_model``:
    substituting a model the operator did not pick is what FR-011 forbids, so
    an incompatible pair is refused instead — see
    test_incompatible_platform_pair_is_refused.
    """
    _wire_dgx_endpoint(monkeypatch, "http://wired-box:9000")
    captured = _run(
        monkeypatch, tmp_path, "/api/grounding/run/campaign-state",
        {"backend": "dgx", "model": "Wired/Model-Name"},
        {"input": "docs/x.md"},
    )
    assert _flag_value(captured["cmd"], "--endpoint") == "http://wired-box:9000"
    assert "Qwen/Qwen2.5-14B-Instruct-AWQ" not in captured["cmd"]


# ── anthropic / no config service → no --backend flag (default API path) ────

def test_anthropic_backend_yields_no_flag(monkeypatch, tmp_path):
    captured = _run(
        monkeypatch, tmp_path, "/api/grounding/run/campaign-state",
        {"backend": "anthropic"},
        {"input": "docs/x.md"},
    )
    assert "--backend" not in captured["cmd"]


def test_no_config_service_yields_no_flag(monkeypatch, tmp_path):
    captured = _run(
        monkeypatch, tmp_path, "/api/grounding/run/campaign-state",
        None,
        {"input": "docs/x.md"},
    )
    assert "--backend" not in captured["cmd"]


# ── Feature 003 guarantees ──────────────────────────────────────────────────

@pytest.mark.parametrize("path,params", ALL_ROUTES)
def test_exactly_one_model_flag(monkeypatch, tmp_path, path, params):
    """Contract guarantee C1. The pre-003 defect: the router appended
    ``--model`` from the platform, then ``_backend_flags`` appended a second
    from session_doc.yaml. argparse last-wins hid it.
    """
    _wire_dgx_endpoint(monkeypatch)
    captured = _run(monkeypatch, tmp_path, path, {"backend": "dgx", "model": "Qwen-X"}, params)
    assert captured["cmd"].count("--model") == 1


def test_incompatible_platform_pair_is_refused(monkeypatch, tmp_path):
    """FR-009/FR-011: a claude-* model on a dgx backend is refused with 409,
    never silently swapped for something that would run.

    This is the platform-tier form of the stale-selection case, and it is
    reachable today: the sidebar's model list is Anthropic-only, so picking
    dgx without typing a dgx model leaves exactly this pair.
    """
    _capture_cmd(monkeypatch)
    _set_selection(monkeypatch, tmp_path, {"backend": "dgx", "model": "claude-sonnet-4-6"})
    r = client.get("/api/grounding/run/campaign-state", params={"input": "docs/x.md"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert detail["model"] == "claude-sonnet-4-6"
    assert detail["backend"] == "dgx"


def test_grounding_does_not_read_the_session_editor():
    """FR-005 / guarantee C4, asserted structurally rather than behaviourally.

    A behavioural test cannot catch a re-introduction cleanly — the two
    services agree whenever the operator set the same backend in both — so
    this checks the import that made the coupling possible.
    """
    import server.routers.grounding as g

    assert not hasattr(g, "SessionEditorConfigService"), (
        "grounding.py must not read the Session Doc Editor's config "
        "(FR-005: no service reads another service's selection)"
    )
    assert not hasattr(g, "_backend_flags"), (
        "_backend_flags was the cross-service read; it is replaced by "
        "resolve_selection"
    )
