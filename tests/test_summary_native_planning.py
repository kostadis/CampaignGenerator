"""Spec 034 User Story 2: planning built from the checked notes and the published dossiers (T032, T033).

Code builds the Threat Tracker, the faction selection, the Active Plots order, the dormant block, the
unratified block and every pointer; a model writes only the prose inside that structure, and a model
block that breaks the structure is replaced by the source text, verbatim, and reported. The fake model
here answers each planning call from its prompt, so no test reaches a backend.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from campaignlib.thread_registry import load_registry
from pipelines.summary_native import annotate, context, key_npcs, notes, schema, select, state_sections, thread_attach
from tests import conftest_party as cp
from tests import conftest_state as cs

BACKEND = ["--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1"]
POINTER = "→ docs/npcs/ilvara-mizzrym.md"
ILVARA_BLOCK = (
    "### Ilvara Mizzrym\n"
    "Status and location: Smiling at the parley. [ch 003 / 003.02]\n"
    "Goals: She wants every debt repaid. [ch 003 / 003.02]\n"
    "Relationships: Speaks for House Mizzrym. [ch 003 / 003.02]\n"
)


# ── helpers ─────────────────────────────────────────────────────────────────


def thread(tid, title, status="open", aliases=(), resolved=None):
    t = {"id": tid, "title": title, "aliases": list(aliases), "status": status, "opened": 2, "log": []}
    if resolved:
        t["resolved"] = resolved
    return t


def registry(*threads):
    return {"version": 1, "threads": list(threads)}


def attach_with(*threads):
    return thread_attach.attach(cp.checked_results(), registry(*threads))


def plan_args(root, *extra):
    return ["synth", "planning", *cp.common(root), *BACKEND, *extra]


def synth_planning(root, *extra):
    return cs.run_cli(plan_args(root, "--recent-chapters", "2", *extra))


def drafts(root) -> Path:
    return cp.range_dir(root) / "state" / "drafts"


def draft_text(root) -> str:
    return (drafts(root) / "planning.draft.md").read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    return text.split(f"\n{heading}\n", 1)[1].split("\n## ", 1)[0]


def write_registry(root, reg):
    (root / "docs" / "thread_registry.yaml").write_text(yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")


def publish_ront(root):
    """A second published dossier, so a selection that includes Ront can build."""
    src = (root / "docs" / "npcs" / "ilvara-mizzrym.md").read_text(encoding="utf-8")
    (root / "docs" / "npcs" / "ront.md").write_text(
        src.replace("Ilvara Mizzrym", "Ront").replace("SECRET-CANARY-034", "SECRET-RONT-034"), encoding="utf-8")


class PlanningModels:
    """Answers each planning call from its prompt; records every call."""

    def __init__(self, base) -> None:
        self.base = base
        self.calls: list[dict] = []
        self.override: dict[str, object] = {}  # heading -> str | callable(user) -> str

    def render(self, client, system, user, model, max_tokens):
        heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
        self.calls.append({"heading": heading, "system": system, "user": user})
        self.base.prose_calls.append({"heading": heading, "system": system, "user": user, "model": model})
        key = heading
        if heading == "## Candidate Arc Score Events":  # one call per scored subject (spec 034 US4)
            key = f"arc:{re.search(r'^SUBJECT: (.+)$', user, re.M).group(1)}"
        out = self.override.get(key, self.override.get(heading))
        if callable(out):
            return out(user)
        if out is not None:
            return out
        return DEFAULT[heading](user)

    def user_of(self, heading: str) -> str:
        return next(c["user"] for c in self.calls if c["heading"] == heading)

    def called(self, heading: str) -> bool:
        return any(c["heading"] == heading for c in self.calls)


def _names(user: str, kind: str) -> list[str]:
    return re.findall(rf"^=== {kind}: (.+?) \(", user, re.M)


DEFAULT = {
    "## NPC Dossiers": lambda u: "\n".join(
        f"### {n}\nStatus and location: Smiling at the parley. [ch 003 / 003.02]\n"
        "Goals: She wants every debt repaid. [ch 003 / 003.02]\n"
        "Relationships: Speaks for House Mizzrym. [ch 003 / 003.02]\n" for n in _names(u, "NPC")),
    "## Faction States": lambda u: "\n".join(
        f"### {n}\nStands aside while the horde passes. [ch 003 / 003.02]\n" for n in _names(u, "FACTION")),
    "## Active Plots": lambda u: "\n".join(
        f"### {n}\nProse for {n}. [ch 004 / 004.01]\n" for n in _names(u, "THREAD")),
    "## DM Notes": lambda u: "- Consider what the gate cost the party. [ch 004 / 004.01]\n",
    "## Candidate Arc Score Events": lambda u: "- (none)\n",
}


@pytest.fixture
def pcamp(tmp_path, monkeypatch):
    root = cp.party_campaign(tmp_path)
    base = cp.fake_party_models(monkeypatch)
    rc, out, err = cs.run_cli(cp.extract_args(root))
    assert rc == 0, out + err
    pm = PlanningModels(base)
    monkeypatch.setattr(cs.synth, "render_part", pm.render)
    return root, pm


# ── T034: the structured planning loader ─────────────────────────────────────


class TestLoadPlanning:
    def test_tracked_npcs_and_factions_with_arc_score_and_trackless_flag(self):
        got = context.load_planning(cp.PARTY_FIXTURE / "config" / "planning.yaml", cp.PARTY_FIXTURE, explicit=False)
        assert [e.name for e in got.npcs] == ["Ilvara Mizzrym"] and [e.name for e in got.factions] == ["House Mizzrym"]
        assert got.npcs[0].arc_score == (cp.PARTY_FIXTURE / "docs/mechanics/ilvara-arc.md").resolve()
        assert got.npcs[0].trackless is False and got.factions[0].arc_score is None and got.factions[0].trackless is True
        assert [e.name for e in got.entries] == ["Ilvara Mizzrym", "House Mizzrym"]
        assert [e.name for e in got.scored] == ["Ilvara Mizzrym"]

    def test_an_absent_default_file_means_none_configured(self, tmp_path):
        got = context.load_planning(tmp_path / "planning.yaml", tmp_path, explicit=False)
        assert got.npcs == [] and got.factions == [] and got.scored == [] and got.path is None

    def test_an_explicit_missing_file_refuses_with_the_existing_message(self, tmp_path):
        with pytest.raises(context.DocConfigError, match=r"--planning-config .*nope\.yaml: no such file"):
            context.load_planning(tmp_path / "nope.yaml", tmp_path, explicit=True)

    def test_a_missing_arc_score_file_refuses_naming_the_entry(self, tmp_path):
        (tmp_path / "planning.yaml").write_text(
            "npcs:\n  - name: Kalan\n    dossier: d.md\n    arc_score: gone.md\n", encoding="utf-8")
        with pytest.raises(context.DocConfigError, match="planning config: Kalan arc score file missing: gone.md"):
            context.load_planning(tmp_path / "planning.yaml", tmp_path, explicit=False)

    def test_files_lists_the_config_and_each_mechanic_file(self):
        got = context.load_planning(cp.PARTY_FIXTURE / "config" / "planning.yaml", cp.PARTY_FIXTURE, explicit=False)
        assert [p.name for p in got.files] == ["planning.yaml", "ilvara-arc.md"]


# ── Threat Tracker ───────────────────────────────────────────────────────────


def entry(name, arc=None, trackless=False):
    return SimpleNamespace(name=name, arc_score=Path(arc) if arc else None, trackless=trackless)


class TestThreatTracker:
    def test_no_scores_is_exactly_the_sentinel(self):
        assert state_sections.threat_tracker_md([], {}) == context.NO_ARC_SENTINEL
        assert state_sections.threat_tracker_md([entry("House Mizzrym", trackless=True), entry("Kalan")], {}) == context.NO_ARC_SENTINEL

    def test_one_row_per_scored_entry_in_config_order_and_none_for_trackless(self):
        md = state_sections.threat_tracker_md([
            entry("Ilvara Mizzrym", "docs/mechanics/ilvara-arc.md"),
            entry("House Mizzrym", trackless=True),
            entry("Zhentarim", "docs/mechanics/zhent.md"),
        ], {})
        assert md.splitlines() == [
            "| Score | Subject | Candidate events | Trigger text |",
            "|---|---|---|---|",
            "| ilvara-arc | Ilvara Mizzrym | — | docs/mechanics/ilvara-arc.md |",
            "| zhent | Zhentarim | — | docs/mechanics/zhent.md |",
        ]

    def test_the_candidate_cell_is_a_hook_for_arc_candidates(self):
        md = state_sections.threat_tracker_md(
            [entry("Ilvara Mizzrym", "m/ilvara-arc.md")],
            {"Ilvara Mizzrym": ["A bargain is refused [ch 003 / 003.02]", "Another [ch 004 / 004.01]"]})
        row = md.splitlines()[2]
        assert "A bargain is refused [ch 003 / 003.02]" in row and "Another [ch 004 / 004.01]" in row
        assert row.count("|") == 5  # still four cells

    def test_a_pipe_in_a_name_cannot_break_the_table(self):
        row = state_sections.threat_tracker_md([entry("A|B", "m/x.md")], {}).splitlines()[2]
        assert row.count("|") == 5


# ── Faction selection ────────────────────────────────────────────────────────


FORMS = {"house mizzrym": "House Mizzrym", "mizzrym": "House Mizzrym"}


class TestSelectFactions:
    def test_config_union_note_subjects_canonical_by_forms_newest_first(self):
        sel = state_sections.select_factions(cp.checked_results(), FORMS, ["House Baenre", "Mizzrym"], 20)
        assert [f.name for f in sel.selected] == ["House Mizzrym", "House Baenre"]
        assert [n.first_chapter for n in sel.selected[0].notes] == [2, 3]
        assert sel.selected[1].notes == [] and sel.selected[1].configured and sel.overflow == []

    def test_an_unresolved_subject_keys_on_itself(self):
        got = state_sections.select_factions(cp.checked_results(), {}, [], 20)
        assert [f.name for f in got.selected] == ["House Mizzrym"]

    def test_the_cap_writes_the_most_recent_and_names_the_rest(self):
        sel = state_sections.select_factions(cp.checked_results(), FORMS, ["House Baenre", "House Xorlarrin"], 2)
        assert [f.name for f in sel.selected] == ["House Mizzrym", "House Baenre"]
        assert sel.overflow == ["House Xorlarrin"]

    def test_the_order_is_deterministic(self):
        a = state_sections.select_factions(cp.checked_results(), FORMS, ["B", "A"], 20)
        b = state_sections.select_factions(cp.checked_results(), FORMS, ["B", "A"], 20)
        assert [f.name for f in a.selected] == [f.name for f in b.selected] == ["House Mizzrym", "B", "A"]


# ── Active Plots ─────────────────────────────────────────────────────────────

CARVER = thread("carver-march", "The Carver's march", aliases=["Carver march"])
RING_OPEN = thread("signet-ring", "The signet ring")
RING_RESOLVED = thread("signet-ring", "The signet ring", status="resolved", resolved=4)
RING_DORMANT = thread("signet-ring", "The signet ring", status="dormant")


def plots(att, bodies=None):
    bodies = {} if bodies is None else bodies
    return state_sections.active_plots_md(att, bodies)


class TestActivePlots:
    def test_open_threads_only_the_gm_resolved_one_is_absent(self):
        att = attach_with(CARVER, RING_RESOLVED)
        assert [s.title for s in att.open_threads] == ["The Carver's march"]
        out = plots(att, {"carver-march": "The march broke. [ch 004 / 004.01]"})
        assert "### The Carver's march\nThe march broke. [ch 004 / 004.01]" in out.text
        assert "### The signet ring" not in out.text and out.replaced == 0 and out.from_model == 1

    def test_gm_status_resolved_wins_over_an_advanced_latest_note(self):
        ring = thread("carver-march", "The Carver's march", status="resolved", resolved=4)
        att = attach_with(ring)
        assert att.open_threads == [] and att.threads["carver-march"].latest.tag == "ADVANCED"

    def test_status_open_defers_to_a_resolved_latest_note(self):
        att = attach_with(RING_OPEN)
        assert att.threads["signet-ring"].latest.tag == "RESOLVED" and att.open_threads == []
        assert "### The signet ring" not in plots(att).text

    def test_a_dropped_thread_is_replaced_by_the_latest_note_verbatim_and_reported(self):
        att = attach_with(CARVER)
        out = plots(att, {"carver-march": None})
        latest = att.threads["carver-march"].latest.text
        assert latest == "- [ADVANCED] **The Carver's march** — The march breaks against the gate. [ch 004 / 004.01]"
        assert f"### The Carver's march\n{latest}" in out.text
        assert out.replaced == 1 and any("The Carver's march" in r for r in out.report)

    def test_an_empty_body_counts_as_missing(self):
        att = attach_with(CARVER)
        out = plots(att, {"carver-march": "  \n"})
        assert out.replaced == 1 and att.threads["carver-march"].latest.text in out.text

    def test_dormant_threads_are_code_built_under_their_own_heading_with_no_model_body(self):
        att = attach_with(CARVER, RING_DORMANT)
        assert [s.title for s in att.dormant_threads] == ["The signet ring"]
        out = plots(att, {"carver-march": "Prose. [ch 004 / 004.01]"})
        dormant = out.text.split(schema.DORMANT_HEADING + "\n", 1)[1].split("\n### ", 1)[0]
        assert dormant.strip() == "- **The signet ring** — Nobody could say what became of the ring. [ch 004 / 004.02]"
        assert out.text.index("### The Carver's march") < out.text.index(schema.DORMANT_HEADING)
        assert "signet" not in out.text.split(schema.DORMANT_HEADING)[0].lower()

    def test_no_dormant_heading_without_a_dormant_thread(self):
        assert schema.DORMANT_HEADING not in plots(attach_with(CARVER), {"carver-march": "x [ch 004 / 004.01]"}).text

    def test_the_unratified_block_holds_every_unattached_note_verbatim_in_chapter_order_with_its_count(self):
        att = attach_with(CARVER)  # the signet ring's two notes belong to no ratified thread
        out = plots(att, {"carver-march": "x [ch 004 / 004.01]"})
        block = out.text.split(schema.UNRATIFIED_HEADING + "\n", 1)[1]
        assert block.startswith("_2 checked thread notes are not in the thread registry.")
        assert "/grounding/threads" in block and "thread-propose" in block
        lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
        assert lines == [
            "- [OPENED] **The signet ring** — Ilvara leaves a signet ring at the fire. [ch 002 / 002.02]",
            "- [RESOLVED] **The signet ring** — Nobody could say what became of the ring. [ch 004 / 004.02]",
        ]

    def test_an_empty_registry_says_no_thread_is_ratified_and_lists_every_note_as_unratified(self):
        att = thread_attach.attach(cp.checked_results(), registry())
        out = plots(att)
        assert out.text.startswith(schema.NO_RATIFIED_THREADS)
        assert "### " not in out.text.split(schema.UNRATIFIED_HEADING)[0]
        assert "_5 checked thread notes are not in the thread registry." in out.text
        assert out.text.count("\n- [") == 5

    def test_an_absent_registry_is_the_same_as_an_empty_one(self):
        assert plots(thread_attach.attach(cp.checked_results(), None)).text == plots(
            thread_attach.attach(cp.checked_results(), registry())).text

    def test_ratified_threads_none_open_says_so_without_claiming_none_exist(self):
        out = plots(attach_with(RING_RESOLVED))
        assert out.text.startswith(schema.NO_OPEN_THREADS) and schema.NO_RATIFIED_THREADS not in out.text

    def test_the_output_is_deterministic(self):
        att = attach_with(CARVER, RING_DORMANT)
        assert plots(att, {"carver-march": "x [ch 004 / 004.01]"}).text == plots(att, {"carver-march": "x [ch 004 / 004.01]"}).text


class TestCheckEntries:
    """The heading set and order of a model's ``###`` blocks, shared by factions, plots and NPCs."""

    def test_a_clean_output_gives_a_body_per_expected_name(self):
        got = state_sections.check_entries("### A\nbody a\n\n### B\nbody b\n", ["A", "B"])
        assert got.bodies == {"A": "body a", "B": "body b"} and got.bad == {} and got.extras == []

    def test_a_dropped_entry_is_bad_and_the_rest_stand(self):
        got = state_sections.check_entries("### A\nbody a\n\n### C\nbody c\n", ["A", "B", "C"])
        assert got.bodies == {"A": "body a", "C": "body c"} and "B" in got.bad

    def test_an_added_entry_is_reported_and_its_text_stays_out_of_the_neighbour(self):
        got = state_sections.check_entries("### A\nbody a\n### Z\nbody z\n### B\nbody b\n", ["A", "B"])
        assert got.bodies == {"A": "body a", "B": "body b"} and got.extras == ["Z"]

    def test_a_reordered_entry_is_bad(self):
        got = state_sections.check_entries("### B\nb\n### A\na\n", ["A", "B"])
        assert got.bodies == {} and set(got.bad) == {"A", "B"}

    def test_a_repeated_heading_keeps_the_first_and_reports_the_extra(self):
        got = state_sections.check_entries("### A\nfirst\n### A\nsecond\n", ["A"])
        assert got.bodies == {"A": "first"} and got.extras == ["A"]

    def test_none_is_all_bad(self):
        got = state_sections.check_entries(None, ["A"])
        assert got.bodies == {} and set(got.bad) == {"A"}


