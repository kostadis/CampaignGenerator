"""Spec 034 User Story 4: candidate arc-score events, checked by code (T040).

``arc_check`` is deterministic. A candidate survives only when it cites a note the subject really has,
quotes its trigger verbatim from the mechanic file, and states no value, total or threshold. Every drop is
named with its reason(s). The model is a surfacer of candidates; the GM owns the score.
"""

from __future__ import annotations

import pytest

from pipelines.summary_native import arc_check, notes, schema

MECHANIC = """\
# Daz — Obsession arc

Daz's obsession with the lost spellbook advances when he risks the party to chase it.
Trigger: "Daz leaves his post to follow a lead on the spellbook".
Trigger: “Daz refuses an order to turn back”.
"""
CITES = ["[ch 003 / 003.01]", "[ch 004 / 004.01]"]
TRIGGER = 'trigger: "Daz leaves his post to follow a lead on the spellbook"'


def line(event="Daz follows a lead", cite="[ch 003 / 003.01]", trigger=TRIGGER):
    return f"- {event} {cite} — {trigger}"


def check(*lines, cites=CITES, mechanic=MECHANIC):
    return arc_check.check_candidates("\n".join(lines) + "\n", cites, mechanic)


class TestKept:
    def test_a_cited_verbatim_value_free_line_is_kept_as_written(self):
        kept, drops = check(line())
        assert kept == [line()] and drops == []

    def test_kept_lines_keep_the_models_order(self):
        a, b = line("First", "[ch 003 / 003.01]"), line("Second", "[ch 004 / 004.01]")
        assert check(b, a)[0] == [b, a]

    def test_curly_quotes_around_the_trigger_are_read_and_a_typographic_variant_is_verbatim(self):
        text = '- Daz refuses [ch 004 / 004.01] — trigger: “Daz refuses an order to turn back”'
        assert check(text)[0] == [text]

    def test_a_multi_part_citation_is_kept_when_every_part_is_the_subjects(self):
        text = line(cite="[ch 003 / 003.01; ch 004 / 004.01]")
        assert check(text)[0] == [text]

    def test_a_citation_written_with_a_heading_word_is_normalised_before_comparing(self):
        # notes.cites folds a heading's own text to its key ([ch 002 / NPCs] is npcs)
        text = line(cite="[ch 002 / NPCs]")
        assert check(text, cites=["[ch 002 / npcs]"])[0] == [text]

    def test_blank_lines_and_the_none_line_are_neither_kept_nor_dropped(self):
        assert check("", "- (none)", "   ") == ([], [])

    def test_empty_output_is_nothing(self):
        assert arc_check.check_candidates("", CITES, MECHANIC) == ([], [])


class TestCiteNotInNotes:
    def test_no_citation_at_all(self):
        (d,) = check(line(cite=""))[1]
        assert d.reasons == (arc_check.CITE_NOT_IN_NOTES,)

    def test_a_citation_that_is_not_among_the_subjects_notes(self):
        kept, drops = check(line(cite="[ch 002 / 002.01]"))  # a real note, but not this subject's
        assert kept == [] and [d.reasons for d in drops] == [("cite-not-in-notes",)]

    def test_one_foreign_part_drops_the_whole_line(self):
        assert check(line(cite="[ch 003 / 003.01; ch 002 / 002.01]"))[0] == []

    def test_a_malformed_citation_is_not_in_the_notes(self):
        assert check(line(cite="[ch 3 / 3.1]"))[0] == []

    def test_the_chapter_alone_is_not_enough(self):
        assert check(line(cite="[ch 003 / 003.02]"))[0] == []  # ch 003 is the subject's, 003.02 is not


class TestTriggerNotVerbatim:
    def test_a_paraphrased_trigger_is_dropped(self):
        (d,) = check(line(trigger='trigger: "Daz leaves his post to chase a lead on the spellbook"'))[1]
        assert d.reasons == (arc_check.TRIGGER_NOT_VERBATIM,)

    def test_a_line_with_no_trigger_part_is_dropped_the_same_way(self):
        (d,) = check("- Daz follows a lead [ch 003 / 003.01]")[1]
        assert d.reasons == ("trigger not verbatim",)

    def test_an_empty_trigger_is_not_verbatim(self):
        assert check(line(trigger='trigger: ""'))[0] == []

    def test_a_trigger_from_another_files_text_is_not_verbatim_here(self):
        assert check(line(), mechanic="Nothing relevant here at all.")[0] == []

    def test_a_line_that_is_not_a_bullet_is_dropped_not_ignored(self):
        kept, drops = check("Here are the candidates:", line())
        assert kept == [line()] and [d.line for d in drops] == ["Here are the candidates:"]


class TestStatesAValue:
    @pytest.mark.parametrize("event", [
        "The score is now 3",
        "Obsession now at 4",
        "Obsession total reaches 5",
        "Daz's value rises to 2",
        "He gains points, bringing it to 6",
        "The threshold is reached",
        "The threshold was crossed",
        "SCORE stands at 3",
    ])
    def test_a_stated_value_total_or_threshold_is_dropped(self, event):
        kept, drops = check(line(event))
        assert kept == [] and [d.reasons for d in drops] == [("states a value",)]

    @pytest.mark.parametrize("event", [
        "Daz casts a level 3 spell",  # a number, but no score word
        "Daz spends a 4th-level slot",
        "Daz leaves three guards behind",
        "Daz scores a hit on the second try",  # 'scores' is not 'score'
        "Daz is pointed to the door of room 3",  # 'pointed' is not 'point'
        "A valued ally gives him 2 maps",  # 'valued' is not 'value'
        "He reaches the threshold of the tower",  # 'threshold' but no reached/crossed/met
        "He now sees 3 banners",  # 'now' + a word before the digit
    ])
    def test_a_number_without_a_score_word_is_not_a_value(self, event):
        assert check(line(event))[0] == [line(event)]

    def test_the_citation_digits_do_not_count_as_a_value(self):
        # 'points' + a citation's digits is not a stated value
        text = line("Daz points the way", cite="[ch 003 / 003.01]")
        assert check(text)[0] == [text]

    def test_the_mechanic_files_own_words_in_the_trigger_are_not_read_as_a_value(self):
        mech = 'Trigger: "the total reaches 3 and Daz is warned".'
        text = line(trigger='trigger: "the total reaches 3 and Daz is warned"')
        assert check(text, mechanic=mech)[0] == [text]


