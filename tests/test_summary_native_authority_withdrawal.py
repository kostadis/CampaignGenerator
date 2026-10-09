from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.summary_native.authority import AuthorityError, load_ledger
from pipelines.summary_native.authority_apply import apply_proposal, create_proposal, create_withdrawal_proposal, request_withdrawal
from tests.test_summary_native_authority_apply import _campaign


def test_withdrawal_proposal_preserves_unrelated_current_edits(tmp_path: Path):
    source = tmp_path / "summary.md"
    source.write_text("before corrected after\nnew unrelated line\n")
    proposal = create_withdrawal_proposal(tmp_path, ruling_id="rule", source_path=source, applied_before=b"before false after\n", applied_after=b"before corrected after\n")
    assert proposal["after_bytes"].decode() == "before false after\nnew unrelated line\n"


def test_withdrawal_is_digest_bound_preserves_later_edits_and_retains_history(tmp_path: Path):
    source = _campaign(tmp_path)
    proposal = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])
    source.write_text(source.read_text().replace("# Chapter 54", "# Chapter 54 — reviewed title") + "\nA later unrelated edit.\n")
    reversal = request_withdrawal(tmp_path, ruling_id="earthstone-ruling", reason="GM reversal")
    receipt = apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=reversal["proposal_sha256"])
    assert "false steward" in source.read_text()
    assert "A later unrelated edit." in source.read_text()
    assert "# Chapter 54 — reviewed title" in source.read_text()
    assert load_ledger(tmp_path).records[0].status == "withdrawn"
    assert (tmp_path / "docs/authority/receipts" / f"{receipt['id']}.json").is_file()
    assert len(list((tmp_path / "docs/authority/events").glob("*.json"))) >= 3


def test_withdrawal_refuses_changed_applied_passage(tmp_path: Path):
    source = _campaign(tmp_path)
    proposal = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])
    source.write_text(source.read_text().replace("correct actor", "later actor"))
    with pytest.raises(AuthorityError, match="AUTH_STALE_PROPOSAL"):
        request_withdrawal(tmp_path, ruling_id="earthstone-ruling", reason="GM reversal")
