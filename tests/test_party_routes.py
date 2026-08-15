"""HTTP tests for the isolated party API (``/api/party/*``).

Exercises the router as wired in ``server/main.py``. Mirrors
``test_planning_routes.py``, including the guard for the double-prefix
regression that shipped there (routes mounted at ``/api/party/api/party/*``
because the router set its own prefix on top of ``include_router``'s).

Replaces ``tests/test_party_yaml_route.py``, which covered the deleted
``/api/config/party-yaml`` pair.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.routers import party_routes  # noqa: E402


class _StubPlatform:
    """``config_path_base`` (where party.yaml lives) and ``campaign_dir``
    (what its paths resolve against) — deliberately different directories."""

    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.campaign_dir = Path(campaign_dir)
        self.config_dir = config_dir
        self.config_path_base = self.campaign_dir / self.config_dir


@pytest.fixture
def client(tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    app = FastAPI()
    # Mirror main.py: the "/api/party" prefix comes from include_router.
    app.include_router(party_routes.router, prefix="/api/party")
    app.state.platform = _StubPlatform(tmp_path)
    return TestClient(app), tmp_path


def _touch(tmp_path: Path, rel: str) -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return rel


# ── Mounting ───────────────────────────────────────────────────────────────

def test_routes_mount_at_api_party_not_double_prefixed(client):
    c, _ = client
    assert c.get("/api/party/characters").status_code == 200
    assert c.get("/api/party/api/party/characters").status_code == 404


def test_router_declares_no_prefix_of_its_own():
    """The lesson from planning-isolation.md's shipped bug, asserted directly."""
    assert party_routes.router.prefix == ""


# ── Status-code contract ───────────────────────────────────────────────────

def test_empty_roster_is_200_empty_list(client):
    c, _ = client
    r = c.get("/api/party/characters")
    assert r.status_code == 200 and r.json() == []


def test_create_returns_201(client):
    c, tmp = client
    sheet = _touch(tmp, "docs/party/soma.md")
    r = c.post("/api/party/characters", json={"name": "Soma", "sheet": sheet})
    assert r.status_code == 201
    assert r.json()["name"] == "Soma"


def test_duplicate_create_is_409(client):
    c, tmp = client
    sheet = _touch(tmp, "docs/party/soma.md")
    body = {"name": "Soma", "sheet": sheet}
    c.post("/api/party/characters", json=body)
    assert c.post("/api/party/characters", json=body).status_code == 409


def test_get_missing_is_404(client):
    c, _ = client
    assert c.get("/api/party/characters/Nobody").status_code == 404


def test_update_name_mismatch_is_400(client):
    c, tmp = client
    sheet = _touch(tmp, "docs/party/soma.md")
    c.post("/api/party/characters", json={"name": "Soma", "sheet": sheet})
    r = c.put("/api/party/characters/Soma", json={"name": "Other", "sheet": sheet})
    assert r.status_code == 400


def test_delete_returns_204_then_404(client):
    c, tmp = client
    sheet = _touch(tmp, "docs/party/soma.md")
    c.post("/api/party/characters", json={"name": "Soma", "sheet": sheet})
    assert c.delete("/api/party/characters/Soma").status_code == 204
    assert c.delete("/api/party/characters/Soma").status_code == 404


