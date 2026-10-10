"""``npc-verify``: the mechanical trust report (spec 032 T027, research R10, FR-024)."""

from __future__ import annotations

import json

import pytest

from pipelines.summary_native import npc_draft, npc_verify, synth
from tests.conftest_npc import SINCE, UNTIL, npc_campaign, run_cli

EVIDENCE = """---
subject: Jimjar
---

# NPC — Jimjar

## Chapter 002

### Entry — Jimjar
- Source: x.md (line 1)

A deep gnome who says, "I don't know a way out."

### Scene 002.01 — Out of the Pens (mentioned)
- Source: x.md (line 7)

Jimjar whispered, "Follow me and stay low." The party followed.

### Moment (mentioned)
- Source: x.md (line 25)
- Scene: none

> "Keep your voices down, the walls listen."
> — Jimjar

## Chapter 003

### Scene 003.01 — Down the Stair (mentioned)
- Source: x.md (line 7)

Jimjar scouted the stair. He kept watch for the patrol.

## Chapter 006

### Scene 006.02 — The Last Camp (mentioned)
- Source: x.md (line 15)

Jimjar kept the first watch.
"""

CORPUS = npc_verify.CorpusIndex(
    frozenset({2, 3, 4, 5, 6}), frozenset({"002.01", "003.01", "004.01", "005.01", "006.02"})
)
MANUAL = ["Jimjar is a deep gnome."]

CLEAN = """<!-- summary_native npc draft | npc: Jimjar -->
---
subject: Jimjar
chapters: [2, 3, 6]
---

## Identity

A deep gnome. [ch 002 / entry] [manual 1]

## Personality and Motivations

Watchful. [ch 003 / 003.01]

## History with the Party

- Guides the party out of the pens. [ch 002 / 002.01]
- Keeps the first watch. [ch 006 / 006.02]

## Last Observed State

As of chapter 006 he kept the first watch. [ch 006 / 006.02]

## Relationships

- Travels with Eldeth. [ch 002 / 002.01]

## Notable Quotes

> "Keep your voices down, the walls listen." — Jimjar [ch 002 / moment]

> "Follow me and stay low." — Jimjar [ch 002 / 002.01]

## Arc-Score Candidates

- Candidate: he leads. [ch 002 / 002.01]
"""


def check(draft=CLEAN, manual=MANUAL, summaries="", evidence=EVIDENCE):
    return npc_verify.verify(draft, evidence, CORPUS, summaries, manual)


def codes(r):
    return [f.code for f in r.failures]


def test_a_clean_draft_passes_with_totals():
    r = check()
    assert r.passed and r.verdict == "pass" and not r.failures
    assert r.totals["quotes"] == 2 and r.totals["quotes_by_source"] == {"moment": 1, "scene": 1}
    assert r.totals["citations"] == r.totals["citations_valid"] == 9
    assert r.totals["manual_edits"] == 1 and r.counts["invalid"] == 0


def test_invalid_scene_id_absent_from_the_corpus():
    r = check(CLEAN.replace("[ch 002 / 002.01]\n- Keeps", "[ch 002 / 002.99]\n- Keeps"))
    f = [x for x in r.failures if x.code == "invalid"]
    assert len(f) == 1 and f[0].text == "[ch 002 / 002.99]" and f[0].line == 17 and not r.passed


def test_a_scene_whose_chapter_part_differs_is_invalid():
    assert "invalid" in codes(check(CLEAN.replace("[ch 003 / 003.01]", "[ch 002 / 003.01]")))


def test_outside_evidence_is_a_real_scene_not_in_this_npcs_pack():
    r = check(CLEAN.replace("[ch 003 / 003.01]", "[ch 005 / 005.01]"))
    assert codes(r) == ["outside-evidence"] and not r.passed


def test_not_found_quote_one_changed_character():
    r = check(CLEAN.replace("walls listen.", "walls listens."))
    assert codes(r) == ["not-found"]


def test_typography_normalised_is_an_advisory_and_the_verdict_stays_pass():
    r = check(CLEAN.replace('"Follow me and stay low."', '"Follow me and stay low’."').replace("stay low’.", "stay low."))
    assert r.passed
    ev = EVIDENCE.replace("Follow me and stay low.", "Don't follow me.")
    d = CLEAN.replace("Follow me and stay low.", "Don’t follow me.")
    r = check(d, evidence=ev)
    assert r.passed and r.counts["typography-normalised"] == 1
    assert [a.code for a in r.advisories] == ["typography-normalised"]


