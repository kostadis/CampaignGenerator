"""Tests for PartyConfigService — Phase 5 of docs/config/grounding-isolation.md.

Replaces tests/test_party_yaml_route.py, which covered the deleted
``/api/config/party-yaml`` pair. Mirrors test_planning_config_service.py,
plus the two things that are specific to this service: the D4 lenient-save
contract (``missing_files``) and the whole-roster ``replace_all`` write.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campaignlib.party_config import (  # noqa: E402
    PartyCharacter,
    PartyConfig,
    load_party_config,
    save_party_config,
)
from server.party_config_service import PartyConfigService  # noqa: E402


class _StubPlatform:
    """Exposes the two attributes the service reads: ``config_path_base``
    (where party.yaml lives) and ``campaign_dir`` (what its paths resolve
    against). Those are deliberately different directories — conflating them
    is the bug Phase 2 fixed."""

    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.campaign_dir = Path(campaign_dir)
        self.config_path_base = Path(campaign_dir) / config_dir


def _service(tmp_path: Path) -> PartyConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    return PartyConfigService(_StubPlatform(tmp_path))


def _touch(tmp_path: Path, rel: str) -> str:
    """Create a file under the campaign root; return its campaign-relative path."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return rel


# ── Empty / missing ────────────────────────────────────────────────────────

def test_missing_file_reads_as_empty(tmp_path):
    assert _service(tmp_path).get_characters() == []


def test_emptied_file_reads_as_empty_not_400(tmp_path):
    """The bug planning-isolation.md had to fix twice: deleting the last entry
    wrote a file the strict loader rejected, so the next GET returned 400."""
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    svc.delete_character("Soma")
    assert svc.get_characters() == []


