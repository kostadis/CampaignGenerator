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


def test_every_document_is_annotatable():
    """Spec 034 T012: party and planning build from the checked notes, so ``annotate`` accepts them."""
    from pipelines.summary_native.cli import build_parser

    for doc in ("world_state", "campaign_state", "party", "planning"):
        assert build_parser().parse_args(["annotate", doc]).doc == doc


# ── Spec 034 US5 (T043/T044): party and planning drafts ─────────────────────

#: A party draft as ``synth party`` builds it: the level line and pointer are code's, a body line is the
#: model's (a paragraph or a bullet), and the candidate events sit in the subsection code places.
PARTY_DOC = """\
<!-- summary_native draft | doc: party | range: ch026-070 | record: runs/x/record.json -->
> **How to read this document.** A blockquote.

## Party Overview
The party are camped by the tower with Kalan. [ch 065 / 065.01]

## Characters
### Thorin Giantfriend

Level: 9 [ch 026 / 026.01]

Thorin travelled with Kalan, who fled the tower. [ch 065 / 065.01]
Kalan said "we shall never yield" to him. [ch 065 / 065.01]
- **Thorin Giantfriend** — A dwarf who holds the line. [ch 026 / 026.01]
- A bullet the model wrote. [ch 026 / 026.01]

#### Candidate Arc Score Events

- Thorin holds the line [ch 026 / 026.01] — trigger: "Thorin holds the line against the tide"
- Thorin falls back [ch 099 / 099.09] — trigger: "words in no chapter at all"

_Full notes: reference/party.md_

## Party Dynamics
Thorin and Kalan are wary allies. [ch 065 / 065.01]
"""

#: A planning draft: the tracker and the dossier-sourced NPC entries are code's; the unratified and dormant
#: blocks are code-built from the notes verbatim.
PLANNING_DOC = """\
<!-- summary_native draft | doc: planning | range: ch026-070 | record: runs/x/record.json -->
> **How to read this document.** A blockquote.

## Threat Tracker

| Score | Subject | Candidate events | Trigger text |
|---|---|---|---|
| kalan-arc | Kalan | Kalan fled [ch 065 / 065.01] — trigger: "never again" | docs/mechanics/kalan-arc.md |

## NPC Dossiers

### Kalan
Status and location: At the tower. [ch 065 / 065.01]
Goals: He said "invented words" for nobody. [ch 065 / 065.01]

→ docs/npcs/kalan.md

## Faction States

### The Avowed
The Avowed regroup at the tower. [ch 065 / 065.01]
- **Thorin Giantfriend** — Joined the Avowed. [ch 026 / 026.01]

### Thorin Giantfriend
A faction block the model named for a player character. [ch 026 / 026.01]

## Active Plots

### The Carver's march
The march gathers. [ch 026 / 026.01]

### Dormant threads
- **Jimjar** — A dormant line that would be stale if scanned. [ch 026 / 026.01]

### Unratified thread notes (not yet ruled on)
_1 checked thread notes are not in the thread registry._
- [OPENED] **Jimjar** — An unratified note that would be stale if scanned. [ch 026 / 026.01]
- A bare unratified line. [ch 026 / 026.01]

## DM Notes
_Suggestions for the GM, not events._
- Ask Kalan about the tower. [ch 065 / 065.01]
"""


@pytest.fixture
def ev2(tmp_path):
    """The scenario above plus a faction note, so a faction block can go stale."""
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
    results = [notes.CheckedChunk("026-070", [*RESULTS[0].notes, _world("FACTION", "The Avowed", "They muster at dawn.", 70)])]
    return annotate.load_evidence(
        results, [_chapter(n) for n in CHAPTER_TEXT], tmp_path / "registry.yaml", tmp_path / "players.yaml")


def entries_of(doc: str, ev):
    return annotate.parse_entries(doc.split("\n"), ev)