def test_a_quote_from_a_scene_body_or_entry_is_accepted_with_its_source():
    d = CLEAN.replace('> "Follow me and stay low." — Jimjar [ch 002 / 002.01]',
                      '> "I don\'t know a way out." — Jimjar [ch 002 / entry]\n\n> "Follow me and stay low." — Jimjar [ch 002 / 002.01]')
    r = check(d)
    assert r.passed and r.totals["quotes_by_source"] == {"entry": 1, "moment": 1, "scene": 1}


def test_there_is_no_not_from_moment_status():
    assert "not-from-moment" not in npc_verify.FAIL_CODES
    assert "not-from-moment" not in json.dumps(check().to_dict())


def test_a_quote_cited_to_the_wrong_item_is_a_citation_mismatch():
    r = check(CLEAN.replace('walls listen." — Jimjar [ch 002 / moment]', 'walls listen." — Jimjar [ch 002 / 002.01]'))
    assert codes(r) == ["citation-mismatch"]
    assert "uncited" not in codes(r)
    r = check(CLEAN.replace(' — Jimjar [ch 002 / moment]', ' — Jimjar'))
    assert codes(r) == ["citation-mismatch"]


def test_a_quoted_span_elsewhere_must_be_verbatim_too():
    r = check(CLEAN.replace("Watchful.", 'He said "nothing like this".'))
    assert codes(r) == ["not-found"]
    assert check(CLEAN.replace("Watchful.", 'He whispered "Follow me and stay low."')).passed


def test_a_quote_found_only_in_the_summaries_says_so():
    r = check(CLEAN.replace("Keep your voices down, the walls listen.", "the walls are thin."), summaries='x "the walls are thin." y')
    assert codes(r) == ["not-found"] and "summaries" in r.failures[0].detail


def test_placeholder_speaker_is_an_advisory():
    r = check(CLEAN.replace("— Jimjar [ch 002 / moment]", "— Speaker [ch 002 / moment]"))
    assert r.passed and r.counts["placeholder-speaker"] == 1


def test_uncited_history_bullet():
    r = check(CLEAN.replace("- Keeps the first watch. [ch 006 / 006.02]", "- Keeps the first watch."))
    f = [x for x in r.failures if x.code == "uncited"]
    assert len(f) == 1 and "Keeps the first watch" in f[0].text and f[0].line == 18


def test_a_manual_citation_satisfies_a_history_bullet():
    assert check(CLEAN.replace("- Keeps the first watch. [ch 006 / 006.02]", "- Is a gnome. [manual 1]")).passed


def test_a_label_with_every_nested_bullet_cited_passes():
    d = CLEAN.replace("- Guides the party out of the pens. [ch 002 / 002.01]",
                      "- Ch 2:\n  - Guides the party out. [ch 002 / 002.01]\n  - Whispers. [ch 002 / moment]")
    r = check(d)
    assert r.passed and r.totals["history_bullets"] == 3


def test_a_label_with_one_uncited_nested_bullet_reports_that_nested_bullet():
    d = CLEAN.replace("- Guides the party out of the pens. [ch 002 / 002.01]",
                      "- Ch 2:\n  - Guides the party out. [ch 002 / 002.01]\n  - Whispers.")
    r = check(d)
    f = [x for x in r.failures if x.code == "uncited"]
    assert len(f) == 1 and f[0].text.endswith("Whispers.")


def test_manual_edit_dropped_when_never_cited():
    r = check(CLEAN.replace(" [manual 1]", ""))
    f = [x for x in r.failures if x.code == "manual-dropped"]
    assert len(f) == 1 and "Jimjar is a deep gnome." in f[0].text and not r.passed


def test_manual_citation_out_of_range_is_invalid():
    r = check(CLEAN.replace("[manual 1]", "[manual 1] [manual 4]"), manual=MANUAL + ["b", "c"])
    assert "manual-invalid" in codes(r)          # [manual 4] with 3 edits
    assert "manual-dropped" in codes(r)          # edits 2 and 3 never cited
    r = check(CLEAN.replace("[manual 1]", "[manual 4]"), manual=["a", "b", "c"])
    assert codes(r).count("manual-invalid") == 1


def test_the_report_carries_the_used_not_meaning_note_and_pairs_edits_with_passages():
    r = check()
    md = npc_verify.render_verify_md(r, "Jimjar")
    assert npc_verify.USED_NOT_MEANING in md
    assert "[manual 1] Jimjar is a deep gnome." in md and "A deep gnome. [ch 002 / entry] [manual 1]" in md
    assert "**Verdict: pass**" in md
    md = npc_verify.render_verify_md(check(CLEAN.replace(" [manual 1]", "")), "Jimjar")
    assert "DROPPED" in md and "manual-dropped" in md


