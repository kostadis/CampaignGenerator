"""synth: outline check, parts, dump-only, refusals, run records (T020)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import synth
from pipelines.summary_native.cli import main
from pipelines.summary_native.schema import UPSTREAM_REFUSAL

FIX = Path(__file__).parent / "fixtures" / "summary_native"
RD = "docs/summary_native/ch002-005"

#: Spec 034 T012 routed party and planning through the chunked synth, so the one-shot harness these tests
#: drove (``camp`` + ``fake``: one model call per outline, ``runs/<doc>/part-N.*``, ``<range>/drafts/``) is
#: unreachable. Each is superseded by the party/planning tests of US1/US2 or deleted with the one-shot body
#: at T048; they stay visible here, skipped, so that work has the list of behaviours to re-cover.
RETIRED_ONE_SHOT = frozenset({
    "test_dump_only_writes_prompts_no_call", "test_dump_only_creates_no_client",
    "test_draft_written_when_outline_complete", "test_incomplete_when_heading_missing_exit3",
    "test_parts_one_call_per_part_joined_in_order", "test_world_state_input_only_from_explicit_flag",
    "test_never_writes_live_docs", "test_existing_draft_needs_force", "test_existing_incomplete_never_blocks",
    "test_record_json_fields", "test_prompts_are_deterministic", "test_run_ids_are_utc_timestamps",
    "test_run_id_collision_gets_suffix", "test_dump_only_leaves_earlier_run_and_draft_record_intact",
    "test_parts_run_then_single_part_run_keep_separate_dirs", "test_incomplete_keeps_previous_draft",
    "test_chatty_part_preamble_makes_run_incomplete", "test_extra_h2_makes_run_incomplete",
    "test_part_with_foreign_heading_incomplete", "test_record_backend_is_effective_backend",
    "test_failed_client_setup_still_writes_record", "test_failed_model_call_still_writes_record",
    "test_party_reads_party_config_and_sheets", "test_party_config_missing_or_invalid_exits_2",
    "test_party_config_failure_prints_one_error_line", "test_planning_no_arc_scores_prompt_states_empty",
    "test_planning_selection_is_npc_only_with_reasons", "test_planning_threat_tracker_score_line_fails",
    "test_planning_sentinel_only_threat_tracker_passes", "test_planning_with_arc_scores_needs_no_extra_check",
    "test_planning_without_any_config_means_no_arc_scores", "test_party_planning_require_explicit_upstream_flags",
    "test_planning_empty_threat_tracker_fails", "test_canon_change_does_not_make_corpus_stale",
    "test_configured_registry_not_stale_after_build_then_stale_on_change",
})


@pytest.fixture(autouse=True)
def _skip_retired_one_shot(request):
    if request.node.originalname in RETIRED_ONE_SHOT:
        pytest.skip("spec 034 T012: party/planning no longer use the one-shot path; superseded in US1/US2, deleted at T048")


@pytest.fixture
def camp(tmp_path, monkeypatch):
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    shutil.copytree(FIX / "clean", root / "summaries")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "world_state.md").write_text("LIVE WORLD\n")
    (root / "docs" / "campaign_state.md").write_text("LIVE CAMPAIGN\n")
    monkeypatch.chdir(root)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    # The generic synth machinery (flags, runs, records, refusals) is exercised through ``party``,
    # a one-shot document. world_state and campaign_state build from checked notes (spec 033).
    write_party(root, trackless=True)
    return root


ARGS = ["--summaries-dir", "summaries"]


def run_dirs(camp, doc):
    root = camp / RD / "runs" / doc
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []


def latest_run(camp, doc):
    return run_dirs(camp, doc)[-1]


def headings(doc):
    return synth.load_outline(doc)


def full_text(doc, skip=()):
    out = []
    for h in headings(doc):
        if h in skip:
            continue
        out.append(f"{h}\n\nBody for {h} (ch 2, 002.01).\n")
    return "\n".join(out)


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


def test_dump_only_writes_prompts_no_call(camp, monkeypatch, fake):
    calls, _ = fake

    def boom(*a, **k):
        raise AssertionError("client created")

    monkeypatch.setattr(synth, "client_from_args", boom)
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    runs = latest_run(camp, "party")
    assert (runs / "part-1.system.md").is_file() and (runs / "part-1.user.md").is_file()
    assert (runs / "selection.json").is_file()
    rec = json.loads((runs / "record.json").read_text())
    assert rec["check"] == "not run"
    assert not calls and not (camp / RD / "drafts").exists()


test_dump_only_creates_no_client = test_dump_only_writes_prompts_no_call


def test_draft_written_when_outline_complete(camp, fake):
    calls, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    draft = (camp / RD / "drafts/party.draft.md").read_text()
    first = draft.splitlines()[0]
    run = latest_run(camp, "party").name
    assert first.startswith(f"<!-- summary_native draft | doc: party | range: ch002-005 | record: runs/party/{run}/record.json | corpus manifest sha256: ")
    assert "## " in draft and len(calls) == 1
    assert (latest_run(camp, "party") / "part-1.out.md").is_file()


def test_incomplete_when_heading_missing_exit3(camp, fake, capsys):
    _, state = fake
    hs = headings("party")
    state["texts"] = full_text("party", skip=(hs[2],))
    assert main(["synth", "party", *ARGS]) == 3
    assert (camp / RD / "drafts/party.incomplete.md").is_file()
    assert not (camp / RD / "drafts/party.draft.md").exists()
    err = capsys.readouterr()
    assert hs[2] in err.out + err.err and "--parts" in err.out + err.err


def test_parts_one_call_per_part_joined_in_order(camp, fake):
    calls, state = fake
    hs = headings("party")
    groups = synth.split_parts(hs, 3)
    state["texts"] = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    assert main(["synth", "party", *ARGS, "--parts", "3"]) == 0
    assert len(calls) == 3
    for k, g in enumerate(groups):
        assert all(h in calls[k]["system"] for h in g)
        assert "write ONLY these headings" in calls[k]["system"]
        assert (latest_run(camp, "party") / f"part-{k + 1}.out.md").is_file()
    draft = (camp / RD / "drafts/party.draft.md").read_text()
    pos = [draft.index(h) for h in hs]
    assert pos == sorted(pos)


def test_split_parts_contiguous():
    assert synth.split_parts(list("abcde"), 2) == [list("abc"), list("de")]
    assert synth.split_parts(list("abc"), 3) == [["a"], ["b"], ["c"]]


def test_check_outline_problems():
    hs = ["## A", "## B"]
    assert synth.check_outline("## A\n\nx\n\n## B\n\ny\n", hs) == []
    assert synth.check_outline("<!-- c -->\n## A\n\nx\n\n## B\n\ny", hs) == []
    assert any("missing" in p for p in synth.check_outline("## A\n\nx\n", hs))
    assert any("order" in p for p in synth.check_outline("## B\n\ny\n\n## A\n\nx\n", hs))
    assert any("empty" in p for p in synth.check_outline("## A\n\n## B\n\ny\n", hs))
    assert synth.check_outline("Sure! here:\n## A\n\nx\n\n## B\n\ny", hs)


def test_world_state_input_only_from_explicit_flag(camp, fake):
    calls, state = fake
    state["texts"] = full_text("party")
    drafts = camp / RD / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "world_state.draft.md").write_text("UNREVIEWED DRAFT TEXT\n")
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    user = (latest_run(camp, "party") / "part-1.user.md").read_text()
    assert "UNREVIEWED DRAFT TEXT" not in user and "UPSTREAM DRAFT" not in user
    reviewed = camp / "reviewed_ws.md"
    reviewed.write_text("REVIEWED WORLD\n")
    assert main(["synth", "party", *ARGS, "--dump-only", "--force", "--world-state", "reviewed_ws.md"]) == 0
    user = (latest_run(camp, "party") / "part-1.user.md").read_text()
    assert "UPSTREAM DRAFT (GM-reviewed): world_state" in user and "REVIEWED WORLD" in user
    assert "UNREVIEWED DRAFT TEXT" not in user
    assert main(["synth", "party", *ARGS, "--dump-only", "--world-state", "nope.md"]) == 2


# The one-shot campaign_state audit tests (audit files fenced as questions, the grounding.yaml default)
# are gone with the one-shot path for these two documents (FR-029): the audit is its own step now, and
# its refusal and freshness are covered under "spec 033 US1" below.


def test_audit_rejected_for_world_state(camp):
    (camp / "track.md").write_text("x\n")
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 2


def test_unknown_doc_rejected_by_parser(camp):
    with pytest.raises(SystemExit):
        main(["synth", "nonsense", *ARGS, "--dump-only"])


def test_never_writes_live_docs(camp, fake):
    _, state = fake
    state["texts"] = full_text("party")
    before = {p.name: p.read_bytes() for p in (camp / "docs").glob("*.md")}
    assert main(["synth", "party", *ARGS]) == 0
    assert {p.name: p.read_bytes() for p in (camp / "docs").glob("*.md")} == before


def test_existing_draft_needs_force(camp, fake):
    calls, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    n = len(calls)
    assert main(["synth", "party", *ARGS]) == 2
    assert len(calls) == n
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS, "--force"]) == 0


def test_existing_incomplete_never_blocks(camp, fake):
    calls, state = fake
    state["texts"] = "## nothing\n"
    assert main(["synth", "party", *ARGS]) == 3
    n = len(calls)
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0 and len(calls) == n + 1
    assert not (camp / RD / "drafts/party.incomplete.md").exists()


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


def test_unmatched_name_exit_2(camp):
    assert main(["synth", "party", *ARGS, "--dump-only", "--name", "Nobody Here"]) == 2


def test_record_json_fields(camp, fake):
    _, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS, "--backend", "anthropic", "--model", "m-test", "--max-tokens", "1234"]) == 0
    rec = json.loads((latest_run(camp, "party") / "record.json").read_text())
    for k in ("doc", "backend", "model", "max_tokens", "parts", "range", "corpus_manifest_sha256",
              "upstream", "audit", "outline", "check", "started", "finished"):
        assert k in rec, k
    assert rec["doc"] == "party" and rec["model"] == "m-test" and rec["max_tokens"] == 1234
    assert rec["range"] == {"since": 2, "until": 5} and rec["parts"] == 1
    assert rec["check"] == {"complete": True, "problems": []}
    assert rec["outline"] == headings("party")
    import hashlib
    assert rec["corpus_manifest_sha256"] == hashlib.sha256((camp / RD / "manifest.json").read_bytes()).hexdigest()


def test_prompts_are_deterministic(camp):
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    r1 = latest_run(camp, "party")
    a = (r1 / "part-1.user.md").read_bytes(), (r1 / "part-1.system.md").read_bytes()
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    r2 = latest_run(camp, "party")
    assert r1 != r2
    assert a == ((r2 / "part-1.user.md").read_bytes(), (r2 / "part-1.system.md").read_bytes())


@pytest.fixture
def clock(monkeypatch):
    from datetime import datetime, timezone
    t = {"n": 0}

    def tick():
        t["n"] += 1
        return datetime(2026, 1, 1, 0, 0, t["n"], tzinfo=timezone.utc)

    monkeypatch.setattr(synth, "_utcnow", tick)
    return tick


def snapshot(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def test_run_ids_are_utc_timestamps(camp, fake, clock):
    _, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    assert [d.name for d in run_dirs(camp, "party")] == ["20260101T000001Z"]


def test_run_id_collision_gets_suffix(camp, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(synth, "_utcnow", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    assert [d.name for d in run_dirs(camp, "party")] == ["20260101T000000Z", "20260101T000000Z-1"]


def test_dump_only_leaves_earlier_run_and_draft_record_intact(camp, fake, clock):
    _, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    runs = camp / RD / "runs/party"
    before = snapshot(runs)
    draft = camp / RD / "drafts/party.draft.md"
    ref = draft.read_text().splitlines()[0].split("record: ")[1].split(" |")[0]
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    after = snapshot(runs)
    assert all(after[k] == v for k, v in before.items())
    assert len(run_dirs(camp, "party")) == 2
    assert (camp / RD / ref).is_file() and (camp / RD / ref).read_bytes() == before[ref.split("/", 2)[2]]


def test_parts_run_then_single_part_run_keep_separate_dirs(camp, fake, clock):
    _, state = fake
    groups = synth.split_parts(headings("party"), 3)
    state["texts"] = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    assert main(["synth", "party", *ARGS, "--parts", "3"]) == 0
    first = run_dirs(camp, "party")[0]
    before = snapshot(first)
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS, "--parts", "1", "--force"]) == 0
    dirs = run_dirs(camp, "party")
    assert len(dirs) == 2 and snapshot(first) == before
    assert sorted(p.name for p in dirs[1].glob("part-*")) == ["part-1.out.md", "part-1.system.md", "part-1.user.md"]
    assert (first / "part-3.out.md").is_file()


def test_incomplete_keeps_previous_draft(camp, fake, clock, capsys):
    _, state = fake
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    draft = camp / RD / "drafts/party.draft.md"
    kept = draft.read_bytes()
    first_run = run_dirs(camp, "party")[0].name
    capsys.readouterr()
    state["texts"] = "## nothing\n"
    assert main(["synth", "party", *ARGS, "--force"]) == 3
    assert draft.read_bytes() == kept
    inc = camp / RD / "drafts/party.incomplete.md"
    second_run = run_dirs(camp, "party")[1].name
    assert f"run: {second_run}" in inc.read_text().splitlines()[0]
    err = capsys.readouterr()
    assert f"previous draft kept: drafts/party.draft.md (from run {first_run})" in err.out + err.err


def test_chatty_part_preamble_makes_run_incomplete(camp, fake, capsys):
    _, state = fake
    groups = synth.split_parts(headings("party"), 3)
    texts = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    texts[1] = "Here is part 2:\n" + texts[1]
    state["texts"] = texts
    assert main(["synth", "party", *ARGS, "--parts", "3"]) == 3
    e = capsys.readouterr()
    assert "part 2" in e.out + e.err
    assert not (camp / RD / "drafts/party.draft.md").exists()


def test_extra_h2_makes_run_incomplete(camp, fake, capsys):
    _, state = fake
    state["texts"] = full_text("party") + "\n## Notes\n\nextra\n"
    assert main(["synth", "party", *ARGS]) == 3
    e = capsys.readouterr()
    assert "unexpected heading: ## Notes" in e.out + e.err


def test_part_with_foreign_heading_incomplete(camp, fake):
    _, state = fake
    hs = headings("party")
    groups = synth.split_parts(hs, 3)
    # part 1 also writes a heading assigned to part 3
    texts = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    texts[0] += f"\n{groups[2][0]}\n\nstolen\n"
    state["texts"] = texts
    assert main(["synth", "party", *ARGS, "--parts", "3"]) == 3


def test_check_outline_unexpected_heading():
    hs = ["## A"]
    assert any("unexpected" in p for p in synth.check_outline("## A\n\nx\n\n## Z\n\ny\n", hs))


def test_record_backend_is_effective_backend(camp, fake, monkeypatch):
    _, state = fake
    state["texts"] = full_text("party")
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    assert main(["synth", "party", *ARGS]) == 0
    rec = json.loads((latest_run(camp, "party") / "record.json").read_text())
    assert rec["backend"] == "openrouter"


def test_failed_client_setup_still_writes_record(camp, monkeypatch):
    """A run that never reaches the model still leaves an explained run dir."""

    def boom(*_a, **_k):
        raise SystemExit("no credentials for this backend")

    monkeypatch.setattr(synth, "client_from_args", boom)
    assert main(["synth", "party", *ARGS]) == 2
    record = json.loads((latest_run(camp, "party") / "record.json").read_text())
    assert record["check"] == {"complete": False, "error": "no credentials for this backend"}


def test_failed_model_call_still_writes_record(camp, monkeypatch, fake, capsys):
    def explode(*_a, **_k):
        raise RuntimeError("upstream 529")

    monkeypatch.setattr(synth, "render_part", explode)
    assert main(["synth", "party", *ARGS]) == 4
    err = capsys.readouterr().err
    assert "Error: model call failed in part 1: RuntimeError: upstream 529" in err
    assert f"see {RD}/runs/party/" in err and "record.json" in err  # campaign-relative
    record = json.loads((latest_run(camp, "party") / "record.json").read_text())
    assert record["check"]["complete"] is False
    assert "upstream 529" in record["check"]["error"]


# ── US4: party and planning (T039) ──────────────────────────────────────────

SENTINEL = "_No arc scores configured._"


def write_party(camp, *, trackless=False, missing_sheet=False):
    (camp / "docs").mkdir(exist_ok=True)
    (camp / "docs" / "Daz.md").write_text("SHEET-OF-DAZ level 5 fighter\n")
    (camp / "docs" / "daz_backstory.md").write_text("BACKSTORY-OF-DAZ was a sellsword\n")
    entry = {"name": "Daz", "sheet": "docs/Nope.md" if missing_sheet else "docs/Daz.md",
             "backstory": "docs/daz_backstory.md"}
    if trackless:
        entry["arc_score"] = None
    (camp / "config" / "party.yaml").write_text(yaml.safe_dump({"characters": [entry]}, sort_keys=False))


def write_planning(camp, *, with_score=False):
    entry = {"name": "Gith", "dossier": "docs/gith.md"}
    if with_score:
        (camp / "docs" / "gith_score.md").write_text("MECHANIC: +1 Rage when Gith is insulted\n")
        entry["arc_score"] = "docs/gith_score.md"
    (camp / "config" / "planning.yaml").write_text(
        yaml.safe_dump({"npcs": [entry], "factions": [{"name": "Gauntlet", "arc_score": None}]}, sort_keys=False)
    )


def test_party_reads_party_config_and_sheets(camp):
    write_party(camp, trackless=True)
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 0
    run = latest_run(camp, "party")
    user = (run / "part-1.user.md").read_text()
    system = (run / "part-1.system.md").read_text()
    assert "SHEET-OF-DAZ" in user and "BACKSTORY-OF-DAZ" in user
    assert "docs/Daz.md" in user and "docs/daz_backstory.md" in user
    assert "trackless" in user.lower()
    assert "## Party Overview" in system and "## Characters" in system
    # an explicit --party-config wins over the default
    (camp / "alt.yaml").write_text(yaml.safe_dump({"characters": [{"name": "Zed", "sheet": "docs/Daz.md"}]}))
    assert main(["synth", "party", *ARGS, "--dump-only", "--party-config", "alt.yaml"]) == 0
    assert "### Zed" in (latest_run(camp, "party") / "part-1.user.md").read_text()


def test_party_config_missing_or_invalid_exits_2(camp, capsys):
    (camp / "config" / "party.yaml").unlink()
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2  # no config/party.yaml
    (camp / "config" / "party.yaml").write_text("characters: not-a-list\n")
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    write_party(camp, missing_sheet=True)
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    assert "Nope.md" in capsys.readouterr().err
    assert not run_dirs(camp, "party")


def test_party_config_failure_prints_one_error_line(camp, capsys):
    (camp / "config" / "party.yaml").unlink()
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    lines = [l for l in capsys.readouterr().err.splitlines() if l.strip()]
    assert len(lines) == 1 and "--party-config" in lines[0]
    (camp / "config" / "party.yaml").write_text("characters: not-a-list\n")
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    lines = [l for l in capsys.readouterr().err.splitlines() if l.strip()]
    assert len(lines) == 1 and "--party-config" in lines[0]
    assert main(["synth", "planning", *ARGS, "--dump-only", "--planning-config", "nope.yaml"]) == 2
    lines = [l for l in capsys.readouterr().err.splitlines() if l.strip()]
    assert len(lines) == 1 and "--planning-config" in lines[0]


def test_planning_no_arc_scores_prompt_states_empty(camp):
    write_planning(camp)
    assert main(["synth", "planning", *ARGS, "--dump-only"]) == 0
    run = latest_run(camp, "planning")
    system = (run / "part-1.system.md").read_text()
    user = (run / "part-1.user.md").read_text()
    assert "## Threat Tracker" in system
    assert SENTINEL in system and SENTINEL in user
    assert "No arc scores are configured" in user
    assert "### Gith" in user and "### Gauntlet" in user
    sel = json.loads((run / "selection.json").read_text())
    assert all(i["subject"] for i in sel["selected"])


def test_planning_selection_is_npc_only_with_reasons(camp):
    write_planning(camp)
    assert main(["synth", "planning", *ARGS, "--dump-only", "--recent-chapters", "0"]) == 0
    sel = json.loads((latest_run(camp, "planning") / "selection.json").read_text())
    from pipelines.summary_native import select as sel_mod
    cats = {d.stem: d.category for d in sel_mod.read_corpus_dossiers(camp / RD)}
    assert sel["selected"] and all(cats[i["dossier"]] == "npc" for i in sel["selected"])
    assert all(i["reason"] for i in sel["selected"])


def test_planning_threat_tracker_score_line_fails(camp, fake, capsys):
    write_planning(camp)
    _, state = fake
    text = full_text("planning").replace(
        "## Threat Tracker\n\nBody for ## Threat Tracker (ch 2, 002.01).\n",
        "## Threat Tracker\n\n| Rage | Gith | 3 |\n",
    )
    state["texts"] = text
    assert main(["synth", "planning", *ARGS]) == 3
    err = capsys.readouterr()
    assert "threat tracker must be empty: no arc scores configured" in err.out + err.err
    assert (camp / RD / "drafts/planning.incomplete.md").is_file()
    assert not (camp / RD / "drafts/planning.draft.md").exists()
    rec = json.loads((latest_run(camp, "planning") / "record.json").read_text())
    assert rec["check"]["complete"] is False
    assert any("threat tracker must be empty" in p for p in rec["check"]["problems"])


def test_planning_sentinel_only_threat_tracker_passes(camp, fake):
    write_planning(camp)
    _, state = fake
    state["texts"] = full_text("planning").replace(
        "## Threat Tracker\n\nBody for ## Threat Tracker (ch 2, 002.01).\n",
        f"## Threat Tracker\n\n  {SENTINEL}  \n",
    )
    assert main(["synth", "planning", *ARGS]) == 0


def test_planning_with_arc_scores_needs_no_extra_check(camp, fake):
    write_planning(camp, with_score=True)
    _, state = fake
    state["texts"] = full_text("planning")
    assert main(["synth", "planning", *ARGS, "--dump-only"]) == 0
    user = (latest_run(camp, "planning") / "part-1.user.md").read_text()
    assert "MECHANIC: +1 Rage" in user and SENTINEL not in user
    assert main(["synth", "planning", *ARGS]) == 0


def test_planning_without_any_config_means_no_arc_scores(camp):
    assert main(["synth", "planning", *ARGS, "--dump-only"]) == 0
    assert SENTINEL in (latest_run(camp, "planning") / "part-1.user.md").read_text()


def test_planning_explicit_missing_config_exits_2(camp):
    assert main(["synth", "planning", *ARGS, "--dump-only", "--planning-config", "nope.yaml"]) == 2


def test_party_planning_require_explicit_upstream_flags(camp):
    write_party(camp)
    write_planning(camp)
    drafts = camp / RD / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "world_state.draft.md").write_text("UNREVIEWED WORLD\n")
    (drafts / "campaign_state.draft.md").write_text("UNREVIEWED CAMPAIGN\n")
    for doc in ("party", "planning"):
        assert main(["synth", doc, *ARGS, "--dump-only", "--force"]) == 0
        user = (latest_run(camp, doc) / "part-1.user.md").read_text()
        assert "UNREVIEWED" not in user and "UPSTREAM DRAFT" not in user
        assert main(["synth", doc, *ARGS, "--dump-only", "--force",
                     "--world-state", "docs/world_state.md", "--campaign-state", "docs/campaign_state.md"]) == 0
        user = (latest_run(camp, doc) / "part-1.user.md").read_text()
        assert "UPSTREAM DRAFT (GM-reviewed): world_state" in user and "LIVE WORLD" in user
        assert "UPSTREAM DRAFT (GM-reviewed): campaign_state" in user and "LIVE CAMPAIGN" in user


def test_party_flags_rejected_for_other_docs(camp):
    write_party(camp)
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--party-config", "config/party.yaml"]) == 2
    assert main(["synth", "party", *ARGS, "--dump-only", "--planning-config", "config/planning.yaml"]) == 2


def test_planning_empty_threat_tracker_fails(camp, fake):
    """An empty section is not the sentinel: it could be a dropped section."""
    write_planning(camp)
    _, state = fake
    state["texts"] = full_text("planning").replace(
        "## Threat Tracker\n\nBody for ## Threat Tracker (ch 2, 002.01).\n",
        "## Threat Tracker\n\n",
    )
    assert main(["synth", "planning", *ARGS]) == 3


# ── upstream flag applicability, registry staleness ─────────────────────────


@pytest.mark.parametrize(
    "doc,flag,ok",
    [
        ("world_state", "--world-state", False),
        ("world_state", "--campaign-state", False),
        ("campaign_state", "--world-state", False),  # one-shot upstream context: party and planning only
        ("campaign_state", "--campaign-state", False),
        # spec 034 T012: party and planning no longer take upstream drafts as prompt context either
        ("party", "--world-state", False),
        ("party", "--campaign-state", False),
        ("planning", "--world-state", False),
        ("planning", "--campaign-state", False),
    ],
)
def test_upstream_flag_applicability(camp, capsys, doc, flag, ok):
    write_party(camp)
    write_planning(camp)
    src = "docs/world_state.md" if flag == "--world-state" else "docs/campaign_state.md"
    rc = main(["synth", doc, *ARGS, "--dump-only", "--force", flag, src])
    assert rc == 2 and not ok
    err = capsys.readouterr().err
    if doc in ("party", "planning"):
        assert UPSTREAM_REFUSAL in err
    else:
        assert f"{flag} does not apply to {doc}" in err


def test_registry_change_makes_corpus_stale(camp, fake, capsys):
    calls, _ = fake
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("entities: []\n")
    assert main(["synth", "party", *ARGS]) == 2
    err = capsys.readouterr().err
    assert "entity registry changed since build" in err and "summary_native build --force" in err
    assert not calls


def test_canon_change_does_not_make_corpus_stale(camp, fake):
    calls, state = fake
    state["texts"] = full_text("party")
    (camp / "docs" / "summary_native").mkdir(parents=True, exist_ok=True)
    (camp / "docs" / "summary_native" / "canon.yaml").write_text("not_duplicates: []\n")
    assert main(["synth", "party", *ARGS]) == 0


def test_configured_registry_not_stale_after_build_then_stale_on_change(camp, fake, capsys):
    calls, state = fake
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("entities: []\n")
    (camp / "reg_cfg.yaml").write_text("entities: []\n")
    (camp / "config" / "grounding.yaml").write_text(
        yaml.safe_dump({"summary_native": {"registry": "reg_cfg.yaml"}})
    )
    assert main(["build", *ARGS, "--force"]) == 0
    state["texts"] = full_text("party")
    assert main(["synth", "party", *ARGS]) == 0
    assert calls
    (camp / "reg_cfg.yaml").write_text("entities: []\n# changed\n")
    calls.clear()
    assert main(["synth", "party", *ARGS]) == 2
    assert "entity registry changed since build" in capsys.readouterr().err
    assert not calls


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

    @pytest.mark.parametrize("doc", ["world_state", "campaign_state"])
    def test_parts_is_retired_for_these_two_documents(self, extracted, fm, doc):
        rc, _, err = cs.run_cli(synth_args(extracted, doc, "--parts", "2"))
        assert rc == 2 and "--parts" in err and "one call per section" in err
        assert not fm.prose_calls

    def test_audit_is_retired_for_campaign_state_naming_the_audit_step(self, extracted, fm):
        rc, _, err = cs.run_cli(synth_args(extracted, "campaign_state", "--audit", "docs/tracking/tracking.txt"))
        assert rc == 2 and "the audit is its own step: summary_native audit" in err

    def test_audit_is_still_refused_for_world_state(self, extracted, fm):
        rc, _, err = cs.run_cli(synth_args(extracted, "world_state", "--audit", "docs/tracking/tracking.txt"))
        assert rc == 2 and "campaign_state only" in err

    @pytest.mark.parametrize("flag", ["--world-state", "--campaign-state"])
    def test_one_shot_upstream_flags_do_not_apply_to_the_chunked_documents(self, extracted, flag):
        rc, _, err = cs.run_cli(synth_args(extracted, "campaign_state", flag, "docs/npcs/ilvara-mizzrym.md"))
        assert rc == 2 and f"{flag} does not apply" in err

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
    @pytest.mark.parametrize("flag", ["--world-state", "--campaign-state"])
    def test_party_and_planning_refuse_the_retired_upstream_flags(self, extracted, fm, doc, flag):
        rc, _, err = cs.run_cli(synth_args(extracted, doc, flag, "docs/npcs/ilvara-mizzrym.md"))
        assert rc == 2 and UPSTREAM_REFUSAL in err
        assert not fm.prose_calls

    @pytest.mark.parametrize("doc", ["party", "planning"])
    def test_parts_is_retired_for_party_and_planning_too(self, extracted, fm, doc):
        rc, _, err = cs.run_cli(synth_args(extracted, doc, "--parts", "2"))
        assert rc == 2 and "--parts" in err and "one call per section" in err

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
