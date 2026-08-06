"""US5: cross-campaign search is reached by naming N≥2 campaigns, and never merges.

Two rules, and they pull in opposite directions on purpose.

**Reachable.** A GM who wants to compare two games can, in one call, by writing
both names. That is the deliberate act Constitution X permits.

**Never implicit, and never merged.** Omitting scope does not fall through to
"all six" (SC-003), and two campaigns holding an entity with the same name keep
them apart. Beta's Silver Lantern is a different object in a different game; a
tool that de-duplicated them would be asserting an identity nobody recorded —
the same defect FR-016 forbids within a campaign, committed across two.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from provenance.cli import EXIT_REFUSED, main
from provenance.search import SearchRequest, ScopeError, run_search

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG = REPO_ROOT / "provenance"


def _search(manifest, root, campaigns, query="Silver Lantern", **kw):
    return run_search(
        SearchRequest(query=query, campaigns=campaigns, **kw), manifest, root
    )


# ── both campaigns answer, and both stay labeled ─────────────────────────────


def test_hits_come_back_from_each_named_campaign(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    assert {h.campaign for h in response.hits} == {"alpha", "beta"}


def test_every_hit_names_its_owning_campaign(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    assert all(h.campaign in ("alpha", "beta") for h in response.hits)
    assert all(h.campaign for h in response.hits)


def test_campaigns_searched_echoes_the_scope(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, ["beta", "alpha"])
    assert response.campaigns_searched == ["beta", "alpha"]


def test_the_same_name_in_two_games_is_never_merged(
    fixture_manifest, fixture_workspace
) -> None:
    """The fixture says it out loud: beta's lantern is a DIFFERENT object."""
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    alpha_hits = [h for h in response.hits if h.campaign == "alpha"]
    beta_hits = [h for h in response.hits if h.campaign == "beta"]
    assert alpha_hits and beta_hits
    # Same path, different campaign, both present — a merge would collapse these.
    assert "docs/world_state.md" in {h.path for h in alpha_hits}
    assert "docs/world_state.md" in {h.path for h in beta_hits}


def test_identical_paths_in_two_campaigns_are_two_hits(
    fixture_manifest, fixture_workspace
) -> None:
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    same_path = [h for h in response.hits if h.path == "docs/world_state.md"]
    assert len(same_path) == 2
    assert {h.campaign for h in same_path} == {"alpha", "beta"}


def test_nothing_is_deduplicated_across_campaigns(
    fixture_manifest, fixture_workspace
) -> None:
    """Two single-campaign searches and one two-campaign search agree on the count."""
    alpha = _search(fixture_manifest, fixture_workspace, ["alpha"], limit=0)
    beta = _search(fixture_manifest, fixture_workspace, ["beta"], limit=0)
    both = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"], limit=0)
    assert both.total_matched == alpha.total_matched + beta.total_matched


def test_ordering_stays_total_across_campaigns(fixture_manifest, fixture_workspace) -> None:
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    keys = [h.sort_key for h in response.hits]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_a_per_campaign_correction_does_not_leak_sideways(
    fixture_manifest, fixture_workspace
) -> None:
    """beta declares no corrections record; alpha's must not attach to beta's hits."""
    response = _search(fixture_manifest, fixture_workspace, ["alpha", "beta"])
    for hit in response.hits:
        if hit.campaign == "beta":
            assert hit.corrections is None


# ── and it is still never implicit (SC-003 at multi-campaign scope, T085) ───


def test_omitting_scope_is_still_refused(fixture_workspace, capsys) -> None:
    assert main(
        ["search", "Silver Lantern", "--campaigns-root", str(fixture_workspace)]
    ) == EXIT_REFUSED
    assert "no implicit" in capsys.readouterr().err


def test_an_empty_scope_list_is_refused_at_the_engine(
    fixture_manifest, fixture_workspace
) -> None:
    """Not only at the parser: the engine is reachable from the MCP seam too."""
    with pytest.raises(ScopeError):
        _search(fixture_manifest, fixture_workspace, [])


def test_an_unknown_campaign_in_a_multi_scope_refuses_the_whole_query(
    fixture_workspace, capsys
) -> None:
    assert main(
        ["search", "x", "--campaign", "alpha", "--campaign", "gamma",
         "--campaigns-root", str(fixture_workspace)]
    ) == EXIT_REFUSED


# ── no "all" token was introduced along the way (T088) ──────────────────────

#: Words that could only ever mean "everything". `*` is deliberately NOT here:
#: it is a glob metacharacter that appears legitimately all over `tiers.py` and
#: `scan.py`, and banning it package-wide would be a guard that fires on the
#: wrong thing. It is checked separately, in the three modules where a *scope*
#: could actually be expressed.
WILDCARD_WORDS = {"all", "ALL", "any", "every", "everything", "all-campaigns"}

#: The modules that can express a scope at all (T088).
SCOPE_MODULES = ("cli.py", "search.py", "provenance_mcp.py")


def _executable_strings(path: Path) -> list[str]:
    """String constants that are not docstrings.

    Docstrings are excluded because these modules discuss the absence of an
    "all" token at length, and no textual scan can tell the discussion from an
    implementation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


def test_no_wildcard_word_exists_anywhere_in_the_package() -> None:
    """Swept over the whole package, so a later phase cannot slip one in."""
    offenders = [
        (path.name, value)
        for path in sorted(PKG.glob("*.py"))
        for value in _executable_strings(path)
        if value in WILDCARD_WORDS
    ]
    assert not offenders, (
        f"a wildcard scope token appeared: {offenders}. Cross-campaign search is "
        "reached by naming N≥2 campaigns by hand, never by a magic word."
    )


def test_no_star_scope_token_in_the_scope_bearing_modules() -> None:
    offenders = [
        (name, value)
        for name in SCOPE_MODULES
        if (PKG / name).is_file()
        for value in _executable_strings(PKG / name)
        if value == "*"
    ]
    assert not offenders, f"a bare '*' appeared where a scope is expressed: {offenders}"


# ── live corpus ──────────────────────────────────────────────────────────────


def test_two_live_campaigns_return_separately_labeled_hits(
    live_manifest, live_workspace
) -> None:
    names = [n for n in ("obelisk", "Hillsfar") if n in live_manifest.campaigns]
    if len(names) < 2:
        pytest.skip("fewer than two of the small live campaigns are enumerated")
    for name in names:
        if not (live_workspace / live_manifest.campaigns[name].root).is_dir():
            pytest.skip(f"{name} root absent on this machine")

    response = _search(live_manifest, live_workspace, names, query="the party", limit=40)
    assert response.campaigns_searched == names
    assert all(h.campaign in names for h in response.hits)
