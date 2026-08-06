"""US4: what was true as of chapter N, and what the tool refuses to guess.

A horizon query is a question about the past, and the worst available failure is
a confident, complete-looking answer full of the future spoilers the question was
asked to exclude. So three behaviours are pinned here:

1. **Attribution comes from the path, never the file body.** A regex over
   contents would be inference and would violate FR-029; the boundary is the
   file (research D14). obelisk needs ``session_(\\d+)_`` where the other five
   need ``chapter_(\\d+)_``, which is why the pattern is per-campaign and
   hand-authored — a shared one fails there in silence (research D2).
2. **A campaign with no marker is refused, never served unfiltered** (FR-025).
3. **A file the pattern cannot attribute is returned labeled, not dropped.** It
   cannot answer the question either way, and removing it would present a
   narrowed corpus as a complete one.
"""

from __future__ import annotations

import pytest

from provenance.cli import EXIT_REFUSED, main
from provenance.envelope import INCLUDED, UNATTRIBUTABLE, chapter_for
from provenance.search import SearchRequest, run_search


def _search(manifest, root, **kw):
    kw.setdefault("query", "Silver Lantern")
    kw.setdefault("campaigns", ["alpha"])
    return run_search(SearchRequest(**kw), manifest, root)


# ── attribution (FR-002, research D14) ───────────────────────────────────────


def test_chapter_comes_from_the_manifest_pattern(alpha) -> None:
    assert chapter_for(alpha, "docs/chapters/chapter_02_the_lantern.md") == 2
    assert chapter_for(alpha, "docs/chapters/chapter_01_arrival.md") == 1


def test_an_unnumbered_file_is_not_attributed(alpha) -> None:
    assert chapter_for(alpha, "docs/chapters/appendix_unnumbered.md") is None


def test_a_campaign_without_a_marker_attributes_nothing(beta) -> None:
    assert chapter_for(beta, "docs/chapters/chapter_09_whatever.md") is None


def test_attribution_never_reads_the_file(alpha, fixture_workspace) -> None:
    """The path is the whole input; the same name in any directory reads the same.

    A body regex would make attribution depend on prose a pipeline rewrites, and
    a chapter number that changes when `distill` runs is not a chapter number.
    """
    body_says_chapter_2 = (
        fixture_workspace / "alpha" / "docs" / "chapters" / "chapter_01_arrival.md"
    ).read_text(encoding="utf-8")
    assert "Chapter 1" in body_says_chapter_2
    assert chapter_for(alpha, "docs/chapters/chapter_01_arrival.md") == 1


def test_obelisks_session_pattern_attributes_correctly(live_manifest) -> None:
    """The case a shared chapter pattern would silently fail (research D2)."""
    if "obelisk" not in live_manifest.campaigns:
        pytest.skip("obelisk not enumerated in the live manifest")
    obelisk = live_manifest.campaigns["obelisk"]
    assert "session_" in obelisk.horizon.path_pattern
    assert chapter_for(obelisk, "docs/chapters/session_003_the_thing.md") == 3
    # And the pattern the other five use must NOT attribute here.
    assert chapter_for(obelisk, "docs/chapters/chapter_03_the_thing.md") is None


def test_the_other_campaigns_use_the_chapter_pattern(live_manifest) -> None:
    for name in ("Phandalin", "out-of-the-abyss", "stormgiants", "toee", "Hillsfar"):
        if name not in live_manifest.campaigns:
            continue
        campaign = live_manifest.campaigns[name]
        assert chapter_for(campaign, "docs/chapters/chapter_07_x.md") == 7


# ── filtering (FR-024, FR-012) ───────────────────────────────────────────────


def test_material_after_the_horizon_is_excluded(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, horizon=1)
    chapters = {h.chapter for h in response.hits if h.chapter is not None}
    assert chapters <= {1}


def test_the_excluded_count_is_reported(fixture_manifest, fixture_workspace) -> None:
    """FR-012: never a silently shortened list."""
    response = _search(fixture_manifest, fixture_workspace, horizon=1)
    assert response.suppressed_by_horizon >= 1