class TestSeveralReasons:
    def test_every_failed_check_is_named_in_a_stable_order(self):
        text = line("The score is now 3", cite="[ch 002 / 002.01]", trigger='trigger: "paraphrase"')
        (d,) = check(text)[1]
        assert d.reasons == ("cite-not-in-notes", "trigger not verbatim", "states a value")
        assert d.line == text

    def test_a_good_line_beside_bad_ones_survives_and_the_bad_are_all_listed(self):
        good = line()
        kept, drops = check(good, line(cite=""), line("Score now 3"), line(trigger='trigger: "made up"'))
        assert kept == [good] and len(drops) == 3


class TestSubjectNotes:
    """What the planning call is given: an NPC or faction's notes by canonical subject (exact forms only)."""

    FORMS = {"ilvara mizzrym": "Ilvara Mizzrym", "ilvara": "Ilvara Mizzrym"}

    def _results(self):
        def world(tag, subject, text, ch):
            return notes.Note("world", f"- [{tag}] **{subject}** — {text} [ch {ch:03d} / {ch:03d}.01]", ch, "c", tag=tag, subject=subject)

        row = notes.Note("status_row", "- Ilvara | Alive | the camp | Smiling [ch 003 / 003.01]", 3, "c",
                         subject="Ilvara", status="Alive", location="the camp", disposition="Smiling", cite="[ch 003 / 003.01]")
        return [notes.CheckedChunk("002-004", [
            world("NPC", "Ilvara Mizzrym", "A priestess.", 2),
            world("FACTION", "House Mizzrym", "Stands aside.", 3),
            world("NPC", "Ilvara", "Smiles.", 3),
            world("LOCATION", "Ilvara Mizzrym", "Not an NPC note.", 4),
            row,
            world("NPC", "Ilvaras Cousin", "A near spelling is not a match.", 4),
        ])]

    def test_world_notes_and_status_rows_by_canonical_subject(self):
        got = arc_check.entity_notes(self._results(), self.FORMS, "Ilvara Mizzrym")
        assert [n.text.split(" — ")[0] for n in got if n.kind == "world"] == ["- [NPC] **Ilvara Mizzrym**", "- [NPC] **Ilvara**"]
        assert [n.kind for n in got] == ["world", "world", "status_row"]  # chapter order, extraction order within one
        assert all("Cousin" not in n.text and "LOCATION" not in n.text for n in got)

    def test_a_faction_gets_its_faction_notes(self):
        (n,) = arc_check.entity_notes(self._results(), self.FORMS, "House Mizzrym")
        assert "Stands aside" in n.text

    def test_a_subject_with_no_notes_gets_none(self):
        assert arc_check.entity_notes(self._results(), self.FORMS, "Nobody") == []

    def test_cites_of_a_note_set_are_the_normalised_parts(self):
        got = arc_check.cites_of(arc_check.entity_notes(self._results(), self.FORMS, "Ilvara Mizzrym"))
        assert got == {"[ch 002 / 002.01]", "[ch 003 / 003.01]"}


class TestReport:
    def _subject(self, **kw):
        base = dict(name="Daz", kind="character", mechanic="docs/mechanics/daz-arc.md", notes=3,
                    kept=[line()], drops=[arc_check.Drop(line(cite=""), ("cite-not-in-notes",))])
        base.update(kw)
        return arc_check.ArcSubject(**base)

    def test_lists_kept_and_dropped_with_reasons_per_subject(self):
        md = arc_check.arc_report_md([self._subject()])
        assert md.startswith("# Arc-score candidates")
        daz = md.split("## Daz")[1]
        assert "docs/mechanics/daz-arc.md" in daz
        assert line() in daz.split("Dropped")[0]
        assert "cite-not-in-notes" in daz.split("Dropped")[1]

    def test_a_trackless_subject_is_listed_as_no_call(self):
        md = arc_check.arc_report_md([self._subject(name="Zalthir", mechanic=None, kept=[], drops=[], notes=0, trackless=True)])
        assert "Zalthir" in md and "trackless" in md and "no call" in md

    def test_a_subject_with_no_notes_is_listed_as_no_call(self):
        md = arc_check.arc_report_md([self._subject(notes=0, kept=[], drops=[])])
        assert "no checked notes" in md and "no call" in md

    def test_nothing_survived_is_said_plainly(self):
        md = arc_check.arc_report_md([self._subject(kept=[])])
        assert "No candidate survived" in md

    def test_the_report_is_deterministic(self):
        s = [self._subject(), self._subject(name="Ilvara Mizzrym", kind="npc")]
        assert arc_check.arc_report_md(s) == arc_check.arc_report_md(list(s))

    def test_the_heading_constant_is_declared_in_the_schema(self):
        assert schema.ARC_HEADING == "#### Candidate Arc Score Events"
