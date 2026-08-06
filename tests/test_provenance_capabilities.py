"""SC-004: an unavailable backend is reported as unavailable, never as zero hits.

That indistinguishability is the whole of Story 3. A caller who gets nothing back
has to decide whether to widen the query or go install something, and those are
opposite actions. The tests here pin the distinction in both places it has to
hold: in ``capabilities``, and on every single ``SearchResponse`` (FR-022) — a
roster reported once at startup would go stale the moment a backend died.

The per-campaign table is the other half. The manifest is the *only* enumeration
of which campaigns exist (FR-023), so a caller who does not know the names has
exactly one place to look, and it has to say which of them are actually on this
machine.
"""

from __future__ import annotations

import json

import pytest

from provenance.backends import BackendStatus, roster, semantic_backend
from provenance.cli import EXIT_OK, main
from provenance.scan import select_scanner
from provenance.search import SearchRequest, run_search


@pytest.fixture()
def root(fixture_workspace) -> list[str]:
    return ["--campaigns-root", str(fixture_workspace)]


def _json(capsys, argv) -> dict:
    assert main(argv) == EXIT_OK
    return json.loads(capsys.readouterr().out)


# ── the backend roster (FR-020, FR-021) ──────────────────────────────────────


def test_every_backend_has_a_closed_status(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    allowed = {s.value for s in BackendStatus}
    assert payload["backends"], "an empty roster asserts nothing"
    for backend in payload["backends"]:
        assert backend["status"] in allowed


def test_an_unavailable_backend_carries_a_reason(root, capsys) -> None:
    """SC-004. "Unavailable" without a reason is not an answer a caller can act on."""
    payload = _json(capsys, ["capabilities", "--json", *root])
    for backend in payload["backends"]:
        if backend["status"] != BackendStatus.AVAILABLE.value:
            assert backend["reason"], backend["name"]


def test_the_semantic_backend_is_probed_not_assumed() -> None:
    """It must read `available` on a host that has MemPalace and not here."""
    backend = semantic_backend()
    assert backend.status in (
        BackendStatus.UNAVAILABLE,
        BackendStatus.NOT_WIRED,
        BackendStatus.AVAILABLE,
    )
    assert "not wired in increment 1" in backend.contributed


def test_an_unavailable_backend_is_never_reported_as_zero_hits(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    semantic = next(b for b in payload["backends"] if b["name"] == "semantic")
    assert semantic["status"] != BackendStatus.AVAILABLE.value
    assert "not-consulted" in semantic["contributed"]
    # And nothing anywhere claims it returned nothing.
    assert "0 hits" not in json.dumps(payload)


def test_the_literal_backend_names_its_implementation() -> None:
    """A ~60× latency swing that varies by host must be visible (research D1)."""
    impl = select_scanner(None)
    literal = next(b for b in roster(impl) if b.name == "literal")
    assert literal.status is BackendStatus.AVAILABLE
    assert literal.impl in ("rg", "python")
    assert literal.impl_version


def test_the_python_fallback_is_reported_as_available_too() -> None:
    literal = next(b for b in roster(select_scanner("python")) if b.name == "literal")
    assert literal.status is BackendStatus.AVAILABLE
    assert literal.impl == "python"


# ── every response repeats the roster (FR-022, T070) ────────────────────────


def test_every_search_response_carries_the_roster(fixture_manifest, fixture_workspace) -> None:
    """A result set is never implicitly complete."""
    for query in ("Silver Lantern", "nothing at all matches this"):
        response = run_search(
            SearchRequest(query=query, campaigns=["alpha"]), fixture_manifest, fixture_workspace
        )
        names = {b.name for b in response.backends_consulted}
        assert names == {"literal", "semantic"}


def test_an_empty_result_still_names_the_unconsulted_backend(
    fixture_manifest, fixture_workspace
) -> None:
    """The exact Story-3 shape: zero hits, and the caller can see why that may be."""
    response = run_search(
        SearchRequest(query="zzz-no-such-string-zzz", campaigns=["alpha"]),
        fixture_manifest,
        fixture_workspace,
    )
    assert response.hits == []
    semantic = next(b for b in response.backends_consulted if b.name == "semantic")
    assert semantic.status is not BackendStatus.AVAILABLE or "not-consulted" in (
        semantic.contributed
    )


def test_the_json_response_serialises_the_roster(
    fixture_manifest, fixture_workspace
) -> None:
    response = run_search(
        SearchRequest(query="Silver Lantern", campaigns=["alpha"]),
        fixture_manifest,
        fixture_workspace,
    )
    payload = json.loads(json.dumps(response.as_dict()))
    assert [b["name"] for b in payload["backends_consulted"]] == ["literal", "semantic"]


# ── the campaign table (FR-023) ──────────────────────────────────────────────


def test_every_campaign_is_enumerated_with_its_status(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    rows = {row["campaign"]: row for row in payload["campaigns"]}
    assert set(rows) == {"alpha", "beta"}
    for row in rows.values():
        for key in ("root", "manifest", "identity_store", "corrections", "horizon"):
            assert row[key], (row["campaign"], key)


def test_the_table_distinguishes_a_store_from_its_absence(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    rows = {row["campaign"]: row for row in payload["campaigns"]}
    assert rows["alpha"]["identity_store"] == "registry"
    assert rows["beta"]["identity_store"] == "NONE"


def test_the_table_distinguishes_no_corrections_record_from_an_empty_one(
    root, capsys
) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    rows = {row["campaign"]: row for row in payload["campaigns"]}
    assert "entries" in rows["alpha"]["corrections"]
    assert rows["beta"]["corrections"] == "none declared"


def test_unverified_corrections_are_visible_in_the_table(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    rows = {row["campaign"]: row for row in payload["campaigns"]}
    assert "unverified" in rows["alpha"]["corrections"]


def test_a_missing_root_is_reported_as_missing_not_as_empty(tmp_path, capsys) -> None:
    """A manifest is portable across machines; a corpus is not (Story 3)."""
    (tmp_path / "provenance.yaml").write_text(
        "version: 1\n"
        "campaigns:\n"
        "  ghost:\n"
        "    root: ghost\n"
        "    tiers: {authoritative: [], search_accelerator: [], "
        "working_reference: [], staging: []}\n"
        "    identity: {registry: null, aliases: null}\n",
        encoding="utf-8",
    )
    payload = _json(capsys, ["capabilities", "--json", "--campaigns-root", str(tmp_path)])
    assert payload["campaigns"][0]["root"] == "MISSING"


# ── discoverability of the root itself (Principle VIII) ─────────────────────


def test_capabilities_reports_which_rule_resolved_the_root(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    assert payload["resolved_from"] == "flag"
    assert payload["resolved_detail"]


def test_the_env_var_route_is_reported_as_such(fixture_workspace, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CAMPAIGNS_ROOT", str(fixture_workspace))
    payload = _json(capsys, ["capabilities", "--json"])
    assert payload["resolved_from"] == "env"


def test_capabilities_states_that_gitignore_does_not_scope(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    note = payload["gitignore_note"]
    assert "--no-ignore" in note and "230 files" in note


def test_capabilities_lists_the_scanners_it_could_use(root, capsys) -> None:
    payload = _json(capsys, ["capabilities", "--json", *root])
    assert "python" in payload["scanners_available"]