def test_without_a_horizon_the_later_material_is_present(
    fixture_manifest, fixture_workspace
) -> None:
    response = _search(fixture_manifest, fixture_workspace)
    assert any(h.chapter == 2 for h in response.hits)


def test_included_hits_say_they_were_included(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, horizon=2)
    attributed = [h for h in response.hits if h.chapter is not None]
    assert attributed and all(h.horizon_disposition == INCLUDED for h in attributed)


def test_no_horizon_means_no_disposition(fixture_manifest, fixture_workspace) -> None:
    """A third state: "nobody asked" is not the same as "asked, and it qualifies"."""
    response = _search(fixture_manifest, fixture_workspace)
    assert all(h.horizon_disposition is None for h in response.hits)


def test_unattributable_files_surface_rather_than_vanish(
    fixture_manifest, fixture_workspace
) -> None:
    response = _search(fixture_manifest, fixture_workspace, horizon=1)
    appendix = next(
        h for h in response.hits if h.path == "docs/chapters/appendix_unnumbered.md"
    )
    assert appendix.horizon_disposition == UNATTRIBUTABLE
    assert any("unattributable" in w for w in response.warnings)


def test_the_provenance_range_labels_authorship(fixture_manifest, fixture_workspace) -> None:
    """FR-026: both ranges are canon for plot and are not interchangeable for voice."""
    # "Greyfen" rather than the lantern: it is the one term both fixture
    # chapters mention, so a single query straddles the range boundary.
    response = _search(fixture_manifest, fixture_workspace, query="Greyfen")
    by_chapter = {h.chapter: h.provenance_range for h in response.hits if h.chapter}
    assert by_chapter[1] == "gm-written"
    assert by_chapter[2] == "ai-assisted"


def test_a_chapter_in_no_declared_range_gets_null(alpha) -> None:
    assert alpha.range_for(None) is None


def test_a_campaign_with_no_ranges_labels_nothing(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, campaigns=["beta"], query="Lantern")
    assert all(h.provenance_range is None for h in response.hits)


def test_live_out_of_the_abyss_labels_both_ranges(live_manifest) -> None:
    if "out-of-the-abyss" not in live_manifest.campaigns:
        pytest.skip("out-of-the-abyss not enumerated in the live manifest")
    oota = live_manifest.campaigns["out-of-the-abyss"]
    assert oota.range_for(10) == "gm-written"
    assert oota.range_for(40) == "ai-assisted"


# ── refusal (FR-025, T077) ───────────────────────────────────────────────────


def test_a_horizon_against_a_markerless_campaign_is_refused(
    fixture_workspace, capsys
) -> None:
    code = main(
        ["search", "Lantern", "--campaign", "beta", "--horizon", "1",
         "--campaigns-root", str(fixture_workspace)]
    )
    assert code == EXIT_REFUSED
    err = capsys.readouterr().err
    assert "records no horizon marker" in err
    assert "unfiltered" in err


def test_the_refusal_is_not_a_quiet_unfiltered_search(fixture_workspace, capsys) -> None:
    """Serving it unfiltered would answer a question about the past with the present."""
    assert main(
        ["search", "Lantern", "--campaign", "beta", "--horizon", "1",
         "--campaigns-root", str(fixture_workspace)]
    ) == EXIT_REFUSED
    assert "┌─" not in capsys.readouterr().out


def test_one_markerless_campaign_refuses_the_whole_query(fixture_workspace, capsys) -> None:
    """No partial service: a mixed scope must not quietly answer for half of it."""
    assert main(
        ["search", "Lantern", "--campaign", "alpha", "--campaign", "beta",
         "--horizon", "1", "--campaigns-root", str(fixture_workspace)]
    ) == EXIT_REFUSED


def test_live_campaigns_all_declare_a_horizon(live_manifest) -> None:
    """If one ever stops, the refusal above is what a caller will meet."""
    missing = [n for n, c in live_manifest.campaigns.items() if c.horizon is None]
    assert not missing, f"these campaigns would refuse every horizon query: {missing}"
