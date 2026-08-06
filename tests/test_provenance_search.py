"""SC-001: every hit carries the complete envelope. Plus ranking and counters.

The central assertion here is **structural, not spot-checked**. SC-001 says
"zero hits with a missing required field," which is a statement about the *key
set* of every hit — so this file compares key sets for equality rather than
poking at a handful of fields and hoping the rest came along. A field that
quietly stops being emitted is exactly the kind of regression a spot check
misses and a caller then misreads as "nothing to report here."

The second theme is that **suppression is never silent** (FR-011, FR-012,
SC-005). A filter that removes everything must return an empty hit list *with
counts*, because "I found nothing" and "I found twelve things and hid them all
from you" justify opposite next actions.
"""

from __future__ import annotations

import pytest

from provenance.envelope import ENVELOPE_FIELDS
from provenance.search import SearchRequest, run_search
from provenance.tiers import TrustTier


def _request(**kw) -> SearchRequest:
    kw.setdefault("query", "Silver Lantern")
    kw.setdefault("campaigns", ["alpha"])
    return SearchRequest(**kw)


@pytest.fixture()
def alpha_hits(fixture_manifest, fixture_workspace):
    return run_search(_request(), fixture_manifest, fixture_workspace)


# ── SC-001: the envelope is complete on every hit ────────────────────────────


def test_the_envelope_has_exactly_the_documented_fields() -> None:
    """data-model.md section 6 lists 18 fields. Drift in either direction fails."""
    assert ENVELOPE_FIELDS == frozenset(
        {
            "campaign",
            "path",
            "line",
            "excerpt",
            "excerpt_encoding",
            "context_before",
            "context_after",
            "tier",
            "tier_ambiguous",
            "generated_by",
            "generated_but_hand_edited",
            "chapter",
            "provenance_range",
            "corrections",
            "corrections_status",
            "matched_surface_form",
            "relevance",
            "horizon_disposition",
        }
    )


def test_every_hit_carries_every_field(alpha_hits) -> None:
    assert alpha_hits.hits, "fixture search returned nothing; the assertion would be vacuous"
    for hit in alpha_hits.hits:
        assert set(hit.as_dict()) == set(ENVELOPE_FIELDS), hit.path


def test_a_field_with_nothing_to_say_is_null_not_absent(alpha_hits) -> None:
    """The unclassified fixture file has no chapter, no range, no generator.

    All three still appear as keys. An omitted key reads as "not applicable";
    a null with a sibling status field reads as "asked, and the answer is none."
    """
    loose = next(h for h in alpha_hits.hits if h.path == "misc/loose_note.md")
    payload = loose.as_dict()
    assert payload["chapter"] is None
    assert payload["provenance_range"] is None
    assert payload["generated_by"] is None
    assert "chapter" in payload and "provenance_range" in payload and "generated_by" in payload


def test_json_payload_is_serialisable(alpha_hits) -> None:
    import json

    json.dumps(alpha_hits.as_dict())  # raises if an enum or Path leaked through


# ── labeling ─────────────────────────────────────────────────────────────────


def test_tiers_are_assigned_from_the_manifest_globs(alpha_hits) -> None:
    by_path = {h.path: h for h in alpha_hits.hits}
    assert by_path["docs/chapters/chapter_02_the_lantern.md"].tier is TrustTier.AUTHORITATIVE
    assert by_path["docs/distill_extractions/ch01_facts.md"].tier is TrustTier.SEARCH_ACCELERATOR
    assert by_path["docs/world_state.md"].tier is TrustTier.WORKING_REFERENCE
    assert by_path["notes/scratch.md"].tier is TrustTier.STAGING
    assert by_path["misc/loose_note.md"].tier is TrustTier.UNCLASSIFIED


def test_unclassified_is_returned_not_dropped(alpha_hits) -> None:
    """FR-013. Dropping it would be the silent narrowing this feature exists to kill."""
    assert any(h.tier is TrustTier.UNCLASSIFIED for h in alpha_hits.hits)


def test_tier_ambiguity_rides_on_the_hit(alpha_hits) -> None:
    """alpha's `docs/**/*.md` deliberately overlaps the authoritative glob (D8)."""
    chapter = next(
        h for h in alpha_hits.hits if h.path == "docs/chapters/chapter_02_the_lantern.md"
    )
    assert TrustTier.WORKING_REFERENCE in chapter.tier_ambiguous


def test_generated_by_is_the_manifest_declaration(alpha_hits) -> None:
    world = next(h for h in alpha_hits.hits if h.path == "docs/world_state.md")
    assert world.generated_by == "distill"


def test_generated_but_hand_edited_flags_a_corrected_generated_file(
    fixture_manifest, fixture_workspace
) -> None:
    """The live shape of toee/docs/npcs/calmer.md, reproduced in the fixture."""
    response = run_search(
        _request(query="Marnix"), fixture_manifest, fixture_workspace
    )
    keeper = next(h for h in response.hits if h.path == "docs/npcs/keeper.md")
    assert keeper.generated_by == "planning"
    assert keeper.generated_but_hand_edited is True


