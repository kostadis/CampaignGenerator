"""Tests for the one-shot ``server/migrate_players_config`` CLI — feature 009.

Mirrors ``test_migrate_grounding_config.py``. The rule that matters most is the
one it shares with every migration in this repo and applies harder:

    **A conflict is reported, never resolved.**

Where two sources disagree about who plays a character, both values and their
origins are printed and neither is written. Choosing between them is
attribution — a precision decision, and the GM's. A merge rule here would be
the "LLM structures" step the repo's pipeline rule forbids, done in Python
instead of a prompt, which is no better.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.migrate_players_config import main  # noqa: E402


def _campaign(tmp_path: Path, party: str, *, session_doc: str | None = None,
              sheets: dict[str, str] | None = None,
              voice: tuple[str, ...] = (),
              examples: tuple[str, ...] = ()) -> Path:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "config" / "party.yaml").write_text(
        textwrap.dedent(party), encoding="utf-8")
    if session_doc is not None:
        (tmp_path / "config" / "session_doc.yaml").write_text(
            textwrap.dedent(session_doc), encoding="utf-8")
    for name, player in (sheets or {}).items():
        (tmp_path / "docs" / f"{name}.md").write_text(
            f"---\nname: {name}\nplayer: {player}\nspecies: Human\n"
            f"class_level: Rogue 4\n---\n# {name}\n", encoding="utf-8")
    for rel in voice:
        p = tmp_path / "voice" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("spec\n", encoding="utf-8")
    for rel in examples:
        p = tmp_path / "examples" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("style\n", encoding="utf-8")
    return tmp_path


def _players(campaign: Path) -> dict:
    return yaml.safe_load(
        (campaign / "config" / "players.yaml").read_text(encoding="utf-8"))


def _party(campaign: Path) -> dict:
    return yaml.safe_load(
        (campaign / "config" / "party.yaml").read_text(encoding="utf-8"))


PHANDALIN_SHAPE = """\
    characters:
    - name: Soma
      sheet: docs/Soma.md
      player: Wade Brown
    - name: Vukradin
      sheet: docs/Vukradin.md
      player: David Mendenhall
