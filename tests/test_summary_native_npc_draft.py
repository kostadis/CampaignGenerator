"""``summary_native npc-draft``: selection, prompts, drafts, records, composition (spec 032 T019)."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import npc_draft, npc_link, synth
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli, sha_tree

OUT = "docs/npcs/summary_native/ch002-006"
GLOBALS = ["npc_eldeth_feldrun", "npc_jimjar", "npc_sarith_kzekarit", "npc_sarith_vale", "npc_spider"]


def _args(root, cmd, *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"),
        "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


def body(skip=(), extra=""):
    out = []
    for h in synth.load_outline("npc_dossier"):
        if h in skip:
            continue
        out.append(f"{h}\n\n- Something happened. [ch 002 / 002.01]{extra}\n")
    return "\n".join(out)


@pytest.fixture
def linked(tmp_path):
    root = npc_campaign(tmp_path)
    rc, _, err = run_cli(_args(root, "npc-link"))
    assert rc == 0, err
    return root


@pytest.fixture
def fake(monkeypatch):
    calls = []
    state = {"text": body(), "fail_at": None}

    def render_part(client, system, user, model, max_tokens):
        calls.append({"system": system, "user": user, "model": model, "max_tokens": max_tokens})
        if state["fail_at"] is not None and len(calls) == state["fail_at"]:
            raise RuntimeError("boom")
        t = state["text"]
        return t(user) if callable(t) else t

    monkeypatch.setattr(npc_draft, "render_part", render_part)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    return calls, state


def draft(root, *extra):
    return run_cli(_args(root, "npc-draft", "--mode", "one-shot", *extra))


def out(root):
    return root / OUT


def latest_run(root):
    return sorted(p for p in (out(root) / "runs").iterdir())[-1]


def test_default_is_all_global_npcs_with_exclusions_recorded(linked, fake):
    calls, _ = fake
    rc, so, err = draft(linked)
    assert rc == 0, err
    assert len(calls) == 5
    assert sorted(p.stem for p in (out(linked) / "draft").glob("npc_*.md") if not p.name.endswith(".verify.md")) == GLOBALS
    sel = json.loads((latest_run(linked) / "selection.json").read_text())
    assert sel["mode"] == "all" and [i["stem"] for i in sel["included"]] == GLOBALS
    assert {i["reason"] for i in sel["included"]} == {"all"}
    reasons = {e["stem"]: e["reason"] for e in sel["excluded"]}
    assert reasons == {
        "npc_kaelis": "registry scope chapter-3: local (deferred to the local-NPC feature)",
        "npc_mantol": "not in registry",
        "npc_quaggoth": "not in registry",
        "npc_thorin": "player character (players.yaml)",
    }


def test_all_flag_equals_default(linked, fake):
    calls, _ = fake
    assert draft(linked, "--all")[0] == 0 and len(calls) == 5


def test_all_with_a_narrowing_flag_refuses(linked, fake):
    rc, _, err = draft(linked, "--all", "--name", "Jimjar")
    assert rc == 2 and "--all" in err


def test_named_takes_exactly_those(linked, fake):
    calls, _ = fake
    assert draft(linked, "--name", "Jimjar", "Eldeth Feldrun")[0] == 0
    assert len(calls) == 2
    sel = json.loads((latest_run(linked) / "selection.json").read_text())
    assert sel["mode"] == "narrowed" and {i["reason"] for i in sel["included"]} == {"named"}
    assert {"stem": "npc_spider", "reason": "narrowed out"} in sel["excluded"]


def test_recent_chapters_narrows_with_031_rules(linked, fake):
    calls, _ = fake
    assert draft(linked, "--recent-chapters", "1")[0] == 0     # last seen in chapter 6
    sel = json.loads((latest_run(linked) / "selection.json").read_text())
    assert [i["stem"] for i in sel["included"]] == ["npc_eldeth_feldrun", "npc_jimjar", "npc_sarith_kzekarit"]
    assert {i["reason"] for i in sel["included"]} == {"recent"}
    assert {"stem": "npc_spider", "reason": "narrowed out"} in sel["excluded"]


def test_recurring_min_narrows(linked, fake):
    assert draft(linked, "--recurring-min", "3", "--recent-chapters", "1")[0] == 0
    sel = json.loads((latest_run(linked) / "selection.json").read_text())
    assert {i["reason"] for i in sel["included"]} <= {"recent", "recurring"}


def test_name_accepts_an_exact_registry_alias(linked, fake):
    calls, _ = fake
    assert draft(linked, "--name", "Eldeth")[0] == 0 and len(calls) == 1      # alias of Eldeth Feldrun
    sel = json.loads((latest_run(linked) / "selection.json").read_text())
    assert [i["subject"] for i in sel["included"]] == ["Eldeth Feldrun"]
    assert draft(linked, "--name", "Eldet")[0] == 2                           # nothing fuzzy


@pytest.mark.parametrize("name,reason", [
    ("Quaggoth", "not in registry"),
    ("Kaelis", "registry scope chapter-3: local (deferred to the local-NPC feature)"),
    ("Thorin", "player character (players.yaml)"),
    ("Nobody At All", "not in registry"),
])
def test_ineligible_name_refuses_with_the_reason(linked, fake, name, reason):
    rc, _, err = draft(linked, "--name", name)
    assert rc == 2 and reason in err
    assert not (out(linked) / "runs").exists()


def test_empty_selection_refuses_with_counts(linked, fake):
    (linked / "config/players.yaml").write_text(
        "players:\n- id: a\n  name: A\n  plays: [Jimjar, Eldeth, Sarith Kzekarit, Sarith Vale, Spider, Thorin Giantfriend]\n")
    assert run_cli(_args(linked, "npc-link", "--force"))[0] == 0
    rc, _, err = draft(linked)
    assert rc == 2 and "empty" in err and "player character (players.yaml)" in err


def test_select_global_registry_npc_with_no_evidence_is_excluded():
    ev = [_ev("npc_a", "A", True, None)]
    sel = npc_draft.select_global(ev, range_until=6, range_text="2-6", registry_npcs=("A", "Ghost"))
    assert {"name": "Ghost", "reason": "no evidence in range"} in sel.excluded
    with pytest.raises(npc_draft.DraftRefusal) as e:
        npc_draft.select_global(ev, ["Ghost"], range_until=6, range_text="2-6", registry_npcs=("A", "Ghost"))
    assert "no evidence in range" in str(e.value)


def _ev(stem, subject, glob, excl, last=6):
    from pathlib import Path
    return npc_link.EvidenceFile(stem, subject, glob, excl, 1, 1, 1, 2, last, (2, last), Path(stem), "x", "---\n---\n", "")


def test_missing_registry_refuses_naming_the_commands(linked, fake):
    (linked / "docs/entity_registry.yaml").unlink()
    rc, _, err = draft(linked)
    assert rc == 2 and "registry init" in err and "registry import-inventory" in err


def test_stale_link_output_refuses(linked, fake):
    (linked / "docs/summary_native/canon.yaml").write_text("link_rulings:\n  - {form: Spider, ruling: safe}\n")
    rc, _, err = draft(linked)
    assert rc == 2 and "npc-link --force" in err


def test_changed_players_yaml_makes_link_output_stale(linked, fake):
    (linked / "config/players.yaml").write_text("players: []\n")
    rc, _, err = draft(linked)
    assert rc == 2 and "npc-link --force" in err


def test_missing_link_output_refuses(tmp_path, fake):
    root = npc_campaign(tmp_path)
    rc, _, err = draft(root)
    assert rc == 2 and "npc-link" in err


def test_changed_summaries_refuse(linked, fake):
    p = linked / "docs/summaries/006-the-surface.md"
    p.write_text(p.read_text().replace("Jimjar kept", "Jimjar keeps"))
    rc, _, err = draft(linked)
    assert rc == 2 and "build --force" in err


def test_user_prompt_holds_evidence_and_numbered_manual_edits(linked, fake):
    calls, _ = fake
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text(
        "subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\n  - He bets Eldeth.\nsecrets: |\n  hidden\n")
    assert draft(linked, "--name", "Jimjar", "Spider")[0] == 0
    ev = (out(linked) / "evidence/npc_jimjar.md").read_text()
    head, evbody = npc_link.split_frontmatter(ev)
    jim = next(c for c in calls if "Jimjar" in c["user"].split("GM MANUAL EDITS")[0][:400] or "[manual 1]" in c["user"])
    assert evbody in jim["user"] and head in jim["user"]
    assert "[manual 1] Jimjar is a deep gnome.\n[manual 2] He bets Eldeth." in jim["user"]
    spider = next(c for c in calls if c is not jim)
    assert "GM MANUAL EDITS:\n\n(none)" in spider["user"]
    assert "hidden" not in jim["user"] + jim["system"]


def test_authored_file_is_found_through_the_slug(linked, fake):
    calls, _ = fake
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "eldeth-feldrun.authored.yaml").write_text("subject: Eldeth Feldrun\nmanual: ['A dwarf, not a drow.']\n")
    assert draft(linked, "--name", "Eldeth Feldrun")[0] == 0
    assert "[manual 1] A dwarf, not a drow." in calls[0]["user"]


def test_mismatched_authored_subject_refuses(linked, fake):
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Somebody Else\nmanual: [x]\n")
    rc, _, err = draft(linked, "--name", "Jimjar")
    assert rc == 2 and "does not match" in err


def test_two_selected_npcs_sharing_a_slug_refuse_for_both():
    with pytest.raises(npc_draft.DraftRefusal) as e:
        npc_draft._check_slugs([{"subject": "Sarith Vale"}, {"subject": "Sarith-Vale"}])
    assert "Sarith Vale" in str(e.value) and "Sarith-Vale" in str(e.value)


def test_draft_file_has_provenance_computed_header_and_body(linked, fake):
    assert draft(linked, "--name", "Jimjar")[0] == 0
    text = (out(linked) / "draft/npc_jimjar.md").read_text()
    first, rest = text.split("\n", 1)
    run = latest_run(linked).name
    assert first.startswith(f"<!-- summary_native npc draft | npc: Jimjar | range: ch002-006 | run: {run} | draft_key: ")
    head, _ = npc_link.split_frontmatter((out(linked) / "evidence/npc_jimjar.md").read_text())
    assert rest.startswith(head)                       # the computed header, inserted by code
    assert rest[len(head):].lstrip("\n").startswith("## Identity")
    idx = json.loads((out(linked) / "draft/index.json").read_text())
    assert idx["npc_jimjar"]["run_id"] == run and len(idx["npc_jimjar"]["draft_key"]) == 64


def test_a_model_written_header_is_stripped_and_reported(linked, fake):
    _, state = fake
    state["text"] = "---\nsubject: WRONG\n---\n\n# Jimjar\n\n" + body()
    rc, _, err = draft(linked, "--name", "Jimjar")
    assert rc == 0 and "wrote its own header" in err
    text = (out(linked) / "draft/npc_jimjar.md").read_text()
    assert "subject: WRONG" not in text and text.count("subject:") == 1


def test_missing_section_writes_incomplete_exit_3_and_index_untouched(linked, fake):
    _, state = fake
    hs = synth.load_outline("npc_dossier")
    state["text"] = body(skip=(hs[3],))
    rc, so, err = draft(linked, "--name", "Jimjar")
    assert rc == 3 and "incomplete" in so and hs[3] in so
    assert (out(linked) / "draft/npc_jimjar.incomplete.md").is_file()
    assert not (out(linked) / "draft/npc_jimjar.md").exists()
    assert not (out(linked) / "draft/index.json").exists()
    rec = json.loads((latest_run(linked) / "record.json").read_text())
    assert rec["npcs"]["npc_jimjar"]["status"] == "incomplete" and rec["npcs"]["npc_jimjar"]["problems"]


def test_a_good_redraft_removes_the_incomplete_file_and_keeps_the_old_draft_on_failure(linked, fake):
    _, state = fake
    assert draft(linked, "--name", "Jimjar")[0] == 0
    before = (out(linked) / "draft/npc_jimjar.md").read_text()
    state["text"] = body(skip=("## Identity",))
    assert draft(linked, "--name", "Jimjar", "--force")[0] == 3
    assert (out(linked) / "draft/npc_jimjar.md").read_text() == before     # previous draft kept
    state["text"] = body()
    assert draft(linked, "--name", "Jimjar", "--force")[0] == 0
    assert not (out(linked) / "draft/npc_jimjar.incomplete.md").exists()


def test_dump_only_writes_prompts_selection_record_and_calls_nothing(linked, fake, monkeypatch):
    calls, _ = fake

    def boom(*a, **k):
        raise AssertionError("client created")

    monkeypatch.setattr(npc_draft, "client_from_args", boom)
    rc, so, _ = draft(linked, "--all", "--dump-only")
    assert rc == 0 and not calls
    run = latest_run(linked)
    assert (run / "selection.json").is_file()
    for stem in GLOBALS:
        assert (run / f"{stem}.system.md").is_file() and (run / f"{stem}.user.md").is_file()
    rec = json.loads((run / "record.json").read_text())
    assert set(rec["npcs"]) == set(GLOBALS) and rec["finished"]
    assert {"draft_key", "evidence_sha256", "manual_sha256", "status", "problems"} <= set(rec["npcs"]["npc_jimjar"])
    for k in ("corpus_manifest_sha256", "link_manifest_sha256", "registry_sha256", "wordlist_sha256", "template_sha256", "backend", "model", "max_tokens"):
        assert k in rec
    assert not (out(linked) / "draft").exists() and not (out(linked) / "gm").exists()


def test_second_run_skips_unchanged_and_composes_anyway(linked, fake):
    calls, _ = fake
    assert draft(linked, "--name", "Jimjar")[0] == 0 and len(calls) == 1
    gm = out(linked) / "gm/npc_jimjar.md"
    assert gm.is_file()
    gm.unlink()
    rc, so, _ = draft(linked, "--name", "Jimjar")
    assert rc == 0 and len(calls) == 1 and "skipped (unchanged)" in so
    assert gm.is_file()                                  # composed for a skipped NPC


def test_changed_manual_edit_redrafts_only_that_npc(linked, fake):
    calls, _ = fake
    assert draft(linked, "--name", "Jimjar", "Spider")[0] == 0 and len(calls) == 2
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual: [A deep gnome.]\n")
    # narrowing is not part of the key: the same two NPCs, one with a new edit
    rc, so, _ = draft(linked, "--name", "Jimjar", "Spider")
    assert rc == 0 and len(calls) == 3 and "Jimjar: drafted" in so and "Spider: skipped" in so


def test_secrets_only_edit_skips_the_model_but_reaches_the_gm_dossier(linked, fake):
    calls, _ = fake
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    f = d / "jimjar.authored.yaml"
    f.write_text("subject: Jimjar\nmanual: [A deep gnome.]\nsecrets: |\n  one\n")
    assert draft(linked, "--name", "Jimjar")[0] == 0
    f.write_text("subject: Jimjar\nmanual: [A deep gnome.]\nsecrets: |\n  two\n")
    rc, so, _ = draft(linked, "--name", "Jimjar")
    assert rc == 0 and len(calls) == 1 and "skipped (unchanged)" in so
    assert "two" in (out(linked) / "gm/npc_jimjar.md").read_text()


def test_force_and_model_change_redraft(linked, fake):
    calls, _ = fake
    assert draft(linked, "--name", "Jimjar")[0] == 0
    assert draft(linked, "--name", "Jimjar", "--force")[0] == 0 and len(calls) == 2
    assert draft(linked, "--name", "Jimjar", "--model", "another-model")[0] == 0 and len(calls) == 3


def test_model_failure_exits_4_keeps_finished_work_and_records_where(linked, fake, capsys):
    calls, state = fake
    state["fail_at"] = 2
    rc, so, err = draft(linked)
    assert rc == 4 and len(calls) == 2
    rec = json.loads((latest_run(linked) / "record.json").read_text())
    assert rec["stopped_at"]["stem"] == GLOBALS[1]
    assert rec["npcs"][GLOBALS[0]]["status"] == "drafted" and rec["npcs"][GLOBALS[1]]["status"] == "failed"
    assert (out(linked) / f"draft/{GLOBALS[0]}.md").is_file() and (out(linked) / f"gm/{GLOBALS[0]}.md").is_file()
    assert not (out(linked) / f"draft/{GLOBALS[1]}.md").exists()
    assert rec["npcs"][GLOBALS[2]]["status"] == "pending"      # not attempted


def test_gm_dossier_is_composed_for_every_selected_npc(linked, fake):
    assert draft(linked)[0] == 0
    assert sorted(p.stem for p in (out(linked) / "gm").glob("*.md")) == GLOBALS
    text = (out(linked) / "gm/npc_jimjar.md").read_text()
    assert text.startswith("<!-- summary_native npc gm | npc: Jimjar") and text.endswith("## Secrets\n_(none authored)_\n")


def test_draft_never_touches_the_031_corpus_or_authored(linked, fake):
    before = sha_tree(linked / "docs/summary_native/ch002-006")
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual: [x]\nsecrets: s\n")
    a = sha_tree(d)
    assert draft(linked)[0] == 0
    assert sha_tree(linked / "docs/summary_native/ch002-006") == before and sha_tree(d) == a


# ── US4: re-draft only what changed (T044, research R8) ─────────────────────

def _relink(root):
    assert run_cli(_args(root, "build", "--force"))[0] == 0
    assert run_cli(_args(root, "npc-link", "--force"))[0] == 0


def test_a_second_run_skips_everything_with_zero_model_calls(linked, fake):
    calls, _ = fake
    assert draft(linked)[0] == 0 and len(calls) == 5
    rc, so, _ = draft(linked)
    assert rc == 0 and len(calls) == 5
    assert so.count("skipped (unchanged)") == 5 and "drafted" not in so


def test_editing_one_summary_redrafts_only_the_npc_it_changes(linked, fake):
    calls, _ = fake
    assert draft(linked)[0] == 0
    p = linked / "docs/summaries/003-the-descent.md"
    p.write_text(p.read_text().replace("that did not attack.", "that did not strike."))
    _relink(linked)
    n = len(calls)
    rc, so, _ = draft(linked)
    assert rc == 0 and len(calls) == n + 1
    assert "Spider: drafted" in so and so.count("skipped (unchanged)") == 4


def test_a_changed_backend_model_max_tokens_or_template_redrafts(linked, fake, monkeypatch):
    calls, _ = fake
    assert draft(linked, "--name", "Jimjar")[0] == 0
    n = len(calls)
    for extra in (["--model", "m2"], ["--max-tokens", "1234"], ["--backend", "openrouter", "--model", "m2"]):
        assert draft(linked, "--name", "Jimjar", *extra)[0] == 0
        assert len(calls) == n + 1, extra
        n = len(calls)
    monkeypatch.setattr(npc_draft, "load_system", lambda: "a different system prompt")
    assert draft(linked, "--name", "Jimjar", "--model", "m2", "--max-tokens", "1234", "--backend", "openrouter")[0] == 0
    assert len(calls) == n + 1
    monkeypatch.setattr(synth, "load_outline", lambda doc: ["## Identity"])
    assert draft(linked, "--name", "Jimjar", "--model", "m2", "--max-tokens", "1234", "--backend", "openrouter")[0] in (0, 3)
    assert len(calls) == n + 2                       # the outline is part of the key too


def test_a_manual_edit_change_redrafts_but_a_secrets_only_change_skips_and_updates_the_gm_dossier(linked, fake):
    calls, _ = fake
    d = linked / "docs/npcs/authored"
    d.mkdir(parents=True)
    f = d / "jimjar.authored.yaml"
    f.write_text("subject: Jimjar\nmanual: [One.]\nsecrets: |\n  first\n")
    assert draft(linked, "--name", "Jimjar")[0] == 0 and len(calls) == 1
    f.write_text("subject: Jimjar\nmanual: [One.]\nsecrets: |\n  second\n")
    rc, so, _ = draft(linked, "--name", "Jimjar")
    assert rc == 0 and len(calls) == 1 and "skipped (unchanged)" in so
    assert "second" in (out(linked) / "gm/npc_jimjar.md").read_text()
    assert (out(linked) / "draft/npc_jimjar.verify.md").is_file()          # re-verified, not just re-composed
    f.write_text("subject: Jimjar\nmanual: [One, changed.]\nsecrets: |\n  second\n")
    rc, so, _ = draft(linked, "--name", "Jimjar")
    assert rc == 0 and len(calls) == 2 and "Jimjar: drafted" in so


def test_force_redrafts_everything(linked, fake):
    calls, _ = fake
    assert draft(linked)[0] == 0
    assert draft(linked, "--force")[0] == 0 and len(calls) == 10


def test_an_incomplete_or_failed_draft_never_updates_the_index(linked, fake):
    calls, state = fake
    assert draft(linked, "--name", "Jimjar")[0] == 0
    before = (out(linked) / "draft/index.json").read_text()
    state["text"] = body(skip=("## Identity",))
    assert draft(linked, "--name", "Jimjar", "--model", "m2")[0] == 3
    assert (out(linked) / "draft/index.json").read_text() == before
    state["fail_at"] = len(calls) + 1
    assert draft(linked, "--name", "Jimjar", "--model", "m3")[0] == 4
    assert (out(linked) / "draft/index.json").read_text() == before


def test_chunked_a_changed_chunk_size_or_mode_redrafts_the_whole_npc_and_a_skip_makes_no_call(linked, monkeypatch):
    from tests.conftest_npc import REDUCE_BODY, kind_of, map_output
    calls = []

    def render(client, system, user, model, max_tokens):
        calls.append(kind_of(system))
        return map_output(user) if kind_of(system) == "map" else REDUCE_BODY

    monkeypatch.setattr(npc_draft, "render_part", render)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    base = _args(linked, "npc-draft", "--name", "Jimjar")
    assert run_cli([*base, "--chunk-chars", "1"])[0] == 0 and calls == ["map"] * 4 + ["reduce"]
    assert run_cli([*base, "--chunk-chars", "1"])[0] == 0 and len(calls) == 5            # skipped: zero calls
    assert run_cli([*base, "--chunk-chars", "100000"])[0] == 0 and calls[5:] == ["map", "reduce"]   # no partial re-map
    n = len(calls)
    monkeypatch.setattr(npc_draft.npc_chunked, "load_map_system", lambda: "PART of a DRAFT, changed")
    assert run_cli([*base, "--chunk-chars", "100000"])[0] == 0 and len(calls) == n + 2    # a map prompt changed


def test_draft_ends_with_a_verification_totals_line_shaped_like_npc_verify(linked, fake):
    rc, so, _ = draft(linked)
    assert rc == 0
    last = so.strip().splitlines()[-1]
    assert last.startswith("verified 5 drafts: ") and " pass, " in last and last.count(" fail") == 1
    rc, so, _ = run_cli(_args(linked, "npc-verify"))
    assert so.strip().splitlines()[-1].split(":")[0] == last.split(":")[0]       # same shape


def test_draft_totals_line_counts_failures(linked, fake):
    _, state = fake
    state["text"] = body(extra=" [ch 002 / 002.99]")
    rc, so, _ = draft(linked, "--name", "Jimjar")
    assert rc == 0 and so.strip().splitlines()[-1].startswith("verified 1 drafts: 0 pass, 1 fail (invalid ")


def test_narrowing_defaults_come_from_npc_dossiers_yaml_not_grounding_yaml(tmp_path, monkeypatch):
    """flag > npc_dossiers.yaml > schema for npc-draft's recent_chapters / recurring_min."""
    from pipelines.summary_native import cli, schema
    from tests.conftest_npc import npc_campaign

    root = npc_campaign(tmp_path)
    cfg = root / "config" / "config.yaml"
    (root / "config" / "grounding.yaml").write_text("summary_native:\n  recent_chapters: 99\n  recurring_min: 98\n")
    assert cli._npc_config(cfg).recent_chapters == schema.DEFAULT_RECENT_CHAPTERS
    (root / "config" / "npc_dossiers.yaml").write_text("recent_chapters: 2\nrecurring_min: 3\n")
    assert (cli._npc_config(cfg).recent_chapters, cli._npc_config(cfg).recurring_min) == (2, 3)
    seen = {}
    monkeypatch.setattr(cli.npc_draft, "run_draft", lambda args, **kw: seen.update(kw) or 0)
    from tests.conftest_npc import SINCE, UNTIL, run_cli
    base = ["npc-draft", "--config", str(cfg), "--summaries-dir", str(root / "docs/summaries"),
            "--since", str(SINCE), "--until", str(UNTIL)]
    # run_draft is stubbed, so link/refusal logic never runs; the defaults reach it.
    rc, _, err = run_cli(base + ["--recent-chapters", "7"])
    assert rc == 0, err
    assert (seen["recent_chapters"], seen["default_recent"], seen["default_recurring"]) == (7, 2, 3)
