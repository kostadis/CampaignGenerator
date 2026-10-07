"""The code-owned sections of the chunked state documents (spec 033 T013, FR-007..FR-010).

Timeline, completed encounters and the NPC status table are built by code from the checked notes,
the entity registry and ``players.yaml``. No model is involved, so the output must be byte-identical
for identical inputs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import notes, schema, state_sections
from tests import conftest_state as cs

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


# ── spec 033 US2: reference files, the timeline file and the reading contract (T024) ─────────


WORLD_RAW = """\
## Events
- The party wakes. [ch 002 / 002.01]
- The party leaves. [ch 003 / 003.01]

## Threads
- [OPENED] **The signet ring** — Ilvara leaves a signet ring. [ch 002 / 002.02]
- [RESOLVED] **The signet ring** — Nobody could say what became of it. [ch 004 / 004.02]
- [ADVANCED] **Kalan's intentions** — The party wonders about Kalan. [ch 005 / 005.01]

## World
- [LOCATION] **Velkynvelve** — A drow outpost. [ch 002 / locations]
- [LOCATION] **The Long Stair** — A spiral stair. [ch 003 / Locations]
- [LOCATION] **Velkynvelve** — The party rests at its gate. [ch 005 / end]
- [FACTION] **House Mizzrym** — Its sigil is on the ring. [ch 002 / items]
- [NPC] **Kalan** — A drow who holds the gate. [ch 004 / npcs]
- [NPC] **Ilvara Mizzrym** — A drow priestess. [ch 002 / npcs]
- [ITEM] **Signet Ring** — A ring bearing a sigil. [ch 002 / items]
- [THREAT] **The gate guards** — Sarith watches the party. [ch 002 / 002.01]
"""


def _world_results():
    return [_check(WORLD_RAW)]


class TestReferenceFiles:
    def test_one_file_per_kind_including_the_thread_ledger(self):
        files = state_sections.reference_files(_world_results())
        assert sorted(files) == ["factions", "items", "locations", "npcs", "threads", "threats"]

    def test_every_kept_note_is_there_verbatim(self):
        results = _world_results()
        files = state_sections.reference_files(results)
        for kind, tag in (("factions", "FACTION"), ("npcs", "NPC"), ("locations", "LOCATION"),
                          ("items", "ITEM"), ("threats", "THREAT")):
            texts = notes.stitched(results, "world", tag)
            assert texts
            for text in texts:
                assert text in files[kind].splitlines()
        for text in notes.thread_ledger(results):
            assert text in files["threads"].splitlines()

    def test_notes_are_grouped_under_one_heading_per_subject_in_chapter_order(self):
        md = state_sections.reference_files(_world_results())["locations"]
        lines = md.splitlines()
        assert lines.count("## Velkynvelve") == 1
        at = lines.index("## Velkynvelve")
        assert lines[at + 1:at + 3] == [
            "- [LOCATION] **Velkynvelve** — A drow outpost. [ch 002 / locations]",
            "- [LOCATION] **Velkynvelve** — The party rests at its gate. [ch 005 / end]"]

    def test_subjects_are_sorted_case_insensitively(self):
        raw = ("## World\n- [NPC] **zed** — z. [ch 002 / npcs]\n- [NPC] **Alpha** — a. [ch 003 / npcs]\n"
               "- [NPC] **beta** — b. [ch 004 / npcs]\n")
        md = state_sections.reference_files([_check(raw)])["npcs"]
        assert [ln for ln in md.splitlines() if ln.startswith("## ")] == ["## Alpha", "## beta", "## zed"]

    def test_a_thread_keeps_its_whole_history_under_one_subject(self):
        lines = state_sections.reference_files(_world_results())["threads"].splitlines()
        at = lines.index("## The signet ring")
        assert lines[at + 1].startswith("- [OPENED]") and lines[at + 2].startswith("- [RESOLVED]")

    def test_an_empty_kind_says_so(self):
        md = state_sections.reference_files([_check("## Events\n- e [ch 002 / 002.01]\n")])["items"]
        assert schema.NONE_VERIFIED in md

    def test_the_header_counts_notes_and_subjects(self):
        md = state_sections.reference_files(_world_results())["locations"]
        assert "3 checked notes, 2 subjects" in md

    def test_byte_identical_across_builds_and_a_json_round_trip(self):
        results = _world_results()
        again = [notes.CheckedChunk.from_dict(json.loads(json.dumps(r.to_dict()))) for r in results]
        assert state_sections.reference_files(results) == state_sections.reference_files(again)


class TestTimelineFile:
    def test_the_timeline_is_its_own_file_holding_every_event(self):
        results = _world_results()
        md = state_sections.timeline_file_md(results)
        assert md.startswith("# Canon Events Timeline\n")
        for e in notes.stitched(results, "event"):
            assert e in md.splitlines()

    def test_worlds_section_points_to_the_file_and_states_the_count(self):
        body = state_sections.timeline_pointer(_world_results(), 2, 5)
        assert schema.TIMELINE_FILE in body and "2 events" in body and "ch 002-005" in body
        assert "- The party wakes." not in body  # the events themselves are not in world_state

    def test_a_reference_pointer_names_its_file_and_counts(self):
        files = state_sections.reference_files(_world_results())
        ptr = state_sections.reference_pointer("locations", files["locations"])
        assert ptr == "_Full notes: reference/locations.md (2 subjects, 3 checked notes)._"


class TestReadingContract:
    PATHS = {"summaries": "docs/summaries", "reference": "docs/reference", "timeline": "docs/canon_events_timeline.md"}

    def _md(self):
        return state_sections.reading_contract((2, 70), self.PATHS)

    def test_it_names_every_marker(self):
        md = self._md()
        for marker in (schema.LATER, schema.SINCE, schema.UNVERIFIED):
            assert marker in md

    def test_it_lists_all_six_reference_files_and_the_timeline(self):
        md = self._md()
        assert len(state_sections.REFERENCE_KINDS) == 6
        for kind in state_sections.REFERENCE_KINDS:
            assert f"docs/reference/{kind}.md" in md
        assert "docs/canon_events_timeline.md" in md

    def test_it_says_where_a_citation_points(self):
        md = self._md()
        assert "[ch NNN / target]" in md and "docs/summaries/NNN-*.md" in md
        for target in ("npcs", "locations", "items", "spells", "moment", "end"):
            assert target in md

    def test_it_says_the_unsettled_is_the_gms_decision_and_a_quotation_is_not_verbatim(self):
        md = self._md()
        assert "decision for the GM" in md and "not verbatim" in md

    def test_it_says_key_npcs_lines_point_to_a_dossier_or_carry_the_fallback_mark(self):
        md = self._md()
        assert "→ docs/npcs/<slug>.md" in md and schema.KEY_NPC_FALLBACK_MARK in md

    def test_it_is_one_blockquote_naming_the_range(self):
        md = self._md()
        assert all(ln.startswith(">") for ln in md.strip().splitlines())
        assert "ch 002-070" in md

    def test_it_is_deterministic(self):
        assert self._md() == self._md()


# ── The session-prep contract (spec 033 US7, T052) ──────────────────────────
#
# contracts/session-prep.md promises session prep four things about the documents. These tests build
# both documents end to end (extract, then synth with the fixture's published dossier, annotate
# included) with the model faked, and read the files back.
#
# A "content line" is a line a reader could take as a claim. Counted: every list item, table data row
# and prose line inside a ``## `` section. Excluded, each by a structural rule and not by wording:
#   * headings (``#``) and blank lines;
#   * the HTML provenance comment and the reading-contract blockquote (``>``): apparatus, tested below;
#   * a pointer line, which is a whole italic line (``_..._``): "Full notes: reference/x.md", the
#     Key NPCs "Source:" line. It names a file; it asserts nothing about the campaign;
#   * annotation sub-bullets (``annotate.ANNOTATION_RE``): they sit under a cited line and are not a
#     claim of the draft; their citations are checked separately;
#   * table header and separator rows;
#   * the body of two sections that are code-built pointers or status, not claims: ``## Canon Events
#     Timeline`` (a pointer to the timeline file, asserted to name it) and ``## Audit: Tracking
#     Claims`` when it says the audit was not run.


def _build_both(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    fm = cs.fake_models(monkeypatch)
    assert cs.run_cli(cs.extract_args(root))[0] == 0
    fm.prose_override.update({
        "## Party": (
            "## Party\n\n### Dealings\n\n- The party bargained with Ilvara Mizzrym. [ch 002 / 002.02]\n"
            "- The party left the pens by night. [ch 003 / 003.02]\n"),
        "## Locations": "## Locations\n\n- **Velkynvelve** — A drow outpost. [ch 002 / locations]\n",
    })
    for doc, extra in (("world_state", ["--fallback-npc-lines"]), ("campaign_state", [])):
        rc, out, err = cs.run_cli(["synth", doc, *cs.common(root), *extra])
        assert rc == 0, err
    drafts = cs.range_dir(root) / schema.STATE_DIR / "drafts"
    texts = {d: (drafts / f"{d}.draft.md").read_text(encoding="utf-8") for d in ("world_state", "campaign_state")}
    return drafts, texts


def _content_lines(text):
    """``[(section heading, line)]`` for the content lines, by the rules in the comment above."""
    from pipelines.summary_native import annotate

    out, section, table_rows = [], None, 0
    for line in text.splitlines():
        if line.startswith("## "):
            section, table_rows = line, 0
            continue
        if section is None or not line.strip() or line.startswith(("#", "<!--", ">")):
            continue
        if section == "## Canon Events Timeline" or (section.startswith("## Audit") and "not run" in line):
            continue
        if line.startswith("_") and line.rstrip().endswith("_"):
            continue
        if annotate.ANNOTATION_RE.match(line):
            continue
        if line.startswith("|"):
            table_rows += 1
            if table_rows <= 2:  # header row and separator row
                continue
        out.append((section, line))
    return out


class TestSessionPrepContract:
    @pytest.fixture
    def built(self, tmp_path, monkeypatch):
        return _build_both(tmp_path, monkeypatch)

    def test_the_content_lines_are_the_ones_the_comment_says(self, built):
        # Guards the definition itself: a rule that silently matched nothing would pass vacuously.
        _, docs = built
        ws = [ln for _, ln in _content_lines(docs["world_state"])]
        assert any(ln.startswith("- **Ilvara Mizzrym**") for ln in ws)
        assert "- **Velkynvelve** — A drow outpost. [ch 002 / locations]" in ws
        assert not any(ln.startswith(("_Full notes", "_Source", ">")) for ln in ws)
        cs_lines = [ln for _, ln in _content_lines(docs["campaign_state"])]
        assert sum(ln.startswith("| ") for ln in cs_lines) == 3  # three NPC rows, no header or separator
        assert len(ws) >= 8 and len(cs_lines) >= 6

    def test_guarantee_1_every_content_line_has_at_least_one_resolving_citation(self, built):
        _, docs = built
        allowed = {c.number: c.targets for c in CHAPTERS}
        for doc, text in docs.items():
            for section, line in _content_lines(text):
                assert notes.cite_problem(line, allowed) is None, f"{doc} {section}: {line}"

    def test_every_annotation_citation_resolves_too(self, built):
        from pipelines.summary_native import annotate

        _, docs = built
        allowed = {c.number: c.targets for c in CHAPTERS}
        found = 0
        for text in docs.values():
            for line in text.splitlines():
                if annotate.ANNOTATION_RE.match(line):
                    found += 1
                    assert notes.cite_problem(line, allowed) is None, line
        assert found >= 1  # the Velkynvelve line gets a "later" annotation

    def test_guarantee_2_world_state_opens_with_the_reading_contract(self, built):
        drafts, docs = built
        body = docs["world_state"].split("\n", 1)[1]  # past the provenance comment
        contract = [ln for ln in body.split("\n## ", 1)[0].splitlines() if ln.strip()]
        assert contract and all(ln.startswith(">") for ln in contract)
        md = "\n".join(contract)
        for marker in (schema.LATER, schema.SINCE, schema.UNVERIFIED):
            assert marker in md
        assert "[ch NNN / target]" in md and "docs/summaries/NNN-*.md" in md
        for target in ("npcs", "locations", "items", "spells", "moment", "end"):
            assert target in md
        assert f"docs/{schema.TIMELINE_FILE}" in md
        for kind in state_sections.REFERENCE_KINDS:
            assert f"docs/reference/{kind}.md" in md
        assert "decision for the GM" in md and "outrank" in md
        # ... and the files it names exist beside the drafts, ready to promote.
        assert (drafts / schema.TIMELINE_FILE).is_file()
        for kind in state_sections.REFERENCE_KINDS:
            assert (drafts / "reference" / f"{kind}.md").is_file()

    def test_guarantee_3_every_key_npcs_line_has_a_dossier_pointer_or_the_fallback_mark(self, built):
        from pipelines.summary_native import key_npcs

        _, docs = built
        lines = [ln for sec, ln in _content_lines(docs["world_state"]) if sec == "## Key NPCs"]
        assert len(lines) == 3
        pointers = fallbacks = 0
        for ln in lines:
            if ln.rstrip().endswith(key_npcs.FALLBACK_MARK):
                fallbacks += 1
                assert "→ docs/npcs/" not in ln  # the mark means "no dossier", so no pointer beside it
            else:
                pointers += 1
                assert re.search(r"→ docs/npcs/[a-z0-9-]+\.md$", ln.rstrip()), ln
        assert pointers == 1 and fallbacks == 2  # Ilvara is published in the fixture; Kalan and Sarith are not
