"""Tests for mcp_server.py — the MCP tool surface (rpg_search, propose_dossier)
and the refs.yaml scope resolution that wires into them (issue #114 step 4).

Strategy:

  * ``_resolve_campaign_scope`` is a pure function of a campaign directory —
    tested directly against ``tmp_path`` fixtures covering the three
    outcomes (missing refs.yaml, valid refs.yaml, malformed refs.yaml). The
    missing-refs.yaml case is the CRITICAL SAFETY PROPERTY the design plan
    calls out explicitly: ``resolve_refs.load_refs()`` raises ``SystemExit``
    when ``config/refs.yaml`` doesn't exist, and without the try/except in
    ``_resolve_campaign_scope`` that would crash the MCP server at import
    time for any campaign lacking one.

  * ``mcp_server`` resolves the module-level ``_campaign_scope`` exactly
    once, at IMPORT time, from whatever ``campaign_dir`` the process starts
    in. This test file's own module-level import below IS a live exercise
    of that import path: this worktree's root (this repo's ``campaign_dir``
    default, since no ``CAMPAIGN_DIR`` env var / ``--campaign-dir`` arg is
    set when pytest runs) has a ``config/`` directory but genuinely no
    ``config/refs.yaml`` — the exact "campaign lacking refs.yaml" scenario
    the plan worries about. If the import raised, collecting this file
    would have failed and no test below would have run at all.

  * ``@mcp.tool()``-decorated functions are plain callables (FastMCP does
    not wrap them at definition time) — tools are called directly here.
    Both ``rpg_search`` and ``propose_dossier`` do their real imports
    lazily, inside the function body, which is the monkeypatch seam: patch
    the attribute on the *imported-from* module
    (``pipelines.rlm.rpg_retriever`` / ``pipelines.rlm.dossier_proposer``)
    and the tool's next call picks up the patched version.

  * The ``full_library`` override gets one genuine end-to-end test (a real
    tmp 5etools data root with two sources) in addition to the kwarg-capture
    tests, so the override is proven to change actual retrieved content —
    not just proven to be forwarded. MemPalace is neutralized by
    monkeypatching ``rpg_retriever.MempalaceClient`` with an in-process
    ``FakeMempalaceClient`` factory (never spawns a subprocess, never hits
    the network); rpg-library HTTP access is neutralized the same way
    ``retrieve_scoped`` already soft-fails when no URL is configured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import pipelines.rlm.dossier_proposer as dossier_proposer_module
import pipelines.rlm.mcp_server as mcp_server
import pipelines.rlm.resolve_refs as rr
import pipelines.rlm.rpg_retriever as rpg_retriever_module
from pipelines.rlm.mempalace_client import FakeMempalaceClient


# ── Shared fixtures: minimal 5etools tree + refs.yaml builders ────────────
#
# Same shape as tests/test_resolve_refs.py's fixtures. Duplicated here
# rather than imported — this repo's test files don't cross-import (each
# test module is self-contained; see tests/test_resolve_refs.py for the
# original).


def _fake_5etools_tree(root: Path, sources: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "adventures.json").write_text(
        json.dumps({"adventure": [{"id": s, "name": s} for s in sources]}),
        encoding="utf-8",
    )
    (root / "books.json").write_text(json.dumps({"book": []}), encoding="utf-8")
    (root / "bestiary").mkdir()
    (root / "bestiary" / "index.json").write_text(
        json.dumps({s: f"bestiary-{s.lower()}.json" for s in sources}),
        encoding="utf-8",
    )
    for s in sources:
        (root / "bestiary" / f"bestiary-{s.lower()}.json").write_text(
            json.dumps({"monster": []}), encoding="utf-8",
        )
    (root / "spells").mkdir()
    (root / "spells" / "index.json").write_text(json.dumps({}), encoding="utf-8")
    return root


def _write_yaml(path: Path, body: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def _whitelist_scope(sources: list[str]) -> rr.ResolvedScope:
    """A minimal ResolvedScope, same convention as test_rpg_retriever.py's
    ``_whitelist_scope`` / test_resolve_refs.py's ``_scope`` helpers."""
    return rr.ResolvedScope(
        canonical_mode="whitelist",
        canonical_sources=sources,
        canonical_excluded=[],
        refs=[],
        roots={},
        refs_path=Path("/tmp/refs.yaml"),
        local_path=None,
    )


