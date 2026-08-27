"""T010 — the three machine-readable read verbs (014, contracts/cli.md).

The server consumes `--json` rather than screen-scraping a human table
(Constitution VI, FR-023). These pin the shapes it depends on, including the
empty-registry case: a campaign that has never harvested is a *state* the
queue renders as "no candidates yet", not an error.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _thread_fixtures import (  # noqa: E402
    CORPUS, cli, campaign, harvested, registry_doc,
)


def test_list_json_shape(tmp_path):
    c = harvested(tmp_path)
    cli(c, "ratify", "--norm", "buppidos-divine-plan", "--plan", "-",
        stdin=cli(c, "ratify", "--norm", "buppidos-divine-plan",
                  "--emit-plan").stdout)
    r = cli(c, "list", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) == {"version", "threads", "count"}
    assert payload["count"] == len(payload["threads"]) == 1
    assert payload["threads"][0]["id"] == "buppidos-divine-plan"


def test_list_json_empty_registry_is_a_state_not_an_error(tmp_path):
    c = campaign(tmp_path)
    r = cli(c, "list", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"version": 1, "threads": [], "count": 0}


def test_proposals_json_shape_and_counts(tmp_path):
    c = harvested(tmp_path)
    r = cli(c, "proposals", "--json")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) == {"proposals", "counts"}
    assert payload["counts"] == {"pending": 1}
    p = payload["proposals"][0]
    assert p["norm"] == "buppidos-divine-plan"
    assert p["chapters"] == [30, 41]
    # Both spellings survive: the equivalence set is shown, never applied as a
    # transform that would destroy which form was actually recorded.
    assert p["all_titles"] == ["Buppido's divine plan", "Buppidos divine plan"]


def test_proposals_json_absent_file_reads_as_empty(tmp_path):
    c = campaign(tmp_path)
    r = cli(c, "proposals", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"proposals": [], "counts": {}}


def test_check_json_clean_registry_exits_zero(tmp_path):
    c = campaign(tmp_path)
    r = cli(c, "check", "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"threads": 0, "problems": []}


def test_check_json_reports_problems_and_keeps_exit_1(tmp_path):
    c = campaign(tmp_path)
    (c / "docs").mkdir(parents=True, exist_ok=True)
    (c / "docs/thread_registry.yaml").write_text(
        "version: 1\nthreads:\n"
        "- id: broken\n  title: Broken\n  status: open\n  opened: 1\n"
        "  log:\n  - {chapter: null, change: advanced, summary: s}\n")
    r = cli(c, "check", "--json")
    # The exit code stays 1 for shell users and CI; the ROUTE turns this into
    # a 200 with `problems` in the body, because a failing check is data to
    # render, not a transport error.
    assert r.returncode == 1
    payload = json.loads(r.stdout)
    assert payload["threads"] == 1
    assert any("real chapter number" in p for p in payload["problems"])


def test_proposals_json_is_never_pre_filtered(tmp_path):
    """FR-028/research D16: no paging, no server-side query, no threshold."""
    c = campaign(tmp_path)
    from _thread_fixtures import chapter, thread_fact
    for i in range(1, 26):
        chapter(c, i, [thread_fact(f"Candidate {i}", f"Something happened {i}.")])
    cli(c, "propose", "--corpus", CORPUS)
    payload = json.loads(cli(c, "proposals", "--json").stdout)
    assert len(payload["proposals"]) == 25
    assert payload["counts"]["pending"] == 25
