"""Prototype 1 of the NPC agent: presence candidates and the knowledge horizon.

Fixtures are written in the published layout (``campaigns-public``): a
``## Summary`` prose section and scene headings with no ``NNN.SS`` id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.npc_agent import cli, corpus, dossier, horizon, knowledge, presence, review, rulings

CH57 = """# Chapter 57

Date: 2026-05-18

## Summary

Daral asked why Sylvira Savikas was not present at the council.

The party went to dinner.

## Scenes

### The Council in Uproar

#### The party is summoned to the Chapter House.

- Daral asks why Sylvira Savikas is not present.

### Dinner

#### The party eats.

- Nothing of note. A Sylviran tapestry hangs on the wall; sylvira is not capitalised here.

## Memorable Moments

> "Where is she?"
> — Daral

## NPCs

### Sylvira Savikas

A Great Reader, absent through illness.

### Daral Yashenti

He asked why Sylvira Savikas was absent.
"""

CH61 = """# Chapter 61

## Summary

Daz visited Sylvira in her quarters.

## Scenes

### Reunion

#### The party regroups.

- They plan the day.

### Interview with Sylvira

#### Daz, alone, visits the ailing Sylvira.

- Sylvira denies drinking honey.

> "Honey? I would never drink honey."
> — Sylvira

## Memorable Moments

> "Honey? I would never drink honey."
> — Sylvira

*She is incredulous.*

> "Wick is lit."
> — Daz

## NPCs

### Sylvira

Bedridden with an abyssal plague.
"""

CH63 = """# Chapter 63

## Scenes

### Battle in the Rotunda

#### The party kills Moziqodo, Sylvira's son.

- Sylvira is not told.
"""

SYLVIRA = """<!-- published by summary_native npc-publish | npc: Sylvira Savikas -->
---
subject: Sylvira Savikas
type: npc
global: true
aliases_used: [Sylvira, Sylvira Savikas]
first_seen: 57
last_seen: 63
chapters: [57, 61, 63]
n_entries: 2
n_scenes: 3
n_moments: 1
---

