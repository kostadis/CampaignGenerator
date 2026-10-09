"""#530: campaign_state's thread sections read the GM's thread registry; a model no longer judges the ledger.

``## Resolved Plot Threads`` holds the ratified threads that are closed (the registry says resolved or abandoned, or
a thread with status ``open`` whose latest attached note is RESOLVED or ABANDONED). ``## Active Quests & Open
Threads`` holds the open ones, then the dormant block and the unratified pointer, exactly as planning's Active Plots
does. Code chooses the threads and their order; one call per section writes one entry per thread from that thread's
own notes, and an entry that breaks the structure is replaced by the thread's latest note, verbatim.

The fake model answers each call from its prompt, so no test reaches a backend. The fixture is the party/planning
campaign with a richer ledger (``RICH``): two threads open, three closed (one by status, two by their latest note),
one dormant by status whose latest note is RESOLVED, and one note no thread owns.
"""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from pipelines.summary_native import annotate, notes, schema, state_sections, synth, thread_attach
from tests import conftest_party as cp
from tests import conftest_state as cs
from tests.test_summary_native_planning import (
    BACKEND, CARVER, RING_OPEN, _names, drafts, registry, section, thread, write_registry,
)

HEADINGS = ("## Resolved Plot Threads", "## Active Quests & Open Threads")

#: Extra thread notes spliced after each chapter's existing ones. Every citation resolves in its own chapter.
EXTRA = {
    2: ("- [OPENED] **The signet ring** — Ilvara leaves a signet ring at the fire. [ch 002 / 002.02]\n", [
        "- [OPENED] **The Pale Court** — A pale envoy waits at the ridge. [ch 002 / 002.01]",
        "- [OPENED] **The Broken Seal** — Zalthir finds a cracked seal in the camp. [ch 002 / 002.02]",
    ]),
    3: ("- [ADVANCED] **Carver march** — Daz counts the banners from the ridge. [ch 003 / 003.01]\n", [
        "- [RESOLVED] **The Pale Court** — The envoy leaves without a word. [ch 003 / 003.01]",
        "- [RESOLVED] **The Broken Seal** — The seal is mended at the ridge. [ch 003 / 003.01]",
        "- [OPENED] **The Ashen Debt** — Zalthir owes a debt to the ashen smiths. [ch 003 / 003.02]",
        "- [OPENED] **The Whispering Well** — A well speaks at night. [ch 003 / 003.02]",
    ]),
    4: ("- [RESOLVED] **The signet ring** — Nobody could say what became of the ring. [ch 004 / 004.02]\n", [
        "- [OPENED] **The Gate Oath** — Daz swears to hold the gate. [ch 004 / 004.01]",
    ]),
}

#: Registry order matters: it breaks ties between equally recent threads.
RICH = registry(
    thread("carver-march", "The Carver's march", status="resolved", aliases=["Carver march"], resolved=4),  # closed by status
    thread("signet-ring", "The signet ring"),                                  # status open, latest RESOLVED: closed by its note
    thread("broken-seal", "The Broken Seal"),                                  # status open, latest RESOLVED: closed by its note
    thread("ashen-debt", "The Ashen Debt"),                                    # open, latest ch 3
    thread("gate-oath", "The Gate Oath"),                                      # open, latest ch 4
    thread("pale-court", "The Pale Court", status="dormant"),                  # dormant wins over a RESOLVED latest note
)  # "The Whispering Well" is in no thread: unratified


