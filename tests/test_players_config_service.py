"""Tests for PlayersConfigService — feature 009, user story 1.

Mirrors ``test_party_config_service.py``, plus the two things specific to this
service:

* **the lenient/strict split.** Shape and identity are refused (a duplicate id,
  a display name held by two players); *references* are reported and never
  block a write, because the GM must be able to bind a player to a character
  they are about to add.
* **``replace_all``** — the page edits the roster as a unit and row order is
  meaningful, so the whole document is written once rather than through a
  delete-all-then-recreate loop that leaves the file momentarily empty.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campaignlib.players_config import Player, load_players_config  # noqa: E402
from server.players_config_service import PlayersConfigService  # noqa: E402


class _StubPlatform:
    """``config_path_base`` (where players.yaml lives) and ``campaign_dir``
    (what party.yaml's paths resolve against) — deliberately different."""

    def __init__(self, campaign_dir: Path, config_dir: str = "config"):
        self.campaign_dir = Path(campaign_dir)
        self.config_path_base = Path(campaign_dir) / config_dir


def _service(tmp_path: Path) -> PlayersConfigService:
    (tmp_path / "config").mkdir(exist_ok=True)
    return PlayersConfigService(_StubPlatform(tmp_path))


def _roster(tmp_path: Path, *names: str) -> None:
    """Write a party.yaml so bindings have something to resolve against."""
    (tmp_path / "config").mkdir(exist_ok=True)
    body = "characters:\n" + "".join(
        f"- name: {n}\n  sheet: docs/{n}.md\n" for n in names
    )
    (tmp_path / "config" / "party.yaml").write_text(body, encoding="utf-8")


# ── empty / missing ──────────────────────────────────────────────────────────


def test_missing_file_reads_as_empty(tmp_path):
    assert _service(tmp_path).get_players() == []


def test_emptied_file_reads_as_empty_not_400(tmp_path):
    """The bug planning-isolation.md had to fix twice: deleting the last entry
    wrote a document the strict loader rejected, so the next GET was a 400."""
    svc = _service(tmp_path)
    svc.create_player(Player(id="wade", name="Wade Brown"))
    svc.delete_player("wade")
    assert svc.get_players() == []


def test_malformed_yaml_is_400(tmp_path):
    svc = _service(tmp_path)
    (tmp_path / "config" / "players.yaml").write_text("players: [oops\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        svc.get_players()
    assert exc.value.status_code == 400


def test_unknown_key_is_400_naming_the_key(tmp_path):
    svc = _service(tmp_path)
    (tmp_path / "config" / "players.yaml").write_text(
        "players:\n- id: wade\n  name: Wade\n  zoom: wb\n", encoding="utf-8"
    )
    with pytest.raises(HTTPException) as exc:
        svc.get_players()
    assert exc.value.status_code == 400
    assert "zoom" in exc.value.detail


# ── CRUD ─────────────────────────────────────────────────────────────────────


def test_create_then_read_back(tmp_path):
    svc = _service(tmp_path)
    svc.create_player(Player(id="wade", name="Wade Brown",
                             display_names=["Wade", "Wade Brown"]))
    got = svc.get_players()
    assert [p["id"] for p in got] == ["wade"]
    assert got[0]["display_names"] == ["Wade", "Wade Brown"]


def test_create_duplicate_id_is_409(tmp_path):
    svc = _service(tmp_path)
    svc.create_player(Player(id="wade", name="Wade Brown"))
    with pytest.raises(HTTPException) as exc:
        svc.create_player(Player(id="wade", name="Wade Other"))
    assert exc.value.status_code == 409


def test_create_duplicate_display_name_is_409_naming_both(tmp_path):
    """FR-005b — the refusal that keeps the speaker map unambiguous."""
    svc = _service(tmp_path)
    svc.create_player(Player(id="kostadis", name="Kostadis Roussos",
                             display_names=["kostadis1"]))
    with pytest.raises(HTTPException) as exc:
        svc.create_player(Player(id="nicholas", name="Nicholas Roussos",
                                 display_names=["kostadis1"]))
    assert exc.value.status_code == 409
    assert "kostadis1" in exc.value.detail


def test_get_unknown_player_is_404(tmp_path):
    with pytest.raises(HTTPException) as exc:
        _service(tmp_path).get_player("nobody")
    assert exc.value.status_code == 404


def test_update_renames_nothing_and_400s_on_id_mismatch(tmp_path):
    svc = _service(tmp_path)
    svc.create_player(Player(id="wade", name="Wade Brown"))
    with pytest.raises(HTTPException) as exc:
        svc.update_player("wade", Player(id="other", name="Wade Brown"))
    assert exc.value.status_code == 400


def test_update_persists(tmp_path):
    svc = _service(tmp_path)
    svc.create_player(Player(id="wade", name="Wade Brown"))
    svc.update_player("wade", Player(id="wade", name="Wade Brown",
                                     display_names=["wbrown"]))
    assert svc.get_player("wade")["display_names"] == ["wbrown"]


def test_delete_unknown_is_404(tmp_path):
    with pytest.raises(HTTPException) as exc:
        _service(tmp_path).delete_player("nobody")
    assert exc.value.status_code == 404


# ── replace_all ──────────────────────────────────────────────────────────────


def test_replace_all_preserves_row_order(tmp_path):
    """Row order is a real edit the page must be able to make, and per-row CRUD
    cannot express it."""
    svc = _service(tmp_path)
    svc.replace_all([
        Player(id="c", name="C"), Player(id="a", name="A"), Player(id="b", name="B"),
    ])
    assert [p["id"] for p in svc.get_players()] == ["c", "a", "b"]


def test_replace_all_is_one_write(tmp_path):
    """Not a delete-all-then-recreate loop — the file is never momentarily
    empty, and no .tmp file survives."""
    svc = _service(tmp_path)
    svc.replace_all([Player(id="a", name="A"), Player(id="b", name="B")])
    assert not list((tmp_path / "config").glob("*.tmp.*"))
    assert len(load_players_config(tmp_path / "config" / "players.yaml").players) == 2


def test_replace_all_rejects_duplicate_ids(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.replace_all([Player(id="a", name="A"), Player(id="a", name="Other")])
    assert exc.value.status_code == 409


def test_replace_all_rejects_a_shared_display_name(tmp_path):
    svc = _service(tmp_path)
    with pytest.raises(HTTPException) as exc:
        svc.replace_all([
            Player(id="a", name="A", display_names=["Wade"]),
            Player(id="b", name="B", display_names=["wade"]),
        ])
    assert exc.value.status_code == 409


def test_replace_all_with_an_empty_list_empties_the_roster(tmp_path):
    svc = _service(tmp_path)
    svc.create_player(Player(id="a", name="A"))
    assert svc.replace_all([]) == []
    assert svc.get_players() == []


# ── the lenient half: problems are reported, never refused (FR-017) ──────────


def test_binding_to_an_unknown_character_saves_and_reports(tmp_path):
    """The GM must be able to name a character they are about to add."""
    svc = _service(tmp_path)
    _roster(tmp_path, "Soma")
    saved = svc.create_player(Player(id="wade", name="Wade Brown",
                                     display_names=["Wade"], plays=["Ghost"]))
    kinds = [p["kind"] for p in saved["problems"]]
    assert "unknown_character" in kinds
    assert svc.get_player("wade")["name"] == "Wade Brown"


def test_a_known_character_produces_no_problem(tmp_path):
    svc = _service(tmp_path)
    _roster(tmp_path, "Soma")
    saved = svc.create_player(Player(id="wade", name="Wade Brown",
                                     display_names=["Wade"], plays=["Soma"]))
    assert saved["problems"] == []


def test_no_display_name_is_reported_not_refused(tmp_path):
    """Hillsfar records a placeholder for all four characters — legitimate, and
    worth saying out loud because that player resolves in no transcript."""
    svc = _service(tmp_path)
    _roster(tmp_path, "Soma")
    saved = svc.create_player(Player(id="wade", name="Wade Brown", plays=["Soma"]))
    assert [p["kind"] for p in saved["problems"]] == ["no_display_name"]


def test_problems_survive_an_absent_party_yaml(tmp_path):
    """A campaign with no roster yet must not 500 the Players page."""
    svc = _service(tmp_path)
    saved = svc.create_player(Player(id="wade", name="Wade Brown",
                                     display_names=["Wade"], plays=["Soma"]))
    assert [p["kind"] for p in saved["problems"]] == ["unknown_character"]


def test_problems_survive_an_unloadable_party_yaml(tmp_path):
    """obelisk's party.yaml does not load at all (research M2). The Players
    page must still work — reporting, not crashing."""
    svc = _service(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "party.yaml").write_text(
        "characters:\n- name: Zenvon Forepot\n", encoding="utf-8"
    )
    saved = svc.create_player(Player(id="a", name="A", display_names=["A"],
                                     plays=["Zenvon Forepot"]))
    assert saved["id"] == "a"
    assert isinstance(saved["problems"], list)
