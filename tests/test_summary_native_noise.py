"""Spec 041 foundation: noise tables, sentence binding, tokenizer, accounting."""
import pytest

from pipelines.summary_native import noise
from pipelines.summary_native.noise import (
    CLASSES, CheckAccounting, NoiseRecord, legacy_code, load_ordinal_idioms, load_status_synonyms,
    parse_spelled_cardinal, sentence_claims, split_sentences, tokens)
from pipelines.summary_native.npc_verify import STATUS_WORDS


# ---- loaders
def test_shipped_tables_load():
    assert "first time" in load_ordinal_idioms()
    syn = load_status_synonyms()
    assert set(syn) == set(STATUS_WORDS)
    assert {"depart", "left", "leaving"} <= set(syn["departed"])


@pytest.mark.parametrize("body", ["", "[]", "- First Time\n", "- ' '\n", "key: v\n", "- 3\n", ": : :\n[", "- a\n- ''\n"])
def test_idioms_reject_malformed(tmp_path, body):
    p = tmp_path / "i.yaml"
    p.write_text(body)
    with pytest.raises(ValueError) as e:
        load_ordinal_idioms(p)
    assert str(p) in str(e.value)


def test_idioms_missing_file(tmp_path):
    with pytest.raises(ValueError):
        load_ordinal_idioms(tmp_path / "nope.yaml")


def test_synonyms_reject_bad_keys_and_values(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("alive: [live]\n")
    with pytest.raises(ValueError, match="STATUS_WORDS"):
        load_status_synonyms(p)
    good = {w: ["x"] for w in STATUS_WORDS}
    import yaml
    for bad in ({**good, "extra": ["x"]}, {**good, "dead": []}, {**good, "dead": ["Died"]}, {**good, "dead": "died"}):
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValueError):
            load_status_synonyms(p)
    p.write_text("- a\n")
    with pytest.raises(ValueError):
        load_status_synonyms(p)
    with pytest.raises(ValueError):
        load_status_synonyms(tmp_path / "none.yaml")


# ---- sentences
def test_split_basic_and_abbreviations():
    assert split_sentences("He left. She stayed. Then it ended.") == ["He left.", "She stayed.", "Then it ended."]
    assert split_sentences("Mr. Smith met Dr. Jones vs. Mrs. Lee, e.g. Ann, i.e. Bo. Next one.") == [
        "Mr. Smith met Dr. Jones vs. Mrs. Lee, e.g. Ann, i.e. Bo.", "Next one."]
    assert split_sentences("See ch. 12 for St. Aldric.") == ["See ch. 12 for St. Aldric."]


def test_split_keeps_brackets_whole_and_trailing_citation_attached():
    line = "He died. [ch 085 / 085.07] She wept [ch 085 / 085.08]. Done."
    assert split_sentences(line) == ["He died. [ch 085 / 085.07]", "She wept [ch 085 / 085.08].", "Done."]
    assert split_sentences("A [note. Not a split] Bo. C") == ["A [note. Not a split] Bo.", "C"]


def test_split_list_numeral_and_empty():
    assert split_sentences("1. Fought the giant. Won.") == ["1. Fought the giant.", "Won."]
    assert split_sentences("") == []


def test_sentence_claims_citation_binding():
    text = ("- Killed 40 orcs [ch 085 / 085.07]. Fled to the hills. [ch 085 / 085.08]\n"
            "- Lone sentence without cite [ch 001 / 001.01]\n"
            "- Two uncited. Both inherit [ch 002 / 002.01]\n")
    cs = sentence_claims(text)
    assert [c.line for c in cs] == [1, 1, 2, 3, 3]
    assert cs[0].citations == ((85, "085.07"),) and not cs[0].inherited
    assert cs[1].citations == ((85, "085.08"),)
    assert "[" not in cs[0].claim and cs[0].sentence.endswith("]. ".strip()) or "[" in cs[0].sentence
    assert cs[3].inherited and cs[3].citations == ((2, "002.01"),)
    assert cs[4].inherited is False  # carries its own citation
    # never another line's citations
    only = sentence_claims("- uncited line\n- cited [ch 001 / 001.01]\n")
    assert only[0].citations == () and only[0].inherited


def test_one_trailing_citation_for_whole_line():
    cs = sentence_claims("He lost 5 hp. He ran 3 miles. [ch 010 / 010.02]\n")
    assert len(cs) == 2
    assert cs[0].inherited and cs[0].citations == ((10, "010.02"),)
    assert not cs[1].inherited