def test_status_claim_unsupported_is_reported_but_leaves_the_verdict_at_pass():
    r = check(CLEAN.replace("he kept the first watch.", "he was killed."))
    assert r.passed and [a.code for a in r.advisories] == ["status-claim-unsupported"]
    assert '"killed"' in r.advisories[0].detail
    # a status word the evidence itself uses is not reported
    ev = EVIDENCE.replace("Jimjar kept the first watch.", "Jimjar kept the first watch; Sarith was killed.")
    assert check(CLEAN.replace("he kept the first watch.", "he was killed."), evidence=ev).advisories == []


# ── through the CLI ─────────────────────────────────────────────────────────

OUT = "docs/npcs/summary_native/ch002-006"


def _args(root, cmd, *extra):
    return [
        cmd, "--config", str(root / "config/config.yaml"), "--summaries-dir", str(root / "docs/summaries"),
        "--since", str(SINCE), "--until", str(UNTIL), *extra,
    ]


@pytest.fixture
def drafted(tmp_path, monkeypatch):
    root = npc_campaign(tmp_path)
    assert run_cli(_args(root, "npc-link"))[0] == 0
    body = "\n".join(f"{h}\n\n- ok [ch 002 / 002.01]\n" for h in synth.load_outline("npc_dossier"))
    monkeypatch.setattr(npc_draft, "render_part", lambda *a, **k: body)
    monkeypatch.setattr(npc_draft, "client_from_args", lambda a, **k: object())
    rc, so, err = run_cli(_args(root, "npc-draft", "--mode", "one-shot", "--name", "Jimjar"))
    assert rc == 0, err
    return root, so


def test_the_verdict_is_in_record_json_and_the_verify_report_is_written(drafted):
    root, so = drafted
    run = sorted((root / OUT / "runs").iterdir())[-1]
    rec = json.loads((run / "record.json").read_text())
    assert rec["npcs"]["npc_jimjar"]["verify"]["verdict"] in ("pass", "fail")
    assert (root / OUT / "draft/npc_jimjar.verify.md").is_file() and "verify:" in so
    assert "npc_jimjar" in json.loads((run / "verify.json").read_text())


def test_npc_verify_passes_a_clean_draft_and_never_edits_it(drafted):
    root, _ = drafted
    p = root / OUT / "draft/npc_jimjar.md"
    before = p.read_bytes()
    rc, so, _ = run_cli(_args(root, "npc-verify"))
    assert rc == 0 and "Jimjar: pass" in so and "1 pass, 0 fail" in so
    assert p.read_bytes() == before


def test_npc_verify_exits_5_listing_each_seeded_defect(drafted):
    root, _ = drafted
    p = root / OUT / "draft/npc_jimjar.md"
    p.write_text(p.read_text().replace("[ch 002 / 002.01]", "[ch 002 / 002.99]", 1), encoding="utf-8")
    before = p.read_bytes()
    rc, so, _ = run_cli(_args(root, "npc-verify", "--name", "Jimjar"))
    assert rc == 5 and "Jimjar: fail (invalid 1" in so
    assert "002.99" in (root / OUT / "draft/npc_jimjar.verify.md").read_text()
    assert p.read_bytes() == before