"""


# ── harvesting ──────────────────────────────────────────────────────────────


def test_players_are_drafted_from_the_roster(tmp_path):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE)
    assert main(["--campaign-dir", str(campaign)]) == 0

    players = _players(campaign)["players"]
    assert [p["name"] for p in players] == ["Wade Brown", "David Mendenhall"]
    assert players[0]["plays"] == ["Soma"]
    assert players[0]["display_names"] == ["Wade Brown"]


def test_the_gm_is_harvested_from_session_doc(tmp_path):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE, session_doc="""\
        roster:
          characters: Soma, Vukradin
          gm_player: Kostadis Roussos
    """)
    main(["--campaign-dir", str(campaign)])
    gm = [p for p in _players(campaign)["players"] if p.get("gm")]
    assert [p["name"] for p in gm] == ["Kostadis Roussos"]


def test_a_gm_who_also_plays_gets_one_entry_with_both_facts(tmp_path):
    """toee's Calmer. Running the game and playing a PC are independent facts
    about one person, and both are recordable (FR-021a governs which label
    their transcript lines get)."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Calmer
          sheet: docs/Calmer.md
          player: Kostadis Roussos
    """, session_doc="roster:\n  gm_player: Kostadis Roussos\n")
    main(["--campaign-dir", str(campaign)])
    players = _players(campaign)["players"]
    assert len(players) == 1
    assert players[0]["gm"] is True
    assert players[0]["plays"] == ["Calmer"]


def test_a_co_piloted_character_yields_two_players(tmp_path):
    """The `/`-separated field the old stores used for two humans, one PC."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Soma
          sheet: docs/Soma.md
          player: Wade / Gabe
    """)
    main(["--campaign-dir", str(campaign)])
    players = _players(campaign)["players"]
    assert [p["name"] for p in players] == ["Wade", "Gabe"]
    assert all(p["plays"] == ["Soma"] for p in players)


def test_ids_are_unique_when_first_names_collide(tmp_path):
    campaign = _campaign(tmp_path, """\
        characters:
        - name: A
          sheet: docs/A.md
          player: Mike Hall
        - name: B
          sheet: docs/B.md
          player: Mike Jones
    """)
    main(["--campaign-dir", str(campaign)])
    ids = [p["id"] for p in _players(campaign)["players"]]
    assert len(ids) == len(set(ids))


# ── conflicts and placeholders ──────────────────────────────────────────────


def test_a_conflict_is_reported_and_neither_value_written(tmp_path, capsys):
    """toee's real shape: the sheets say the D&D Beyond account handle, the
    roster says the person. Which wins is a GM ruling."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Calmer
          sheet: docs/Calmer.md
          player: Kostadis Roussos
    """, sheets={"Calmer": "kostadis1"})
    main(["--campaign-dir", str(campaign)])

    out = capsys.readouterr().out
    assert "CONFLICTS" in out
    assert "kostadis1" in out
    assert "Kostadis Roussos" in out
    assert _players(campaign)["players"] == []


def test_placeholders_become_no_player_not_a_person(tmp_path):
    """Hillsfar records "(Not specified)" for all four characters. A person
    named "N/A" must never appear in a roster."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Akritas
          sheet: docs/Akritas.md
          player: (Not specified)
    """)
    main(["--campaign-dir", str(campaign)])
    assert _players(campaign)["players"] == []


def test_a_campaign_with_nothing_to_harvest_says_so(tmp_path, capsys):
    """Four of the six campaigns record no player anywhere. An almost-empty
    result there is the correct outcome, and silence would read as a bug."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Vardis
          sheet: docs/Vardis.md
    """)
    assert main(["--campaign-dir", str(campaign)]) == 0
    out = capsys.readouterr().out
    assert "records no player anywhere" in out


# ── declarations ────────────────────────────────────────────────────────────


def test_voice_and_example_declarations_are_proposed(tmp_path):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE,
                         voice=("soma_new_pipeline.md", "vukradin_voice.md"),
                         examples=("soma.md", "vukradin.md"))
    main(["--campaign-dir", str(campaign)])

    by_name = {c["name"]: c for c in _party(campaign)["characters"]}
    assert by_name["Soma"]["voice"] == "voice/soma_new_pipeline.md"
    assert by_name["Vukradin"]["voice"] == "voice/vukradin_voice.md"
    assert by_name["Soma"]["examples"] == "examples/soma.md"


def test_files_attributed_to_nobody_are_listed_for_a_ruling(tmp_path, capsys):
    """OOTA's `vizeran_voice.md` is an NPC's; stormgiants' `thistl.md` is a
    typo. The tool cannot tell them apart, so it lists both."""
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE,
                         voice=("vizeran_voice.md",),
                         examples=("house_style.md",))
    main(["--campaign-dir", str(campaign)])

    out = capsys.readouterr().out
    assert "attributed to nobody" in out
    assert "vizeran_voice.md" in out
    assert "house_style.md" in out
    # Listed, never WRITTEN. "This file matched no character" and "this file
    # belongs to the whole campaign" are the same observation, and writing the
    # second from the first is the fall-through feature 009 deleted — it is how
    # stormgiants' typo'd `thistl.md` reached all four narrators.
    assert "shared_examples" not in _party(campaign)
    # A ready-to-paste block instead, so the GM's ruling is one copy away.
    assert "shared_examples:" in out


# ── retirement ──────────────────────────────────────────────────────────────


def test_the_player_field_is_removed_from_the_roster(tmp_path):
    """FR-036: migrate-and-delete. A location that still parses is a split
    brain waiting to happen."""
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE)
    main(["--campaign-dir", str(campaign)])
    assert all("player" not in c for c in _party(campaign)["characters"])


def test_the_roster_group_is_removed_from_session_doc(tmp_path):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE, session_doc="""\
        roster:
          characters: Soma, Vukradin
          gm_player: Kostadis Roussos
        narrate:
          tokens: 16000
    """)
    main(["--campaign-dir", str(campaign)])
    on_disk = yaml.safe_load(
        (campaign / "config" / "session_doc.yaml").read_text(encoding="utf-8"))
    assert "roster" not in on_disk
    assert on_disk["narrate"]["tokens"] == 16000      # nothing else disturbed


def test_the_three_state_arc_score_survives(tmp_path):
    """`arc_score: null` means "trackless by design" and is a different
    document from the key being absent. Rewriting party.yaml must not flatten
    them together."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Soma
          sheet: docs/Soma.md
          player: Wade
          arc_score: null
        - name: Vukradin
          sheet: docs/Vukradin.md
          player: Dave
    """)
    main(["--campaign-dir", str(campaign)])
    chars = _party(campaign)["characters"]
    assert "arc_score" in chars[0] and chars[0]["arc_score"] is None
    assert "arc_score" not in chars[1]


# ── refusals ────────────────────────────────────────────────────────────────


def test_refuses_to_overwrite_without_force(tmp_path, capsys):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE)
    (campaign / "config" / "players.yaml").write_text(
        "players:\n- id: keep\n  name: Keep Me\n", encoding="utf-8")

    assert main(["--campaign-dir", str(campaign)]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err
    assert _players(campaign)["players"][0]["id"] == "keep"


def test_force_overwrites(tmp_path):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE)
    (campaign / "config" / "players.yaml").write_text(
        "players:\n- id: keep\n  name: Keep Me\n", encoding="utf-8")

    assert main(["--campaign-dir", str(campaign), "--force"]) == 0
    assert [p["name"] for p in _players(campaign)["players"]] == [
        "Wade Brown", "David Mendenhall"]


def test_refuses_a_party_yaml_that_is_a_bare_name_list(tmp_path, capsys):
    """obelisk. Its config/party.yaml is a PC-name exclusion list for the
    entity registry — two readers, two contracts, one filename. Which use wins
    is a GM ruling, so this refuses by name rather than inventing a roster."""
    campaign = _campaign(tmp_path, """\
        characters:
        - name: Zenvon Forepot
        - name: Veyra
    """)
    assert main(["--campaign-dir", str(campaign)]) == 1
    err = capsys.readouterr().err
    assert "exclusion list" in err
    assert not (campaign / "config" / "players.yaml").exists()


def test_refuses_when_there_is_no_roster_at_all(tmp_path, capsys):
    (tmp_path / "config").mkdir()
    assert main(["--campaign-dir", str(tmp_path)]) == 1
    assert "nothing to adopt" in capsys.readouterr().err


def test_unrecognised_roster_keys_are_reported_not_dropped_silently(tmp_path, capsys):
    campaign = _campaign(tmp_path, PHANDALIN_SHAPE, session_doc="""\
        roster:
          characters: Soma
          something_else: value
    """)
    main(["--campaign-dir", str(campaign)])
    assert "something_else" in capsys.readouterr().out