# ---- tokens
def _t(text):
    return [(t.surface, t.kind, t.value) for t in tokens(text)]


def test_grouped_and_lists():
    assert _t("5,000 gold") == [("5,000", "cardinal", 5000)]
    assert _t("5, 6 and 7") == [("5", "cardinal", 5), ("6", "cardinal", 6), ("7", "cardinal", 7)]


def test_spelled_numbers():
    assert _t("five")[0][2] == 5
    assert _t("a thousand")[0][2] == 1000
    assert _t("a hundred coins") == [("a hundred", "cardinal", 100)]
    assert _t("twenty-five")[0][2] == 25
    assert _t("two million")[0][2] == 2_000_000
    assert _t("one hundred twenty three")[0][2] == 123
    t = tokens("three hundred and twelve")
    assert len(t) == 1 and t[0].value == 312
    assert parse_spelled_cardinal("five six") is None
    assert parse_spelled_cardinal("twenty hundred") is None
    assert parse_spelled_cardinal("hundred") is None
    assert parse_spelled_cardinal("ten five") is None
    t = tokens("five six")
    assert len(t) == 1 and t[0].value is None and t[0].surface == "five six"


def test_word_boundaries():
    assert tokens("someone, anyone, none, phone, tone, stone, bone") == []
    assert tokens("no one came")[0].value == 1  # classification, not tokenizing, decides


def test_ordinals():
    assert _t("the 3rd and 21st") == [("3rd", "ordinal", 3), ("21st", "ordinal", 21)]
    assert _t("third")[0][1:] == ("ordinal", 3)
    assert _t("twenty-first")[0][1:] == ("ordinal", 21)


@pytest.mark.parametrize("text,surface", [
    ("Chapter 036", "036"), ("chapters 028–064", "064"), ("ch 12-14", "14"),
    ("1. Intro", "1"), ("- 1. Intro", "1"), ("Scene 036.04", "036.04"), ("see ch. 7", "7"),
    ("session 4", "4"),
])
def test_labels(text, surface):
    labelled = [t.surface for t in tokens(text) if t.label]
    assert surface in labelled


@pytest.mark.parametrize("text,labelled", [
    ("Gruumsh stirs (004) again", ["004"]),
    ("seen (004, 005) twice", ["004", "005"]),
    ("seen (004–006) twice", ["004", "006"]),
    ("seen (004-006)", ["004", "006"]),
    ("seen ( 004 )", ["004"]),
])
def test_bare_parenthesised_chapter_is_a_label(text, labelled):
    assert [t.surface for t in tokens(text) if t.label] == labelled


@pytest.mark.parametrize("text", [
    "(3 giants)", "(12)", "(100 gold)", "(1,000)", "(100)", "(004 gold)", "(0.5)", "(1004)", "004 giants",
])
def test_parenthesised_story_numbers_still_checked(text):
    ts = tokens(text)
    assert ts and not any(t.label for t in ts)


def test_label_only_the_attached_token():
    ts = tokens("lost 36 hit points in Chapter 36")
    assert [t.label for t in ts] == [False, True]
    ts = tokens("chapters 28–64")
    assert [t.label for t in ts] == [True, True]
    assert [t.label for t in tokens("He lost 1. hp")] == [False]


def test_idioms():
    t = tokens("for the first time ever")[0]
    assert t.idiom == "first time"
    assert tokens("the third giant to fall")[0].idiom is None
    assert tokens("in third person")[0].idiom == "third person"
    assert tokens("a second-hand tale")[0].idiom == "second-hand"
    assert tokens("a third partying crowd")[0].idiom is None


# ---- records and accounting
def test_classes_and_legacy_code():
    assert CLASSES == ("label", "idiom", "negated-status", "spelled-number", "synonym", "other-citation")
    assert legacy_code("label") == "noise-label"
    with pytest.raises(ValueError):
        legacy_code("bogus")


def test_noise_record_round_trip():
    r = NoiseRecord("number", "label", 3, "36", "In Chapter 36.", ("ch 036 / 036.01",), "Chapter")
    assert NoiseRecord.from_dict(r.to_dict()) == r
    assert r.legacy_code == "noise-label"
    with pytest.raises(ValueError):
        NoiseRecord("number", "x", 1, "a", "b", (), "c")


