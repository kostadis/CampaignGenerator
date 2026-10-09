"""synth: outline check, refusals, and the behaviours every document shares (T020, spec 034 T047/T048).

Every document is built the same way: one call per section, from the checked notes (spec 034 retired the
one-shot path). The generic behaviours of a ``synth`` run (run ids, the record written on a failure, the
previous draft kept on an incomplete build, freshness) are asserted for all four documents in
``TestEveryDocumentBuildsTheSameWay`` below.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import synth
from pipelines.summary_native.cli import main

FIX = Path(__file__).parent / "fixtures" / "summary_native"
RD = "docs/summary_native/ch002-005"


@pytest.fixture
def camp(tmp_path, monkeypatch):
    """A built corpus and no extraction: whatever ``synth`` does here, it does before reading any note."""
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    shutil.copytree(FIX / "clean", root / "summaries")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "world_state.md").write_text("LIVE WORLD\n")
    (root / "docs" / "campaign_state.md").write_text("LIVE CAMPAIGN\n")
    monkeypatch.chdir(root)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    write_party(root, trackless=True)
    return root


ARGS = ["--summaries-dir", "summaries"]


@pytest.fixture
def fake(monkeypatch):
    calls = []
    state = {"texts": None}

    def render_part(client, system, user, model, max_tokens):
        calls.append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
        t = state["texts"]
        return t.pop(0) if isinstance(t, list) else t

    def no_client(a, **k):
        return object()

    monkeypatch.setattr(synth, "render_part", render_part)
    monkeypatch.setattr(synth, "client_from_args", no_client)
    return calls, state


def test_check_outline_problems():
    hs = ["## A", "## B"]
    assert synth.check_outline("## A\n\nx\n\n## B\n\ny\n", hs) == []
    assert synth.check_outline("<!-- c -->\n## A\n\nx\n\n## B\n\ny", hs) == []
    assert any("missing" in p for p in synth.check_outline("## A\n\nx\n", hs))
    assert any("order" in p for p in synth.check_outline("## B\n\ny\n\n## A\n\nx\n", hs))
    assert any("empty" in p for p in synth.check_outline("## A\n\n## B\n\ny\n", hs))
    assert synth.check_outline("Sure! here:\n## A\n\nx\n\n## B\n\ny", hs)


def test_check_outline_unexpected_heading():
    hs = ["## A"]
    assert any("unexpected" in p for p in synth.check_outline("## A\n\nx\n\n## Z\n\ny\n", hs))


def test_audit_rejected_for_world_state(camp):
    (camp / "track.md").write_text("x\n")
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 2


def test_unknown_doc_rejected_by_parser(camp):
    with pytest.raises(SystemExit):
        main(["synth", "nonsense", *ARGS, "--dump-only"])


def test_synth_refuses_stale_corpus(camp, fake, capsys):
    calls, _ = fake
    f = camp / "summaries" / "002-the-gate.md"
    f.write_text(f.read_text() + "\nAn edit after build.\n")
    assert main(["synth", "party", *ARGS]) == 2
    assert "summaries changed since build" in capsys.readouterr().err
    assert not calls


def test_synth_refuses_blocking_validation(camp, fake, capsys):
    f = camp / "summaries" / "002-the-gate.md"
    f.write_text(f.read_text().replace("# Chapter 2", "# Chapter 9"))
    assert main(["synth", "party", *ARGS]) == 1  # same as validate/build
    assert "blocking" in capsys.readouterr().out.lower()  # the report is printed
    assert not fake[0]


def test_synth_refuses_incomplete_manifest(camp, fake):
    mp = camp / RD / "manifest.json"
    m = json.loads(mp.read_text())
    m["complete"] = False
    mp.write_text(json.dumps(m))
    assert main(["synth", "party", *ARGS]) == 2
    assert not fake[0]


def test_synth_refuses_unbuilt_range(camp, fake):
    shutil.rmtree(camp / RD)
    assert main(["synth", "party", *ARGS]) == 2


def test_party_flags_rejected_for_other_docs(camp):
    write_party(camp)
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--party-config", "config/party.yaml"]) == 2
    assert main(["synth", "party", *ARGS, "--dump-only", "--planning-config", "config/planning.yaml"]) == 2


def test_registry_change_makes_corpus_stale(camp, fake, capsys):
    calls, _ = fake
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("entities: []\n")
    assert main(["synth", "party", *ARGS]) == 2
    err = capsys.readouterr().err
    assert "entity registry changed since build" in err and "summary_native build --force" in err
    assert not calls


def write_party(camp, *, trackless=False, missing_sheet=False):
    (camp / "docs").mkdir(exist_ok=True)
    (camp / "docs" / "Daz.md").write_text("SHEET-OF-DAZ level 5 fighter\n")
    (camp / "docs" / "daz_backstory.md").write_text("BACKSTORY-OF-DAZ was a sellsword\n")
    entry = {"name": "Daz", "sheet": "docs/Nope.md" if missing_sheet else "docs/Daz.md",
             "backstory": "docs/daz_backstory.md"}
    if trackless:
        entry["arc_score"] = None
    (camp / "config" / "party.yaml").write_text(yaml.safe_dump({"characters": [entry]}, sort_keys=False))


# ── spec 033 US1: world_state and campaign_state build from checked notes (T015) ─────────────


from pipelines.summary_native import notes as notes_mod  # noqa: E402
from pipelines.summary_native import schema  # noqa: E402
from tests import conftest_state as cs  # noqa: E402

WORLD_PROSE = ["## Party", "## Factions and Powers", "## Key NPCs", "## Locations", "## Items and Artifacts",
               "## Active Threats and Open Pressures"]
CAMPAIGN_PROSE = ["## Resolved Plot Threads", "## Active Quests & Open Threads", "## Party Current Situation"]


@pytest.fixture
def scamp(tmp_path):
    return cs.state_campaign(tmp_path)


@pytest.fixture
def fm(monkeypatch):
    return cs.fake_models(monkeypatch)


@pytest.fixture
def extracted(scamp, fm):
    rc, _, err = cs.run_cli(cs.extract_args(scamp))
    assert rc == 0, err
    fm.extract_calls.clear()
    return scamp


def synth_args(root, doc, *extra):
    """The fixture publishes a dossier for one of its three selectable NPCs, so world_state builds only with
    ``--fallback-npc-lines``; ``test_summary_native_key_npcs`` covers the default refusal."""
    fallback = ["--fallback-npc-lines"] if doc == "world_state" and "--no-fallback" not in extra else []
    return ["synth", doc, *cs.common(root), *fallback, *(e for e in extra if e != "--no-fallback")]


def state_dir(root):
    return cs.range_dir(root) / schema.STATE_DIR


def draft_of(root, doc):
    return (state_dir(root) / "drafts" / f"{doc}.draft.md").read_text()


def section(text, heading):
    secs = notes_mod.npc_check.parse_sections(text)
    return notes_mod.npc_check.section_text(secs, heading)


class TestChunkedRefusals:
    def test_without_notes_refuses_naming_the_extract_command(self, scamp, fm):
        for doc in ("world_state", "campaign_state"):
            rc, _, err = cs.run_cli(synth_args(scamp, doc))
            assert rc == 2
            assert "summary_native extract --since 2 --until 5" in err
            assert "no checked notes" in err
        assert not fm.prose_calls

    def test_stale_notes_refuse_naming_the_command(self, extracted, fm):
        (extracted / "config" / "players.yaml").write_text("players: []\n")
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 2 and "stale" in err and "players" in err
        assert "summary_native extract --since 2 --until 5" in err and not fm.prose_calls

    def test_notes_with_a_failed_chunk_refuse(self, scamp, fm):
        fm.fail_chunks["004-004"] = 2
        assert cs.run_cli(cs.extract_args(scamp))[0] == 3
        rc, _, err = cs.run_cli(synth_args(scamp, "campaign_state"))
        assert rc == 2 and "004-004" in err and "summary_native extract --since 2 --until 5" in err

    def test_dump_only_extraction_is_not_checked_notes(self, scamp, fm):
        assert cs.run_cli(cs.extract_args(scamp, "--dump-only"))[0] == 0
        rc, _, err = cs.run_cli(synth_args(scamp, "world_state"))
        assert rc == 2 and "summary_native extract" in err

    @pytest.mark.parametrize("doc", schema.DOCS)
    @pytest.mark.parametrize("flag,value", [("--parts", "2"), ("--world-state", "docs/npcs/ilvara-mizzrym.md"),
                                            ("--campaign-state", "docs/npcs/ilvara-mizzrym.md")])
    def test_the_retired_flags_are_refused_for_every_document_with_notes_in_place(self, extracted, fm, doc, flag, value):
        """The CLI-level matrix is in test_summary_native_cli.py; this one proves no model is reached."""
        rc, _, err = cs.run_cli(synth_args(extracted, doc, flag, value))
        assert rc == 2 and schema.RETIRED_SYNTH_FLAGS[flag[2:].replace("-", "_")] in err
        assert not fm.prose_calls

    def test_audit_is_retired_for_campaign_state_naming_the_audit_step(self, extracted, fm):
        rc, _, err = cs.run_cli(synth_args(extracted, "campaign_state", "--audit", "docs/tracking/tracking.txt"))
        assert rc == 2 and "the audit is its own step: summary_native audit" in err

    def test_audit_is_still_refused_for_world_state(self, extracted, fm):
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state", "--audit", "docs/tracking/tracking.txt"))
        assert rc == 2 and "campaign_state only" in err

    def test_a_stale_audit_refuses_naming_the_audit_step(self, extracted, fm):
        (extracted / "config" / "grounding.yaml").write_text(
            "campaign_state:\n  track_files: [docs/tracking/tracking.txt]\n")
        audit = state_dir(extracted) / "audit"
        audit.mkdir(parents=True)
        (audit / "items.json").write_text(json.dumps({"track_files_sha256": [["tracking.txt", "stale"]]}))
        rc, _, err = cs.run_cli(synth_args(extracted, "campaign_state"))
        assert rc == 2 and "summary_native audit" in err and not fm.prose_calls

    @pytest.mark.parametrize("doc", ["party", "planning"])
    def test_party_and_planning_route_through_the_chunked_synth(self, extracted, fm, doc):
        """Spec 034 T012: no one-shot ``runs/<doc>/part-N.*``; the run lives in ``state/runs`` and the draft in ``state/drafts``."""
        extra = []
        if doc == "party":  # party reads its roster: the 033 fixture has none, so give it one (US1 refuses without)
            (extracted / "docs" / "sheet.md").write_text("# Daz\n\nLevel: 8\n")
            (extracted / "config" / "party.yaml").write_text("characters:\n  - name: Daz\n    sheet: docs/sheet.md\n")
        else:  # planning refuses an NPC with no published dossier, and this fixture publishes one of three
            extra = ["--fallback-npc-lines"]
        rc, out, err = cs.run_cli(synth_args(extracted, doc, "--dump-only", *extra))
        assert rc == 0, err
        (run,) = [p for p in (state_dir(extracted) / "runs").iterdir() if (p / f"{doc}.system.md").is_file()]
        assert (run / f"{doc}.system.md").is_file() and (run / "record.json").is_file()
        assert json.loads((run / "record.json").read_text())["doc"] == doc
        assert not (cs.range_dir(extracted) / "runs").exists() and not (cs.range_dir(extracted) / "drafts").exists()
        assert not fm.prose_calls

    def test_planning_opens_with_its_reading_contract_and_builds_with_fallback_lines(self, extracted, fm):
        """Spec 034 US2: planning's sections exist (party's: tests/test_summary_native_party.py; planning's in depth: tests/test_summary_native_planning.py)."""
        rc, _, err = cs.run_cli(synth_args(extracted, "planning", "--fallback-npc-lines"))
        assert rc == 0, err
        text = (state_dir(extracted) / "drafts" / "planning.draft.md").read_text()
        assert "How to read this document" in text and "summary_native pointers:" in text
        assert not (state_dir(extracted) / "drafts" / "planning.incomplete.md").exists()
        assert not (cs.range_dir(extracted) / "drafts").exists()

    def test_planning_refuses_an_npc_with_no_published_dossier_before_any_call(self, extracted, fm):
        rc, _, err = cs.run_cli(synth_args(extracted, "planning"))
        assert rc == 2 and "planning's NPC Dossiers need a published, verified dossier" in err
        assert not fm.prose_calls

    @pytest.mark.parametrize("doc", ["party", "planning"])
    def test_notes_extracted_under_the_old_party_grammar_refuse_naming_extract(self, extracted, fm, doc):
        nm = cs.notes_dir(extracted) / "manifest.json"
        m = json.loads(nm.read_text())
        m["system_sha256"] = "0" * 64
        nm.write_text(json.dumps(m))
        rc, _, err = cs.run_cli(synth_args(extracted, doc))
        assert rc == 2
        assert "the party notes predate the subject grammar" in err
        assert "summary_native extract --since 2 --until 5" in err
        # world_state is untouched by the party grammar
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state", "--dump-only"))
        assert rc == 0, err

    def test_budgets_default_per_document(self):
        assert synth._default_budgets("party") == schema.DEFAULT_PARTY_BUDGETS
        assert synth._default_budgets("planning") == schema.DEFAULT_PLANNING_BUDGETS
        assert synth._default_budgets("world_state") == schema.DEFAULT_WORLD_BUDGETS

    def test_every_document_drafts_under_state_drafts(self, tmp_path):
        for doc in schema.DOCS:
            assert schema.draft_dir(tmp_path, doc) == tmp_path / "state" / "drafts"
        assert schema.STATE_DOCS == schema.DOCS


