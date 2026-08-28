"""Gate guards: drafts-only synthesis, no live-doc writes, promote is the sole
live-doc writer (FR-013, SC-005, spec US3)."""

from pathlib import Path

from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_synthesize_rejects_live_doc_output(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "world_state", "output": "docs/world_state.md"})
    assert r.status_code == 400
    assert "draft" in r.json()["detail"]


def test_put_file_rejects_live_doc(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    r = client.put("/api/ensemble/file", params={"path": "docs/world_state.md"},
                   json={"content": "clobbered"})
    assert r.status_code == 403


def test_put_file_allows_aliases(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.put("/api/ensemble/file",
                   params={"path": "docs/ensemble/aliases.json"},
                   json={"content": "{}"})
    assert r.status_code == 200
    assert (tmp_path / "docs/ensemble/aliases.json").read_text() == "{}"


def test_promote_is_sole_live_writer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    draft = tmp_path / "docs/world_state_draft.md"
    draft.write_text("promoted body")
    live = tmp_path / "docs/world_state.md"
    assert not live.exists()

    r = client.post("/api/ensemble/promote",
                    json={"draft": "docs/world_state_draft.md", "live": "docs/world_state.md"})
    assert r.status_code == 200
    assert live.read_text() == "promoted body"


def test_promote_rejects_non_grounding_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/world_state_draft.md").write_text("x")
    r = client.post("/api/ensemble/promote",
                    json={"draft": "docs/world_state_draft.md", "live": "docs/notes.md"})
    assert r.status_code == 400


def test_path_traversal_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/file", params={"path": "../../etc/passwd"})
    assert r.status_code == 400


def test_synthesise_polish_is_a_separate_human_triggered_face():
    """Polish rendering is an explicit review action, not synthesize's tail.

    Keeping this route-level guard independent of TestClient also makes the
    intended boundary visible before the implementation exists: the action
    accepts its reviewed merged input/output and selection, and has no
    approval or auto-advance control of its own.
    """
    paths = app.openapi()["paths"]
    path = "/api/ensemble/run/synthesise-polish"
    assert path in paths
    operation = next(iter(paths[path].values()))
    names = {p["name"] for p in operation.get("parameters", [])}
    assert {"merged", "output", "backend", "model"} <= names
    assert "approval" not in names
    assert "approve" not in names
    assert "/api/ensemble/run/synthesize" in paths


# ── Stale backend-profile leakage (a switched-back-to-anthropic run must not
# ── inherit a previous non-anthropic model/endpoint) ─────────────────────────

def _capture_cmd(monkeypatch):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        captured["env_extra"] = env_extra
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("server.routers.ensemble.stream_subprocess", fake_stream_subprocess)
    return captured


def _write_registry(tmp_path) -> Path:
    """A minimal valid docs/entity_registry.yaml — for tests that don't care
    about registry contents but need one to exist, since /run/bundle,
    /run/threads, and world_state synthesis all require one now."""
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    registry = docs / "entity_registry.yaml"
    registry.write_text("version: 1\nentities: []\n")
    return registry


def test_synthesize_refuses_stale_model_for_anthropic(tmp_path, monkeypatch):
    """FR-009/FR-011 (feature 003): a stale non-Anthropic id on an Anthropic
    run is REFUSED, not silently replaced.

    This test is the deliberate reversal of
    ``test_synthesize_ignores_stale_model_for_anthropic``. The invariant it
    guarded is unchanged and still holds — a foreign id must never reach an
    Anthropic run — but the *remedy* changed. Phase 4 of
    ``docs/config/ensemble-isolation.md`` dropped the stale id and swapped in
    the platform's model, so the run proceeded on something the operator had
    not chosen. The Setup page keeps a per-stage model across a backend
    switch, so this is easy to reach: pick dgx, type a Qwen id, switch back to
    Anthropic.

    Under 003 the operator is told, and clears or corrects the override —
    see ``specs/003-model-selection-resolution/spec.md`` Clarifications.

    If this test ever passes while asserting the old silent substitution, the
    reversal has been undone rather than implemented.
    """
    _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "world_state",
        "backend": "anthropic",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoint": "http://192.168.1.147:8001/v1",
    })
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert detail["model"] == "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
    assert detail["backend"] == "anthropic"
    assert detail["service"] == "ensemble"