# ── Factions through the CLI ─────────────────────────────────────────────────


class TestFactionStates:
    def test_the_selection_prompt_and_block(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        user = pm.user_of("## Faction States")
        assert _names(user, "FACTION") == ["House Mizzrym"]
        assert "House Mizzrym sends word that it will stand aside." not in user  # events are not faction notes
        assert "It will stand aside while the horde passes. [ch 003 / 003.02]" in user
        facs = section(draft_text(root), "## Faction States")
        assert "### House Mizzrym\nStands aside while the horde passes. [ch 003 / 003.02]" in facs

    def test_a_failing_block_becomes_that_factions_latest_note_verbatim_and_is_reported(self, pcamp):
        root, pm = pcamp
        pm.override["## Faction States"] = "### Somebody Else\nWrong.\n"
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        facs = section(draft_text(root), "## Faction States")
        assert "### House Mizzrym\n- [FACTION] **House Mizzrym** — It will stand aside while the horde passes. [ch 003 / 003.02]" in facs
        assert "Wrong." not in facs
        assert "House Mizzrym: the latest note replaces the model's block (missing from the model's output)" in out
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text())
        assert rec["planning"]["Faction States"]["replaced"] == 1

    def test_what_code_replaced_is_written_to_the_planning_report_on_disk(self, pcamp):
        """Spec 034 T048: the faction substitutions are a file a GM can open, not only stdout and the run record."""
        root, pm = pcamp
        pm.override["## Faction States"] = "### Somebody Else\nWrong.\n"
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        rep = (drafts(root) / "planning_npcs_report.md").read_text()
        facs = rep.split("\n## Faction States\n", 1)[1]
        assert "1 written: House Mizzrym" in facs
        assert "House Mizzrym: the latest note replaces the model's block (missing from the model's output)" in facs
        assert "discarded (not a selected faction, or repeated): ### Somebody Else" in facs

    def test_a_clean_faction_build_reports_what_was_written_and_nothing_replaced(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        facs = (drafts(root) / "planning_npcs_report.md").read_text().split("\n## Faction States\n", 1)[1]
        assert "1 written: House Mizzrym" in facs and "replaces the model's block" not in facs

    def test_the_cap_overflow_is_named_in_the_report(self, pcamp, monkeypatch):
        root, _ = pcamp
        cfg = root / "config" / "planning.yaml"
        cfg.write_text(cfg.read_text() + "  - name: House Baenre\n    arc_score: null\n", encoding="utf-8")
        monkeypatch.setattr(schema, "DEFAULT_MAX_FACTIONS", 1)
        assert synth_planning(root)[0] == 0
        facs = (drafts(root) / "planning_npcs_report.md").read_text().split("\n## Faction States\n", 1)[1]
        assert "1 not written (the cap): House Baenre" in facs

    def test_a_configured_faction_with_no_notes_gets_a_code_line_and_no_model_input(self, pcamp):
        root, pm = pcamp
        cfg = root / "config" / "planning.yaml"
        cfg.write_text(cfg.read_text() + "  - name: House Baenre\n    arc_score: null\n", encoding="utf-8")
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        facs = section(draft_text(root), "## Faction States")
        assert "### House Baenre\nThe summaries in this range record nothing for House Baenre." in facs
        assert "Baenre" not in pm.user_of("## Faction States")
        assert facs.index("### House Mizzrym") < facs.index("### House Baenre")

    def test_over_the_cap_the_rest_are_named_with_a_pointer(self, pcamp, monkeypatch):
        root, pm = pcamp
        cfg = root / "config" / "planning.yaml"
        cfg.write_text(cfg.read_text() + "  - name: House Baenre\n    arc_score: null\n", encoding="utf-8")
        monkeypatch.setattr(schema, "DEFAULT_MAX_FACTIONS", 1)
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        facs = section(draft_text(root), "## Faction States")
        assert "### House Baenre" not in facs
        assert "House Baenre" in facs and "reference/factions.md" in facs
        assert re.findall(r"^### (.+)$", facs, re.M) == ["House Mizzrym"]

    def test_notes_alone_select_a_faction_when_the_config_names_none(self, pcamp):
        root, pm = pcamp
        (root / "config" / "planning.yaml").write_text("npcs: []\n", encoding="utf-8")
        rc, out, err = synth_planning(root, "--fallback-npc-lines")
        assert rc == 0, out + err
        assert "### House Mizzrym" in section(draft_text(root), "## Faction States")

    def test_no_faction_at_all_is_one_code_line(self):
        sel = state_sections.FactionSelection([], [])
        text, report = state_sections.faction_states_md(sel, {})
        assert text == schema.NO_FACTIONS and report == []


# ── NPC Dossiers (T033) ──────────────────────────────────────────────────────


def view_of(root=cp.PARTY_FIXTURE):
    return key_npcs.planning_view(root / "docs" / "npcs" / "ilvara-mizzrym.md")


class TestVerifyPlanningBlock:
    def test_a_clean_block_passes(self):
        assert key_npcs.verify_planning_block(ILVARA_BLOCK, view_of(), "") is None

    def test_a_wrong_heading_fails(self):
        assert key_npcs.verify_planning_block(ILVARA_BLOCK.replace("### Ilvara Mizzrym", "### Ilvara"), view_of(), "")

    def test_a_missing_or_reordered_label_fails(self):
        swapped = ILVARA_BLOCK.replace("Goals:", "Xx:")
        assert "label" in key_npcs.verify_planning_block(swapped, view_of(), "")
        lines = ILVARA_BLOCK.splitlines()
        lines[2], lines[3] = lines[3], lines[2]
        assert key_npcs.verify_planning_block("\n".join(lines), view_of(), "")

    def test_a_citation_from_another_dossier_fails(self):
        why = key_npcs.verify_planning_block(ILVARA_BLOCK.replace("[ch 003 / 003.02]", "[ch 004 / 004.01]", 1), view_of(), "")
        assert why and "citation not in this NPC's dossier" in why

    def test_a_line_without_a_citation_fails_unless_it_says_not_established(self):
        assert key_npcs.verify_planning_block(ILVARA_BLOCK.replace(" [ch 003 / 003.02]", "", 1), view_of(), "")
        ok = ILVARA_BLOCK.replace("Goals: She wants every debt repaid. [ch 003 / 003.02]", "Goals: not established in the dossier")
        assert key_npcs.verify_planning_block(ok, view_of(), "") is None

    def test_a_quotation_that_is_not_verbatim_in_the_dossier_fails(self):
        bad = ILVARA_BLOCK.replace("She wants", 'She says "all debts shall be paid in blood" and wants')
        why = key_npcs.verify_planning_block(bad, view_of(), "")
        assert why and "quotation not verbatim" in why

    def test_a_verbatim_quotation_passes(self):
        good = ILVARA_BLOCK.replace("She wants", 'She is "Patient and transactional" and wants')
        assert key_npcs.verify_planning_block(good, view_of(), "") is None

    def test_an_extra_line_fails(self):
        assert key_npcs.verify_planning_block(ILVARA_BLOCK + "Also: something\n", view_of(), "")


class TestSynthNpcDossiers:
    def test_the_block_ends_with_its_pointer_and_the_secret_never_appears(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        npcs = section(draft_text(root), "## NPC Dossiers")
        assert re.findall(r"^### (.+)$", npcs, re.M) == ["Ilvara Mizzrym"]
        block = npcs.split("### Ilvara Mizzrym\n")[1]
        assert "Status and location: Smiling at the parley. [ch 003 / 003.02]" in block
        assert block.split("\n\n")[0].splitlines()[-1] == POINTER

    def test_the_canary_is_in_no_prompt_no_output_and_no_file(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        for call in pm.calls:
            assert cp.CANARY not in call["system"] and cp.CANARY not in call["user"]
        for p in (root / "docs" / "summary_native").rglob("*"):
            if p.is_file():
                assert cp.CANARY not in p.read_text(encoding="utf-8", errors="replace"), p

    def test_the_prompt_holds_the_four_sections_only(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        user = pm.user_of("## NPC Dossiers")
        for frag in ("A drow priestess of House Mizzrym", "Patient and transactional", "Smiling at the parley", "Speaks for House Mizzrym"):
            assert frag in user
        assert "A drow priestess of House Mizzrym who bargains with everyone. [ch 002 / npcs]" in user  # entry -> npcs, as world_state

    def test_one_call_for_all_the_npcs(self, pcamp):
        root, pm = pcamp
        publish_ront(root)
        assert synth_planning(root, "--name", "Ront")[0] == 0
        assert [c["heading"] for c in pm.calls].count("## NPC Dossiers") == 1
        assert _names(pm.user_of("## NPC Dossiers"), "NPC") == ["Ilvara Mizzrym", "Ront"]

    def test_selection_is_tracked_then_named_then_recent_and_recurring(self, pcamp):
        root, pm = pcamp
        publish_ront(root)
        # with all chapters recent, Ront (last seen ch 2) joins by recency; Ilvara leads as tracked
        assert cs.run_cli(plan_args(root, "--recent-chapters", "0"))[0] == 0
        assert _names(pm.user_of("## NPC Dossiers"), "NPC") == ["Ilvara Mizzrym", "Ront"]
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text())
        assert [(k["name"], k["reason"]) for k in rec["key_npcs"]["selected"]] == [("Ilvara Mizzrym", "tracked"), ("Ront", "recent")]

    def test_a_tracked_alias_resolves_to_the_canonical_name(self, pcamp):
        root, pm = pcamp
        cfg = root / "config" / "planning.yaml"
        cfg.write_text("npcs:\n  - name: Ilvara\n    dossier: docs/npcs/ilvara-mizzrym.md\nfactions: []\n", encoding="utf-8")
        assert synth_planning(root)[0] == 0
        assert _names(pm.user_of("## NPC Dossiers"), "NPC") == ["Ilvara Mizzrym"]

    def test_a_tracked_npc_with_no_corpus_dossier_is_still_selected(self, pcamp):
        root, pm = pcamp
        src = (root / "docs" / "npcs" / "ilvara-mizzrym.md").read_text(encoding="utf-8")
        (root / "docs" / "npcs" / "kalan.md").write_text(
            src.replace("Ilvara Mizzrym", "Kalan").replace(cp.CANARY, "SECRET-KALAN-034"), encoding="utf-8")
        cfg = root / "config" / "planning.yaml"
        cfg.write_text("npcs:\n  - name: Kalan\n    dossier: docs/npcs/kalan.md\n  - name: Ilvara Mizzrym\n"
                       "    dossier: docs/npcs/ilvara-mizzrym.md\n", encoding="utf-8")
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        assert _names(pm.user_of("## NPC Dossiers"), "NPC") == ["Kalan", "Ilvara Mizzrym"]  # config order

    def test_a_block_citing_another_dossier_is_replaced_by_the_dossiers_first_state_sentence(self, pcamp):
        root, pm = pcamp
        pm.override["## NPC Dossiers"] = ILVARA_BLOCK.replace("[ch 003 / 003.02]", "[ch 004 / 004.01]", 1)
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        block = section(draft_text(root), "## NPC Dossiers").split("### Ilvara Mizzrym\n")[1]
        assert "Smiling at the parley, House Mizzrym standing aside while the horde passes. [ch 003 / 003.02]" in block
        assert "Status and location: Smiling at the parley. [ch 004" not in block
        assert block.split("\n\n")[0].splitlines()[-1] == POINTER
        rep = (drafts(root) / "planning_npcs_report.md").read_text()
        assert "Ilvara Mizzrym" in rep and "citation not in this NPC's dossier" in rep

    def test_a_non_verbatim_quotation_is_replaced_and_reported(self, pcamp):
        root, pm = pcamp
        pm.override["## NPC Dossiers"] = ILVARA_BLOCK.replace("She wants", 'She vows "blood for blood" and wants')
        assert synth_planning(root)[0] == 0
        assert "blood for blood" not in draft_text(root)
        assert "quotation not verbatim" in (drafts(root) / "planning_npcs_report.md").read_text()

    def test_a_missing_block_is_replaced_too(self, pcamp):
        root, pm = pcamp
        pm.override["## NPC Dossiers"] = "I could not write that.\n"
        assert synth_planning(root)[0] == 0
        assert "Smiling at the parley, House Mizzrym standing aside" in draft_text(root)
        assert "missing from the model's output" in (drafts(root) / "planning_npcs_report.md").read_text()

    def test_a_missing_dossier_refuses_naming_the_npc_and_its_state(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--name", "Ront")
        assert rc == 2 and pm.calls == []
        assert "planning's NPC Dossiers need a published, verified dossier" in err
        assert "Ront: not drafted" in err and "--fallback-npc-lines" in err
        assert not (drafts(root) / "planning.draft.md").exists()
        got = json.loads((cp.range_dir(root) / "state" / schema.missing_dossiers_file("planning")).read_text())
        assert got["refused"] is True and got["npcs"] == [{"name": "Ront", "state": "not drafted"}]

    def test_the_planning_refusal_leaves_world_states_missing_list_alone(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root, "--name", "Ront")[0] == 2
        assert not (cp.range_dir(root) / "state" / schema.MISSING_DOSSIERS_FILE).exists()

    def test_fallback_lines_write_the_marked_line_instead(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--name", "Ront", "--fallback-npc-lines")
        assert rc == 0, out + err
        npcs = section(draft_text(root), "## NPC Dossiers")
        ront = npcs.split("### Ront\n")[1].split("\n\n")[0]
        assert ront == f"Alive; the wall; Friendly [ch 002 / 002.01] {schema.KEY_NPC_FALLBACK_MARK}"
        assert "Ront" not in pm.user_of("## NPC Dossiers")  # no dossier, no model input
        got = json.loads((cp.range_dir(root) / "state" / schema.missing_dossiers_file("planning")).read_text())
        assert got["refused"] is False and [n["name"] for n in got["npcs"]] == ["Ront"]
        assert "Ront" in (drafts(root) / "planning_npcs_report.md").read_text()

    def test_only_fallback_npcs_make_no_dossier_call(self, pcamp):
        root, pm = pcamp
        (root / "docs" / "npcs" / "ilvara-mizzrym.md").unlink()
        rc, out, err = synth_planning(root, "--fallback-npc-lines")
        assert rc == 0, out + err
        assert not pm.called("## NPC Dossiers")
        assert schema.KEY_NPC_FALLBACK_MARK in section(draft_text(root), "## NPC Dossiers")

    def test_npc_root_is_accepted_and_named_in_the_refusals_commands(self, pcamp):
        """Spec 034 T048: ``--npc-root`` applies to planning as to world_state (it was refused for planning)."""
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--name", "Ront", "--npc-root", "docs/elsewhere")
        assert rc == 2 and "--npc-root applies" not in err and pm.calls == []
        assert "summary_native npc-draft --since 2 --until 4 --npc-root docs/elsewhere --name \"Ront\"" in err

    def test_fallback_flag_is_refused_for_party_and_campaign_state(self, pcamp):
        root, _ = pcamp
        rc, _, err = cs.run_cli(["synth", "party", *cp.common(root), *BACKEND, "--fallback-npc-lines"])
        assert rc == 2 and "applies to world_state and planning only" in err


# ── The whole planning document through the CLI ──────────────────────────────


class TestSynthPlanning:
    def test_builds_a_complete_draft_in_outline_order_with_the_contract(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        text = draft_text(root)
        assert re.findall(r"^## .+$", text, re.M) == [
            "## Threat Tracker", "## NPC Dossiers", "## Faction States", "## Active Plots", "## DM Notes"]
        assert text.splitlines()[1].startswith("> **How to read this document.**")
        assert (drafts(root) / "planning.incomplete.md").exists() is False

    def test_the_threat_tracker_matches_planning_yaml(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        tracker = section(draft_text(root), "## Threat Tracker").strip().splitlines()
        assert tracker == [
            "| Score | Subject | Candidate events | Trigger text |",
            "|---|---|---|---|",
            "| ilvara-arc | Ilvara Mizzrym | — | docs/mechanics/ilvara-arc.md |",
        ]

    def test_no_arc_scores_gives_exactly_the_sentinel(self, pcamp):
        root, _ = pcamp
        (root / "config" / "planning.yaml").unlink()
        assert synth_planning(root)[0] == 0
        assert section(draft_text(root), "## Threat Tracker").strip() == context.NO_ARC_SENTINEL

    def test_an_explicit_missing_planning_config_refuses_before_any_call(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--planning-config", "config/nope.yaml")
        assert rc == 2 and "--planning-config" in err and "nope.yaml" in err and pm.calls == []

    def test_planning_config_flag_picks_the_file(self, pcamp):
        root, pm = pcamp
        (root / "config" / "alt.yaml").write_text("factions:\n  - name: House Baenre\n    arc_score: null\n", encoding="utf-8")
        rc, out, err = synth_planning(root, "--planning-config", "config/alt.yaml")
        assert rc == 0, out + err
        assert "House Baenre" in section(draft_text(root), "## Faction States")
        assert section(draft_text(root), "## Threat Tracker").strip() == context.NO_ARC_SENTINEL

    def test_active_plots_lists_the_open_ratified_thread_and_not_the_gm_resolved_one(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        plots_text = section(draft_text(root), "## Active Plots")
        assert re.findall(r"^### (.+)$", plots_text, re.M) == ["The Carver's march", schema.UNRATIFIED_HEADING[4:]]
        assert "Prose for The Carver's march. [ch 004 / 004.01]" in plots_text
        assert "signet" not in pm.user_of("## Active Plots").lower()

    def test_the_active_plots_prompt_gives_each_open_thread_its_attached_notes_in_chapter_order(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        user = pm.user_of("## Active Plots")
        assert _names(user, "THREAD") == ["The Carver's march"]
        assert user.index("A horde is spoken of in whispers.") < user.index("Daz counts the banners") < user.index("The march breaks against the gate.")

    def test_a_model_that_adds_or_drops_a_thread_is_replaced_by_the_latest_note(self, pcamp):
        root, pm = pcamp
        pm.override["## Active Plots"] = "### The Carver's march\nok. [ch 004 / 004.01]\n### An invented plot\nBoo.\n"
        assert synth_planning(root)[0] == 0
        plots_text = section(draft_text(root), "## Active Plots")
        assert "An invented plot" not in plots_text and "Boo." not in plots_text and "### The Carver's march\nok." in plots_text
        pm.override["## Active Plots"] = "### Some other plot\nBoo.\n"
        assert cs.run_cli(plan_args(root, "--recent-chapters", "2", "--force"))[0] == 0
        plots_text = section(draft_text(root), "## Active Plots")
        assert "### The Carver's march\n- [ADVANCED] **The Carver's march** — The march breaks against the gate. [ch 004 / 004.01]" in plots_text
        rep = (drafts(root) / "threads_report.md").read_text()
        assert "The Carver's march" in rep.split("replaced by code")[1]

    def test_a_dormant_thread_is_listed_under_its_heading_and_costs_no_model_input(self, pcamp):
        root, pm = pcamp
        write_registry(root, registry(CARVER, RING_DORMANT))
        assert synth_planning(root)[0] == 0
        plots_text = section(draft_text(root), "## Active Plots")
        dormant = plots_text.split(schema.DORMANT_HEADING + "\n", 1)[1].split("\n### ", 1)[0]
        assert "- **The signet ring** — Nobody could say what became of the ring. [ch 004 / 004.02]" in dormant
        assert "signet" not in pm.user_of("## Active Plots").lower()

    def test_the_unratified_block_and_its_count(self, pcamp):
        root, pm = pcamp
        write_registry(root, registry(CARVER))
        assert synth_planning(root)[0] == 0
        block = section(draft_text(root), "## Active Plots").split(schema.UNRATIFIED_HEADING + "\n", 1)[1]
        assert block.startswith("_2 checked thread notes are not in the thread registry.")
        assert "- [OPENED] **The signet ring** — Ilvara leaves a signet ring at the fire. [ch 002 / 002.02]" in block

    def test_an_empty_registry_builds_and_says_no_thread_is_ratified(self, pcamp):
        root, pm = pcamp
        write_registry(root, registry())
        assert synth_planning(root)[0] == 0
        plots_text = section(draft_text(root), "## Active Plots")
        assert plots_text.strip().startswith(schema.NO_RATIFIED_THREADS)
        assert "_5 checked thread notes are not in the thread registry." in plots_text
        assert not pm.called("## Active Plots")

    def test_an_absent_registry_file_builds(self, pcamp):
        root, pm = pcamp
        (root / "docs" / "thread_registry.yaml").unlink()
        assert synth_planning(root)[0] == 0
        assert schema.NO_RATIFIED_THREADS in draft_text(root)

    def test_a_registry_that_fails_its_check_refuses_with_the_findings(self, pcamp):
        root, pm = pcamp
        write_registry(root, registry(thread("a", "Same"), thread("b", "Same")))
        rc, out, err = synth_planning(root)
        assert rc == 2 and "collides" in err and "thread_registry check" in err and pm.calls == []

    def test_dm_notes_begin_with_the_label_and_hold_the_models_lines(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        notes_text = section(draft_text(root), "## DM Notes").lstrip("\n")
        assert notes_text.startswith(schema.DM_NOTES_LABEL + "\n")
        assert "- Consider what the gate cost the party. [ch 004 / 004.01]" in notes_text

    def test_dm_notes_inputs_are_the_open_threads_the_status_table_and_the_last_chunk(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        user = pm.user_of("## DM Notes")
        assert "The march breaks against the gate." in user  # the open thread's latest note
        assert "| NPC | Status |" in user and "Ilvara Mizzrym" in user  # the status table
        assert "EVIDENCE OF THE LAST CHUNK" in user

    def test_the_references_are_factions_npcs_and_threads_only(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        assert sorted(p.name for p in (drafts(root) / "reference").iterdir()) == ["factions.md", "npcs.md", "threads.md"]
        text = draft_text(root)
        for kind in ("npcs", "factions", "threads"):
            assert f"reference/{kind}.md" in text
        assert not (drafts(root) / schema.TIMELINE_FILE).exists()

    def test_attach_json_and_threads_report_are_written(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        att = json.loads((cp.range_dir(root) / "state" / "threads" / "attach.json").read_text())
        assert att["kind"] == "thread_attach" and att["counts"]["unattached"] == 0 and "carver-march" in att["threads"]
        assert "# Threads report" in (drafts(root) / "threads_report.md").read_text()

    def test_the_run_record_has_the_registry_the_config_files_and_the_budgets(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text())
        reg = root / "docs" / "thread_registry.yaml"
        assert rec["inputs"]["thread_registry_sha256"] == hashlib.sha256(reg.read_bytes()).hexdigest()
        pc = rec["inputs"]["planning_config"]
        cfg = root / "config" / "planning.yaml"
        assert pc["path"] == "config/planning.yaml" and pc["sha256"] == hashlib.sha256(cfg.read_bytes()).hexdigest()
        assert {f["path"] for f in pc["files"]} == {"docs/mechanics/ilvara-arc.md"}
        assert rec["inputs"]["budgets"] == schema.DEFAULT_PLANNING_BUDGETS
        assert {"NPC Dossiers", "Faction States", "Active Plots", "DM Notes"} <= set(rec["budgets"])
        # the prose calls, then one arc call for the one scored subject (Ilvara; House Mizzrym is trackless)
        assert [c["heading"] for c in rec["calls"]] == [
            "## NPC Dossiers", "## Faction States", "## Active Plots", "## DM Notes", schema.ARC_HEADING]

    def test_the_prompts_are_recorded_beside_the_run(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        names = sorted(p.name for p in run.iterdir())
        for stem in ("npc_dossiers", "faction_states", "active_plots", "dm_notes"):
            assert f"planning.{stem}.user.md" in names and f"planning.{stem}.out.md" in names

    def test_dump_only_makes_no_call(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--dump-only")
        assert rc == 0 and pm.calls == []
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert (run / "planning.npc_dossiers.user.md").is_file() and (run / "record.json").is_file()

    def test_code_built_parts_are_byte_identical_across_rebuilds(self, pcamp):
        root, _ = pcamp
        write_registry(root, registry(CARVER, RING_DORMANT))
        assert synth_planning(root)[0] == 0
        names = ("planning.draft.md", "planning_npcs_report.md", "threads_report.md", "reference/factions.md",
                 "reference/npcs.md", "reference/threads.md")
        first = {n: (drafts(root) / n).read_bytes() for n in names}
        attach_first = (cp.range_dir(root) / "state" / "threads" / "attach.json").read_bytes()
        assert synth_planning(root, "--force")[0] == 0
        strip = lambda b: re.sub(rb"record: runs/[^ ]+ ", b"record: runs/X ", b)  # noqa: E731
        for n in names:
            assert strip(first[n]) == strip((drafts(root) / n).read_bytes()), n
        assert attach_first == (cp.range_dir(root) / "state" / "threads" / "attach.json").read_bytes()

    def test_planning_does_not_change_world_state_or_party(self, pcamp):
        root, _ = pcamp
        assert synth_planning(root)[0] == 0
        assert not (drafts(root) / "world_state.draft.md").exists() and not (drafts(root) / "party.draft.md").exists()

    def test_a_model_failure_exits_4(self, pcamp, monkeypatch):
        root, pm = pcamp

        def boom(*a, **k):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(cs.synth, "render_part", boom)
        rc, out, err = synth_planning(root)
        assert rc == 4 and "model call failed" in err

    def test_a_missing_dm_notes_body_makes_the_draft_incomplete(self, pcamp):
        root, pm = pcamp
        pm.override["## DM Notes"] = ""
        rc, out, err = synth_planning(root)
        assert rc == 3 and "DM Notes" in err
        assert (drafts(root) / "planning.incomplete.md").is_file()


# ── US4 (T042): candidate arc-score events in the Threat Tracker ─────────────

ILVARA_TRIGGER = "The party refuses a bargain Ilvara offers"
GOOD_ILVARA = f'- Ilvara\'s offer is refused [ch 003 / 003.02] — trigger: "{ILVARA_TRIGGER}"'
HOUSE_TRIGGER = "House Mizzrym stands aside"


def score_house(root):
    """Give the (trackless by default) faction an arc score and a mechanic file."""
    (root / "docs" / "mechanics" / "house-arc.md").write_text(
        f'# House Mizzrym — Neutrality arc\n\nTrigger: "{HOUSE_TRIGGER}".\n', encoding="utf-8")
    cfg = root / "config" / "planning.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("    arc_score: null\n", "    arc_score: docs/mechanics/house-arc.md\n"),
                   encoding="utf-8")


def tracker_rows(root) -> list[list[str]]:
    rows = section(draft_text(root), "## Threat Tracker").strip().splitlines()[2:]
    return [[c.strip() for c in r.strip("|").split("|")] for r in rows]


class TestArcCandidates:
    def test_a_checked_candidate_fills_the_trackers_cell(self, pcamp):
        root, pm = pcamp
        pm.override["arc:Ilvara Mizzrym"] = GOOD_ILVARA + "\n"
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        (row,) = tracker_rows(root)
        assert row == ["ilvara-arc", "Ilvara Mizzrym", GOOD_ILVARA[2:], "docs/mechanics/ilvara-arc.md"]

    def test_several_candidates_share_the_cell_and_none_leaves_a_dash(self, pcamp):
        root, pm = pcamp
        second = f'- A second refusal [ch 002 / 002.02] — trigger: "{ILVARA_TRIGGER}"'
        pm.override["arc:Ilvara Mizzrym"] = GOOD_ILVARA + "\n" + second + "\n"
        assert synth_planning(root)[0] == 0
        assert tracker_rows(root)[0][2] == f"{GOOD_ILVARA[2:]}<br>{second[2:]}"
        pm.override["arc:Ilvara Mizzrym"] = "- (none)\n"
        assert synth_planning(root, "--force")[0] == 0
        assert tracker_rows(root)[0][2] == "—"

    def test_the_arc_prompt_holds_the_subjects_notes_and_the_mechanic_only(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0
        arc = [c for c in pm.calls if c["heading"] == "## Candidate Arc Score Events"]
        assert len(arc) == 1  # House Mizzrym is trackless: no call
        user = arc[0]["user"]
        assert "SUBJECT: Ilvara Mizzrym" in user and "KIND: npc" in user
        assert "A drow priestess of House Mizzrym who left a signet ring. [ch 002 / npcs]" in user
        assert "Ilvara Mizzrym | Alive | the parley | Smiling [ch 003 / 003.02]" in user
        assert ILVARA_TRIGGER in user and "docs/mechanics/ilvara-arc.md" in user
        for foreign in ("It will stand aside while the horde passes", "The horde", "Patient and transactional", cp.CANARY):
            assert foreign not in user  # no faction note, no threat note, nothing of the dossier

    def test_drops_are_listed_with_reasons_and_never_reach_the_tracker(self, pcamp):
        root, pm = pcamp
        pm.override["arc:Ilvara Mizzrym"] = "\n".join([
            GOOD_ILVARA,
            '- She is refused again [ch 003 / 003.02] — trigger: "The party refuses a bargain she offers"',
            f'- The score is now 3 [ch 003 / 003.02] — trigger: "{ILVARA_TRIGGER}"',
            f'- A foreign note [ch 004 / 004.01] — trigger: "{ILVARA_TRIGGER}"',
            "",
        ])
        assert synth_planning(root)[0] == 0
        (row,) = tracker_rows(root)
        assert row[2] == GOOD_ILVARA[2:]
        rep = (drafts(root) / "arc_report.md").read_text(encoding="utf-8")
        assert "trigger not verbatim" in rep and "states a value" in rep and "cite-not-in-notes" in rep
        assert "Kept (1)" in rep and "Dropped (3)" in rep
        assert "House Mizzrym" in rep and "trackless" in rep.split("## House Mizzrym")[1]

    def test_a_scored_faction_gets_its_own_call_and_row_after_the_npcs(self, pcamp):
        root, pm = pcamp
        score_house(root)
        pm.override["arc:House Mizzrym"] = f'- It stands aside [ch 003 / 003.02] — trigger: "{HOUSE_TRIGGER}"\n'
        assert synth_planning(root)[0] == 0
        arc = [c for c in pm.calls if c["heading"] == "## Candidate Arc Score Events"]
        assert [re.search(r"^SUBJECT: (.+)$", c["user"], re.M).group(1) for c in arc] == ["Ilvara Mizzrym", "House Mizzrym"]
        assert "KIND: faction" in arc[1]["user"] and "It will stand aside while the horde passes" in arc[1]["user"]
        notes_block = arc[1]["user"].split("VERIFIED NOTES ABOUT")[1].split("\n\nMECHANIC FILE (")[0]
        assert "**Ilvara Mizzrym**" not in notes_block and "| Alive |" not in notes_block  # the NPC's notes stay in its call
        rows = tracker_rows(root)
        assert [r[1] for r in rows] == ["Ilvara Mizzrym", "House Mizzrym"]
        assert rows[0][2] == "—" and rows[1][2] == f"It stands aside [ch 003 / 003.02] — trigger: \"{HOUSE_TRIGGER}\""

    def test_no_arc_score_configured_means_no_call_and_no_report(self, pcamp):
        root, pm = pcamp
        assert synth_planning(root)[0] == 0 and (drafts(root) / "arc_report.md").is_file()
        (root / "config" / "planning.yaml").unlink()
        pm.calls.clear()
        assert synth_planning(root, "--force")[0] == 0
        assert not pm.called("## Candidate Arc Score Events")
        assert not (drafts(root) / "arc_report.md").exists()
        assert section(draft_text(root), "## Threat Tracker").strip() == context.NO_ARC_SENTINEL

    def test_a_scored_subject_with_no_notes_gets_no_call(self, pcamp):
        root, pm = pcamp
        cfg = root / "config" / "planning.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("factions:\n", "factions:\n  - name: Nobody\n    arc_score: docs/mechanics/ilvara-arc.md\n"),
                       encoding="utf-8")
        assert synth_planning(root)[0] == 0
        assert len([c for c in pm.calls if c["heading"] == "## Candidate Arc Score Events"]) == 1
        assert [r[1] for r in tracker_rows(root)] == ["Ilvara Mizzrym", "Nobody"]
        assert "no checked notes about Nobody" in (drafts(root) / "arc_report.md").read_text(encoding="utf-8")

    def test_a_model_failure_in_an_arc_call_is_exit_4(self, pcamp):
        root, pm = pcamp

        def boom(user):
            raise RuntimeError("upstream down")

        pm.override["arc:Ilvara Mizzrym"] = boom
        rc, out, err = synth_planning(root)
        assert rc == 4 and "Arc score: Ilvara Mizzrym" in err and "upstream down" in err
        assert not (drafts(root) / "planning.draft.md").exists()

    def test_the_call_prompt_and_output_are_recorded(self, pcamp):
        root, pm = pcamp
        pm.override["arc:Ilvara Mizzrym"] = GOOD_ILVARA + "\n"
        assert synth_planning(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert (run / "planning.arc_ilvara_mizzrym.user.md").is_file()
        assert (run / "planning.arc_ilvara_mizzrym.out.md").read_text(encoding="utf-8") == GOOD_ILVARA + "\n"
        assert (run / "planning.arc.system.md").is_file()
        rec = json.loads((run / "record.json").read_text(encoding="utf-8"))
        (call,) = [c for c in rec["calls"] if c["route"] == "arc"]
        assert call["subject"] == "Ilvara Mizzrym" and call["notes"] > 0
        assert rec["arc"]["Ilvara Mizzrym"]["kept"] == 1 and rec["arc"]["House Mizzrym"]["trackless"] is True

    def test_dump_only_writes_the_arc_prompt_and_makes_no_call(self, pcamp):
        root, pm = pcamp
        rc, out, err = synth_planning(root, "--dump-only")
        assert rc == 0 and pm.calls == []
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert (run / "planning.arc_ilvara_mizzrym.user.md").is_file()

    def test_the_tracker_and_the_report_are_byte_identical_across_rebuilds(self, pcamp):
        root, pm = pcamp
        pm.override["arc:Ilvara Mizzrym"] = GOOD_ILVARA + "\n"
        assert synth_planning(root)[0] == 0
        first = (section(draft_text(root), "## Threat Tracker"), (drafts(root) / "arc_report.md").read_bytes())
        assert synth_planning(root, "--force")[0] == 0
        assert (section(draft_text(root), "## Threat Tracker"), (drafts(root) / "arc_report.md").read_bytes()) == first


# ── US5 (T045): annotation runs at the end of synth planning ─────────────────

STALE_FACTION = "### House Mizzrym\nIlvara speaks for it. [ch 002 / npcs]\n"


class TestAnnotation:
    def _built(self, pcamp, faction=STALE_FACTION):
        root, pm = pcamp
        pm.override["## Faction States"] = faction
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        return root, out, draft_text(root)

    def test_a_faction_block_with_a_later_note_gets_a_later_and_keeps_its_text(self, pcamp):
        root, out, text = self._built(pcamp)
        assert ("Ilvara speaks for it. [ch 002 / npcs]\n"
                f"  - {schema.LATER} **House Mizzrym** — It will stand aside while the horde passes. [ch 003 / 003.02]\n") in text

    def test_a_real_factions_line_naming_a_player_character_is_kept(self, pcamp):
        # A PC named inside a real faction's block is a claim about the faction, never a removal; only a
        # block NAMED for a PC is removed (tests/test_summary_native_annotate.py covers that case).
        root, out, text = self._built(pcamp, STALE_FACTION + "- **Daz** — Joined the house. [ch 003 / 003.01]\n")
        assert "- **Daz** — Joined the house. [ch 003 / 003.01]" in text
        assert "0 removed" in out

    def test_the_tracker_the_npc_dossiers_and_the_thread_blocks_carry_no_annotation(self, pcamp):
        root, out, text = self._built(pcamp)
        for heading in ("## Threat Tracker", "## NPC Dossiers"):
            sec = section(text, heading)
            assert not any(m in sec for m in (schema.LATER, schema.SINCE, schema.UNVERIFIED)), heading
        plots_text = section(text, "## Active Plots")
        for block in (schema.DORMANT_HEADING, schema.UNRATIFIED_HEADING):
            if block in plots_text:
                tail = plots_text.split(block)[1]
                assert not any(m in tail for m in (schema.LATER, schema.SINCE, schema.UNVERIFIED))

    def test_an_active_plot_entry_with_a_bad_citation_is_unverified(self, pcamp):
        root, pm = pcamp
        pm.override["## Active Plots"] = "### The Carver's march\nThe march gathers. [ch 004 / 004.77]\n"
        rc, out, err = synth_planning(root)
        assert rc == 0, out + err
        line = "The march gathers. [ch 004 / 004.77]"
        assert f"{line}\n  - {schema.UNVERIFIED} citation [ch 004 / 004.77] does not resolve\n" in draft_text(root)

    def test_the_counts_are_recorded_and_the_report_written(self, pcamp):
        root, out, text = self._built(pcamp)
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        counts = json.loads((run / "record.json").read_text(encoding="utf-8"))["annotations"]
        assert counts["later"] >= 1
        assert f"annotations: {counts['later']} later, {counts['since']} since, {counts['unverified']} unverified; {counts['removed']} removed" in out
        assert "## planning" in (drafts(root) / "annotations.md").read_text(encoding="utf-8")
        assert annotate.read_counts(drafts(root))["planning"] == counts

    def test_every_difference_from_the_built_sections_is_an_annotation_or_a_removal(self, pcamp):
        # SC-008: annotating the finished draft again changes nothing, and stripping the annotations leaves the assembly
        root, out, text = self._built(pcamp, STALE_FACTION + "- **Daz** — Joined the house. [ch 003 / 003.01]\n")
        plain = [ln for ln in text.split("\n") if not annotate.ANNOTATION_RE.match(ln)]
        raw = (sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1] / "planning.faction_states.out.md").read_text(encoding="utf-8")
        want = iter(plain)
        # every line the model wrote is in the draft, in order: annotation only adds lines
        assert all(ln in want for ln in raw.splitlines() if ln.strip())
        rc, o, e = cs.run_cli(["annotate", "planning", *cp.common(root)])
        assert rc == 0, e
        assert draft_text(root) == text

    def test_annotate_planning_dry_run_writes_nothing(self, pcamp):
        root, out, text = self._built(pcamp)
        before = {q: q.read_bytes() for q in drafts(root).rglob("*") if q.is_file()}
        rc, o, e = cs.run_cli(["annotate", "planning", *cp.common(root), "--dry-run"])
        assert rc == 0 and "nothing written" in o and "House Mizzrym" in o
        assert {q: q.read_bytes() for q in drafts(root).rglob("*") if q.is_file()} == before

    def test_an_incomplete_planning_draft_is_not_annotated(self, pcamp):
        root, pm = pcamp
        pm.override["## DM Notes"] = ""
        rc, out, err = synth_planning(root)
        assert rc == 3
        assert not (drafts(root) / "annotations.md").exists()


# ── Annotation: the code-built blocks are never scanned ──────────────────────


class TestAnnotationSkipsCodeBuiltBlocks:
    EV = SimpleNamespace(canon=lambda n: n)

    def test_threat_tracker_npc_dossiers_dormant_and_unratified_are_not_entries(self):
        lines = [
            "## NPC Dossiers", "### Kalan", "- **Kalan** — a fallback line (no published dossier — from checked notes)",
            "## Active Plots", "### The Carver's march", "- a model bullet [ch 004 / 004.01]",
            schema.DORMANT_HEADING, "- **The signet ring** — a dormant line [ch 004 / 004.02]",
            schema.UNRATIFIED_HEADING, "- [OPENED] **Other** — an unratified note [ch 002 / 002.02]",
            "## Faction States", "### House Mizzrym", "- a faction bullet [ch 003 / 003.02]",
        ]
        got = annotate.parse_entries(lines, self.EV)
        assert [e.text for e in got] == ["- a model bullet [ch 004 / 004.01]", "- a faction bullet [ch 003 / 003.02]"]
