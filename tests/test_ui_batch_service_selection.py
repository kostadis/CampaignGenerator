"""Feature 005-ui-batch-selection, US1 (T015) — batch reaches the run command
it belongs to, persists through the settable services' write paths, and
refuses cleanly (never silently) when it cannot be honoured.

Scope is Phase 3 (US1) only: grounding/party/planning's dedicated
``PUT/GET/DELETE /api/{service}/selection`` trio, plus the Session Doc
Editor's per-backend-profile equivalent (``PUT /api/editor/config`` writing
``backends.<name>.batch``, previewed at ``GET /api/editor/selection/resolved``
— the editor never had a dedicated ``/selection`` write route; see
``tests/test_service_selection_override.py``'s ``OVERRIDE_SERVICES``, which
has always excluded it).

The editor's *run* commands do not yet emit ``--batch`` from the resolved
selection — that rewiring is explicitly reserved for T029 (Phase 6), which
retires the bespoke ``useBatch``/``?batch=1`` mechanism this feature
replaces. Asserting ``--batch`` in an editor run's built command belongs
there, not here; this file only exercises storage + the preview for editor.
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

# The three services with a dedicated `/selection` write door (feature 003).
OVERRIDE_SERVICES = ["grounding", "party", "planning"]

RUN_ROUTE = {
    "grounding": ("/api/grounding/run/distill", {"input": "docs/x.md"}),
    "party": ("/api/grounding/run/party", {"output": "docs/party.md"}),
    "planning": ("/api/grounding/run/planning", {"output": "docs/planning.md"}),
}


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


# ── `--batch` in the built command (T015's headline assertion) ─────────────


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_batch_true_emits_flag(platform, monkeypatch, service):
    client.put(f"/api/{service}/selection", json={"batch": True})
    captured = _capture(monkeypatch)
    path, params = RUN_ROUTE[service]
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text  # drain the SSE body so the faked subprocess runs
    assert "--batch" in captured["cmd"]


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_batch_unset_omits_flag(platform, monkeypatch, service):
    captured = _capture(monkeypatch)
    path, params = RUN_ROUTE[service]
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" not in captured["cmd"]


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_batch_false_override_omits_flag_even_when_platform_is_on(platform, monkeypatch, service):
    """`batch: false` is a sticky, explicit choice (data-model.md) — it must
    NOT follow an app-wide batch-on change, unlike an unset (null) override."""
    platform.update_runtime({"default_batch": True})
    client.put(f"/api/{service}/selection", json={"batch": False})
    captured = _capture(monkeypatch)
    path, params = RUN_ROUTE[service]
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" not in captured["cmd"]


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_platform_batch_is_inherited_when_service_defers(platform, monkeypatch, service):
    platform.update_runtime({"default_batch": True})
    captured = _capture(monkeypatch)
    path, params = RUN_ROUTE[service]
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" in captured["cmd"]


# ── PUT persists batch ──────────────────────────────────────────────────────


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_put_persists_batch_alongside_model_and_backend(platform, service):
    r = client.put(
        f"/api/{service}/selection",
        json={"backend": "dgx", "model": "Qwen3-Next-80B", "batch": True},
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json() == {
        "backend": "dgx", "model": "Qwen3-Next-80B", "batch": True,
    }


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_put_batch_only_is_not_treated_as_empty(platform, service):
    """The load-bearing null-vs-false/empty distinction (data-model.md): a
    selection carrying only `batch` (no model/backend) must survive the
    save/load round-trip, not be discarded as "nothing chosen". This is the
    `ModelSelection.is_empty()` fix `save_party_config`/`save_planning_config`
    and `grounding.py::_selection_for` both depend on.
    """
    r = client.put(f"/api/{service}/selection", json={"batch": True})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json() == {
        "backend": None, "model": None, "batch": True,
    }
    resolved = client.get(f"/api/{service}/selection/resolved").json()
    assert resolved["batch"] is True
    assert resolved["batch_origin"] == "service"


# ── unsatisfiable batch: stored, not rejected (contracts/selection-api.md) ──


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_unsatisfiable_batch_is_stored_not_rejected(platform, service):
    r = client.put(
        f"/api/{service}/selection",
        json={"backend": "dgx", "model": "Qwen3-Next-80B", "batch": True},
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json()["batch"] is True


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_unsatisfiable_batch_refuses_at_preview_without_raising(platform, service):
    client.put(
        f"/api/{service}/selection",
        json={"backend": "dgx", "model": "Qwen3-Next-80B", "batch": True},
    )
    r = client.get(f"/api/{service}/selection/resolved")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compatible"] is False
    assert "batch" in body["refusal"]


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_unsatisfiable_batch_refuses_the_run_and_spawns_nothing(platform, monkeypatch, service):
    client.put(
        f"/api/{service}/selection",
        json={"backend": "dgx", "model": "Qwen3-Next-80B", "batch": True},
    )
    captured = _capture(monkeypatch)
    path, params = RUN_ROUTE[service]
    r = client.get(path, params=params)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "batch" in detail["message"]
    assert "cmd" not in captured, "an incompatible selection must not reach the subprocess"


def test_unsatisfiable_platform_batch_refuses_identically(platform, monkeypatch):
    """D3: origin-independent — an inherited app-wide batch refuses exactly
    as a per-service one does."""
    platform.update_runtime({
        "default_backend": "dgx", "default_model": "Qwen3-Next-80B", "default_batch": True,
    })
    captured = _capture(monkeypatch)
    r = client.get("/api/grounding/run/distill", params={"input": "docs/x.md"})
    assert r.status_code == 409, r.text
    assert "batch" in r.json()["detail"]["message"]
    assert "cmd" not in captured


# ── clearing the override restores inheritance ──────────────────────────────


@pytest.mark.parametrize("service", OVERRIDE_SERVICES)
def test_clearing_override_restores_batch_inheritance(platform, service):
    platform.update_runtime({"default_batch": True})
    client.put(f"/api/{service}/selection", json={"batch": False})
    resolved = client.get(f"/api/{service}/selection/resolved").json()
    assert resolved["batch"] is False
    assert resolved["batch_origin"] == "service"

    r = client.delete(f"/api/{service}/selection")
    assert r.status_code == 200, r.text
    assert client.get(f"/api/{service}/selection").json() == {
        "backend": None, "model": None, "batch": None,
    }

    resolved = client.get(f"/api/{service}/selection/resolved").json()
    assert resolved["batch"] is True
    assert resolved["batch_origin"] == "platform"


# ── Editor: batch persists through PUT /api/editor/config, previewed
#    at GET /api/editor/selection/resolved (T012/T013) ──────────────────────
# The editor has no dedicated `/selection` write route (feature 003 never
# gave it one — its "own document" write door is the grouped
# `PUT /api/editor/config`, merging into `backends.<name>`). `batch` rides
# along on `BackendProfile` (a `ModelSelection` subclass) the same way.


def test_editor_batch_persists_through_config_put(platform):
    r = client.put(
        "/api/editor/config",
        json={"backends": {"anthropic": {"batch": True}}},
    )
    assert r.status_code == 200, r.text
    cfg = client.get("/api/editor/config").json()
    assert cfg["backends"]["anthropic"]["batch"] is True

    resolved = client.get("/api/editor/selection/resolved").json()
    assert resolved["batch"] is True
    assert resolved["batch_origin"] == "service"


def test_editor_unsatisfiable_batch_refuses_at_preview_without_raising(platform):
    """The active profile is dgx with a dgx model, plus batch=true — batch is
    a Claude API option, so this must refuse (naming batch) without raising,
    exactly like the dedicated-`/selection` services above."""
    r = client.put(
        "/api/editor/config",
        json={
            "backends": {
                "active": "dgx",
                "dgx": {"model": "Qwen3-Next-80B", "batch": True},
            }
        },
    )
    assert r.status_code == 200, r.text
    resolved = client.get("/api/editor/selection/resolved").json()
    assert resolved["compatible"] is False
    assert "batch" in resolved["refusal"]


def test_editor_clearing_batch_restores_platform_inheritance(platform):
    platform.update_runtime({"default_batch": True})
    client.put("/api/editor/config", json={"backends": {"anthropic": {"batch": False}}})
    resolved = client.get("/api/editor/selection/resolved").json()
    assert resolved["batch"] is False
    assert resolved["batch_origin"] == "service"

    r = client.put("/api/editor/config", json={"backends": {"anthropic": {"batch": None}}})
    assert r.status_code == 200, r.text
    cfg = client.get("/api/editor/config").json()
    assert cfg["backends"]["anthropic"]["batch"] is None

    resolved = client.get("/api/editor/selection/resolved").json()
    assert resolved["batch"] is True
    assert resolved["batch_origin"] == "platform"
