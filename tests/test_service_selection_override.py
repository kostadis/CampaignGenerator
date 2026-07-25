"""Feature 003 US2 — a service can deliberately override, and only for itself.

Five services own a configuration document and may therefore hold an override:
Ensemble, Session Doc Editor, Grounding, Party, Planning. Five own none and
always inherit: Setup, Session Prep, NPC Table, Query, Connection Graph.

That split is the scope decision recorded in the spec's Clarifications, and it
is load-bearing rather than arbitrary — the five inheriting services were
deliberately stripped of configuration by D1
(``docs/config/ui-state-retirement.md``), so handing it back would reverse a
decision this feature has no business reversing. Hence
``test_no_new_config_file_is_created``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME

client = TestClient(app)

PLATFORM_MODEL = "claude-opus-5"


@pytest.fixture
def platform(monkeypatch, tmp_path):
    config_subdir = tmp_path / "config"
    config_subdir.mkdir(parents=True, exist_ok=True)
    (config_subdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    svc = PlatformConfigService(tmp_path)
    svc.update_runtime({"default_model": PLATFORM_MODEL, "default_backend": "anthropic"})
    monkeypatch.setattr(app.state, "platform", svc, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "server.platform_config_service.wiring_get",
        lambda key, default=None: {"dgx_endpoint": "http://box:8001"}.get(key, default),
    )
    return svc


def _capture(monkeypatch, module="server.routers.grounding"):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr(f"{module}.stream_subprocess", fake_stream_subprocess)
    return captured


def _model_of(cmd):
    return cmd[cmd.index("--model") + 1] if "--model" in cmd else None


# ── The three services that gained an override ─────────────────────────────

OVERRIDE_SERVICES = ["grounding", "party", "planning"]


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_selection_roundtrips(platform, service):
    r = client.put(f"/api/{service}/selection",
                   json={"backend": "dgx", "model": "Qwen3-Next-80B"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json() == {
        "backend": "dgx", "model": "Qwen3-Next-80B",
    }


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_clearing_restores_platform_inheritance(platform, service):
    """FR-013 — clearing requires only clearing it; no global setting is
    disturbed in either direction (SC-007)."""
    client.put(f"/api/{service}/selection", json={"backend": "dgx", "model": "Qwen3-Next-80B"})
    r = client.delete(f"/api/{service}/selection")
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json() == {"backend": None, "model": None}

    resolved = client.get(f"/api/{service}/selection/resolved").json()
    assert resolved["model"] == PLATFORM_MODEL
    assert resolved["model_origin"] == "platform"
    # the platform was never touched by any of the above
    assert platform.runtime.default_model == PLATFORM_MODEL


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_empty_selection_is_indistinguishable_from_absent(platform, service):
    r = client.put(f"/api/{service}/selection", json={"backend": None, "model": None})
    assert r.status_code == 200
    resolved = client.get(f"/api/{service}/selection/resolved").json()
    assert resolved["model_origin"] == "platform"


def test_grounding_override_wins_for_its_own_runs(platform, monkeypatch):
    captured = _capture(monkeypatch)
    client.put("/api/grounding/selection", json={"backend": "dgx", "model": "Qwen3-Next-80B"})
    r = client.get("/api/grounding/run/distill", params={"input": "docs/x.md"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert _model_of(captured["cmd"]) == "Qwen3-Next-80B"
    assert "--backend" in captured["cmd"]


def test_one_services_override_does_not_touch_another(platform, monkeypatch):
    """SC-004. Party overrides; Grounding's own runs must not notice."""
    client.put("/api/party/selection", json={"backend": "dgx", "model": "Qwen3-Next-80B"})

    captured = _capture(monkeypatch)
    r = client.get("/api/grounding/run/distill", params={"input": "docs/x.md"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert _model_of(captured["cmd"]) == PLATFORM_MODEL
    assert "--backend" not in captured["cmd"]


def test_party_and_planning_have_independent_overrides(platform, monkeypatch):
    """They own separate documents, so they must be able to differ — even
    though both runs launch from the Grounding page."""
    client.put("/api/party/selection", json={"backend": "dgx", "model": "Qwen-Party"})
    client.put("/api/planning/selection", json={"model": "claude-haiku-4-5"})

    captured = _capture(monkeypatch)
    r = client.get("/api/grounding/run/party", params={"output": "docs/party.md"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert _model_of(captured["cmd"]) == "Qwen-Party"

    captured2 = _capture(monkeypatch)
    r = client.get("/api/grounding/run/planning", params={"output": "docs/planning.md"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert _model_of(captured2["cmd"]) == "claude-haiku-4-5"


def test_platform_change_moves_non_overriding_services_only(platform, monkeypatch):
    client.put("/api/grounding/selection", json={"model": "claude-haiku-4-5"})
    platform.update_runtime({"default_model": "claude-sonnet-5"})

    captured = _capture(monkeypatch)
    r = client.get("/api/grounding/run/distill", params={"input": "docs/x.md"})
    _ = r.text
    assert _model_of(captured["cmd"]) == "claude-haiku-4-5", "override must be unmoved"

    captured2 = _capture(monkeypatch, "server.routers.prep")
    r = client.get("/api/prep/run/npc-table")
    _ = r.text
    assert _model_of(captured2["cmd"]) == "claude-sonnet-5", "inheritor must follow"


def test_stale_service_override_is_refused_not_substituted(platform, monkeypatch):
    """FR-009/FR-011 at the service tier, with the remedy pointing at the
    override rather than the platform."""
    client.put("/api/grounding/selection", json={"model": "Qwen3-Next-80B"})
    r = client.get("/api/grounding/run/distill", params={"input": "docs/x.md"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["model_origin"] == "service"
    assert detail["remedy"] == "clear_override"
    assert detail["service"] == "distill"


def test_resolved_preview_reports_incompatibility_without_raising(platform):
    """FR-012: the preview must SHOW the problem, not raise it — that is what
    lets the UI display the reason and offer the fix before a run is started."""
    client.put("/api/grounding/selection", json={"model": "Qwen3-Next-80B"})
    r = client.get("/api/grounding/selection/resolved", params={"doc": "distill"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compatible"] is False
    assert "Qwen3-Next-80B" in body["refusal"]
    assert body["model_origin"] == "service"


# ── FR-004: the inheriting services gained nothing ─────────────────────────

@pytest.mark.parametrize("service", ["setup", "prep", "connections"])
def test_inheriting_services_have_no_selection_endpoint(platform, service):
    """Asserted against the route table, not the HTTP status.

    ``server/main.py`` mounts an SPA catch-all (``@app.get("/{full_path:path}")``)
    that serves index.html for anything unmatched, so an absent API route
    answers 200 with HTML rather than 404. Checking the status would therefore
    pass for a route that exists and fail to notice one that doesn't.
    """
    paths = {getattr(r, "path", None) for r in app.routes}
    assert f"/api/{service}/selection" not in paths, (
        "an inheriting service must have nowhere to SET a selection (FR-004)"
    )
    # The read-only preview IS provided, and deliberately so: FR-004 forbids a
    # place to *set* a selection, not a place to *see* the one inherited. These
    # four are precisely the services whose effective backend was invisible
    # before 003, so withholding the preview would preserve the opacity the
    # feature exists to remove.
    assert f"/api/{service}/selection/resolved" in paths


def test_no_new_config_file_is_created(platform, tmp_path):
    """The feature must create zero new config documents — the whole basis of
    the scope decision. Overrides live in files that already existed."""
    client.put("/api/grounding/selection", json={"model": "claude-haiku-4-5"})
    client.put("/api/party/selection", json={"model": "claude-haiku-4-5"})
    client.put("/api/planning/selection", json={"model": "claude-haiku-4-5"})

    written = {p.name for p in (tmp_path / "config").glob("*.yaml")}
    assert "setup.yaml" not in written
    assert "prep.yaml" not in written
    assert "connections.yaml" not in written
    assert written <= {
        "config.yaml", "platform.yaml", "grounding.yaml", "party.yaml",
        "planning.yaml", "session_doc.yaml", "ensemble.yaml",
    }, f"unexpected config document created: {written}"
