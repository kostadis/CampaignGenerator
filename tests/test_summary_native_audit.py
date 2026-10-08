"""audit: the tracking audit as its own step (spec 033 US6, T046, FR-026/FR-027).

Unit tests drive ``audit_select`` (items, candidate chapters, the verdict check, rendering) with no
model. The CLI tests use ``conftest_state.FakeModels``, so nothing reaches a backend.
"""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import audit_select as sel
from pipelines.summary_native import freshness, notes, npc_forms, schema, state_sections
from tests.conftest_state import (
    audit_args, audit_dir, common, extract_args, fake_models, range_dir, run_cli, state_campaign,
)


@pytest.fixture
def camp(tmp_path):
    return state_campaign(tmp_path)


@pytest.fixture
def fm(monkeypatch):
    return fake_models(monkeypatch)


# ── Items ───────────────────────────────────────────────────────────────────


def test_items_are_numbered_from_dash_lines_across_files(tmp_path):
    a, b = tmp_path / "one.txt", tmp_path / "two.md"
    a.write_text("# Tracking\n\n- First thing\nnot an item\n- Second thing\n-not an item either\n")
    b.write_text("- Third thing\n- \n")
    items = sel.load_items([a, b])
    assert [(i.id, i.file, i.text) for i in items] == [
        ("A1", "one.txt", "First thing"), ("A2", "one.txt", "Second thing"), ("A3", "two.md", "Third thing"),
    ]


# ── Candidate chapters ──────────────────────────────────────────────────────


def _chapters(camp):
    return notes.load_chapters(camp / "docs" / "summaries", 2, 5)


def _forms_and_words(camp):
    forms, _, _ = state_sections.load_identity(camp / "docs" / "entity_registry.yaml", camp / "config" / "players.yaml")
    words, _ = npc_forms.load_wordlist()
    return set(forms), words


def test_candidates_are_picked_by_registry_forms_and_distinctive_words(camp):
    forms, words = _forms_and_words(camp)
    chapters = _chapters(camp)
    # "Velkynvelve" and "Sarith" are names; "Reach", "meet" are dictionary words and never count.
    assert sel.item_tokens("Reach Velkynvelve and meet Sarith", forms, words) == ["velkynvelve", "sarith"]
    assert sel.candidate_chapters("Reach Velkynvelve and meet Sarith", chapters, forms, words, 3) == [2, 3, 4]
    # a registry form counts as one token; its words count again, so the full name outranks a part
    toks = sel.item_tokens("Ilvara Mizzrym is dead", forms, words)
    assert toks == ["ilvara", "ilvara mizzrym", "mizzrym"] or set(toks) == {"ilvara mizzrym", "ilvara", "mizzrym"}


def test_candidates_are_at_most_n_and_deterministic(camp):
    forms, words = _forms_and_words(camp)
    chapters = _chapters(camp)
    item = "Reach Velkynvelve and meet Sarith"
    got = [sel.candidate_chapters(item, chapters, forms, words, n) for n in (1, 2, 3, 9)]
    assert [len(g) for g in got] == [1, 2, 3, 4]
    assert got[0] == [2]  # tie on score: the earlier chapter
    assert sel.candidate_chapters(item, list(reversed(chapters)), forms, words, 3) == got[2]
    assert sel.candidate_chapters(item, chapters, forms, words, 0) == []


def test_generic_words_and_partial_words_do_not_make_candidates(camp):
    forms, words = _forms_and_words(camp)
    chapters = _chapters(camp)
    assert sel.candidate_chapters("Find the lost party and rest", chapters, forms, words, 3) == []
    # whole words only: "Sarithian" is not "Sarith"
    assert sel.candidate_chapters("Defeat the Sarithian", chapters, forms, words, 3) == []
    # a single-word registry form that is also a dictionary word is generic, so it counts for nothing
    assert sel.item_tokens("Gate", {"gate"}, words) == []


# ── The verdict check ───────────────────────────────────────────────────────


def _cands(camp, *numbers):
    return {c.number: c for c in _chapters(camp) if c.number in numbers}


SPAN = "Ilvara Mizzrym came to the bars at dusk"


