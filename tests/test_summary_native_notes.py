"""The shared primitives of the chunked state notes (spec 033 T007).

Phase 2 covers the loading and citation/quote/claim primitives; the code check, drop reasons,
cache keys and routing (T016) extend this file.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from pipelines.summary_native import notes, npc_chunked

FIXTURE = Path(__file__).parent / "fixtures" / "summary_native" / "state" / "docs" / "summaries"


def _chapters():
    return notes.load_chapters(FIXTURE, 2, 5)


class TestLoadChapters:
    def test_loads_the_range_in_order(self):
        assert [c.number for c in _chapters()] == [2, 3, 4, 5]
        assert [c.number for c in notes.load_chapters(FIXTURE, 3, 4)] == [3, 4]
        assert notes.load_chapters(FIXTURE, 9, 20) == []

    def test_targets_are_scene_ids_plus_the_section_keys_present(self):
        by = {c.number: c for c in _chapters()}
        assert by[2].targets == {"002.01", "002.02", "moment", "npcs", "locations", "items"}
        assert by[3].targets == {"003.01", "003.02", "moment", "npcs", "locations", "end"}
        assert by[5].targets == {"005.01", "moment", "end"}

    def test_text_is_the_file_verbatim(self):
        c = _chapters()[0]
        assert c.text == (FIXTURE / "002-the-pens.md").read_text(encoding="utf-8")

    def test_chunks_through_the_shared_make_chunks(self):
        chunks = npc_chunked.make_chunks(_chapters(), 10**6)
        assert [[c.number for c in k] for k in chunks] == [[2, 3, 4, 5]]
        assert len(npc_chunked.make_chunks(_chapters(), 1)) == 4


class TestCites:
    def test_a_scene_and_a_section_key(self):
        got = notes.cites("Sarith fell [ch 004 / 004.01; ch 004 / npcs].")
        assert got == [("[ch 004 / 004.01; ch 004 / npcs]", 4, "004.01"), ("[ch 004 / 004.01; ch 004 / npcs]", 4, "npcs")]

    def test_heading_text_is_the_key_in_any_case(self):
        assert notes.cites("x [ch 031 / NPCs]")[0][1:] == (31, "npcs")
        assert notes.cites("x [ch 031 / npcs]")[0][1:] == (31, "npcs")
        assert notes.cites("x [ch 031 / Session-End State]")[0][1:] == (31, "end")
        assert notes.cites("x [ch 031 / memorable moments]")[0][1:] == (31, "moment")
        assert notes.cites("x [ch 031 / Memorable Moments; ch 032 / 032.01]") == [
            ("[ch 031 / moment; ch 032 / 032.01]", 31, "moment"),
            ("[ch 031 / moment; ch 032 / 032.01]", 32, "032.01"),
        ]

    def test_an_unknown_heading_is_invalid(self):
        (b, ch, tgt), = notes.cites("x [ch 031 / Factions]")
        assert ch == -1 and tgt == ""

    def test_malformed_brackets_are_invalid(self):
        for bad in ("[ch 31 / 031.01]", "[ch 031 / ]", "[ch 031]", "[ch 031 / 031.01 ch 032 / moment]"):
            (_, ch, _), = notes.cites(f"x {bad}")
            assert ch == -1, bad

    def test_text_without_brackets_has_none(self):
        assert notes.cites("no citation here") == []
        assert notes.cites("a [not a cite] b") == []


class TestCiteProblem:
    ALLOWED = {2: {"002.01", "npcs"}, 3: {"003.01"}}

    def test_clean(self):
        assert notes.cite_problem("a [ch 002 / 002.01; ch 003 / 003.01]", self.ALLOWED) is None
        assert notes.cite_problem("a [ch 002 / NPCs]", self.ALLOWED) is None

    def test_uncited(self):
        assert notes.cite_problem("a claim", self.ALLOWED) == "uncited"

    def test_outside_the_chunk(self):
        assert notes.cite_problem("a [ch 004 / 004.01]", self.ALLOWED) == "outside-chunk [ch 004 / 004.01]"
        assert notes.cite_problem("a [ch 002 / items]", self.ALLOWED) == "outside-chunk [ch 002 / items]"

    def test_invalid(self):
        assert notes.cite_problem("a [ch 002 / Factions]", self.ALLOWED) == "invalid-citation [ch 002 / Factions]"
        # a scene id whose chapter part differs from the citation's chapter
        assert notes.cite_problem("a [ch 002 / 003.01]", self.ALLOWED) == "invalid-citation [ch 002 / 003.01]"


class TestBadSpan:
    HAY = "She said, “The web remembers every debt,” and left. He said \"Down is the only way left.\""

    def test_verbatim_spans_pass(self):
        assert notes.bad_span('x "The web remembers every debt" y', self.HAY) is None
        assert notes.bad_span("x “Down is the only way left.” y", self.HAY) is None

    def test_an_altered_span_is_returned(self):
        assert notes.bad_span('x "The web forgets every debt" y', self.HAY) == '"The web forgets every debt"'

    def test_the_first_bad_span_wins_and_short_ones_are_ignored(self):
        assert notes.bad_span('"no" and "nor this one at all"', self.HAY) == '"nor this one at all"'

    def test_no_spans(self):
        assert notes.bad_span("nothing quoted", self.HAY) is None


class TestClaimsAndFirstChapter:
    def test_claims_end_at_their_own_citation(self):
        t = "Kalan fled [ch 002 / 002.01] and Sarith held the gate [ch 003 / 003.02]; the rest is silence"
        assert notes.claims_of(t) == [
            "Kalan fled [ch 002 / 002.01]",
            " and Sarith held the gate [ch 003 / 003.02]",
        ]

    def test_no_citation_no_claims(self):
        assert notes.claims_of("nothing") == []

    def test_first_chapter(self):
        assert notes.first_chapter("a [ch 004 / 004.01; ch 002 / npcs]") == 4
        assert notes.first_chapter("a [ch 031 / NPCs]") == 31
        assert notes.first_chapter("no cite") == 9999
        assert notes.first_chapter("a [ch 31 / bad]") == 9999


# ── T012: the code check, drops, outliers, cache keys, routing ───────────────


def _chunk(lo=2, hi=3):
    return [c for c in _chapters() if lo <= c.number <= hi]


def _raw(**sections: str) -> str:
    """A model output: ``_raw(Events="- a [ch 002 / 002.01]")``. Missing sections are omitted."""
    names = {"Events": "## Events", "Concluded": "## Concluded", "Threads": "## Threads",
             "Status": "## NPC Status", "World": "## World", "Party": "## Party"}
    return "\n\n".join(f"{names[k]}\n{v}" for k, v in sections.items()) + "\n"


def _reasons(cc):
    return [(d.kind, d.reason.split(" ")[0]) for d in cc.drops]


class TestCheckChunk:
    def test_a_clean_output_is_kept_by_kind(self):
        cc = notes.check_chunk(
            _raw(
                Events="- Sarith holds the gate. [ch 002 / 002.01]",
                Concluded="- (none)",
                Threads="- [OPENED] **The ring** — a ring is left. [ch 002 / 002.02]",
                Status="- Sarith | Alive | the gate | Hostile [ch 002 / 002.01]",
                World="- [LOCATION] **Velkynvelve** — an outpost. [ch 002 / locations]",
                Party="- **Party** — The party is in the pens. [ch 002 / 002.01]",
            ),
            _chunk(),
        )
        assert cc.drops == []
        assert {k: len(cc.kept(k)) for k in notes.KINDS} == {
            "event": 1, "concluded": 0, "thread": 1, "status_row": 1, "world": 1, "party": 1,
        }
        assert cc.chunk == "002-003"

    def test_uncited(self):
        cc = notes.check_chunk(_raw(Events="- Sarith holds the gate."), _chunk())
        assert _reasons(cc) == [("event", "uncited")]
        assert cc.drops[0].text == "- Sarith holds the gate."

    def test_invalid_citation(self):
        cc = notes.check_chunk(_raw(Events="- x [ch 002 / Factions]"), _chunk())
        assert _reasons(cc) == [("event", "invalid-citation")]
        assert "[ch 002 / Factions]" in cc.drops[0].reason

    def test_outside_chunk(self):
        cc = notes.check_chunk(_raw(Events="- x [ch 004 / 004.01]"), _chunk())
        assert _reasons(cc) == [("event", "outside-chunk")]
        # a real section name of a chapter that lacks it is also outside
        cc = notes.check_chunk(_raw(Events="- x [ch 003 / items]"), _chunk())
        assert _reasons(cc) == [("event", "outside-chunk")]

    def test_quoted_span_not_found(self):
        cc = notes.check_chunk(_raw(Events='- She said "the web is a lie" [ch 002 / 002.02]'), _chunk())
        assert _reasons(cc) == [("event", "quoted-span-not-found")]
        assert '"the web is a lie"' in cc.drops[0].reason

    def test_a_verbatim_span_is_kept(self):
        cc = notes.check_chunk(
            _raw(Events='- She said "The web remembers every debt" [ch 002 / 002.02]'), _chunk()
        )
        assert cc.drops == [] and len(cc.kept("event")) == 1

    def test_missing_thread_tag_and_world_tag(self):
        cc = notes.check_chunk(
            _raw(
                Threads="- **The ring** — no tag. [ch 002 / 002.02]\n- [WRONG] **x** — y [ch 002 / 002.02]",
                World="- **Velkynvelve** — no tag [ch 002 / locations]",
            ),
            _chunk(),
        )
        assert _reasons(cc) == [("thread", "missing-thread-tag"), ("thread", "missing-thread-tag"),
                                ("world", "missing-world-tag")]

    def test_malformed_row(self):
        cc = notes.check_chunk(
            _raw(Status="- Sarith | Kinda | the gate | Hostile [ch 002 / 002.01]\n- Sarith, alive [ch 002 / 002.01]"),
            _chunk(),
        )
        assert _reasons(cc) == [("status_row", "malformed-row"), ("status_row", "malformed-row")]

    def test_a_status_row_is_parsed(self):
        cc = notes.check_chunk(_raw(Status="- Sarith Kzekarit | Alive | the gate | Hostile [ch 002 / 002.01]"), _chunk())
        (n,) = cc.kept("status_row")
        assert (n.subject, n.status, n.location, n.disposition, n.cite) == (
            "Sarith Kzekarit", "Alive", "the gate", "Hostile", "[ch 002 / 002.01]")
        assert n.first_chapter == 2 and n.chunk == "002-003"

    def test_nested_bullet(self):
        cc = notes.check_chunk(_raw(Events="- a [ch 002 / 002.01]\n  - nested [ch 002 / 002.01]"), _chunk())
        assert _reasons(cc) == [("event", "nested-bullet")]
        assert len(cc.kept("event")) == 1

    def test_heading_text_is_accepted_as_its_key_but_an_unknown_heading_is_not(self):
        ok = notes.check_chunk(_raw(Events="- x [ch 003 / NPCs]"), _chunk())
        assert ok.drops == []
        bad = notes.check_chunk(_raw(Events="- x [ch 003 / Factions]"), _chunk())
        assert _reasons(bad) == [("event", "invalid-citation")]

    def test_subjects_and_tags_of_threads_and_world_notes(self):
        cc = notes.check_chunk(
            _raw(Threads="- [ADVANCED] **The ring** — x [ch 002 / 002.02]",
                 World="- [NPC] **Ilvara Mizzrym** — y [ch 002 / npcs]"),
            _chunk(),
        )
        t, w = cc.kept("thread")[0], cc.kept("world")[0]
        assert (t.tag, t.subject) == ("ADVANCED", "The ring")
        assert (w.tag, w.subject) == ("NPC", "Ilvara Mizzrym")

    def test_a_missing_section_is_just_empty(self):
        cc = notes.check_chunk(_raw(Events="- x [ch 002 / 002.01]"), _chunk())
        assert cc.kept("party") == [] and cc.drops == []

    def test_counts(self):
        cc = notes.check_chunk(
            _raw(Events="- a [ch 002 / 002.01]\n- b\n- c [ch 009 / 009.01]"), _chunk())
        c = cc.counts()
        assert c["kept"]["event"] == 1 and c["dropped"] == 2
        assert c["reasons"] == {"outside-chunk": 1, "uncited": 1}

    def test_json_round_trip(self):
        cc = notes.check_chunk(
            _raw(Events="- a [ch 002 / 002.01]\n- b", Status="- S | Alive | x | y [ch 002 / 002.01]"), _chunk())
        again = notes.CheckedChunk.from_dict(json.loads(json.dumps(cc.to_dict(), sort_keys=True)))
        assert again == cc


def _cc(label, n_drops):
    return notes.CheckedChunk(
        label, [], [notes.Drop(label, "event", "uncited", f"- d{i}") for i in range(n_drops)])


class TestOutliers:
    def test_more_than_three_times_the_median_and_at_least_twenty(self):
        results = [_cc("001-001", 1), _cc("002-002", 0), _cc("003-003", 2), _cc("004-004", 40), _cc("005-005", 0)]
        assert notes.outlier_chunks(results) == ["004-004"]

    def test_many_drops_but_not_an_outlier(self):
        # 19 drops is more than 3x the median but under the floor of 20
        assert notes.outlier_chunks([_cc("1", 1), _cc("2", 1), _cc("3", 19)]) == []
        # 20 drops, but the median is high: not more than 3x
        assert notes.outlier_chunks([_cc("1", 10), _cc("2", 10), _cc("3", 20)]) == []

    def test_the_drops_report_flags_it(self):
        md = notes.render_drops_md([_cc("001-001", 1), _cc("002-002", 25), _cc("003-003", 0)])
        assert "OUTLIER" in md and "002-002" in md
        assert "uncited: 26" in md

    def test_the_drops_report_lists_every_drop_with_its_reason(self):
        cc = notes.check_chunk(_raw(Events="- gone\n- x [ch 004 / 004.01]"), _chunk())
        md = notes.render_drops_md([cc])
        assert "- [event] uncited: - gone" in md
        assert "outside-chunk [ch 004 / 004.01]" in md
        assert "OUTLIER" not in md

    def test_the_report_is_deterministic(self):
        cc = notes.check_chunk(_raw(Events="- gone"), _chunk())
        assert notes.render_drops_md([cc]) == notes.render_drops_md([cc])


class TestCacheKey:
    BASE = dict(system="S", user="U", backend="dgx", model="m", max_tokens=100, chunk_chars=60000)

    def test_stable(self):
        assert notes.cache_key(**self.BASE) == notes.cache_key(**self.BASE)

    @pytest.mark.parametrize("field,value", [
        ("system", "S2"), ("user", "U2"), ("backend", "claude-code"), ("model", "m2"),
        ("max_tokens", 101), ("chunk_chars", 1),
    ])
    def test_changes_when_any_input_changes(self, field, value):
        assert notes.cache_key(**{**self.BASE, field: value}) != notes.cache_key(**self.BASE)

    def test_a_missing_model_is_a_value(self):
        assert notes.cache_key(**{**self.BASE, "model": None}) != notes.cache_key(**self.BASE)


class TestRouting:
    def _results(self):
        a = notes.check_chunk(
            _raw(Events="- late event [ch 003 / 003.01]\n- early event [ch 002 / 002.01]",
                 World="- [FACTION] **House Mizzrym** — f [ch 002 / items]\n- [NPC] **Ilvara** — n [ch 002 / npcs]",
                 Threads="- [OPENED] **The ring** — o [ch 002 / 002.02]"),
            _chunk(2, 3))
        b = notes.check_chunk(
            _raw(Events="- chapter four [ch 004 / 004.01]\n- early event [ch 002 / 002.01]",
                 Threads="- [RESOLVED] **The ring** — r [ch 004 / 004.02]"),
            _chunk(2, 4))
        return [a, b]

    def test_stitched_is_deduplicated_and_in_chapter_order(self):
        assert notes.stitched(self._results(), "event") == [
            "- early event [ch 002 / 002.01]", "- late event [ch 003 / 003.01]", "- chapter four [ch 004 / 004.01]"]

    def test_stitched_filters_by_tag(self):
        assert notes.stitched(self._results(), "world", "FACTION") == ["- [FACTION] **House Mizzrym** — f [ch 002 / items]"]
        assert notes.stitched(self._results(), "world", "NPC") == ["- [NPC] **Ilvara** — n [ch 002 / npcs]"]
        assert notes.stitched(self._results(), "world", "THREAT") == []

    def test_thread_ledger_is_every_thread_note_in_order(self):
        assert notes.thread_ledger(self._results()) == [
            "- [OPENED] **The ring** — o [ch 002 / 002.02]",
            "- [RESOLVED] **The ring** — r [ch 004 / 004.02]",
        ]


# ── Spec 034 T005: party subjects, checked levels and note ids ───────────────


def _lvl_chapter(*scene_texts: str, number: int = 2) -> notes.Chapter:
    """A chapter whose scene ``NNN.0k`` holds ``scene_texts[k-1]`` (and nothing else is citable)."""
    body = "".join(f"### {number:03d}.{k:02d} Scene {k}\n\n{t}\n\n" for k, t in enumerate(scene_texts, 1))
    text = f"# Chapter {number}\n\nDate: 2026-03-01\n\n## Scenes\n\n{body}"
    return notes.Chapter(
        number, Path(f"{number:03d}-x.md"), text, {f"{number:03d}.{k:02d}" for k in range(1, len(scene_texts) + 1)})


def _party_check(party: str, *scene_texts: str):
    return notes.check_chunk(_raw(Party=party), [_lvl_chapter(*scene_texts)])


def _party_reasons(cc):
    return [d.reason.split(" ")[0] for d in cc.drops]


class TestPartySubject:
    def test_a_party_bullet_without_a_leading_subject_is_dropped(self):
        cc = _party_check("- The party is in the pens. [ch 002 / 002.01]\n- Daz: rests [ch 002 / 002.01]", "text")
        assert _party_reasons(cc) == ["missing-party-subject", "missing-party-subject"]
        assert cc.kept("party") == []
        assert cc.drops[0].kind == "party" and cc.drops[0].text.startswith("- The party")

    def test_a_character_subject_is_kept(self):
        cc = _party_check("- **Daz** — Casts Glyph of Warding. [ch 002 / 002.01]", "text")
        (n,) = cc.kept("party")
        assert (n.subject, n.tag, n.level) == ("Daz", None, None)
        assert n.text == "- **Daz** — Casts Glyph of Warding. [ch 002 / 002.01]"

    def test_the_party_subject_and_a_joined_subject_are_kept_as_written(self):
        cc = _party_check(
            "- **Party** — Holds the gate. [ch 002 / 002.01]\n- **Daz and Zalthir** — Scout. [ch 002 / 002.01]", "x")
        assert [n.subject for n in cc.kept("party")] == ["Party", "Daz and Zalthir"]

    def test_a_level_row_without_a_subject_is_dropped_as_missing_subject(self):
        cc = _party_check("- [LEVEL] 9 [ch 002 / 002.01]", "the party reaches 9th level")
        assert _party_reasons(cc) == ["missing-party-subject"]

    def test_other_sections_are_unaffected(self):
        cc = notes.check_chunk(_raw(Events="- A thing happens. [ch 002 / 002.01]"), [_lvl_chapter("x")])
        assert cc.drops == [] and len(cc.kept("event")) == 1


class TestPartyLevelRows:
    ROW = "- [LEVEL] **Party** — 9 [ch 002 / 002.01]"

    @pytest.mark.parametrize("cited", [
        "By dawn the party reaches 9th level.",
        "Everyone is now level 9.",
        "They are ninth level now.",
        "The party is level nine.",
        "A 9th-level party at last.",
        "Party levels to 9 after the fight.",
        "The party levels up to 9 at dawn.",
        "The party reached level 9.",
        "Three nights later the party reaches ninth level.",
    ])
    def test_a_level_phrase_in_the_cited_text_confirms_the_level(self, cited):
        cc = _party_check(self.ROW, cited)
        assert cc.drops == [], cited
        (n,) = cc.kept("party")
        assert (n.subject, n.tag, n.level) == ("Party", "LEVEL", 9)

    @pytest.mark.parametrize("cited", [
        "She spends a 4th-level slot.",
        "A 9th-level spell, cast at dawn.",
        "Level 9 spells are out of reach.",
        "Using a level nine slot costs her.",
        "Nothing about levels here, but 9 goblins attack.",
    ])
    def test_a_spell_level_or_a_bare_number_does_not_confirm_it(self, cited):
        cc = _party_check(self.ROW, cited)
        assert _party_reasons(cc) == ["level-not-in-cited-text"], cited
        assert cc.kept("party") == []

    def test_the_level_row_of_a_character(self):
        cc = _party_check("- [LEVEL] **Daz** — 5 [ch 002 / 002.01]", "Daz is now a 5th-level wizard.")
        (n,) = cc.kept("party")
        assert (n.subject, n.tag, n.level) == ("Daz", "LEVEL", 5)

    def test_the_tag_written_inside_the_bold_is_the_same_level_row(self):
        # qwen3.8 writes `**[LEVEL] Daz**` (seen on OOTA ch 016): it is a level row, checked like any other
        cc = _party_check("- **[LEVEL] Daz** — 5 [ch 002 / 002.01]", "Daz is now a 5th-level wizard.")
        (n,) = cc.kept("party")
        assert (n.subject, n.tag, n.level) == ("Daz", "LEVEL", 5)
        cc = _party_check("- **[LEVEL] Daz** — 5 [ch 002 / 002.01]", "quiet")
        assert _party_reasons(cc) == ["level-not-in-cited-text"]

    def test_the_phrase_must_be_in_a_cited_section_not_just_the_chunk(self):
        ch = _lvl_chapter("quiet", "The party reaches 9th level.")
        cc = notes.check_chunk(_raw(Party="- [LEVEL] **Party** — 9 [ch 002 / 002.01]"), [ch])
        assert _party_reasons(cc) == ["level-not-in-cited-text"]
        cc = notes.check_chunk(_raw(Party="- [LEVEL] **Party** — 9 [ch 002 / 002.01; ch 002 / 002.02]"), [ch])
        assert cc.drops == [] and cc.kept("party")[0].level == 9

    def test_a_section_key_citation_reads_that_sections_text(self):
        text = "# Chapter 2\n\n## Scenes\n\n### 002.01 One\n\nquiet\n\n## NPCs\n\n### Daz\n\nDaz reaches level 6 today.\n"
        ch = notes.Chapter(2, Path("002-x.md"), text, {"002.01", "npcs"})
        cc = notes.check_chunk(_raw(Party="- [LEVEL] **Daz** — 6 [ch 002 / npcs]"), [ch])
        assert cc.drops == [] and cc.kept("party")[0].level == 6

    def test_a_level_row_with_no_number_is_dropped(self):
        cc = _party_check("- [LEVEL] **Party** — high [ch 002 / 002.01]", "the party reaches 9th level")
        assert _party_reasons(cc) == ["malformed-level-row"]

    def test_the_new_fields_survive_a_json_round_trip(self):
        cc = _party_check(self.ROW, "the party reaches 9th level")
        again = notes.CheckedChunk.from_dict(json.loads(json.dumps(cc.to_dict(), sort_keys=True)))
        assert again == cc and again.kept("party")[0].level == 9

    def test_stitched_party_is_still_the_note_text(self):
        cc = _party_check(f"{self.ROW}\n- **Daz** — Rests. [ch 002 / 002.01]", "the party reaches 9th level")
        assert notes.stitched([cc], "party") == [self.ROW, "- **Daz** — Rests. [ch 002 / 002.01]"]


class TestNoteId:
    def _note(self, **kw):
        base = dict(kind="thread", text="- [OPENED] **The ring** — a ring. [ch 002 / 002.02]", first_chapter=2, chunk="002-003")
        return notes.Note(**{**base, **kw})

    def test_stable_for_identical_chapter_kind_and_text(self):
        a, b = self._note(), self._note(chunk="002-005", tag="OPENED", subject="The ring")
        assert a.note_id == b.note_id == notes.note_id(a)
        assert re.fullmatch(r"n-[0-9a-f]{10}", a.note_id)

    def test_differs_when_chapter_kind_or_text_differs(self):
        base = self._note().note_id
        assert self._note(first_chapter=3).note_id != base
        assert self._note(kind="world").note_id != base
        assert self._note(text="- [OPENED] **The ring** — a different ring. [ch 002 / 002.02]").note_id != base

    def test_the_id_is_the_documented_digest(self):
        n = self._note()
        want = "n-" + hashlib.sha1(f"002|thread|{n.text}".encode("utf-8")).hexdigest()[:10]
        assert n.note_id == want


class TestPartyPlanningFixture:
    """T004: the checked-note set the party/planning tests share, run through the real code check."""

    def test_the_party_notes_that_survive_and_the_ones_that_do_not(self):
        from tests import conftest_party as cp

        results = cp.checked_results()
        kept = [(n.first_chapter, n.subject, n.tag, n.level) for r in results for n in r.kept("party")]
        assert (2, "Party", "LEVEL", 9) in kept                      # "the party reaches 9th level"
        assert (2, "Dazz", None, None) in kept and (2, "Ront", None, None) in kept
        assert (2, "Daz and Zalthir", None, None) in kept
        assert not [k for k in kept if k[2] == "LEVEL" and k[1] == "Zalthir"]   # spell levels only
        reasons = sorted(d.reason.split(" ")[0] for r in results for d in r.drops)
        assert reasons == ["level-not-in-cited-text", "level-not-in-cited-text", "missing-party-subject"]

    def test_the_thread_notes_name_one_thread_two_ways_and_one_is_resolved(self):
        from tests import conftest_party as cp

        subjects = {(n.tag, n.subject) for r in cp.checked_results() for n in r.kept("thread")}
        assert ("OPENED", "The Carver's march") in subjects and ("ADVANCED", "Carver march") in subjects
        assert ("RESOLVED", "The signet ring") in subjects

    def test_the_published_dossier_reads_through_the_planning_take_set(self):
        from pipelines.summary_native import key_npcs
        from tests import conftest_party as cp

        v = key_npcs.planning_view(cp.PARTY_FIXTURE / "docs" / "npcs" / "ilvara-mizzrym.md")
        assert v.name == "Ilvara Mizzrym" and v.personality and v.relationships and v.state
        assert cp.CANARY not in repr(v)


class TestPartyGrammarFreshness:
    """T008: notes extracted under the pre-034 prompt are refused by party/planning."""

    def _write(self, range_dir, **manifest):
        nd = range_dir / "state" / "notes"
        nd.mkdir(parents=True)
        (nd / "manifest.json").write_text(json.dumps({"kind": "state_notes", **manifest}), encoding="utf-8")

    def test_a_manifest_from_the_current_prompt_is_fine(self, tmp_path):
        from pipelines.summary_native import context, extract, freshness

        sha = freshness.sha_file(context.PROMPT_DIR / extract.SYSTEM_PROMPT)
        self._write(tmp_path, system_sha256=sha, range={"since": 2, "until": 70})
        assert freshness.check_party_grammar(tmp_path) is None

    def test_an_older_prompt_is_refused_with_the_extract_command(self, tmp_path):
        from pipelines.summary_native import freshness

        self._write(tmp_path, system_sha256="0" * 64, range={"since": 2, "until": 70})
        assert freshness.check_party_grammar(tmp_path) == (
            "the party notes predate the subject grammar; "
            "run `summary_native extract --since 2 --until 70` (it re-extracts every chunk)"
        )

    def test_a_manifest_with_no_prompt_sha_is_also_old(self, tmp_path):
        from pipelines.summary_native import freshness

        self._write(tmp_path, range={"since": 2, "until": 5})
        assert "predate the subject grammar" in freshness.check_party_grammar(tmp_path)

    def test_no_manifest_is_not_this_checks_report(self, tmp_path):
        from pipelines.summary_native import freshness

        assert freshness.check_party_grammar(tmp_path) is None
