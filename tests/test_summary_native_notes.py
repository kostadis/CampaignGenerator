"""The shared primitives of the chunked state notes (spec 033 T007).

Phase 2 covers the loading and citation/quote/claim primitives; the code check, drop reasons,
cache keys and routing (T016) extend this file.
"""

from __future__ import annotations

import json
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
                Party="- The party is in the pens. [ch 002 / 002.01]",
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
