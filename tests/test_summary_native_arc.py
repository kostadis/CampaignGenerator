"""Spec 034 User Story 4: candidate arc-score events, checked by code (T040).

``arc_check`` is deterministic. A candidate survives only when it cites a note the subject really has,
quotes its trigger verbatim from the mechanic file, and states no value, total or threshold. Every drop is
named with its reason(s). The model is a surfacer of candidates; the GM owns the score.
"""

from __future__ import annotations

from pathlib import Path

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


#: The verdict table for ``arc_check.states_a_value`` (#526): ``(event text, states a value?, reason, accepted)``.
#: ``accepted`` marks a false positive we chose to keep (a dropped ordinary line costs one candidate in
#: ``arc_report.md``; the alternative is a miss). ``specs/034-chunked-party-planning/arc_value_check.md`` lists it.
#: Names are the mechanic file's score names, as ``score_names`` reads them from ``MECHANIC`` below.
SCORE_NAMES = ("obsession", "wrath", "corruption")
VALUE_TABLE = [
    # -- states a value: must be dropped (a miss puts a number in front of the GM as if decided) --
    ("The score is now 3", True, "score word + number", False),
    ("SCORE stands at 3", True, "score word + number", False),
    ("Daz's value rises to 2", True, "value word + number", False),
    ("He gains points, bringing it to 6", True, "points word + 'bringing it to N'", False),
    ("Daz gains 2 points", True, "a stated point count", False),
    ("Daz gains one point", True, "a stated point count (number word)", False),
    ("The threshold is reached", True, "threshold reached", False),
    ("The threshold was crossed", True, "threshold crossed", False),
    ("Daz crosses the Obsession threshold", True, "crosses 'the ... threshold' (no 'of')", False),
    ("Daz pushes it to 5", True, "counter verb + 'it to N'", False),
    ("Daz bumps it to a 4", True, "counter verb + 'it to a N'", False),
    ("Daz drops it to zero", True, "counter verb + 'to <number word>' ending the clause", False),
    ("Daz raises the count by 2", True, "counter verb + 'by N'", False),
    ("Wrath +2", True, "signed delta after a word", False),
    ("Wrath -1", True, "signed delta, minus", False),
    ("Daz takes a second strike against him (2/3)", True, "parenthesised fraction", False),
    ("Daz is on strike 2 of 3", True, "counter noun + 'N of M'", False),
    ("They are now at 3", True, "'now at N' ending the clause", False),
    ("The count is now 3", True, "'now N' ending the clause", False),
    ("Wrath, now 3, flares", True, "'now N' before a comma", False),
    ("The tally stands at four", True, "'stands at <number word>'", False),
    ("Obsession now at 4", True, "score name + now at N", False),
    ("Obsession climbs to 4", True, "score name + verb + N", False),
    ("Obsession rises by 1", True, "score name + verb + N", False),
    ("Obsession is at level 3", True, "score name + is at level N", False),
    ("Obsession: 4", True, "score name + colon + N", False),
    ("His Wrath 2 goes up", True, "score name directly followed by N", False),
    ("Obsession total reaches 5", True, "total + number", False),
    # -- states a value, added after review: a value followed by a capitalised word (a score's name) --
    ("Daz now at 3 Obsession", True, "value followed by a score name; a capital letter alone is not an address", False),
    ("Daz now at 4 Madness", True, "value followed by a capitalised word", False),
    ("A score of 5 Doom", True, "score word + number + capitalised word", False),
    ("Score 4 Obsession", True, "score word + number + score name", False),
    ("The Madness score is now 3 Daz snaps", True, "'now 3' followed by a capitalised word", False),
    ("His point count is 4", True, "singular 'point' is a score word", False),
    ("Daz pushes it to 5 Wrath", True, "counter verb + 'it to N' + score name", False),
    ("Daz raises it to 4 Corruption", True, "counter verb + 'it to N' + score name", False),
    # -- states a value, added after review: more shapes --
    ("A score of seven", True, "score word + number word", False),
    ("His score is seven", True, "score word + number word", False),
    ("Daz's arc is at 3", True, "'arc' near a number", False),
    ("The tally is 4", True, "'tally' near a number", False),
    ("Daz is at 3", True, "'is at N' ending the clause", False),
    ("Max is 6 and he is at 5", True, "'is at N' before 'and'", False),
    ("Daz has 3 strikes against him", True, "bare count of a counter noun", False),
    ("Daz needs two more strikes", True, "'N more' + counter noun", False),
    ("Daz has three marks", True, "'has N marks'", False),
    ("4 marks now", True, "'N marks now'", False),
    ("A second strike against him", True, "ordinal + strike", False),
    ("His third strike", True, "ordinal + strike", False),
    ("Strike two", True, "'strike N'", False),
    ("Daz fills a third box", True, "ordinal + box", False),
    ("The meter fills", True, "a meter filling", False),
    ("Daz's meter is full", True, "a meter full", False),
    ("Daz is one mark away from the threshold", True, "'away from the threshold'", False),
    ("Daz goes from 2 to 3", True, "'from N to M'", False),
    ("Wrath ticks up", True, "'ticks up'", False),
    ("Wrath ticks up to 4", True, "'ticks up' + 'to N'", False),
    ("Daz gains 1 Obsession", True, "N + score name", False),
    ("Daz loses 2 Wrath", True, "N + score name", False),
    ("Daz gains two Obsession", True, "number word + score name", False),
    ("Daz gains 2 Corruption points", True, "N + score name + points", False),
    ("Another point of Wrath", True, "'point of' + score name", False),
    ("Daz's first Obsession point", True, "score name + point", False),
    ("Wrath is maxed out", True, "score name maxed", False),
    ("Obsession is at its maximum", True, "score name at its maximum", False),
    ("Obsession reaches its peak", True, "score name reaches its peak", False),
    ("Daz's Obsession, at 4, flares", True, "score name, at N,", False),
    # -- ordinary text: must be kept --
    ("He is now one of the Council", False, "'now one' is not a count when 'of the' follows", False),
    ("The meeting is at 9", False, "'is at N' after an appointment noun", False),
    ("Daz leaves two marks on the cell door", False, "'marks' counts only after a possessing verb or before 'now'", False),
    ("Daz bears a second mark from the ritual", False, "ordinal + 'mark' is left out on purpose", False),
    ("Daz carries the mark of Demogorgon", False, "'mark' with no number", False),
    ("Daz lands the first strike on the ogre", False, "ordinal + strike followed by 'on'", False),
    ("Daz travels from 3 to 4 days out", False, "'from N to M' where M carries a unit", False),
    ("The maximum depth is 300 feet", False, "a unit amount; 'maximum' is not a rule here", False),
    ("The count of Gracklstugh offers him a deal", False, "'count' with no number", False),
    ("The clock tower strikes three", False, "'strikes' is a verb; the clock is not a meter", False),
    ("Daz counts 3 tracks in the mud", False, "'tracks' is not a counter noun", False),
    ("The party is at 3 days from the Underdark exit", False, "'is at N' where N carries a unit", False),
    ("Daz is at the 2nd gate", False, "an ordinal", False),
    ("Daz drinks to the full", False, "'full' with no meter", False),
    ("Daz kills two more and flees", False, "'two more' with no counter noun", False),
    ("Total strangers at the 3rd gate", False, "'total' but the number is an ordinal", False),
    ("The point of no return at 2 bells", False, "'point' but 2 counts bells", False),
    ("They are now at 3 Waterdeep Lane", False, "an address (capitalised street name follows)", False),
    ("Daz moves to 3 Waterdeep Lane", False, "an address", False),
    ("Daz casts a level 3 spell", False, "a number, no score word", False),
    ("Daz spends a 4th-level slot", False, "an ordinal", False),
    ("Daz leaves three guards behind", False, "a count of creatures", False),
    ("Daz meets 13 goblins at the pass", False, "a count of creatures", False),
    ("Daz fights 4 orcs on the road", False, "a count of creatures", False),
    ("Daz hits 3 guards", False, "a count of creatures (hit is not a counter verb)", False),
    ("Daz kills 2 of the 5 guards", False, "'N of M' without a counter noun", False),
    ("Daz pays 500 gp to the guard", False, "gold amount", False),
    ("Daz buys a ring worth 200 gp", False, "gold amount", False),
    ("Daz gets 10 feet closer", False, "a distance", False),
    ("They meet at 9 pm", False, "a time of day", False),
    ("Daz arrives at 4 o'clock", False, "a time of day", False),
    ("Daz raises the alarm at 2 bells", False, "raise-verb, but no 'to N' and a time unit", False),
    ("Daz waits 3 days", False, "a duration", False),
    ("Daz climbs to the 2nd floor", False, "counter verb + 'to', but an ordinal", False),
    ("Daz is now at the gate", False, "'now at' + no number", False),
    ("He now sees 3 banners", False, "'now' + a word before the digit", False),
    ("Daz scores a hit on the second try", False, "'scores' is not 'score'", False),
    ("A valued ally gives him 2 maps", False, "'valued' is not 'value'", False),
    ("He reaches the threshold of the tower", False, "a doorway, not a stated threshold", False),
    ("Daz reaches 3 Waterdeep Lane", False, "'reaches' + an address", False),
    ("Obsession flares at 3 gates", False, "score name, but 'flares' is not a value connector", False),
    ("Daz's obsession leads him to the vault", False, "score name, no number", False),
    # -- accepted false positives: dropped although ordinary; one candidate lost, listed in arc_report.md --
    ("Daz lands 3 strikes on the ogre", True, "a bare 'N strikes' is a count of the counter noun; combat prose is not told apart", True),
    ("Daz opens 3 boxes in the cellar", True, "a bare 'N boxes' is a count of the counter noun", True),
    ("Daz wields a +1 longsword", True, "a magic item's '+1' is indistinguishable from a signed delta", True),
    ("A total of 12 guards patrol the wall", True, "'total ... N' is the value shape; the idiom is not told apart", True),
    ("2/3 of the guards flee", True, "any bare 'N/M' is read as a fraction/score", True),
    ("Daz takes 3 points of damage", True, "'N points' is a point count; damage is not told apart", True),
    ("Daz is at 5/5 hp", True, "any bare 'N/M' is read as a fraction/score", True),
]


