"""Tests for ``players check`` — feature 009, user story 5.

Every failure this feature exists to remove was silent. This is where they
become a list you read before spending a token.

The finding that earns its keep is the last one: **a display name absent from
this transcript**. The wrong-VTT pre-flight in ``scene_extract`` and
``enhance_summary`` fires only when *zero* expected names match, so it catches
the whole map being wrong and misses three-of-four matching while the fourth
vanishes — and the second case is the one that has actually happened.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipelines.workspace.players import collect_findings, main  # noqa: E402


def _campaign(tmp_path: Path, *, players: str, party: str,
              voice: tuple[str, ...] = (), examples: tuple[str, ...] = ()) -> Path:
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "config" / "players.yaml").write_text(
        textwrap.dedent(players), encoding="utf-8")
    (tmp_path / "config" / "party.yaml").write_text(
        textwrap.dedent(party), encoding="utf-8")
    for rel in voice:
        p = tmp_path / "voice" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("spec\n", encoding="utf-8")
    for rel in examples:
        p = tmp_path / "examples" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("style\n", encoding="utf-8")
    return tmp_path


COHERENT_PLAYERS = """\
    players:
    - id: ben
      name: Ben Pfaff
      display_names: [Ben Pfaff]
      plays: [Gyrgum]
"""

COHERENT_PARTY = """\
    characters:
    - name: Gyrgum
      sheet: docs/Gyrgum.md
      voice: voice/gyrgum_voice.md
      examples: examples/gyrgum.md
