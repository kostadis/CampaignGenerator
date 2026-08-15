"""HTTP tests for the isolated players API (``/api/players/*``) — feature 009.

Mirrors ``test_party_routes.py``, including the guard for the double-prefix
regression that has now shipped twice in this codebase: routes mounted at
``/api/<x>/api/<x>/*`` because the router set its own prefix on top of
``include_router``'s.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import players_routes  # noqa: E402


class _StubPlatform:
    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.campaign_dir = Path(campaign_dir)
        self.config_dir = config_dir
        self.config_path_base = self.campaign_dir / self.config_dir


@pytest.fixture
def client(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    app = FastAPI()
    # Mirror main.py: the "/api/players" prefix comes from include_router.
    app.include_router(players_routes.router, prefix="/api/players")
    app.state.platform = _StubPlatform(tmp_path)
    return TestClient(app), tmp_path


def _roster(tmp_path: Path, *names: str) -> None:
    body = "characters:\n" + "".join(
        f"- name: {n}\n  sheet: docs/{n}.md\n" for n in names
    )
    (tmp_path / "config" / "party.yaml").write_text(body, encoding="utf-8")


# ── mounting ─────────────────────────────────────────────────────────────────


def test_routes_mount_at_api_players_not_double_prefixed(client):
    c, _ = client
    assert c.get("/api/players/players").status_code == 200
    assert c.get("/api/players/api/players/players").status_code == 404


def test_router_declares_no_prefix_of_its_own():
    """The lesson planning-isolation.md and party-isolation both record."""
    assert players_routes.router.prefix == ""


# ── status-code contract ─────────────────────────────────────────────────────


def test_empty_roster_is_200_empty_list(client):
    c, _ = client
    r = c.get("/api/players/players")
    assert r.status_code == 200
    assert r.json() == []


def test_post_returns_201(client):
    c, _ = client
    r = c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    assert r.status_code == 201
    assert r.json()["id"] == "wade"


def test_post_duplicate_id_is_409(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    r = c.post("/api/players/players", json={"id": "wade", "name": "Other"})
    assert r.status_code == 409


def test_post_duplicate_display_name_is_409(client):
    c, _ = client
    c.post("/api/players/players",
           json={"id": "a", "name": "A", "display_names": ["Wade"]})
    r = c.post("/api/players/players",
               json={"id": "b", "name": "B", "display_names": ["Wade"]})
    assert r.status_code == 409
    assert "Wade" in r.json()["detail"]


def test_get_one_is_200_and_unknown_is_404(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    assert c.get("/api/players/players/wade").status_code == 200
    assert c.get("/api/players/players/nobody").status_code == 404


def test_put_one_updates(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    r = c.put("/api/players/players/wade",
              json={"id": "wade", "name": "Wade Brown",
                    "display_names": ["wbrown"]})
    assert r.status_code == 200
    assert r.json()["display_names"] == ["wbrown"]


def test_put_one_with_mismatched_id_is_400(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    r = c.put("/api/players/players/wade", json={"id": "other", "name": "X"})
    assert r.status_code == 400


def test_delete_is_204_then_404(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "wade", "name": "Wade Brown"})
    assert c.delete("/api/players/players/wade").status_code == 204
    assert c.delete("/api/players/players/wade").status_code == 404


def test_put_all_replaces_and_preserves_order(client):
    c, _ = client
    r = c.put("/api/players/players", json=[
        {"id": "c", "name": "C"}, {"id": "a", "name": "A"}, {"id": "b", "name": "B"},
    ])
    assert r.status_code == 200
    assert [p["id"] for p in r.json()] == ["c", "a", "b"]


def test_put_all_empty_empties_the_roster(client):
    c, _ = client
    c.post("/api/players/players", json={"id": "a", "name": "A"})
    assert c.put("/api/players/players", json=[]).json() == []
    assert c.get("/api/players/players").json() == []


def test_a_body_that_is_not_a_player_is_422(client):
    c, _ = client
    assert c.post("/api/players/players", json={"name": "no id"}).status_code == 422


def test_an_unknown_body_field_is_rejected(client):
    """extra='forbid' reaches the API surface, not only the file."""
    c, _ = client
    r = c.post("/api/players/players",
               json={"id": "a", "name": "A", "zoom_handle": "x"})
    assert r.status_code == 422


# ── the problems array (FR-016, FR-017) ──────────────────────────────────────


def test_every_player_carries_a_problems_array(client):
    c, tmp = client
    _roster(tmp, "Soma")
    r = c.post("/api/players/players",
               json={"id": "wade", "name": "Wade Brown",
                     "display_names": ["Wade"], "plays": ["Soma"]})
    assert r.json()["problems"] == []


def test_an_unresolved_binding_is_reported_and_the_save_succeeds(client):
    c, tmp = client
    _roster(tmp, "Soma")
    r = c.post("/api/players/players",
               json={"id": "wade", "name": "Wade Brown",
                     "display_names": ["Wade"], "plays": ["Ghost"]})
    assert r.status_code == 201
    problem = r.json()["problems"][0]
    assert problem["kind"] == "unknown_character"
    assert problem["value"] == "Ghost"


def test_no_selection_routes_exist(client):
    """Every sibling service has /selection; this one deliberately does not —
    it spends no tokens, so it has no model or backend override to carry."""
    c, _ = client
    assert c.get("/api/players/selection").status_code == 404


# ── the check route ──────────────────────────────────────────────────────────


def test_check_route_is_mounted(client):
    """Wired in US1, filled in with US5. It must exist and must never write."""
    c, _ = client
    assert c.get("/api/players/check").status_code in (200, 501)
