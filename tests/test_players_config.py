"""Round-trip and refusal tests for campaignlib/players_config.py.

Same failure mode the party-roster tests exist for: the loader and the saver
both **hand-build** their dict rather than dumping the model, so a newly added
field is silently dropped unless it is named in both. ``party.yaml``'s
``selection`` went through that door once already — the write returned success
and persisted nothing.

The refusal tests carry more weight than usual here. Two of them —
``FR-005a`` (duplicate id) and ``FR-005b`` (a display name under two players) —
are the whole reason this document can be trusted as a speaker map: a duplicate
display name would leave ``normalize_vtt_speakers`` with two valid answers and
no way to choose, which is precisely the silent misattribution feature 009
exists to remove.
"""

import sys
import textwrap
from pathlib import Path

import pytest

# The editable-install .pth hardcodes the main checkout, so a worktree can
# import main's copy of campaignlib. Insert the repo root first (research D16).
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from campaignlib.players_config import (  # noqa: E402
    PLAYERS_CONFIG_FILENAME,
    Player,
    PlayersConfig,
    load_players_config,
    save_players_config,
    speaker_map,
)
from campaignlib.party_config import PartyCharacter, PartyConfig  # noqa: E402


# ── shape ────────────────────────────────────────────────────────────────────


def test_the_filename_is_declared_once():
    assert PLAYERS_CONFIG_FILENAME == "players.yaml"


def test_every_field_survives_a_save_load_round_trip(tmp_path):
    """The guard. Both ends hand-build; a field named in only one is lost."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    save_players_config(path, PlayersConfig(players=[
        Player(
            id="ben",
            name="Ben Pfaff",
            display_names=["Ben Pfaff", "ben.pfaff"],
            plays=["Gyrgum"],
            dndbeyond_id="67390528",
        ),
        Player(id="kostadis", name="Kostadis Roussos",
               display_names=["Kostadis Roussos"], plays=["Calmer"], gm=True),
        Player(id="gabe", name="Gabe", display_names=["Gabe"],
               plays=["Zalthir"], active=False),
    ]))

    reloaded = load_players_config(path)
    assert [p.id for p in reloaded.players] == ["ben", "kostadis", "gabe"]
    assert reloaded.players[0].display_names == ["Ben Pfaff", "ben.pfaff"]
    assert reloaded.players[0].plays == ["Gyrgum"]
    assert reloaded.players[0].dndbeyond_id == "67390528"
    assert reloaded.players[1].gm is True
    assert reloaded.players[2].active is False


def test_display_name_order_is_preserved(tmp_path):
    """FR-003. The order is authored, and Phandalin's Wade went from `Wade` to
    `Wade Brown` mid-campaign — the old label still has to work."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    save_players_config(path, PlayersConfig(players=[
        Player(id="wade", name="Wade Brown",
               display_names=["Wade", "Wade Brown"], plays=["Soma"]),
    ]))
    assert load_players_config(path).players[0].display_names == ["Wade", "Wade Brown"]


def test_defaults_are_omitted_on_save(tmp_path):
    """FR-010: a round-trip may not rewrite what the GM authored. Stamping
    `gm: false` and `active: true` onto every row is a rewrite."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    save_players_config(path, PlayersConfig(players=[
        Player(id="wade", name="Wade Brown"),
    ]))
    written = path.read_text(encoding="utf-8")
    assert "gm:" not in written
    assert "active:" not in written
    assert "dndbeyond_id" not in written
    assert "display_names" not in written
    assert "plays" not in written


def test_the_document_is_written_atomically(tmp_path):
    """A crash mid-write leaves the previous document, not a truncated one."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    save_players_config(path, PlayersConfig(players=[Player(id="a", name="A")]))
    save_players_config(path, PlayersConfig(players=[Player(id="b", name="B")]))
    assert [p.id for p in load_players_config(path).players] == ["b"]
    assert not list(tmp_path.glob("*.tmp.*"))


# ── empty and absent are not errors ──────────────────────────────────────────


def test_absent_file_reads_back_empty(tmp_path):
    """FR-009, and the 'an emptied file reads back as 400' bug that
    docs/config/planning-isolation.md had to fix twice."""
    assert load_players_config(tmp_path / "nope.yaml").players == []