def test_supported_needs_a_citation_in_the_candidates_and_a_verbatim_span(camp):
    v = sel.check_verdict(f'SHOWN\nCITE: [ch 002 / 002.02] "{SPAN}"\nShe came.', _cands(camp, 2, 3))
    assert (v.verdict, v.citation, v.span) == (sel.SUPPORTED, "[ch 002 / 002.02]", SPAN)


@pytest.mark.parametrize("answer,why", [
    (f'SHOWN\nCITE: [ch 004 / 004.02] "Ilvara Mizzrym was struck down in the doorway"', "outside the candidate chapters"),
    (f'SHOWN\nCITE: [ch 002 / 002.02] "She came to the bars at midnight"', "not verbatim"),
    (f'SHOWN\nCITE: [ch 002 / 002.02] "dusk"', "too short"),
    (f'SHOWN\nCITE: [ch 002 / 002.02]', "without a quoted span"),
    (f'SHOWN\n{SPAN}', "without a CITE line"),
    ('SHOWN', "without a CITE line"),
    ('It looks to me as if she did.', "did not begin with SHOWN or NOT SHOWN"),
    ('', "did not begin with SHOWN or NOT SHOWN"),
])
def test_a_shown_without_a_checkable_citation_and_span_is_unverified(camp, answer, why):
    v = sel.check_verdict(answer, _cands(camp, 2, 3))
    assert (v.verdict, v.reason) == (sel.NOT_FOUND, sel.UNVERIFIED)
    assert why in v.detail
    assert v.citation is None and v.span is None


@pytest.mark.parametrize("bad", ["002.09", "end"])
def test_a_verbatim_span_under_a_missing_target_is_cited_where_it_sits(camp, bad):
    # GM ruling 2026-10-07: the model named a scene or section the chapter does not have, but the
    # span is verbatim in that chapter. Code cites the scene that holds it and records the change.
    v = sel.check_verdict(f'SHOWN\nCITE: [ch 002 / {bad}] "{SPAN}"', _cands(camp, 2, 3))
    assert (v.verdict, v.citation, v.span) == (sel.SUPPORTED, "[ch 002 / 002.02]", SPAN)
    assert v.detail == f"citation corrected from [ch 002 / {bad}]"
    md = sel.render_audit_md({"verdicts": [{"id": "A1", "file": "t.txt", "text": "x", **v.to_dict()}]})
    assert f"citation corrected from [ch 002 / {bad}]" in md


@pytest.mark.parametrize("glue", ["\\n"])
def test_a_heading_glued_to_its_paragraph_is_narrowed_to_the_verbatim_piece(camp, glue):
    # GM ruling 2026-10-08: the judge quotes "Heading\nParagraph"; only the verbatim piece is kept.
    v = sel.check_verdict(f'SHOWN\nCITE: [ch 002 / 002.02] "Prisoner Notes{glue}{SPAN}"', _cands(camp, 2, 3))
    assert (v.verdict, v.citation, v.span) == (sel.SUPPORTED, "[ch 002 / 002.02]", SPAN)
    assert "narrowed" in v.detail


def test_narrowing_never_accepts_a_reworded_piece(camp):
    v = sel.check_verdict('SHOWN\nCITE: [ch 002 / 002.02] "Prisoner Notes\\nIlvara Mizzrym came to the bars at midnight"',
                          _cands(camp, 2, 3))
    assert v.reason == sel.UNVERIFIED and "not verbatim" in v.detail


def test_a_missing_target_with_a_span_from_elsewhere_is_still_unverified(camp):
    v = sel.check_verdict('SHOWN\nCITE: [ch 002 / 002.09] "She came to the bars at midnight"', _cands(camp, 2, 3))
    assert v.reason == sel.UNVERIFIED and "not verbatim" in v.detail


def test_section_of_names_the_nearest_citable_heading_and_never_inherits_across_an_uncitable_one():
    text = ("# S\n\n## Scenes\n\nlead-in words here\n\n### 002.01 One\n\nfirst scene words\n\n"
            "## Spells\n\nspell words\n\n## Unlisted Heading\n\nloose words\n")
    assert sel.section_of(text, "first scene words") == "002.01"
    assert sel.section_of(text, "spell words") == "spells"
    assert sel.section_of(text, "loose words") is None
    assert sel.section_of(text, "lead-in words here") is None
    assert sel.section_of(text, "absent words entirely") is None