def test_bundle_refuses_stale_model_for_anthropic(tmp_path, monkeypatch):
    """FR-009/FR-011 (feature 003): a stale non-Anthropic id on an Anthropic
    run is REFUSED, not silently replaced.

    This test is the deliberate reversal of
    ``test_bundle_ignores_stale_model_for_anthropic``. The invariant it
    guarded is unchanged and still holds — a foreign id must never reach an
    Anthropic run — but the *remedy* changed. Phase 4 of
    ``docs/config/ensemble-isolation.md`` dropped the stale id and swapped in
    the platform's model, so the run proceeded on something the operator had
    not chosen. The Setup page keeps a per-stage model across a backend
    switch, so this is easy to reach: pick dgx, type a Qwen id, switch back to
    Anthropic.

    Under 003 the operator is told, and clears or corrects the override —
    see ``specs/003-model-selection-resolution/spec.md`` Clarifications.

    If this test ever passes while asserting the old silent substitution, the
    reversal has been undone rather than implemented.
    """
    _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    r = client.get("/api/ensemble/run/bundle", params={
        "backend": "anthropic",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoints": ["http://192.168.1.147:8001/v1"],
    })
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert detail["model"] == "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
    assert detail["backend"] == "anthropic"
    assert detail["service"] == "ensemble"

def test_extract_refuses_stale_model_for_anthropic(tmp_path, monkeypatch):
    """FR-009/FR-011 (feature 003): a stale non-Anthropic id on an Anthropic
    run is REFUSED, not silently replaced.

    This test is the deliberate reversal of
    ``test_extract_ignores_stale_model_for_anthropic``. The invariant it
    guarded is unchanged and still holds — a foreign id must never reach an
    Anthropic run — but the *remedy* changed. Phase 4 of
    ``docs/config/ensemble-isolation.md`` dropped the stale id and swapped in
    the platform's model, so the run proceeded on something the operator had
    not chosen. The Setup page keeps a per-stage model across a backend
    switch, so this is easy to reach: pick dgx, type a Qwen id, switch back to
    Anthropic.

    Under 003 the operator is told, and clears or corrects the override —
    see ``specs/003-model-selection-resolution/spec.md`` Clarifications.

    If this test ever passes while asserting the old silent substitution, the
    reversal has been undone rather than implemented.
    """
    _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/extract", params={
        "chapters": ["docs/chapters/chapter_01.md"],
        "backend": "anthropic",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoints": ["http://192.168.1.147:8001/v1"],
    })
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert detail["model"] == "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
    assert detail["backend"] == "anthropic"
    assert detail["service"] == "ensemble"

