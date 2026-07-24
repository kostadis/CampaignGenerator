"""HTTP tests for the isolated planning API (``/api/planning/*``).

These exercise the router as wired in ``server/main.py`` and would have
caught the double-prefix regression (routes mounted at
``/api/planning/api/planning/*`` because the router set its own prefix on
top of ``include_router``'s prefix). Status-code contract: 200/201/204
happy paths, 404 missing, 409 duplicate, 400 name mismatch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import planning_routes  # noqa: E402


class _StubPlatform:
    """Minimal stand-in exposing exactly the one attribute the planning
    router reads from ``app.state.platform`` — ``config_path_base`` (via
    planning_routes.get_planning_service / PlanningConfigService)."""

    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.campaign_dir = Path(campaign_dir)
        self.config_dir = config_dir
        self.config_path_base = self.campaign_dir / self.config_dir


@pytest.fixture
def client(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    app = FastAPI()
    # Mirror main.py: the "/api/planning" prefix comes from include_router.
    app.include_router(planning_routes.router, prefix="/api/planning")
    app.state.platform = _StubPlatform(tmp_path)
    return TestClient(app), tmp_path


def _touch(tmp_path: Path, rel: str) -> None:
    p = tmp_path / "config" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


# ── routes are mounted at the correct path (double-prefix regression) ──────

def test_routes_mounted_at_api_planning(client):
    c, _ = client
    # Correct path resolves...
    assert c.get("/api/planning/npcs").status_code == 200
    # ...and the double-prefixed path does NOT exist.
    assert c.get("/api/planning/api/planning/npcs").status_code == 404


# ── faction lifecycle over HTTP (name-only, no file deps) ──────────────────

def test_faction_http_lifecycle(client):
    c, _ = client
    assert c.get("/api/planning/factions").json() == []

    r = c.post("/api/planning/factions", json={"name": "Krakens"})
    assert r.status_code == 201
    assert r.json()["name"] == "Krakens"

    assert c.get("/api/planning/factions/Krakens").status_code == 200
    assert [f["name"] for f in c.get("/api/planning/factions").json()] == ["Krakens"]

    # duplicate → 409
    assert c.post("/api/planning/factions", json={"name": "Krakens"}).status_code == 409

    # update (PUT) round-trips
    r = c.put("/api/planning/factions/Krakens", json={"name": "Krakens", "trackless": True})
    assert r.status_code == 200
    assert r.json()["trackless"] is True

    # name mismatch → 400
    assert c.put("/api/planning/factions/Krakens", json={"name": "Other"}).status_code == 400

    # missing → 404
    assert c.get("/api/planning/factions/Nope").status_code == 404

    # delete → 204; last entry removed, list reads back empty (not 400)
    assert c.delete("/api/planning/factions/Krakens").status_code == 204
    assert c.get("/api/planning/factions").json() == []


# ── npc lifecycle over HTTP (dossier file must exist for load) ─────────────

def test_npc_http_lifecycle(client):
    c, tmp_path = client
    _touch(tmp_path, "docs/npcs/adabra.md")

    r = c.post("/api/planning/npcs", json={"name": "Adabra", "dossier": "docs/npcs/adabra.md"})
    assert r.status_code == 201

    got = c.get("/api/planning/npcs/Adabra")
    assert got.status_code == 200
    assert got.json()["dossier"].endswith("adabra.md")

    # missing npc → 404
    assert c.get("/api/planning/npcs/Ghost").status_code == 404

    # delete → 204, list empty afterwards
    assert c.delete("/api/planning/npcs/Adabra").status_code == 204
    assert c.get("/api/planning/npcs").json() == []