def test_the_span_must_be_in_the_cited_chapter_not_just_a_candidate(camp):
    # the sentence exists in chapter 4, but the model cited chapter 2
    v = sel.check_verdict('SHOWN\nCITE: [ch 002 / 002.01] "Ilvara Mizzrym was struck down in the doorway"',
                          _cands(camp, 2, 4))
    assert v.reason == sel.UNVERIFIED and "not verbatim" in v.detail


def test_not_shown_keeps_only_partial_evidence_code_can_verify(camp):
    ans = (
        "NOT SHOWN\n"
        f'She is seen but nothing is done. "{SPAN}" [ch 002 / 002.02] Also something in [ch 009 / 009.01].'
    )
    v = sel.check_verdict(ans, _cands(camp, 2, 3))
    assert (v.verdict, v.reason) == (sel.NOT_FOUND, sel.NOT_SHOWN)
    assert len(v.partial) == 1 and "[ch 002 / 002.02]" in v.partial[0]


def test_verdict_round_trips_through_json():
    v = sel.Verdict(sel.NOT_FOUND, sel.UNVERIFIED, detail="d", partial=["p [ch 002 / 002.01]"])
    assert sel.Verdict.from_dict(json.loads(json.dumps(v.to_dict()))) == v


def test_render_lists_each_verdict_with_its_evidence_or_reason():
    data = {"verdicts": [
        {"id": "A1", "file": "t.txt", "text": "Reach X", "verdict": sel.SUPPORTED, "citation": "[ch 002 / 002.01]", "span": "arrived at X"},
        {"id": "A2", "file": "t.txt", "text": "Kill Y", "verdict": sel.NOT_FOUND, "reason": sel.NO_CANDIDATES},
        {"id": "A3", "file": "u.txt", "text": "Find Z", "verdict": sel.NOT_FOUND, "reason": sel.UNVERIFIED, "detail": "the span is not verbatim"},
        {"id": "A4", "file": "u.txt", "text": "Free W", "verdict": sel.NOT_FOUND, "reason": sel.NOT_SHOWN, "partial": ["W is chained [ch 003 / 003.01]"]},
        {"id": "A5", "file": "u.txt", "text": "Burn V", "verdict": sel.NOT_JUDGED},
    ]}
    md = sel.render_audit_md(data)
    assert md.startswith("audit: 5 items — 1 SUPPORTED, 3 NOT FOUND (1 no candidates, 1 unverified), 1 NOT JUDGED")
    assert '### t.txt' in md and '### u.txt' in md
    assert '- [A1] "Reach X" — `SUPPORTED`\n  - [ch 002 / 002.01] "arrived at X"' in md
    assert "`NOT FOUND` (no candidate chapters)" in md
    assert "not accepted: the span is not verbatim" in md
    assert "partial: W is chained [ch 003 / 003.01]" in md
    assert "`NOT JUDGED`" in md


# ── The step ────────────────────────────────────────────────────────────────

A1_SHOWN = (
    'SHOWN\nCITE: [ch 002 / 002.01] "Sarith held the gate and watched them through the bars"\nHe is met.\n'
)


def _audit(camp, *extra):
    return run_cli(audit_args(camp, *extra))


def test_a_supported_item_is_accepted_and_a_not_shown_one_is_not_found(camp, fm):
    fm.audit_answers["A1"] = A1_SHOWN
    rc, out, err = _audit(camp)
    assert rc == 0, err
    assert "audit: 2 items — 1 SUPPORTED, 1 NOT FOUND (0 no candidates, 0 unverified)" in out
    data = json.loads((audit_dir(camp) / "audit.json").read_text())
    by = {v["id"]: v for v in data["verdicts"]}
    assert by["A1"]["verdict"] == sel.SUPPORTED and by["A1"]["candidates"] == [2, 3, 4]
    assert by["A1"]["citation"] == "[ch 002 / 002.01]"
    assert by["A2"]["verdict"] == sel.NOT_FOUND and by["A2"]["reason"] == sel.NOT_SHOWN
    md = (audit_dir(camp) / "audit.md").read_text()
    assert "`SUPPORTED`" in md and "tracking.txt" in md


