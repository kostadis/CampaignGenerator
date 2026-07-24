"""Unit tests for PlanningConfigService — the isolated planning.yaml CRUD
service introduced by docs/config/planning-isolation.md.

Covers NPC + faction create/get/update/delete, the 404/409/400 error
contract, the 3-state arc_score round-trip through save/load (which also
exercises save_planning_config, previously untested), and the
"delete the last entry" edge: an emptied planning.yaml must read back as
empty rather than erroring.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.planning_config_service import PlanningConfigService  # noqa: E402
from server.planning_config_shared import (  # noqa: E402
    PlanningConfig,
    PlanningEntry,
    load_planning_config,
    save_planning_config,
)


class _StubPlatform:
    """Minimal stand-in exposing exactly the one attribute
    ``PlanningConfigService`` reads — ``config_path_base`` — since
    docs/config/platform-isolation.md Phase 2 made it compose
    ``PlatformConfigService`` instead of resolving campaign_dir/config_dir
    itself. A real ``PlatformConfigService`` would require a ``config.yaml``
    fixture on disk that these tests don't need."""

    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.config_path_base = Path(campaign_dir) / config_dir


def _service(tmp_path: Path) -> PlanningConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    return PlanningConfigService(_StubPlatform(tmp_path, "config"))


def _touch(tmp_path: Path, rel: str) -> Path:
    """Create <campaign>/config/<rel> so load-time file resolution succeeds."""
    p = tmp_path / "config" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return Path(rel)


# ── empty / missing file ──────────────────────────────────────────────────

def test_empty_campaign_returns_empty_lists(tmp_path):
    svc = _service(tmp_path)
    assert svc.get_npcs() == []
    assert svc.get_factions() == []


# ── NPC CRUD ──────────────────────────────────────────────────────────────

def test_create_and_get_npc(tmp_path):
    svc = _service(tmp_path)
    dossier = _touch(tmp_path, "docs/npcs/adabra.md")
    created = svc.create_npc(PlanningEntry(name="Adabra", dossier=dossier))
    assert created.name == "Adabra"

    got = svc.get_npc("Adabra")
    assert got.name == "Adabra"
    assert got.dossier is not None and got.dossier.name == "adabra.md"
    assert [n.name for n in svc.get_npcs()] == ["Adabra"]


def test_create_duplicate_npc_conflicts(tmp_path):
    svc = _service(tmp_path)
    dossier = _touch(tmp_path, "docs/npcs/adabra.md")
    svc.create_npc(PlanningEntry(name="Adabra", dossier=dossier))
    with pytest.raises(HTTPException) as exc:
        svc.create_npc(PlanningEntry(name="Adabra", dossier=dossier))
    assert exc.value.status_code == 409


def test_get_missing_npc_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.get_npc("Nobody")
    assert exc.value.status_code == 404


def test_update_npc_replaces_arc_score(tmp_path):
    svc = _service(tmp_path)
    dossier = _touch(tmp_path, "docs/npcs/adabra.md")
    arc = _touch(tmp_path, "docs/tracking/adabra.md")
    svc.create_npc(PlanningEntry(name="Adabra", dossier=dossier))
    updated = svc.update_npc(
        "Adabra",
        PlanningEntry(name="Adabra", dossier=dossier, arc_score=arc),
    )
    assert updated.arc_score is not None
    got = svc.get_npc("Adabra")
    assert got.arc_score is not None and got.arc_score.name == "adabra.md"


def test_update_npc_name_mismatch_400(tmp_path):
    svc = _service(tmp_path)
    dossier = _touch(tmp_path, "docs/npcs/adabra.md")
    svc.create_npc(PlanningEntry(name="Adabra", dossier=dossier))
    with pytest.raises(HTTPException) as exc:
        svc.update_npc("Adabra", PlanningEntry(name="Lyra", dossier=dossier))
    assert exc.value.status_code == 400


def test_update_missing_npc_404(tmp_path):
    svc = _service(tmp_path)
    dossier = _touch(tmp_path, "docs/npcs/ghost.md")
    with pytest.raises(HTTPException) as exc:
        svc.update_npc("Ghost", PlanningEntry(name="Ghost", dossier=dossier))
    assert exc.value.status_code == 404


def test_delete_npc_then_missing(tmp_path):
    svc = _service(tmp_path)
    adabra = _touch(tmp_path, "docs/npcs/adabra.md")
    lyra = _touch(tmp_path, "docs/npcs/lyra.md")
    svc.create_npc(PlanningEntry(name="Adabra", dossier=adabra))
    svc.create_npc(PlanningEntry(name="Lyra", dossier=lyra))
    svc.delete_npc("Adabra")
    assert [n.name for n in svc.get_npcs()] == ["Lyra"]
    with pytest.raises(HTTPException) as exc:
        svc.get_npc("Adabra")
    assert exc.value.status_code == 404


def test_delete_missing_npc_404(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.delete_npc("Nobody")
    assert exc.value.status_code == 404


# ── Faction CRUD (name-only, no file refs) ─────────────────────────────────

def test_faction_crud_lifecycle(tmp_path):
    svc = _service(tmp_path)
    svc.create_faction(PlanningEntry(name="Krakens"))
    assert [f.name for f in svc.get_factions()] == ["Krakens"]
    assert svc.get_faction("Krakens").name == "Krakens"

    with pytest.raises(HTTPException) as dup:
        svc.create_faction(PlanningEntry(name="Krakens"))
    assert dup.value.status_code == 409

    svc.create_faction(PlanningEntry(name="Splinters"))
    svc.delete_faction("Krakens")
    assert [f.name for f in svc.get_factions()] == ["Splinters"]
    with pytest.raises(HTTPException) as missing:
        svc.get_faction("Krakens")
    assert missing.value.status_code == 404


# ── delete-the-last-entry edge (empty file must read back empty) ───────────

def test_delete_last_entry_reads_back_empty(tmp_path):
    svc = _service(tmp_path)
    svc.create_faction(PlanningEntry(name="Onlyone"))
    svc.delete_faction("Onlyone")
    # Before the _load empty-file fix this raised 400 ("must define a
    # non-empty 'npcs' or 'factions' list").
    assert svc.get_factions() == []
    assert svc.get_npcs() == []


# ── save/load 3-state arc_score round-trip (exercises save_planning_config) ─

def test_save_load_arc_score_three_state(tmp_path):
    track = tmp_path / "echoes.md"
    track.write_text("x", encoding="utf-8")
    cfg_path = tmp_path / "planning.yaml"

    config = PlanningConfig(factions=[
        PlanningEntry(name="Absent"),                         # key omitted
        PlanningEntry(name="Trackless", trackless=True),      # arc_score: null
        PlanningEntry(name="Tracked", arc_score=track.resolve()),  # path
    ])
    save_planning_config(cfg_path, config)

    text = cfg_path.read_text(encoding="utf-8")
    assert "arc_score: null" in text  # the explicit-trackless entry

    reloaded = {f.name: f for f in load_planning_config(cfg_path).factions}
    assert reloaded["Absent"].arc_score is None and reloaded["Absent"].trackless is False
    assert reloaded["Trackless"].arc_score is None and reloaded["Trackless"].trackless is True
    assert reloaded["Tracked"].arc_score == track.resolve()
    assert reloaded["Tracked"].trackless is False