def test_empty_file_reads_back_empty(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("", encoding="utf-8")
    assert load_players_config(path).players == []


def test_null_document_reads_back_empty(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("---\n", encoding="utf-8")
    assert load_players_config(path).players == []


def test_an_emptied_roster_round_trips(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    save_players_config(path, PlayersConfig())
    assert load_players_config(path).players == []


# ── refusals ─────────────────────────────────────────────────────────────────


def test_top_level_must_be_a_mapping(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("- ben\n- wade\n", encoding="utf-8")
    with pytest.raises(ValueError, match="top level must be a mapping"):
        load_players_config(path)


def test_malformed_yaml_names_the_file(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("players: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_players_config(path)


def test_a_missing_id_is_refused(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("players:\n- name: Ben Pfaff\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'id'"):
        load_players_config(path)


def test_a_blank_name_is_refused(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("players:\n- id: ben\n  name: '  '\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'name'"):
        load_players_config(path)


def test_a_duplicate_id_is_refused_naming_both(tmp_path):
    """FR-005a."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text(textwrap.dedent("""\
        players:
        - id: wade
          name: Wade Brown
        - id: wade
          name: Wade Other
    """), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_players_config(path)
    assert "wade" in str(exc.value)
    assert "Wade Brown" in str(exc.value)
    assert "Wade Other" in str(exc.value)


def test_a_display_name_under_two_players_is_refused(tmp_path):
    """FR-005b — the rule that makes the speaker map unambiguous. The message
    must name both players and the shared value."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text(textwrap.dedent("""\
        players:
        - id: kostadis
          name: Kostadis Roussos
          display_names: [kostadis1]
        - id: nicholas
          name: Nicholas Roussos
          display_names: [ncroussos, kostadis1]
    """), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_players_config(path)
    msg = str(exc.value)
    assert "kostadis1" in msg
    assert "kostadis" in msg
    assert "nicholas" in msg


def test_display_name_collision_is_case_and_space_insensitive(tmp_path):
    """A transcript label is matched exactly, but two rows differing only by
    case are still one label for a human, and refusing is the safe direction."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text(textwrap.dedent("""\
        players:
        - id: a
          name: A
          display_names: [Wade Brown]
        - id: b
          name: B
          display_names: ['  wade brown ']
    """), encoding="utf-8")
    with pytest.raises(ValueError, match="display name"):
        load_players_config(path)


def test_one_player_may_hold_the_same_display_name_twice(tmp_path):
    """Only a collision *between* players is a conflict. A duplicate inside one
    player's own list is noise, not ambiguity."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text(textwrap.dedent("""\
        players:
        - id: wade
          name: Wade Brown
          display_names: [Wade, Wade]
    """), encoding="utf-8")
    assert load_players_config(path).players[0].display_names == ["Wade", "Wade"]


def test_an_unknown_key_names_itself_and_the_entry(tmp_path):
    """FR-008: extra='forbid'. Silently dropping a key the GM still cares about
    is the failure mode the strict-config effort exists to remove."""
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text(textwrap.dedent("""\
        players:
        - id: wade
          name: Wade Brown
          zoom_handle: wbrown
    """), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_players_config(path)
    assert "zoom_handle" in str(exc.value)


def test_an_unknown_root_key_is_refused(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("players: []\nselection: {}\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_players_config(path)
    assert "selection" in str(exc.value)


def test_players_must_be_a_list(tmp_path):
    path = tmp_path / PLAYERS_CONFIG_FILENAME
    path.write_text("players: ben\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        load_players_config(path)


# ── speaker_map (FR-020, FR-021a) ────────────────────────────────────────────


def _party(*names: str) -> PartyConfig:
    return PartyConfig(characters=[
        PartyCharacter(name=n, sheet=f"docs/{n}.md") for n in names
    ])


def test_every_display_name_resolves_to_the_character():
    """FR-020: all of them, not one."""
    players = PlayersConfig(players=[
        Player(id="wade", name="Wade Brown",
               display_names=["Wade", "Wade Brown", "wbrown"], plays=["Soma"]),
    ])
    assert speaker_map(players, _party("Soma")) == {
        "Wade": "Soma", "Wade Brown": "Soma", "wbrown": "Soma",
    }


def test_the_game_master_label_always_wins():
    """FR-021a. toee's Calmer is a GM-played PC. Labelling that person's lines
    with the character name would attribute narration and NPC speech to a PC."""
    players = PlayersConfig(players=[
        Player(id="kostadis", name="Kostadis Roussos",
               display_names=["Kostadis Roussos", "kostadis1"],
               plays=["Calmer"], gm=True),
        Player(id="wade", name="Wade Brown",
               display_names=["Wade"], plays=["Zinnia"]),
    ])
    mapped = speaker_map(players, _party("Calmer", "Zinnia"))
    assert mapped["Kostadis Roussos"] == "GM"
    assert mapped["kostadis1"] == "GM"
    assert "Calmer" not in mapped.values()
    assert mapped["Wade"] == "Zinnia"


def test_an_inactive_players_labels_still_resolve():
    """FR-011a: the transcript archive still carries their label."""
    players = PlayersConfig(players=[
        Player(id="gabe", name="Gabe", display_names=["Gabe"],
               plays=["Zalthir"], active=False),
    ])
    assert speaker_map(players, _party("Zalthir")) == {"Gabe": "Zalthir"}


def test_a_player_with_no_characters_contributes_nothing():
    players = PlayersConfig(players=[
        Player(id="obs", name="Observer", display_names=["Obs"]),
    ])
    assert speaker_map(players, _party("Soma")) == {}


def test_a_player_with_no_display_names_contributes_nothing():
    """Hillsfar records a placeholder for all four characters. Legitimate."""
    players = PlayersConfig(players=[
        Player(id="wade", name="Wade Brown", plays=["Soma"]),
    ])
    assert speaker_map(players, _party("Soma")) == {}


def test_a_binding_to_an_unknown_character_is_skipped_not_invented():
    """FR-025: the map never asserts an identity the roster does not have."""
    players = PlayersConfig(players=[
        Player(id="wade", name="Wade Brown", display_names=["Wade"],
               plays=["Ghost"]),
    ])
    assert speaker_map(players, _party("Soma")) == {}