def test_each_item_is_judged_alone_against_only_its_candidates(camp, fm):
    assert _audit(camp)[0] == 0
    by = {c["id"]: c for c in fm.audit_calls}
    assert set(by) == {"A1", "A2"}
    a1 = by["A1"]["user"]
    assert "[A1] Reach Velkynvelve and meet Sarith" in a1 and "Ilvara signet ring" not in a1
    assert "CANDIDATE CHAPTERS (the only evidence): 002, 003, 004" in a1
    assert "======== CHAPTER 002" in a1 and "======== CHAPTER 005" not in a1
    assert "SHOWN" in by["A1"]["system"]


def test_a_supported_verdict_outside_the_candidates_is_downgraded_and_counted_not_found(camp, fm):
    # chapter 5 is a real chapter but not one of A1's candidates (2, 3, 4)
    fm.audit_answers["A1"] = 'SHOWN\nCITE: [ch 005 / 005.01] "The party rests and speaks of Ilvara Mizzrym"'
    rc, out, err = _audit(camp)
    assert rc == 0, err
    assert "0 SUPPORTED, 2 NOT FOUND (0 no candidates, 1 unverified)" in out
    assert "not accepted and counted NOT FOUND" in out
    a1 = json.loads((audit_dir(camp) / "audit.json").read_text())["verdicts"][0]
    assert (a1["verdict"], a1["reason"]) == (sel.NOT_FOUND, sel.UNVERIFIED)
    assert "outside the candidate chapters (002, 003, 004)" in a1["detail"]
    assert "outside the candidate chapters" in (audit_dir(camp) / "audit.md").read_text()


def test_a_non_verbatim_span_is_downgraded(camp, fm):
    fm.audit_answers["A1"] = 'SHOWN\nCITE: [ch 002 / 002.01] "Sarith stood the gate and watched the party"'
    rc, out, _ = _audit(camp)
    assert rc == 0 and "0 SUPPORTED" in out and "1 unverified" in out


def test_an_item_with_no_candidates_is_not_found_with_zero_calls(camp, fm, tmp_path):
    track = camp / "docs" / "tracking" / "generic.txt"
    track.write_text("- Find the lost party and rest\n")
    rc, out, err = run_cli([
        "audit", *common(camp), "--track-file", str(track),
        "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1",
    ])
    assert rc == 0, err
    assert fm.audit_calls == []
    assert "audit: 1 items — 0 SUPPORTED, 1 NOT FOUND (1 no candidates, 0 unverified)" in out
    v = json.loads((audit_dir(camp) / "audit.json").read_text())["verdicts"][0]
    assert (v["reason"], v["candidates"]) == (sel.NO_CANDIDATES, [])
    assert "no candidate chapters" in (audit_dir(camp) / "audit.md").read_text()
    # nothing was sent, so no endpoint was asked either
    assert fm.preflighted == []


def test_verdicts_are_cached_per_item(camp, fm):
    fm.audit_answers["A1"] = A1_SHOWN
    assert _audit(camp)[0] == 0
    assert len(fm.audit_calls) == 2
    fm.audit_calls.clear()
    rc, out, _ = _audit(camp)
    assert rc == 0 and fm.audit_calls == []
    assert "0 judged, 2 cached" in out and "1 SUPPORTED" in out  # the cached answer is re-checked, still accepted
    rc, _, _ = _audit(camp, "--force")
    assert rc == 0 and len(fm.audit_calls) == 2


def test_a_changed_item_re_judges_only_that_item(camp, fm):
    assert _audit(camp)[0] == 0
    fm.audit_calls.clear()
    (camp / "docs" / "tracking" / "tracking.txt").write_text(
        "- Reach Velkynvelve and meet Sarith\n- Obtain the Ilvara signet ring and wear it\n")
    assert _audit(camp)[0] == 0
    assert [c["id"] for c in fm.audit_calls] == ["A2"]


def test_a_different_model_does_not_reuse_the_cache(camp, fm):
    assert _audit(camp)[0] == 0
    fm.audit_calls.clear()
    args = audit_args(camp)
    args[args.index("fake-model")] = "other-model"
    assert run_cli(args)[0] == 0
    assert len(fm.audit_calls) == 2


