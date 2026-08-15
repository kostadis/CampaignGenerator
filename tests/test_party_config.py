"""Round-trip tests for campaignlib/party_config.py's roster model.

These exist for one specific failure mode, documented in that module's own
source: the loader, the saver and the resolver all **hand-build** their output
instead of dumping the model, so a newly added field is silently dropped unless
it is named in all three. When feature 003 added ``selection`` it hit exactly
that — the write returned success and persisted nothing. ``player`` (feature
008) is the next field through the same door, so it gets the guard the last one
did not have.
"""

import sys
import textwrap
from pathlib import Path

# D12 — see tests/test_sheet_naming.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from campaignlib.party_config import (  # noqa: E402
    PartyCharacter,
    PartyConfig,
    load_party_config,
    missing_files,
    resolve_party_config,
    save_party_config,
)


def test_player_survives_a_save_load_round_trip(tmp_path):
    """The D9 guard. A 200 from the API is not proof the value reached disk."""
    path = tmp_path / "party.yaml"
    save_party_config(path, PartyConfig(characters=[
        PartyCharacter(name="Soma", sheet="docs/party/Soma.md", player="Wade"),
        PartyCharacter(name="Vukradin", sheet="docs/party/Vukradin.md"),
    ]))

    assert "player: Wade" in path.read_text(encoding="utf-8")
    reloaded = load_party_config(path)
    assert reloaded.characters[0].player == "Wade"
    assert reloaded.characters[1].player is None


def test_player_reaches_the_resolved_config(tmp_path):
    """resolve_party_config hand-builds too — and it is what the render
    pipelines actually consume."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Soma.md").write_text("# Soma\n", encoding="utf-8")
    cfg = PartyConfig(characters=[
        PartyCharacter(name="Soma", sheet="docs/Soma.md", player="Wade"),
    ])
    resolved = resolve_party_config(cfg, tmp_path)
    assert resolved.characters[0].player == "Wade"


def test_a_roster_with_no_player_anywhere_still_loads_and_saves(tmp_path):
    """FR-008a: the field is additive and optional. Every existing campaign's
    roster must keep loading, and must not grow an empty key on save."""
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
    assert [c.player for c in cfg.characters] == [None, None]

    save_party_config(path, cfg)
    written = path.read_text(encoding="utf-8")
    assert "player" not in written
    # The three-state arc_score encoding still round-trips beside it.
    again = load_party_config(path)
    assert again.characters[1].trackless is True
    assert again.characters[0].arc_score == "../docs/tracking/brewbarry-score.md"


def test_player_is_not_a_path_field(tmp_path):
    """missing_files reports referenced files; a player name is not one, and a
    roster naming a player must not report as ungrounded."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Soma.md").write_text("# Soma\n", encoding="utf-8")
    cfg = PartyConfig(characters=[
        PartyCharacter(name="Soma", sheet="docs/Soma.md", player="Wade"),
    ])
    assert missing_files(cfg, tmp_path) == {}
