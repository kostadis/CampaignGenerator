from __future__ import annotations

import pytest

from pipelines.summary_native.authority import AuthorityError, load_ledger
from pipelines.summary_native.authority_inputs import resolve_selection
from pipelines.summary_native.freshness import (
    check_authority_cache_fresh,
    check_authority_output_fresh,
)


def _current_manifest() -> dict:
    return {
        "authority_schema": 1,
        "authority_policy": 1,
        "ledger_sha256": "a" * 64,
        "ledger_revision": 1,
        "records": [],
        "audience": "gm",
        "horizon": None,
        "range": None,
        "selection": None,
        "pending_transaction": None,
        "filtered_payload_sha256": "b" * 64,
    }


def test_summary_only_workspace_stays_valid_and_empty_configured_selection_refuses(tmp_path):
    # No ledger/authority manifest means an established summary-only workspace
    # remains usable.  Configuring authority notes is the opt-in boundary.
    assert load_ledger(tmp_path, required=False) is None
    assert check_authority_output_fresh({"inputs": {}}, None) is None
    with pytest.raises(AuthorityError, match="configured authority note selection is empty"):
        resolve_selection(tmp_path, [])


def test_legacy_authority_aware_runs_and_caches_refuse_with_regeneration_command():
    current = _current_manifest()
    legacy_manifest = {"ledger_sha256": "a" * 64, "records": []}
    run_problem = check_authority_output_fresh(
        {"inputs": {"authority_manifest": legacy_manifest}}, current,
    )
    cache_problem = check_authority_cache_fresh(
        {"authority_manifest": legacy_manifest}, current,
    )
    assert "retired authority manifest schema" in run_problem
    assert "summary_native synth" in run_problem and "--force" in run_problem
    assert "retired authority manifest schema" in cache_problem
    assert "summary_native extract" in cache_problem and "--force" in cache_problem


def test_unsupported_authority_version_refuses_without_lazy_migration_or_narrow_store_mutation(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    ledger = docs / "authority.yaml"
    original_ledger = b"version: 2\ncampaign: fixture\nrevision: 1\nrecords: []\nconflicts: []\n"
    ledger.write_bytes(original_ledger)
    narrow = {
        docs / "summary_native" / "canon.yaml": b"version: 1\nlinks: []\n",
        docs / "corrections.yaml": b"version: 1\ncorrections: []\n",
        tmp_path / "transcript_corrections.yaml": b"version: 1\ncorrections: []\n",
    }
    for path, contents in narrow.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    with pytest.raises(AuthorityError, match="invalid authority ledger"):
        load_ledger(tmp_path)

    assert ledger.read_bytes() == original_ledger
    assert {path: path.read_bytes() for path in narrow} == narrow
