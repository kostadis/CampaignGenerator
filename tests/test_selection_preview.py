"""Feature 003 US3 — `GET /api/<service>/selection/resolved` across all eight.

The preview is what makes US3 possible: it reports the model, the backend and
the ORIGIN of each *before* a run starts, and it reports an incompatible pair
**without raising**, so the UI can show the reason and offer the fix rather
than the operator meeting it as a failed run.

That last property is the one worth a dedicated test. Every other selection
path raises `IncompatibleSelection` (409); this one must not, or the pre-run
display would itself 500 exactly when it has something useful to say.
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

# Every token-spending service. The five that own a document may override; the
# five that do not always inherit — but all eight expose the preview, because
# seeing what you inherit is not the same as being able to set it (FR-004).
ALL_SERVICES = ["grounding", "party", "planning", "ensemble", "editor",
                "prep", "setup", "connections"]
OVERRIDE_CAPABLE = ["grounding", "party", "planning"]
INHERITING = ["prep", "setup", "connections"]


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


@pytest.mark.parametrize("service", ALL_SERVICES)
def test_every_service_exposes_a_preview(platform, service):
    r = client.get(f"/api/{service}/selection/resolved")
    assert r.status_code == 200, f"{service}: {r.text}"
    body = r.json()
    assert set(body) == {
        "model", "backend", "model_origin", "backend_origin", "compatible", "refusal",
    }, f"{service} returned {sorted(body)}"


@pytest.mark.parametrize("service", ALL_SERVICES)
def test_preview_reports_the_platform_selection_when_nothing_overrides(platform, service):
    body = client.get(f"/api/{service}/selection/resolved").json()
    assert body["model"] == PLATFORM_MODEL
    assert body["backend"] == "anthropic"
    assert body["model_origin"] == "platform"
    assert body["backend_origin"] == "platform"
    assert body["compatible"] is True
    assert body["refusal"] is None


@pytest.mark.parametrize("service", INHERITING)
def test_inheriting_services_always_report_platform_origin(platform, service):
    """These four are precisely the ones whose effective backend was invisible
    before 003 — they forwarded none at all. Reporting 'platform' is the whole
    answer they have to give, and it is the answer the operator needs."""
    platform.update_runtime({"default_backend": "dgx", "default_model": "Qwen3-Next-80B"})
    body = client.get(f"/api/{service}/selection/resolved").json()
    assert body["backend"] == "dgx"
    assert body["backend_origin"] == "platform"
    assert body["model_origin"] == "platform"


@pytest.mark.parametrize("service", OVERRIDE_CAPABLE)
def test_preview_reports_service_origin_when_overridden(platform, service):
    client.put(f"/api/{service}/selection", json={"model": "claude-haiku-4-5"})
    body = client.get(f"/api/{service}/selection/resolved").json()
    assert body["model"] == "claude-haiku-4-5"
    assert body["model_origin"] == "service"
    # backend was not overridden, so it still comes from the platform —
    # the preview must distinguish the two halves, not report one origin.
    assert body["backend_origin"] == "platform"


@pytest.mark.parametrize("service", OVERRIDE_CAPABLE)
def test_preview_reports_incompatibility_without_raising(platform, service):
    """The property the whole pre-run display rests on. Every other selection
    path raises 409; this one returns 200 and describes the problem."""
    client.put(f"/api/{service}/selection", json={"model": "Qwen3-Next-80B"})
    r = client.get(f"/api/{service}/selection/resolved")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compatible"] is False
    assert body["refusal"] and "Qwen3-Next-80B" in body["refusal"]
    assert body["model_origin"] == "service"


def test_platform_incompatibility_is_previewed_for_inheriting_services(platform):
    """Reachable in normal use: the sidebar model list is Anthropic-only, so
    picking dgx without typing a dgx model leaves this pair — and an
    inheriting service has no override to blame it on."""
    platform.update_runtime({"default_backend": "dgx", "default_model": "claude-sonnet-4-6"})
    body = client.get("/api/prep/selection/resolved").json()
    assert body["compatible"] is False
    assert body["model_origin"] == "platform"


def test_ensemble_preview_is_per_stage(platform):
    """Ensemble's selection is per stage — the canonical workflow runs extract
    on DGX and synthesize on Anthropic in one campaign, so a single answer for
    "the ensemble" would be wrong for one of them."""
    for stage in ("extract", "synthesize"):
        r = client.get("/api/ensemble/selection/resolved", params={"stage": stage})
        assert r.status_code == 200, f"{stage}: {r.text}"
        assert "model" in r.json()


def test_preview_tracks_a_platform_change(platform):
    before = client.get("/api/prep/selection/resolved").json()
    assert before["model"] == PLATFORM_MODEL
    platform.update_runtime({"default_model": "claude-sonnet-5"})
    after = client.get("/api/prep/selection/resolved").json()
    assert after["model"] == "claude-sonnet-5", (
        "the preview must re-resolve, not cache — the sidebar moves this value"
    )


@pytest.mark.parametrize("service", OVERRIDE_CAPABLE)
def test_preview_matches_what_the_run_actually_uses(platform, monkeypatch, service):
    """SC-005's real claim: the displayed value is not merely plausible, it is
    the same value the run receives. A preview that could drift from the run
    would be worse than none."""
    client.put(f"/api/{service}/selection", json={"model": "claude-haiku-4-5"})
    previewed = client.get(f"/api/{service}/selection/resolved").json()["model"]

    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr("server.routers.grounding.stream_subprocess", fake_stream_subprocess)
    route = {
        "grounding": ("/api/grounding/run/distill", {"input": "docs/x.md"}),
        "party": ("/api/grounding/run/party", {"output": "docs/party.md"}),
        "planning": ("/api/grounding/run/planning", {"output": "docs/planning.md"}),
    }[service]
    r = client.get(route[0], params=route[1])
    assert r.status_code == 200, r.text
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--model") + 1] == previewed


def test_ensemble_inherits_the_platform_backend_when_its_stage_is_unconfigured(platform, monkeypatch, tmp_path):
    """FR-008 for the ensemble, and a defect the preview sweep surfaced.

    `EnsembleBackend.backend` has the schema default "anthropic", and
    `_backend_args` folds it in before resolving. Passed as the *request* tier
    that pinned every unconfigured stage to Anthropic — the platform's backend
    could never reach an ensemble run, which is exactly what FR-008 forbids.
    Passing it as the *service* tier lets resolve_selection recognise the
    schema default as "deferring".
    """
    platform.update_runtime({"default_backend": "dgx", "default_model": "Qwen3-Next-80B"})
    body = client.get("/api/ensemble/selection/resolved", params={"stage": "extract"}).json()
    assert body["backend"] == "dgx"
    assert body["backend_origin"] == "platform"
    assert body["model"] == "Qwen3-Next-80B"
