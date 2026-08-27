"""T032c — the atomic `ratify` verb (014, GM ruling research D18).

D18 replaced `add` + N x `log` + `rule` with one verb because that sequence
could half-apply, forcing the route to report a 207 partial state the GM then
had to interpret. What these tests pin is mostly what does NOT happen: a
refused ratification writes nothing at all.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _thread_fixtures import (  # noqa: E402
    ADJUDICATION, CORPUS, PROPOSALS, REGISTRY, chapter, cli, harvested,
    proposals_doc, registry_doc, thread_fact,
)

NORM = "buppidos-divine-plan"


def _plan(c):
    r = cli(c, "ratify", "--norm", NORM, "--emit-plan")
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_emit_plan_writes_nothing_and_round_trips_verbatim(tmp_path):
    c = harvested(tmp_path)
    plan = _plan(c)
    assert not (c / REGISTRY).exists(), "--emit-plan must write nothing"
    r = cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=plan)
    assert r.returncode == 0, r.stderr
    assert len(registry_doc(c)["threads"]) == 1


def test_plan_without_matches_creates_thread_with_exactly_its_log_rows(tmp_path):
    c = harvested(tmp_path)
    cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=_plan(c))
    t = registry_doc(c)["threads"][0]
    assert t["id"] == NORM and t["opened"] == 30
    assert [r["chapter"] for r in t["log"]] == [30, 41]
    assert [r["change"] for r in t["log"]] == ["opened", "advanced"]
    # The verified quote is carried through unmodified (Principle IV).
    assert t["log"][0]["quote"] == "the Sparkjewel told me"
    assert proposals_doc(c)["proposals"][0]["status"] == "ratified"
    assert proposals_doc(c)["proposals"][0]["ruled_thread"] == NORM


def test_plan_with_matches_appends_and_creates_no_second_thread(tmp_path):
    c = harvested(tmp_path)
    cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=_plan(c))
    # A later chapter re-offers the SAME candidate, now matched (FR-009a).
    chapter(c, 50, [thread_fact("Buppidos divine plan", "The shrine is finished.")])
    cli(c, "propose", "--corpus", CORPUS)
    p = proposals_doc(c)["proposals"][0]
    assert p["status"] == "pending" and p["chapters"] == [50]
    assert p["matches"] == NORM

    cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=_plan(c))
    threads = registry_doc(c)["threads"]
    assert len(threads) == 1, "FR-009: a matched proposal must not fork a thread"
    assert [r["chapter"] for r in threads[0]["log"]] == [30, 41, 50]


def test_log_row_without_a_real_chapter_is_refused_writing_nothing(tmp_path):
    c = harvested(tmp_path)
    bad = json.dumps({"id": "x", "title": "X",
                      "log": [{"chapter": None, "change": "opened", "summary": "s"}]})
    r = cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=bad)
    assert r.returncode != 0
    assert "yours to decide, not the harvest's" in r.stderr
    assert not (c / REGISTRY).exists()
    assert proposals_doc(c)["proposals"][0]["status"] == "pending"


def test_plan_failing_check_registry_writes_nothing(tmp_path):
    c = harvested(tmp_path)
    bad = json.dumps({"id": "x", "title": "X", "status": "resolved",
                      "opened": 30,
                      "log": [{"chapter": 30, "change": "opened", "summary": "s"}]})
    r = cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=bad)
    assert r.returncode != 0
    assert "refusing to save a registry that fails check" in r.stderr
    assert "no `resolved:` chapter" in r.stderr
    assert not (c / REGISTRY).exists()


def test_duplicate_thread_id_is_refused(tmp_path):
    c = harvested(tmp_path)
    cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=_plan(c))
    # Force a second, unmatched ratification onto the same id.
    (c / PROPOSALS).write_text(
        "proposals:\n- norm: other\n  title: Other thing\n  chapters: [30]\n"
        "  status: pending\n  evidence: []\n")
    dup = json.dumps({"id": NORM, "title": "Something else",
                      "log": [{"chapter": 30, "change": "opened", "summary": "s"}]})
    r = cli(c, "ratify", "--norm", "other", "--plan", "-", stdin=dup)
    assert r.returncode != 0
    assert "already exists" in r.stderr


def test_missing_plan_names_emit_plan_as_the_way_forward(tmp_path):
    c = harvested(tmp_path)
    r = cli(c, "ratify", "--norm", NORM)
    assert r.returncode != 0
    # FR-033's principle applied locally: a refusal names a way to proceed.
    assert "--emit-plan" in r.stderr


def test_registry_is_written_before_the_ruling(tmp_path):
    """The one non-atomic seam, asserted rather than hoped for.

    contracts/cli.md states the order: canon first, then the ruling. If the
    proposals write fails, the thread exists and the candidate stays
    `pending` — readable and recoverable. The other order would risk a
    proposal marked ratified with no thread behind it, which is worse.
    """
    c = harvested(tmp_path)
    plan = _plan(c)
    prop_dir = (c / PROPOSALS).parent
    mode = prop_dir.stat().st_mode
    os.chmod(prop_dir, 0o555)          # proposals write will fail
    try:
        r = cli(c, "ratify", "--norm", NORM, "--plan", "-", stdin=plan)
    finally:
        os.chmod(prop_dir, mode)
    assert r.returncode != 0
    assert (c / REGISTRY).exists(), "canon must already be written"
    assert registry_doc(c)["threads"][0]["id"] == NORM
    assert proposals_doc(c)["proposals"][0]["status"] == "pending"