class CampaignModels:
    """Answers each campaign_state call from its prompt; records every call."""

    def __init__(self, base) -> None:
        self.base = base
        self.calls: list[dict] = []
        self.override: dict[str, object] = {}  # heading -> str | callable(user) -> str

    def render(self, client, system, user, model, max_tokens):
        heading = re.search(r"^SECTION: (## .+)$", user, re.M).group(1)
        self.calls.append({"heading": heading, "system": system, "user": user})
        self.base.prose_calls.append({"heading": heading, "system": system, "user": user, "model": model})
        out = self.override.get(heading)
        if callable(out):
            return out(user)
        if out is not None:
            return out
        if heading in HEADINGS:
            return "\n".join(f"### {n}\nProse for {n}. [ch 004 / 004.01]\n" for n in _names(user, "THREAD"))
        return f"{heading}\n\nWhere the party stands. [ch 004 / end]\n"

    def user_of(self, heading: str) -> str:
        return next(c["user"] for c in self.calls if c["heading"] == heading)

    def called(self, heading: str) -> bool:
        return any(c["heading"] == heading for c in self.calls)


def _rich_canned() -> dict[int, str]:
    out = dict(cp.CANNED_PARTY)
    for ch, (after, added) in EXTRA.items():
        assert after in out[ch]
        out[ch] = out[ch].replace(after, after + "\n".join(added) + "\n", 1)
    return out


@pytest.fixture
def ccamp(tmp_path, monkeypatch):
    for ch, text in _rich_canned().items():
        monkeypatch.setitem(cp.CANNED_PARTY, ch, text)
    root = cp.party_campaign(tmp_path)
    base = cp.fake_party_models(monkeypatch)
    rc, out, err = cs.run_cli(cp.extract_args(root))
    assert rc == 0, out + err
    write_registry(root, RICH)
    cm = CampaignModels(base)
    monkeypatch.setattr(cs.synth, "render_part", cm.render)
    return root, cm


def camp_args(root, *extra):
    return ["synth", "campaign_state", *cp.common(root), *BACKEND, *extra]


def build(root, *extra):
    return cs.run_cli(camp_args(root, *extra))


def draft(root) -> str:
    return (drafts(root) / "campaign_state.draft.md").read_text(encoding="utf-8")


def entries(text: str) -> list[str]:
    return re.findall(r"^### (.+)$", text, re.M)


def last_record(root) -> dict:
    run = sorted(p for p in (cp.range_dir(root) / "state" / "runs").iterdir()
                 if json.loads((p / "record.json").read_text()).get("step") == "synth")[-1]
    return json.loads((run / "record.json").read_text(encoding="utf-8"))


# ── Which threads, in which section, in what order ──────────────────────────