def test_malformed_yaml_is_400(tmp_path):
    svc = _service(tmp_path)
    svc.party_path.write_text("characters: [oops\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        svc.get_characters()
    assert exc.value.status_code == 400


# ── CRUD contract ──────────────────────────────────────────────────────────

def test_create_and_get(tmp_path):
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    created = svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    assert created["name"] == "Soma"
    # Stored as authored, not resolved to an absolute path.
    assert created["sheet"] == "docs/party/soma.md"
    assert svc.get_character("Soma")["sheet"] == sheet
    assert [c["name"] for c in svc.get_characters()] == ["Soma"]


def test_create_duplicate_is_409(tmp_path):
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    with pytest.raises(HTTPException) as exc:
        svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    assert exc.value.status_code == 409


def test_get_missing_is_404(tmp_path):
    with pytest.raises(HTTPException) as exc:
        _service(tmp_path).get_character("Nobody")
    assert exc.value.status_code == 404


def test_update_replaces_fields(tmp_path):
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    arc = _touch(tmp_path, "docs/tracking/soma.md")
    svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    svc.update_character("Soma", PartyCharacter(name="Soma", sheet=sheet, arc_score=arc))
    assert svc.get_character("Soma")["arc_score"] == arc


def test_update_name_mismatch_is_400(tmp_path):
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    svc.create_character(PartyCharacter(name="Soma", sheet=sheet))
    with pytest.raises(HTTPException) as exc:
        svc.update_character("Soma", PartyCharacter(name="Other", sheet=sheet))
    assert exc.value.status_code == 400


def test_update_missing_is_404(tmp_path):
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    with pytest.raises(HTTPException) as exc:
        svc.update_character("Ghost", PartyCharacter(name="Ghost", sheet=sheet))
    assert exc.value.status_code == 404


def test_delete_missing_is_404(tmp_path):
    with pytest.raises(HTTPException) as exc:
        _service(tmp_path).delete_character("Ghost")
    assert exc.value.status_code == 404


# ── D4: lenient save + missing_files ───────────────────────────────────────

def test_save_succeeds_and_reports_missing_file(tmp_path):
    """The GM must be able to name a sheet they are about to write."""
    svc = _service(tmp_path)
    created = svc.create_character(
        PartyCharacter(name="Soma", sheet="docs/party/soma.md")
    )
    assert created["missing_files"] == ["sheet"]
    # ...and it survives a reload, rather than being a save-time-only warning.
    assert svc.get_character("Soma")["missing_files"] == ["sheet"]
    assert svc.party_path.exists()


def test_missing_files_empty_when_all_present(tmp_path):
    svc = _service(tmp_path)
    pc = PartyCharacter(
        name="Soma",
        sheet=_touch(tmp_path, "docs/party/soma.md"),
        backstory=_touch(tmp_path, "docs/back/soma.md"),
        dossier=_touch(tmp_path, "docs/npcs/npc_soma.md"),
        arc_score=_touch(tmp_path, "docs/tracking/soma.md"),
    )
    assert svc.create_character(pc)["missing_files"] == []


def test_missing_files_names_each_absent_field(tmp_path):
    svc = _service(tmp_path)
    pc = PartyCharacter(
        name="Soma",
        sheet=_touch(tmp_path, "docs/party/soma.md"),
        backstory="docs/back/nope.md",
        arc_score="docs/tracking/nope.md",
    )
    assert svc.create_character(pc)["missing_files"] == ["backstory", "arc_score"]


def test_missing_files_resolves_against_campaign_root_not_config_dir(tmp_path):
    """Phase 2's contract. A sheet at <campaign>/docs/... must NOT be reported
    missing just because party.yaml lives in <campaign>/config/."""
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/soma.md")
    assert svc.create_character(
        PartyCharacter(name="Soma", sheet=sheet)
    )["missing_files"] == []


# ── replace_all ────────────────────────────────────────────────────────────

def test_replace_all_overwrites_and_preserves_order(tmp_path):
    svc = _service(tmp_path)
    a = _touch(tmp_path, "docs/party/a.md")
    b = _touch(tmp_path, "docs/party/b.md")
    svc.replace_all([
        PartyCharacter(name="A", sheet=a),
        PartyCharacter(name="B", sheet=b),
    ])
    assert [c["name"] for c in svc.get_characters()] == ["A", "B"]
    # Reordering is a real edit the per-row endpoints cannot express.
    svc.replace_all([
        PartyCharacter(name="B", sheet=b),
        PartyCharacter(name="A", sheet=a),
    ])
    assert [c["name"] for c in svc.get_characters()] == ["B", "A"]


def test_replace_all_rejects_duplicate_names(tmp_path):
    svc = _service(tmp_path)
    a = _touch(tmp_path, "docs/party/a.md")
    with pytest.raises(HTTPException) as exc:
        svc.replace_all([
            PartyCharacter(name="A", sheet=a),
            PartyCharacter(name="A", sheet=a),
        ])
    assert exc.value.status_code == 409


def test_replace_all_with_empty_list_clears_roster(tmp_path):
    svc = _service(tmp_path)
    svc.create_character(
        PartyCharacter(name="A", sheet=_touch(tmp_path, "docs/party/a.md"))
    )
    svc.replace_all([])
    assert svc.get_characters() == []


# ── Three-state arc_score round-trip, through the ONE implementation ───────

def test_arc_score_three_state_round_trip(tmp_path):
    """Absent / null / path are three different documents. This used to be
    encoded twice — once in the validating loader, once in raw YAML inside
    config_routes.py — which is the drift this effort removes."""
    svc = _service(tmp_path)
    sheet = _touch(tmp_path, "docs/party/x.md")
    track = _touch(tmp_path, "docs/tracking/x.md")
    svc.replace_all([
        PartyCharacter(name="Absent", sheet=sheet),
        PartyCharacter(name="Trackless", sheet=sheet, trackless=True),
        PartyCharacter(name="Tracked", sheet=sheet, arc_score=track),
    ])

    raw = yaml.safe_load(svc.party_path.read_text(encoding="utf-8"))
    by_name = {c["name"]: c for c in raw["characters"]}
    assert "arc_score" not in by_name["Absent"]          # key omitted
    assert by_name["Trackless"]["arc_score"] is None     # explicit null
    assert by_name["Tracked"]["arc_score"] == track      # path

    back = {c["name"]: c for c in svc.get_characters()}
    assert back["Absent"]["arc_score"] is None and back["Absent"]["trackless"] is False
    assert back["Trackless"]["arc_score"] is None and back["Trackless"]["trackless"] is True
    assert back["Tracked"]["arc_score"] == track and back["Tracked"]["trackless"] is False


def test_round_trip_preserves_relative_paths(tmp_path):
    """A load/save cycle must not rewrite the GM's relative references as
    absolute machine-specific ones — the bug save_planning_config had."""
    cfg_path = tmp_path / "party.yaml"
    original = "characters:\n  - name: Soma\n    sheet: docs/party/soma.md\n"
    cfg_path.write_text(original, encoding="utf-8")
    save_party_config(cfg_path, load_party_config(cfg_path))
    assert "docs/party/soma.md" in cfg_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in cfg_path.read_text(encoding="utf-8")


def test_save_is_atomic_leaving_no_tmp_file(tmp_path):
    svc = _service(tmp_path)
    svc.create_character(
        PartyCharacter(name="A", sheet=_touch(tmp_path, "docs/party/a.md"))
    )
    assert not list(svc.party_path.parent.glob("*.tmp*"))
