"""HTTP tests for the Session Doc Editor profile API
(``/api/editor/profiles/*``) — Phase 3a of
``docs/config/session-editor-isolation.md``.

Mirrors ``tests/test_planning_routes.py``'s status-code contract (200/201/
204/404/409/400 via an isolated ``FastAPI()`` + ``include_router(prefix=
...)``), but — unlike planning's stub — wires ``app.state.platform`` to a
real ``PlatformConfigService``: the editor router's dependency chain
(``get_editor_service`` -> ``get_editor_config``) calls
``.resolved_editor_config()``, which a stub can't satisfy. Scaffold
(``fresh_campaign`` / minimal ``config.yaml``) copied from
``tests/test_editor_service_integration.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.platform_config_service import PlatformConfigService, TRACKED_CONFIG_NAME
from server.routers import scene_editor

CONFIG_SUBDIR = "config"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fresh_campaign(tmp_path):
    _write(
        tmp_path / CONFIG_SUBDIR / TRACKED_CONFIG_NAME,
        "documents:\n  - label: world_state\n    path: docs/world_state.md\n",
    )
    return tmp_path


@pytest.fixture
def client(fresh_campaign):
    app = FastAPI()
    # Mirror main.py: the "/api/editor" prefix comes from include_router.
    app.include_router(scene_editor.router, prefix="/api/editor")
    app.state.platform = PlatformConfigService(fresh_campaign)
    return TestClient(app), fresh_campaign


# ── routes are mounted at the correct path (double-prefix regression) ──────


def test_double_prefix_guard(client):
    c, _ = client
    # Correct path resolves...
    assert c.get("/api/editor/profiles").status_code == 200
    # ...and the double-prefixed path does NOT exist.
    assert c.get("/api/editor/api/editor/profiles").status_code == 404


# ── profile CRUD status contract (mirrors planning's faction lifecycle) ────


def test_profile_http_lifecycle(client):
    c, _ = client
    assert c.get("/api/editor/profiles").json() == []

    r = c.post(
        "/api/editor/profiles",
        json={"name": "fast", "knobs": {"narrate_tokens": 4000}},
    )
    assert r.status_code == 201
    assert r.json()["name"] == "fast"
    assert r.json()["knobs"]["narrate_tokens"] == 4000

    got = c.get("/api/editor/profiles/fast")
    assert got.status_code == 200
    assert got.json()["name"] == "fast"

    assert [p["name"] for p in c.get("/api/editor/profiles").json()] == ["fast"]

    # duplicate → 409
    assert c.post("/api/editor/profiles", json={"name": "fast"}).status_code == 409

    # update (PUT) round-trips
    r = c.put(
        "/api/editor/profiles/fast",
        json={"name": "fast", "knobs": {"narrate_tokens": 8000}},
    )
    assert r.status_code == 200
    assert r.json()["knobs"]["narrate_tokens"] == 8000

    # name mismatch → 400
    assert c.put("/api/editor/profiles/fast", json={"name": "other"}).status_code == 400

    # missing → 404 (get / put / delete)
    assert c.get("/api/editor/profiles/nope").status_code == 404
    assert c.put("/api/editor/profiles/nope", json={"name": "nope"}).status_code == 404
    assert c.delete("/api/editor/profiles/nope").status_code == 404

    # delete → 204; last entry removed, list reads back empty (not 400)
    assert c.delete("/api/editor/profiles/fast").status_code == 204
    assert c.get("/api/editor/profiles").json() == []


# ── activate mirrors the profile's knobs into the resolved config ──────────


def test_activate_profile_mirrors_knobs_into_resolved_config(client):
    c, _ = client
    c.post(
        "/api/editor/profiles",
        json={
            "name": "batch_dgx",
            "knobs": {
                "narrate_tokens": 9000,
                "prose_mode": True,
                "reflections": True,
                "narration_genre": "noir",
                "backend": "dgx",
            },
        },
    )

    r = c.post("/api/editor/profiles/batch_dgx/activate")
    assert r.status_code == 200
    body = r.json()
    # Same shape as GET /api/editor/config — the _serialize_resolved helper
    # is the single source of truth for both.
    assert set(body.keys()) == {
        "paths", "narrate", "scrub", "roster", "backends",
        "session_name", "profiles", "active_profile", "model",
        "work_dir", "campaign_dir", "config_dir", "vtt", "session_dir",
    }
    assert body["narrate"]["tokens"] == 9000
    assert body["narrate"]["prose_mode"] is True
    assert body["narrate"]["reflections"] is True
    assert body["narrate"]["genre"] == "noir"
    assert body["backends"]["active"] == "dgx"
    assert body["active_profile"] == "batch_dgx"

    # And a subsequent GET /api/editor/config reflects the same persisted
    # state — activation is a real write, not just an echoed response.
    get_body = c.get("/api/editor/config").json()
    assert get_body["narrate"]["tokens"] == 9000
    assert get_body["active_profile"] == "batch_dgx"


def test_activate_missing_profile_404(client):
    c, _ = client
    assert c.post("/api/editor/profiles/nope/activate").status_code == 404
