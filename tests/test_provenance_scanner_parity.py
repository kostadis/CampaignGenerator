"""The two scanners must be indistinguishable except in latency (research D1).

`rg` is ~60× faster than the stdlib fallback, and which one runs depends on
whether `shutil.which("rg")` resolves in the *spawning process's* PATH — which
differed between an interactive shell and a Python subprocess on this very host,
on the same day. If the two implementations could disagree, results would vary
by machine and by how the tool was launched, and SC-009 ("identical results on
rebuild") would be unfalsifiable.

So parity is asserted mechanically, over the pinned fixture workspace **and**
over one live campaign — because the fixture cannot reproduce a 4,000-file tree
with spaces in filenames, `.gitignore`d subdirectories and non-UTF-8 sidecars,
and those are precisely where two scanners drift apart.

`suppressed_by_exclude` is part of the parity contract, not an afterthought: a
count that differs between implementations is a scope difference that has not
yet shown up as a missing hit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from provenance.scan import scan, select_scanner
from provenance.search import SearchRequest, run_search

pytestmark = pytest.mark.usefixtures("rg_or_skip")


def _both(campaign, root: Path, query: str, **kw):
    return (
        scan(campaign, root, query, impl=select_scanner("rg"), **kw),
        scan(campaign, root, query, impl=select_scanner("python"), **kw),
    )


def test_identical_match_sets_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    rg, py = _both(
        fixture_manifest.campaigns["alpha"], fixture_workspace / "alpha", "Silver Lantern"
    )
    assert {(m.path, m.line) for m in rg.matches} == {(m.path, m.line) for m in py.matches}


def test_identical_exclude_counts_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    rg, py = _both(
        fixture_manifest.campaigns["alpha"], fixture_workspace / "alpha", "Silver Lantern"
    )
    assert rg.files.excluded == py.files.excluded


def test_identical_on_a_case_insensitive_query(fixture_manifest, fixture_workspace) -> None:
    rg, py = _both(
        fixture_manifest.campaigns["alpha"], fixture_workspace / "alpha", "silver lantern"
    )
    assert {(m.path, m.line) for m in rg.matches} == {(m.path, m.line) for m in py.matches}


def test_identical_on_a_regex_query(fixture_manifest, fixture_workspace) -> None:
    rg, py = _both(
        fixture_manifest.campaigns["alpha"],
        fixture_workspace / "alpha",
        r"Marnix\s+Vale",
        regex=True,
    )
    assert {(m.path, m.line) for m in rg.matches} == {(m.path, m.line) for m in py.matches}


def test_identical_full_responses_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    """Path, line AND excerpt, through the whole pipeline including ranking."""
    responses = [
        run_search(
            SearchRequest(query="Silver Lantern", campaigns=["alpha", "beta"], scanner=s),
            fixture_manifest,
            fixture_workspace,
        )
        for s in ("rg", "python")
    ]
    shapes = [
        [(h.campaign, h.path, h.line, h.excerpt) for h in r.hits] for r in responses
    ]
    assert shapes[0] == shapes[1]
    assert responses[0].suppressed_by_exclude == responses[1].suppressed_by_exclude
    assert responses[0].total_matched == responses[1].total_matched


def test_the_total_order_tail_is_load_bearing(fixture_manifest, fixture_workspace) -> None:
    """Sanity: the fixture actually contains relevance ties across files.

    If it did not, the parity assertions above would pass with a sort key that
    leaves ties to scan order — and would then start flapping against the live
    corpus instead, which is the worst place to discover it.
    """
    response = run_search(
        SearchRequest(query="Silver Lantern", campaigns=["alpha"]),
        fixture_manifest,
        fixture_workspace,
    )
    relevances = [h.relevance for h in response.hits]
    assert len(set(relevances)) < len(relevances), "no ties in the fixture; parity is vacuous"


# ── live corpus ──────────────────────────────────────────────────────────────


def test_identical_on_one_live_campaign(live_manifest, live_workspace) -> None:
    """The fixture cannot reproduce 4,000 files, spaces in names, or real .gitignores."""
    name = next(
        (n for n in ("Phandalin", "obelisk", "Hillsfar") if n in live_manifest.campaigns),
        live_manifest.campaign_names[0],
    )
    campaign = live_manifest.campaigns[name]
    root = live_workspace / campaign.root
    if not root.is_dir():
        pytest.skip(f"{name} root absent on this machine")

    rg, py = _both(campaign, root, "the")
    assert {(m.path, m.line) for m in rg.matches} == {(m.path, m.line) for m in py.matches}
    assert rg.files.excluded == py.files.excluded