def _fake_mempalace_client_factory(**_kwargs):
    """Stand-in for ``rpg_retriever.MempalaceClient(palace=...)`` — never
    spawns a subprocess, never touches the network. Same canned
    ``search_hierarchical`` shape used throughout test_rpg_retriever.py.
    """
    return FakeMempalaceClient(responses={
        "mempalace_search_hierarchical": lambda **kw: {
            "query": kw.get("query", ""), "max_depth": kw.get("max_depth", 2),
            "path": {"wings": [], "rooms": []}, "results": [],
            "total_before_filter": 0, "fallback": False,
        },
    })


# ── _resolve_campaign_scope ────────────────────────────────────────────────


class TestResolveCampaignScope:
    def test_no_refs_yaml_returns_none_not_exception(self, tmp_path: Path):
        """THE mandated regression test (design plan section 4): a campaign
        directory with no config/refs.yaml must resolve to None, never
        raise. Without the try/except SystemExit in
        _resolve_campaign_scope, this scenario would crash the MCP server
        at import time — not every campaign is guaranteed to have a
        refs.yaml.
        """
        campaign = tmp_path / "campaign_no_refs"
        campaign.mkdir()
        result = mcp_server._resolve_campaign_scope(campaign)
        assert result is None

    def test_valid_refs_yaml_returns_resolved_scope(self, tmp_path: Path):
        campaign = tmp_path / "campaign_with_refs"
        campaign.mkdir()
        fivetools_root = _fake_5etools_tree(
            tmp_path / "fivetools-data", ["OotA", "MM"]
        )
        _write_yaml(
            campaign / "config" / rr.LOCAL_FILENAME,
            {"roots": {"fivetools_data": str(fivetools_root)}},
        )
        _write_yaml(
            campaign / "config" / rr.REFS_FILENAME,
            {"canonical": ["MM"]},
        )
        result = mcp_server._resolve_campaign_scope(campaign)
        assert result is not None
        assert result.canonical_mode == "whitelist"
        assert result.canonical_sources == ["MM"]

    def test_malformed_refs_yaml_top_level_list_returns_none(self, tmp_path: Path):
        """A refs.yaml that parses as YAML but isn't a mapping (a bare list
        at the top level) is a different resolve_refs.load_refs() failure
        mode than "file missing" — still funnels through the same
        try/except SystemExit and must still degrade to None, not raise.
        """
        campaign = tmp_path / "campaign_bad_refs"
        campaign.mkdir()
        _write_yaml(campaign / "config" / rr.REFS_FILENAME, ["not", "a", "mapping"])
        result = mcp_server._resolve_campaign_scope(campaign)
        assert result is None

    def test_unparseable_refs_yaml_returns_none(self, tmp_path: Path):
        """Genuinely broken YAML (not just wrong-shaped) is yet another
        SystemExit source inside resolve_refs (_load_yaml's YAMLError
        handler) — same safety property, different trigger.
        """
        campaign = tmp_path / "campaign_unparseable_refs"
        refs_path = campaign / "config" / rr.REFS_FILENAME
        refs_path.parent.mkdir(parents=True, exist_ok=True)
        refs_path.write_text("canonical: [unterminated\n", encoding="utf-8")
        result = mcp_server._resolve_campaign_scope(campaign)
        assert result is None


