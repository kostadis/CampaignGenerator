"""Prototype 1 of the NPC agent: presence candidates and the knowledge horizon.

Fixtures are written in the published layout (``campaigns-public``): a
``## Summary`` prose section and scene headings with no ``NNN.SS`` id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.npc_agent import cli, corpus, dossier, horizon, presence, rulings

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


def test_rulings_load_and_empty_means_unruled(camp, tmp_path):
    f = tmp_path / "r.yaml"
    f.write_text('version: 1\nnpcs:\n  Sylvira Savikas:\n    "061.02": present\n    "063.01":\n')
    assert rulings.load_rulings(f, _ids(camp)) == {"Sylvira Savikas": {"061.02": "present"}}


@pytest.mark.parametrize(
    "body, needle",
    [
        ('version: 1\nnpcs:\n  Sylvira Savikas:\n    "061.02": there\n', "is not one of"),
        ('version: 1\nnpcs:\n  Sylvira Savikas:\n    "057.p02": present\n', "nor a scene in the corpus"),
        ('version: 1\nnpcs:\n  Sylvira Savikas:\n    "061.01": mentioned\n', "'mentioned' needs an item that names"),
        ('version: 1\nnpcs:\n  Ilvara:\n    "002.01": present\n', "not an NPC with a published dossier"),
        ('version: 2\nnpcs: {}\n', "version must be 1"),
        ('version: 1\nnpcs: {}\nextra: 1\n', "unknown top-level key"),
    ],
)
def test_rulings_refuse_what_they_cannot_apply(camp, tmp_path, body, needle):
    f = tmp_path / "r.yaml"
    f.write_text(body)
    with pytest.raises(rulings.RulingError, match=needle):
        rulings.load_rulings(f, _ids(camp), _scene_ids(camp))


def _scene_ids(camp):
    c = corpus.load_corpus(camp / "summaries")
    return frozenset(it.item_id for it in c.items() if it.kind == corpus.SCENE)


def test_a_companion_may_be_ruled_present_in_a_scene_that_never_names_him(camp, tmp_path):
    # Glabbagool, in the bag of holding, is named in 91 of the 240 scenes of his span.
    f = tmp_path / "r.yaml"
    f.write_text('version: 1\nnpcs:\n  Sylvira Savikas:\n    "061.01": present\n    "061.02": present\n')
    ruled = rulings.load_rulings(f, _ids(camp), _scene_ids(camp))
    assert ruled == {"Sylvira Savikas": {"061.01": "present", "061.02": "present"}}

    c, _, table, syl = _setup(camp)
    items = {it.item_id: it for it in c.items()}
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), ruled["Sylvira Savikas"], 61, items)
    assert [x.item.item_id for x in h.witnessed] == ["061.01", "061.02"]
    assert h.witnessed[0].signals == ()
    assert "[ch 061 / 061.01] 061-session-colloquium.md:9 — not named in the text" in horizon.render_horizon(h)


def test_an_unnamed_scene_after_the_chapter_stays_hidden(camp, tmp_path):
    c, _, table, syl = _setup(camp)
    items = {it.item_id: it for it in c.items()}
    h = horizon.build_horizon(syl, presence.candidates(c, syl, table), {"061.01": "present"}, 57, items)
    assert h.witnessed == ()
    assert "Reunion" not in horizon.render_horizon(h)


# ── horizon ────────────────────────────────────────────────────────────────


def test_nothing_is_present_without_a_ruling(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    h = horizon.build_horizon(syl, cands, {}, 63)
    assert h.witnessed == () and len(h.unruled) == len(cands)


def test_horizon_cuts_at_the_chapter_and_sorts_by_ruling(camp):
    c, _, table, syl = _setup(camp)
    cands = presence.candidates(c, syl, table)
    ruled = {"061.02": "present", "057.01": "mentioned", "061.p01": "unsure", "063.01": "mentioned"}
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
    assert rulings.load_rulings(out / "presence.template.yaml", _ids(camp)) == {"Sylvira Savikas": {}}


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
    r.write_text('version: 1\nnpcs:\n  Sylvira Savikas:\n    "061.02": present\n')
    rc = cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira",
                   "--chapter", "61", "--rulings", str(r)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Knowledge horizon — Sylvira Savikas, as of chapter 61" in out
    assert "Honey? I would never drink honey." in out


def test_the_ruling_file_is_never_written(camp, tmp_path):
    r = tmp_path / "r.yaml"
    r.write_text('version: 1\nnpcs: {}\n')
    before = r.read_bytes()
    cli.main(["horizon", "--campaign-dir", str(camp), "--npc", "Sylvira", "--chapter", "63", "--rulings", str(r),
              "--out", str(tmp_path / "h.md")])
    assert r.read_bytes() == before
