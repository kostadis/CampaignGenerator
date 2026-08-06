"""SC-002 over the four corrections-backed incidents.

**These assert labeling, not stale text.** SC-002's own wording is that "the
misleading source is labeled such that a reviewer identifies it as stale
*without opening the file*" — which is a claim about the envelope, not about the
file's contents. That distinction is not pedantry: incident 1's stale sentence
was regenerated away between the spec being written and 2026-08-05 (research
D12). A test asserting the stale string would now be red for a reason that has
nothing to do with whether the feature works.

Each incident therefore gets two halves:

- a **pinned fixture** assertion that proves the mechanism where nothing drifts;
- a **live-corpus** assertion limited to what is stable — that the envelope
  carries the label — skipped when `~/src/campaigns` is absent.

**Incident 5 is deliberately not here.** It is an identity problem, not a
corrections one, and its coverage lives in `test_provenance_identity.py`
(T051/T052). Filing it here would have made this file look complete while
testing the wrong mechanism.
"""

from __future__ import annotations

import pytest

from provenance.corrections import CorrectionsStatus
from provenance.search import SearchRequest, run_search
from provenance.tiers import TrustTier


def _search(manifest, root, query, campaign, **kw):
    return run_search(
        SearchRequest(query=query, campaigns=[campaign], **kw), manifest, root
    )


def _hit(response, path):
    return next((h for h in response.hits if h.path == path), None)


# ── incident 1: a generated doc read as canon (Phandalin / Woodland Manse) ───


def test_incident_1_mechanism_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    """The generated file is labeled generated AND carries its correction inline."""
    response = _search(fixture_manifest, fixture_workspace, "Silver Lantern", "alpha")
    hit = _hit(response, "docs/world_state.md")

    assert hit.generated_by == "distill"
    assert hit.tier is TrustTier.WORKING_REFERENCE
    assert hit.corrections_status is CorrectionsStatus.CONSULTED
    assert "silver-lantern-recovered" in {c.id for c in hit.corrections}


def test_incident_1_correction_attaches_though_the_stale_text_is_gone(
    fixture_manifest, fixture_workspace
) -> None:
    """The load-bearing assertion of the whole feature (research D12).

    `chapter_02_the_lantern.md` states the *corrected* fact — the lantern was
    recovered. A tool that matched corrections by looking for `stale_claim` in
    the text would not attach anything to `docs/world_state.md` once that file
    is regenerated. Path-and-subject matching keeps it attached until a human
    prunes it.
    """
    record = fixture_manifest.campaigns["alpha"]
    response = _search(fixture_manifest, fixture_workspace, "Silver Lantern", "alpha")
    hit = _hit(response, "docs/world_state.md")

    correction = next(c for c in hit.corrections if c.id == "silver-lantern-recovered")
    assert correction.stale_claim.strip() not in hit.excerpt
    assert record.corrections == "docs/corrections.yaml"


def test_incident_1_authoritative_outranks_the_generated_doc(
    fixture_manifest, fixture_workspace
) -> None:
    """Story 1's independent test: chapter material ranks above world_state."""
    response = _search(fixture_manifest, fixture_workspace, "Silver Lantern", "alpha")
    order = [h.path for h in response.hits]
    assert order.index("docs/chapters/chapter_02_the_lantern.md") < order.index(
        "docs/world_state.md"
    )


def test_incident_1_envelope_on_the_live_corpus(live_manifest, live_workspace) -> None:
    if "Phandalin" not in live_manifest.campaigns:
        pytest.skip("Phandalin not enumerated in the live manifest")
    response = _search(live_manifest, live_workspace, "Woodland Manse", "Phandalin", limit=200)
    hit = _hit(response, "docs/world_state.md")
    if hit is None:
        pytest.skip("no hit in docs/world_state.md today; the corpus is regenerated often")

    assert hit.generated_by, "a generated grounding doc must be labeled as such"
    assert "woodland-manse-empty" in {c.id for c in hit.corrections}


# ── incident 2: generated AND hand-edited afterwards (toee / Calmer) ─────────


def test_incident_2_mechanism_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, "Marnix", "alpha")
    hit = _hit(response, "docs/npcs/keeper.md")

    assert hit.generated_by == "planning"
    assert hit.generated_but_hand_edited is True, (
        "the hand-written banner will be clobbered on the next run; that is the warning"
    )
    assert "keeper-still-alive" in {c.id for c in hit.corrections}


def test_incident_2_hand_editing_does_not_re_tier_the_file(
    fixture_manifest, fixture_workspace
) -> None:
    """The manifest's declaration governs; a hand edit is a warning, not a promotion."""
    response = _search(fixture_manifest, fixture_workspace, "Marnix", "alpha")
    hit = _hit(response, "docs/npcs/keeper.md")
    assert hit.tier is TrustTier.WORKING_REFERENCE


def test_incident_2_on_the_live_corpus(live_manifest, live_workspace) -> None:
    if "toee" not in live_manifest.campaigns:
        pytest.skip("toee not enumerated in the live manifest")
    # The phrase, not the bare name, and the choice is load-bearing twice over.
    #
    # Ranking: "Calmer" alone appears ~1,500 times in `docs/ensemble/merged.json`
    # and ~600 in `docs/toee-summary.md`. Relevance is `matches-in-this-file +
    # bonuses` (research D9), so one file fills the whole page and the dossier
    # never surfaces — the formula behaving exactly as specified. See the ranking
    # note in `docs/cli/provenance_search.md`.
    #
    # Correction matching: this correction declares `subjects: [Calmer, Calmert]`,
    # so it attaches only to hits whose query or excerpt names one of them (D13).
    # The line below contains "Calmer", so the annotation is genuinely earned
    # rather than arranged for by the test.
    response = _search(
        live_manifest, live_workspace, "Calmer is a PC", "toee", limit=50
    )
    hit = _hit(response, "docs/npcs/calmer.md")
    if hit is None:
        pytest.skip("the dossier's STALE banner has changed wording")

    assert "calmer-alive-undercover" in {c.id for c in hit.corrections}