def test_a_failed_item_leaves_the_audit_incomplete_and_the_next_run_judges_only_it(camp, fm):
    fm.audit_answers["A1"] = A1_SHOWN
    fm.audit_fail["A2"] = 2  # the call and its one retry
    rc, out, err = _audit(camp)
    assert rc == 3 and "A2" in err and "1 NOT JUDGED" in out
    data = json.loads((audit_dir(camp) / "audit.json").read_text())
    assert {v["id"]: v["verdict"] for v in data["verdicts"]} == {"A1": sel.SUPPORTED, "A2": sel.NOT_JUDGED}
    fm.audit_calls.clear()
    rc, out, _ = _audit(camp)
    assert rc == 0 and [c["id"] for c in fm.audit_calls] == ["A2"]
    assert "NOT JUDGED" not in (audit_dir(camp) / "audit.md").read_text()


def test_every_call_failing_is_exit_4(camp, fm):
    fm.audit_fail.update({"A1": 2, "A2": 2})
    rc, _, err = _audit(camp)
    assert rc == 4 and "no item could be judged" in err


def test_dump_only_writes_prompts_and_makes_no_call(camp, fm):
    rc, out, err = _audit(camp, "--dump-only")
    assert rc == 0, err
    assert fm.audit_calls == [] and "--dump-only" in out
    assert not (audit_dir(camp) / "audit.json").exists() and not (audit_dir(camp) / "items.json").exists()
    runs = sorted((range_dir(camp) / schema.STATE_DIR / "runs").iterdir())
    assert (runs[-1] / "audit.A1.user.md").is_file() and (runs[-1] / "audit.system.md").is_file()


def test_items_json_records_candidates_keys_and_the_digests_freshness_reads(camp, fm):
    assert _audit(camp)[0] == 0
    items = json.loads((audit_dir(camp) / "items.json").read_text())
    assert items["kind"] == "audit_items"
    assert [(i["id"], i["candidate_chapters"]) for i in items["items"]] == [("A1", [2, 3, 4]), ("A2", [2, 3, 4])]
    assert all(i["cache_key"] for i in items["items"]) and items["candidates"] == 3
    assert freshness.check_audit_fresh(range_dir(camp), [camp / "docs" / "tracking" / "tracking.txt"]) is None
    (camp / "docs" / "tracking" / "tracking.txt").write_text("- changed\n")
    assert "the audit is stale" in freshness.check_audit_fresh(range_dir(camp), [camp / "docs" / "tracking" / "tracking.txt"])


def test_the_run_record_names_inputs_endpoint_and_per_item_results(camp, fm):
    assert _audit(camp, "--candidates", "2")[0] == 0
    (rec_path,) = (range_dir(camp) / schema.STATE_DIR / "runs").glob("*/record.json")
    rec = json.loads(rec_path.read_text())
    assert rec["step"] == "audit" and rec["backend"] == "dgx" and rec["model"] == "fake-model"
    assert rec["candidates"] == 2 and rec["endpoints"] == ["spark:8001"] and rec["exit_code"] == 0
    assert rec["inputs"]["track_files_sha256"][0][0] == "tracking.txt"
    assert [i["candidates"] for i in rec["items"]] == [[2, 3], [2, 4]]
    assert all(i["status"] == "judged" and i["endpoint"] == "spark:8001" for i in rec["items"])


def test_the_judge_runs_on_the_shared_multi_endpoint_queue(camp, fm):
    eps = ["http://spark:8001/v1", "http://spark2:8001/v1"]
    args = [a for a in audit_args(camp) if a not in ("--endpoint", "http://spark:8001/v1")]
    rc, _, err = run_cli([*args, "--endpoints", *eps, "--parallel", "2"])
    assert rc == 0, err
    assert fm.preflighted == eps
    assert len(fm.audit_calls) == 2


def test_an_unreachable_endpoint_is_refused_before_any_call(camp, fm):
    fm.unreachable.add("http://spark2:8001/v1")
    args = [a for a in audit_args(camp) if a not in ("--endpoint", "http://spark:8001/v1")]
    rc, _, err = run_cli([*args, "--endpoints", "http://spark:8001/v1", "http://spark2:8001/v1"])
    assert rc == 2 and "spark2:8001" in err and "no item was sent" in err
    assert fm.audit_calls == []


def test_endpoint_and_endpoints_together_are_refused(camp, fm):
    rc, _, err = _audit(camp, "--endpoints", "http://spark:8001/v1")
    assert rc == 2 and "--endpoint or --endpoints, not both" in err and fm.audit_calls == []