def test_npc_verify_reports_a_dropped_manual_edit(drafted):
    root, _ = drafted
    d = root / "docs/npcs/authored"
    d.mkdir(parents=True)
    (d / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual:\n  - Jimjar is a deep gnome.\n")
    rc, so, err = run_cli(_args(root, "npc-verify", "--name", "Jimjar"))
    assert rc == 5 and "manual-dropped 1" in so and 'manual edit 1 dropped' in err and "Jimjar is a deep gnome." in err


def test_npc_verify_exits_2_with_no_drafts_or_an_unknown_name(tmp_path, drafted):
    root, _ = drafted
    rc, _, err = run_cli(_args(root, "npc-verify", "--name", "Nobody"))
    assert rc == 2 and "no evidence" in err
    rc, _, err = run_cli(_args(root, "npc-verify", "--name", "Spider"))
    assert rc == 2 and "no draft" in err
    for f in (root / OUT / "draft").glob("*.md"):
        f.unlink()
    rc, _, err = run_cli(_args(root, "npc-verify"))
    assert rc == 2 and "no draft dossiers" in err


def test_verify_writes_a_stable_local_journal_and_explicit_resume_accepts_it(drafted):
    root, _ = drafted
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar"))[0] == 0
    record_path = next((root / OUT / "verify_runs").glob("*/record.json"))
    record = json.loads(record_path.read_text())
    assert record["operation"] == "npc-verify" and record["status"] == "completed"
    assert record["items"] == [{"id": "npc_jimjar", "key": record["items"][0]["key"]}]
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar", "--resume", record["run_id"]))[0] == 0


def test_verifier_taxonomy_preserves_legacy_codes_on_the_shared_axis():
    from pipelines.summary_native import npc_verify

    assert npc_verify.verifier_category(npc_verify.INVALID) == "missing_source"
    assert npc_verify.verifier_category(npc_verify.NOT_FOUND) == "unsupported_or_contradicted"
    assert npc_verify.verifier_category(npc_verify.STATUS_UNSUPPORTED) == "citation_non_entailment"
    assert npc_verify.verifier_category("superseded-claim") == "superseded_claim"
    assert npc_verify.verifier_category("knowledge-leak") == "knowledge_leak"
    assert npc_verify.verifier_category(npc_verify.TYPOGRAPHY) == "presentation_only"
    assert npc_verify.verifier_category("verifier-transport-or-protocol") == "verifier_transport_or_protocol"


def test_verifier_failure_envelopes_keep_each_legacy_code_and_two_axes():
    from pipelines.summary_native import npc_verify
    result = npc_verify.VerificationResult(
        "fail", [npc_verify.Finding(npc_verify.INVALID, 7, "bad", "bad pointer")],
        [npc_verify.Finding(npc_verify.TYPOGRAPHY, 8, "quote", "curly quote")], {},
    )
    envelopes = npc_verify.failure_envelopes(result)
    assert [(e.operational_category, e.code, e.verifier_category) for e in envelopes] == [
        ("verifier_finding", "invalid", "missing_source"),
        ("verifier_finding", "typography-normalised", "presentation_only"),
    ]


def test_completed_verify_resume_reuses_current_result_without_local_execution(drafted, monkeypatch):
    """T031/T034/T035: a completed local result has the same zero-call rule."""
    root, _ = drafted
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar"))[0] == 0
    record_path = next((root / OUT / "verify_runs").glob("*/record.json"))
    run_id = json.loads(record_path.read_text())["run_id"]
    monkeypatch.setattr(npc_verify, "verify_draft", lambda *a, **k: pytest.fail("completed item was recomputed"))
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar", "--resume", run_id))[0] == 0


def test_completed_failing_verify_resume_preserves_its_verdict_without_execution(drafted, monkeypatch):
    root, _ = drafted
    authored = root / "docs/npcs/authored"
    authored.mkdir(parents=True)
    (authored / "jimjar.authored.yaml").write_text("subject: Jimjar\nmanual: [This claim is uncited.]\n")
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar"))[0] == 5
    record_path = next((root / OUT / "verify_runs").glob("*/record.json"))
    run_id = json.loads(record_path.read_text())["run_id"]
    monkeypatch.setattr(npc_verify, "verify_draft", lambda *a, **k: pytest.fail("completed item was recomputed"))
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar", "--resume", run_id))[0] == 5


def test_verify_resume_recomputes_when_journal_result_has_no_artifact(drafted, monkeypatch):
    """A journal cannot claim success when the corresponding verify artifact vanished."""
    root, _ = drafted
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar"))[0] == 0
    record_path = next((root / OUT / "verify_runs").glob("*/record.json"))
    record = json.loads(record_path.read_text())
    (root / OUT / "draft/npc_jimjar.verify.md").unlink()
    calls = []
    original = npc_verify.verify_draft
    monkeypatch.setattr(npc_verify, "verify_draft", lambda *a, **k: calls.append(1) or original(*a, **k))
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar", "--resume", record["run_id"]))[0] == 0
    assert calls == [1]


def test_verify_resume_refuses_changed_inputs_without_local_execution(drafted, monkeypatch):
    root, _ = drafted
    assert run_cli(_args(root, "npc-verify", "--name", "Jimjar"))[0] == 0
    record_path = next((root / OUT / "verify_runs").glob("*/record.json"))
    run_id = json.loads(record_path.read_text())["run_id"]
    draft = root / OUT / "draft/npc_jimjar.md"
    draft.write_text(draft.read_text() + "\nChanged after verification.\n")
    monkeypatch.setattr(npc_verify, "verify_draft", lambda *a, **k: pytest.fail("stale run executed"))
    rc, _, err = run_cli(_args(root, "npc-verify", "--name", "Jimjar", "--resume", run_id))
    assert rc == 2 and "inputs are stale" in err