def test_extract_forwards_backend_and_endpoints_when_non_anthropic(tmp_path, monkeypatch):
    """run_extract previously had no way to forward a backend choice at all
    (ensemble_batch.py had no --backend flag, so the router could only ever
    fall back to env_extra, which run_extract never even set). That gap is
    closed now that ensemble_batch.py accepts --backend/--endpoints/--model
    via the shared backend_cli_args seam."""
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    r = client.get("/api/ensemble/run/extract", params={
        "chapters": ["docs/chapters/chapter_01.md"],
        "backend": "dgx",
        "model": "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        "endpoints": ["http://192.168.1.147:8001/v1"],
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--backend" in cmd
    assert cmd[cmd.index("--backend") + 1] == "dgx"
    assert "--endpoints" in cmd
    assert cmd[cmd.index("--endpoints") + 1] == "http://192.168.1.147:8001/v1"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
    # Chapter selection flags are undisturbed by backend forwarding.
    assert "--chapters" in cmd
    assert not captured["env_extra"]


# ── The entity registry is now mandatory for /run/bundle and /run/threads
# ── (Phase 2 of the registry migration: legacy --aliases/--known-names were
# ── removed from the web UI entirely — migrate-and-delete, not a
# ── dual-location fallback). A campaign dir with no docs/entity_registry.yaml
# ── gets a real SSE error, not a silent legacy run. ─────────────────────────

def test_bundle_passes_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    registry = _write_registry(tmp_path)

    r = client.get("/api/ensemble/run/bundle")
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" in cmd
    assert cmd[cmd.index("--registry") + 1] == str(registry)
    assert "--aliases" not in cmd
    assert "--known-names" not in cmd


def test_bundle_errors_without_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/bundle")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "No entity registry" in r.text
    assert "cmd" not in captured


def test_threads_passes_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    registry = _write_registry(tmp_path)

    r = client.get("/api/ensemble/run/threads")
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" in cmd
    assert cmd[cmd.index("--registry") + 1] == str(registry)
    assert "--aliases" not in cmd


# ── Per-stage batch forwarding (005-ui-batch-selection, T020/T022) ──────────
#
# The ensemble stage tier (extract/synthesize) is duck-typed into
# resolve_selection via _backend_args, which — unlike every other router —
# builds its own args instead of delegating wholesale to selection_cli_args
# (endpoint/endpoints are a per-stage fan-out shape ModelSelection cannot
# carry). These tests exercise the seam end to end: a stage's stored `batch`
# reaches the actual subprocess command, a request-level override wins over
# it, an incompatible combination refuses before any subprocess spawns
# (mirroring test_ui_batch_service_selection.py's grounding/party/planning
# coverage for T027, extended here to the newly-wired ensemble path per
# T028's "no route builds a command from a batch-true-but-incompatible
# selection" backstop), and the per-stage preview reflects it independently
# for extract vs. synthesize.

import pytest
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME


@pytest.fixture
def ensemble_platform(monkeypatch, tmp_path):
    """A live platform for the ensemble tests that need platform-tier
    inheritance (mirrors tests/test_ui_batch_service_selection.py's
    `platform` fixture) — most of this file's tests run with no live
    platform at all (resolve_selection tolerates that), so this is opt-in
    rather than file-wide."""
    config_subdir = tmp_path / "config"
    config_subdir.mkdir(parents=True, exist_ok=True)
    (config_subdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    svc = PlatformConfigService(tmp_path)
    svc.update_runtime({"default_model": "claude-opus-5", "default_backend": "anthropic"})
    monkeypatch.setattr(app.state, "platform", svc, raising=False)
    monkeypatch.chdir(tmp_path)
    return svc


def test_extract_batch_forwarded_when_stage_config_batch_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.put("/api/ensemble/config", json={"extract": {"batch": True}})
    assert r.status_code == 200, r.text

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract",
                   params={"chapters": ["docs/chapters/chapter_01.md"]})
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" in captured["cmd"]


def test_extract_batch_omitted_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract",
                   params={"chapters": ["docs/chapters/chapter_01.md"]})
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" not in captured["cmd"]


def test_extract_request_batch_overrides_stored_stage_config(tmp_path, monkeypatch):
    """The request tier still wins over the stored per-stage value — the
    per-stage `batch` query param on /run/extract is folded the same
    null-vs-false-aware way as backend/model."""
    monkeypatch.chdir(tmp_path)
    client.put("/api/ensemble/config", json={"extract": {"batch": True}})

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract", params={
        "chapters": ["docs/chapters/chapter_01.md"], "batch": False,
    })
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" not in captured["cmd"]


def test_bundle_batch_forwarded_from_extract_stage(tmp_path, monkeypatch):
    """/run/bundle has no tier of its own — it reuses the extract stage's
    selection (same as backend/model already do, see run_bundle)."""
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    client.put("/api/ensemble/config", json={"extract": {"batch": True}})

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/bundle")
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" in captured["cmd"]


def test_synthesize_batch_forwarded_when_stage_config_batch_true(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.put("/api/ensemble/config", json={"synthesize": {"batch": True}})

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/synthesize", params={"doc": "campaign_state"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" in captured["cmd"]


def test_synthesize_batch_omitted_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/synthesize", params={"doc": "campaign_state"})
    assert r.status_code == 200, r.text
    _ = r.text
    assert "--batch" not in captured["cmd"]


def test_extract_and_synthesize_batch_are_independent_stages(tmp_path, monkeypatch):
    """Setting batch on one stage must not leak onto the other — matching how
    backend/model already differ per stage in the canonical DGX-extract /
    Anthropic-synthesize workflow."""
    monkeypatch.chdir(tmp_path)
    client.put("/api/ensemble/config", json={"extract": {"batch": True},
                                             "synthesize": {"batch": False}})

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract",
                   params={"chapters": ["docs/chapters/chapter_01.md"]})
    _ = r.text
    assert "--batch" in captured["cmd"]

    captured2 = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/synthesize", params={"doc": "campaign_state"})
    _ = r.text
    assert "--batch" not in captured2["cmd"]


# ── Incompatible batch refuses before any subprocess spawns (T027 backstop
# ── for the ensemble path specifically; T028's "no route builds a command
# ── from a batch-true-but-incompatible selection") ──────────────────────────


