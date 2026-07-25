"""Feature 003 — the cross-router guarantees, asserted in one place.

`tests/test_grounding_backend.py` covers the grounding routes in depth and
`tests/test_ensemble_*` cover the ensemble ones. This file asserts the
properties that are only meaningful *across* routers, and which no per-router
test can catch:

- **C4 / FR-005** — no router reads another service's configuration. This is
  structural, mirroring `tests/test_retrieve_render_isolation.py`, which is
  the repo's precedent for enforcing a constitutional boundary with a test
  rather than a convention.
- **C1** — exactly one `--model` per command, on every endpoint.
- **C2 / SC-001** — the platform backend reaches every token-spending
  endpoint. Four of the six routers ignored it entirely before 003.
- **FR-004** — the five inheriting services gained no config surface.

The endpoint inventory below is the feature's scope made executable. It is 22
endpoints, not the 17 the first draft of the spec claimed — the Session Doc
Editor has six, not two (see research.md R10).
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from server.main import app
from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME

client = TestClient(app)

ROUTERS = Path(__file__).resolve().parent.parent / "server" / "routers"


# ── C4 / FR-005: no router reads another service's config ──────────────────

# Which config service each router is allowed to import. A router may compose
# the *platform* (every service does) and the service whose work its endpoints
# actually run — nothing else.
#
# grounding.py is allowed three because it *hosts* three services' run
# endpoints: /run/campaign-state and /run/distill are Grounding's own, but
# /run/party runs the Party service and /run/planning runs Planning. Reading
# party.yaml to run party.py is reading the document of the service whose work
# you are doing; that is not the coupling FR-005 forbids.
#
# The coupling FR-005 forbids is reading a service's document to configure a
# DIFFERENT service's run — which is exactly what grounding.py did with
# SessionEditorConfigService, taking the editor's backend to decide grounding's
# own. SessionEditorConfigService is therefore absent from every allowlist
# below and asserted against by name in
# test_grounding_no_longer_defines_backend_flags.
#
# The underlying misalignment — that /run/party lives in grounding.py while
# party.yaml belongs to PartyConfigService — predates this feature and is left
# alone deliberately: moving those endpoints would change API paths the
# frontend depends on, which is a different change from unifying selection.
OWN_SERVICE = {
    "grounding.py": {"GroundingConfigService", "PartyConfigService", "PlanningConfigService"},
    "ensemble.py": {"EnsembleConfigService"},
    "scene_editor.py": {"SessionEditorConfigService"},
    "party_routes.py": {"PartyConfigService"},
    "planning_routes.py": {"PlanningConfigService"},
    "prep.py": set(),
    "setup.py": set(),
    "connections.py": set(),
    "config_routes.py": set(),
}

ALL_SERVICES = {
    "GroundingConfigService", "EnsembleConfigService", "SessionEditorConfigService",
    "PartyConfigService", "PlanningConfigService",
}


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
        elif isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[-1] for a in node.names)
    return names


@pytest.mark.parametrize("filename,allowed", sorted(OWN_SERVICE.items()))
def test_router_reads_only_its_own_service(filename, allowed):
    """A router may compose the platform and its own service. Reading another
    service's document is the coupling that let a Session Doc Editor edit
    silently re-target every Grounding run.
    """
    path = ROUTERS / filename
    if not path.is_file():  # pragma: no cover - router renamed
        pytest.skip(f"{filename} not present")
    foreign = (_imported_names(path) & ALL_SERVICES) - allowed
    assert not foreign, (
        f"{filename} imports {sorted(foreign)} — a router must not read another "
        f"service's configuration (FR-005, contract guarantee C4)"
    )


def test_grounding_no_longer_defines_backend_flags():
    """The specific function that carried the cross-service read."""
    import server.routers.grounding as g

    assert not hasattr(g, "_backend_flags")
    assert not hasattr(g, "SessionEditorConfigService")


# ── FR-004: the inheriting services gained no config surface ───────────────

def test_no_setup_config_module_was_created():
    """Setup, Session Prep, NPC Table, Query and Connection Graph own no
    configuration by prior decision (D1, docs/config/ui-state-retirement.md).
    003 must not hand it back — the whole point of scoping overrides to the
    five services that already own a document is that this feature creates
    zero new config files.
    """
    server_dir = ROUTERS.parent
    for forbidden in ("setup_config_service.py", "setup_config_shared.py",
                      "prep_config_service.py", "connections_config_service.py"):
        assert not (server_dir / forbidden).is_file(), (
            f"{forbidden} would give an inheriting service a config surface (FR-004)"
        )


# ── C1 / C2 / SC-001: every endpoint carries the resolved selection ────────

# The full token-spending inventory. Session-editor and connections routes are
# exercised by their own suites (they need session fixtures / an API client);
# the /run/* set below is what can be driven uniformly from one harness.
RUN_ENDPOINTS = [
    ("server.routers.grounding", "/api/grounding/run/campaign-state", {"input": "docs/x.md"}),
    ("server.routers.grounding", "/api/grounding/run/distill", {"input": "docs/x.md"}),
    ("server.routers.grounding", "/api/grounding/run/party", {"output": "docs/party.md"}),
    ("server.routers.grounding", "/api/grounding/run/planning", {"output": "docs/planning.md"}),
    ("server.routers.grounding", "/api/grounding/run/build-dossiers", {"summaries": "docs/s"}),
    ("server.routers.prep", "/api/prep/run/session-prep", {"beat": "the party descends"}),
    ("server.routers.prep", "/api/prep/run/npc-table", {}),
    ("server.routers.prep", "/api/prep/run/query", {"input": "docs/s.md", "query": "who"}),
    ("server.routers.setup", "/api/setup/run/dnd-sheet", {"pdfs": ["sheet.pdf"], "output": "o.md"}),
    ("server.routers.setup", "/api/setup/run/make-tracking", {"input": "docs/m.md"}),
]


def _seed(monkeypatch, tmp_path, backend, model):
    config_subdir = tmp_path / "config"
    config_subdir.mkdir(parents=True, exist_ok=True)
    (config_subdir / TRACKED_CONFIG_NAME).write_text(
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
        encoding="utf-8",
    )
    platform = PlatformConfigService(tmp_path)
    platform.update_runtime({"default_backend": backend, "default_model": model})
    monkeypatch.setattr(app.state, "platform", platform, raising=False)
    monkeypatch.setattr(
        "server.platform_config_service.wiring_get",
        lambda key, default=None: {"dgx_endpoint": "http://box:8001"}.get(key, default),
    )


def _capture(monkeypatch, module):
    captured = {}

    async def fake_stream_subprocess(cmd, cwd=None, env_extra=None, on_complete=None):
        captured["cmd"] = cmd
        if on_complete:
            on_complete(0)
        return
        yield  # pragma: no cover

    monkeypatch.setattr(f"{module}.stream_subprocess", fake_stream_subprocess)
    return captured


@pytest.mark.parametrize("module,path,params", RUN_ENDPOINTS)
def test_platform_backend_reaches_every_run_endpoint(monkeypatch, tmp_path, module, path, params):
    """SC-001 / C2. Before 003, prep.py and setup.py emitted no --backend at
    all: selecting DGX and running an NPC Table, a Query, a session prep, a
    D&D sheet import or make-tracking silently billed the metered Anthropic
    API. Nothing in the UI said the choice had been dropped.
    """
    captured = _capture(monkeypatch, module)
    _seed(monkeypatch, tmp_path, "dgx", "Qwen3-Next-80B")
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    cmd = captured["cmd"]
    assert "--backend" in cmd, f"{path} dropped the platform backend"
    assert cmd[cmd.index("--backend") + 1] == "dgx"


@pytest.mark.parametrize("module,path,params", RUN_ENDPOINTS)
def test_exactly_one_model_flag_everywhere(monkeypatch, tmp_path, module, path, params):
    """C1. The pre-003 Grounding path emitted two --model flags from two
    different owners and relied on argparse last-wins.
    """
    captured = _capture(monkeypatch, module)
    _seed(monkeypatch, tmp_path, "dgx", "Qwen3-Next-80B")
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    assert captured["cmd"].count("--model") == 1


@pytest.mark.parametrize("module,path,params", RUN_ENDPOINTS)
def test_platform_model_reaches_every_run_endpoint(monkeypatch, tmp_path, module, path, params):
    """SC-002 — the resolved model is the operator's, on every endpoint."""
    captured = _capture(monkeypatch, module)
    _seed(monkeypatch, tmp_path, "anthropic", "claude-opus-5")
    r = client.get(path, params=params)
    assert r.status_code == 200, r.text
    _ = r.text
    cmd = captured["cmd"]
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5"