def test_unknown_field_is_rejected(client):
    """PartyCharacter is strict (extra="forbid") — a typo'd key is a 422 at the
    boundary, not silent unvalidated overflow."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/soma.md")
    r = c.post(
        "/api/party/characters",
        json={"name": "Soma", "sheet": sheet, "shet": "typo.md"},
    )
    assert r.status_code == 422


# ── D4 over the wire ───────────────────────────────────────────────────────

def test_save_with_missing_file_is_201_with_report(client):
    c, _ = client
    r = c.post("/api/party/characters", json={"name": "Soma", "sheet": "docs/nope.md"})
    assert r.status_code == 201
    assert r.json()["missing_files"] == ["sheet"]


def test_put_collection_replaces_whole_roster(client):
    c, tmp = client
    a, b = _touch(tmp, "docs/a.md"), _touch(tmp, "docs/b.md")
    r = c.put("/api/party/characters", json=[
        {"name": "A", "sheet": a},
        {"name": "B", "sheet": b},
    ])
    assert r.status_code == 200
    assert [x["name"] for x in r.json()] == ["A", "B"]
    # Replaces, not appends.
    r = c.put("/api/party/characters", json=[{"name": "C", "sheet": a}])
    assert [x["name"] for x in r.json()] == ["C"]


def test_put_collection_duplicate_names_is_409(client):
    c, tmp = client
    a = _touch(tmp, "docs/a.md")
    r = c.put("/api/party/characters", json=[
        {"name": "A", "sheet": a},
        {"name": "A", "sheet": a},
    ])
    assert r.status_code == 409


# ── The declared file fields over the wire (feature 009) ───────────────────

def test_voice_and_examples_round_trip_through_the_collection_put(client):
    """A 200 is not proof. ``save_party_config`` hand-builds its YAML dict, so
    the failure mode this guards is a save that succeeds and persists nothing
    — exactly what happened when ``selection`` was added."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/Soma.md")
    voice = _touch(tmp, "voice/soma_voice.md")
    examples = _touch(tmp, "examples/soma.md")
    r = c.put("/api/party/characters", json=[
        {"name": "Soma", "sheet": sheet, "voice": voice, "examples": examples},
        {"name": "Vukradin", "sheet": sheet},
    ])
    assert r.status_code == 200
    assert [x.get("voice") for x in r.json()] == [voice, None]

    listed = c.get("/api/party/characters").json()
    assert [x.get("examples") for x in listed] == [examples, None]
    # …and it actually reached disk, not just the response model.
    written = (tmp / "config" / "party.yaml").read_text(encoding="utf-8")
    assert f"voice: {voice}" in written
    assert f"examples: {examples}" in written


def test_a_declared_file_that_is_absent_is_reported_not_refused(client):
    """FR-017: the GM must be able to name a file they are about to write."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/Soma.md")
    r = c.put("/api/party/characters", json=[
        {"name": "Soma", "sheet": sheet, "voice": "voice/not_written_yet.md"},
    ])
    assert r.status_code == 200
    assert "voice" in r.json()[0]["missing_files"]


def test_the_retired_player_field_is_rejected(client):
    """FR-013. Accepting and ignoring it would leave the GM believing they had
    recorded who plays Soma."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/Soma.md")
    r = c.put("/api/party/characters",
              json=[{"name": "Soma", "sheet": sheet, "player": "Wade"}])
    assert r.status_code == 422


def test_the_shape_the_editor_holds_is_not_the_shape_the_api_accepts(client):
    """``missing_files`` is server-reported output on the way out and a 422 on
    the way back in, because PartyCharacter is extra="forbid". The roster
    editor loads rows carrying it, so it MUST strip the field before saving —
    otherwise every save from the browser fails and the player field can never
    be persisted. Asserted here so a future round-trip test that hand-builds
    its payload cannot hide it again."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/Soma.md")
    listed = c.put("/api/party/characters",
                   json=[{"name": "Soma", "sheet": sheet}]).json()
    assert "missing_files" in listed[0]

    echoed = c.put("/api/party/characters", json=listed)
    assert echoed.status_code == 422

    stripped = [{k: v for k, v in row.items() if k != "missing_files"}
                for row in listed]
    assert c.put("/api/party/characters", json=stripped).status_code == 200


def test_a_roster_saved_without_player_does_not_grow_the_key(client):
    """FR-008a: additive and optional."""
    c, tmp = client
    sheet = _touch(tmp, "docs/party/Soma.md")
    c.put("/api/party/characters", json=[{"name": "Soma", "sheet": sheet}])
    assert "player" not in (tmp / "config" / "party.yaml").read_text(encoding="utf-8")


def test_old_party_yaml_route_is_gone(tmp_path):
    """GET/PUT /api/config/party-yaml took the target file as a browser-supplied
    parameter. It should not exist any more."""
    from server.routers import config_routes

    paths = {r.path for r in config_routes.router.routes}
    assert "/party-yaml" not in paths