## History with the Party
- Daral asks after her [ch 057 / 057.01].
- Daz interviews her [ch 061 / 061.02; ch 061 / moment].
- Her son is killed [ch 063 / 063.01].
"""

WICK = """<!-- published -->
---
subject: Wick
aliases_used: [Wick]
first_seen: 61
last_seen: 61
chapters: [61]
n_entries: 0
n_scenes: 0
n_moments: 0
---
"""


@pytest.fixture
def camp(tmp_path: Path) -> Path:
    s = tmp_path / "summaries"
    n = tmp_path / "npcs"
    s.mkdir()
    n.mkdir()
    (s / "057-session-council.md").write_text(CH57)
    (s / "061-session-colloquium.md").write_text(CH61)
    (s / "063-session-key.md").write_text(CH63)
    (n / "sylvira-savikas.md").write_text(SYLVIRA)
    (n / "wick.md").write_text(WICK)
    return tmp_path


def _setup(camp, rulings_map=None):
    c = corpus.load_corpus(camp / "summaries")
    ds = dossier.read_dossiers(camp / "npcs")
    table = presence.build_form_table(ds, frozenset({"wick"}), rulings_map or {})
    syl = dossier.select(ds, ["Sylvira"])[0]
    return c, ds, table, syl


# ── corpus ──────────────────────────────────────────────────────────────────


def test_scene_ids_are_assigned_by_position_when_undeclared(camp):
    c = corpus.load_corpus(camp / "summaries")
    ch61 = next(ch for ch in c.chapters if ch.chapter == 61)
    scenes = [it for it in ch61.items if it.kind == corpus.SCENE]
    assert [(s.item_id, s.title) for s in scenes] == [("061.01", "Reunion"), ("061.02", "Interview with Sylvira")]


def test_a_declared_scene_id_is_kept():
    ch, _ = corpus.parse_chapter("# Chapter 5\n\n## Scenes\n\n### 005.07 Late Scene\n\n- x\n", "005-x.md")
    assert [it.item_id for it in ch.items] == ["005.07"]


def test_prose_moment_and_entry_items_are_chapter_level(camp):
    c = corpus.load_corpus(camp / "summaries")
    ids = [it.item_id for it in c.chapters[0].items]
    assert ids == ["057.01", "057.02", "057.p01", "057.p02", "057.m01", "057.e01", "057.e02"]


def test_item_lines_point_at_the_file(camp):
    c = corpus.load_corpus(camp / "summaries")
    for it in c.items():
        lines = (camp / "summaries" / it.source_file).read_text().splitlines()
        for n, text in it.lines:
            assert lines[n - 1] == text, (it.item_id, n)


# ── mentions, events, snapshots, context ──────────────────────────────────


def _mentions(camp):
    c, _, table, syl = _setup(camp)
    return presence.mentions(c, syl, table)


def test_only_scenes_are_events_to_answer(camp):
    # One event, one answer. Prose renders the scenes and an entry is a snapshot;
    # asking presence of either atomises an event (survey F2, F10).
    ms = _mentions(camp)
    assert [c.item.item_id for c in presence.events(ms)] == ["057.01", "061.02", "063.01"]
    assert [c.item.item_id for c in presence.snapshots(ms)] == ["057.e01", "061.e01"]
    assert [c.item.item_id for c in presence.context(ms)] == ["057.p01", "057.e02", "061.p01", "061.m01"]


def test_matching_is_exact_case_sensitive_and_word_bounded(camp):
    ids = [c.item.item_id for c in _mentions(camp)]
    assert "057.02" not in ids  # "Sylviran" and lower-case "sylvira" do not name her


def test_signals(camp):
    by_id = {c.item.item_id: c for c in _mentions(camp)}
    assert by_id["061.02"].signals == (presence.QUOTED, presence.HEADLINE, presence.NAMED)
    assert by_id["061.m01"].signals == (presence.QUOTED,)
    assert by_id["057.e01"].signals == (presence.OWN_ENTRY,)
    assert by_id["057.e02"].signals == (presence.NAMED,)  # another NPC's entry naming her
    assert by_id["063.01"].signals == (presence.HEADLINE, presence.NAMED)


def test_a_longer_form_of_another_npc_wins_the_match(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "n").mkdir()
    (tmp_path / "s" / "069-x.md").write_text(
        "# Chapter 69\n\n## Memorable Moments\n\n> \"A door.\"\n> — Manshoon (Simulacrum)\n"
    )
    for stem, subject, forms in (("manshoon", "Manshoon", "[Manshoon]"),
                                 ("sim", "Manshoon (Simulacrum)", "[Manshoon (Simulacrum)]")):
        (tmp_path / "n" / f"{stem}.md").write_text(
            f"---\nsubject: {subject}\naliases_used: {forms}\nchapters: [69]\n---\n"
        )
    c = corpus.load_corpus(tmp_path / "s")
    ds = dossier.read_dossiers(tmp_path / "n")
    table = presence.build_form_table(ds, frozenset(), {})
    got = {d.subject: len(presence.mentions(c, d, table)) for d in ds}
    assert got == {"Manshoon": 0, "Manshoon (Simulacrum)": 1}


def test_a_generic_form_is_withheld_until_ruled_safe(camp):
    c, ds, table, _ = _setup(camp)
    wick = dossier.select(ds, ["Wick"])[0]
    assert presence.mentions(c, wick, table) == []
    assert table.withheld_for(wick) == (("Wick", presence.GENERIC),)
    safe = presence.build_form_table(ds, frozenset({"wick"}), {"Wick": "safe"})
    assert [x.item.item_id for x in presence.mentions(c, wick, safe)] == ["061.m02"]


def test_a_form_owned_by_two_npcs_is_ambiguous_and_withheld(tmp_path):
    a = dossier.Dossier("A", "a", tmp_path, ("Vex",), (), 0, 0, 0, 0, 0, ())
    b = dossier.Dossier("B", "b", tmp_path, ("Vex", "Vex the Second"), (), 0, 0, 0, 0, 0, ())
    t = presence.build_form_table([a, b], frozenset(), {})
    assert t.status["Vex"] == presence.AMBIGUOUS
    assert t.linkable("Vex the Second")


# ── check against the dossier ──────────────────────────────────────────────


def test_the_check_reads_every_mention_and_passes(camp):
    c, _, table, syl = _setup(camp)
    chk = presence.check_against_dossier(c, syl, presence.mentions(c, syl, table), table)
    assert chk.ok, chk.lines


def test_the_check_reports_a_mismatch_and_repairs_nothing(camp):
    c, _, table, syl = _setup(camp)
    wrong = dossier.Dossier(**{**syl.__dict__, "chapters": (57, 61), "n_moments": 4})
    chk = presence.check_against_dossier(c, wrong, presence.mentions(c, syl, table), table)
    assert not chk.ok
    assert any(ln.startswith("MISMATCH chapters") for ln in chk.lines)
    assert any(ln.startswith("MISMATCH moments") for ln in chk.lines)


# ── rulings (version 3: answers are about events) ──────────────────────────


def _ids(camp):
    c, _, table, syl = _setup(camp)
    return {syl.subject: {x.item.item_id for x in presence.candidates(c, syl, table)}}


def _corpus(camp):
    return corpus.load_corpus(camp / "summaries")


def _load(camp, tmp_path, body):
    f = tmp_path / "r.yaml"
    f.write_text("version: 3\nnpcs:\n  Sylvira Savikas:\n" + body)
    return rulings.load_rulings(f, _ids(camp), _corpus(camp))["Sylvira Savikas"]


def _effective(camp, r):
    return rulings.effective(r, _corpus(camp), _ids(camp)["Sylvira Savikas"])


def test_rulings_load_and_empty_means_unanswered(camp, tmp_path):
    r = _load(camp, tmp_path, '    items:\n      "061.02": present\n      "063.01":\n')
    assert r == rulings.NpcRulings(items={"061.02": "present"}, spans=())


@pytest.mark.parametrize(
    "body, needle",
    [
        ('    items:\n      "061.02": there\n', "is not one of"),
        ('    items:\n      "057.p01": mentioned\n', "not a scene; answers are about events"),
        ('    items:\n      "061.e01": present\n', "not a scene; answers are about events"),
        ('    items:\n      "061.01": mentioned\n', "'mentioned' needs an event that names the NPC"),
        ('    items:\n      "061.01": neither\n', "'neither' is for an event that names the NPC"),
        ('    items:\n      "061.02": absent\n', "answer it 'mentioned', not 'absent'"),
        ('    items:\n      "061.02": unsure\n', "is not one of present, mentioned, neither, absent"),
        ('    default: present\n', "default 'present' is not one of"),
        ('    spans:\n      - {from: "061.02", to: "057.01"}\n', "is after to"),
        ('    spans:\n      - {from: "061.09", to: "063.01"}\n', "'061.09' is not a scene"),
        ('    spans:\n      - {from: "057.01", to: "061.02", value: unsure}\n', "value 'unsure' is not one of present"),
        ('    spans:\n      - {from: "057.01", to: "061.02", follows: Zalthor}\n', "appears nowhere in the summaries"),
        ('    spans:\n      - {from: "057.01", to: "061.01"}\n      - {from: "061.01", to: "063.01"}\n', "overlap"),
        ('    spans:\n      - {from: "057.01", to: "061.01", until: "x"}\n', "unknown key"),
        ('    "061.02": present\n', "expected a mapping with 'spans', 'items', 'default' and/or 'not_perceived'"),
    ],
)
def test_rulings_refuse_what_they_cannot_apply(camp, tmp_path, body, needle):
    with pytest.raises(rulings.RulingError, match=needle):
        _load(camp, tmp_path, body)


@pytest.mark.parametrize(
    "text, needle",
    [
        ('version: 3\nnpcs:\n  Ilvara:\n    items: {}\n', "not an NPC with a published dossier"),
        ('version: 2\nnpcs: {}\n', "version must be 3"),  # element-based answers are not half-read
        ('version: 3\nnpcs: {}\nextra: 1\n', "unknown top-level key"),
    ],
)
def test_the_file_itself_is_refused_when_it_cannot_be_applied(camp, tmp_path, text, needle):
    f = tmp_path / "r.yaml"
    f.write_text(text)
    with pytest.raises(rulings.RulingError, match=needle):
        rulings.load_rulings(f, _ids(camp), _corpus(camp))


def test_a_span_covers_scenes_and_nothing_else(camp, tmp_path):
    # GM ruling 2026-10-12: Glabbagool in the bag of holding counts as present.
    eff = _effective(camp, _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "063.01"}\n'))
    assert eff["061.01"] == ("present", rulings.FROM_SPAN)  # names nobody; covered anyway
    assert set(eff) == {"061.01", "061.02", "063.01"}


def test_an_item_answer_overrides_the_span(camp, tmp_path):
    body = ('    spans:\n      - {from: "057.01", to: "063.01", note: "in the bag"}\n'
            '    items:\n      "061.01": absent\n      "061.02": mentioned\n')
    r = _load(camp, tmp_path, body)
    assert r.spans[0].note == "in the bag"
    eff = _effective(camp, r)
    assert eff["061.01"] == ("absent", rulings.FROM_ITEM)
    assert eff["061.02"] == ("mentioned", rulings.FROM_ITEM)
    assert eff["057.02"] == ("present", rulings.FROM_SPAN)


def test_follows_is_kept_as_a_hint(camp, tmp_path):
    # GM ruling 2026-10-12: when the party splits, Glabbagool is with Zalthir.
    (camp / "summaries" / "061-session-colloquium.md").write_text(CH61 + "\nZalthir keeps the bag.\n")
    r = _load(camp, tmp_path, '    spans:\n      - {from: "057.01", to: "063.01", follows: Zalthir}\n')
    assert r.spans[0].follows == "Zalthir"


def test_a_default_answers_every_event_nothing_else_reaches(camp, tmp_path):
    r = _load(camp, tmp_path, '    default: mentioned\n    spans:\n      - {from: "061.01", to: "061.02"}\n'
              '    items:\n      "063.01": neither\n')
    eff = _effective(camp, r)
    assert eff["057.01"] == ("mentioned", rulings.FROM_DEFAULT)
    assert eff["061.02"] == ("present", rulings.FROM_SPAN)
    assert eff["063.01"] == ("neither", rulings.FROM_ITEM)


# ── horizon ────────────────────────────────────────────────────────────────


def _items(camp):
    return {it.item_id: it for it in _corpus(camp).items()}


def _horizon(camp, eff, chapter):
    c, _, table, syl = _setup(camp)
    ms = presence.mentions(c, syl, table)
    return horizon.build_horizon(syl, presence.events(ms), eff, chapter, _items(camp), presence.snapshots(ms))


def _item_rulings(d):
    return {k: (v, rulings.FROM_ITEM) for k, v in d.items()}


def test_nothing_is_present_without_an_answer(camp):
    h = _horizon(camp, {}, 63)
    assert h.witnessed == () and [c.item.item_id for c in h.unruled] == ["057.01", "061.02", "063.01"]


def test_the_horizon_sorts_events_by_answer_and_cuts_at_the_chapter(camp):
    h = _horizon(camp, _item_rulings({"061.02": "present", "057.01": "mentioned", "063.01": "mentioned"}), 61)
    assert [x.item.item_id for x in h.witnessed] == ["061.02"]
    assert [x.item.item_id for x in h.mentioned] == ["057.01"]
    assert h.later == 1
    text = horizon.render_horizon(h)
    assert "Moziqodo" not in text and "[ch 061 / 061.02]" in text


def test_state_is_the_latest_entry_and_every_event_naming_them_after_it(camp):
    h = _horizon(camp, {}, 63)
    assert h.snapshot.item_id == "061.e01"
    assert [c.item.item_id for c in h.since_snapshot] == ["063.01"]
    text = horizon.render_horizon(h)
    assert "Bedridden with an abyssal plague" in text
    assert "Events naming them since that entry" in text


def test_neither_is_kept_out_of_both_other_answers(camp, tmp_path):
    r = _load(camp, tmp_path, '    default: mentioned\n    items:\n      "057.01": neither\n      "061.02": present\n')
    h = _horizon(camp, _effective(camp, r), 63)
    assert [x.item.item_id for x in h.neither] == ["057.01"]
    assert "possible linking errors" in horizon.render_horizon(h)
    assert "(by default)" in horizon.render_horizon(h)


def test_a_companion_may_be_present_at_an_event_that_never_names_him(camp, tmp_path):
    r = _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "061.02"}\n')
    h = _horizon(camp, _effective(camp, r), 61)
    assert [x.item.item_id for x in h.witnessed] == ["061.01", "061.02"]
    assert "[ch 061 / 061.01] 061-session-colloquium.md:9 — not named in the scene, by span" in horizon.render_horizon(h)


def test_an_absent_scene_is_left_out(camp, tmp_path):
    r = _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "061.02"}\n    items:\n      "061.01": absent\n')
    h = _horizon(camp, _effective(camp, r), 61)
    assert "061.01" not in [x.item.item_id for x in h.witnessed + h.unruled + h.mentioned + h.neither]


def test_a_horizon_before_the_npc_appears_says_nothing_about_the_future(camp):
    h = _horizon(camp, {}, 40)
    assert h.first_seen is None and h.snapshot is None and h.later > 0
    text = horizon.render_horizon(h)
    for future in ("57", "61", "63", str(h.later)):
        assert future not in text.replace("chapter 40", "")


# ── CLI ────────────────────────────────────────────────────────────────────


def test_cli_candidates_writes_reports_and_a_template(camp, tmp_path):
    out = tmp_path / "out"
    rc = cli.main(["candidates", "--campaign-dir", str(camp), "--npc", "Sylvira", "--out-dir", str(out)])
    assert rc == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "check_report.md", "presence.template.yaml",
        "sylvira-savikas.candidates.json", "sylvira-savikas.candidates.md",
    ]
    tmpl = (out / "presence.template.yaml").read_text()
    assert '"061.02":   # quoted,headline,named' in tmpl and "057.p01" not in tmpl
    loaded = rulings.load_rulings(out / "presence.template.yaml", _ids(camp), _corpus(camp))
    assert loaded == {"Sylvira Savikas": rulings.NpcRulings()}
    md = (out / "sylvira-savikas.candidates.md").read_text()
    assert "Events to answer: 3" in md and "State (their entry, not answered)" in md


def test_cli_exits_3_on_a_mismatch(camp, tmp_path):
    (camp / "npcs" / "wick.md").write_text(WICK.replace("n_scenes: 0", "n_scenes: 5"))
    rc = cli.main(["candidates", "--campaign-dir", str(camp), "--npc", "Wick", "--out-dir", str(tmp_path / "o")])
    assert rc == 3


def test_cli_refuses_to_write_into_its_sources(camp, capsys):
    rc = cli.main(["candidates", "--campaign-dir", str(camp), "--all", "--out-dir", str(camp / "summaries" / "x")])
    assert rc == 2
    assert "never writes into its sources" in capsys.readouterr().err
    assert not (camp / "summaries" / "x").exists()


def test_cli_refuses_an_npc_without_a_published_dossier(camp, tmp_path, capsys):
    rc = cli.main(["candidates", "--campaign-dir", str(camp), "--npc", "Ilvara", "--out-dir", str(tmp_path / "o")])
    assert rc == 2
    assert "no published dossier for 'Ilvara'" in capsys.readouterr().err


def test_cli_horizon(camp, tmp_path, capsys):
    r = tmp_path / "r.yaml"
    r.write_text('version: 3\nnpcs:\n  Sylvira Savikas:\n    items:\n      "061.02": present\n')
    rc = cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira", "--chapter", "61", "--rulings", str(r)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Knowledge horizon — Sylvira Savikas, as of chapter 61" in out
    assert "Honey? I would never drink honey." in out


def test_the_ruling_file_is_never_written(camp, tmp_path):
    r = tmp_path / "r.yaml"
    r.write_text("version: 3\nnpcs: {}\n")
    before = r.read_bytes()
    cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira", "--chapter", "63", "--rulings", str(r),
              "--out", str(tmp_path / "h.md")])
    assert r.read_bytes() == before


# ── review page ────────────────────────────────────────────────────────────


def test_review_bundle_answers_events_and_shows_state_and_context(camp):
    c, _, table, syl = _setup(camp)
    data = review.bundle(c, [(syl, presence.mentions(c, syl, table))], "test")
    n = data["npcs"][0]
    assert list(n["candidates"]) == ["057.01", "061.02", "063.01"]
    assert n["snapshots"] == ["057.e01", "061.e01"]
    assert n["context"] == ["057.p01", "057.e02", "061.p01", "061.m01"]
    assert [ch["n"] for ch in data["chapters"]] == [57, 61, 63]
    assert data["rulings_version"] == rulings.VERSION == 3


def test_review_page_embeds_its_data_safely_and_loads_nothing_but_fonts(camp, tmp_path):
    import re

    (camp / "summaries" / "063-session-key.md").write_text(CH63 + "\n- A stray </script> in a bullet.\n")
    out = tmp_path / "page.html"
    assert cli.main(["review", "--campaign-dir", str(camp), "--npc", "Sylvira", "--out", str(out)]) == 0
    page = out.read_text()
    assert review.DATA_SLOT not in page
    assert page.count("</script>") == 1
    hosts = set(re.findall(r"https?://([^/\"' ]+)", page))
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}


def test_the_file_the_page_saves_is_a_ruling_file(camp, tmp_path):
    import json

    saved = {"version": 3, "npcs": {"Sylvira Savikas": {
        "default": "mentioned",
        "spans": [{"from": "061.01", "to": "063.01", "value": "present", "follows": "Daz"}],
        "items": {"057.01": "neither"}}}}
    f = tmp_path / "presence.json"
    f.write_text(json.dumps(saved, indent=2))
    r = rulings.load_rulings(f, _ids(camp), _corpus(camp))["Sylvira Savikas"]
    assert r.spans[0].follows == "Daz" and r.items == {"057.01": "neither"} and r.default == "mentioned"


def test_review_refuses_to_write_into_its_sources(camp):
    rc = cli.main(["review", "--campaign-dir", str(camp), "--all", "--out", str(camp / "npcs" / "page.html")])
    assert rc == 2
    assert not (camp / "npcs" / "page.html").exists()


# ── beats and what the NPC perceived ───────────────────────────────────────


def test_beats_are_the_headline_and_top_level_bullets(camp):
    it = {i.item_id: i for i in _corpus(camp).items()}
    bs = corpus.beats(it["061.02"])
    assert [b.beat_id for b in bs] == ["061.02.b01", "061.02.b02"]
    assert bs[0].text.startswith("#### Daz, alone")
    assert "> — Sylvira" in bs[1].text  # the quote under a bullet belongs to it
    assert corpus.beats(it["061.p01"]) == ()


def test_not_perceived_needs_a_beat_of_a_present_event(camp, tmp_path):
    r = _load(camp, tmp_path, '    items:\n      "061.02": present\n    not_perceived:\n      - "061.02.b02"\n')
    assert r.not_perceived == frozenset({"061.02.b02"})
    with pytest.raises(rulings.RulingError, match="not answered 'present', so there is nothing to perceive"):
        _load(camp, tmp_path, '    items:\n      "063.01": mentioned\n    not_perceived:\n      - "063.01.b01"\n')
    with pytest.raises(rulings.RulingError, match="not a beat"):
        _load(camp, tmp_path, '    items:\n      "061.02": present\n    not_perceived:\n      - "061.02.b09"\n')


def _agent_view(camp, tmp_path, body, chapter):
    r = _load(camp, tmp_path, body)
    c, _, table, syl = _setup(camp)
    ms = presence.mentions(c, syl, table)
    h = horizon.build_horizon(syl, presence.events(ms), _effective(camp, r), chapter, _items(camp),
                              presence.snapshots(ms), r.not_perceived)
    return h


def test_a_beat_not_perceived_never_reaches_what_the_npc_could_know(camp, tmp_path):
    # 067.03: "Sylvira is Moziqodo's mother, but does not yet know that the party killed her son."
    body = ('    default: mentioned\n    items:\n      "061.02": present\n'
            '    not_perceived:\n      - "061.02.b02"\n')
    h = _agent_view(camp, tmp_path, body, 63)
    agent = horizon.render_horizon(h, for_agent=True)
    assert "Honey" not in agent and "1 beat(s) of this scene left out" in agent
    assert "Daz, alone" in agent  # the perceived beat stays
    gm = horizon.render_horizon(h)
    assert "Part 2 — for the GM only" in gm and "061.02.b02 —" in gm


def test_the_agent_view_carries_nothing_but_present_events(camp, tmp_path):
    h = _agent_view(camp, tmp_path, '    default: mentioned\n    items:\n      "061.02": present\n', 63)
    agent = horizon.render_horizon(h, for_agent=True)
    for gm_only in ("Bedridden with an abyssal plague", "Council in Uproar", "Battle in the Rotunda",
                    "057-session", "mentioned", "Part 2"):
        assert gm_only not in agent


def test_the_cli_refuses_an_agent_view_with_unanswered_events(camp, tmp_path, capsys):
    r = tmp_path / "r.yaml"
    r.write_text('version: 3\nnpcs:\n  Sylvira Savikas:\n    items:\n      "061.02": present\n')
    rc = cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira", "--chapter", "63",
                   "--rulings", str(r), "--for-agent"])
    assert rc == 2
    assert "an agent is never given an incomplete horizon" in capsys.readouterr().err


def test_the_review_bundle_carries_each_scenes_beats(camp):
    c, _, table, syl = _setup(camp)
    data = review.bundle(c, [(syl, presence.mentions(c, syl, table))], "test")
    assert [b[0] for b in data["items"]["061.02"]["b"]] == ["061.02.b01", "061.02.b02"]
    assert "b" not in data["items"]["061.p01"]


# ── knowledge notes ─────────────────────────────────────────────────────────

CH64 = """# Chapter 64

