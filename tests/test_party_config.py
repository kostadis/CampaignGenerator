"""Round-trip tests for campaignlib/party_config.py's roster model.

These exist for one specific failure mode, documented in that module's own
source: the loader, the saver and the resolver all **hand-build** their output
instead of dumping the model, so a newly added field is silently dropped unless
it is named in all three. When feature 003 added ``selection`` it hit exactly
that — the write returned success and persisted nothing.

Feature 009 sent three more fields through the same door — ``voice`` and
``examples`` on a character, ``shared_examples`` on the campaign — and took one
away. ``player`` is not merely absent now: a document still carrying it is
**refused by name**, because a retired location that still parses is a split
brain waiting to happen.
"""

import sys
import textwrap
from pathlib import Path

import pytest

# D12 — see tests/test_sheet_naming.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from campaignlib.party_config import (  # noqa: E402
    PATH_FIELDS,
    PartyCharacter,
    PartyConfig,
    load_party_config,
    missing_files,
    resolve_party_config,
    save_party_config,
)


# ── the retired player field ────────────────────────────────────────────────


def test_a_roster_still_carrying_player_is_refused(tmp_path):
    """FR-013. Ignoring it would leave two places recording the same fact, one
    of them silently unread — the shape feature 009 exists to remove."""
    path = tmp_path / "party.yaml"
    path.write_text(textwrap.dedent("""\
        characters:
        - name: Soma
          sheet: docs/party/Soma.md
          player: Wade Brown
    """), encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        load_party_config(path)
    msg = str(exc.value)
    assert "Soma" in msg
    assert "player" in msg
    # The message has to say what to run, not only what is wrong.
    assert "migrate_players_config" in msg


def test_the_model_does_not_accept_a_player_field():
    with pytest.raises(ValueError):
        PartyCharacter(name="Soma", sheet="docs/Soma.md", player="Wade")


# ── the two declared file fields ────────────────────────────────────────────


def test_voice_and_examples_are_path_fields():
    """Joining PATH_FIELDS is the whole mechanism: missing_files walks it, the
    API reports it, the Party page renders it. No new machinery."""
    assert "voice" in PATH_FIELDS
    assert "examples" in PATH_FIELDS


def test_voice_and_examples_survive_a_save_load_round_trip(tmp_path):
    path = tmp_path / "party.yaml"
    save_party_config(path, PartyConfig(characters=[
        PartyCharacter(name="Gyrgum", sheet="docs/Gyrgum.md",
                       voice="voice/gyrgum_voice.md",
                       examples="examples/gyrgum.md"),
        PartyCharacter(name="Daz", sheet="docs/Daz.md"),
    ]))
    written = path.read_text(encoding="utf-8")
    assert "voice: voice/gyrgum_voice.md" in written
    assert "examples: examples/gyrgum.md" in written

    reloaded = load_party_config(path)
    assert reloaded.characters[0].voice == "voice/gyrgum_voice.md"
    assert reloaded.characters[0].examples == "examples/gyrgum.md"
    assert reloaded.characters[1].voice is None
    assert reloaded.characters[1].examples is None


def test_a_roster_declaring_neither_does_not_grow_empty_keys(tmp_path):
    path = tmp_path / "party.yaml"
    save_party_config(path, PartyConfig(characters=[
        PartyCharacter(name="Daz", sheet="docs/Daz.md"),
    ]))
    written = path.read_text(encoding="utf-8")
    assert "voice" not in written
    assert "examples" not in written


def test_declared_files_reach_the_resolved_config(tmp_path):
    """The resolver hand-builds too, and it is what the render pipelines
    actually consume — a field missing there is a field the renderer never
    sees, however faithfully the loader read it."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "voice").mkdir()
    (tmp_path / "examples").mkdir()
    for rel in ("docs/Gyrgum.md", "voice/gyrgum_voice.md", "examples/gyrgum.md"):
        (tmp_path / rel).write_text("x", encoding="utf-8")
    cfg = PartyConfig(characters=[
        PartyCharacter(name="Gyrgum", sheet="docs/Gyrgum.md",
                       voice="voice/gyrgum_voice.md",
                       examples="examples/gyrgum.md"),
    ])
    resolved = resolve_party_config(cfg, tmp_path)
    assert resolved.characters[0].voice == (tmp_path / "voice/gyrgum_voice.md")
    assert resolved.characters[0].examples == (tmp_path / "examples/gyrgum.md")


def test_a_declared_file_that_is_absent_is_reported(tmp_path):
    """The Gyrgum case, as a missing file rather than as silence."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Gyrgum.md").write_text("x", encoding="utf-8")
    cfg = PartyConfig(characters=[
        PartyCharacter(name="Gyrgum", sheet="docs/Gyrgum.md",
                       voice="voice/grygum_voice.md"),
    ])
    assert missing_files(cfg, tmp_path) == {"Gyrgum": ["voice"]}


# ── shared_examples ─────────────────────────────────────────────────────────


def test_shared_examples_round_trips(tmp_path):
    """toee's six house-style files. They reach every narrator — the change is
    that a human wrote down that they should."""
    path = tmp_path / "party.yaml"
    save_party_config(path, PartyConfig(
        characters=[PartyCharacter(name="Zinnia", sheet="docs/zinnia.md")],
        shared_examples=["examples/combat_and_consequences.md",
                         "examples/political_maneuvering.md"],
    ))
    assert "shared_examples:" in path.read_text(encoding="utf-8")
    assert load_party_config(path).shared_examples == [
        "examples/combat_and_consequences.md",
        "examples/political_maneuvering.md",
    ]


def test_no_shared_examples_writes_no_key(tmp_path):
    path = tmp_path / "party.yaml"
    save_party_config(path, PartyConfig(characters=[
        PartyCharacter(name="Daz", sheet="docs/Daz.md"),
    ]))
    assert "shared_examples" not in path.read_text(encoding="utf-8")


def test_shared_examples_reach_the_resolved_config(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "examples").mkdir()
    (tmp_path / "docs" / "Zinnia.md").write_text("x", encoding="utf-8")
    (tmp_path / "examples" / "house.md").write_text("x", encoding="utf-8")
    cfg = PartyConfig(
        characters=[PartyCharacter(name="Zinnia", sheet="docs/Zinnia.md")],
        shared_examples=["examples/house.md"],
    )
    resolved = resolve_party_config(cfg, tmp_path)
    assert resolved.shared_examples == [tmp_path / "examples" / "house.md"]


def test_shared_examples_must_be_a_list(tmp_path):
    path = tmp_path / "party.yaml"
    path.write_text(
        "characters:\n- name: A\n  sheet: a.md\nshared_examples: examples/x.md\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a list"):
        load_party_config(path)


# ── unchanged behaviour that the new fields must not disturb ────────────────


def test_a_plain_roster_still_loads_and_saves(tmp_path):
    path = tmp_path / "party.yaml"
    path.write_text(textwrap.dedent("""\
        characters:
        - name: Brewbarry
          sheet: ../docs/party/Brewbarry.md
          arc_score: ../docs/tracking/brewbarry-score.md
        - name: Vukradin
          sheet: ../docs/party/Vukradin.md
          arc_score: null
    """), encoding="utf-8")

    cfg = load_party_config(path)
    save_party_config(path, cfg)
    again = load_party_config(path)
    # The three-state arc_score encoding still round-trips beside the new keys.
    assert again.characters[1].trackless is True
    assert again.characters[0].arc_score == "../docs/tracking/brewbarry-score.md"