class TestMembershipAndOrder:
    def test_resolved_holds_the_closed_ratified_threads_newest_activity_first(self, ccamp):
        root, _ = ccamp
        rc, out, err = build(root)
        assert rc == 0, out + err
        # Carver (status resolved, latest ch 4) and the signet ring (latest note RESOLVED, ch 4) tie on the chapter:
        # the registry's order decides. The broken seal's latest note is ch 3.
        assert entries(section(draft(root), "## Resolved Plot Threads")) == [
            "The Carver's march", "The signet ring", "The Broken Seal"]

    def test_a_dormant_thread_is_in_neither_entry_list_whatever_its_latest_note_says(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        text = draft(root)
        assert "The Pale Court" not in section(text, "## Resolved Plot Threads")
        active = section(text, "## Active Quests & Open Threads")
        assert entries(active) == ["The Gate Oath", "The Ashen Debt", schema.DORMANT_HEADING[4:], schema.UNRATIFIED_HEADING[4:]]
        dormant = active.split(schema.DORMANT_HEADING + "\n", 1)[1].split("\n### ", 1)[0]
        assert dormant.strip() == "- **The Pale Court** — The envoy leaves without a word. [ch 003 / 003.01]"
        assert "Pale Court" not in cm.user_of("## Active Quests & Open Threads")
        assert "Pale Court" not in cm.user_of("## Resolved Plot Threads")

    def test_open_threads_are_ordered_by_their_latest_note_not_by_the_registry(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        # ashen-debt precedes gate-oath in the registry, but the oath has the newer note
        assert entries(section(draft(root), "## Active Quests & Open Threads"))[:2] == ["The Gate Oath", "The Ashen Debt"]

    def test_the_unratified_note_is_a_pointer_and_a_reference_file_never_a_model_input(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        active = section(draft(root), "## Active Quests & Open Threads")
        block = active.split(schema.UNRATIFIED_HEADING + "\n", 1)[1]
        assert block.startswith("_1 checked thread note is not in the thread registry.")
        assert "reference/threads_unratified.md" in block and "Whispering Well" not in block
        assert all("Whispering Well" not in c["user"] for c in cm.calls)
        ref = (drafts(root) / "reference" / "threads_unratified.md").read_text(encoding="utf-8")
        assert "- [OPENED] **The Whispering Well** — A well speaks at night. [ch 003 / 003.02]" in ref

    def test_the_draft_is_complete_in_outline_order_and_both_sections_point_to_the_ledger_file(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        text = draft(root)
        assert synth.check_outline(text, synth.load_outline("campaign_state")) == []
        for h in HEADINGS:
            assert "_Full notes: reference/threads.md (" in section(text, h)
        assert not (drafts(root) / "campaign_state.incomplete.md").exists()

    def test_a_thread_that_is_open_by_status_but_closed_by_its_note_is_resolved_not_active(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        assert "The signet ring" in section(draft(root), "## Resolved Plot Threads")
        assert "The signet ring" not in section(draft(root), "## Active Quests & Open Threads")


# ── The calls: one per section, one entry per thread, from that thread's notes ──


class TestTheCalls:
    def test_one_call_per_thread_section_then_party_current_situation(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        assert [c["heading"] for c in cm.calls] == [*HEADINGS, "## Party Current Situation"]
        assert last_record(root)["check"] == {"complete": True, "problems": []}

    def test_each_call_names_its_threads_in_code_order_and_gives_each_only_its_own_notes(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        resolved, active = cm.user_of(HEADINGS[0]), cm.user_of(HEADINGS[1])
        assert _names(resolved, "THREAD") == ["The Carver's march", "The signet ring", "The Broken Seal"]
        assert _names(active, "THREAD") == ["The Gate Oath", "The Ashen Debt"]
        assert re.findall(r"^\d+\. (.+)$", resolved, re.M) == ["The Carver's march", "The signet ring", "The Broken Seal"]
        # chapter order inside a thread, and nothing from another thread
        ring = resolved.split("=== THREAD: The signet ring")[1].split("=== THREAD:")[0]
        assert ring.index("Ilvara leaves a signet ring") < ring.index("Nobody could say what became")
        assert "Carver" not in ring and "Broken Seal" not in ring
        carver = resolved.split("=== THREAD: The Carver's march")[1].split("=== THREAD:")[0]
        assert "A horde is spoken of" in carver and "Daz counts the banners" in carver and "signet" not in carver
        assert "Gate Oath" in active and "Ashen Debt" in active and "Carver" not in active

    def test_the_resolved_call_says_why_each_thread_is_closed(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        resolved = cm.user_of(HEADINGS[0])
        assert "closed because the GM set it resolved" in resolved
        assert "closed because its latest note (ch 3) is RESOLVED" in resolved
        assert "closed because" not in cm.user_of(HEADINGS[1])

    def test_the_thread_prompts_have_their_own_system_prompt_no_budget_and_no_whole_ledger_or_chunk_evidence(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        for h in HEADINGS:
            call = next(c for c in cm.calls if c["heading"] == h)
            assert "DOCUMENT: campaign_state" in call["user"] and "SECTION: " + h in call["user"]
            assert "campaign_state document" in call["system"] and "WORD BUDGET" not in call["user"] + call["system"]
            assert "CHAPTER 00" not in call["user"] and "THREAD LEDGER" not in call["user"]
            assert "VERIFIED NOTES" not in call["user"]  # the old whole-ledger prompt shape
        # the plain routed section keeps the document's prose prompt and the last chunk's evidence
        party = next(c for c in cm.calls if c["heading"] == "## Party Current Situation")
        assert "CHAPTER 004" in party["user"] and "campaign_state document" not in party["system"]

    def test_the_prompts_and_the_per_call_system_prompt_are_recorded_beside_the_run(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        names = {p.name for p in run.iterdir()}
        for stem in ("resolved_plot_threads", "active_quests_open_threads"):
            assert {f"campaign_state.{stem}.user.md", f"campaign_state.{stem}.out.md", f"campaign_state.{stem}.system.md"} <= names

    def test_dump_only_makes_no_call_and_writes_the_thread_prompts(self, ccamp):
        root, cm = ccamp
        rc, out, err = build(root, "--dump-only")
        assert rc == 0, err
        assert cm.calls == []
        run = sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1]
        assert (run / "campaign_state.resolved_plot_threads.user.md").is_file()
        assert not (drafts(root) / "campaign_state.draft.md").exists()

    def test_a_thread_section_with_nothing_to_write_from_makes_no_call(self, ccamp):
        root, cm = ccamp
        write_registry(root, registry(CARVER))  # one open thread, nothing closed
        assert build(root)[0] == 0
        assert not cm.called(HEADINGS[0]) and cm.called(HEADINGS[1])
        assert section(draft(root), HEADINGS[0]).startswith(schema.NO_RESOLVED_THREADS)

    def test_a_model_failure_in_a_thread_call_is_exit_4_with_a_record(self, ccamp):
        root, cm = ccamp

        def boom(user):
            raise RuntimeError("upstream 529")

        cm.override[HEADINGS[0]] = boom
        rc, out, err = build(root)
        assert rc == 4 and "model call failed in section Resolved Plot Threads" in err
        assert not (drafts(root) / "campaign_state.draft.md").exists()


# ── The checker: a model entry that breaks the structure is replaced by the source ──


class TestTheChecker:
    def test_a_model_that_adds_drops_or_repeats_a_thread_is_replaced_by_the_latest_note_verbatim_and_reported(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[0]] = (
            "### The signet ring\nThe ring was lost. [ch 004 / 004.02]\n"
            "### An invented thread\nBoo.\n"
            "### The signet ring\nAgain.\n")
        assert build(root)[0] == 0
        resolved = section(draft(root), HEADINGS[0])
        assert "An invented thread" not in resolved and "Boo." not in resolved and "Again." not in resolved
        assert "### The signet ring\nThe ring was lost. [ch 004 / 004.02]" in resolved
        # the Carver's march entry (first in code order) was dropped by the model: the signet ring is then out of order
        latest = "- [ADVANCED] **The Carver's march** — The march breaks against the gate. [ch 004 / 004.01]"
        assert f"### The Carver's march\n{latest}" in resolved
        assert "### The Broken Seal\n- [RESOLVED] **The Broken Seal** — The seal is mended at the ridge. [ch 003 / 003.01]" in resolved
        rep = (drafts(root) / schema.CAMPAIGN_THREADS_REPORT_FILE).read_text(encoding="utf-8")
        replaced = rep.split("## Resolved Plot Threads entries replaced by code")[1].split("## Active Quests")[0]
        assert "The Carver's march" in replaced and "The Broken Seal" in replaced
        assert "discarded" in replaced and "An invented thread" in replaced
        rec = last_record(root)["threads"]["Resolved Plot Threads"]
        assert rec["replaced"] >= 2 and rec["resolved"] == ["The Carver's march", "The signet ring", "The Broken Seal"]

    def test_a_reordered_entry_is_replaced(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[1]] = ("### The Ashen Debt\nA debt. [ch 003 / 003.02]\n"
                                    "### The Gate Oath\nAn oath. [ch 004 / 004.01]\n")
        assert build(root)[0] == 0
        active = section(draft(root), HEADINGS[1])
        # two blocks swapped are both out of the order code gave: neither is trusted, each is its latest note
        assert "### The Ashen Debt\n- [OPENED] **The Ashen Debt**" in active
        assert "### The Gate Oath\n- [OPENED] **The Gate Oath**" in active
        assert "An oath." not in active and "A debt." not in active
        assert entries(active)[:2] == ["The Gate Oath", "The Ashen Debt"]  # and the order is code's

    def test_nothing_usable_from_the_model_leaves_every_entry_its_threads_latest_note(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[0]] = "I could not write that.\n"
        cm.override[HEADINGS[1]] = ""
        rc, out, err = build(root)
        assert rc == 0, err  # code's replacement completes the section
        for h, expect in ((HEADINGS[0], 3), (HEADINGS[1], 2)):
            body = section(draft(root), h)
            assert len(re.findall(r"^### (?!Dormant|Unratified)", body, re.M)) == expect
        assert "### The Gate Oath\n- [OPENED] **The Gate Oath** — Daz swears to hold the gate. [ch 004 / 004.01]" in draft(root)
        assert last_record(root)["threads"]["Active Quests & Open Threads"]["replaced"] == 2

    def test_the_code_built_parts_do_not_depend_on_the_model(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        first = draft(root)
        cm.override[HEADINGS[1]] = "nothing"
        assert build(root, "--force")[0] == 0
        second = draft(root)
        for block in (schema.DORMANT_HEADING, schema.UNRATIFIED_HEADING):
            assert first.split(block)[1].split("\n### ")[0] == second.split(block)[1].split("\n### ")[0]
        assert section(first, "## NPC Current States") == section(second, "## NPC Current States")


# ── Registry states: none, empty, nothing closed, invalid ───────────────────


class TestRegistryStates:
    def test_an_absent_registry_file_builds_pointer_only_and_makes_no_thread_call(self, ccamp):
        root, cm = ccamp
        (root / "docs" / "thread_registry.yaml").unlink()
        rc, out, err = build(root)
        assert rc == 0, err
        text = draft(root)
        assert section(text, HEADINGS[0]).startswith(schema.NO_RATIFIED_THREADS)
        active = section(text, HEADINGS[1])
        assert active.startswith(schema.NO_RATIFIED_THREADS) and "_12 checked thread notes are not in the thread registry." in active
        assert [c["heading"] for c in cm.calls] == ["## Party Current Situation"]

    def test_an_empty_registry_is_the_same_as_an_absent_one(self, ccamp):
        root, cm = ccamp
        write_registry(root, registry())
        assert build(root)[0] == 0
        assert section(draft(root), HEADINGS[0]).startswith(schema.NO_RATIFIED_THREADS)
        assert not cm.called(HEADINGS[0]) and not cm.called(HEADINGS[1])

    def test_no_open_and_no_closed_thread_each_say_so_without_claiming_none_exist(self, ccamp):
        root, cm = ccamp
        write_registry(root, registry(RING_OPEN, thread("pale-court", "The Pale Court", status="dormant")))
        assert build(root)[0] == 0
        text = draft(root)
        assert section(text, HEADINGS[0]).startswith("### The signet ring")  # latest note RESOLVED
        assert section(text, HEADINGS[1]).startswith(schema.NO_OPEN_THREADS)
        write_registry(root, registry(thread("gate-oath", "The Gate Oath")))
        assert build(root, "--force")[0] == 0
        assert section(draft(root), HEADINGS[0]).startswith(schema.NO_RESOLVED_THREADS)

    def test_a_registry_that_fails_its_check_refuses_before_any_call(self, ccamp):
        root, cm = ccamp
        write_registry(root, registry(thread("a", "Same"), thread("b", "Same")))
        rc, out, err = build(root)
        assert rc == 2 and "collides" in err and "thread_registry check" in err and cm.calls == []
        assert not (drafts(root) / "campaign_state.draft.md").exists()


# ── The run record and freshness ────────────────────────────────────────────


class TestRunRecord:
    def test_the_record_holds_the_thread_registry_digest(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        reg = root / "docs" / "thread_registry.yaml"
        assert last_record(root)["inputs"]["thread_registry_sha256"] == hashlib.sha256(reg.read_bytes()).hexdigest()

    def test_editing_the_registry_changes_the_recorded_digest_so_the_draft_is_stale(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        before = last_record(root)["inputs"]["thread_registry_sha256"]
        write_registry(root, registry(CARVER))
        assert build(root, "--force")[0] == 0
        after = last_record(root)["inputs"]["thread_registry_sha256"]
        assert after != before and after == hashlib.sha256((root / "docs" / "thread_registry.yaml").read_bytes()).hexdigest()

    def test_an_absent_registry_is_recorded_as_none(self, ccamp):
        root, _ = ccamp
        (root / "docs" / "thread_registry.yaml").unlink()
        assert build(root)[0] == 0
        assert last_record(root)["inputs"]["thread_registry_sha256"] is None

    def test_the_other_documents_records_are_unchanged(self, ccamp):
        root, _ = ccamp
        assert cs.run_cli(["synth", "party", *cp.common(root), *BACKEND])[0] == 0
        assert "thread_registry_sha256" not in last_record(root)["inputs"]

    def test_the_attach_map_and_campaign_threads_report_are_written_and_planning_reports_are_left_alone(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        att = json.loads((cp.range_dir(root) / "state" / "threads" / "attach.json").read_text())
        assert att["kind"] == "thread_attach" and att["counts"]["unattached"] == 1
        assert {"carver-march", "signet-ring", "broken-seal", "ashen-debt", "gate-oath", "pale-court"} == set(att["threads"])
        rep = (drafts(root) / schema.CAMPAIGN_THREADS_REPORT_FILE).read_text(encoding="utf-8")
        assert "# Threads report" in rep and "closed" in rep and "dormant" in rep
        assert not (drafts(root) / "threads_report.md").exists()  # planning's file


# ── Annotate still works on the thread sections ─────────────────────────────


class TestAnnotation:
    def test_a_thread_entry_with_a_bad_citation_is_unverified_and_its_text_is_kept(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[1]] = ("### The Gate Oath\nDaz swears. [ch 004 / 004.77]\n"
                                    "### The Ashen Debt\nA debt. [ch 003 / 003.02]\n")
        assert build(root)[0] == 0
        assert f"Daz swears. [ch 004 / 004.77]\n  - {schema.UNVERIFIED} citation [ch 004 / 004.77] does not resolve\n" in draft(root)
        assert "A debt. [ch 003 / 003.02]\n  -" not in draft(root)

    def test_the_dormant_and_unratified_blocks_carry_no_annotation(self, ccamp):
        root, cm = ccamp
        assert build(root)[0] == 0
        active = section(draft(root), HEADINGS[1])
        for block in (schema.DORMANT_HEADING, schema.UNRATIFIED_HEADING):
            tail = active.split(block)[1].split("\n### ")[0]
            assert not any(m in tail for m in (schema.LATER, schema.SINCE, schema.UNVERIFIED))

    def test_the_standalone_annotate_step_reads_the_thread_sections(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[0]] = "### The Carver's march\nIt ended. [ch 004 / 004.55]\n"
        assert build(root)[0] == 0
        text = draft(root)
        rc, o, e = cs.run_cli(["annotate", "campaign_state", *cp.common(root)])
        assert rc == 0, e
        assert draft(root) == text  # idempotent
        assert f"  - {schema.UNVERIFIED} citation [ch 004 / 004.55] does not resolve" in text

    def test_annotation_only_adds_lines(self, ccamp):
        root, cm = ccamp
        cm.override[HEADINGS[0]] = "### The Carver's march\nIt ended. [ch 004 / 004.55]\n"
        assert build(root)[0] == 0
        plain = [ln for ln in draft(root).split("\n") if not annotate.ANNOTATION_RE.match(ln)]
        raw = (sorted((cp.range_dir(root) / "state" / "runs").iterdir())[-1] / "campaign_state.resolved_plot_threads.out.md").read_text()
        want = iter(plain)
        assert all(ln in want for ln in raw.splitlines() if ln.strip())


# ── The audit step and the other sections are untouched ─────────────────────


class TestUntouched:
    def test_the_audit_section_and_the_code_owned_sections_are_as_before(self, ccamp):
        root, _ = ccamp
        assert build(root)[0] == 0
        text = draft(root)
        assert section(text, "## Audit: Tracking Claims").strip() == schema.AUDIT_NOT_RUN
        assert "## Completed Encounters & Quests" in text and "## NPC Current States" in text

    def test_the_old_whole_ledger_route_is_gone(self):
        assert [h for h, _, _ in state_sections.PROSE_SECTIONS["campaign_state"]] == ["## Party Current Situation"]
        assert "threads" not in {route for rows in state_sections.PROSE_SECTIONS.values() for _, route, _ in rows}


# ── state_sections unit tests ────────────────────────────────────────────────


def _attach(registry_doc):
    chunks = []
    for ch, text in _rich_canned().items():
        chapters = notes.load_chapters(cp.PARTY_FIXTURE / "docs" / "summaries", ch, ch)
        chunks.append(notes.check_chunk(text, chapters))
    return thread_attach.attach(chunks, registry_doc)


class TestResolvedThreadsMd:
    def test_entries_are_the_closed_threads_in_code_order_with_the_models_bodies(self):
        att = _attach(RICH)
        out = state_sections.resolved_threads_md(att, {t.id: f"Body {t.id}. [ch 004 / 004.01]" for t in att.closed_threads})
        assert entries(out.text) == ["The Carver's march", "The signet ring", "The Broken Seal"]
        assert out.replaced == 0 and out.from_model == 3 and "### The signet ring\nBody signet-ring." in out.text
        assert schema.DORMANT_HEADING not in out.text and schema.UNRATIFIED_HEADING not in out.text

    def test_a_missing_body_is_the_latest_attached_note_and_is_reported(self):
        att = _attach(RICH)
        out = state_sections.resolved_threads_md(att, {"signet-ring": "  "}, {"signet-ring": "empty body"})
        assert out.replaced == 3
        assert f"### The signet ring\n{att.threads['signet-ring'].latest.text}" in out.text
        assert any("The signet ring" in r and "empty body" in r for r in out.report)

    def test_no_closed_thread_is_one_code_line(self):
        assert state_sections.resolved_threads_md(_attach(registry()), {}).text == schema.NO_RATIFIED_THREADS
        att = _attach(registry(thread("gate-oath", "The Gate Oath")))
        assert state_sections.resolved_threads_md(att, {}).text == schema.NO_RESOLVED_THREADS

    def test_active_plots_md_is_what_active_quests_uses(self):
        att = _attach(RICH)
        out = state_sections.active_plots_md(att, {"gate-oath": "Oath. [ch 004 / 004.01]", "ashen-debt": "Debt. [ch 003 / 003.02]"})
        assert entries(out.text) == ["The Gate Oath", "The Ashen Debt", schema.DORMANT_HEADING[4:], schema.UNRATIFIED_HEADING[4:]]

    def test_closed_open_and_dormant_partition_the_attached_threads(self):
        att = _attach(RICH)
        ids = lambda ts: {t.id for t in ts}  # noqa: E731
        assert ids(att.closed_threads) | ids(att.open_threads) | ids(att.dormant_threads) == set(att.threads)
        assert not (ids(att.closed_threads) & ids(att.open_threads)) and not (ids(att.dormant_threads) & ids(att.closed_threads))