## Scenes

### Tea with Sylvira

#### Sylvira receives Daz in the Vault.

- Sylvira does not yet know that the party killed her son. She thanks Daz.
- Daz asks where the key is. Sylvira does not know.
- The party is unaware of the trap under the rug.
- Daral says, "She does not know," and leaves.

> She does not know.
"""


@pytest.fixture
def kcamp(camp: Path) -> Path:
    (camp / "summaries" / "064-session-tea.md").write_text(CH64)
    return camp


def _kfile(tmp_path, notes: str, campaign: str = "camp") -> Path:
    f = tmp_path / "k.yaml"
    f.write_text(f"version: 2\ncampaigns:\n  {campaign}:\n" + notes)
    return f


def test_the_search_finds_not_knowing_beats_outside_quoted_speech(kcamp):
    found = knowledge.find(_corpus(kcamp))
    assert [k.beat_id for k in found] == ["064.01.b02", "064.01.b03", "064.01.b04"]
    assert found[0].phrase == "does not yet know" and found[0].scene_title == "Tea with Sylvira"
    assert found[2].phrase == "is unaware"
    # b05's only matches are quoted speech and a > quote line: never a candidate


def test_the_search_suggests_who_does_not_know_and_rules_nothing(kcamp):
    c, ds, _, _ = _setup(kcamp)
    found = {k.beat_id: k for k in knowledge.find(c)}
    # "Sylvira does not yet know": the name before the phrase; no other dossier is named
    assert knowledge.suggest(found["064.01.b02"], ds) == (("Sylvira",), False)
    # "Daz asks ... Sylvira does not know."
    assert knowledge.suggest(found["064.01.b03"], ds) == (("Sylvira",), False)
    assert knowledge.suggest(found["064.01.b04"], ds) == ((), True)  # "The party is unaware"


def test_a_suggestion_takes_two_names_and_skips_pronouns():
    def cand(before):
        return knowledge.Candidate("1.01.b01", "001.01", 1, "f", 1, "did not know", before + "did not know", "", before, "")
    assert knowledge.suggest(cand("- The party learned that Nym and Kaelira genuinely "), []) == (("Nym", "Kaelira"), False)
    assert knowledge.suggest(cand("- He "), []) == ((), False)
    assert knowledge.suggest(cand("- Asha "), []) == (("Asha",), False)  # "Asha remained unaware": the verb is in the phrase


def test_a_knowledge_file_loads_one_campaign(kcamp, tmp_path):
    f = _kfile(tmp_path, '    "064.01.b02": {who: [Sylvira], gives_away: true, note: learns at 70}\n'
                         '    "064.01.b03": {who: [Sylvira], gives_away: false}\n'
                         '    "064.01.b04": {who: party}\n    "064.01.b01":\n'
                         '  other:\n    "999.01.b01": {who: nonsense}\n')
    notes = knowledge.load_knowledge(f, "camp", _corpus(kcamp))
    assert notes == {
        "064.01.b02": knowledge.Note("064.01.b02", ("Sylvira",), gives_away=True, note="learns at 70"),
        "064.01.b03": knowledge.Note("064.01.b03", ("Sylvira",), gives_away=False),
        "064.01.b04": knowledge.Note("064.01.b04", party=True),
    }


@pytest.mark.parametrize("notes, needle", [
    ('    "064.01.b02": {who: everyone}\n', "who must be 'party', 'unsure', or a list of names"),
    ('    "064.01.b02": {who: [Sylvira]}\n', "gives_away must be true or false"),
    ('    "064.01.b04": {who: party, gives_away: false}\n', "gives_away is for characters"),
    ('    "064.01.b09": {who: party}\n', "not a beat"),
    ('    "064.01.b02": {who: [Sylvra], gives_away: true}\n', "Sylvra appears nowhere in the summaries"),
    ('    "064.01.b02": {kind: secret, hidden_from: [Sylvira]}\n', "expected a mapping with 'who'"),
])
def test_a_knowledge_file_refuses_what_it_cannot_apply(kcamp, tmp_path, notes, needle):
    with pytest.raises(knowledge.KnowledgeError, match=needle):
        knowledge.load_knowledge(_kfile(tmp_path, notes), "camp", _corpus(kcamp))


def test_a_version_1_knowledge_file_is_refused_with_the_conversion(kcamp, tmp_path):
    f = tmp_path / "k.yaml"
    f.write_text('version: 1\ncampaigns:\n  camp:\n    "064.01.b04": {kind: party}\n')
    with pytest.raises(knowledge.KnowledgeError, match="'kind: party' is 'who: party'"):
        knowledge.load_knowledge(f, "camp", _corpus(kcamp))


def _kview(kcamp, tmp_path, notes, chapter):
    r = _load(kcamp, tmp_path, '    default: mentioned\n    items:\n      "064.01": present\n')
    c, _, table, syl = _setup(kcamp)
    ms = presence.mentions(c, syl, table)
    hidden = knowledge.hidden_from(knowledge.load_knowledge(_kfile(tmp_path, notes), "camp", c), syl)
    return horizon.build_horizon(syl, presence.events(ms), _effective(kcamp, r), chapter, _items(kcamp),
                                 presence.snapshots(ms), r.not_perceived, hidden)


def test_a_beat_giving_away_what_an_npc_does_not_know_never_reaches_them(kcamp, tmp_path):
    h = _kview(kcamp, tmp_path, '    "064.01.b02": {who: [Sylvira], gives_away: true}\n', 64)
    agent = horizon.render_horizon(h, for_agent=True)
    assert "killed her son" not in agent and "1 beat(s) of this scene left out" in agent
    assert "Daz asks where the key is" in agent
    assert "064.01.b02 (knowledge note: gives away what they don't know)" in horizon.render_horizon(h)


def test_a_beat_hidden_from_someone_else_or_later_changes_nothing(kcamp, tmp_path):
    other = _kview(kcamp, tmp_path, '    "064.01.b02": {who: [Daral], gives_away: true}\n', 64)
    assert other.not_perceived == frozenset() and "killed her son" in horizon.render_horizon(other, for_agent=True)
    earlier = _kview(kcamp, tmp_path, '    "064.01.b02": {who: [Sylvira], gives_away: true}\n', 63)
    assert earlier.not_perceived == frozenset() and earlier.hidden_by_note == frozenset()
    assert "Beats left out as not perceived: 0" in horizon.render_horizon(earlier)


def test_only_a_beat_that_gives_it_away_hides_anything(kcamp, tmp_path):
    h = _kview(kcamp, tmp_path, '    "064.01.b02": {who: [Sylvira], gives_away: false}\n'
                                '    "064.01.b03": {who: unsure}\n    "064.01.b04": {who: party}\n', 64)
    assert h.not_perceived == frozenset()


def test_cli_leaks_lists_who_must_not_know_what(kcamp, tmp_path, capsys):
    import yaml

    f = _kfile(tmp_path, '    "064.01.b02": {who: [Sylvira, Daral], gives_away: true}\n'
                         '    "064.01.b03": {who: [Sylvira], gives_away: false}\n',
               campaign=kcamp.name)
    out = tmp_path / "leaks.yaml"
    assert cli.main(["leaks", "--campaign-dir", str(kcamp), "--knowledge", str(f), "--out", str(out)]) == 0
    cases = yaml.safe_load(out.read_text())
    assert cases["campaign"] == kcamp.name
    assert [(c["who"], c.get("dossier"), c["beat"], c["chapter"]) for c in cases["cases"]] == [
        ("Sylvira", "Sylvira Savikas", "064.01.b02", 64), ("Daral", None, "064.01.b02", 64)]
    assert cases["cases"][0]["must_not_know"].startswith("- Sylvira does not yet know")
    err = capsys.readouterr().err
    assert "Daral has no published dossier; kept as a leak case" in err
    assert "gives away (hidden) 1, only says they don't know (kept) 1, the party 0, unsure 0" in err


def test_cli_horizon_reads_the_knowledge_file(kcamp, tmp_path, capsys):
    r = tmp_path / "r.yaml"
    r.write_text('version: 3\nnpcs:\n  Sylvira Savikas:\n    default: mentioned\n    items:\n      "064.01": present\n')
    f = _kfile(tmp_path, '    "064.01.b02": {who: [Sylvira Savikas], gives_away: true}\n', campaign="tea")
    rc = cli.main(["horizon", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--chapter", "64", "--rulings", str(r),
                   "--knowledge", str(f), "--campaign", "tea", "--for-agent"])
    assert rc == 0
    assert "killed her son" not in capsys.readouterr().out
    bad = _kfile(tmp_path, '    "064.01.b02": {who: [Sylvira Savikas]}\n', campaign="tea")
    rc = cli.main(["horizon", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--chapter", "64", "--rulings", str(r),
                   "--knowledge", str(bad), "--campaign", "tea"])
    assert rc == 2 and "gives_away must be true or false" in capsys.readouterr().err


def test_review_shows_knowledge_notes_from_each_campaign_its_own_first(kcamp, tmp_path):
    import json

    other = tmp_path / "elsewhere" / "obelisk"
    (other / "summaries").mkdir(parents=True)
    (other / "npcs").mkdir()
    (other / "summaries" / "002-session-x.md").write_text(
        "# Chapter 2\n\n## Scenes\n\n### Town\n\n#### Arrival.\n\n- Harbin does not know who sent them.\n")
    out = tmp_path / "page.html"
    assert cli.main(["review", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--also-campaign-dir", str(other),
                     "--out", str(out)]) == 0
    page = out.read_text()
    data = json.loads(page.split("const DATA = ", 1)[1].split(";\n", 1)[0].replace("<\\/", "</"))
    camps = data["knowledge"]["campaigns"]
    assert [c["campaign"] for c in camps] == [kcamp.name, "obelisk"]
    assert [k["id"] for k in camps[0]["cards"]] == ["064.01.b02", "064.01.b03", "064.01.b04"]
    assert camps[0]["subjects"] == ["Sylvira Savikas", "Wick"] and camps[1]["subjects"] == []
    assert camps[1]["cards"][0]["ph"] == "does not know" and "Harbin" in camps[1]["cards"][0]["sx"]
    assert camps[0]["cards"][0]["sg"] == ["Sylvira"] and camps[0]["cards"][2]["sp"] is True
    assert data["knowledge"]["version"] == knowledge.VERSION == 2
    rc = cli.main(["review", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--also-campaign-dir", str(kcamp),
                   "--out", str(out)])
    assert rc == 2


def test_the_file_the_page_saves_is_a_knowledge_file(kcamp, tmp_path):
    import json

    saved = {"version": 2, "campaigns": {"camp": {
        "064.01.b02": {"who": ["Sylvira Savikas"], "gives_away": True, "note": "learns at 70"},
        "064.01.b04": {"who": "party"}}}}
    f = tmp_path / "knowledge.json"
    f.write_text(json.dumps(saved, indent=2))
    notes = knowledge.load_knowledge(f, "camp", _corpus(kcamp))
    assert notes["064.01.b02"].who == ("Sylvira Savikas",) and notes["064.01.b04"].party


def test_the_search_shows_what_they_do_not_know_up_to_the_end_of_the_clause(kcamp):
    found = {k.beat_id: k for k in knowledge.find(_corpus(kcamp))}
    assert found["064.01.b02"].what == "that the party killed her son"
    assert found["064.01.b03"].what == ""  # "Sylvira does not know." says not what
    assert found["064.01.b04"].what == "of the trap under the rug"  # the phrase is "is unaware"
    assert knowledge._what(" where the secret room was, only that others had not", " where the secret room was, only that others had not") \
        == "where the secret room was"
    assert knowledge._what(" how to open the door and appears to be flailing", " how to open the door and appears to be flailing") \
        == "how to open the door"
