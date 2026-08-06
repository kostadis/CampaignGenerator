"""Identity resolution: three states, never two, and never a guess.

**The three states carry different next actions.** `resolved` says use this
canonical form. `not-found` says the store exists and nobody has recorded this
link — go run `registry alias` if it should exist. `no-store` says there is
nothing to record against. Collapsing `not-found` into `no-store` would send a
GM looking for a registry that was never there; collapsing it the other way
would have them editing a file that does not exist (FR-017, FR-018, SC-006).

**Name similarity is never evidence (FR-016).** The last test in this file walks
the AST of `provenance/identity.py` looking for a string-distance function, and
that guard exists because the temptation is real: `Vera` and `Veyra` are one
letter apart, the corpus has a `characters/veyra.md`, and a fuzzy matcher would
"work" on the demo and be wrong forever after. Near-duplicate surfacing is
`registry check`'s separate, human-gated job.

Contract tests run against **pinned** fixture registries; live-corpus tests
assert only what is true on disk today (research D10, D11).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from provenance.identity import (
    ConfusionKind,
    IdentityStatus,
    expansion_forms,
    resolve,
)
from provenance.search import SearchRequest, run_search

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE = REPO_ROOT / "provenance" / "identity.py"


@pytest.fixture()
def alpha_root(fixture_workspace: Path) -> Path:
    return fixture_workspace / "alpha"


@pytest.fixture()
def beta_root(fixture_workspace: Path) -> Path:
    return fixture_workspace / "beta"


# ── the three states ─────────────────────────────────────────────────────────


def test_a_recorded_alias_resolves(alpha, alpha_root) -> None:
    result = resolve(alpha, alpha_root, "Marnix")
    assert result.status is IdentityStatus.RESOLVED
    assert result.canonical == "Marnix Vale"
    assert result.type == "npc"
    assert "The Keeper" in result.aliases


def test_an_unrecorded_name_is_not_found(alpha, alpha_root) -> None:
    result = resolve(alpha, alpha_root, "Nobody At All")
    assert result.status is IdentityStatus.NOT_FOUND
    assert result.canonical is None
    assert result.reason and "not a claim that no such entity exists" in result.reason.lower()


def test_a_campaign_without_a_store_says_so(beta, beta_root) -> None:
    result = resolve(beta, beta_root, "Anyone")
    assert result.status is IdentityStatus.NO_STORE
    assert result.canonical is None


def test_not_found_and_no_store_are_never_collapsed(alpha, alpha_root, beta, beta_root) -> None:
    """SC-006. Two different answers to two different questions."""
    missing = resolve(alpha, alpha_root, "Nobody At All")
    absent = resolve(beta, beta_root, "Nobody At All")
    assert missing.status is not absent.status
    assert missing.as_dict()["status"] != absent.as_dict()["status"]


def test_a_declared_but_missing_store_is_a_machine_problem(alpha, tmp_path) -> None:
    """Not "the entity is unknown" — nothing was consulted at all."""
    result = resolve(alpha, tmp_path, "Marnix")
    assert result.status is IdentityStatus.NO_STORE
    assert "no such file exists on this machine" in result.reason


def test_case_differences_are_the_same_string(alpha, alpha_root) -> None:
    """Casefolding is not similarity matching; it is one string written two ways."""
    assert resolve(alpha, alpha_root, "marnix").canonical == "Marnix Vale"


# ── spec Story 2's acceptance criteria, on pinned fixtures (T051) ────────────


def test_story2_as1_vera_resolves_to_veyra(alpha, alpha_root) -> None:
    """Given on the live corpus is FALSE today; the mechanism is proven here."""
    result = resolve(alpha, alpha_root, "Vera")
    assert result.status is IdentityStatus.RESOLVED
    assert result.canonical == "Veyra"


def test_story2_as2_short_form_resolves_with_a_non_identity_note(alpha, alpha_root) -> None:
    result = resolve(alpha, alpha_root, "KP")
    assert result.canonical == "Kazneporium Ketternopappux"

    kinds = {c.kind for c in result.known_confusions}
    assert ConfusionKind.DISTINCT in kinds or ConfusionKind.REJECTED_ALIAS in kinds
    names = {n for c in result.known_confusions for n in c.names}
    assert "Kostadinious the Sage" in names


def test_the_two_confusion_kinds_stay_distinct(alpha, alpha_root) -> None:
    """`distinct:` and `rejected_aliases:` mean different things (FR-015)."""
    result = resolve(alpha, alpha_root, "Torvin")
    assert [c.kind for c in result.known_confusions] == [ConfusionKind.DISTINCT]

    marnix = resolve(alpha, alpha_root, "Marnix")
    assert ConfusionKind.REJECTED_ALIAS in {c.kind for c in marnix.known_confusions}


def test_known_wrong_variants_reports_the_schema_gap(alpha, alpha_root) -> None:
    """FR-014 asks for a field the registry does not have. Say so, don't fake it."""
    result = resolve(alpha, alpha_root, "Marnix")
    assert result.known_wrong_variants["status"] == "not-recorded-by-schema"
    assert "FR-016" in result.known_wrong_variants["explanation"]