class TestValueVerdictTable:
    @pytest.mark.parametrize("text,verdict,reason,accepted", VALUE_TABLE, ids=[r[0] for r in VALUE_TABLE])
    def test_verdict(self, text, verdict, reason, accepted):
        assert arc_check.states_a_value(text, SCORE_NAMES) is verdict, reason

    def test_the_table_has_no_miss_and_names_every_accepted_false_positive(self):
        stated = [r for r in VALUE_TABLE if r[1] and not r[3]]
        ordinary = [r for r in VALUE_TABLE if not r[1]]
        accepted = [r for r in VALUE_TABLE if r[3]]
        assert len(stated) >= 10 and len(ordinary) >= 10 and accepted
        assert all(arc_check.states_a_value(r[0], SCORE_NAMES) for r in stated)  # zero misses
        assert not any(arc_check.states_a_value(r[0], SCORE_NAMES) for r in ordinary)  # no unaccepted false positive

    def test_every_row_is_recorded_in_the_spec(self):
        spec = (Path(__file__).resolve().parent.parent / "specs/034-chunked-party-planning/arc_value_check.md").read_text(encoding="utf-8")
        assert [r[0] for r in VALUE_TABLE if r[0] not in spec] == []

    @pytest.mark.parametrize("text", [r[0] for r in VALUE_TABLE if r[1] and not r[3]])
    def test_a_stated_value_is_dropped_end_to_end(self, text):
        mech = MECHANIC + "\nWrath meter: the Wrath score goes up when Daz loses his temper. The Corruption score too.\n"
        kept, drops = check(line(text), mechanic=mech)
        assert kept == [] and [d.reasons for d in drops] == [("states a value",)]

    def test_score_names_are_read_from_the_mechanic_file(self):
        assert arc_check.score_names(MECHANIC) == {"obsession"}
        assert arc_check.score_names("The Wrath score. His rage meter. Each arc score; the arc.") == {"wrath", "rage"}
        assert arc_check.score_names("") == frozenset()

    def test_a_sentence_initial_word_or_a_common_word_is_not_a_score_name(self):
        text = "Keep score each session. Time score. The ability score of a hero. Roll the dice.\n# Daz — Obsession arc\n"
        assert arc_check.score_names(text) == {"obsession"}

    def test_empty_names_are_ignored(self):
        assert not arc_check.states_a_value("Daz is 3 doors away", ("", " "))

    def test_a_score_name_alone_is_not_a_value(self):
        assert not arc_check.states_a_value("Obsession drives Daz on", ("obsession",))
        # without the name there is nothing to anchor on, and nothing else in the text says it is a score
        assert not arc_check.states_a_value("Obsession 4", ())


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