def test_track_files_default_to_grounding_yaml_and_are_required(camp, fm):
    args = ["audit", *common(camp), "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1"]
    rc, _, err = run_cli(args)
    assert rc == 2 and "no track files" in err
    (camp / "config" / "grounding.yaml").write_text("campaign_state:\n  track_files: [docs/tracking/tracking.txt]\n")
    rc, out, err = run_cli(args)
    assert rc == 0, err
    assert "audit: 2 items" in out


def test_a_missing_track_file_is_refused_by_name(camp, fm):
    rc, _, err = run_cli(["audit", *common(camp), "--track-file", "docs/tracking/nope.txt",
                          "--backend", "dgx", "--model", "fake-model", "--endpoint", "http://spark:8001/v1"])
    assert rc == 2 and "nope.txt" in err


def test_repeated_track_files_are_numbered_across_files(camp, fm):
    extra = camp / "docs" / "tracking" / "more.txt"
    extra.write_text("- Free Kalan from the east stair\n")
    args = audit_args(camp) + ["--track-file", str(extra)]
    rc, out, err = run_cli(args)
    assert rc == 0, err
    ids = [v["id"] for v in json.loads((audit_dir(camp) / "audit.json").read_text())["verdicts"]]
    assert ids == ["A1", "A2", "A3"]


def test_a_stale_corpus_is_refused(camp, fm):
    (camp / "docs" / "summaries" / "002-the-pens.md").write_text(
        (camp / "docs" / "summaries" / "002-the-pens.md").read_text() + "\nChanged.\n")
    rc, _, err = _audit(camp)
    assert rc == 2 and "summary_native build --force" in err and fm.audit_calls == []


def test_the_extraction_prompts_still_carry_no_audit_list(camp, fm):
    """FR-027 stays true with the audit built: extraction never sees an item."""
    assert run_cli(extract_args(camp))[0] == 0
    for call in fm.extract_calls:
        assert "Obtain the Ilvara signet ring" not in call["user"] + call["system"]


# ── campaign_state's Audit section ──────────────────────────────────────────


def _campaign_state(camp):
    rc, _, err = run_cli(["synth", "campaign_state", *common(camp), "--backend", "claude-code", "--model", "m", "--force"])
    assert rc == 0, err
    return (range_dir(camp) / schema.STATE_DIR / "drafts" / "campaign_state.draft.md").read_text()


def test_campaign_state_renders_its_audit_section_from_audit_json(camp, fm):
    assert run_cli(extract_args(camp))[0] == 0
    (camp / "config" / "grounding.yaml").write_text("campaign_state:\n  track_files: [docs/tracking/tracking.txt]\n")
    assert "Audit not run for this range." in _campaign_state(camp)
    fm.audit_answers["A1"] = A1_SHOWN
    assert _audit(camp)[0] == 0
    draft = _campaign_state(camp)
    body = draft.split("## Audit: Tracking Claims", 1)[1]
    assert "Audit not run" not in body
    assert '- [A1] "Reach Velkynvelve and meet Sarith" — `SUPPORTED`' in body
    assert '[ch 002 / 002.01] "Sarith held the gate and watched them through the bars"' in body
    assert "`NOT FOUND`" in body
    # byte-identical to the renderer's output for the file on disk: nothing else shaped the section
    data = json.loads((audit_dir(camp) / "audit.json").read_text())
    assert sel.render_audit_md(data).strip() in body


def test_a_stale_audit_stops_campaign_state_naming_the_audit_step(camp, fm):
    assert run_cli(extract_args(camp))[0] == 0
    (camp / "config" / "grounding.yaml").write_text("campaign_state:\n  track_files: [docs/tracking/tracking.txt]\n")
    assert _audit(camp)[0] == 0
    (camp / "docs" / "tracking" / "tracking.txt").write_text("- Something else\n")
    rc, _, err = run_cli(["synth", "campaign_state", *common(camp), "--backend", "claude-code", "--model", "m", "--force"])
    assert rc == 2 and "the audit is stale" in err and "summary_native audit" in err


def test_an_unreadable_audit_json_reads_as_not_run(camp):
    ad = audit_dir(camp)
    ad.mkdir(parents=True)
    (ad / "items.json").write_text("{}")
    (ad / "audit.json").write_text("{not json")
    assert state_sections.audit_md(range_dir(camp)) == schema.AUDIT_NOT_RUN
