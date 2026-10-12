"""Prototype 1 of the NPC agent: presence candidates and the knowledge horizon.

Fixtures are written in the published layout (``campaigns-public``): a
``## Summary`` prose section and scene headings with no ``NNN.SS`` id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.npc_agent import cli, corpus, dossier, horizon, presence, review, rulings

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


# ── candidates ─────────────────────────────────────────────────────────────


def test_matching_is_exact_case_sensitive_and_word_bounded(camp):
    c, _, table, syl = _setup(camp)
    ids = [x.item.item_id for x in presence.candidates(c, syl, table)]
    assert "057.02" not in ids  # "Sylviran" and lower-case "sylvira" do not name her


def test_signals(camp):
    c, _, table, syl = _setup(camp)
    by_id = {x.item.item_id: x for x in presence.candidates(c, syl, table)}
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
    got = {d.subject: len(presence.candidates(c, d, table)) for d in ds}
    assert got == {"Manshoon": 0, "Manshoon (Simulacrum)": 1}


def test_a_generic_form_is_withheld_until_ruled_safe(camp):
    c, ds, table, _ = _setup(camp)
    wick = dossier.select(ds, ["Wick"])[0]
    assert presence.candidates(c, wick, table) == []
    assert table.withheld_for(wick) == (("Wick", presence.GENERIC),)
    safe = presence.build_form_table(ds, frozenset({"wick"}), {"Wick": "safe"})
    assert [x.item.item_id for x in presence.candidates(c, wick, safe)] == ["061.m02"]


def test_a_form_owned_by_two_npcs_is_ambiguous_and_withheld(tmp_path):
    a = dossier.Dossier("A", "a", tmp_path, ("Vex",), (), 0, 0, 0, 0, 0, ())
    b = dossier.Dossier("B", "b", tmp_path, ("Vex", "Vex the Second"), (), 0, 0, 0, 0, 0, ())
    t = presence.build_form_table([a, b], frozenset(), {})
    assert t.status["Vex"] == presence.AMBIGUOUS
    assert t.linkable("Vex the Second")


# ── check against the dossier ──────────────────────────────────────────────


def test_check_passes_when_counts_agree(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    chk = presence.check_against_dossier(c, syl, cands, table)
    assert chk.ok, chk.lines


def test_check_reports_a_mismatch_and_repairs_nothing(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    wrong = dossier.Dossier(**{**syl.__dict__, "chapters": (57, 61), "n_moments": 4})
    chk = presence.check_against_dossier(c, wrong, cands, table)
    assert not chk.ok
    assert any(ln.startswith("MISMATCH chapters") for ln in chk.lines)
    assert any(ln.startswith("MISMATCH moments") for ln in chk.lines)


# ── rulings ────────────────────────────────────────────────────────────────


def _ids(camp):
    c, _, table, syl = _setup(camp)
    return {syl.subject: {x.item.item_id for x in presence.candidates(c, syl, table)}}


def _corpus(camp):
    return corpus.load_corpus(camp / "summaries")


def _load(camp, tmp_path, body):
    f = tmp_path / "r.yaml"
    f.write_text("version: 2\nnpcs:\n  Sylvira Savikas:\n" + body)
    return rulings.load_rulings(f, _ids(camp), _corpus(camp))["Sylvira Savikas"]


def test_rulings_load_and_empty_means_unruled(camp, tmp_path):
    r = _load(camp, tmp_path, '    items:\n      "061.02": present\n      "063.01":\n')
    assert r == rulings.NpcRulings(items={"061.02": "present"}, spans=())


@pytest.mark.parametrize(
    "body, needle",
    [
        ('    items:\n      "061.02": there\n', "is not one of"),
        ('    items:\n      "057.p02": present\n', "nor a scene in the corpus"),
        ('    items:\n      "061.01": mentioned\n', "'mentioned' needs an item that names"),
        ('    items:\n      "061.02": absent\n', "rule it 'mentioned', not 'absent'"),
        ('    spans:\n      - {from: "061.02", to: "057.01"}\n', "is after to"),
        ('    spans:\n      - {from: "061.09", to: "063.01"}\n', "'061.09' is not a scene"),
        ('    spans:\n      - {from: "057.01", to: "061.02", value: mentioned}\n', "value 'mentioned'"),
        ('    spans:\n      - {from: "057.01", to: "061.02", follows: Zalthor}\n', "appears nowhere in the summaries"),
        ('    spans:\n      - {from: "057.01", to: "061.01"}\n      - {from: "061.01", to: "063.01"}\n', "overlap"),
        ('    spans:\n      - {from: "057.01", to: "061.01", until: "x"}\n', "unknown key"),
        ('    "061.02": present\n', "expected a mapping with 'spans', 'items' and/or 'default'"),
    ],
)
def test_rulings_refuse_what_they_cannot_apply(camp, tmp_path, body, needle):
    with pytest.raises(rulings.RulingError, match=needle):
        _load(camp, tmp_path, body)


@pytest.mark.parametrize(
    "text, needle",
    [
        ('version: 2\nnpcs:\n  Ilvara:\n    items: {}\n', "not an NPC with a published dossier"),
        ('version: 1\nnpcs: {}\n', "version must be 2"),
        ('version: 2\nnpcs: {}\nextra: 1\n', "unknown top-level key"),
    ],
)
def test_the_file_itself_is_refused_when_it_cannot_be_applied(camp, tmp_path, text, needle):
    f = tmp_path / "r.yaml"
    f.write_text(text)
    with pytest.raises(rulings.RulingError, match=needle):
        rulings.load_rulings(f, _ids(camp), _corpus(camp))


def _effective(camp, r):
    return rulings.effective(r, _corpus(camp), _ids(camp)["Sylvira Savikas"])


def test_a_span_covers_its_scenes_and_the_prose_of_chapters_wholly_inside_it(camp, tmp_path):
    # GM ruling 2026-10-12: Glabbagool in the bag of holding counts as present.
    r = _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "063.01"}\n')
    eff = _effective(camp, r)
    assert eff["061.01"] == ("present", rulings.FROM_SPAN)  # names nobody; covered anyway
    assert eff["061.p01"] == ("present", rulings.FROM_SPAN)  # ch61 is wholly inside
    assert eff["061.m02"] == ("present", rulings.FROM_SPAN)  # a moment that does not name her
    assert eff["061.e01"] == ("present", rulings.FROM_SPAN)  # her own entry
    assert "057.p01" not in eff  # ch57 is outside


def test_a_span_starting_mid_chapter_does_not_cover_that_chapters_prose(camp, tmp_path):
    eff = _effective(camp, _load(camp, tmp_path, '    spans:\n      - {from: "057.02", to: "063.01"}\n'))
    assert eff["057.02"][0] == "present"
    assert "057.01" not in eff and "057.p01" not in eff and "057.m01" not in eff


def test_an_item_ruling_overrides_the_span(camp, tmp_path):
    body = ('    spans:\n      - {from: "057.01", to: "063.01", value: unsure, note: "in the bag"}\n'
            '    items:\n      "061.01": absent\n      "061.02": present\n')
    r = _load(camp, tmp_path, body)
    assert r.spans[0].note == "in the bag"
    eff = _effective(camp, r)
    assert eff["061.01"] == ("absent", rulings.FROM_ITEM)
    assert eff["061.02"] == ("present", rulings.FROM_ITEM)
    assert eff["057.01"] == ("unsure", rulings.FROM_SPAN)


def test_follows_is_kept_as_a_hint(camp, tmp_path):
    # GM ruling 2026-10-12: when the party splits, Glabbagool is with Zalthir.
    (camp / "summaries" / "061-session-colloquium.md").write_text(CH61 + "\nZalthir keeps the bag.\n")
    r = _load(camp, tmp_path, '    spans:\n      - {from: "057.01", to: "063.01", follows: Zalthir}\n')
    assert r.spans[0].follows == "Zalthir"


# ── horizon ────────────────────────────────────────────────────────────────


def _items(camp):
    return {it.item_id: it for it in _corpus(camp).items()}


def _item_rulings(d):
    return {k: (v, rulings.FROM_ITEM) for k, v in d.items()}


def test_a_companion_may_be_ruled_present_in_a_scene_that_never_names_him(camp, tmp_path):
    # Glabbagool, in the bag of holding, is named in 91 of the 240 scenes of his span.
    r = _load(camp, tmp_path, '    items:\n      "061.01": present\n      "061.02": present\n')
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), _effective(camp, r), 61, _items(camp))
    assert [x.item.item_id for x in h.witnessed] == ["061.01", "061.02"]
    assert h.witnessed[0].signals == ()
    assert "[ch 061 / 061.01] 061-session-colloquium.md:9 — not named in the text" in horizon.render_horizon(h)


def test_a_span_fills_the_horizon_and_says_so(camp, tmp_path):
    r = _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "061.02"}\n')
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), _effective(camp, r), 61, _items(camp))
    ids = [x.item.item_id for x in h.witnessed]
    assert ids[:2] == ["061.01", "061.02"] and "061.p01" in ids
    assert "— not named in the text, by span" in horizon.render_horizon(h)


def test_an_absent_scene_is_left_out(camp, tmp_path):
    r = _load(camp, tmp_path, '    spans:\n      - {from: "061.01", to: "061.02"}\n    items:\n      "061.01": absent\n')
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), _effective(camp, r), 61, _items(camp))
    assert "061.01" not in [x.item.item_id for x in h.witnessed + h.unruled + h.unsure + h.mentioned]


def test_an_unnamed_scene_after_the_chapter_stays_hidden(camp):
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), _item_rulings({"061.01": "present"}), 57,
                              _items(camp))
    assert h.witnessed == ()
    assert "Reunion" not in horizon.render_horizon(h)


def test_nothing_is_present_without_a_ruling(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    h = horizon.build_horizon(syl, cands, {}, 63)
    assert h.witnessed == () and len(h.unruled) == len(cands)


def test_horizon_cuts_at_the_chapter_and_sorts_by_ruling(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    ruled = _item_rulings({"061.02": "present", "057.01": "mentioned", "061.p01": "unsure", "063.01": "mentioned"})
    h = horizon.build_horizon(syl, cands, ruled, 61)
    assert [x.item.item_id for x in h.witnessed] == ["061.02"]
    assert [x.item.item_id for x in h.mentioned] == ["057.01"]
    assert [x.item.item_id for x in h.unsure] == ["061.p01"]
    assert h.later == 1  # chapter 63 is withheld, ruled or not
    text = horizon.render_horizon(h)
    assert "Moziqodo" not in text
    assert "[ch 061 / 061.02]" in text


def test_a_horizon_before_the_npc_appears_says_nothing_about_the_future(camp):
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), {}, 40)
    assert h.first_seen is None and h.later > 0
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
    assert '"061.02":   # scene' in tmpl
    # The template, filled in by nobody, is a valid ruling file with nothing ruled.
    loaded = rulings.load_rulings(out / "presence.template.yaml", _ids(camp), _corpus(camp))
    assert loaded == {"Sylvira Savikas": rulings.NpcRulings()}


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
    r.write_text('version: 2\nnpcs:\n  Sylvira Savikas:\n    items:\n      "061.02": present\n')
    rc = cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira",
                   "--chapter", "61", "--rulings", str(r)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Knowledge horizon — Sylvira Savikas, as of chapter 61" in out
    assert "Honey? I would never drink honey." in out


def test_the_ruling_file_is_never_written(camp, tmp_path):
    r = tmp_path / "r.yaml"
    r.write_text('version: 2\nnpcs: {}\n')
    before = r.read_bytes()
    cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira", "--chapter", "63", "--rulings", str(r),
              "--out", str(tmp_path / "h.md")])
    assert r.read_bytes() == before


# ── review page ────────────────────────────────────────────────────────────


def test_review_bundle_carries_candidates_and_every_item_of_their_chapters(camp):
    c, _, table, syl = _setup(camp)
    data = review.bundle(c, [(syl, presence.candidates(c, syl, table))], "test")
    assert [ch["n"] for ch in data["chapters"]] == [57, 61, 63]
    assert data["chapters"][0]["title"] == "Chapter 57"
    assert "057.02" in data["items"]  # names nobody, but a span may still reach it
    assert data["npcs"][0]["candidates"]["061.02"] == ["quoted", "headline", "named"]
    assert data["rulings_version"] == rulings.VERSION


def test_review_page_embeds_its_data_safely_and_loads_nothing_but_fonts(camp, tmp_path):
    import re

    (camp / "summaries" / "063-session-key.md").write_text(CH63 + "\n- A stray </script> in a bullet.\n")
    out = tmp_path / "page.html"
    assert cli.main(["review", "--campaign-dir", str(camp), "--npc", "Sylvira", "--out", str(out)]) == 0
    page = out.read_text()
    assert review.DATA_SLOT not in page
    assert page.count("</script>") == 1  # the data cannot close its own script block
    hosts = set(re.findall(r"https?://([^/\"' ]+)", page))
    assert hosts <= {"fonts.googleapis.com", "fonts.gstatic.com"}


def test_the_file_the_page_saves_is_a_ruling_file(camp, tmp_path):
    import json

    saved = {"version": 2, "npcs": {"Sylvira Savikas": {
        "spans": [{"from": "061.01", "to": "063.01", "value": "present", "follows": "Daz"}],
        "items": {"057.01": "mentioned"}}}}
    f = tmp_path / "presence.json"
    f.write_text(json.dumps(saved, indent=2))
    r = rulings.load_rulings(f, _ids(camp), _corpus(camp))["Sylvira Savikas"]
    assert r.spans[0].follows == "Daz" and r.items == {"057.01": "mentioned"}


def test_review_refuses_to_write_into_its_sources(camp, capsys):
    rc = cli.main(["review", "--campaign-dir", str(camp), "--all", "--out", str(camp / "npcs" / "page.html")])
    assert rc == 2
    assert not (camp / "npcs" / "page.html").exists()


# ── NPC default ────────────────────────────────────────────────────────────


def test_a_default_rules_every_candidate_nothing_else_reaches(camp, tmp_path):
    # Sylvira: present in a few of the passages naming her, talked about in the rest.
    r = _load(camp, tmp_path, '    default: mentioned\n    items:\n      "061.02": present\n')
    eff = _effective(camp, r)
    assert eff["061.02"] == ("present", rulings.FROM_ITEM)
    assert eff["057.01"] == ("mentioned", rulings.FROM_DEFAULT)
    assert "061.01" not in eff  # not a candidate: a default never reaches it


def test_a_span_outranks_the_default(camp, tmp_path):
    r = _load(camp, tmp_path, '    default: mentioned\n    spans:\n      - {from: "061.01", to: "061.02"}\n')
    eff = _effective(camp, r)
    assert eff["061.02"] == ("present", rulings.FROM_SPAN)
    assert eff["057.01"] == ("mentioned", rulings.FROM_DEFAULT)


def test_a_default_cannot_be_present(camp, tmp_path):
    with pytest.raises(rulings.RulingError, match="default 'present' is not one of"):
        _load(camp, tmp_path, '    default: present\n')


def test_the_horizon_labels_what_the_default_ruled(camp, tmp_path):
    r = _load(camp, tmp_path, '    default: mentioned\n    items:\n      "061.02": present\n')
    c, _, table, syl = _setup(camp)
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), _effective(camp, r), 61, _items(camp))
    assert h.unruled == ()
    assert "[ch 057 / 057.01] 057-session-council.md:13 (by default) — scene" in horizon.render_horizon(h)
