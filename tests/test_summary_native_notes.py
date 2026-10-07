"""The shared primitives of the chunked state notes (spec 033 T007).

Phase 2 covers the loading and citation/quote/claim primitives; the code check, drop reasons,
cache keys and routing (T016) extend this file.
"""

from __future__ import annotations

from pathlib import Path

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
