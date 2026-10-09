"""Key NPCs from the published dossiers (spec 033 US3, T029): selection, the view, the line checks,
the refusal and the code-built fallback. No model is reached: the two seams are faked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipelines.summary_native import key_npcs, notes, schema, select, synth
from tests import conftest_state as cs

pytestmark = pytest.mark.filterwarnings("ignore")

RNG = "ch002-005"
ILVARA_LINE = (
    "- **Ilvara Mizzrym** — A drow priestess who offered the party a bargain; struck down in a doorway "
    "[ch 002 / npcs] [ch 004 / 004.02]."
)


# ── helpers ─────────────────────────────────────────────────────────────────


def dossier(name, identity, state, *, verify="pass", rng=RNG, extra=""):
    head = (
        f"<!-- published by summary_native npc-publish | source: summary_native | npc: {name} | range: {rng} "
        f"| draft run: fixture | draft sha256: {'0' * 64} | authored sha256: none | verify: {verify} "
        f"| published sha256: {'1' * 64} -->\n"
    )
    return f"{head}# {name}\n\n## Identity\n\n{identity}\n\n{extra}## Last Observed State\n\n{state}\n"


def publish(root: Path, slug, text):
    (root / "docs" / "npcs" / f"{slug}.md").write_text(text)


def npc_dir(root: Path) -> Path:
    return root / schema.DEFAULT_NPC_ROOT / RNG


def verify_md(root: Path, stem, verdict, failures=()):
    d = npc_dir(root) / "draft"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.md").write_text("draft\n")
    body = "\n".join(f"- {code} (line {n}): text" for n, code in enumerate(failures, 3)) or "None."
    (d / f"{stem}.verify.md").write_text(f"# Verification: x\n\n**Verdict: {verdict}**\n\n## Totals\n\n## Failures\n\n{body}\n\n## Manual edits\n")


def synth_args(root, *extra):
    return ["synth", "world_state", *cs.common(root), *extra]


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


def draft(root):
    return (cs.range_dir(root) / schema.STATE_DIR / "drafts" / "world_state.draft.md").read_text()


def key_section(root):
    secs = notes.npc_check.parse_sections(draft(root))
    return notes.npc_check.section_text(secs, "## Key NPCs")


# ── selection ───────────────────────────────────────────────────────────────


def corpus_dossier(subject, last, n=3, category="npc"):
    return select.Dossier(f"npc_{subject.lower()}", subject, category, n, 1, last, Path("x"))


class TestSelection:
    SCOPES = {"Kalan": "persistent", "Ilvara Mizzrym": "persistent", "Thorin": "persistent", "Dela": "local"}

    def pool(self):
        return [corpus_dossier("Kalan", 4), corpus_dossier("Ilvara Mizzrym", 3), corpus_dossier("Thorin", 5, 40),
                corpus_dossier("Dela", 5), corpus_dossier("Unregistered", 5), corpus_dossier("Signet", 5, category="item")]

    def names(self, **kw):
        sel = key_npcs.select_key_npcs(self.pool(), self.SCOPES, {"Thorin"}, range_until=5, **kw)
        return [(d.subject, why) for d, why in sel]

    def test_031_rules_in_031_order_over_the_global_npcs(self):
        assert self.names(recent_chapters=4, recurring_min=10) == [("Kalan", "recent"), ("Ilvara Mizzrym", "recent")]

    def test_a_player_character_is_never_selected_even_when_named(self):
        assert "Thorin" not in dict(self.names(recent_chapters=4, recurring_min=1))
        with pytest.raises(select.SelectionError):
            self.names(recent_chapters=4, recurring_min=10, named=["Thorin"])

    def test_local_unregistered_and_non_npc_subjects_are_out(self):
        got = dict(self.names(recent_chapters=0, recurring_min=1))
        assert set(got) == {"Kalan", "Ilvara Mizzrym"}

    def test_recent_window_recurring_floor_and_named(self):
        assert self.names(recent_chapters=1, recurring_min=10) == []
        assert self.names(recent_chapters=1, recurring_min=3) == [("Ilvara Mizzrym", "recurring"), ("Kalan", "recurring")]  # by observations, then stem
        assert self.names(recent_chapters=1, recurring_min=10, named=["Ilvara Mizzrym"]) == [("Ilvara Mizzrym", "named")]


# ── the view ────────────────────────────────────────────────────────────────


class TestPublishedView:
    def test_returns_only_the_name_header_facts_and_the_two_sections(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text(dossier(
            "Kalan", "A drow who holds the gate. [ch 004 / entry]", "Holds the gate. [ch 004 / 004.01]",
            extra="## Notable Quotes\n\nQUOTE-SECTION-TEXT\n\n## Secrets\n\nSECRET-CANARY-033 hidden\n\n"))
        v = key_npcs.published_view(p)
        assert (v.name, v.slug, v.range, v.verify) == ("Kalan", "x", RNG, "pass")
        assert v.identity == "A drow who holds the gate. [ch 004 / npcs]"  # entry -> npcs
        assert v.state == "Holds the gate. [ch 004 / 004.01]"
        assert set(vars(v)) == {"name", "slug", "range", "verify", "identity", "state"}
        assert "QUOTE-SECTION-TEXT" not in repr(v) and "SECRET-CANARY-033" not in repr(v)

    def test_a_hand_built_or_unpublished_file_is_not_a_publication(self, tmp_path):
        p = tmp_path / "x.md"
        p.write_text("# Kalan\n\n## Identity\n\nx\n")
        with pytest.raises(key_npcs.NotPublished):
            key_npcs.published_view(p)
        p.write_text("<!-- published by summary_native npc-publish | source: hand-built | path: a | sha256: b "
                     "| verification: not applicable | published sha256: c -->\n## Identity\n\nx\n")
        with pytest.raises(key_npcs.NotPublished):
            key_npcs.published_view(p)

    def test_only_this_range_and_a_passing_verification_are_usable(self, scamp):
        publish(scamp, "kalan", dossier("Kalan", "i [ch 004 / entry]", "s [ch 004 / 004.01]"))
        publish(scamp, "sarith", dossier("Sarith Kzekarit", "i [ch 002 / entry]", "s [ch 002 / 002.01]", rng="ch002-070"))
        publish(scamp, "forced", dossier("Forced", "i [ch 002 / entry]", "s [ch 002 / 002.01]", verify="unverified(forced)"))
        usable, unusable = key_npcs.published_dossiers(scamp, RNG)
        assert set(usable) == {"ilvara mizzrym", "kalan"}
        assert unusable["sarith kzekarit"] == f"published for ch002-070, not {RNG}"
        assert unusable["forced"].startswith("failed verification")


# ── the line checks ─────────────────────────────────────────────────────────

VIEW = key_npcs.PublishedView(
    "Ilvara Mizzrym", "ilvara-mizzrym", RNG, "pass",
    "A drow priestess of House Mizzrym who offered the party a bargain. [ch 002 / npcs]",
    'Struck down in a doorway; she said "the web is a lie". [ch 004 / 004.02]')
HAY = 'she said "the web is a lie" and nothing else'


class TestLineChecks:
    def test_a_good_line_passes(self):
        assert key_npcs.verify_line(ILVARA_LINE, VIEW, HAY, 60) is None

    @pytest.mark.parametrize("line,why", [
        ("- **Ilvara** — x [ch 004 / 004.02]", "exact name"),
        ("- **Ilvara Mizzrym** — no citation here.", "uncited"),
        ("- **Ilvara Mizzrym** — x [ch 003 / 003.01]", "citation not in this NPC's dossier"),
        ("- **Ilvara Mizzrym** — x [ch 004 / npcs]", "citation not in this NPC's dossier"),
        ('- **Ilvara Mizzrym** — she said "the web is a truth" [ch 004 / 004.02]', "quotation not verbatim"),
        ("- **Ilvara Mizzrym** — " + "word " * 130 + "[ch 004 / 004.02]", "too long"),
    ])
    def test_failures(self, line, why):
        assert why in key_npcs.verify_line(line, VIEW, HAY, 60)

    def test_a_verbatim_quotation_from_the_dossier_or_the_summaries_passes(self):
        assert key_npcs.verify_line('- **Ilvara Mizzrym** — "the web is a lie" [ch 004 / 004.02]', VIEW, "", 60) is None

    def plan(self):
        return [key_npcs.KeyNpc("Ilvara Mizzrym", "npc_ilvara_mizzrym", "ilvara-mizzrym", "recent", 3, VIEW)]

    def test_each_line_ends_with_its_dossier_pointer(self):
        a = key_npcs.assemble(self.plan(), ILVARA_LINE, HAY, 60, [], {})
        assert a.lines == [ILVARA_LINE + " → docs/npcs/ilvara-mizzrym.md"] and a.from_model == 1 and a.report == []

    def test_a_failing_line_falls_back_to_the_dossiers_first_cited_sentence(self):
        a = key_npcs.assemble(self.plan(), "- **Ilvara Mizzrym** — nothing cited", HAY, 60, [], {})
        assert a.lines == ['- **Ilvara Mizzrym** — Struck down in a doorway; she said "the web is a lie". '
                           "[ch 004 / 004.02] → docs/npcs/ilvara-mizzrym.md"]
        assert a.substituted == 1 and "uncited" in a.report[0]

    def test_a_missing_line_falls_back_too(self):
        a = key_npcs.assemble(self.plan(), "", HAY, 60, [], {})
        assert a.substituted == 1 and "missing" in a.report[0]

    def test_an_uncited_state_sentence_is_led_by_the_cited_identity(self):
        v = key_npcs.PublishedView("Kalan", "kalan", RNG, "pass", "A drow. [ch 004 / npcs]", "Status not established in the summaries.")
        assert key_npcs.fallback_from_dossier(v) == "- **Kalan** — A drow. [ch 004 / npcs] Status not established in the summaries."

    def test_extra_repeated_and_reordered_lines_are_discarded(self):
        other = key_npcs.PublishedView("Kalan", "kalan", RNG, "pass", "A drow. [ch 004 / npcs]", "Holds the gate. [ch 004 / 004.01]")
        plan = [key_npcs.KeyNpc("Ilvara Mizzrym", "s", "ilvara-mizzrym", "recent", 3, VIEW),
                key_npcs.KeyNpc("Kalan", "k", "kalan", "recent", 4, other)]
        kal = "- **Kalan** — Holds the gate. [ch 004 / 004.01]"
        out = "\n".join([kal, "- **Dela** — an NPC nobody selected [ch 004 / 004.01]", ILVARA_LINE, ILVARA_LINE])
        a = key_npcs.assemble(plan, out, HAY, 60, [], {})
        assert [ln.split("**")[1] for ln in a.lines] == ["Ilvara Mizzrym", "Kalan"]  # selection order, one each
        assert any("discarded" in r and "Dela" in r for r in a.report)

    def test_the_prompt_carries_only_the_two_passages_in_selection_order(self):
        text = key_npcs.lines_prompt(self.plan(), 40)
        assert "### Ilvara Mizzrym (last seen ch 003)" in text and "At most 40 words per line" in text
        assert VIEW.identity in text and VIEW.state in text


# ── without a published dossier ─────────────────────────────────────────────


class TestMissing:
    def test_the_states_from_verifications_and_the_log(self, scamp):
        verify_md(scamp, "npc_sarith_kzekarit", "fail", ["not-found", "not-found", "citation-mismatch"])
        verify_md(scamp, "npc_kalan", "pass")
        log = {}
        kw = dict(npc_root=scamp / schema.DEFAULT_NPC_ROOT, rng=RNG, unusable={}, log=log)
        assert key_npcs.missing_dossier_state("Sarith Kzekarit", "npc_sarith_kzekarit", "sarith-kzekarit", **kw) == \
            "failed verification (not-found 2, citation-mismatch 1)"
        assert key_npcs.missing_dossier_state("Kalan", "npc_kalan", "kalan", **kw) == "drafted, not published"
        assert key_npcs.missing_dossier_state("Dela", "npc_dela", "dela", **kw) == "not drafted"
        (npc_dir(scamp) / "draft" / "npc_dela.md").write_text("draft\n")
        assert key_npcs.missing_dossier_state("Dela", "npc_dela", "dela", **kw) == "drafted, not verified"
        log["kalan"] = {"range": "ch002-070"}
        assert key_npcs.missing_dossier_state("Kalan", "npc_kalan", "kalan", **kw) == f"published for ch002-070, not {RNG}"

    def test_the_default_build_refuses_naming_each_npc_and_the_commands(self, extracted, fm):
        verify_md(extracted, "npc_sarith_kzekarit", "fail", ["not-found", "not-found"])
        verify_md(extracted, "npc_kalan", "pass")
        rc, _, err = cs.run_cli(synth_args(extracted))
        assert rc == 2
        assert "Kalan: drafted, not published" in err
        assert "Sarith Kzekarit: failed verification (not-found 2)" in err
        assert "Ilvara Mizzrym:" not in err  # published and verified
        for cmd in ("npc-draft", "npc-verify", "npc-compose", "npc-publish"):
            assert f"summary_native {cmd} --since 2 --until 5 --name" in err
        assert "--fallback-npc-lines" in err and schema.KEY_NPC_FALLBACK_MARK in err
        assert not fm.prose_calls
        assert not (cs.range_dir(extracted) / schema.STATE_DIR / "drafts" / "world_state.draft.md").exists()

    def test_the_refusal_comes_before_any_file_is_written_and_with_dump_only_too(self, extracted, fm):
        runs = cs.range_dir(extracted) / schema.STATE_DIR / "runs"
        before = sorted(runs.glob("*")) if runs.exists() else []
        assert cs.run_cli(synth_args(extracted, "--dump-only"))[0] == 2
        assert (sorted(runs.glob("*")) if runs.exists() else []) == before

    def test_a_published_dossier_makes_the_refusal_shorter(self, extracted):
        publish(extracted, "kalan", dossier("Kalan", "A drow. [ch 004 / entry]", "Holds the gate. [ch 004 / 004.01]"))
        _, _, err = cs.run_cli(synth_args(extracted))
        assert "Kalan:" not in err and "Sarith Kzekarit: not drafted" in err and "1 of 3" in err

    def test_the_latest_attempts_missing_list_is_left_for_the_state_route(self, extracted):
        """`GET /state` reads state/missing_dossiers.json: the refused attempt, then the fallback one."""
        import json

        path = cs.range_dir(extracted) / schema.STATE_DIR / schema.MISSING_DOSSIERS_FILE
        assert cs.run_cli(synth_args(extracted))[0] == 2
        got = json.loads(path.read_text())
        assert got["refused"] is True
        assert {n["name"]: n["state"] for n in got["npcs"]} == {"Kalan": "not drafted", "Sarith Kzekarit": "not drafted"}
        assert cs.run_cli(synth_args(extracted, "--fallback-npc-lines"))[0] == 0
        got = json.loads(path.read_text())
        assert got["refused"] is False and len(got["npcs"]) == 2

    def test_npc_root_is_followed_and_echoed_in_the_commands(self, extracted):
        custom = extracted / "elsewhere"
        d = custom / RNG / "draft"
        d.mkdir(parents=True)
        (d / "npc_kalan.md").write_text("draft\n")
        _, _, err = cs.run_cli(synth_args(extracted, "--npc-root", "elsewhere"))
        assert "Kalan: drafted, not verified" in err and "--npc-root elsewhere" in err

    def test_fallback_lines_are_built_by_code_from_checked_notes_alone(self, extracted, fm):
        rc, out, err = cs.run_cli(synth_args(extracted, "--fallback-npc-lines"))
        assert rc == 0, err
        lines = {ln.split("**")[1]: ln for ln in key_section(extracted).splitlines() if ln.startswith("- **")}
        assert list(lines) == ["Kalan", "Ilvara Mizzrym", "Sarith Kzekarit"]  # 031 order: last seen, then name
        mark = schema.KEY_NPC_FALLBACK_MARK
        assert lines["Kalan"] == ("- **Kalan** — Alive; the gate; Holds the gate [ch 004 / 004.01] "
                                  f"A drow who now holds the gate. [ch 004 / npcs] {mark}")
        assert lines["Sarith Kzekarit"].endswith(f"Dead; the foot of the stair [ch 004 / 004.01] {mark}")
        assert lines["Ilvara Mizzrym"].endswith("→ docs/npcs/ilvara-mizzrym.md")  # published: pointer, no mark
        # the model was asked about the one NPC that has a dossier, and only that one
        (call,) = [c for c in fm.prose_calls if c["heading"] == "## Key NPCs"]
        assert "### Ilvara Mizzrym" in call["user"] and "Kalan" not in call["user"] and "Sarith" not in call["user"]
        assert "Kalan: fallback line from checked notes (not drafted)" in out
        runs = cs.range_dir(extracted) / schema.STATE_DIR / "runs"
        record = json.loads(next(runs.glob("*/record.json")).read_text())
        assert record["key_npcs"]["fallback_requested"] is True and record["key_npcs"]["fallbacks"] == 2

    def test_fallback_citations_are_only_checked_note_citations(self, extracted):
        assert cs.run_cli(synth_args(extracted, "--fallback-npc-lines"))[0] == 0
        allowed = {b for _, r in [notes.load_checked(cs.range_dir(extracted))] for c in r for n in c.notes
                   for b, _, _ in notes.cites(n.text)}
        for ln in key_section(extracted).splitlines():
            if schema.KEY_NPC_FALLBACK_MARK in ln:
                assert {b for b, _, _ in notes.cites(ln)} <= allowed

    def test_an_npc_no_note_names_gets_an_honest_uncited_fallback(self):
        line = key_npcs.fallback_from_notes("Nobody", [], {})
        assert line == f"- **Nobody** — no checked note names this NPC. {schema.KEY_NPC_FALLBACK_MARK}"

    def test_a_later_unknown_row_never_replaces_the_known_status(self, extracted):
        _, results = notes.load_checked(cs.range_dir(extracted))
        assert "Alive; the gate; Holds the gate" in key_npcs.fallback_from_notes("Kalan", results, {})  # ch 005 says Unknown


# ── the whole build ─────────────────────────────────────────────────────────


class TestBuild:
    @pytest.fixture
    def all_published(self, extracted):
        publish(extracted, "kalan", dossier("Kalan", "A drow who holds the gate. [ch 004 / entry]", "Holds the gate. [ch 004 / 004.01]"))
        publish(extracted, "sarith-kzekarit", dossier("Sarith Kzekarit", "A guard. [ch 002 / entry]", "Died at the stair. [ch 004 / 004.01]"))
        return extracted

    def test_a_model_line_that_passes_the_checks_is_used_and_points_to_its_dossier(self, all_published, fm):
        fm.prose_override["## Key NPCs"] = "\n".join([
            "- **Kalan** — Holds the gate [ch 004 / 004.01]", ILVARA_LINE,
            "- **Sarith Kzekarit** — Died at the stair [ch 004 / 004.01]"])
        rc, out, err = cs.run_cli(synth_args(all_published))
        assert rc == 0, err
        lines = [ln for ln in key_section(all_published).splitlines() if ln.startswith("- **")]
        assert [ln.split("**")[1] for ln in lines] == ["Kalan", "Ilvara Mizzrym", "Sarith Kzekarit"]
        assert all(ln.endswith(f"→ docs/npcs/{s}.md") for ln, s in zip(lines, ("kalan", "ilvara-mizzrym", "sarith-kzekarit")))
        assert "0 replaced" in out and "Key NPCs: 3 NPCs (3 from the model" in out
        assert "reference/npcs.md" in key_section(all_published)
        assert "— docs/npcs/kalan.md" in (cs.range_dir(all_published) / schema.STATE_DIR / "drafts" / "key_npcs_report.md").read_text()

    def test_a_failing_line_is_replaced_and_the_substitution_is_reported(self, all_published, fm):
        fm.prose_override["## Key NPCs"] = "\n".join([
            "- **Kalan** — Holds the gate, and invents a second gate [ch 009 / 009.01]", ILVARA_LINE,
            "- **Sarith Kzekarit** — Died at the stair [ch 004 / 004.01]"])
        rc, out, _ = cs.run_cli(synth_args(all_published))
        assert rc == 0
        assert "- **Kalan** — Holds the gate. [ch 004 / 004.01] → docs/npcs/kalan.md" in key_section(all_published)
        assert "1 replaced by the dossier's own sentence" in out and "citation not in this NPC's dossier" in out

    def test_the_default_prompt_model_output_without_lines_falls_back_per_npc(self, all_published, fm):
        rc, _, _ = cs.run_cli(synth_args(all_published))  # the fake answers with a heading and a paragraph
        assert rc == 0
        assert "Holds the gate. [ch 004 / 004.01] → docs/npcs/kalan.md" in key_section(all_published)

    def test_the_run_record_lists_the_dossiers_used_with_their_digest(self, all_published):
        assert cs.run_cli(synth_args(all_published))[0] == 0
        rec = json.loads(next((cs.range_dir(all_published) / schema.STATE_DIR / "runs").glob("*/record.json")).read_text())
        sel = {s["name"]: s for s in rec["key_npcs"]["selected"]}
        assert sel["Kalan"]["dossier"] == "docs/npcs/kalan.md" and len(sel["Kalan"]["sha256"]) == 64
        assert rec["budgets"]["Key NPCs"]["budget"] == 900

    def test_a_forced_fallback_is_per_run_never_remembered(self, extracted):
        assert cs.run_cli(synth_args(extracted, "--fallback-npc-lines"))[0] == 0
        rc, _, err = cs.run_cli(synth_args(extracted, "--force"))
        assert rc == 2 and "not drafted" in err

    def test_published_later_the_next_build_uses_the_dossier(self, extracted):
        assert cs.run_cli(synth_args(extracted, "--fallback-npc-lines"))[0] == 0
        publish(extracted, "kalan", dossier("Kalan", "A drow. [ch 004 / entry]", "Holds the gate. [ch 004 / 004.01]"))
        assert cs.run_cli(synth_args(extracted, "--fallback-npc-lines", "--force"))[0] == 0
        sec = key_section(extracted)
        assert "Holds the gate. [ch 004 / 004.01] → docs/npcs/kalan.md" in sec
        assert sum(schema.KEY_NPC_FALLBACK_MARK in ln for ln in sec.splitlines()) == 1  # only Sarith remains


# ── the selection flags ─────────────────────────────────────────────────────


class TestFlags:
    def test_recent_and_recurring_narrow_the_key_npcs(self, extracted):
        rc, _, err = cs.run_cli(synth_args(extracted, "--recent-chapters", "1", "--recurring-min", "99"))
        assert rc == 0, err  # nobody selected: no refusal, no call
        assert key_npcs.NO_NPCS_SELECTED in key_section(extracted)

    def test_name_force_includes_a_global_npc_by_alias(self, extracted):
        rc, _, err = cs.run_cli(synth_args(extracted, "--recent-chapters", "1", "--recurring-min", "99", "--name", "Sarith"))
        assert rc == 2 and "Sarith Kzekarit: not drafted" in err and "1 of 1" in err

    def test_name_outside_the_global_npcs_is_refused(self, extracted):
        rc, _, err = cs.run_cli(synth_args(extracted, "--name", "Thorin Giantfriend"))
        assert rc == 2 and "Thorin" in err and "global NPCs" in err

    @pytest.mark.parametrize("flag,value", [("--name", "Kalan"), ("--recent-chapters", "2"), ("--recurring-min", "2")])
    def test_the_selection_flags_do_not_apply_to_campaign_state(self, extracted, flag, value):
        rc, _, err = cs.run_cli(["synth", "campaign_state", *cs.common(extracted), flag, value])
        assert rc == 2 and f"{flag} does not apply to campaign_state" in err

    def test_npc_root_applies_to_world_state_and_planning_only(self, extracted):
        rc, _, err = cs.run_cli(["synth", "campaign_state", *cs.common(extracted), "--npc-root", "x"])
        assert rc == 2 and "applies to world_state and planning only, not campaign_state" in err

    @pytest.mark.parametrize("doc", ["campaign_state", "party"])
    def test_fallback_npc_lines_applies_to_world_state_and_planning_only(self, extracted, doc):
        # spec 034 (contracts/cli.md): planning writes Key-NPC-style lines too, so the flag is no longer world_state's alone
        rc, _, err = cs.run_cli(["synth", doc, *cs.common(extracted), "--fallback-npc-lines"])
        assert rc == 2 and "applies to world_state and planning only" in err

    def test_party_refuses_the_npc_selection_flags_and_planning_keeps_them(self, extracted):
        assert synth.run_synth is not None
        rc, _, err = cs.run_cli(["synth", "party", *cs.common(extracted), "--name", "Kalan"])
        assert rc == 2 and "party selects no NPCs; these apply to planning and world_state" in err
        rc, _, err = cs.run_cli(["synth", "planning", *cs.common(extracted), "--fallback-npc-lines", "--dump-only"])
        assert "does not apply" not in err and "applies to" not in err