def test_an_empty_alias_list_is_not_read_as_no_confusions(alpha, alpha_root) -> None:
    """Silver Lantern has an alias and no confusions; both are stated, not implied."""
    result = resolve(alpha, alpha_root, "The Lantern")
    assert result.canonical == "Silver Lantern"
    assert result.known_confusions == ()
    assert result.known_wrong_variants["status"] == "not-recorded-by-schema"


# ── alias expansion (FR-019) ─────────────────────────────────────────────────


def test_expansion_covers_canonical_and_aliases(alpha, alpha_root) -> None:
    forms = expansion_forms(alpha, alpha_root, "Marnix")
    assert set(forms) >= {"Marnix", "Marnix Vale", "The Keeper"}


def test_expansion_without_a_store_returns_the_surface_form(beta, beta_root) -> None:
    assert expansion_forms(beta, beta_root, "Anyone") == ("Anyone",)


def test_expanded_search_labels_the_form_that_matched(
    fixture_manifest, fixture_workspace
) -> None:
    response = run_search(
        SearchRequest(query="Marnix", campaigns=["alpha"], expand_aliases=True),
        fixture_manifest,
        fixture_workspace,
    )
    forms = {h.matched_surface_form for h in response.hits}
    assert forms - {"Marnix"}, "expansion found nothing the bare form would not have"
    assert all(h.matched_surface_form for h in response.hits)


def test_expanded_hits_are_deduped_on_position(fixture_manifest, fixture_workspace) -> None:
    response = run_search(
        SearchRequest(query="Marnix", campaigns=["alpha"], expand_aliases=True),
        fixture_manifest,
        fixture_workspace,
    )
    positions = [(h.campaign, h.path, h.line) for h in response.hits]
    assert len(positions) == len(set(positions))


def test_dedup_keeps_the_longest_matched_form(fixture_manifest, fixture_workspace) -> None:
    """A hit found by both "Marnix" and "Marnix Vale" is labeled with the specific one."""
    response = run_search(
        SearchRequest(query="Marnix", campaigns=["alpha"], expand_aliases=True),
        fixture_manifest,
        fixture_workspace,
    )
    keeper = next(h for h in response.hits if h.path == "docs/npcs/keeper.md" and h.line == 1)
    assert keeper.matched_surface_form == "Marnix Vale"


# ── FR-016 as a property of the code, not of the wording (T053) ─────────────


FUZZY_NAMES = {
    "get_close_matches",
    "SequenceMatcher",
    "ratio",
    "partial_ratio",
    "token_sort_ratio",
    "levenshtein",
    "damerau_levenshtein",
    "jaro",
    "jaro_winkler",
    "edit_distance",
    "fuzz",
    "difflib",
    "rapidfuzz",
    "Levenshtein",
    "ndiff",
}


def test_no_string_distance_asserts_identity() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FUZZY_NAMES:
            offenders.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in FUZZY_NAMES:
            offenders.append(f".{node.attr}")
        elif isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name in FUZZY_NAMES]
        elif isinstance(node, ast.ImportFrom) and (node.module or "") in FUZZY_NAMES:
            offenders.append(node.module)
    assert not offenders, (
        f"identity.py references a string-distance name {sorted(set(offenders))}. "
        "FR-016: name similarity is never evidence of identity. Near-duplicate "
        "surfacing belongs to `registry check`, behind a human."
    )


def test_the_fuzzy_guard_is_not_vacuous() -> None:
    assert MODULE.is_file() and MODULE.read_text(encoding="utf-8").strip()


# ── live corpus (T052) ───────────────────────────────────────────────────────