def test_extract_incompatible_batch_refuses_and_spawns_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.put("/api/ensemble/config", json={
        "extract": {"backend": "dgx", "model": "Qwen3-Next-80B",
                    "endpoints": ["http://box:8001/v1"], "batch": True},
    })
    assert r.status_code == 200, r.text

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract",
                   params={"chapters": ["docs/chapters/chapter_01.md"]})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert "batch" in detail["message"]
    assert "cmd" not in captured, "an incompatible selection must not reach the subprocess"


def test_synthesize_incompatible_batch_refuses_and_spawns_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.put("/api/ensemble/config", json={
        "synthesize": {"backend": "openrouter", "model": "anthropic/claude-sonnet-4",
                       "batch": True},
    })
    assert r.status_code == 200, r.text

    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/synthesize", params={"doc": "campaign_state"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "incompatible_selection"
    assert "batch" in detail["message"]
    assert "cmd" not in captured


def test_platform_inherited_batch_refuses_identically_for_ensemble(ensemble_platform, monkeypatch):
    """D3, extended to ensemble: an app-wide batch inherited by an
    unconfigured stage refuses exactly as a per-stage override does."""
    ensemble_platform.update_runtime({
        "default_backend": "dgx", "default_model": "Qwen3-Next-80B", "default_batch": True,
    })
    captured = _capture_cmd(monkeypatch)
    r = client.get("/api/ensemble/run/extract",
                   params={"chapters": ["docs/chapters/chapter_01.md"]})
    assert r.status_code == 409, r.text
    assert "batch" in r.json()["detail"]["message"]
    assert "cmd" not in captured


# ── Per-stage preview exposes batch independently (T022) ───────────────────


def test_ensemble_preview_exposes_batch_per_stage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.put("/api/ensemble/config", json={
        "extract": {"batch": True}, "synthesize": {"batch": False},
    })

    extract_preview = client.get("/api/ensemble/selection/resolved",
                                 params={"stage": "extract"}).json()
    assert extract_preview["batch"] is True
    assert extract_preview["batch_origin"] == "service"

    synth_preview = client.get("/api/ensemble/selection/resolved",
                               params={"stage": "synthesize"}).json()
    assert synth_preview["batch"] is False
    assert synth_preview["batch_origin"] == "service"