class TestModuleImportWithoutRefsYaml:
    """Regression guard for the same safety property, exercised at the
    module-import level rather than by calling the function directly.
    mcp_server.campaign_dir was frozen at the first import of this module
    in this pytest process (the module-level import at the top of this
    file), from the CWD pytest was invoked from — this worktree root,
    which has a config/ directory but genuinely no config/refs.yaml.
    """

    def test_worktree_campaign_dir_has_no_refs_yaml(self):
        # Precondition pinned explicitly: if this repo ever grows a
        # config/refs.yaml at its own root, the test below would pass for
        # the wrong reason.
        refs_path = mcp_server.campaign_dir / "config" / "refs.yaml"
        assert not refs_path.exists(), (
            f"expected no refs.yaml at {refs_path} for this regression "
            "test to be meaningful"
        )

    def test_module_import_did_not_raise_and_scope_is_none(self):
        # The import already happened (module-level `import ... as
        # mcp_server` above, at collection time). If
        # _resolve_campaign_scope's try/except were missing or wrong,
        # collecting this file would itself have raised SystemExit and no
        # test in this module would have run.
        assert mcp_server._campaign_scope is None


# ── rpg_search scope wiring ─────────────────────────────────────────────────


class TestRpgSearchScopeWiring:
    def test_passes_campaign_scope_by_default(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}

        def fake_retrieve_scoped(query, **kwargs):
            captured["query"] = query
            captured.update(kwargs)
            return {"query": query, "hits": []}

        monkeypatch.setattr(rpg_retriever_module, "retrieve_scoped", fake_retrieve_scoped)
        fake_scope = _whitelist_scope(["MM"])
        monkeypatch.setattr(mcp_server, "_campaign_scope", fake_scope)

        result = mcp_server.rpg_search("goblin")
        assert not result.startswith("Error"), result
        assert captured["scope"] is fake_scope

    def test_full_library_bypasses_campaign_scope(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}

        def fake_retrieve_scoped(query, **kwargs):
            captured.update(kwargs)
            return {"query": query, "hits": []}

        monkeypatch.setattr(rpg_retriever_module, "retrieve_scoped", fake_retrieve_scoped)
        monkeypatch.setattr(mcp_server, "_campaign_scope", _whitelist_scope(["MM"]))

        result = mcp_server.rpg_search("goblin", full_library=True)
        assert not result.startswith("Error"), result
        assert captured["scope"] is None

    def test_unscoped_campaign_unaffected_by_full_library_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # A campaign with no refs.yaml (_campaign_scope is already None)
        # must behave identically regardless of full_library — there is
        # nothing to bypass.
        captured: dict = {}

        def fake_retrieve_scoped(query, **kwargs):
            captured.update(kwargs)
            return {"query": query, "hits": []}

        monkeypatch.setattr(rpg_retriever_module, "retrieve_scoped", fake_retrieve_scoped)
        monkeypatch.setattr(mcp_server, "_campaign_scope", None)

        mcp_server.rpg_search("goblin", full_library=False)
        assert captured["scope"] is None

        captured.clear()
        mcp_server.rpg_search("goblin", full_library=True)
        assert captured["scope"] is None

    def test_forwards_preexisting_kwargs_unchanged(self, monkeypatch: pytest.MonkeyPatch):
        # Spot-check that switching retrieve -> retrieve_scoped and adding
        # `scope`/`full_library` didn't drop any of the tool's existing
        # forwarding.
        captured: dict = {}

        def fake_retrieve_scoped(query, **kwargs):
            captured.update(kwargs)
            return {"query": query, "hits": []}

        monkeypatch.setattr(rpg_retriever_module, "retrieve_scoped", fake_retrieve_scoped)
        monkeypatch.setattr(mcp_server, "_campaign_scope", None)

        result = mcp_server.rpg_search(
            "goblin", limit=7, k_cheap=3, source="MM", book_id=42
        )
        assert not result.startswith("Error"), result
        assert captured["limit"] == 7
        assert captured["k_cheap"] == 3
        assert captured["source"] == "MM"
        assert captured["book_id"] == 42


# ── propose_dossier scope wiring ─────────────────────────────────────────────


def _empty_proposal(query: str) -> dossier_proposer_module.Proposal:
    return dossier_proposer_module.Proposal(
        query=query,
        campaign_dir=str(mcp_server.campaign_dir),
        palace=None,
        rpglib_db=None,
        generated_at="t",
        slots={
            k: [] for k in (
                "npc", "location", "encounter", "statblock", "lore",
                "ingest_cheap", "ingest_expensive",
            )
        },
        raw_hit_count=0,
        fallback=False,
        fallback_reason=None,
    )


