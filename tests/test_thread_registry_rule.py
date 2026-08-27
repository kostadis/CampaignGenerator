"""T035/T036 — the `rule` verb, the adjudication bundle, and the round-trip.

The round-trip test at the bottom is the one that matters: it distinguishes
"a ruling persists" (SC-006) from "a ratified thread stops surfacing"
(FR-009a) — two behaviours the old short-circuit conflated, which is how
ratifying at ch41 could hide ch50-60 of that same thread forever (D17b).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from _thread_fixtures import (  # noqa: E402
    ADJUDICATION, CORPUS, PROPOSALS, chapter, cli, harvested,
    proposals_doc, registry_doc, thread_fact,
)

NORM = "buppidos-divine-plan"


def _by_norm(c):
    return {p["norm"]: p for p in proposals_doc(c)["proposals"]}


def test_each_status_writes_back(tmp_path):
    for status in ("rejected", "deferred"):
        c = harvested(tmp_path / status)
        r = cli(c, "rule", "--norm", NORM, "--status", status)
        assert r.returncode == 0, r.stderr
        assert _by_norm(c)[NORM]["status"] == status
    # `ratified` needs a thread to point at — see the test below.
    c = harvested(tmp_path / "ratified")
    r = cli(c, "rule", "--norm", NORM, "--status", "ratified", "--thread", "t1")
    assert r.returncode == 0, r.stderr
    assert _by_norm(c)[NORM]["status"] == "ratified"


def test_ratified_without_a_thread_is_refused(tmp_path):
    """A ruling that would not survive the next `propose` is not a ruling.

    `load_prior_rulings` keeps it, but the short-circuit covers only
    rejected/deferred, `match_thread` finds nothing (no thread was created)
    and `ruled_thread` is absent — so the next harvest rewrites the row as
    `pending` and the ruling evaporates, contradicting the docstring's
    promise that rulings are preserved across re-proposes.
    """
    c = harvested(tmp_path)
    r = cli(c, "rule", "--norm", NORM, "--status", "ratified")
    assert r.returncode != 0
    assert "--thread" in r.stderr and "does not survive" in r.stderr
    assert _by_norm(c)[NORM]["status"] == "pending", "nothing written"


def test_note_and_thread_are_recorded(tmp_path):
    c = harvested(tmp_path)
    cli(c, "rule", "--norm", NORM, "--status", "ratified",
        "--note", "same as the Sparkjewel thread", "--thread", "sparkjewel")
    p = _by_norm(c)[NORM]
    assert p["note"] == "same as the Sparkjewel thread"
    assert p["ruled_thread"] == "sparkjewel"


def test_other_proposals_and_the_preamble_survive(tmp_path):
    c = harvested(tmp_path)
    chapter(c, 31, [thread_fact("A second thing", "It also happened.")])
    cli(c, "propose", "--corpus", CORPUS)
    before = yaml.safe_load((c / PROPOSALS).read_text())
    assert before.get("note"), "fixture should have a preamble to preserve"

    cli(c, "rule", "--norm", NORM, "--status", "rejected")
    after = yaml.safe_load((c / PROPOSALS).read_text())
    assert after["note"] == before["note"]
    assert len(after["proposals"]) == len(before["proposals"])
    assert _by_norm(c)["a-second-thing"]["status"] == "pending"


def test_deferred_appends_to_the_bundle_with_its_evidence(tmp_path):
    c = harvested(tmp_path)
    cli(c, "rule", "--norm", NORM, "--status", "deferred", "--note", "unsure")
    bundle = json.loads((c / ADJUDICATION).read_text())
    assert bundle["version"] == 1 and len(bundle["entries"]) == 1
    e = bundle["entries"][0]
    assert e["norm"] == NORM and e["note"] == "unsure"
    # SC-007: self-sufficient — adjudicable without re-running the harvest.
    assert len(e["evidence"]) == 2
    assert e["evidence"][0]["quote"] == "the Sparkjewel told me"


def test_deferring_a_second_candidate_appends_rather_than_overwrites(tmp_path):
    c = harvested(tmp_path)
    chapter(c, 31, [thread_fact("A second thing", "It also happened.")])
    cli(c, "propose", "--corpus", CORPUS)
    cli(c, "rule", "--norm", NORM, "--status", "deferred")
    cli(c, "rule", "--norm", "a-second-thing", "--status", "deferred")
    entries = json.loads((c / ADJUDICATION).read_text())["entries"]
    assert [e["norm"] for e in entries] == [NORM, "a-second-thing"]


def test_re_ruling_deferred_to_ratified_keeps_the_bundle_entry(tmp_path):
    c = harvested(tmp_path)
    cli(c, "rule", "--norm", NORM, "--status", "deferred", "--note", "ask")
    cli(c, "rule", "--norm", NORM, "--status", "ratified", "--thread", "t1")
    assert _by_norm(c)[NORM]["status"] == "ratified"
    # The conversation happened; the record of it is not a lie.
    entries = json.loads((c / ADJUDICATION).read_text())["entries"]
    assert len(entries) == 1 and entries[0]["note"] == "ask"


def test_refusals(tmp_path):
    c = harvested(tmp_path)
    r = cli(c, "rule", "--norm", "nope", "--status", "ratified")
    assert r.returncode != 0 and "no proposal with norm 'nope'" in r.stderr

    r = cli(c, "rule", "--norm", NORM, "--status", "maybe")
    assert r.returncode != 0
    assert "bad ruling 'maybe'" in r.stderr and "ratified, rejected, deferred" in r.stderr

    (c / PROPOSALS).unlink()
    r = cli(c, "rule", "--norm", NORM, "--status", "rejected")
    assert r.returncode != 0 and "run propose first" in r.stderr


# ── the round-trip (T036) ────────────────────────────────────────────────

def test_round_trip_rejected_deferred_persist_ratified_keeps_surfacing(tmp_path):
    c = harvested(tmp_path)
    chapter(c, 31, [thread_fact("A rejected thing", "Noise.")])
    chapter(c, 32, [thread_fact("A deferred thing", "Maybe something.")])
    cli(c, "propose", "--corpus", CORPUS)

    cli(c, "rule", "--norm", "a-rejected-thing", "--status", "rejected")
    cli(c, "rule", "--norm", "a-deferred-thing", "--status", "deferred")
    plan = cli(c, "ratify", "--norm", NORM, "--emit-plan").stdout
    cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=plan)

    cli(c, "propose", "--corpus", CORPUS)
    after = _by_norm(c)

    # (1) SC-006 — a rejection and a deferral survive and do not return pending
    assert after["a-rejected-thing"]["status"] == "rejected"
    assert after["a-deferred-thing"]["status"] == "deferred"

    # (2) a ratified candidate's already-logged chapters are not re-proposed,
    #     but its RULING is kept — dropping the row would lose the record and
    #     let a later chapter re-offer the candidate as brand new.
    assert after[NORM]["status"] == "ratified"
    assert after[NORM]["ruled_thread"] == NORM

    # (3) FR-009a — the assertion that would have caught the D17b defect:
    #     a LATER chapter of an accepted thread is offered again.
    chapter(c, 50, [thread_fact("Buppidos divine plan", "The shrine is finished.")])
    cli(c, "propose", "--corpus", CORPUS)
    reoffered = _by_norm(c)[NORM]
    assert reoffered["status"] == "pending"
    assert reoffered["chapters"] == [50], "only the unlogged chapter"
    assert reoffered["matches"] == NORM, "append, never a second thread"
    assert len(registry_doc(c)["threads"]) == 1