def test_incident_2_exposes_a_gap_in_toees_ratified_manifest(
    live_manifest, live_workspace
) -> None:
    """The corpus's best generated-and-hand-edited file is not declared generated.

    toee's manifest block declares `docs/world_state.md`, `docs/campaign_state.md`
    and `docs/party.md` as generated, and tiers `docs/*.md` — but says nothing
    about `docs/npcs/`. Phandalin and stormgiants both declare
    `docs/npcs/*.md` generated by `planning --build-dossiers`; toee's 104
    dossiers, written by the same command, come back `unclassified` with
    `generated_by: null`.

    The correction still reaches the reader — it matches on path — so the hit is
    labeled KNOWN STALE either way. What is missing is the *other* warning: that
    the next `planning --build-dossiers` run will destroy the hand-written banner
    at the top of that file.

    `provenance check --campaign toee` already reports this as
    `unclassified-heavy: docs/npcs/ — 104/104`. Closing it is two globs in
    `~/src/campaigns/provenance.yaml` and it is the GM's call, not this feature's
    (FR-029, FR-031). This test pins the gap so it stays visible, and it will
    fail — correctly — the day someone closes it.
    """
    if "toee" not in live_manifest.campaigns:
        pytest.skip("toee not enumerated in the live manifest")
    toee = live_manifest.campaigns["toee"]

    assert toee.generated_by("docs/npcs/calmer.md") is None, (
        "toee now declares docs/npcs/ generated — good. Update this test and "
        "restore the generated_by/generated_but_hand_edited assertions above."
    )
    # The comparison that makes it a gap rather than a preference:
    for name in ("Phandalin", "stormgiants"):
        if name in live_manifest.campaigns:
            assert (
                live_manifest.campaigns[name].generated_by("docs/npcs/anyone.md")
                == "planning"
            )


# ── incident 3: the unreproducible one (toee / species swap) ────────────────


def test_incident_3_surfaces_as_unsettled_on_the_fixture(
    fixture_manifest, fixture_workspace
) -> None:
    """A correction that could not be reproduced is labeled, not published as fact."""
    response = _search(fixture_manifest, fixture_workspace, "Torvald", "alpha")
    hit = _hit(response, "docs/world_state.md")

    unverified = [c for c in hit.corrections if not c.verified]
    assert [c.id for c in unverified] == ["torvald-death-unconfirmed"]
    assert unverified[0].note, "verified: false without evidence is just an assertion"


def test_incident_3_on_the_live_corpus(live_manifest, live_workspace) -> None:
    if "toee" not in live_manifest.campaigns:
        pytest.skip("toee not enumerated in the live manifest")
    from provenance.corrections import consult

    campaign = live_manifest.campaigns["toee"]
    lookup = consult(campaign, live_workspace / campaign.root)
    assert lookup.status is CorrectionsStatus.CONSULTED
    unverified = {c.id for c in lookup.record.unverified}
    assert "sequioa-zephyr-species-swap" in unverified, (
        "the species swap is not reproducible on disk; it must ship verified: false "
        "rather than as a settled fact"
    )


# ── incident 4: the naming authority is not the generated doc (obelisk) ─────


def test_incident_4_mechanism_on_the_fixture(fixture_manifest, fixture_workspace) -> None:
    """A hand-curated reference and a generated doc are distinguishable at a glance."""
    response = _search(fixture_manifest, fixture_workspace, "Silver Lantern", "alpha")
    generated = _hit(response, "docs/world_state.md")
    curated = _hit(response, "docs/chapters/chapter_02_the_lantern.md")

    assert generated.generated_by is not None
    assert curated.generated_by is None
    assert curated.tier.ordinal < generated.tier.ordinal


def test_incident_4_on_the_live_corpus(live_manifest, live_workspace) -> None:
    if "obelisk" not in live_manifest.campaigns:
        pytest.skip("obelisk not enumerated in the live manifest")
    response = _search(live_manifest, live_workspace, "Foreput", "obelisk", limit=200)
    generated = [h for h in response.hits if h.generated_by]
    if not generated:
        pytest.skip("no generated-doc hit for this query today")
    for hit in generated:
        assert hit.corrections_status is CorrectionsStatus.CONSULTED


def test_incident_4_the_glossary_is_searchable_at_all(live_manifest, live_workspace) -> None:
    """The concrete defect: check_consistency never loads the glossary. Search does."""
    if "obelisk" not in live_manifest.campaigns:
        pytest.skip("obelisk not enumerated in the live manifest")
    glossary = live_workspace / "obelisk" / "docs" / "background" / "name_glossary.md"
    if not glossary.is_file():
        pytest.skip("name_glossary.md absent")

    response = _search(live_manifest, live_workspace, "Foreput", "obelisk", limit=200)
    hit = _hit(response, "docs/background/name_glossary.md")
    if hit is None:
        pytest.skip("the glossary holds no hit for this query today")
    assert hit.generated_by is None
    assert hit.tier is not TrustTier.UNCLASSIFIED
