"""Annotate, never rewrite (spec 033 US4, T034, FR-019..FR-021).

The detectors run over a drafted document and code appends the later evidence under the line it bears
on, verbatim. A unit scenario (an in-memory campaign, so each detector has exactly one trigger) and an
end-to-end run through the real CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import annotate, notes, schema
from tests import conftest_state as cs

# ── A scenario small enough to read ─────────────────────────────────────────

REGISTRY = {
    "version": 1, "campaign": "t",
    "entities": [
        {"name": "Jimjar", "type": "npc"},
        {"name": "Kalan", "type": "npc"},
        {"name": "Alaundo", "type": "npc"},
        {"name": "Thorin", "type": "npc", "aliases": ["Thorin Giantfriend"]},
        {"name": "The Avowed", "type": "faction", "aliases": ["Avowed"]},
        {"name": "Mantol-Derith", "type": "location"},
    ],
}
PLAYERS = {"players": [{"id": "joe", "name": "Joe", "plays": ["Thorin Giantfriend"]}]}
CHAPTER_TEXT = {
    26: 'Jimjar travels with the party. "We go together," said Jimjar.',
    30: "Mantol-Derith is a trading post.",
    48: "Jimjar left the party at Mantol-Derith.",
    55: "Mantol-Derith is under siege.",
    65: "Kalan fled the tower. The Avowed regroup.",
    67: "Kalan is reinstated. Alaundo is dead.",
    70: "The Avowed muster at dawn.",
}


def _chapter(n: int) -> notes.Chapter:
    targets = {f"{n:03d}.01", "npcs", "end"}
    return notes.Chapter(n, Path(f"{n:03d}-x.md"), CHAPTER_TEXT[n], targets)


def _world(tag, subject, text, ch):
    body = f"- [{tag}] **{subject}** — {text} [ch {ch:03d} / {ch:03d}.01]"
    return notes.Note("world", body, ch, "c", tag=tag, subject=subject)


def _row(name, status, ch, loc="—", disp="—"):
    cite = f"[ch {ch:03d} / {ch:03d}.01]"
    return notes.Note("status_row", f"- {name} | {status} | {loc} | {disp} {cite}", ch, "c",
                      subject=name, status=status, location=loc, disposition=disp, cite=cite)


JIMJAR_LATER = _world("NPC", "Jimjar", "Left the party and trades in Mantol-Derith.", 48)
THREAT_LATER = _world("THREAT", "Mantol-Derith", "The post is under siege.", 55)
RESULTS = [notes.CheckedChunk("026-070", [
    _world("NPC", "Jimjar", "Travels with the party.", 26),
    JIMJAR_LATER,
    THREAT_LATER,
    _row("Kalan", "Missing", 65, "the tower"),
    _row("Kalan", "Alive", 67, "the tower", "Reinstated"),
    _row("Alaundo", "Dead", 67),
])]


@pytest.fixture
def ev(tmp_path):
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
    return annotate.load_evidence(
        RESULTS, [_chapter(n) for n in CHAPTER_TEXT], tmp_path / "registry.yaml", tmp_path / "players.yaml")


def run(ev, *body):
    """Annotate a document made of ``body`` lines; return the Result."""
    return annotate.annotate_text("\n".join(body) + "\n", ev)


def under(result, line):
    """The annotation sub-bullets directly under ``line`` in the annotated document."""
    lines = result.text.split("\n")
    i = lines.index(line)
    out = []
    for ln in lines[i + 1:]:
        if not ln.startswith("  - "):
            break
        out.append(ln[4:])
    return out


class TestStale:
    LINE = "- **Jimjar** — Travels with the party as a companion. [ch 026 / 026.01]"

    def test_a_later_note_about_the_subject_is_appended_verbatim(self, ev):
        r = run(ev, "## Party", "", self.LINE)
        assert under(r, self.LINE) == [
            f"{schema.LATER} **Jimjar** — Left the party and trades in Mantol-Derith. [ch 048 / 048.01]"]

    def test_the_line_itself_is_untouched(self, ev):
        r = run(ev, "## Party", "", self.LINE)
        assert self.LINE in r.text.split("\n")

    def test_no_annotation_when_the_line_cites_the_latest_chapter(self, ev):
        line = "- **Jimjar** — Trades in Mantol-Derith. [ch 048 / 048.01]"
        assert under(run(ev, "## Party", "", line), line) == []


class TestMentionedStatus:
    def test_a_status_change_after_the_claims_citation_is_a_since(self, ev):
        line = "- **The Avowed** — Their captain reports that Kalan fled the tower. [ch 065 / 065.01]"
        r = run(ev, "## Factions and Powers", "", line)
        assert under(r, line) == [f"{schema.SINCE} **Kalan** — Alive; the tower; Reinstated [ch 067 / 067.01]"]

    def test_judged_per_claim_so_a_later_citation_elsewhere_on_the_line_cannot_hide_it(self, ev):
        line = ("- **The Avowed** — Kalan fled the tower. [ch 065 / 065.01] "
                "They muster at dawn. [ch 070 / 070.01]")
        got = under(run(ev, "## Factions and Powers", "", line), line)
        assert got == [f"{schema.SINCE} **Kalan** — Alive; the tower; Reinstated [ch 067 / 067.01]"]

    def test_a_dead_npc_with_no_earlier_status_row_is_no_news(self, ev):
        line = "- **The Avowed** — Alaundo spoke for them once. [ch 065 / 065.01]"
        assert under(run(ev, "## Factions and Powers", "", line), line) == []

    def test_an_unchanged_status_is_no_news(self, ev):
        line = "- **The Avowed** — Kalan is back at the tower. [ch 067 / 067.01]"
        assert under(run(ev, "## Factions and Powers", "", line), line) == []

    def test_the_subject_of_the_line_and_player_characters_are_not_mentions(self, ev):
        line = "- **Kalan** — Thorin Giantfriend met Kalan at the tower. [ch 065 / 065.01]"
        r = run(ev, "## Factions and Powers", "", line)
        assert not [a for a in under(r, line) if a.startswith(schema.SINCE)]


class TestCrossSection:
    OLD = "- **Mantol-Derith** — A trading post the party passed through. [ch 030 / 030.01]"
    NEW = "- **Mantol-Derith** — Under siege, its roads cut. [ch 055 / 055.01]"

    def test_the_older_line_points_at_the_newer_section(self, ev):
        r = run(ev, "## Locations", "", self.OLD, "", "## Active Threats and Open Pressures", "", self.NEW)
        got = under(r, self.OLD)
        assert f"{schema.LATER} see Active Threats and Open Pressures: **Mantol-Derith** — Under siege, its roads cut. [ch 055 / 055.01]" in got

    def test_the_newer_line_is_not_annotated_for_the_older(self, ev):
        r = run(ev, "## Locations", "", self.OLD, "", "## Active Threats and Open Pressures", "", self.NEW)
        assert not [a for a in under(r, self.NEW) if "see Locations" in a]


class TestUnverified:
    def test_a_quotation_not_verbatim_in_the_chapter_it_cites(self, ev):
        line = '- **Jimjar** — He swore "we go home at dawn" to the party. [ch 048 / 048.01]'
        got = under(run(ev, "## Party", "", line), line)
        assert [a for a in got if a.startswith(schema.UNVERIFIED) and "we go home at dawn" in a]

    def test_a_quotation_from_another_chapter_is_not_the_cited_chapters(self, ev):
        # the words are real, but chapter 26 said them; the line cites chapter 48
        line = '- **Jimjar** — "We go together," he said. [ch 048 / 048.01]'
        assert [a for a in under(run(ev, "## Party", "", line), line) if a.startswith(schema.UNVERIFIED)]

    def test_a_verbatim_quotation_is_clean(self, ev):
        line = '- **Jimjar** — "We go together," he said. [ch 026 / 026.01]'
        assert not [a for a in under(run(ev, "## Party", "", line), line) if a.startswith(schema.UNVERIFIED)]

    def test_a_citation_that_does_not_resolve(self, ev):
        line = "- **Kalan** — He guards the tower. [ch 065 / 065.09]"
        got = under(run(ev, "## Factions and Powers", "", line), line)
        assert [a for a in got if a.startswith(schema.UNVERIFIED) and "065.09" in a]

    def test_a_citation_to_a_chapter_outside_the_range(self, ev):
        line = "- **Kalan** — He guards the tower. [ch 099 / 099.01]"
        assert [a for a in under(run(ev, "## Factions and Powers", "", line), line) if a.startswith(schema.UNVERIFIED)]


class TestPlayerCharacters:
    LINE = "- **Thorin Giantfriend** — A dwarf who fights beside them. [ch 026 / 026.01]"

    def test_a_player_character_listed_as_a_companion_is_removed(self, ev):
        r = run(ev, "## Party", "", "### Companions", "", self.LINE, "- **Jimjar** — Along for the ride. [ch 048 / 048.01]")
        assert self.LINE not in r.text
        assert "**Jimjar**" in r.text
        assert [(x.section, x.text) for x in r.removed] == [("Party", self.LINE)]
        assert r.counts()["removed"] == 1

    def test_the_same_line_outside_an_npc_group_stays(self, ev):
        r = run(ev, "## Party", "", "### The party", "", self.LINE)
        assert self.LINE in r.text and r.removed == []


class TestWhatIsNeverScanned:
    """FR-019: Key NPCs is fixed in the dossiers; the code-owned sections carry their own later evidence."""

    STALE = "- **Jimjar** — Travels with the party. [ch 026 / 026.01]"

    @pytest.mark.parametrize("heading", [
        "## Key NPCs", "## Canon Events Timeline", "## Completed Encounters & Quests",
        "## NPC Current States", "## Audit: Tracking Claims",
    ])
    def test_no_entry_and_no_annotation(self, ev, heading):
        doc = [heading, "", self.STALE, '- **Kalan** — "invented words" [ch 099 / 099.01]']
        assert annotate.parse_entries(doc, ev) == []
        r = run(ev, *doc)
        assert r.hits == [] and r.text == "\n".join(doc) + "\n"

    def test_a_player_character_line_in_key_npcs_is_left_alone(self, ev):
        line = "- **Thorin Giantfriend** — A dwarf. [ch 026 / 026.01]"
        assert line in run(ev, "## Key NPCs", "", "### Companions", "", line).text

    def test_the_same_line_in_a_scanned_section_is_annotated(self, ev):
        assert under(run(ev, "## Party", "", self.STALE), self.STALE)


class TestTheReport:
    def test_every_hit_and_removal_is_listed_with_its_evidence(self, ev, tmp_path):
        stale = "- **Jimjar** — Travels with the party. [ch 026 / 026.01]"
        pc = "- **Thorin Giantfriend** — A dwarf. [ch 026 / 026.01]"
        r = run(ev, "## Party", "", "### Companions", "", pc, stale)
        path = annotate.write_report(tmp_path, "world_state", r)
        md = path.read_text(encoding="utf-8")
        assert path.name == "annotations.md"
        assert stale in md and "Left the party and trades in Mantol-Derith." in md
        assert pc in md and "player character" in md
        assert "1 later, 0 since, 0 unverified on 1 lines; 1 lines removed." in md

    def test_two_documents_share_the_report_without_overwriting_each_other(self, ev, tmp_path):
        r = run(ev, "## Party", "", "- **Jimjar** — Travels with the party. [ch 026 / 026.01]")
        annotate.write_report(tmp_path, "world_state", r)
        annotate.write_report(tmp_path, "campaign_state", run(ev, "## Party Current Situation", "", "- Nothing. [ch 026 / 026.01]"))
        md = (tmp_path / annotate.REPORT_FILE).read_text(encoding="utf-8")
        assert "## world_state" in md and "## campaign_state" in md
        assert set(annotate.read_counts(tmp_path)) == {"world_state", "campaign_state"}
        assert annotate.read_counts(tmp_path)["world_state"]["later"] == 1

    def test_read_counts_of_nothing_is_empty(self, tmp_path):
        assert annotate.read_counts(tmp_path) == {}


# ── End to end: the real CLI over the fixture campaign ──────────────────────

DRAFT = {
    "## Party": (
        "## Party\n\n### Companions\n\n- **Thorin Giantfriend** — A dwarf at the party's side. [ch 003 / 003.01]\n\n"
        "### Dealings\n\n- The party bargained with Ilvara Mizzrym. [ch 002 / 002.02]\n"
    ),
    "## Locations": "## Locations\n\n- **Velkynvelve** — A drow outpost. [ch 002 / locations]\n",
}


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    fm = cs.fake_models(monkeypatch)
    assert cs.run_cli(cs.extract_args(root))[0] == 0
    fm.prose_override.update(DRAFT)
    rc, out, err = cs.run_cli(["synth", "world_state", *cs.common(root), "--fallback-npc-lines"])
    assert rc == 0, err
    return root, out


def draft_path(root, doc="world_state"):
    return cs.range_dir(root) / schema.STATE_DIR / "drafts" / f"{doc}.draft.md"


def test_synth_annotates_the_draft_and_reports_the_counts(built):
    root, out = built
    text = draft_path(root).read_text(encoding="utf-8")
    assert "- **Velkynvelve** — A drow outpost. [ch 002 / locations]\n" \
           f"  - {schema.LATER} **Velkynvelve** — The party rests at its gate. [ch 005 / end]\n" in text
    assert f"  - {schema.SINCE} **Ilvara Mizzrym** — Dead; the doorway [ch 004 / 004.02]\n" in text
    assert "A dwarf at the party's side" not in text
    assert "annotations: 1 later, 1 since, 0 unverified; 1 removed" in out


def test_the_annotated_line_is_the_models_line_unchanged(built):
    root, _ = built
    run_dir = next((cs.range_dir(root) / schema.STATE_DIR / "runs").iterdir())
    raw = (run_dir / "world_state.locations.out.md").read_text(encoding="utf-8")
    line = "- **Velkynvelve** — A drow outpost. [ch 002 / locations]"
    assert line in raw and line in draft_path(root).read_text(encoding="utf-8")


def test_the_annotations_report_lists_every_hit(built):
    root, _ = built
    md = (cs.range_dir(root) / schema.STATE_DIR / "drafts" / "annotations.md").read_text(encoding="utf-8")
    assert "## world_state" in md and "A drow outpost." in md and "Dead; the doorway" in md
    assert "Removed" in md and "Thorin Giantfriend" in md
    record = next((cs.range_dir(root) / schema.STATE_DIR / "runs").iterdir()) / "record.json"
    assert '"annotations"' in record.read_text(encoding="utf-8")


def test_key_npcs_and_the_code_sections_carry_no_annotation(built):
    root, _ = built
    text = draft_path(root).read_text(encoding="utf-8")
    sec = text.split("## Key NPCs")[1].split("\n## ")[0]
    assert sec.strip() and schema.LATER not in sec and schema.SINCE not in sec and schema.UNVERIFIED not in sec
    assert "## Canon Events Timeline" in text
    tl = text.split("## Canon Events Timeline")[1].split("\n## ")[0]
    assert schema.LATER not in tl


def test_annotate_is_idempotent_and_never_stacks(built):
    root, _ = built
    before = draft_path(root).read_text(encoding="utf-8")
    for _ in range(2):
        rc, out, err = cs.run_cli(["annotate", "world_state", *cs.common(root)])
        assert rc == 0, err
        assert "annotations: 1 later, 1 since, 0 unverified; 0 removed" in out  # the removal already happened
        assert draft_path(root).read_text(encoding="utf-8") == before


def test_dry_run_prints_the_hits_and_writes_nothing(built):
    root, _ = built
    drafts = cs.range_dir(root) / schema.STATE_DIR / "drafts"
    snap = {p: p.read_bytes() for p in drafts.rglob("*") if p.is_file()}
    rc, out, err = cs.run_cli(["annotate", "world_state", *cs.common(root), "--dry-run"])
    assert rc == 0, err
    assert "A drow outpost." in out and "nothing written" in out
    assert {p: p.read_bytes() for p in drafts.rglob("*") if p.is_file()} == snap


def test_a_hand_edit_to_a_line_survives_a_reannotate(built):
    root, _ = built
    p = draft_path(root)
    p.write_text(p.read_text(encoding="utf-8").replace("A drow outpost.", "A drow outpost (GM: fixed)."), encoding="utf-8")
    assert cs.run_cli(["annotate", "world_state", *cs.common(root)])[0] == 0
    assert "A drow outpost (GM: fixed)." in p.read_text(encoding="utf-8")


def test_refuses_without_a_draft(tmp_path, monkeypatch):
    root = cs.state_campaign(tmp_path)
    cs.fake_models(monkeypatch)
    assert cs.run_cli(cs.extract_args(root))[0] == 0
    rc, out, err = cs.run_cli(["annotate", "world_state", *cs.common(root)])
    assert rc == 2 and "no draft for world_state" in err and "summary_native synth world_state" in err


def test_refuses_when_the_notes_are_stale(built):
    root, _ = built
    reg = root / "docs" / "entity_registry.yaml"
    reg.write_text(reg.read_text(encoding="utf-8") + "  - name: Newcomer\n    type: npc\n", encoding="utf-8")
    rc, out, err = cs.run_cli(["annotate", "world_state", *cs.common(root)])
    assert rc == 2 and "stale" in err and "summary_native extract" in err


def test_party_and_planning_are_not_annotatable():
    from pipelines.summary_native.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["annotate", "party"])