def test_check_accounting_invariant():
    a = CheckAccounting(examined=10, supported=4, noise={"label": 3, "idiom": 1}, findings=2)
    a.check()
    assert set(a.noise) == set(CLASSES) and a.noise["synonym"] == 0
    assert CheckAccounting.from_dict(a.to_dict()) == a
    with pytest.raises(AssertionError):
        CheckAccounting(examined=11, supported=4, noise={"label": 3, "idiom": 1}, findings=2).check()
    with pytest.raises(ValueError):
        CheckAccounting(noise={"nope": 1})
    CheckAccounting().check()


# ---- code-review fixes (spec 041) ------------------------------------------------------------
def test_initials_and_new_abbreviations_do_not_split():
    assert len(split_sentences("He met J. R. Smith. Then he died [ch 001 / 001.01].")) == 2
    assert len(split_sentences("Capt. Hale met Lt. Orn and Sgt. Vee at Mt. Dun. Then it ended.")) == 2


def test_scene_id_is_a_label_only_beside_scene_or_a_cited_chapter():
    t, = tokens("He paid 120.50 gold", (4,))
    assert not t.label and t.value is None and t.surface == "120.50"
    t, = tokens("Scene 036.07 shows the gate", (36,))
    assert t.label
    t, = tokens("He paid 036.07 gold", (36,))  # 036 is the cited chapter: still a label
    assert t.label
    t, = tokens("See the scene noted at 036.07", ())
    assert t.label
    t, = tokens("He paid 036.07 gold", ())
    assert not t.label


def _scenes_ev(**by_scene):
    out = ["## Chapter 001", ""]
    for sid, body in by_scene.items():
        out += [f"### Scene 001.{sid} - t", "- Source: s.md (line 1)", "", body, ""]
    return "\n".join(out)


def test_decimal_amount_is_a_number_finding():
    from pipelines.summary_native import npc_check
    ev = npc_check.EvidenceIndex.of(npc_check.split_chapters(
        "## Chapter 004\n\n### Scene 004.02 - t\n- Source: s.md (line 1)\n\nHe paid 95.25 gold.\n"))
    a = noise.analyse_numbers("He paid 120.50 gold [ch 004 / 004.02]\n", ev)
    assert len(a.findings) == 1 and "120.50" in a.findings[0].detail
    ev2 = npc_check.EvidenceIndex.of(npc_check.split_chapters(
        "## Chapter 036\n\n### Scene 036.07 - t\n- Source: s.md (line 1)\n\nThe gate held.\n"))
    a = noise.analyse_numbers("Scene 036.07 shows the gate. [ch 036 / 036.07]\n", ev2)
    assert a.findings == () and a.noise[0].noise_class == "label"


def _status_eval(state_line, evidence):
    from pipelines.summary_native import npc_check
    from pipelines.summary_native.npc_verify import LAST_STATE
    draft = f"{LAST_STATE}\n{state_line}\n"
    return noise.classify_status(draft, npc_check.parse_sections(draft), evidence)


_EV_STATUS = ("## Chapter 001\n\n### Scene 001.01 - t\n- Source: s.md (line 1)\n\nShe leaves the city.\n\n"
              "### Scene 001.02 - t\n- Source: s.md (line 2)\n\nNothing else happened.\n\n"
              "### Scene 001.03 - t\n- Source: s.md (line 3)\n\nThey turned left at the fork.\n")


def test_synonym_must_appear_in_a_cited_scene():
    f, r, _ = _status_eval("She departed the city [ch 001 / 001.01]", _EV_STATUS)
    assert f == [] and [x.noise_class for x in r] == ["synonym"]
    f, r, _ = _status_eval("She departed the city [ch 001 / 001.02]", _EV_STATUS)
    assert len(f) == 1 and r == []   # 'left' only in another scene
    f, r, _ = _status_eval("She departed the city", _EV_STATUS)
    assert len(f) == 1               # no citation: synonyms do not apply


def test_negation_is_scoped_to_its_clause():
    ev = "## Chapter 001\n\n### Scene 001.01 - t\n- Source: s.md (line 1)\n\nNothing.\n"
    f, r, _ = _status_eval("It is unclear whether the cult knows; Vizeran was killed by the party [ch 001 / 001.01]", ev)
    assert len(f) == 1 and '"killed"' in f[0].detail and r == []
    f, r, _ = _status_eval("Her status is unknown to the party, but Drizzt killed her [ch 001 / 001.01]", ev)
    assert len(f) == 1 and '"killed"' in f[0].detail
    f, r, _ = _status_eval("No further status (alive, dead, escaped) is established [ch 001 / 001.01]", ev)
    assert f == [] and sum(1 for x in r if x.noise_class == "negated-status") >= 2