def test_corrections_attach_inline(fixture_manifest, fixture_workspace) -> None:
    response = run_search(_request(), fixture_manifest, fixture_workspace)
    world = next(h for h in response.hits if h.path == "docs/world_state.md")
    assert [c.id for c in world.corrections] == ["silver-lantern-recovered"]


def test_chapter_comes_from_the_path_pattern(alpha_hits) -> None:
    by_path = {h.path: h for h in alpha_hits.hits}
    assert by_path["docs/chapters/chapter_02_the_lantern.md"].chapter == 2
    # Matches the authoritative glob, carries no chapter number the pattern reads.
    assert by_path["docs/chapters/appendix_unnumbered.md"].chapter is None


def test_provenance_range_is_labeled_never_guessed(alpha_hits) -> None:
    by_path = {h.path: h for h in alpha_hits.hits}
    assert by_path["docs/chapters/chapter_02_the_lantern.md"].provenance_range == "ai-assisted"
    assert by_path["misc/loose_note.md"].provenance_range is None


# ── ranking (FR-010, D9) ─────────────────────────────────────────────────────


def test_ranking_is_a_total_order(alpha_hits) -> None:
    keys = [h.sort_key for h in alpha_hits.hits]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys), "two hits share a sort key; the order is not total"


def test_tier_breaks_relevance_ties(alpha_hits) -> None:
    """FR-010: at equal relevance the more trusted tier ranks first."""
    from itertools import groupby

    for _, group in groupby(alpha_hits.hits, key=lambda h: h.relevance):
        ordinals = [h.tier.ordinal for h in group]
        assert ordinals == sorted(ordinals)


def test_ranking_is_stable_across_runs(fixture_manifest, fixture_workspace) -> None:
    """rg is multithreaded; without the (campaign, path, line) tail this flaps."""
    first = run_search(_request(), fixture_manifest, fixture_workspace)
    second = run_search(_request(), fixture_manifest, fixture_workspace)
    assert [h.sort_key for h in first.hits] == [h.sort_key for h in second.hits]


# ── suppression is never silent ──────────────────────────────────────────────


def test_tier_filter_reports_what_it_removed(fixture_manifest, fixture_workspace) -> None:
    response = run_search(
        _request(tiers=[TrustTier.AUTHORITATIVE]), fixture_manifest, fixture_workspace
    )
    assert all(h.tier is TrustTier.AUTHORITATIVE for h in response.hits)
    assert sum(response.suppressed_by_tier.values()) > 0
    assert response.suppressed_by_tier[TrustTier.STAGING.value] == 1


def test_a_filter_that_removes_everything_still_reports_counts(
    fixture_manifest, fixture_workspace
) -> None:
    """SC-005. `hits: []` alone is indistinguishable from "found nothing"."""
    response = run_search(
        _request(query="cursed", tiers=[TrustTier.AUTHORITATIVE]),
        fixture_manifest,
        fixture_workspace,
    )
    assert response.hits == []
    assert response.total_matched == 1
    assert response.suppressed_by_tier[TrustTier.STAGING.value] == 1


def test_total_matched_counts_before_any_filter(alpha_hits) -> None:
    assert alpha_hits.total_matched == len(alpha_hits.hits)


def test_truncation_is_reported(fixture_manifest, fixture_workspace) -> None:
    response = run_search(_request(limit=2), fixture_manifest, fixture_workspace)
    assert len(response.hits) == 2
    assert response.truncated_by_limit == response.total_matched - 2


def test_suppressed_by_exclude_is_always_present(alpha_hits) -> None:
    """D17 made `exclude` the single scope authority, so it is counted like the rest."""
    assert isinstance(alpha_hits.suppressed_by_exclude, int)


def test_an_added_exclude_glob_shows_up_in_the_count(
    fixture_manifest, fixture_workspace
) -> None:
    campaign = fixture_manifest.campaigns["alpha"]
    original = list(campaign.exclude)
    try:
        campaign.exclude = original + ["notes/**"]
        response = run_search(_request(), fixture_manifest, fixture_workspace)
        assert response.suppressed_by_exclude == 1
        assert not any(h.path.startswith("notes/") for h in response.hits)
    finally:
        campaign.exclude = original


# ── response metadata ────────────────────────────────────────────────────────


def test_campaigns_searched_echoes_the_resolved_scope(alpha_hits) -> None:
    assert alpha_hits.campaigns_searched == ["alpha"]


def test_backends_consulted_is_populated(alpha_hits) -> None:
    """FR-022: a result set is never implicitly complete."""
    names = {b.name for b in alpha_hits.backends_consulted}
    assert "literal" in names


def test_elapsed_ms_is_reported(alpha_hits) -> None:
    assert alpha_hits.elapsed_ms >= 0
