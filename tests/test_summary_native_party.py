"""Spec 034 User Story 1: party built from the checked notes (T013-T015).

``party_notes`` is deterministic code: attribution (research R2), the level line (R3) and the two
files that keep every checked note. ``synth party`` is the chunked build around it: one call per
configured character, one each for the overview and the dynamics, and code-built headings and level
lines the model never writes.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from pipelines.summary_native import notes, party_notes, schema, state_sections
from tests import conftest_party as cp
from tests import conftest_state as cs

# ── helpers ─────────────────────────────────────────────────────────────────


def pnote(subject: str, text: str | None = None, chapter: int = 2, *, level: int | None = None) -> notes.Note:
    """A kept party note, built the way ``notes.check_chunk`` builds one."""
    cite = f"[ch {chapter:03d} / {chapter:03d}.01]"
    if level is not None:
        body = f"- [LEVEL] **{subject}** — {level} {cite}"
    else:
        body = f"- **{subject}** — {text or 'does a thing'} {cite}"
    return notes.Note("party", body, chapter, f"{chapter:03d}-{chapter:03d}",
                      tag=schema.LEVEL_TAG if level is not None else None, subject=subject, level=level)


def chunk(*ns: notes.Note) -> list[notes.CheckedChunk]:
    return [notes.CheckedChunk("002-004", list(ns))]


def identity(entities=(), plays=()):
    return state_sections.build_identity(list(entities), list(plays))


NAMES = ["Daz", "Zalthir"]
ENTITIES = [("Ront", []), ("Ilvara Mizzrym", ["Ilvara"]), ("Topsy and Turvy", [])]


def attribute_one(subject: str, entities=ENTITIES, plays=("Daz",), names=NAMES):
    (a,) = party_notes.attribute(chunk(pnote(subject)), identity(entities, plays), names)
    return a


# ── T013: attribution ───────────────────────────────────────────────────────


class TestAttribute:
    def test_party_is_party_wide_whatever_its_case(self):
        for s in ("Party", "party", "PARTY"):
            a = attribute_one(s)
            assert a.scope == "party" and a.characters == ()

    def test_a_player_character_subject_goes_to_that_character(self):
        a = attribute_one("Daz")
        assert (a.scope, a.characters) == ("character", ("Daz",))

    def test_match_is_by_casefolded_equality(self):
        assert attribute_one("zalthir").characters == ("Zalthir",)

    def test_party_yaml_names_and_players_plays_both_count(self):
        # Zalthir is only in party.yaml here; Gyrgum is only in players.yaml.
        a = party_notes.attribute(chunk(pnote("Zalthir"), pnote("Gyrgum")), identity(ENTITIES, ["Gyrgum"]), NAMES)
        assert [(x.scope, x.characters) for x in a] == [("character", ("Zalthir",)), ("character", ("Gyrgum",))]

    def test_a_joint_subject_with_no_such_entity_goes_to_both(self):
        a = attribute_one("Daz and Zalthir")
        assert (a.scope, a.characters) == ("character", ("Daz", "Zalthir"))

    @pytest.mark.parametrize("subject", ["Daz, Zalthir", "Daz & Zalthir", "Daz, and Zalthir"])
    def test_other_joiners_split_too(self, subject):
        assert attribute_one(subject).characters == ("Daz", "Zalthir")

    def test_an_entity_whose_name_contains_and_stays_one_companion(self):
        a = attribute_one("Topsy and Turvy")
        assert (a.scope, a.characters, a.companions) == ("companion", (), ("Topsy and Turvy",))

    def test_a_registry_npc_is_a_companion_by_name_or_alias(self):
        assert attribute_one("Ront").scope == "companion"
        a = attribute_one("Ilvara")
        assert (a.scope, a.companions) == ("companion", ("Ilvara Mizzrym",))

    def test_an_unknown_subject_is_unattributed_with_a_reason_never_guessed(self):
        a = attribute_one("Dazz")  # one letter from Daz: similarity must not match it
        assert a.scope == "unattributed" and a.characters == ()
        assert "Dazz" in a.reason

    def test_a_split_subject_needs_every_piece_to_resolve(self):
        a = attribute_one("Daz and Dazz")
        assert a.scope == "unattributed" and "Dazz" in a.reason

    def test_a_form_claimed_by_two_entities_is_unattributed(self):
        a = attribute_one("Bob", entities=[("Bob Smith", ["Bob"]), ("Bob Jones", ["Bob"])])
        assert a.scope == "unattributed" and "claimed by more than one entity" in a.reason

    def test_a_player_character_with_a_registry_alias_resolves_through_it(self):
        ents = [("Daz Devir", ["Daz"])]
        a = party_notes.attribute(chunk(pnote("Daz Devir"), pnote("Daz")), identity(ents, ["Daz"]), NAMES)
        assert [(x.scope, x.characters) for x in a] == [("character", ("Daz",))] * 2

    def test_a_player_character_is_never_a_companion(self):
        a = attribute_one("Zalthir", entities=[("Zalthir", [])], plays=("Zalthir",))
        assert a.scope == "character"

    def test_one_attribution_per_distinct_note_in_chapter_order(self):
        n3, n2 = pnote("Daz", chapter=3), pnote("Ront", chapter=2)
        got = party_notes.attribute(chunk(n3, n2, n3), identity(ENTITIES, ["Daz"]), NAMES)
        assert [a.note_id for a in got] == [n2.note_id, n3.note_id]

    def test_attributes_the_fixture_notes(self):
        ident = identity([("Ront", []), ("Ilvara Mizzrym", ["Ilvara"])], ["Daz", "Zalthir"])
        got = {a.note.subject: a for a in party_notes.attribute(cp.checked_results(), ident, NAMES)}
        assert got["Party"].scope == "party"
        assert got["Daz"].characters == ("Daz",)
        assert got["Daz and Zalthir"].characters == ("Daz", "Zalthir")
        assert got["Ront"].scope == "companion"
        assert got["Dazz"].scope == "unattributed"


# ── T014: the level line ────────────────────────────────────────────────────


def level_of(name, ns, sheet=None, *, plays=("Daz", "Zalthir")):
    results = chunk(*ns)
    attrs = party_notes.attribute(results, identity(ENTITIES, plays), NAMES)
    return party_notes.level_line(name, results, attrs, sheet)


class TestLevelLine:
    def test_the_latest_row_wins_with_its_citation(self):
        line = level_of("Daz", [pnote("Party", level=8, chapter=2), pnote("Party", level=9, chapter=4)])
        assert line == "Level: 9 [ch 004 / 004.01]"

    def test_a_later_party_row_beats_an_earlier_character_row(self):
        line = level_of("Daz", [pnote("Daz", level=8, chapter=2), pnote("Party", level=9, chapter=3)])
        assert line == "Level: 9 [ch 003 / 003.01]"

    def test_a_character_row_beats_a_party_row_in_the_same_chapter(self):
        line = level_of("Daz", [pnote("Party", level=9, chapter=3), pnote("Daz", level=10, chapter=3)])
        assert line == "Level: 10 [ch 003 / 003.01]"
        line = level_of("Daz", [pnote("Daz", level=10, chapter=3), pnote("Party", level=9, chapter=3)])
        assert line == "Level: 10 [ch 003 / 003.01]"  # not an artifact of row order

    def test_another_characters_row_is_not_this_characters_level(self):
        line = level_of("Daz", [pnote("Zalthir", level=5)], "Level: 8\n")
        assert line == "Level: not recorded in the summaries (sheet says 8)"

    def test_a_joint_subject_row_counts_for_each_character(self):
        assert level_of("Zalthir", [pnote("Daz and Zalthir", level=6)]).startswith("Level: 6 ")

    def test_no_row_shows_the_sheets_figure_as_the_sheets(self):
        assert level_of("Daz", [], "# Daz\n\nClass: Wizard\nLevel: 8\n") == (
            "Level: not recorded in the summaries (sheet says 8)")

    def test_no_row_and_no_sheet_level_says_the_sheet_gives_none(self):
        assert level_of("Daz", [], "# Daz\n\nClass: Wizard\n") == "Level: not recorded in the summaries (sheet gives none)"
        assert level_of("Daz", [], None) == "Level: not recorded in the summaries (sheet gives none)"

    def test_a_row_ignores_the_sheet(self):
        assert level_of("Daz", [pnote("Party", level=9)], "Level: 8\n") == "Level: 9 [ch 002 / 002.01]"

    def test_the_source_is_reported_for_party_report(self):
        results = chunk(pnote("Party", level=9, chapter=3))
        attrs = party_notes.attribute(results, identity(ENTITIES, ["Daz"]), NAMES)
        lv = party_notes.level_for("Daz", results, attrs, "Level: 8\n")
        assert lv.level == 9 and "Party" in lv.source and "ch 003" in lv.source


class TestSheetLevel:
    """The sheet pattern is explicit lines only; nothing is guessed from prose or spell headings."""

    @pytest.mark.parametrize("text,want", [
        ("Level: 8\n", 8),
        ("**Level:** 8\n", 8),
        ("- **Level:** 12\n", 12),
        ("| Level | 7 |\n", 7),
        ("Level 9\n\nClass: Wizard\n", None),  # a bare "Level 9" line is not a header
        ("## Level 9\n", 9),
        ("### 9th-level Wizard\n", 9),
        ("class_level: Wizard 9\n", 9),
        ("- **Class & Level:** Wizard 9\n", 9),
        ("- **Class & Level:** Wizard 5 / Cleric 4\n", None),  # multiclass: two numbers, not one level
        ("Class: Wizard\nEquipment: staff\n", None),
        ("### 1st Level (4 Slots: OOOO)\n### 3rd Level Spells\n", None),  # spell levels are not character levels
        ("Level 1 Spell. Choose a level 1 spell.\n", None),
        ("Level: 8\nLevel: 9\n", None),  # two figures: unreadable, not guessed
        ("", None),
    ])
    def test_patterns(self, text, want):
        assert party_notes.sheet_level(text) == want

    def test_the_oota_shaped_sheet(self):
        sheet = (cp.PARTY_FIXTURE / "docs" / "sheets" / "oota-shape-daz.md").read_text(encoding="utf-8")
        assert party_notes.sheet_level(sheet) == 9


# ── reference/party.md and party_report.md ──────────────────────────────────


class TestReferenceAndReport:
    def setup_method(self):
        self.results = cp.checked_results()
        self.ident = identity([("Ront", []), ("Ilvara Mizzrym", ["Ilvara"])], ["Daz", "Zalthir"])
        self.attrs = party_notes.attribute(self.results, self.ident, NAMES)

    def test_groups_are_pcs_in_party_order_then_party_companions_unattributed(self):
        md = party_notes.reference_md(self.results, self.attrs, NAMES)
        heads = re.findall(r"^## (.+)$", md, re.M)
        assert heads == ["Daz", "Zalthir", "Party", "Companions", "Unattributed"]

    def test_notes_are_verbatim_and_in_chapter_order(self):
        md = party_notes.reference_md(self.results, self.attrs, NAMES)
        daz = md.split("## Daz\n")[1].split("\n## ")[0]
        assert daz.index("Counts the march's banners") < daz.index("Is wounded in the fight")
        for a in self.attrs:
            assert a.note.text in md

    def test_a_joint_note_is_kept_under_each_character(self):
        md = party_notes.reference_md(self.results, self.attrs, NAMES)
        assert md.count("- **Daz and Zalthir** — Hold the gate together.") == 2

    def test_companions_group_by_name_and_unattributed_keep_their_text(self):
        md = party_notes.reference_md(self.results, self.attrs, NAMES)
        assert "### Ront" in md.split("## Companions")[1]
        assert "**Dazz** — Offers to carry the packs." in md.split("## Unattributed")[1]

    def test_a_character_with_no_notes_still_has_a_group(self):
        md = party_notes.reference_md(chunk(pnote("Daz")), party_notes.attribute(
            chunk(pnote("Daz")), self.ident, NAMES), NAMES)
        assert schema.NONE_VERIFIED in md.split("## Zalthir")[1]

    def test_report_lists_every_unattributed_subject_with_text_and_citation(self):
        levels = {n: party_notes.level_for(n, self.results, self.attrs, None) for n in NAMES}
        md = party_notes.report_md(self.results, self.attrs, NAMES, levels, since=2, until=4)
        un = md.split("## Unattributed")[1]
        assert "Dazz" in un and "Offers to carry the packs." in un and "[ch 002 / 002.01]" in un
        assert "Ront" in md.split("## Companions")[1].split("## Unattributed")[0]
        assert "## Level source" in md and "Daz" in md.split("## Level source")[1]

    def test_both_are_deterministic(self):
        levels = {n: party_notes.level_for(n, self.results, self.attrs, "Level: 8\n") for n in NAMES}
        a = party_notes.reference_md(self.results, self.attrs, NAMES), party_notes.report_md(
            self.results, self.attrs, NAMES, levels, since=2, until=4)
        b = party_notes.reference_md(self.results, self.attrs, NAMES), party_notes.report_md(
            self.results, self.attrs, NAMES, levels, since=2, until=4)
        assert a == b


# ── T015: synth party end to end ────────────────────────────────────────────

BACKEND = ["--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1"]


def synth_party(root, *extra):
    return cs.run_cli(["synth", "party", *cp.common(root), *BACKEND, *extra])


@pytest.fixture
def pcamp(tmp_path, monkeypatch):
    root = cp.party_campaign(tmp_path)
    fm = cp.fake_party_models(monkeypatch)
    rc, out, err = cs.run_cli(cp.extract_args(root))
    assert rc == 0, out + err
    return root, fm


def drafts(root) -> Path:
    return cp.range_dir(root) / "state" / "drafts"


class TestSynthParty:
    def test_builds_a_complete_draft(self, pcamp):
        root, fm = pcamp
        rc, out, err = synth_party(root)
        assert rc == 0, out + err
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        assert (drafts(root) / "party.incomplete.md").exists() is False
        assert re.findall(r"^## .+$", text, re.M) == ["## Party Overview", "## Characters", "## Party Dynamics"]

    def test_the_draft_opens_with_the_party_contract(self, pcamp):
        root, _ = pcamp
        synth_party(root)
        lines = (drafts(root) / "party.draft.md").read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("<!-- summary_native draft | doc: party")
        assert lines[1].startswith("> **How to read this document.**")
        body = "\n".join(lines[:20])
        assert "reference/party.md" in body and "reference/factions.md" not in body and "## Key NPCs" not in body

    def test_one_heading_per_configured_character_in_config_order_with_level_and_body(self, pcamp):
        root, fm = pcamp
        assert synth_party(root)[0] == 0
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        chars = text.split("## Characters\n")[1].split("\n## Party Dynamics")[0]
        assert re.findall(r"^### (.+)$", chars, re.M) == ["Daz", "Zalthir"]
        daz = chars.split("### Daz\n")[1].split("\n### ")[0]
        assert daz.lstrip().startswith("Level: 9 [ch 002 / 002.01]")
        assert "Body for Daz" in daz  # the model's text sits under the code-built heading and level line
        assert daz.index("Level: 9") < daz.index("Body for Daz")
        assert "_Full notes: reference/party.md_" in daz
        assert "Body for Zalthir" in chars.split("### Zalthir\n")[1]

    def test_the_model_never_writes_the_heading_or_level_line(self, pcamp):
        root, fm = pcamp
        fm.character_override["Daz"] = "### Daz\n\nLevel: 12\n\nA body [ch 003 / 003.01].\n"
        rc, out, err = synth_party(root)
        # a level line or heading from the model makes the section unusable, so the draft is incomplete
        assert rc == 3 and "Daz" in err
        assert (drafts(root) / "party.incomplete.md").is_file() and not (drafts(root) / "party.draft.md").exists()

    def test_one_call_per_character_plus_overview_and_dynamics(self, pcamp):
        root, fm = pcamp
        synth_party(root)
        got = [(c["heading"], c["character"]) for c in fm.party_calls]
        assert sorted(got, key=str) == sorted([
            ("## Party Overview", None), ("## Characters", "Daz"), ("## Characters", "Zalthir"),
            ("## Party Dynamics", None)], key=str)

    def test_a_characters_prompt_holds_no_other_characters_notes(self, pcamp):
        root, fm = pcamp
        synth_party(root)
        daz = next(c for c in fm.party_calls if c["character"] == "Daz")["user"]
        zal = next(c for c in fm.party_calls if c["character"] == "Zalthir")["user"]
        assert "Counts the march's banners" in daz and "Is wounded in the fight" in daz
        assert "Wards the camp" not in daz and "Reads a scroll aloud" not in daz
        assert "Carries Daz back from the gate" not in daz  # a Zalthir note that names Daz is still Zalthir's
        assert "Wards the camp" in zal and "Counts the march's banners" not in zal
        assert "Hold the gate together" in daz and "Hold the gate together" in zal  # the joint note is both
        # nothing attributed elsewhere, and no level row, reaches either prompt
        for prompt in (daz, zal):
            assert "Keeps watch from the wall" not in prompt and "Offers to carry the packs" not in prompt
            assert "[LEVEL]" not in prompt

    def test_the_sheet_and_backstory_of_that_character_only(self, pcamp):
        root, fm = pcamp
        synth_party(root)
        daz = next(c for c in fm.party_calls if c["character"] == "Daz")["user"]
        zal = next(c for c in fm.party_calls if c["character"] == "Zalthir")["user"]
        assert "Equipment: quarterstaff, spellbook" in daz and "Collegium of Brindol" in daz
        assert "quarterstaff" not in zal and "Equipment: mace, holy symbol" in zal

    def test_party_wide_notes_of_the_last_chunk_reach_a_character_prompt(self, pcamp):
        root, fm = pcamp
        synth_party(root)
        daz = next(c for c in fm.party_calls if c["character"] == "Daz")["user"]
        assert "[ch 004 / end]" in daz  # the chapter 4 (last chunk) party-wide note
        assert "**Party** — The party holds the gate of Brindol. [ch 002 / 002.01]" not in daz  # an earlier chunk's

    def test_overview_and_dynamics_see_party_wide_notes_and_the_latest_two_per_character(self, pcamp):
        root, fm = pcamp
        synth_party(root)
        ov = next(c for c in fm.party_calls if c["heading"] == "## Party Overview")["user"]
        assert "**Party** — The party holds the gate of Brindol. [ch 002 / 002.01]" in ov and "[ch 004 / end]" in ov
        assert "Is wounded in the fight" in ov and "Carries Daz back from the gate" in ov
        assert "Keeps watch from the wall" not in ov  # a companion's note is not the overview's

    def test_dynamics_also_see_the_companions(self, pcamp):
        # GM ruling 2026-10-08: bonds with companions belong in Party Dynamics.
        root, fm = pcamp
        synth_party(root)
        dyn = next(c for c in fm.party_calls if c["heading"] == "## Party Dynamics")["user"]
        assert "THE LATEST TWO NOTES OF EACH COMPANION" in dyn
        assert "Keeps watch from the wall" in dyn  # Ront's (a companion's) note
        assert "Is wounded in the fight" in dyn  # still the characters' latest notes too

    def test_a_character_with_no_notes_says_so_and_makes_no_call(self, pcamp):
        root, fm = pcamp
        # Zalthir has notes in the fixture; give party.yaml a third character nobody wrote about.
        cfg = root / "config" / "party.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + "  - name: Nobody\n    sheet: docs/sheets/zalthir.md\n    arc_score: null\n",
                       encoding="utf-8")
        rc, out, err = synth_party(root)
        assert rc == 0, out + err
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        nobody = text.split("### Nobody\n")[1].split("\n## ")[0]
        assert "The summaries in this range record nothing for Nobody." in nobody
        assert "Level: 9 [ch 002 / 002.01]" in nobody  # the level line is still the code's
        assert "Body for" not in nobody and "_Full notes: reference/party.md_" in nobody
        assert "Nobody" not in [c["character"] for c in fm.party_calls]
        assert re.findall(r"^### (.+)$", text, re.M) == ["Daz", "Zalthir", "Nobody"]

    def test_reference_party_md_groups_and_party_report(self, pcamp):
        root, _ = pcamp
        synth_party(root)
        ref = (drafts(root) / "reference" / "party.md").read_text(encoding="utf-8")
        assert re.findall(r"^## (.+)$", ref, re.M) == ["Daz", "Zalthir", "Party", "Companions", "Unattributed"]
        assert "**Ront** — Keeps watch from the wall." in ref.split("## Companions")[1]
        assert "**Dazz** — Offers to carry the packs." in ref.split("## Unattributed")[1]
        report = (drafts(root) / "party_report.md").read_text(encoding="utf-8")
        assert "Dazz" in report.split("## Unattributed")[1] and "Ront" in report
        # party writes its own reference file only
        assert sorted(p.name for p in (drafts(root) / "reference").iterdir()) == ["party.md"]
        assert not (drafts(root) / "npc_status_report.md").exists()

    def test_dump_only_makes_no_call_and_writes_the_prompts_and_a_record(self, pcamp):
        root, fm = pcamp
        rc, out, err = synth_party(root, "--dump-only")
        assert rc == 0 and fm.prose_calls == []
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert (run / "party.characters_daz.user.md").is_file() and (run / "party.characters_zalthir.user.md").is_file()
        assert (run / "party.party_overview.user.md").is_file() and (run / "record.json").is_file()

    def test_the_run_record_has_party_config_shas_and_budgets(self, pcamp):
        root, _ = pcamp
        assert synth_party(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text(encoding="utf-8"))
        pc = rec["inputs"]["party_config"]
        cfg = root / "config" / "party.yaml"
        assert pc["path"] == "config/party.yaml" and pc["sha256"] == hashlib.sha256(cfg.read_bytes()).hexdigest()
        files = {f["path"]: f["sha256"] for f in pc["files"]}
        sheet = root / "docs" / "sheets" / "daz.md"
        assert files["docs/sheets/daz.md"] == hashlib.sha256(sheet.read_bytes()).hexdigest()
        assert {"docs/sheets/daz-backstory.md", "docs/mechanics/daz-arc.md", "docs/sheets/zalthir.md"} <= set(files)
        assert rec["inputs"]["budgets"] == schema.DEFAULT_PARTY_BUDGETS
        assert set(rec["budgets"]) >= {"Party Overview", "Characters: Daz", "Characters: Zalthir", "Party Dynamics"}
        assert [c["character"] for c in rec["calls"] if c["heading"] == "## Characters"] == ["Daz", "Zalthir"]

    def test_a_budget_overrun_is_reported_never_trimmed(self, pcamp):
        root, fm = pcamp
        long_body = " ".join(["word"] * 650) + " [ch 004 / 004.01]."
        fm.character_override["Daz"] = long_body
        rc, out, err = synth_party(root)
        assert rc == 0
        assert "OVER" in out
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        assert long_body in text  # kept whole
        assert "Daz" in (drafts(root) / "party_report.md").read_text(encoding="utf-8").split("## Budgets")[1]

    def test_a_missing_character_body_makes_the_draft_incomplete(self, pcamp):
        root, fm = pcamp
        fm.character_override["Zalthir"] = ""
        rc, out, err = synth_party(root)
        assert rc == 3 and "Zalthir" in err
        assert (drafts(root) / "party.incomplete.md").is_file()

    def test_rebuild_determinism_of_every_code_built_line(self, pcamp):
        root, _ = pcamp
        assert synth_party(root)[0] == 0
        first = {n: (drafts(root) / n).read_bytes() for n in ("party.draft.md", "party_report.md", "reference/party.md")}
        assert synth_party(root, "--force")[0] == 0
        second = {n: (drafts(root) / n).read_bytes() for n in first}
        # the run id in the header comment names the run; everything else is identical
        strip = lambda b: re.sub(rb"record: runs/[^ ]+ ", b"record: runs/X ", b)  # noqa: E731
        assert strip(first["party.draft.md"]) == strip(second["party.draft.md"])
        assert first["party_report.md"] == second["party_report.md"]
        assert first["reference/party.md"] == second["reference/party.md"]

    def test_annotation_never_removes_a_player_character_section(self, pcamp):
        root, fm = pcamp
        fm.character_override["Daz"] = "- Daz counts the banners from the ridge [ch 003 / 003.01].\n- Daz is wounded [ch 004 / 004.01].\n"
        assert synth_party(root)[0] == 0
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        assert "### Daz" in text and "### Zalthir" in text
        assert "- Daz counts the banners from the ridge [ch 003 / 003.01]." in text  # a line's own text is never changed
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        rec = json.loads((run / "record.json").read_text(encoding="utf-8"))
        assert rec["annotations"]["removed"] == 0

    def test_a_missing_party_yaml_is_refused_before_any_call(self, pcamp):
        root, fm = pcamp
        (root / "config" / "party.yaml").unlink()
        rc, out, err = synth_party(root)
        assert rc == 2 and "party.yaml" in err and fm.prose_calls == []

    def test_party_config_flag_picks_the_roster(self, pcamp):
        root, fm = pcamp
        (root / "config" / "alt.yaml").write_text(
            "characters:\n  - name: Zalthir\n    sheet: docs/sheets/zalthir.md\n    arc_score: null\n", encoding="utf-8")
        rc, out, err = synth_party(root, "--party-config", "config/alt.yaml")
        assert rc == 0, out + err
        text = (drafts(root) / "party.draft.md").read_text(encoding="utf-8")
        assert re.findall(r"^### (.+)$", text, re.M) == ["Zalthir"]
        # Daz is a player character (players.yaml) with notes but no section: reported, never given one
        assert "Daz" in (drafts(root) / "party_report.md").read_text(encoding="utf-8").split("no party.yaml entry")[1]
        rc, out, err = synth_party(root, "--party-config", "config/nope.yaml", "--force")
        assert rc == 2 and "nope.yaml" in err

    def test_party_does_not_change_world_state(self, pcamp):
        root, _ = pcamp
        assert synth_party(root)[0] == 0
        assert not (drafts(root) / "world_state.draft.md").exists()