@pytest.mark.parametrize("module,path,params", RUN_ENDPOINTS)
def test_incompatible_platform_pair_refuses_every_run_endpoint(monkeypatch, tmp_path, module, path, params):
    """FR-009/FR-011 across the board: no endpoint quietly substitutes.

    Reachable in normal use — the sidebar's model list is Anthropic-only, so
    selecting dgx without typing a dgx model produces exactly this pair. That
    is why T018 (free-text model entry for non-Anthropic backends) is part of
    the same story rather than a nicety.
    """
    captured = _capture(monkeypatch, module)
    _seed(monkeypatch, tmp_path, "dgx", "claude-sonnet-4-6")
    r = client.get(path, params=params)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "incompatible_selection"
    assert "cmd" not in captured, "no subprocess may be spawned on a refusal"


# ── FR-014: the run record proves what actually ran ────────────────────────

def test_run_log_records_the_resolved_selection(tmp_path):
    """FR-014 is satisfied by existing infrastructure, not new code.

    `specs/002-ensemble-run-observability` already writes a durable run record
    whose `command` block is the full invocation. Because the resolved model
    and backend reach the subprocess *as flags on that command line*, the
    record contains them for free. This test pins that inference so a future
    change to `_save_run_log`'s format cannot quietly break the guarantee.
    """
    from server.subprocess_runner import _save_run_log

    cmd = ["distill", "--input", "docs/x.md", "--backend", "dgx",
           "--endpoint", "http://box:8001", "--model", "Qwen3-Next-80B"]
    _save_run_log(cmd, str(tmp_path), "done", 0, "succeeded", 1.5)

    logs = list((tmp_path / "logs").glob("*.md"))
    assert len(logs) == 1
    body = logs[0].read_text(encoding="utf-8")
    assert "--model" in body and "Qwen3-Next-80B" in body
    assert "--backend" in body and "dgx" in body
    assert "result: `succeeded`" in body
    # secret-free (SC-002 of specs/002): keys are inherited env, never argv
    assert "API_KEY" not in body
