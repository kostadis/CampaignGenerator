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


# ── duplicate log rows on a matched thread (review finding, 2026-08-27) ──

def test_matched_ratify_does_not_duplicate_an_already_logged_chapter(tmp_path):
    """A matched candidate keeps its FULL chapter span in the payload, so a
    derived plan can carry a chapter the target thread already logged.
    Appending it again duplicates canon — and `check_registry` does not flag a
    repeated chapter, so nothing downstream catches it.

    Reproduces the reported path: the GM hand-creates a thread, then harvests
    a corpus whose candidate title matches it.
    """
    from _thread_fixtures import campaign as mk
    c = mk(tmp_path)
    (c / "docs").mkdir(parents=True, exist_ok=True)
    (c / "docs/thread_registry.yaml").write_text(
        "version: 1\nthreads:\n"
        "- {id: hand-made, title: A hand-made thread, status: open, opened: 30,\n"
        "   resolved: null, tracker: null, notes: '', aliases: [],\n"
        "   log: [{chapter: 30, change: opened, summary: typed by hand}]}\n")
    chapter(c, 30, [thread_fact("A hand-made thread", "corpus mentions it."),
                    thread_fact("A hand-made thread", "twice.")])
    chapter(c, 41, [thread_fact("A hand-made thread", "and again later.")])
    cli(c, "propose", "--corpus", CORPUS)

    p = proposals_doc(c)["proposals"][0]
    assert p["matches"] == "hand-made" and p["chapters"] == [30, 41]

    plan = cli(c, "ratify", "--norm", p["norm"], "--emit-plan").stdout
    r = cli(c, "ratify", "--norm", p["norm"], "--plan", "-", stdin=plan)
    assert r.returncode == 0, r.stderr

    threads = registry_doc(c)["threads"]
    assert len(threads) == 1
    chapters = [row["chapter"] for row in threads[0]["log"]]
    assert chapters == [30, 41], f"ch30 duplicated: {chapters}"
    # the skip is reported, never silent
    assert "already logged" in r.stdout and "ch30" in r.stdout


def test_ratify_records_the_ruling_when_every_row_is_already_present(tmp_path):
    """Nothing to append is not an error.

    `propose` never offers a candidate whose chapters are all logged, so this
    is reachable only via a hand-written plan — which is what `--plan`
    invites. Refusing would be the wrong call: the registry does not change,
    but the RULING is not a no-op. The GM decided this candidate is that
    thread, and recording it is what stops the candidate returning forever.
    What must not happen is a duplicated row or a message that implies one was
    written.
    """
    from _thread_fixtures import campaign as mk
    c = mk(tmp_path)
    (c / "docs").mkdir(parents=True, exist_ok=True)
    (c / "docs/thread_registry.yaml").write_text(
        "version: 1\nthreads:\n"
        "- {id: hand-made, title: A hand-made thread, status: open, opened: 30,\n"
        "   resolved: null, tracker: null, notes: '', aliases: [],\n"
        "   log: [{chapter: 30, change: opened, summary: typed by hand}]}\n")
    (c / "docs/ensemble").mkdir(parents=True, exist_ok=True)
    (c / PROPOSALS).write_text(
        "proposals:\n- norm: a-hand-made-thread\n  title: A hand-made thread\n"
        "  all_titles: [A hand-made thread]\n  matches: hand-made\n"
        "  chapters: [30]\n  status: pending\n  evidence: []\n")

    plan = json.dumps({"id": "hand-made", "title": "A hand-made thread",
                       "log": [{"chapter": 30, "change": "opened",
                                "summary": "the same row again"}]})
    r = cli(c, "ratify", "--norm", "a-hand-made-thread", "--plan", "-", stdin=plan)
    assert r.returncode == 0, r.stderr
    assert "0 log row(s) added" in r.stdout and "1 already present" in r.stdout
    assert len(registry_doc(c)["threads"][0]["log"]) == 1, "canon unchanged"
    assert proposals_doc(c)["proposals"][0]["status"] == "ratified", "ruling recorded"