class TestPartyDraft:
    def test_a_characters_sub_entries_take_the_three_hash_name_as_subject(self, ev2):
        es = [e for e in entries_of(PARTY_DOC, ev2) if e.section == "## Characters"]
        assert {e.group for e in es} == {"Thorin Giantfriend"}
        assert {e.subject for e in es if "A bullet the model wrote" in e.text} == {"Thorin"}  # canonical, via the registry

    def test_prose_lines_under_a_character_are_entries_but_the_level_line_and_pointer_are_not(self, ev2):
        texts = [e.text for e in entries_of(PARTY_DOC, ev2) if e.section == "## Characters"]
        assert "Thorin travelled with Kalan, who fled the tower. [ch 065 / 065.01]" in texts
        assert not any(t.startswith("Level:") or t.startswith("_Full notes") for t in texts)

    def test_the_candidate_subsection_is_never_scanned(self, ev2):
        texts = [e.text for e in entries_of(PARTY_DOC, ev2)]
        assert not any("Thorin holds the line [ch" in t or "Thorin falls back" in t for t in texts)

    def test_the_scanning_resumes_after_the_candidate_subsection(self):
        # the subsection ends at the next heading of any level
        doc = f"## Characters\n### A\n{schema.ARC_HEADING}\n- one [ch 026 / 026.01]\n### B\n- two [ch 026 / 026.01]\n"
        got = annotate.parse_entries(doc.split("\n"), SimpleNamespaceEv())
        assert [e.text for e in got] == ["- two [ch 026 / 026.01]"]

    def test_a_companion_whose_status_changed_later_gets_a_since_under_the_prose_line(self, ev2):
        r = annotate.annotate_text(PARTY_DOC, ev2)
        line = "Thorin travelled with Kalan, who fled the tower. [ch 065 / 065.01]"
        assert under(r, line) == [f"{schema.SINCE} **Kalan** — Alive; the tower; Reinstated [ch 067 / 067.01]"]

    def test_a_quote_that_is_not_verbatim_is_unverified_and_the_line_keeps_its_text(self, ev2):
        r = annotate.annotate_text(PARTY_DOC, ev2)
        line = 'Kalan said "we shall never yield" to him. [ch 065 / 065.01]'
        assert line in r.text.split("\n")
        assert [a for a in under(r, line) if a.startswith(schema.UNVERIFIED) and "we shall never yield" in a]

    def test_a_player_character_in_a_characters_section_is_never_removed(self, ev2):
        r = annotate.annotate_text(PARTY_DOC, ev2)
        assert r.removed == []
        assert "- **Thorin Giantfriend** — A dwarf who holds the line. [ch 026 / 026.01]" in r.text.split("\n")
        assert "### Thorin Giantfriend" in r.text

    def test_the_candidate_lines_the_level_line_and_the_pointer_carry_no_annotation(self, ev2):
        r = annotate.annotate_text(PARTY_DOC, ev2)
        lines = r.text.split("\n")
        for needle in ("Level: 9 [ch 026 / 026.01]", "- Thorin falls back [ch 099 / 099.09]", "_Full notes: reference/party.md_"):
            i = next(n for n, ln in enumerate(lines) if ln.startswith(needle))
            assert not annotate.ANNOTATION_RE.match(lines[i + 1])

    def test_an_invalid_citation_in_a_character_line_is_unverified(self, ev2):
        doc = "## Characters\n### Thorin Giantfriend\nHe holds. [ch 026 / 026.77]\n"
        r = annotate.annotate_text(doc, ev2)
        assert [a for a in under(r, "He holds. [ch 026 / 026.77]") if a.startswith(schema.UNVERIFIED) and "026.77" in a]

    def test_the_overview_and_dynamics_are_scanned_like_any_other_prose_section(self, ev2):
        r = annotate.annotate_text(PARTY_DOC, ev2)
        for line in ("The party are camped by the tower with Kalan. [ch 065 / 065.01]",
                     "Thorin and Kalan are wary allies. [ch 065 / 065.01]"):
            assert [a for a in under(r, line) if a.startswith(schema.SINCE) and "**Kalan**" in a], line


# ── #527: subject-less party prose is about the whole party ─────────────────

PARTY_CHAPTERS = {2: "The party holds the gate of Brindol.", 4: "The party lost the gate of Brindol.",
                  5: "Thorin took the gate."}


def _party_note(text, ch, subject="Party", tag=None):
    return notes.Note("party", f"- **{subject}** — {text} [ch {ch:03d} / {ch:03d}.01]", ch, "c", tag=tag, subject=subject)


