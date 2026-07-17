"""Tests for proposal_loader — the shared dossier_proposal.md accessor."""

from __future__ import annotations

from pathlib import Path

import pytest

import pipelines.rlm.proposal_loader as pl


def _write_proposal(campaign_dir: Path, text: str) -> Path:
    p = campaign_dir / pl.DOSSIER_PROPOSAL_REL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── load_proposal ────────────────────────────────────────────────────────


class TestLoadProposal:
    def test_missing_returns_none(self, tmp_path: Path):
        assert pl.load_proposal(tmp_path) is None

    def test_default_banner_is_unapproved(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** candidates only.\n")
        got = pl.load_proposal(tmp_path)
        assert got is not None
        assert got.approved is False
        assert got.path.name == "dossier_proposal.md"

    def test_edited_banner_is_approved(self, tmp_path: Path):
        _write_proposal(
            tmp_path,
            "# X\n\n> **Status:** approved by Kostadis on 2026-04-24.\n",
        )
        got = pl.load_proposal(tmp_path)
        assert got is not None
        assert got.approved is True


# ── require_approved_proposal ────────────────────────────────────────────


class TestRequireApproved:
    def test_missing_raises_required(self, tmp_path: Path):
        with pytest.raises(pl.ProposalRequired):
            pl.require_approved_proposal(tmp_path)

    def test_unapproved_raises(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** candidates only.\n")
        with pytest.raises(pl.ProposalNotApproved):
            pl.require_approved_proposal(tmp_path)

    def test_approved_returns_loaded(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved 2026-04-24.\n")
        got = pl.require_approved_proposal(tmp_path)
        assert got.approved is True


# ── attach_proposal_to_documents ─────────────────────────────────────────


class TestAttachToDocuments:
    def test_noop_when_missing(self, tmp_path: Path):
        config: dict = {"documents": []}
        assert pl.attach_proposal_to_documents(config, tmp_path) is False
        assert config["documents"] == []

    def test_appends_record_when_proposal_present(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved.\n")
        config: dict = {"documents": [{"label": "world_state", "path": "/ws.md"}]}
        attached = pl.attach_proposal_to_documents(config, tmp_path)
        assert attached is True
        labels = [d["label"] for d in config["documents"]]
        assert labels == ["world_state", "dossier_proposal"]

    def test_prepend_option(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved.\n")
        config: dict = {"documents": [{"label": "world_state", "path": "/ws.md"}]}
        pl.attach_proposal_to_documents(config, tmp_path, prepend=True)
        labels = [d["label"] for d in config["documents"]]
        assert labels == ["dossier_proposal", "world_state"]

    def test_idempotent(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved.\n")
        config: dict = {"documents": []}
        first = pl.attach_proposal_to_documents(config, tmp_path)
        second = pl.attach_proposal_to_documents(config, tmp_path)
        assert first is True
        assert second is False
        assert len(config["documents"]) == 1

    def test_creates_documents_key_when_missing(self, tmp_path: Path):
        _write_proposal(tmp_path, "# X\n\n> **Status:** approved.\n")
        config: dict = {}
        pl.attach_proposal_to_documents(config, tmp_path)
        assert config["documents"]
