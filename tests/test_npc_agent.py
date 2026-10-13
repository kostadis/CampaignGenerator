"""Prototype 1 of the NPC agent: presence candidates and the knowledge horizon.

Fixtures are written in the published layout (``campaigns-public``): a
``## Summary`` prose section and scene headings with no ``NNN.SS`` id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.npc_agent import cli, corpus, dossier, horizon, knowledge, leakcheck, persona, presence, review, rulings

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

- Sylvira is grieving, but does not yet know that the party killed her son. She thanks Daz.
- Daz asks where the key is. Sylvira does not know where it is.
- The party is unaware of the trap under the rug.
- Daral says, "She does not know," and leaves.
- The dragon doesn't know about the egg.
- Asha remained unaware that the sign was a deception.

> She does not know.
"""


@pytest.fixture
def kcamp(camp: Path) -> Path:
    (camp / "summaries" / "064-session-tea.md").write_text(CH64)
    return camp


def _kfile(tmp_path, who: str, campaign: str = "camp") -> Path:
    f = tmp_path / "k.yaml"
    f.write_text(f"version: 3\ncampaigns:\n  {campaign}:\n    who:\n" + who)
    return f


def _resolved(kcamp, rulings=None):
    return {r.candidate.beat_id: r for r in knowledge.resolve(_corpus(kcamp), rulings)}


def test_the_search_finds_not_knowing_beats_outside_quoted_speech(kcamp):
    found = knowledge.find(_corpus(kcamp))
    assert [k.beat_id for k in found] == ["064.01.b02", "064.01.b03", "064.01.b04", "064.01.b06", "064.01.b07"]
    assert found[0].phrase == "does not yet know" and found[0].scene_title == "Tea with Sylvira"
    # b05's only matches are quoted speech and a > quote line: never a candidate


def test_the_search_shows_what_they_do_not_know_up_to_the_end_of_the_clause(kcamp):
    found = {k.beat_id: k for k in knowledge.find(_corpus(kcamp))}
    assert found["064.01.b02"].what == "that the party killed her son"
    assert found["064.01.b03"].what == "where it is"
    assert found["064.01.b04"].what == "of the trap under the rug"  # the phrase is "is unaware"
    assert knowledge._what(" where the secret room was, only that others had not",
                           " where the secret room was, only that others had not") == "where the secret room was"
    assert knowledge._what(" how to open the door and appears to be flailing",
                           " how to open the door and appears to be flailing") == "how to open the door"


def _cand(phrase, what, before="- Someone "):
    return knowledge.Candidate("1.01.b01", "001.01", 1, "f", 1, phrase, before + phrase + " " + what, "", before, what)


@pytest.mark.parametrize("phrase, what, expected", [
    ("does not yet know", "that the party killed her son", knowledge.HIDES),
    ("does not know", "he is being groomed for replacement", knowledge.HIDES),
    ("doesn't know", "about the egg", knowledge.HIDES),
    ("unaware of", "the party's presence", knowledge.HIDES),
    ("has not been told", "", knowledge.HIDES),  # "He is a simulacrum, and the party has not been told."
    ("didn't know", "where the secret room was", knowledge.KEEPS),
    ("does not know", "which spells", knowledge.KEEPS),
    ("does not know", "exactly where he is", knowledge.KEEPS),
    ("does not know", "Manshoon's lair", knowledge.KEEPS),
    ("did not know", "their patron's identity", knowledge.KEEPS),
    ("does not know", "", knowledge.KEEPS),  # "Tadric does not know." answers a question in the bullet
])
def test_the_sentence_decides_whether_a_beat_hides_anything(phrase, what, expected):
    assert knowledge.outcome(_cand(phrase, what)) == expected


@pytest.mark.parametrize("before, names, party", [
    ("- Asha ", ("Asha",), False),
    ("- The party learned that Nym and Kaelira genuinely ", ("Nym", "Kaelira"), False),
    ("- Sylvira is Moziqodo's mother, but ", ("Sylvira",), False),
    ("- He is a simulacrum, and the party ", (), True),
    ("- He ", (), False),
    ("- The GM cautions the party, since the dragon ", (), False),
])
def test_who_is_read_from_the_sentence_only_when_it_names_them(before, names, party):
    assert knowledge.who_from_sentence(_cand("does not know", "that x", before)) == (names, party)