@pytest.fixture
def evp(tmp_path):
    (tmp_path / "registry.yaml").write_text(yaml.safe_dump(REGISTRY), encoding="utf-8")
    (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
    results = [notes.CheckedChunk("002-005", [
        _party_note("Hold the gate of Brindol.", 2),
        _party_note("Lost the gate of Brindol.", 4),
        _party_note("Thorin took the gate.", 5, subject="Thorin Giantfriend"),  # one character's, not the party's
        _world("NPC", "Thorin", "Holds the gate alone.", 5),
    ])]
    chapters = [notes.Chapter(n, Path(f"{n:03d}-x.md"), t, {f"{n:03d}.01", "end"}) for n, t in PARTY_CHAPTERS.items()]
    return annotate.load_evidence(results, chapters, tmp_path / "registry.yaml", tmp_path / "players.yaml")


class TestPartyProseSubject:
    OVERVIEW = "The party holds the gate of Brindol. [ch 002 / 002.01]"

    def test_a_subjectless_overview_line_is_stale_against_a_later_whole_party_note(self, evp):
        doc = f"## Party Overview\n{self.OVERVIEW}\n"
        r = annotate.annotate_text(doc, evp)
        assert under(r, self.OVERVIEW) == [f"{schema.LATER} **Party** — Lost the gate of Brindol. [ch 004 / 004.01]"]
        # the line's text is untouched: dropping the annotation leaves the draft as it was
        assert annotate.strip_annotations(r.text.split("\n")) == doc.split("\n")

    def test_the_subject_is_the_schemas_party_token_for_overview_and_dynamics(self, evp):
        doc = "## Party Overview\nOne. [ch 002 / 002.01]\n\n## Party Dynamics\nTwo. [ch 002 / 002.01]\n"
        es = annotate.parse_entries(doc.split("\n"), evp)
        assert [(e.section, e.subject) for e in es] == [("## Party Overview", schema.PARTY_SUBJECT),
                                                        ("## Party Dynamics", schema.PARTY_SUBJECT)]

    def test_a_dynamics_line_with_a_bold_character_keeps_that_character(self, evp):
        line = "**Thorin Giantfriend** keeps the gate. [ch 002 / 002.01]"
        (e,) = annotate.parse_entries(["## Party Dynamics", line], evp)
        assert e.subject == "Thorin" and not e.implicit
        r = annotate.annotate_text(f"## Party Dynamics\n{line}\n", evp)
        # compared with Thorin's own note, not the whole party's
        assert under(r, line) == [f"{schema.LATER} **Thorin** — Holds the gate alone. [ch 005 / 005.01]"]

    def test_a_line_under_a_group_keeps_the_group(self, evp):
        (e,) = annotate.parse_entries(["## Party Overview", "### Thorin Giantfriend", "He holds. [ch 002 / 002.01]"], evp)
        assert e.subject == "Thorin" and not e.implicit

    def test_a_registry_entity_aliased_party_does_not_capture_the_whole_party(self, tmp_path):
        reg = {**REGISTRY, "entities": [*REGISTRY["entities"], {"name": "The Company", "type": "faction", "aliases": ["party"]}]}
        (tmp_path / "registry.yaml").write_text(yaml.safe_dump(reg), encoding="utf-8")
        (tmp_path / "players.yaml").write_text(yaml.safe_dump(PLAYERS), encoding="utf-8")
        chapters = [notes.Chapter(n, Path(f"{n:03d}-x.md"), t, {f"{n:03d}.01", "end"}) for n, t in PARTY_CHAPTERS.items()]
        ev = annotate.load_evidence([notes.CheckedChunk("002-005", [_party_note("Lost the gate of Brindol.", 4)])],
                                    chapters, tmp_path / "registry.yaml", tmp_path / "players.yaml")
        for line in (self.OVERVIEW, "**Party** hold the gate. [ch 002 / 002.01]"):
            r = annotate.annotate_text(f"## Party Overview\n{line}\n", ev)
            assert under(r, line) == [f"{schema.LATER} **Party** — Lost the gate of Brindol. [ch 004 / 004.01]"], line

    def test_a_mention_is_not_a_subject(self, evp):
        (e,) = annotate.parse_entries(["## Party Overview", "The party met Thorin Giantfriend. [ch 002 / 002.01]"], evp)
        assert e.subject == schema.PARTY_SUBJECT  # Thorin is mentioned, the whole party is the subject

    def test_a_party_line_cited_at_or_after_the_latest_party_note_is_not_stale(self, evp):
        r = annotate.annotate_text("## Party Overview\nThe gate is lost. [ch 004 / 004.01]\n", evp)
        assert r.hits == []

    def test_a_level_row_and_a_characters_note_are_not_whole_party_evidence(self, evp):
        assert [f.chapter for f in evp.facts(schema.PARTY_SUBJECT)] == [2, 4]
        lvl = notes.Note("party", "- [LEVEL] **Party** — 9 [ch 009 / 009.01]", 9, "c", tag=schema.LEVEL_TAG,
                         subject="Party", level=9)
        ev = annotate.load_evidence([notes.CheckedChunk("x", [lvl])], [], None, None)
        assert ev.facts(schema.PARTY_SUBJECT) == []

    def test_two_subjectless_lines_in_different_sections_are_not_cross_section_stale(self, evp):
        doc = "## Party Overview\nOlder. [ch 002 / 002.01]\n\n## Party Dynamics\nNewer. [ch 004 / 004.01]\n"
        flags = annotate.detect(annotate.parse_entries(doc.split("\n"), evp), evp)
        assert [f.kind for f in flags] == [annotate.STALE]  # only the whole-party stale check, no pairing

    def test_other_documents_sections_keep_an_empty_subject(self, evp):
        doc = "## DM Notes\nAsk about the gate. [ch 002 / 002.01]\n\n## Party\n- A bare bullet. [ch 002 / 002.01]\n"
        es = annotate.parse_entries(doc.split("\n"), evp)
        assert [e.subject for e in es] == ["", ""]
        assert annotate.annotate_text(doc, evp).hits == []


class SimpleNamespaceEv:
    @staticmethod
    def canon(name):
        return name


class TestPlanningDraft:
    def test_the_threat_tracker_and_the_npc_dossiers_are_skipped(self, ev2):
        sections = {e.section for e in entries_of(PLANNING_DOC, ev2)}
        assert "## Threat Tracker" not in sections and "## NPC Dossiers" not in sections

    def test_the_dormant_and_unratified_blocks_are_skipped_but_the_plot_entry_is_not(self, ev2):
        es = [e for e in entries_of(PLANNING_DOC, ev2) if e.section == "## Active Plots"]
        assert [e.text for e in es] == ["The march gathers. [ch 026 / 026.01]"]
        assert es[0].subject == "The Carver's march"  # the ### name, as written (no registry entity)

    def test_nothing_in_the_skipped_blocks_is_annotated(self, ev2):
        r = annotate.annotate_text(PLANNING_DOC, ev2)
        lines = r.text.split("\n")
        for needle in ("| kalan-arc |", "Goals: He said", "- **Jimjar** — A dormant line", "- [OPENED] **Jimjar** — An unratified",
                       "- A bare unratified line."):
            i = next(n for n, ln in enumerate(lines) if ln.startswith(needle))
            assert not annotate.ANNOTATION_RE.match(lines[i + 1]), needle
        assert not [h for h in r.hits if h.section in ("Threat Tracker", "NPC Dossiers")]

    def test_a_faction_block_whose_faction_has_a_later_note_gets_a_later(self, ev2):
        r = annotate.annotate_text(PLANNING_DOC, ev2)
        line = "The Avowed regroup at the tower. [ch 065 / 065.01]"
        assert under(r, line) == [f"{schema.LATER} **The Avowed** — They muster at dawn. [ch 070 / 070.01]"]

    def test_a_faction_block_named_for_a_player_character_is_removed_and_reported(self, ev2):
        r = annotate.annotate_text(PLANNING_DOC, ev2)
        assert "A faction block the model named for a player character. [ch 026 / 026.01]" not in r.text
        assert {(x.section, x.text) for x in r.removed} == {
            ("Faction States", "A faction block the model named for a player character. [ch 026 / 026.01]")}
        assert r.counts()["removed"] == 1

    def test_a_real_factions_line_naming_a_player_character_stays(self, ev2):
        # "Thorin joined the Avowed" is a claim about the Avowed, not a PC listed as an NPC: it is kept.
        line = "- **Thorin Giantfriend** — Joined the Avowed. [ch 026 / 026.01]"
        assert line in annotate.annotate_text(PLANNING_DOC, ev2).text
        assert line in annotate.annotate_text(f"## Faction States\n### The Avowed\n{line}\n", ev2).text
        assert line in annotate.annotate_text(f"## Characters\n### Thorin Giantfriend\n{line}\n", ev2).text

    def test_a_dm_note_is_scanned(self, ev2):
        line = "- Ask Kalan about the tower. [ch 065 / 065.01]"
        assert [a for a in under(annotate.annotate_text(PLANNING_DOC, ev2), line) if a.startswith(schema.SINCE)]

    def test_the_label_and_the_unratified_summary_line_are_not_entries(self, ev2):
        assert not [e for e in entries_of(PLANNING_DOC, ev2) if e.text.startswith("_")]