"""


def _coherent(tmp_path: Path) -> Path:
    campaign = _campaign(tmp_path, players=COHERENT_PLAYERS, party=COHERENT_PARTY,
                         voice=("gyrgum_voice.md",), examples=("gyrgum.md",))
    (campaign / "docs" / "Gyrgum.md").write_text("x", encoding="utf-8")
    return campaign


# ── clean ───────────────────────────────────────────────────────────────────


def test_a_coherent_campaign_reports_nothing(tmp_path):
    findings = collect_findings(_coherent(tmp_path))
    assert findings["clean"] is True


def test_clean_exits_zero(tmp_path, capsys):
    assert main(["check", "--campaign-dir", str(_coherent(tmp_path))]) == 0
    assert "Clean." in capsys.readouterr().out


def test_findings_exit_one(tmp_path, capsys):
    campaign = _campaign(tmp_path, players="players: []\n", party=COHERENT_PARTY)
    assert main(["check", "--campaign-dir", str(campaign)]) == 1


# ── the four config-only sections ───────────────────────────────────────────


def test_a_character_nobody_plays_is_named(tmp_path):
    campaign = _campaign(tmp_path, players="players: []\n", party=COHERENT_PARTY)
    assert collect_findings(campaign)["unplayed_characters"] == ["Gyrgum"]


def test_a_character_played_only_by_an_inactive_player_is_not_reported(tmp_path):
    """FR-011a. A departed player's character is historical, not broken — and
    deleting them instead would have made every one of that character's
    archived sessions unresolvable."""
    campaign = _campaign(tmp_path, party=COHERENT_PARTY, players="""\
        players:
        - id: gabe
          name: Gabe
          display_names: [Gabe]
          plays: [Gyrgum]
          active: false
    """)
    assert collect_findings(campaign)["unplayed_characters"] == []


def test_a_binding_to_an_unknown_character_is_named(tmp_path):
    campaign = _campaign(tmp_path, party=COHERENT_PARTY, players="""\
        players:
        - id: ben
          name: Ben Pfaff
          display_names: [Ben Pfaff]
          plays: [Grygum]
    """)
    found = collect_findings(campaign)["unknown_characters"]
    assert found == [{"player": "ben", "character": "Grygum"}]


def test_a_player_with_no_display_name_is_named(tmp_path):
    """Hillsfar's state. Legitimate, and worth saying out loud: that player
    resolves in no transcript."""
    campaign = _campaign(tmp_path, party=COHERENT_PARTY, players="""\
        players:
        - id: ben
          name: Ben Pfaff
          plays: [Gyrgum]
    """)
    assert collect_findings(campaign)["players_without_display_name"] == ["ben"]


def test_a_declared_file_that_is_absent_is_named(tmp_path):
    """The Gyrgum case, as a report rather than as silence."""
    campaign = _campaign(tmp_path, players=COHERENT_PLAYERS, party="""\
        characters:
        - name: Gyrgum
          sheet: docs/Gyrgum.md
          voice: voice/grygum_voice.md
    """)
    found = collect_findings(campaign)["missing_declared_files"]
    assert found[0]["character"] == "Gyrgum"
    assert found[0]["field"] == "voice"
    assert "grygum_voice.md" in found[0]["path"]


# ── orphans ─────────────────────────────────────────────────────────────────


def test_a_file_nothing_declares_is_named(tmp_path):
    """What a rename leaves behind. Under the deleted rule it was invisible
    twice over: it reached no narrator, AND the detector built to catch exactly
    this could not see it (#315)."""
    campaign = _campaign(tmp_path, players=COHERENT_PLAYERS, party=COHERENT_PARTY,
                         voice=("gyrgum_voice.md",),
                         examples=("gyrgum.md", "grygum.md"))
    assert collect_findings(campaign)["undeclared_files"] == ["examples/grygum.md"]


def test_shared_examples_are_declared_and_not_orphans(tmp_path):
    """toee's six house-style files. They reach every narrator because the
    roster says so — which is exactly what makes them not orphans."""
    campaign = _campaign(tmp_path, players=COHERENT_PLAYERS, party="""\
        characters:
        - name: Gyrgum
          sheet: docs/Gyrgum.md
        shared_examples:
        - examples/house_style.md
    """, examples=("house_style.md",))
    assert collect_findings(campaign)["undeclared_files"] == []


def test_underscore_files_are_not_orphans(tmp_path):
    """`_genre.md` is shared campaign material, not a per-character file."""
    campaign = _campaign(tmp_path, players=COHERENT_PLAYERS, party=COHERENT_PARTY,
                         voice=("gyrgum_voice.md", "_genre.md"),
                         examples=("gyrgum.md",))
    assert collect_findings(campaign)["undeclared_files"] == []


# ── the transcript check ────────────────────────────────────────────────────


def _vtt(tmp_path: Path, *speakers: str) -> Path:
    p = tmp_path / "session.vtt"
    body = "WEBVTT\n\n" + "".join(f"{s}: something.\n" for s in speakers)
    p.write_text(body, encoding="utf-8")
    return p


def test_one_absent_display_name_of_four_is_named(tmp_path):
    """The case the existing pre-flight cannot see: it fires only when ZERO
    expected names match, so three-of-four passes it while the fourth player's
    every line silently keeps a raw transcript label (FR-039)."""
    campaign = _campaign(tmp_path, party="""\
        characters:
        - name: A
          sheet: docs/A.md
        - name: B
          sheet: docs/B.md
        - name: C
          sheet: docs/C.md
        - name: D
          sheet: docs/D.md
    """, players="""\
        players:
        - id: w
          name: W
          display_names: [Wade]
          plays: [A]
        - id: g
          name: G
          display_names: [Gabe]
          plays: [B]
        - id: m
          name: M
          display_names: [Mike Hall]
          plays: [C]
        - id: b
          name: B
          display_names: [Ben Pfaff]
          plays: [D]
    """)
    vtt = _vtt(tmp_path, "Wade", "Gabe", "Mike Hall")
    assert collect_findings(campaign, vtt)["absent_in_vtt"] == ["Ben Pfaff"]


def test_every_name_present_reports_nothing(tmp_path):
    campaign = _coherent(tmp_path)
    vtt = _vtt(tmp_path, "Ben Pfaff")
    assert collect_findings(campaign, vtt)["absent_in_vtt"] == []


def test_without_a_vtt_the_section_is_not_checked(tmp_path, capsys):
    main(["check", "--campaign-dir", str(_coherent(tmp_path))])
    assert "not checked — pass --vtt" in capsys.readouterr().out


def test_a_missing_vtt_exits_one(tmp_path, capsys):
    rc = main(["check", "--campaign-dir", str(_coherent(tmp_path)),
               "--vtt", str(tmp_path / "nope.vtt")])
    assert rc == 1
    assert "--vtt not found" in capsys.readouterr().err


# ── unable to run vs. nothing to report ─────────────────────────────────────


def test_an_unloadable_roster_is_an_error_not_a_clean_run(tmp_path, capsys):
    """obelisk's party.yaml is a PC-name exclusion list, not a roster. "The
    check could not run" and "the check found nothing" must never look the
    same."""
    campaign = _campaign(tmp_path, players="players: []\n",
                         party="characters:\n- name: Zenvon Forepot\n")
    assert main(["check", "--campaign-dir", str(campaign)]) == 1
    assert "Error:" in capsys.readouterr().err


def test_a_retired_player_field_is_reported_as_an_error(tmp_path, capsys):
    campaign = _campaign(tmp_path, players="players: []\n", party="""\
        characters:
        - name: Gyrgum
          sheet: docs/Gyrgum.md
          player: Ben Pfaff
    """)
    assert main(["check", "--campaign-dir", str(campaign)]) == 1
    err = capsys.readouterr().err
    assert "retired 'player' field" in err
    assert "migrate_players_config" in err


def test_the_check_writes_nothing(tmp_path):
    """Read-only, asserted rather than assumed (FR-040)."""
    campaign = _coherent(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in campaign.rglob("*") if p.is_file()}
    collect_findings(campaign)
    after = {p: p.stat().st_mtime_ns for p in campaign.rglob("*") if p.is_file()}
    assert before == after