def test_ensemble_preview_unsatisfiable_batch_reports_without_raising(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.put("/api/ensemble/config", json={
        "extract": {"backend": "dgx", "model": "Qwen3-Next-80B", "batch": True},
    })
    r = client.get("/api/ensemble/selection/resolved", params={"stage": "extract"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compatible"] is False
    assert "batch" in body["refusal"]


def test_threads_errors_without_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/threads")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "No entity registry" in r.text
    assert "cmd" not in captured


# ── world_state synthesis: same mandatory-registry gate, plus --inventory ──

def test_synthesize_world_state_passes_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    registry = _write_registry(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "world_state"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--registry" in cmd
    assert cmd[cmd.index("--registry") + 1] == str(registry)


def test_synthesize_world_state_errors_without_registry(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "world_state"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "No entity registry" in r.text
    assert "cmd" not in captured


def test_synthesize_world_state_passes_inventory(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    inv_dir = tmp_path / "docs" / "background"
    inv_dir.mkdir(parents=True)
    inv = inv_dir / "inv.md"
    inv.write_text("# Inventory\n")

    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "world_state", "inventory": "docs/background/inv.md",
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--inventory" in cmd
    assert cmd[cmd.index("--inventory") + 1] == str(inv)

    # No param, and no cfg.paths.inventory set (this router has no
    # EnsembleConfigService override here, so it's the schema default "") ->
    # the flag must be entirely absent, not passed as an empty string.
    r2 = client.get("/api/ensemble/run/synthesize", params={"doc": "world_state"})
    assert r2.status_code == 200
    _ = r2.text
    assert "--inventory" not in captured["cmd"]


# ── Subscription (claude-code) backend selection ────────────────────────────

def test_synthesize_forwards_claude_code_backend_and_model(tmp_path, monkeypatch):
    """Backend selection now travels as explicit CLI flags on cmd, not as
    env_extra (env_extra is never passed by any route anymore)."""
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "world_state",
        "backend": "claude-code",
        "model": "claude-opus-4-8",
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--backend" in cmd
    assert cmd[cmd.index("--backend") + 1] == "claude-code"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-8"
    # Other flags around the backend forwarding are undisturbed.
    assert "--dossiers" in cmd
    assert "--output" in cmd
    assert not captured["env_extra"]


def test_bundle_forwards_claude_code_backend_and_model(tmp_path, monkeypatch):
    """Same cmd-based forwarding for the run_bundle route (-> facts_to_state.py)."""
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    r = client.get("/api/ensemble/run/bundle", params={
        "backend": "claude-code",
        "model": "claude-opus-4-8",
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--backend" in cmd
    assert cmd[cmd.index("--backend") + 1] == "claude-code"
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-8"
    # Other flags around the backend forwarding are undisturbed.
    assert "--out-dir" in cmd
    assert "--min-facts" in cmd
    assert not captured["env_extra"]


@pytest.mark.parametrize(
    "path,base_params",
    [
        ("/api/ensemble/run/synthesize", {"doc": "world_state"}),
        ("/api/ensemble/run/bundle", {}),
        ("/api/ensemble/run/extract", {"chapters": ["docs/chapters/chapter_01.md"]}),
    ],
)
def test_ensemble_routes_forward_explicit_codex_selection(tmp_path, monkeypatch, path, base_params):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    params = dict(base_params)
    params.update(backend="codex-cli", model="gpt-5-codex")
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


def test_ensemble_codex_omits_inherited_claude_model(ensemble_platform, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    _write_registry(ensemble_platform.campaign_dir)
    r = client.get("/api/ensemble/run/synthesize", params={"doc": "world_state", "backend": "codex-cli"})
    assert r.status_code == 200, r.text
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--backend") + 1] == "codex-cli"
    assert "--model" not in cmd


def test_ensemble_codex_explicit_claude_model_refuses_before_child(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    _write_registry(tmp_path)
    r = client.get(
        "/api/ensemble/run/synthesize",
        params={"doc": "world_state", "backend": "codex-cli", "model": "claude-sonnet-4-6"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "incompatible_selection"
    assert "cmd" not in captured


# ── party synthesis: party.yaml preferred over staged extracts ─────────────

def test_synthesize_party_auto_detects_conventional_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    party_yaml = tmp_path / "config" / "party.yaml"
    party_yaml.write_text("characters: []\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--party-config" in cmd
    assert cmd[cmd.index("--party-config") + 1] == str(party_yaml)
    assert "--synthesize-only" not in cmd
    assert "--extract-dir" not in cmd
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "party config:" in r.text


def test_synthesize_party_explicit_path_overrides_default(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    custom = tmp_path / "custom_party.yaml"
    custom.write_text("characters: []\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "party", "party": "custom_party.yaml"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--party-config") + 1] == str(custom)
    # Caller supplied the path explicitly, and no world_state/campaign_state
    # docs exist in this tmp_path to auto-detect as context either.
    assert "Auto-detected" not in r.text


def test_synthesize_party_falls_back_without_any_party_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--party-config" not in cmd
    assert "--synthesize-only" in cmd


def test_synthesize_party_auto_includes_world_state_and_campaign_state_context(tmp_path, monkeypatch):
    """Characters-only party synthesis has no session extracts of its own —
    without world_state/campaign_state as --context it can only report
    current location/quests/reputation as absent (the bug this closes)."""
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    (tmp_path / "docs").mkdir()
    # world_state: only a draft exists — draft should be preferred. Default
    # drafts_dir (no config/ensemble.yaml in this fixture) is
    # docs/ensemble/drafts (EnsemblePaths.drafts_dir).
    (tmp_path / "docs" / "ensemble" / "drafts").mkdir(parents=True)
    ws_draft = tmp_path / "docs" / "ensemble" / "drafts" / "world_state_draft.md"
    ws_draft.write_text("world state")
    # campaign_state: only the live doc exists — should be used as a fallback.
    cs_live = tmp_path / "docs" / "campaign_state.md"
    cs_live.write_text("campaign state")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "party"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    context_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--context"]
    assert str(ws_draft) in context_flags
    assert str(cs_live) in context_flags
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "party config:" in r.text
    assert "context:" in r.text


def test_synthesize_party_explicit_context_overrides_auto_detect(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "party.yaml").write_text("characters: []\n")
    (tmp_path / "docs").mkdir()
    # Present only to prove explicit --context wins over auto-detect; its
    # exact location doesn't matter since _default_party_context is never
    # called when the caller supplies context.
    (tmp_path / "docs" / "ensemble" / "drafts").mkdir(parents=True)
    (tmp_path / "docs" / "ensemble" / "drafts" / "world_state_draft.md").write_text("world state")
    custom_context = tmp_path / "notes.md"
    custom_context.write_text("notes")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "party", "context": ["notes.md"]})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    context_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--context"]
    assert context_flags == ["notes.md"]
    # Caller-supplied context — no auto-detect note for it.
    assert "context:" not in r.text


# ── planning synthesis: planning.yaml preferred over raw --npc/--arc-scores ─

def test_synthesize_planning_auto_detects_conventional_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    planning_yaml = tmp_path / "config" / "planning.yaml"
    planning_yaml.write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--planning-config" in cmd
    assert cmd[cmd.index("--planning-config") + 1] == str(planning_yaml)
    assert "--arc-scores" not in cmd
    # em-dash is JSON-escaped in the SSE payload — check around it instead.
    assert "Auto-detected" in r.text
    assert "planning config:" in r.text


def test_synthesize_planning_explicit_path_overrides_default(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")
    custom = tmp_path / "custom_planning.yaml"
    custom.write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "planning", "planning_config": "custom_planning.yaml"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--planning-config") + 1] == str(custom)
    assert "Auto-detected" not in r.text


def test_synthesize_planning_falls_back_without_any_planning_config(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)

    r = client.get("/api/ensemble/run/synthesize", params={
        "doc": "planning",
        "npc": ["grundar.md"],
        "arc_scores": ["grundar_score.md"],
    })
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--planning-config" not in cmd
    assert cmd[cmd.index("--npc") + 1] == "grundar.md"
    assert cmd[cmd.index("--arc-scores") + 1] == "grundar_score.md"


# ── planning synthesis: --npc pass-through for NPCs not in planning.yaml ───
# planning.yaml's npcs: list is only the arc-scored minority (planning.py's
# own docstring calls --npc pass-through "the majority") — without this,
# every NPC not manually added to planning.yaml is silently absent from
# planning.md.

def test_synthesize_planning_auto_includes_passthrough_npc_dossiers(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    tracked = dossiers_dir / "npc_grundar.md"
    tracked.write_text("# Grundar\n")
    untracked = dossiers_dir / "npc_xalvosh.md"
    untracked.write_text("# Xalvosh\n")

    planning_yaml = tmp_path / "config" / "planning.yaml"
    planning_yaml.write_text(f"npcs:\n  - name: Grundar\n    dossier: {tracked}\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    npc_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--npc"]
    # The config-bound dossier must NOT also appear as pass-through (planning.py's
    # own overlap guard rejects an NPC appearing in both places).
    assert str(untracked) in npc_flags
    assert str(tracked) not in npc_flags
    assert "Auto-detected" in r.text
    assert "pass-through NPC dossier" in r.text


def test_synthesize_planning_explicit_npc_overrides_passthrough(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    (dossiers_dir / "npc_xalvosh.md").write_text("# Xalvosh\n")
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize",
                   params={"doc": "planning", "npc": ["custom.md"]})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    npc_flags = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--npc"]
    assert npc_flags == ["custom.md"]
    assert "pass-through" not in r.text


def test_synthesize_planning_no_passthrough_without_merged_dossiers(tmp_path, monkeypatch):
    captured = _capture_cmd(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "planning.yaml").write_text("factions:\n  - name: Test\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    _ = r.text
    cmd = captured["cmd"]
    assert "--npc" not in cmd
    assert "pass-through" not in r.text


def test_synthesize_planning_bad_config_surfaces_sse_error_not_500(tmp_path, monkeypatch):
    """load_planning_config raises ValueError on a missing dossier reference —
    that must reach the client as a readable SSE error, not an unhandled 500
    (which the frontend's EventSource can't distinguish from a dropped
    connection and reports as "[connection lost — run stopped]")."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    bad = tmp_path / "config" / "planning.yaml"
    bad.write_text("npcs:\n  - name: Ghost\n    dossier: missing.md\n")
    dossiers_dir = tmp_path / "docs" / "ensemble" / "merged_dossiers"
    dossiers_dir.mkdir(parents=True)
    (dossiers_dir / "npc_xalvosh.md").write_text("# Xalvosh\n")

    r = client.get("/api/ensemble/run/synthesize", params={"doc": "planning"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "planning config error" in r.text
    assert "event: done" in r.text