def test_resolve_hides_from_the_named_and_leaves_a_description_open(kcamp):
    r = _resolved(kcamp)
    assert (r["064.01.b02"].outcome, r["064.01.b02"].who, r["064.01.b02"].source) == (knowledge.HIDES, ("Sylvira",), "sentence")
    assert r["064.01.b03"].outcome == knowledge.KEEPS and r["064.01.b03"].who == ()
    assert r["064.01.b04"].party and not r["064.01.b04"].unresolved
    assert r["064.01.b06"].unresolved  # "The dragon doesn't know about the egg."
    assert r["064.01.b07"].who == ("Asha",)


def test_a_who_ruling_names_the_description_and_overrides_the_sentence(kcamp, tmp_path):
    f = _kfile(tmp_path, '      "064.01.b06": [Daral]\n      "064.01.b02": [Sylvira Savikas]\n')
    r = _resolved(kcamp, knowledge.load_knowledge(f, "camp", _corpus(kcamp)))
    assert (r["064.01.b06"].who, r["064.01.b06"].source) == (("Daral",), "gm")
    assert r["064.01.b02"].who == ("Sylvira Savikas",)


@pytest.mark.parametrize("who, needle", [
    ('      "064.01.b03": [Sylvira]\n', "nothing in it is hidden"),
    ('      "064.01.b01": [Sylvira]\n', "not a beat that says someone does not know"),
    ('      "064.01.b06": [Themberchaud]\n', "Themberchaud appears nowhere in the summaries"),
    ('      "064.01.b06": Daral\n', "who must be a list of names"),
])
def test_a_knowledge_file_refuses_what_it_cannot_apply(kcamp, tmp_path, who, needle):
    with pytest.raises(knowledge.KnowledgeError, match=needle):
        knowledge.load_knowledge(_kfile(tmp_path, who), "camp", _corpus(kcamp))


def test_an_earlier_knowledge_file_is_refused_with_what_changed(kcamp, tmp_path):
    f = tmp_path / "k.yaml"
    f.write_text('version: 2\ncampaigns:\n  camp:\n    "064.01.b04": {who: party}\n')
    with pytest.raises(knowledge.KnowledgeError, match="version 3 sorts them from the sentence"):
        knowledge.load_knowledge(f, "camp", _corpus(kcamp))


def _kview(kcamp, tmp_path, chapter, rulings=None):
    r = _load(kcamp, tmp_path, '    default: mentioned\n    items:\n      "064.01": present\n')
    c, _, table, syl = _setup(kcamp)
    ms = presence.mentions(c, syl, table)
    resolved = knowledge.resolve(c, rulings)
    unresolved = frozenset(x.candidate.beat_id for x in resolved if x.unresolved)
    return horizon.build_horizon(syl, presence.events(ms), _effective(kcamp, r), chapter, _items(kcamp),
                                 presence.snapshots(ms), r.not_perceived, knowledge.hidden_from(resolved, syl), unresolved)


def test_a_beat_stating_what_an_npc_does_not_know_never_reaches_them(kcamp, tmp_path):
    h = _kview(kcamp, tmp_path, 64)
    agent = horizon.render_horizon(h, for_agent=True)
    assert "killed her son" not in agent and "1 beat(s) of this scene left out" in agent
    assert "Sylvira does not know where it is" in agent  # says only that she does not know
    gm = horizon.render_horizon(h)
    assert "064.01.b02 (the summary says they don't know this)" in gm
    assert "064.01.b06" in gm and "nobody has said who" in gm


def test_a_beat_at_a_later_chapter_changes_nothing(kcamp, tmp_path):
    h = _kview(kcamp, tmp_path, 63)
    assert h.not_perceived == frozenset() and h.unresolved == frozenset()
    assert "Beats left out as not perceived: 0" in horizon.render_horizon(h)