class TestProposeDossierScopeWiring:
    def test_passes_campaign_scope_and_retrieve_scoped_by_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        captured: dict = {}

        def fake_propose(query, **kwargs):
            captured["query"] = query
            captured.update(kwargs)
            return _empty_proposal(query)

        monkeypatch.setattr(dossier_proposer_module, "propose", fake_propose)
        fake_scope = _whitelist_scope(["MM"])
        monkeypatch.setattr(mcp_server, "_campaign_scope", fake_scope)

        out_path = tmp_path / "dossier_proposal.md"
        result = mcp_server.propose_dossier("goblin lair", output=str(out_path))
        assert not result.startswith("Error"), result
        assert captured["scope"] is fake_scope
        assert captured["retriever"] is rpg_retriever_module.retrieve_scoped

    def test_full_library_bypasses_campaign_scope(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        captured: dict = {}

        def fake_propose(query, **kwargs):
            captured.update(kwargs)
            return _empty_proposal(query)

        monkeypatch.setattr(dossier_proposer_module, "propose", fake_propose)
        monkeypatch.setattr(mcp_server, "_campaign_scope", _whitelist_scope(["MM"]))

        out_path = tmp_path / "dossier_proposal.md"
        result = mcp_server.propose_dossier(
            "goblin lair", output=str(out_path), full_library=True
        )
        assert not result.startswith("Error"), result
        assert captured["scope"] is None
        assert captured["retriever"] is rpg_retriever_module.retrieve_scoped


# ── full_library genuine end-to-end override (rpg_search) ───────────────────


class TestFullLibraryEndToEnd:
    """Proves full_library actually changes retrieved content, not just
    that the kwarg is forwarded — a real tmp 5etools data root with two
    sources (MM, VGM), a whitelist scope restricting to MM, and an
    assertion that only full_library=True surfaces the VGM hit.

    MemPalace and rpg-library are neutralized (fake MempalaceClient
    factory, no rpg_library_url, include_expensive=False) so this stays a
    fast, offline, deterministic unit test — no subprocess, no network.
    """

    def _build_data_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "data"
        bestiary = root / "bestiary"
        bestiary.mkdir(parents=True)
        (bestiary / "bestiary-mm.json").write_text(json.dumps({
            "_meta": {},
            "monster": [{"name": "Goblin", "source": "MM", "page": 166}],
        }))
        (bestiary / "bestiary-vgm.json").write_text(json.dumps({
            "_meta": {},
            "monster": [{"name": "Goblin Boss", "source": "VGM", "page": 120}],
        }))
        return root

    def test_full_library_expands_cheap_candidate_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        data_root = self._build_data_root(tmp_path)

        monkeypatch.setattr(mcp_server, "_campaign_scope", _whitelist_scope(["MM"]))
        monkeypatch.setattr(mcp_server, "_resolve_fivetools_data_root", lambda: data_root)
        monkeypatch.setattr(mcp_server, "_resolve_rpg_library_url", lambda: None)
        monkeypatch.setattr(mcp_server, "_resolve_palace_path", lambda: None)
        monkeypatch.setattr(
            rpg_retriever_module, "MempalaceClient", _fake_mempalace_client_factory
        )

        scoped_raw = mcp_server.rpg_search("Goblin", include_expensive=False)
        assert not scoped_raw.startswith("Error"), scoped_raw
        scoped = json.loads(scoped_raw)
        scoped_sources = {
            h["source"] for h in scoped["hits"] if h["kind"] == "candidate"
        }
        assert scoped_sources == {"MM"}

        full_raw = mcp_server.rpg_search(
            "Goblin", include_expensive=False, full_library=True
        )
        assert not full_raw.startswith("Error"), full_raw
        full = json.loads(full_raw)
        full_sources = {
            h["source"] for h in full["hits"] if h["kind"] == "candidate"
        }
        assert full_sources == {"MM", "VGM"}