class TestWorldState:
    def test_builds_a_complete_draft_from_one_prose_call_per_section(self, extracted, fm):
        rc, out, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 0, err
        assert [c["heading"] for c in fm.prose_calls] == WORLD_PROSE
        text = draft_of(extracted, "world_state")
        assert synth.check_outline(text, synth.load_outline("world_state")) == []
        assert "Prose for Locations" in section(text, "## Locations")
        first = text.splitlines()[0]
        assert first.startswith("<!-- summary_native draft | doc: world_state | range: ch002-005 | record: runs/")
        assert (state_dir(extracted) / "drafts" / "world_state.incomplete.md").exists() is False

    def test_the_timeline_is_code_built_in_chapter_order(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        # the events are their own file (US2); world_state's section only points at it
        assert not [ln for ln in section(draft_of(extracted, "world_state"), "## Canon Events Timeline").splitlines()
                    if ln.startswith("- ")]
        body = (state_dir(extracted) / "drafts" / schema.TIMELINE_FILE).read_text()
        events = [ln for ln in body.splitlines() if ln.startswith("- ")]
        assert events[0] == "- The party wakes in the pens of Velkynvelve. [ch 002 / 002.01]"
        assert events[-1] == "- The party rests and speaks of Ilvara Mizzrym's death. [ch 005 / 005.01]"
        chapters = [notes_mod.first_chapter(e) for e in events]
        assert chapters == sorted(chapters) and len(events) == 6  # chapter 3's second event cites outside its chunk and is dropped

    def test_each_section_gets_only_the_notes_routed_to_it(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        by = {c["heading"]: c["user"] for c in fm.prose_calls}
        assert "**Velkynvelve**" in by["## Locations"] and "**The Long Stair**" in by["## Locations"]
        assert "House Mizzrym" not in by["## Locations"] and "Signet Ring" not in by["## Locations"]
        assert "**House Mizzrym**" in by["## Factions and Powers"] and "Velkynvelve" not in by["## Factions and Powers"].split("OUTLINE")[0].split("VERIFIED NOTES")[1]
        assert "**Signet Ring**" in by["## Items and Artifacts"]
        assert "**The gate guards**" in by["## Active Threats and Open Pressures"]
        # the thread ledger rides with the threats section
        assert "[RESOLVED] **The signet ring**" in by["## Active Threats and Open Pressures"]
        # Party: the party notes plus the last chunk's evidence for the current state
        assert "The party rests at the gate of Velkynvelve." in by["## Party"]
        assert "CHAPTER 005" in by["## Party"] and "CHAPTER 002" not in by["## Party"]
        # every routed note is a verified one: the dropped bullets never reach a prompt
        assert all("the web is a lie" not in u and "A claim about a later chapter" not in u for u in by.values())

    def test_key_npcs_is_not_a_notes_routed_prose_section(self, extracted, fm):
        """Key NPCs reads the published dossiers (US3), never the [NPC] notes or the status table."""
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        user = next(c["user"] for c in fm.prose_calls if c["heading"] == "## Key NPCs")
        assert "### Ilvara Mizzrym" in user and "IDENTITY:" in user and "LAST OBSERVED STATE:" in user
        assert "[NPC] **" not in user and "CODE-BUILT NPC STATUS TABLE" not in user

    def test_the_prose_prompt_carries_the_quotation_rule(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert all("Quotation marks are reserved" in c["system"] for c in fm.prose_calls if c["heading"] != "## Key NPCs")

    def test_a_missing_prose_section_writes_incomplete_and_exits_3(self, extracted, fm):
        fm.prose_missing = {"## Locations"}
        rc, out, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 3
        drafts = state_dir(extracted) / "drafts"
        assert (drafts / "world_state.incomplete.md").is_file() and not (drafts / "world_state.draft.md").exists()
        assert "missing heading: ## Locations" in err + out
        inc = (drafts / "world_state.incomplete.md").read_text()
        assert "## Party" in inc and "## Locations" not in inc

    def test_a_good_draft_is_kept_when_a_later_run_is_incomplete(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        kept = (state_dir(extracted) / "drafts" / "world_state.draft.md").read_bytes()
        fm.prose_missing = {"## Party"}
        assert cs.run_cli(synth_args(extracted, "world_state", "--force"))[0] == 3
        assert (state_dir(extracted) / "drafts" / "world_state.draft.md").read_bytes() == kept

    def test_an_existing_draft_needs_force(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        n = len(fm.prose_calls)
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 2 and "--force" in err and len(fm.prose_calls) == n

    def test_dump_only_writes_prompts_and_makes_no_call(self, extracted, fm):
        rc, out, err = cs.run_cli(synth_args(extracted, "world_state", "--dump-only"))
        assert rc == 0, err
        assert not fm.prose_calls
        (run,) = [p for p in (state_dir(extracted) / "runs").iterdir() if p.is_dir() and (p / "record.json").exists()
                  and json.loads((p / "record.json").read_text()).get("step") == "synth"]
        assert json.loads((run / "record.json").read_text())["check"] == "not run"
        assert len(list(run.glob("world_state.*.user.md"))) == 6
        assert not (state_dir(extracted) / "drafts").exists()

    def test_the_run_record_names_inputs_settings_and_every_call(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        recs = [json.loads(p.read_text()) for p in (state_dir(extracted) / "runs").glob("*/record.json")]
        (rec,) = [r for r in recs if r.get("step") == "synth"]
        assert rec["doc"] == "world_state" and rec["backend"] == "claude-code"
        assert rec["model"] == "claude-sonnet-5-5" and rec["effort"] == "medium"
        assert rec["check"] == {"complete": True, "problems": []}
        assert [c["heading"] for c in rec["calls"]] == WORLD_PROSE
        assert rec["inputs"]["notes_manifest_sha256"] and rec["inputs"]["registry_sha256"]
        assert rec["started"] and rec["finished"]

    def test_flags_beat_grounding_yaml_beats_schema_for_the_prose_backend(self, extracted, fm):
        (extracted / "config" / "grounding.yaml").write_text(
            "summary_native:\n  prose:\n    backend: openrouter\n    model: vendor/model\n")
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert {c["model"] for c in fm.prose_calls} == {"vendor/model"}
        fm.prose_calls.clear()
        assert cs.run_cli(synth_args(extracted, "world_state", "--force", "--model", "flag-model"))[0] == 0
        assert {c["model"] for c in fm.prose_calls} == {"flag-model"}

    def test_never_writes_live_docs_or_the_corpus(self, extracted, fm):
        docs = {p.relative_to(extracted).as_posix(): p.read_bytes() for p in (extracted / "docs").rglob("*")
                if p.is_file() and "summary_native" not in p.parts}
        corpus = {p.name: p.read_bytes() for p in cs.range_dir(extracted).iterdir() if p.is_file()}
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        assert docs == {p.relative_to(extracted).as_posix(): p.read_bytes() for p in (extracted / "docs").rglob("*")
                        if p.is_file() and "summary_native" not in p.parts}
        assert corpus == {p.name: p.read_bytes() for p in cs.range_dir(extracted).iterdir() if p.is_file()}

    def test_the_secret_canary_in_a_published_dossier_reaches_nothing(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        for p in state_dir(extracted).rglob("*"):
            if p.is_file():
                assert "SECRET-CANARY-033" not in p.read_text(encoding="utf-8", errors="ignore"), p


class TestCampaignState:
    def test_builds_a_complete_draft(self, extracted, fm):
        rc, out, err = cs.run_cli(synth_args(extracted, "campaign_state"))
        assert rc == 0, err
        assert [c["heading"] for c in fm.prose_calls] == CAMPAIGN_PROSE
        text = draft_of(extracted, "campaign_state")
        assert synth.check_outline(text, synth.load_outline("campaign_state")) == []

    def test_code_owned_sections(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        text = draft_of(extracted, "campaign_state")
        completed = section(text, "## Completed Encounters & Quests")
        assert completed.splitlines() == [
            "- The escape from Velkynvelve ends at the foot of the stair. [ch 003 / 003.02]",
            "- The fight at the gate ends with Sarith's death and Kalan holding the gate. [ch 004 / 004.01]",
        ]
        table = section(text, "## NPC Current States")
        rows = {ln.split("|")[1].strip(): ln for ln in table.splitlines()[2:]}
        assert set(rows) == {"Ilvara Mizzrym", "Kalan", "Sarith Kzekarit"}  # Thorin is a player character
        assert "| Dead |" in rows["Ilvara Mizzrym"] and "| Dead |" in rows["Sarith Kzekarit"]
        assert "| Alive |" in rows["Kalan"] and "later, status not stated" in rows["Kalan"]
        assert section(text, "## Audit: Tracking Claims") == "Audit not run for this range."

    def test_the_status_report_is_written_beside_the_drafts(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        rep = (state_dir(extracted) / "drafts" / "npc_status_report.md").read_text()
        assert "Ilvara Mizzrym: Ilvara, Ilvara Mizzrym" in rep and "Player-character rows dropped (1)" in rep

    def test_the_thread_sections_get_the_ledger_and_the_last_chunk(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        by = {c["heading"]: c["user"] for c in fm.prose_calls}
        ledger = by["## Resolved Plot Threads"]
        assert "[OPENED] **The signet ring**" in ledger and "[RESOLVED] **The signet ring**" in ledger
        assert "CHAPTER 005" in by["## Active Quests & Open Threads"] and "CHAPTER 005" in by["## Party Current Situation"]
        assert "CHAPTER 005" not in ledger

    def test_the_audit_section_says_it_was_not_run(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        assert "Audit not run for this range." in draft_of(extracted, "campaign_state")


def _words(n: int, cite: str = "") -> str:
    return " ".join(["word"] * n) + (f" {cite}" if cite else "")


class TestWorldStateBudgetsAndReferences:
    """Spec 033 US2 (T025): budgets, the reading contract, reference files and the timeline file."""

    def _record(self, root):
        recs = [json.loads(p.read_text()) for p in (state_dir(root) / "runs").glob("*/record.json")]
        (rec,) = [r for r in recs if r.get("step") == "synth"]
        return rec

    def test_the_world_prompt_carries_the_budget_and_the_quotation_rule(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        by = {c["heading"]: c for c in fm.prose_calls}
        for heading, words in (("## Party", 700), ("## Factions and Powers", 450),
                               ("## Locations", 450), ("## Items and Artifacts", 450),
                               ("## Active Threats and Open Pressures", 600)):
            assert f"WORD BUDGET: {words} words, hard limit." in by[heading]["user"]
            assert "WORD BUDGET" in by[heading]["system"]
            assert "Quotation marks are reserved" in by[heading]["system"]
        # Key NPCs is budgeted per line: its 900 words are shared by the NPCs that have a dossier
        assert "At most 900 words per line" in by["## Key NPCs"]["user"]

    def test_campaign_state_has_no_budget(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        assert all("WORD BUDGET" not in c["user"] and "WORD BUDGET" not in c["system"] for c in fm.prose_calls)

    def test_budgets_come_from_config_then_from_the_schema(self, extracted, fm):
        (extracted / "config" / "grounding.yaml").write_text(
            "summary_native:\n  prose:\n    budgets:\n      Locations: 120\n")
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        by = {c["heading"]: c["user"] for c in fm.prose_calls}
        assert "WORD BUDGET: 120 words, hard limit." in by["## Locations"]
        assert "WORD BUDGET: 700 words, hard limit." in by["## Party"]  # the schema default
        assert self._record(extracted)["budgets"]["Locations"]["budget"] == 120

    def test_an_overrun_is_reported_and_the_text_is_not_truncated(self, extracted, fm):
        fm.prose_override["## Locations"] = "## Locations\n\n" + _words(600, "[ch 004 / 004.01]") + "\n"
        rc, out, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 0, err  # an overrun is a report for the GM, never a failure
        assert "Locations: 600/450 words" in out and "OVER" in out
        assert _words(600, "[ch 004 / 004.01]") in draft_of(extracted, "world_state")
        rec = self._record(extracted)
        assert rec["budgets"]["Locations"] == {"budget": 450, "words": 600, "over": True}
        assert rec["budgets"]["Party"]["over"] is False
        assert rec["check"] == {"complete": True, "problems": []}

    def test_citations_do_not_count_toward_the_budget(self, extracted, fm):
        fm.prose_override["## Locations"] = "## Locations\n\n" + (_words(10, "[ch 004 / 004.01]") + "\n") * 45
        rc, out, err = cs.run_cli(synth_args(extracted, "world_state"))
        assert rc == 0, err
        assert self._record(extracted)["budgets"]["Locations"] == {"budget": 450, "words": 450, "over": False}

    def test_the_budget_report_is_written_beside_the_drafts(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        rep = json.loads((state_dir(extracted) / "drafts" / "budget_report.json").read_text())
        assert set(rep) == {"Party", "Factions and Powers", "Key NPCs", "Locations", "Items and Artifacts",
                            "Active Threats and Open Pressures"}

    def test_the_reading_contract_is_the_first_block_after_the_header(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        lines = draft_of(extracted, "world_state").splitlines()
        assert lines[0].startswith("<!-- summary_native draft")
        assert lines[1].startswith("> **How to read this document.**")
        first_h2 = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
        assert lines[1].startswith(">") and all(ln.startswith(">") or not ln for ln in lines[1:first_h2])
        contract = "\n".join(lines[1:first_h2])
        assert "reference/factions.md" in contract and "canon_events_timeline.md" in contract
        assert "not verbatim" in contract

    def test_the_outline_check_runs_on_the_sections_and_the_contract_adds_nothing_else(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        text = draft_of(extracted, "world_state")
        assert synth.check_outline(text, synth.load_outline("world_state")) == []
        assert [ln for ln in text.splitlines() if ln.startswith("## ")] == synth.load_outline("world_state")

    def test_each_reference_section_points_to_its_file(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        text = draft_of(extracted, "world_state")
        for heading, kind in (("## Factions and Powers", "factions"), ("## Key NPCs", "npcs"),
                              ("## Locations", "locations"), ("## Items and Artifacts", "items"),
                              ("## Active Threats and Open Pressures", "threats")):
            assert f"_Full notes: reference/{kind}.md (" in section(text, heading)
        assert "_Full notes:" not in section(text, "## Party")

    def test_the_reference_files_and_timeline_are_written_by_code(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        drafts = state_dir(extracted) / "drafts"
        assert sorted(p.name for p in (drafts / "reference").iterdir()) == [
            "factions.md", "items.md", "locations.md", "npcs.md", "threads.md", "threats.md"]
        locations = (drafts / "reference" / "locations.md").read_text()
        assert "- [LOCATION] **Velkynvelve** — A drow outpost built into the cavern wall. [ch 002 / locations]" in locations
        assert "the web is a lie" not in "".join(p.read_text() for p in (drafts / "reference").iterdir())  # dropped notes stay out
        assert (drafts / schema.TIMELINE_FILE).read_text().startswith("# Canon Events Timeline\n")

    def test_the_files_are_identical_across_rebuilds(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        drafts = state_dir(extracted) / "drafts"
        snap = {p.name: p.read_bytes() for p in list(drafts.glob("reference/*.md")) + [drafts / schema.TIMELINE_FILE]}
        assert cs.run_cli(synth_args(extracted, "world_state", "--force"))[0] == 0
        assert snap == {p.name: p.read_bytes() for p in list(drafts.glob("reference/*.md")) + [drafts / schema.TIMELINE_FILE]}

    def test_campaign_states_two_thread_sections_point_to_the_ledger_file(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        text = draft_of(extracted, "campaign_state")
        for h in ("## Resolved Plot Threads", "## Active Quests & Open Threads"):
            assert "_Full notes: reference/threads.md (" in section(text, h)
        assert "_Full notes:" not in section(text, "## Party Current Situation")
        assert not text.splitlines()[1].startswith(">")  # the contract opens world_state only
        assert (state_dir(extracted) / "drafts" / "reference" / "threads.md").is_file()

    def test_dump_only_writes_no_reference_files(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state", "--dump-only"))[0] == 0
        assert not (state_dir(extracted) / "drafts").exists()


class TestDeterminism:
    def test_code_owned_sections_are_byte_identical_across_runs(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        first = draft_of(extracted, "campaign_state")
        assert cs.run_cli(synth_args(extracted, "campaign_state", "--force"))[0] == 0
        second = draft_of(extracted, "campaign_state")
        for h in ("## Completed Encounters & Quests", "## NPC Current States", "## Audit: Tracking Claims"):
            assert section(first, h) == section(second, h)
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        t1 = section(draft_of(extracted, "world_state"), "## Canon Events Timeline")
        assert cs.run_cli(synth_args(extracted, "world_state", "--force"))[0] == 0
        assert t1 == section(draft_of(extracted, "world_state"), "## Canon Events Timeline")

    def test_and_identical_when_rebuilt_from_cached_notes(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "campaign_state"))[0] == 0
        first = section(draft_of(extracted, "campaign_state"), "## NPC Current States")
        rc, out, _ = cs.run_cli(cs.extract_args(extracted))  # all cached
        assert rc == 0 and not fm.extract_calls
        assert cs.run_cli(synth_args(extracted, "campaign_state", "--force"))[0] == 0
        assert first == section(draft_of(extracted, "campaign_state"), "## NPC Current States")


# ── spec 033 US5: extraction and prose are chosen separately (T040) ─────────


class TestSeparateBackends:
    def _prose_clients(self, fm):
        return fm.client_args

    def test_with_no_flag_and_no_config_the_schema_defaults_apply(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert {(a["backend"], a["model"], a["effort"]) for a in fm.client_args[-1:]} == {
            (schema.DEFAULT_PROSE_BACKEND, schema.DEFAULT_PROSE_MODEL, schema.DEFAULT_PROSE_EFFORT)}

    def test_grounding_yaml_prose_beats_the_schema_and_a_flag_beats_both(self, extracted, fm):
        (extracted / "config" / "grounding.yaml").write_text(
            "summary_native:\n  prose:\n    backend: claude-code\n    model: yaml-model\n    effort: high\n")
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert (fm.client_args[-1]["backend"], fm.client_args[-1]["model"], fm.client_args[-1]["effort"]) == (
            "claude-code", "yaml-model", "high")
        assert cs.run_cli(synth_args(extracted, "campaign_state", "--model", "flag-model",
                                     "--claude-code-effort", "low"))[0] == 0
        assert (fm.client_args[-1]["model"], fm.client_args[-1]["effort"]) == ("flag-model", "low")

    def test_the_effort_flag_is_passed_through_to_the_backend_and_recorded(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state", "--claude-code-effort", "max"))[0] == 0
        assert fm.client_args[-1]["effort"] == "max"
        recs = [json.loads(p.read_text()) for p in (state_dir(extracted) / "runs").glob("*/record.json")]
        (rec,) = [r for r in recs if r.get("step") == "synth"]
        assert rec["effort"] == "max"

    def test_extraction_config_never_reaches_the_prose_step(self, extracted, fm):
        (extracted / "config" / "grounding.yaml").write_text(
            "summary_native:\n  extract:\n    backend: dgx\n    model: extract-model\n"
            "  prose:\n    backend: openrouter\n    model: vendor/prose\n")
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        assert (fm.client_args[-1]["backend"], fm.client_args[-1]["model"]) == ("openrouter", "vendor/prose")
        assert {c["model"] for c in fm.prose_calls} == {"vendor/prose"}

    def test_prose_config_never_reaches_extraction(self, scamp, fm):
        (scamp / "config" / "grounding.yaml").write_text(
            "summary_native:\n  extract:\n    backend: dgx\n    model: extract-model\n"
            "  prose:\n    backend: openrouter\n    model: vendor/prose\n")
        args = ["extract", *cs.common(scamp), "--chunk-chars", "1", "--endpoint", "http://spark:8001/v1"]
        assert cs.run_cli(args)[0] == 0
        assert {a["backend"] for a in fm.client_args} == {"dgx"}
        assert {c["model"] for c in fm.extract_calls} == {"extract-model"}

    def test_a_prose_only_rebuild_makes_no_extraction_call(self, extracted, fm):
        assert cs.run_cli(synth_args(extracted, "world_state"))[0] == 0
        fm.prose_calls.clear()
        fm.client_args.clear()
        fm.preflighted.clear()
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state", "--force", "--model", "another-model"))
        assert rc == 0, err
        assert fm.extract_calls == [] and fm.prose_calls
        assert fm.preflighted == [] and {a["backend"] for a in fm.client_args} == {"claude-code"}


# ── spec 034 US6 (T047/T048): one build surface for all four documents ──────

from tests import conftest_party as cp  # noqa: E402
from tests.test_summary_native_planning import DEFAULT as PLANNING_DEFAULT  # noqa: E402

#: One section per document that, left blank, makes that document's draft incomplete (exit 3).
BLANKABLE = {
    "world_state": "## Locations", "campaign_state": "## Resolved Plot Threads",
    "party": "## Party Overview", "planning": "## DM Notes",
}


class Models:
    """The fake model for a campaign that builds all four documents: it answers each call the way that
    document's own tests do, and can blank one section per document or fail every call."""

    def __init__(self, base) -> None:
        self.base = base
        self.blank = False  # the one BLANKABLE section of each document comes back empty
        self.fail: Exception | None = None

    def render(self, client, system, user, model, max_tokens):
        if self.fail is not None:
            raise self.fail
        doc = re.search(r"^DOCUMENT: (\w+)", user, re.M).group(1)
        heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
        if self.blank and heading == BLANKABLE[doc]:
            return ""
        if doc == "planning":
            self.base.prose_calls.append({"heading": heading, "system": system, "user": user, "model": model})
            return PLANNING_DEFAULT[heading](user)
        if doc == "party":
            return type(self.base).prose_render(self.base, client, system, user, model, max_tokens)
        return cs.FakeModels.prose_render(self.base, client, system, user, model, max_tokens)


@pytest.fixture
def four(tmp_path, monkeypatch):
    """The party/planning fixture campaign, extracted once, with a fake model that can build any document."""
    root = cp.party_campaign(tmp_path)
    base = cp.fake_party_models(monkeypatch)
    rc, out, err = cs.run_cli(cp.extract_args(root))
    assert rc == 0, out + err
    base.extract_calls.clear()
    base.preflighted.clear()
    models = Models(base)
    monkeypatch.setattr(cs.synth, "render_part", models.render)
    return root, base, models


def build(root, doc, *extra):
    flags = ["--fallback-npc-lines"] if doc in ("world_state", "planning") else []
    return ["synth", doc, *cp.common(root), *flags, *(["--recent-chapters", "2"] if doc == "planning" else []), *extra]


def state(root):
    return cp.range_dir(root) / "state"


def runs(root):
    return sorted(p for p in (state(root) / "runs").iterdir() if (p / "record.json").is_file()
                  and json.loads((p / "record.json").read_text()).get("step") == "synth")


class TestEveryDocumentBuildsTheSameWay:
    def test_all_four_documents_build_from_one_extraction_and_synth_extracts_nothing(self, four):
        root, base, _ = four
        for doc in schema.DOCS:
            rc, out, err = cs.run_cli(build(root, doc))
            assert rc == 0, f"{doc}: {err}"
            text = (state(root) / "drafts" / f"{doc}.draft.md").read_text()
            assert synth.check_outline(text, synth.load_outline(doc)) == [], doc
            assert not (state(root) / "drafts" / f"{doc}.incomplete.md").exists()
        # synth owns no extraction call and no endpoint check: the notes it read were extracted once, above
        assert base.extract_calls == [] and base.preflighted == []
        assert base.prose_calls and not (cp.range_dir(root) / "drafts").exists()

    def test_the_notes_are_untouched_by_building_all_four(self, four):
        root, _, _ = four
        notes_dir = state(root) / "notes"
        before = {p.name: p.read_bytes() for p in notes_dir.iterdir() if p.is_file()}
        assert before
        for doc in schema.DOCS:
            assert cs.run_cli(build(root, doc))[0] == 0
        assert before == {p.name: p.read_bytes() for p in notes_dir.iterdir() if p.is_file()}

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_never_writes_live_docs(self, four, doc):
        root, _, _ = four
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "docs").rglob("*")
                  if p.is_file() and "summary_native" not in p.parts}
        assert cs.run_cli(build(root, doc))[0] == 0
        assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "docs").rglob("*")
                          if p.is_file() and "summary_native" not in p.parts}

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_dump_only_creates_no_client_makes_no_call_and_writes_no_draft(self, four, monkeypatch, doc):
        root, base, _ = four

        def boom(*a, **k):
            raise AssertionError("a client was created")

        monkeypatch.setattr(cs.synth, "client_from_args", boom)
        rc, out, err = cs.run_cli(build(root, doc, "--dump-only"))
        assert rc == 0, err
        (run,) = runs(root)
        assert json.loads((run / "record.json").read_text())["check"] == "not run"
        assert (run / f"{doc}.system.md").is_file() and list(run.glob(f"{doc}.*.user.md"))
        assert not base.prose_calls and not (state(root) / "drafts").exists()

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_prompts_are_byte_identical_across_runs(self, four, doc):
        root, _, _ = four
        assert cs.run_cli(build(root, doc, "--dump-only"))[0] == 0
        assert cs.run_cli(build(root, doc, "--dump-only"))[0] == 0
        first, second = runs(root)
        assert first != second
        names = sorted(p.name for p in first.glob("*.md"))
        assert names and names == sorted(p.name for p in second.glob("*.md"))
        assert all((first / n).read_bytes() == (second / n).read_bytes() for n in names)

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_run_ids_are_utc_timestamps_and_a_clash_gets_a_suffix(self, four, monkeypatch, doc):
        root, _, _ = four
        monkeypatch.setattr(synth, "_utcnow", lambda: datetime(2026, 1, 1, 0, 0, 7, tzinfo=timezone.utc))
        assert cs.run_cli(build(root, doc, "--dump-only"))[0] == 0
        assert cs.run_cli(build(root, doc, "--dump-only"))[0] == 0
        assert [p.name for p in runs(root)] == ["20260101T000007Z", "20260101T000007Z-1"]

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_dump_only_run_leaves_the_earlier_run_and_the_draft_record_intact(self, four, monkeypatch, doc):
        root, _, _ = four
        ticks = iter(range(1, 60))
        monkeypatch.setattr(synth, "_utcnow", lambda: datetime(2026, 1, 1, 0, 0, next(ticks), tzinfo=timezone.utc))
        assert cs.run_cli(build(root, doc))[0] == 0
        (first,) = runs(root)
        before = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
        draft = state(root) / "drafts" / f"{doc}.draft.md"
        ref = re.search(r"record: (runs/\S+/record\.json)", draft.read_text().splitlines()[0]).group(1)
        assert cs.run_cli(build(root, doc, "--dump-only"))[0] == 0
        assert len(runs(root)) == 2
        assert {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()} == before
        assert (state(root) / ref).read_bytes() == (first / "record.json").read_bytes()

    def test_a_rebuild_that_reports_no_budgets_removes_that_documents_stale_report_only(self, four, monkeypatch):
        # party is the document with no code-built budgeted part: world_state and planning still measure
        # their code-built sections when the model returns nothing, so their report is never empty
        doc = "party"
        root, _, _ = four
        drafts = state(root) / "drafts"
        for d in ("world_state", "party", "planning"):
            assert cs.run_cli(build(root, d))[0] == 0
        files = {d: drafts / schema.budget_report_file(d) for d in ("world_state", "party", "planning")}
        assert all(f.is_file() for f in files.values())
        kept = {d: f.read_bytes() for d, f in files.items() if d != doc}
        # every section comes back empty, so nothing is measured against a budget on this run
        monkeypatch.setattr(cs.synth, "render_part", lambda *a, **k: "")
        cs.run_cli(build(root, doc, "--force"))
        assert not files[doc].exists()
        assert {d: f.read_bytes() for d, f in files.items() if d != doc} == kept

    def test_a_campaign_state_build_never_touches_world_states_budget_report(self, four):
        # campaign_state has no budgets, and budget_report_file used to answer "budget_report.json" for it too
        root, _, _ = four
        report = state(root) / "drafts" / schema.budget_report_file("world_state")
        assert cs.run_cli(build(root, "world_state"))[0] == 0
        kept = report.read_bytes()
        assert cs.run_cli(build(root, "campaign_state"))[0] == 0
        assert cs.run_cli(build(root, "campaign_state", "--force"))[0] == 0
        assert report.read_bytes() == kept
        assert "campaign_state" not in schema.BUDGET_DOCS
        with pytest.raises(ValueError, match="no word budgets"):
            schema.budget_report_file("campaign_state")

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_an_existing_draft_needs_force(self, four, doc):
        root, base, _ = four
        assert cs.run_cli(build(root, doc))[0] == 0
        n = len(base.prose_calls)
        rc, _, err = cs.run_cli(build(root, doc))
        assert rc == 2 and "--force" in err and len(base.prose_calls) == n
        assert cs.run_cli(build(root, doc, "--force"))[0] == 0 and len(base.prose_calls) > n

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_an_incomplete_build_exits_3_keeps_the_previous_draft_and_names_the_run_it_came_from(self, four, doc):
        root, base, models = four
        assert cs.run_cli(build(root, doc))[0] == 0
        draft = state(root) / "drafts" / f"{doc}.draft.md"
        kept = draft.read_bytes()
        (first,) = runs(root)
        models.blank = True
        rc, out, err = cs.run_cli(build(root, doc, "--force"))
        assert rc == 3, err
        assert draft.read_bytes() == kept
        incomplete = state(root) / "drafts" / f"{doc}.incomplete.md"
        second = [r for r in runs(root) if r != first][0]
        assert f"run: {second.name}" in incomplete.read_text().splitlines()[0]
        assert f"previous draft kept: state/drafts/{doc}.draft.md (from run {first.name})" in err
        assert json.loads((second / "record.json").read_text())["check"]["complete"] is False

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_an_existing_incomplete_file_never_blocks_a_rebuild_and_a_good_build_removes_it(self, four, doc):
        root, _, models = four
        models.blank = True
        assert cs.run_cli(build(root, doc))[0] == 3
        incomplete = state(root) / "drafts" / f"{doc}.incomplete.md"
        assert incomplete.is_file() and not (state(root) / "drafts" / f"{doc}.draft.md").exists()
        models.blank = False
        assert cs.run_cli(build(root, doc))[0] == 0  # no --force: only a draft needs it
        assert not incomplete.exists()

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_failed_client_setup_still_leaves_an_explained_record(self, four, monkeypatch, doc):
        root, _, _ = four

        def boom(*_a, **_k):
            raise SystemExit("no credentials for this backend")

        monkeypatch.setattr(cs.synth, "client_from_args", boom)
        rc, _, err = cs.run_cli(build(root, doc))
        assert rc == 2 and "no credentials for this backend" in err
        (run,) = runs(root)
        assert json.loads((run / "record.json").read_text())["check"] == {
            "complete": False, "error": "no credentials for this backend"}
        assert not (state(root) / "drafts" / f"{doc}.draft.md").exists()

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_failed_model_call_exits_4_and_still_leaves_a_record(self, four, doc):
        root, _, models = four
        models.fail = RuntimeError("upstream 529")
        rc, _, err = cs.run_cli(build(root, doc))
        assert rc == 4
        assert "Error: model call failed in " in err and "RuntimeError: upstream 529" in err
        assert "state/runs/" in err and "record.json" in err  # campaign-relative
        (run,) = runs(root)
        check = json.loads((run / "record.json").read_text())["check"]
        assert check["complete"] is False and "upstream 529" in check["error"]
        assert not (state(root) / "drafts" / f"{doc}.draft.md").exists()

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_the_record_names_the_effective_backend_and_the_settings(self, four, doc):
        root, _, _ = four
        assert cs.run_cli(build(root, doc, "--model", "m-test", "--max-tokens", "1234"))[0] == 0
        (run,) = runs(root)
        rec = json.loads((run / "record.json").read_text())
        assert (rec["doc"], rec["backend"], rec["model"], rec["max_tokens"]) == (doc, "claude-code", "m-test", 1234)
        assert rec["range"] == {"since": cp.SINCE, "until": cp.UNTIL} and rec["check"] == {"complete": True, "problems": []}
        assert "parts" not in rec and "outline" not in rec  # the one-shot record's fields

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_changed_registry_refuses_every_document_before_any_call(self, four, doc):
        root, base, _ = four
        reg = root / "docs" / "entity_registry.yaml"
        reg.write_text(reg.read_text() + "\n# edited after the build\n")
        rc, _, err = cs.run_cli(build(root, doc))
        assert rc == 2 and "entity registry changed since build" in err and "summary_native build --force" in err
        assert not base.prose_calls

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_canon_file_is_not_a_corpus_input(self, four, doc):
        root, _, _ = four
        canon = root / "docs" / "summary_native" / "canon.yaml"
        canon.write_text("not_duplicates: []\n")
        assert cs.run_cli(build(root, doc))[0] == 0

    @pytest.mark.parametrize("doc", schema.DOCS)
    def test_a_registry_named_in_grounding_yaml_is_fresh_after_a_rebuild_and_stale_on_change(self, four, doc):
        root, base, _ = four
        shutil.copy(root / "docs" / "entity_registry.yaml", root / "reg_cfg.yaml")
        (root / "config" / "grounding.yaml").write_text(yaml.safe_dump({"summary_native": {"registry": "reg_cfg.yaml"}}))
        assert cs.run_cli(["build", *cp.common(root), "--force"])[0] == 0
        assert cs.run_cli(cp.extract_args(root))[0] == 0
        assert cs.run_cli(build(root, doc))[0] == 0
        (root / "reg_cfg.yaml").write_text((root / "reg_cfg.yaml").read_text() + "\n# changed\n")
        base.prose_calls.clear()
        rc, _, err = cs.run_cli(build(root, doc, "--force"))
        assert rc == 2 and "entity registry changed since build" in err and not base.prose_calls


class TestPromotedBundlesAreCheckedAgainstTheirOwnContract:
    """``check-pointers`` requires only the files the document's reading contract names (spec 034 T048)."""

    @staticmethod
    def _promote(root, doc, name):
        """Copy a built draft and the files it points to to ``reviewed/<name>``, as a GM would after review."""
        target = root / "reviewed" / name
        shutil.copytree(state(root) / "drafts", target)
        return target, target / f"{doc}.draft.md"

    @pytest.mark.parametrize("doc,kinds,timeline", [
        ("party", ["party"], False), ("planning", ["factions", "npcs", "threads", "threads_unratified"], False),
        ("world_state", ["factions", "items", "locations", "npcs", "threads", "threats"], True),
    ])
    def test_the_contract_names_exactly_the_files_that_document_points_to(self, four, doc, kinds, timeline):
        from pipelines.summary_native.pointers import check_paths

        root, _, _ = four
        assert cs.run_cli(build(root, doc))[0] == 0
        target, document = self._promote(root, doc, doc)
        assert check_paths(document, root) == []
        assert cs.run_cli(["check-pointers", str(document), "--config", str(root / "config" / "config.yaml")])[0] == 0
        assert sorted(p.stem for p in (target / "reference").glob("*.md")) == kinds
        assert (target / schema.TIMELINE_FILE).is_file() is timeline

    def test_a_promoted_party_bundle_is_complete_with_its_one_reference_file_and_no_timeline(self, four):
        from pipelines.summary_native.pointers import check_paths

        root, _, _ = four
        assert cs.run_cli(build(root, "party"))[0] == 0
        target, document = self._promote(root, "party", "party")
        # nothing but the document and the one file its contract names
        for extra in [p for p in target.rglob("*") if p.is_file() and p not in (document, target / "reference" / "party.md")]:
            extra.unlink()
        assert check_paths(document, root) == []
        (target / "reference" / "party.md").unlink()
        problems = check_paths(document, root)
        assert len(problems) == 1 and "reference/party.md" in problems[0]
        rc, _, err = cs.run_cli(["check-pointers", str(document), "--config", str(root / "config" / "config.yaml")])
        assert rc == 2 and "reference/party.md" in err and "timeline" not in err

    def test_a_promoted_planning_bundle_is_complete_with_its_three_reference_files(self, four):
        from pipelines.summary_native.pointers import check_paths

        root, _, _ = four
        assert cs.run_cli(build(root, "planning"))[0] == 0
        target, document = self._promote(root, "planning", "planning")
        for extra in [p for p in target.rglob("*") if p.is_file()
                      and p != document and p.parent != target / "reference"]:
            extra.unlink()  # the reports and the budget file are not part of the contract
        assert check_paths(document, root) == []
        (target / "reference" / "npcs.md").unlink()
        problems = check_paths(document, root)
        assert len(problems) == 1 and "reference/npcs.md" in problems[0]

    def test_a_published_dossier_the_planning_document_points_to_is_still_required(self, four):
        from pipelines.summary_native.pointers import check_paths

        root, _, _ = four
        assert cs.run_cli(build(root, "planning"))[0] == 0
        _, document = self._promote(root, "planning", "planning")
        (root / "docs" / "npcs" / "ilvara-mizzrym.md").unlink()
        problems = check_paths(document, root)
        assert any("docs/npcs/ilvara-mizzrym.md" in p for p in problems)

    def test_a_document_whose_contract_lists_no_reference_files_is_refused(self, tmp_path):
        from pipelines.summary_native.pointers import check_paths

        doc = tmp_path / "x.md"
        doc.write_text('> <!-- summary_native pointers: {"reference": "reference", "summaries": "s", "timeline": "t.md"} -->\n')
        assert check_paths(doc, tmp_path) == [
            "the reading contract lists no reference files; regenerate the document with summary_native synth"]
