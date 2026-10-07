"""The code-owned sections of the chunked state documents (spec 033 T013, FR-007..FR-010).

Timeline, completed encounters and the NPC status table are built by code from the checked notes,
the entity registry and ``players.yaml``. No model is involved, so the output must be byte-identical
for identical inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import notes, state_sections

FIXTURE = Path(__file__).parent / "fixtures" / "summary_native" / "state"
CHAPTERS = notes.load_chapters(FIXTURE / "docs" / "summaries", 2, 5)
#: Two entities claiming one alias. The registry loader refuses that, so the identity is built directly.
VANE = state_sections.build_identity([("Alpha Vane", ["Vane"]), ("Beta Vane", ["Vane"])], [])


def _chunk(lo, hi):
    return [c for c in CHAPTERS if lo <= c.number <= hi]


def _check(raw, lo=2, hi=5):
    return notes.check_chunk(raw, _chunk(lo, hi))


def _identity():
    return state_sections.load_identity(
        FIXTURE / "docs" / "entity_registry.yaml", FIXTURE / "config" / "players.yaml")


def _rows(*lines):
    return _check("## NPC Status\n" + "\n".join(lines) + "\n")


def _table(*results, identity=None):
    forms, pcs, amb = identity or _identity()
    return state_sections.npc_status_table(list(results), forms, pcs, amb)


def _data_rows(table_md):
    return [ln for ln in table_md.splitlines()[2:] if ln.startswith("|")]


class TestTimelineAndCompleted:
    def test_timeline_is_in_chapter_order_and_deduplicated(self):
        late = _check("## Events\n- later [ch 004 / 004.01]\n- same [ch 003 / 003.01]\n", 3, 4)
        early = _check("## Events\n- earlier [ch 002 / 002.01]\n- same [ch 003 / 003.01]\n", 2, 3)
        md = state_sections.timeline_md([late, early])
        assert md.splitlines() == ["- earlier [ch 002 / 002.01]", "- same [ch 003 / 003.01]", "- later [ch 004 / 004.01]"]

    def test_completed_is_the_concluded_notes_in_order(self):
        a = _check("## Concluded\n- end of three [ch 003 / 003.01]\n- (none)\n- end of three [ch 003 / 003.01]\n")
        b = _check("## Concluded\n- end of two [ch 002 / 002.01]\n")
        assert state_sections.completed_md([a, b]).splitlines() == [
            "- end of two [ch 002 / 002.01]", "- end of three [ch 003 / 003.01]"]

    def test_empty_sections_say_so(self):
        empty = _check("## Events\n- (none)\n")
        assert state_sections.timeline_md([empty]) == "_(none verified)_"
        assert state_sections.completed_md([empty]) == "_(none verified)_"


class TestIdentity:
    def test_forms_and_player_characters_come_from_the_registry_and_players(self):
        forms, pcs, amb = _identity()
        assert forms["ilvara"] == forms["ilvara mizzrym"] == "Ilvara Mizzrym"
        assert forms["sarith"] == "Sarith Kzekarit"
        assert pcs == {"Thorin"} and amb == {}  # "Thorin Giantfriend" is an alias of the registry's Thorin

    def test_a_form_claimed_by_two_entities_is_ambiguous_not_resolved(self):
        forms, pcs, amb = VANE
        assert "vane" not in forms and forms["alpha vane"] == "Alpha Vane"
        assert amb == {"vane": ["Alpha Vane", "Beta Vane"]} and pcs == set()

    def test_the_registry_itself_refuses_such_a_collision_so_it_never_loads(self, tmp_path):
        reg = tmp_path / "reg.yaml"
        reg.write_text(yaml.safe_dump({"version": 1, "entities": [
            {"name": "Alpha Vane", "type": "npc", "aliases": ["Vane"]},
            {"name": "Beta Vane", "type": "npc", "aliases": ["Vane"]},
        ]}))
        with pytest.raises(ValueError, match="identity collision"):
            state_sections.load_identity(reg, None)

    def test_no_registry_and_no_players_is_empty(self):
        assert state_sections.load_identity(None, None) == ({}, set(), {})


class TestNpcStatusTable:
    def test_two_forms_of_one_npc_are_one_row_holding_the_latest_status(self):
        r = _rows("- Ilvara | Alive | the pens | Offers a bargain [ch 002 / 002.02]",
                  "- Ilvara Mizzrym | Dead | the doorway | — [ch 004 / 004.02]")
        table, report = _table(r)
        (row,) = _data_rows(table)
        assert row.startswith("| Ilvara Mizzrym |") and "| Dead |" in row and "[ch 004 / 004.02]" in row
        assert "⚠" not in row
        assert "Ilvara Mizzrym: Ilvara, Ilvara Mizzrym" in report  # merged forms are reported

    def test_the_latest_row_wins_across_chunks_whatever_their_order(self):
        old = _rows("- Sarith | Alive | the gate | Hostile [ch 002 / 002.01]")
        new = _rows("- Sarith Kzekarit | Dead | the stair | — [ch 004 / 004.01]")
        for order in ((old, new), (new, old)):
            (row,) = _data_rows(_table(*order)[0])
            assert "| Dead |" in row and "[ch 004 / 004.01]" in row

    def test_a_later_unknown_is_shown_beside_the_known_status_never_replacing_it(self):
        r = _rows("- Sarith | Dead | the stair | — [ch 004 / 004.01]",
                  "- Sarith | Unknown | somewhere | Wary [ch 005 / 005.01]")
        (row,) = _data_rows(_table(r)[0])
        assert "| Dead |" in row and "[ch 004 / 004.01]" in row
        assert "later, status not stated: somewhere (Wary) [ch 005 / 005.01]" in row

    def test_an_earlier_unknown_is_not_a_later_report(self):
        r = _rows("- Kalan | Unknown | east stair | — [ch 002 / 002.01]",
                  "- Kalan | Alive | the gate | Holds it [ch 004 / 004.01]")
        (row,) = _data_rows(_table(r)[0])
        assert "| Alive |" in row and "later, status not stated" not in row

    def test_a_known_status_replaces_an_unknown_one(self):
        r = _rows("- Kalan | Unknown | — | — [ch 005 / 005.01]", "- Kalan | Alive | the gate | x [ch 004 / 004.01]")
        (row,) = _data_rows(_table(r)[0])
        assert "| Alive |" in row and "later, status not stated" in row  # the ch 5 Unknown is shown, not applied

    def test_only_unknown_rows_stay_unknown(self):
        r = _rows("- Kalan | Unknown | — | — [ch 002 / 002.01]")
        (row,) = _data_rows(_table(r)[0])
        assert "| Unknown |" in row

    def test_a_player_character_row_is_dropped_and_reported(self):
        r = _rows("- Thorin Giantfriend | Alive | the stair | Leads [ch 003 / 003.01]",
                  "- Sarith | Alive | the gate | — [ch 002 / 002.01]")
        table, report = _table(r)
        assert "Thorin" not in table and len(_data_rows(table)) == 1
        assert "Player-character rows dropped (1)" in report and "- Thorin Giantfriend" in report

    def test_an_unresolved_name_is_kept_as_written_marked_and_listed(self):
        r = _rows("- Edvaldo | Alive | the hall | — [ch 003 / 003.01]")
        table, report = _table(r)
        (row,) = _data_rows(table)
        assert row.startswith("| Edvaldo ⚠ |")
        assert "Unresolved names (1)" in report and "- Edvaldo" in report

    def test_a_form_claimed_by_two_entities_stays_unresolved_and_marked(self):
        r = _rows("- Vane | Alive | the hall | — [ch 003 / 003.01]", "- Alpha Vane | Dead | the hall | — [ch 004 / 004.01]")
        table, report = _table(r, identity=VANE)
        names = sorted(ln.split("|")[1].strip() for ln in _data_rows(table))
        assert names == ["Alpha Vane", "Vane ⚠"]
        assert "claimed by more than one entity" in report and "Alpha Vane, Beta Vane" in report

    def test_rows_are_sorted_by_name(self):
        r = _rows("- Sarith | Alive | g | — [ch 002 / 002.01]", "- Kalan | Alive | g | — [ch 002 / 002.01]",
                  "- Ilvara | Alive | g | — [ch 002 / 002.02]")
        names = [ln.split("|")[1].strip() for ln in _data_rows(_table(r)[0])]
        assert names == ["Ilvara Mizzrym", "Kalan", "Sarith Kzekarit"]

    def test_pipes_in_a_cell_cannot_break_the_table(self):
        r = _check("## NPC Status\n- Kalan | Alive | the hall / the stair | fine [ch 004 / 004.01]\n")
        assert all(ln.count("|") == 6 for ln in _data_rows(_table(r)[0]))


class TestDeterminism:
    def _results(self):
        a = _check("## Events\n- e [ch 002 / 002.01]\n## NPC Status\n- Ilvara | Alive | x | y [ch 002 / 002.02]\n"
                   "- Sarith | Unknown | — | — [ch 005 / 005.01]\n")
        b = _check("## Events\n- f [ch 004 / 004.01]\n## Concluded\n- c [ch 004 / 004.01]\n"
                   "## NPC Status\n- Sarith | Dead | z | — [ch 004 / 004.01]\n")
        return [a, b]

    def _build(self, results):
        forms, pcs, amb = _identity()
        table, report = state_sections.npc_status_table(results, forms, pcs, amb)
        return state_sections.timeline_md(results), state_sections.completed_md(results), table, report

    def test_two_runs_are_byte_identical(self):
        assert self._build(self._results()) == self._build(self._results())

    def test_identical_after_a_round_trip_through_json(self):
        results = self._results()
        again = [notes.CheckedChunk.from_dict(json.loads(json.dumps(r.to_dict()))) for r in results]
        assert self._build(results) == self._build(again)
