"""synth: outline check, parts, dump-only, refusals, run records (T020)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from pipelines.summary_native import synth
from pipelines.summary_native.cli import main

FIX = Path(__file__).parent / "fixtures" / "summary_native"
RD = "docs/summary_native/ch002-005"


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
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    runs = latest_run(camp, "world_state")
    assert (runs / "part-1.system.md").is_file() and (runs / "part-1.user.md").is_file()
    assert (runs / "selection.json").is_file()
    rec = json.loads((runs / "record.json").read_text())
    assert rec["check"] == "not run"
    assert not calls and not (camp / RD / "drafts").exists()


test_dump_only_creates_no_client = test_dump_only_writes_prompts_no_call


def test_draft_written_when_outline_complete(camp, fake):
    calls, state = fake
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    draft = (camp / RD / "drafts/world_state.draft.md").read_text()
    first = draft.splitlines()[0]
    run = latest_run(camp, "world_state").name
    assert first.startswith(f"<!-- summary_native draft | doc: world_state | range: ch002-005 | record: runs/world_state/{run}/record.json | corpus manifest sha256: ")
    assert "## " in draft and len(calls) == 1
    assert (latest_run(camp, "world_state") / "part-1.out.md").is_file()


def test_incomplete_when_heading_missing_exit3(camp, fake, capsys):
    _, state = fake
    hs = headings("world_state")
    state["texts"] = full_text("world_state", skip=(hs[2],))
    assert main(["synth", "world_state", *ARGS]) == 3
    assert (camp / RD / "drafts/world_state.incomplete.md").is_file()
    assert not (camp / RD / "drafts/world_state.draft.md").exists()
    err = capsys.readouterr()
    assert hs[2] in err.out + err.err and "--parts" in err.out + err.err


def test_parts_one_call_per_part_joined_in_order(camp, fake):
    calls, state = fake
    hs = headings("world_state")
    groups = synth.split_parts(hs, 3)
    state["texts"] = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    assert main(["synth", "world_state", *ARGS, "--parts", "3"]) == 0
    assert len(calls) == 3
    for k, g in enumerate(groups):
        assert all(h in calls[k]["system"] for h in g)
        assert "write ONLY these headings" in calls[k]["system"]
        assert (latest_run(camp, "world_state") / f"part-{k + 1}.out.md").is_file()
    draft = (camp / RD / "drafts/world_state.draft.md").read_text()
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
    state["texts"] = full_text("campaign_state")
    drafts = camp / RD / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "world_state.draft.md").write_text("UNREVIEWED DRAFT TEXT\n")
    assert main(["synth", "campaign_state", *ARGS, "--dump-only"]) == 0
    user = (latest_run(camp, "campaign_state") / "part-1.user.md").read_text()
    assert "UNREVIEWED DRAFT TEXT" not in user and "UPSTREAM DRAFT" not in user
    reviewed = camp / "reviewed_ws.md"
    reviewed.write_text("REVIEWED WORLD\n")
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--force", "--world-state", "reviewed_ws.md"]) == 0
    user = (latest_run(camp, "campaign_state") / "part-1.user.md").read_text()
    assert "UPSTREAM DRAFT (GM-reviewed): world_state" in user and "REVIEWED WORLD" in user
    assert "UNREVIEWED DRAFT TEXT" not in user
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--world-state", "nope.md"]) == 2


def test_audit_files_fenced_as_questions(camp, fake):
    (camp / "track.md").write_text("- Reach Candlekeep\n")
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 0
    runs = latest_run(camp, "campaign_state")
    user = (runs / "part-1.user.md").read_text()
    system = (runs / "part-1.system.md").read_text()
    assert "AUDIT QUESTIONS — NOT EVIDENCE" in user and "Reach Candlekeep" in user and "track.md" in user
    assert "## Audit: Tracking Claims" in system and "NOT FOUND IN SUMMARIES" in system
    assert "SUPPORTED (ch N, scene X)" in system


def test_audit_default_from_grounding_yaml(camp):
    (camp / "track.md").write_text("- Default tracked thing\n")
    (camp / "config" / "grounding.yaml").write_text(
        yaml.safe_dump({"campaign_state": {"track_files": ["track.md"]}})
    )
    assert main(["synth", "campaign_state", *ARGS, "--dump-only"]) == 0
    assert "Default tracked thing" in (latest_run(camp, "campaign_state") / "part-1.user.md").read_text()


def test_audit_rejected_for_world_state(camp):
    (camp / "track.md").write_text("x\n")
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 2


def test_unknown_doc_rejected_by_parser(camp):
    with pytest.raises(SystemExit):
        main(["synth", "nonsense", *ARGS, "--dump-only"])


def test_never_writes_live_docs(camp, fake):
    _, state = fake
    state["texts"] = full_text("world_state")
    before = {p.name: p.read_bytes() for p in (camp / "docs").glob("*.md")}
    assert main(["synth", "world_state", *ARGS]) == 0
    assert {p.name: p.read_bytes() for p in (camp / "docs").glob("*.md")} == before


def test_existing_draft_needs_force(camp, fake):
    calls, state = fake
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    n = len(calls)
    assert main(["synth", "world_state", *ARGS]) == 2
    assert len(calls) == n
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS, "--force"]) == 0


def test_existing_incomplete_never_blocks(camp, fake):
    calls, state = fake
    state["texts"] = "## nothing\n"
    assert main(["synth", "world_state", *ARGS]) == 3
    n = len(calls)
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0 and len(calls) == n + 1
    assert not (camp / RD / "drafts/world_state.incomplete.md").exists()


def test_synth_refuses_stale_corpus(camp, fake, capsys):
    calls, _ = fake
    f = camp / "summaries" / "002-the-gate.md"
    f.write_text(f.read_text() + "\nAn edit after build.\n")
    assert main(["synth", "world_state", *ARGS]) == 2
    assert "summaries changed since build" in capsys.readouterr().err
    assert not calls


def test_synth_refuses_blocking_validation(camp, fake, capsys):
    f = camp / "summaries" / "002-the-gate.md"
    f.write_text(f.read_text().replace("# Chapter 2", "# Chapter 9"))
    assert main(["synth", "world_state", *ARGS]) == 1  # same as validate/build
    assert "blocking" in capsys.readouterr().out.lower()  # the report is printed
    assert not fake[0]


def test_synth_refuses_incomplete_manifest(camp, fake):
    mp = camp / RD / "manifest.json"
    m = json.loads(mp.read_text())
    m["complete"] = False
    mp.write_text(json.dumps(m))
    assert main(["synth", "world_state", *ARGS]) == 2
    assert not fake[0]


def test_synth_refuses_unbuilt_range(camp, fake):
    shutil.rmtree(camp / RD)
    assert main(["synth", "world_state", *ARGS]) == 2


def test_unmatched_name_exit_2(camp):
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--name", "Nobody Here"]) == 2


def test_record_json_fields(camp, fake):
    _, state = fake
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS, "--backend", "anthropic", "--model", "m-test", "--max-tokens", "1234"]) == 0
    rec = json.loads((latest_run(camp, "world_state") / "record.json").read_text())
    for k in ("doc", "backend", "model", "max_tokens", "parts", "range", "corpus_manifest_sha256",
              "upstream", "audit", "outline", "check", "started", "finished"):
        assert k in rec, k
    assert rec["doc"] == "world_state" and rec["model"] == "m-test" and rec["max_tokens"] == 1234
    assert rec["range"] == {"since": 2, "until": 5} and rec["parts"] == 1
    assert rec["check"] == {"complete": True, "problems": []}
    assert rec["outline"] == headings("world_state")
    import hashlib
    assert rec["corpus_manifest_sha256"] == hashlib.sha256((camp / RD / "manifest.json").read_bytes()).hexdigest()


def test_prompts_are_deterministic(camp):
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    r1 = latest_run(camp, "world_state")
    a = (r1 / "part-1.user.md").read_bytes(), (r1 / "part-1.system.md").read_bytes()
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    r2 = latest_run(camp, "world_state")
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
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    assert [d.name for d in run_dirs(camp, "world_state")] == ["20260101T000001Z"]


def test_run_id_collision_gets_suffix(camp, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(synth, "_utcnow", lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    assert [d.name for d in run_dirs(camp, "world_state")] == ["20260101T000000Z", "20260101T000000Z-1"]


def test_dump_only_leaves_earlier_run_and_draft_record_intact(camp, fake, clock):
    _, state = fake
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    runs = camp / RD / "runs/world_state"
    before = snapshot(runs)
    draft = camp / RD / "drafts/world_state.draft.md"
    ref = draft.read_text().splitlines()[0].split("record: ")[1].split(" |")[0]
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    after = snapshot(runs)
    assert all(after[k] == v for k, v in before.items())
    assert len(run_dirs(camp, "world_state")) == 2
    assert (camp / RD / ref).is_file() and (camp / RD / ref).read_bytes() == before[ref.split("/", 2)[2]]


def test_parts_run_then_single_part_run_keep_separate_dirs(camp, fake, clock):
    _, state = fake
    groups = synth.split_parts(headings("world_state"), 3)
    state["texts"] = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    assert main(["synth", "world_state", *ARGS, "--parts", "3"]) == 0
    first = run_dirs(camp, "world_state")[0]
    before = snapshot(first)
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS, "--parts", "1", "--force"]) == 0
    dirs = run_dirs(camp, "world_state")
    assert len(dirs) == 2 and snapshot(first) == before
    assert sorted(p.name for p in dirs[1].glob("part-*")) == ["part-1.out.md", "part-1.system.md", "part-1.user.md"]
    assert (first / "part-3.out.md").is_file()


def test_incomplete_keeps_previous_draft(camp, fake, clock, capsys):
    _, state = fake
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    draft = camp / RD / "drafts/world_state.draft.md"
    kept = draft.read_bytes()
    first_run = run_dirs(camp, "world_state")[0].name
    capsys.readouterr()
    state["texts"] = "## nothing\n"
    assert main(["synth", "world_state", *ARGS, "--force"]) == 3
    assert draft.read_bytes() == kept
    inc = camp / RD / "drafts/world_state.incomplete.md"
    second_run = run_dirs(camp, "world_state")[1].name
    assert f"run: {second_run}" in inc.read_text().splitlines()[0]
    err = capsys.readouterr()
    assert f"previous draft kept: drafts/world_state.draft.md (from run {first_run})" in err.out + err.err


def test_chatty_part_preamble_makes_run_incomplete(camp, fake, capsys):
    _, state = fake
    groups = synth.split_parts(headings("world_state"), 3)
    texts = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    texts[1] = "Here is part 2:\n" + texts[1]
    state["texts"] = texts
    assert main(["synth", "world_state", *ARGS, "--parts", "3"]) == 3
    e = capsys.readouterr()
    assert "part 2" in e.out + e.err
    assert not (camp / RD / "drafts/world_state.draft.md").exists()


def test_extra_h2_makes_run_incomplete(camp, fake, capsys):
    _, state = fake
    state["texts"] = full_text("world_state") + "\n## Notes\n\nextra\n"
    assert main(["synth", "world_state", *ARGS]) == 3
    e = capsys.readouterr()
    assert "unexpected heading: ## Notes" in e.out + e.err


def test_part_with_foreign_heading_incomplete(camp, fake):
    _, state = fake
    hs = headings("world_state")
    groups = synth.split_parts(hs, 3)
    # part 1 also writes a heading assigned to part 3
    texts = ["\n".join(f"{h}\n\nBody {h}\n" for h in g) for g in groups]
    texts[0] += f"\n{groups[2][0]}\n\nstolen\n"
    state["texts"] = texts
    assert main(["synth", "world_state", *ARGS, "--parts", "3"]) == 3


def test_check_outline_unexpected_heading():
    hs = ["## A"]
    assert any("unexpected" in p for p in synth.check_outline("## A\n\nx\n\n## Z\n\ny\n", hs))


def test_record_backend_is_effective_backend(camp, fake, monkeypatch):
    _, state = fake
    state["texts"] = full_text("world_state")
    monkeypatch.setenv("CG_BACKEND", "openrouter")
    assert main(["synth", "world_state", *ARGS]) == 0
    rec = json.loads((latest_run(camp, "world_state") / "record.json").read_text())
    assert rec["backend"] == "openrouter"


def test_failed_client_setup_still_writes_record(camp, monkeypatch):
    """A run that never reaches the model still leaves an explained run dir."""

    def boom(*_a, **_k):
        raise SystemExit("no credentials for this backend")

    monkeypatch.setattr(synth, "client_from_args", boom)
    assert main(["synth", "world_state", *ARGS]) == 2
    record = json.loads((latest_run(camp, "world_state") / "record.json").read_text())
    assert record["check"] == {"complete": False, "error": "no credentials for this backend"}


def test_failed_model_call_still_writes_record(camp, monkeypatch, fake, capsys):
    def explode(*_a, **_k):
        raise RuntimeError("upstream 529")

    monkeypatch.setattr(synth, "render_part", explode)
    assert main(["synth", "world_state", *ARGS]) == 4
    err = capsys.readouterr().err
    assert "Error: model call failed in part 1: RuntimeError: upstream 529" in err
    assert f"see {RD}/runs/world_state/" in err and "record.json" in err  # campaign-relative
    record = json.loads((latest_run(camp, "world_state") / "record.json").read_text())
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
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2  # no config/party.yaml
    (camp / "config" / "party.yaml").write_text("characters: not-a-list\n")
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    write_party(camp, missing_sheet=True)
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2
    assert "Nope.md" in capsys.readouterr().err
    assert not run_dirs(camp, "party")


def test_party_config_failure_prints_one_error_line(camp, capsys):
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
        ("campaign_state", "--world-state", True),
        ("campaign_state", "--campaign-state", False),
        ("party", "--world-state", True),
        ("party", "--campaign-state", True),
        ("planning", "--world-state", True),
        ("planning", "--campaign-state", True),
    ],
)
def test_upstream_flag_applicability(camp, capsys, doc, flag, ok):
    write_party(camp)
    write_planning(camp)
    src = "docs/world_state.md" if flag == "--world-state" else "docs/campaign_state.md"
    rc = main(["synth", doc, *ARGS, "--dump-only", "--force", flag, src])
    if ok:
        assert rc == 0
    else:
        assert rc == 2
        assert f"{flag} does not apply to {doc}" in capsys.readouterr().err


def test_registry_change_makes_corpus_stale(camp, fake, capsys):
    calls, _ = fake
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("entities: []\n")
    assert main(["synth", "world_state", *ARGS]) == 2
    err = capsys.readouterr().err
    assert "entity registry changed since build" in err and "summary_native build --force" in err
    assert not calls


def test_canon_change_does_not_make_corpus_stale(camp, fake):
    calls, state = fake
    state["texts"] = full_text("world_state")
    (camp / "docs" / "summary_native").mkdir(parents=True, exist_ok=True)
    (camp / "docs" / "summary_native" / "canon.yaml").write_text("not_duplicates: []\n")
    assert main(["synth", "world_state", *ARGS]) == 0


def test_configured_registry_not_stale_after_build_then_stale_on_change(camp, fake, capsys):
    calls, state = fake
    reg = camp / "docs" / "entity_registry.yaml"
    reg.write_text("entities: []\n")
    (camp / "reg_cfg.yaml").write_text("entities: []\n")
    (camp / "config" / "grounding.yaml").write_text(
        yaml.safe_dump({"summary_native": {"registry": "reg_cfg.yaml"}})
    )
    assert main(["build", *ARGS, "--force"]) == 0
    state["texts"] = full_text("world_state")
    assert main(["synth", "world_state", *ARGS]) == 0
    assert calls
    (camp / "reg_cfg.yaml").write_text("entities: []\n# changed\n")
    calls.clear()
    assert main(["synth", "world_state", *ARGS]) == 2
    assert "entity registry changed since build" in capsys.readouterr().err
    assert not calls
