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
    runs = camp / RD / "runs/world_state"
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
    assert first.startswith("<!-- summary_native draft | doc: world_state | range: ch002-005 | record: runs/world_state/record.json | corpus manifest sha256: ")
    assert "## " in draft and len(calls) == 1
    assert (camp / RD / "runs/world_state/part-1.out.md").is_file()


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
        assert (camp / RD / f"runs/world_state/part-{k + 1}.out.md").is_file()
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
    user = (camp / RD / "runs/campaign_state/part-1.user.md").read_text()
    assert "UNREVIEWED DRAFT TEXT" not in user and "UPSTREAM DRAFT" not in user
    reviewed = camp / "reviewed_ws.md"
    reviewed.write_text("REVIEWED WORLD\n")
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--force", "--world-state", "reviewed_ws.md"]) == 0
    user = (camp / RD / "runs/campaign_state/part-1.user.md").read_text()
    assert "UPSTREAM DRAFT (GM-reviewed): world_state" in user and "REVIEWED WORLD" in user
    assert "UNREVIEWED DRAFT TEXT" not in user
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--world-state", "nope.md"]) == 2


def test_audit_files_fenced_as_questions(camp, fake):
    (camp / "track.md").write_text("- Reach Candlekeep\n")
    assert main(["synth", "campaign_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 0
    runs = camp / RD / "runs/campaign_state"
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
    assert "Default tracked thing" in (camp / RD / "runs/campaign_state/part-1.user.md").read_text()


def test_audit_rejected_for_world_state(camp):
    (camp / "track.md").write_text("x\n")
    assert main(["synth", "world_state", *ARGS, "--dump-only", "--audit", "track.md"]) == 2


def test_other_docs_refused_until_later(camp):
    assert main(["synth", "party", *ARGS, "--dump-only"]) == 2


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


def test_existing_incomplete_also_needs_force(camp, fake):
    calls, state = fake
    state["texts"] = "## nothing\n"
    assert main(["synth", "world_state", *ARGS]) == 3
    n = len(calls)
    assert main(["synth", "world_state", *ARGS]) == 2 and len(calls) == n


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
    assert main(["synth", "world_state", *ARGS]) == 2
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
    rec = json.loads((camp / RD / "runs/world_state/record.json").read_text())
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
    runs = camp / RD / "runs/world_state"
    a = (runs / "part-1.user.md").read_bytes(), (runs / "part-1.system.md").read_bytes()
    assert main(["synth", "world_state", *ARGS, "--dump-only"]) == 0
    assert a == ((runs / "part-1.user.md").read_bytes(), (runs / "part-1.system.md").read_bytes())