def _campaign(manifest, workspace, name):
    if name not in manifest.campaigns:
        pytest.skip(f"{name} not enumerated in the live manifest")
    campaign = manifest.campaigns[name]
    root = workspace / campaign.root
    if not root.is_dir():
        pytest.skip(f"{name} root absent on this machine")
    return campaign, root


@pytest.mark.parametrize(
    "campaign_name,pair",
    [
        ("out-of-the-abyss", ("Topsy", "Turvy")),
        ("toee", ("Barkinar", "Deggum")),
        ("Phandalin", ("Meril's Staff", "Staff of Birdcalls")),
    ],
)
def test_live_distinct_pairs_are_reported_as_non_identity(
    live_manifest, live_workspace, campaign_name, pair
) -> None:
    campaign, root = _campaign(live_manifest, live_workspace, campaign_name)
    result = resolve(campaign, root, pair[0])
    if result.status is not IdentityStatus.RESOLVED:
        pytest.skip(f"{pair[0]} not registered in {campaign_name} today")
    names = {n.casefold() for c in result.known_confusions for n in c.names}
    assert pair[1].casefold() in names


@pytest.mark.parametrize(
    "campaign_name,pair",
    [("Phandalin", ("Corbin", "Corwin")), ("out-of-the-abyss", ("Shoor Vandree", "Stool"))],
)
def test_live_rejected_aliases_are_reported_as_refused_links(
    live_manifest, live_workspace, campaign_name, pair
) -> None:
    campaign, root = _campaign(live_manifest, live_workspace, campaign_name)
    result = resolve(campaign, root, pair[0])
    confusions = result.known_confusions
    if not confusions:
        pytest.skip(f"no confusion recorded for {pair[0]} in {campaign_name} today")
    names = {n.casefold() for c in confusions for n in c.names}
    assert pair[1].casefold() in names


def test_live_vera_now_resolves_to_veyra(live_manifest, live_workspace) -> None:
    """Spec Story 2 AS-1, now true on the live corpus (T098, 2026-08-06).

    Until the GM ran `registry add obelisk --name Veyra --aliases Vera`, this
    asserted the honest `not-found` — Veyra was real on disk
    (`obelisk/characters/veyra.md`, and named in `docs/background/name_glossary.md`)
    but no alias link was recorded, so FR-018 required saying so rather than
    guessing from the one-letter difference.

    What made the link enterable was *evidence*, not similarity: the GM's own
    `notes/vtt_transcription_corrections.md` already listed Vera → Veyra, and
    `docs/world_state.md` records the same correction. FR-016 is unchanged —
    nothing here resolved the name because it looked close.
    """
    campaign, root = _campaign(live_manifest, live_workspace, "obelisk")
    result = resolve(campaign, root, "Vera")
    assert result.status is IdentityStatus.RESOLVED
    assert result.canonical == "Veyra"


def test_live_kp_resolves_to_the_full_name_and_is_distinct_from_the_biographer(
    live_manifest, live_workspace
) -> None:
    """Spec Story 2 AS-2, now true on the live corpus (T099, 2026-08-06).

    The defect this closes is documented in
    `Phandalin/notes/corrections/kp_identity_attribution.md`: a source file named
    `KP post Barovia - Kostadinious the Sage.md` put the two strings adjacent, and
    LLMs read the filename as (alias — true name). Kostadinious is KP's in-world
    *biographer*. The registry now says so, so the confusion is recorded rather
    than re-derived every session.
    """
    campaign, root = _campaign(live_manifest, live_workspace, "Phandalin")
    result = resolve(campaign, root, "KP")
    assert result.status is IdentityStatus.RESOLVED
    assert result.canonical == "Kazneporium Ketternopappux"

    confusions = {
        n for c in result.known_confusions if c.kind is ConfusionKind.DISTINCT
        for n in c.names
    }
    assert "Kostadinious the Sage" in confusions

    # And the biographer is a real entity in his own right, not just a name in a
    # guard — so resolving him answers `resolved`, not `not-found`.
    other = resolve(campaign, root, "Kostadinious the Sage")
    assert other.status is IdentityStatus.RESOLVED
    assert other.canonical != result.canonical


def test_live_campaigns_without_a_store_say_no_store(live_manifest, live_workspace) -> None:
    for name in ("stormgiants", "Hillsfar"):
        campaign, root = _campaign(live_manifest, live_workspace, name)
        assert resolve(campaign, root, "Anyone").status is IdentityStatus.NO_STORE