def test_cli_horizon_refuses_an_agent_view_while_a_hidden_beat_has_no_who(kcamp, tmp_path, capsys):
    r = tmp_path / "r.yaml"
    r.write_text('version: 3\nnpcs:\n  Sylvira Savikas:\n    default: mentioned\n    items:\n      "064.01": present\n')
    args = ["horizon", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--chapter", "64", "--rulings", str(r), "--for-agent"]
    assert cli.main(args) == 2
    assert "064.01.b06: in an event Sylvira Savikas attended" in capsys.readouterr().err
    f = _kfile(tmp_path, '      "064.01.b06": [Daral]\n', campaign="tea")
    assert cli.main(args + ["--knowledge", str(f), "--campaign", "tea"]) == 0
    out = capsys.readouterr().out
    assert "killed her son" not in out and "about the egg" in out  # hidden from Daral, not from her


def test_cli_leaks_lists_who_must_not_know_what(kcamp, tmp_path, capsys):
    import yaml

    f = _kfile(tmp_path, '      "064.01.b06": [Daral]\n', campaign=kcamp.name)
    out = tmp_path / "leaks.yaml"
    assert cli.main(["leaks", "--campaign-dir", str(kcamp), "--knowledge", str(f), "--out", str(out)]) == 0
    cases = yaml.safe_load(out.read_text())
    assert cases["campaign"] == kcamp.name
    assert [(c["who"], c.get("dossier"), c["from"], c["beat"]) for c in cases["cases"]] == [
        ("Sylvira", "Sylvira Savikas", "sentence", "064.01.b02"),
        ("Daral", None, "gm", "064.01.b06"),
        ("Asha", None, "sentence", "064.01.b07")]
    err = capsys.readouterr().err
    assert "5 beat(s) say someone doesn't know: 4 state what, 1 do not" in err
    assert "064.01.b04: hidden from the party; no NPC case" in err


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
    cards = {k["id"]: k for k in camps[0]["cards"]}
    assert (cards["064.01.b02"]["o"], cards["064.01.b02"]["wh"]) == ("hides", ["Sylvira"])
    assert cards["064.01.b03"]["o"] == "keeps" and cards["064.01.b04"]["pa"] is True
    assert camps[0]["subjects"] == ["Sylvira Savikas", "Wick"] and camps[1]["subjects"] == []
    assert camps[1]["cards"][0]["o"] == "keeps" and "Harbin" in camps[1]["cards"][0]["sx"]
    assert data["knowledge"]["version"] == knowledge.VERSION == 3
    rc = cli.main(["review", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--also-campaign-dir", str(kcamp),
                   "--out", str(out)])
    assert rc == 2


def test_the_file_the_page_saves_is_a_knowledge_file(kcamp, tmp_path):
    import json

    f = tmp_path / "knowledge.json"
    f.write_text(json.dumps({"version": 3, "campaigns": {"camp": {"who": {"064.01.b06": ["Daral"]}}}}, indent=2))
    assert knowledge.load_knowledge(f, "camp", _corpus(kcamp)) == {"064.01.b06": ("Daral",)}


# ── persona ─────────────────────────────────────────────────────────────────

CH65 = """# Chapter 65

## NPCs

### Sylvira Savikas

A tiefling Great Reader, bedridden with plague. Daral called attention to her absence. She was heard screaming at night. She keeps a ledger of the dead. Sylvira Savikas trusts only Wick. Her ink is red. Daral said, "She is calm. Truly." Kalan visited her chamber.
"""

CH66 = """# Chapter 66

## NPCs

### Sylvira

She is Moziqodo's mother and does not yet know that the party killed her son.
She still mourns him.
"""


@pytest.fixture
def pcamp(camp: Path) -> Path:
    (camp / "summaries" / "065-session-ledger.md").write_text(CH65)
    (camp / "summaries" / "066-session-mother.md").write_text(CH66)
    return camp


def _entries(camp):
    c, _, table, syl = _setup(camp)
    return syl, [x.item for x in presence.snapshots(presence.mentions(c, syl, table))]


def _persona(camp, chapter):
    syl, entries = _entries(camp)
    return syl, persona.persona(entries, syl, chapter)


def _reason(ss, start):
    return next(s.reason for s in ss if s.text.startswith(start))


def test_sentences_split_on_a_capital_and_not_inside_quotes():
    text = '### Sylvira\n\nShe said, “Wait. Stop.” Then left.\nShe sat.  Wick said "Go. Now." Done? Yes!'
    assert persona.split_sentences(text) == [
        "She said, “Wait. Stop.”", "Then left.", "She sat.", 'Wick said "Go. Now."', "Done?", "Yes!"]
    assert persona.split_sentences("Dr. smith went. ok") == ["Dr. smith went. ok"]
    assert persona.split_sentences("   \n ") == []


def test_every_reason_in_the_persona_rule(pcamp):
    ss = [s for s in _persona(pcamp, 65)[1] if s.entry_id == "065.e01"]
    expect = {
        "A tiefling Great Reader": (True, persona.REASON_FIRST),
        "Daral called": (False, persona.REASON_OTHER),
        "She was heard": (False, persona.REASON_REPORTED),
        "She keeps": (True, persona.REASON_SELF),
        "Sylvira Savikas trusts": (True, persona.REASON_SELF),
        "Her ink": (True, persona.REASON_SELF),
        "Daral said": (False, persona.REASON_OTHER),
        "Kalan visited": (False, persona.REASON_OTHER),
    }
    for start, (kept, reason) in expect.items():
        s = next(x for x in ss if x.text.startswith(start))
        assert (s.kept, s.reason) == (kept, reason), start
    assert len(ss) == 8  # the quoted "She is calm. Truly." did not split


def test_a_report_with_her_name_is_dropped_too(pcamp):
    syl, _ = _entries(pcamp)
    e = corpus.parse_chapter("# Chapter 70\n\n## NPCs\n\n### Sylvira\n\nA reader. Sylvira was reportedly seen at dusk.\n", "070-x.md")[0].items[0]
    ss = persona.persona([e], syl, 70)
    assert [(s.kept, s.reason) for s in ss] == [(True, persona.REASON_FIRST), (False, persona.REASON_REPORTED)]


def test_a_sentence_that_says_what_she_does_not_know_is_dropped_whoever_it_names(pcamp):
    _, ss = _persona(pcamp, 66)
    assert _reason(ss, "She is Moziqodo") == persona.REASON_HIDDEN
    assert not next(s for s in ss if s.text.startswith("She is Moziqodo")).kept
    # "does not know where" states nothing hidden: it stays, as the first-sentence/self rules decide
    syl, _ = _entries(pcamp)
    e = corpus.parse_chapter("# Chapter 70\n\n## NPCs\n\n### Sylvira\n\nA reader. She does not know where the key is.\n", "070-x.md")[0].items[0]
    assert persona.persona([e], syl, 70)[1].kept


def test_the_chapter_cut_leaves_out_later_entries_and_chapter_numbers(pcamp):
    _, ss = _persona(pcamp, 65)
    assert {s.chapter for s in ss} <= {57, 61, 65}
    syl, ss = _persona(pcamp, 61)
    assert {s.chapter for s in ss} == {57, 61}
    text = persona.render_persona(ss, syl.subject, 61)
    assert text.startswith("# Who Sylvira Savikas is, as of chapter 61")
    assert "[ch 057]" in text and "[ch 061]" in text and "065" not in text and "066" not in text


def test_render_persona_carries_kept_sentences_only_and_the_report_every_one(pcamp):
    syl, ss = _persona(pcamp, 66)
    text = persona.render_persona(ss, syl.subject, 66)
    assert "She keeps a ledger" in text and "Daral called" not in text and "killed her son" not in text
    rep = persona.render_persona_report(ss, syl.subject, 66)
    assert f"DROPPED ({persona.REASON_HIDDEN}): She is Moziqodo" in rep
    assert f"DROPPED ({persona.REASON_OTHER}): Daral called" in rep
    assert f"KEPT ({persona.REASON_FIRST})" in rep


def test_cli_persona_writes_the_persona_and_the_report(pcamp, tmp_path, capsys):
    out, rep = tmp_path / "p.md", tmp_path / "r.md"
    assert cli.main(["persona", "--campaign-dir", str(pcamp), "--npc", "Sylvira", "--chapter", "66",
                     "--out", str(out), "--report", str(rep)]) == 0
    assert "She keeps a ledger" in out.read_text() and "killed her son" not in out.read_text()
    assert "DROPPED" in rep.read_text()
    assert cli.main(["persona", "--campaign-dir", str(pcamp), "--npc", "Sylvira", "--chapter", "61"]) == 0
    assert "# Who Sylvira Savikas is, as of chapter 61" in capsys.readouterr().out


def test_cli_persona_refuses_to_write_into_its_sources(pcamp, capsys):
    rc = cli.main(["persona", "--campaign-dir", str(pcamp), "--npc", "Sylvira", "--chapter", "61",
                   "--out", str(pcamp / "summaries" / "x.md")])
    assert rc == 2 and "never writes into its sources" in capsys.readouterr().err


# ── leak check ──────────────────────────────────────────────────────────────


def _cases(kcamp):
    syl = dossier.select(dossier.read_dossiers(kcamp / "npcs"), ["Sylvira"])[0]
    cases = [c for c in knowledge.leak_cases(_resolved_list(kcamp), dossier.read_dossiers(kcamp / "npcs"))
             if knowledge.names_dossier(c.who, syl)]
    return cases


def _resolved_list(kcamp):
    return knowledge.resolve(_corpus(kcamp))


def _check(kcamp, answer, given="", chapter=64, target=None):
    return leakcheck.check(answer, given=given, cases=_cases(kcamp), corpus=_corpus(kcamp),
                           chapter=chapter, target_scene=target)


def test_a_sentence_with_every_content_word_of_a_hidden_beat_is_flagged(kcamp):
    (case,) = _cases(kcamp)
    assert case.beat_id == "064.01.b02"
    flags = _check(kcamp, "My son was slain. My son was slain; the party killed him.")
    secret = [f for f in flags if f.kind == leakcheck.KIND_SECRET]
    assert [(f.beat_id, f.sentence) for f in secret] == [("064.01.b02", "My son was slain; the party killed him.")]
    assert "states 064.01.b02: that the party killed her son" in secret[0].detail


def test_a_sentence_missing_two_content_words_is_not_flagged(kcamp):
    assert _check(kcamp, "I pray for my son. The party ate.") == []
    # one word short is flagged on purpose, even when innocent: the GM dismisses it
    assert [f.sentence for f in _check(kcamp, "The party killed no one.")] == ["The party killed no one."]


def test_a_case_after_the_target_scene_is_not_checked(kcamp):
    answer = "The party killed my son."
    assert _check(kcamp, answer, target="064.01")
    assert not _check(kcamp, answer, target="063.09")
    assert not _check(kcamp, answer, chapter=63)


def test_a_name_in_the_summaries_but_not_in_what_she_was_given_is_flagged(kcamp):
    (f,) = _check(kcamp, "I heard Asha laughing.", given="Sylvira. Daral.", chapter=64)
    assert (f.kind, f.name, f.first_chapter, f.future) == (leakcheck.KIND_NAME, "Asha", 64, False)
    assert f.sentence == "I heard Asha laughing." and "first in the summaries at ch 064" in f.detail


def test_a_name_in_what_she_was_given_or_outside_the_summaries_is_not_flagged(kcamp):
    assert _check(kcamp, "I heard Asha laughing.", given="Asha is a guard.") == []
    assert _check(kcamp, "I heard Zorblax laughing.", given="") == []
    assert _check(kcamp, "I am Sylvira. I'm tired.", given="Sylvira") == []


def test_a_name_first_used_after_the_freeze_chapter_is_marked_future(kcamp):
    (f,) = _check(kcamp, "Asha knows.", given="", chapter=61)
    assert f.name == "Asha" and f.future and f.first_chapter == 64
    assert "FUTURE" in leakcheck.render_flags([f])


def test_a_sentence_initial_word_is_not_a_name_unless_it_is_one(kcamp):
    assert _check(kcamp, "Honey is sweet. Not today.", given="") == []
    names = [f.name for f in _check(kcamp, "Daral and Asha spoke. Then the Order of Daral left.", given="")]
    assert names == ["Daral", "Asha"]


def test_a_multiword_name_is_accepted_when_each_word_was_given(kcamp):
    assert _check(kcamp, "Daz Asha came.", given="Daz and Asha") == []


def test_cli_leakcheck(kcamp, tmp_path, capsys):
    ans, giv, out = tmp_path / "a.txt", tmp_path / "g.txt", tmp_path / "f.md"
    ans.write_text("The party killed my son. Asha knew.")
    giv.write_text("Sylvira Savikas")
    base = ["leakcheck", "--campaign-dir", str(kcamp), "--npc", "Sylvira", "--chapter", "64",
            "--answer", str(ans), "--given", str(giv)]
    assert cli.main(base + ["--out", str(out)]) == 0
    text = out.read_text()
    assert "2 flag(s)" in text and "064.01.b02" in text and "'Asha'" in text
    assert cli.main(base + ["--target-scene", "063.01"]) == 0
    assert "1 flag(s)" in capsys.readouterr().out
    assert cli.main(base + ["--target-scene", "64"]) == 2


def test_a_secret_paraphrase_missing_one_word_is_still_flagged(kcamp):
    c = _corpus(kcamp)
    case = knowledge.LeakCase("Sylvira", "Sylvira Savikas", "064.01.b02", "064.01", 64, "", "sentence")
    flags = leakcheck.check("The party killed Moziqodo. I pray for my son.", given="", cases=[case],
                            corpus=c, chapter=64, target_scene="064.01")
    assert [f.sentence for f in flags if f.kind == leakcheck.KIND_SECRET] == ["The party killed Moziqodo."]
