from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.summary_native.authority import AuthorityError, AuthorityLedger, DOCUMENT_ANCHOR, RulingRecord, load_ledger, sha256_bytes, write_ledger
from pipelines.summary_native.authority_apply import apply_proposal, create_proposal
from pipelines.summary_native.authority_inputs import resolve_anchor_span


def _ruling() -> RulingRecord:
    source = b"# Chapter 54\n\n## Scenes\n\n### 054.01 Earthstone\n<!-- anchor: earthstone -->\nThe false steward acted.\n"
    return RulingRecord.model_validate({"id":"earthstone-ruling","kind":"ruling","revision":1,"classification":"RULED","subject":{"kind":"topic","id":"earthstone"},"effective":{"from_chapter":54,"through_chapter":54},"audience":{"grants":["gm"]},"projections":["world_state"],"status":"draft","recorded_at":"2026-10-09T00:00:00Z","recorded_by":"GM","source":{"path":"docs/summaries/054-earthstone.md","anchor":"earthstone","before_sha256":sha256_bytes(source),"before_span_sha256":sha256_bytes(b"false steward")},"rejected_claim":"false steward","replacement_fact":"correct actor"})


def _campaign(tmp_path: Path) -> Path:
    source = tmp_path / "docs/summaries/054-earthstone.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Chapter 54\n\n## Scenes\n\n### 054.01 Earthstone\n<!-- anchor: earthstone -->\nThe false steward acted.\n")
    write_ledger(tmp_path, AuthorityLedger(version=2, campaign="fixture", revision=1, records=[_ruling()]))
    return source


def test_proposal_is_immutable_and_apply_requires_displayed_digest(tmp_path: Path):
    source = _campaign(tmp_path)
    proposal = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    assert proposal["proposal_sha256"]
    with pytest.raises(AuthorityError, match="AUTH_STALE_PROPOSAL"):
        apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256="0" * 64)
    receipt = apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])
    assert receipt["proposal_id"] == proposal["id"]
    assert source.read_text() == "# Chapter 54\n\n## Scenes\n\n### 054.01 Earthstone\n<!-- anchor: earthstone -->\nThe correct actor acted.\n"


def test_apply_refuses_stale_source_and_reproposal_gets_a_new_immutable_id(tmp_path: Path):
    source = _campaign(tmp_path)
    first = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    source.write_text(source.read_text() + "\nA later unrelated edit.\n")
    with pytest.raises(AuthorityError, match="AUTH_STALE_PROPOSAL"):
        apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=first["proposal_sha256"])
    refreshed = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    assert refreshed["id"] != first["id"]
    assert (tmp_path / "docs/authority/proposals" / first["id"] / "proposal.json").is_file()


def test_competing_anchor_proposal_is_refused_and_receipt_does_not_cycle_into_ledger(tmp_path: Path):
    _campaign(tmp_path)
    original = load_ledger(tmp_path)
    other = _ruling().model_copy(update={"id": "earthstone-competing", "revision": 1})
    write_ledger(tmp_path, original.model_copy(update={"revision": 2, "records": [*original.records, other]}))
    proposal = create_proposal(tmp_path, "earthstone-ruling", summaries_dir=tmp_path / "docs/summaries")
    with pytest.raises(AuthorityError, match="AUTH_CONFLICT"):
        create_proposal(tmp_path, "earthstone-competing", summaries_dir=tmp_path / "docs/summaries")
    receipt = apply_proposal(tmp_path, "earthstone-ruling", proposal_sha256=proposal["proposal_sha256"])
    ledger = load_ledger(tmp_path)
    assert receipt["id"] in ledger.model_dump_json()
    assert "after_source_sha256" not in ledger.model_dump_json()
    assert (tmp_path / "docs/authority/receipts" / f"{receipt['id']}.json").is_file()


def test_competing_proposals_canonicalize_dot_and_in_root_symlink_targets(tmp_path: Path):
    source = _campaign(tmp_path)
    original = load_ledger(tmp_path)
    dotted = _ruling().model_copy(update={
        "id": "earthstone-dot", "source": _ruling().source.model_copy(update={"path": "docs/summaries/./054-earthstone.md"}),
    })
    linked = source.parent / "earthstone-alias.md"
    linked.symlink_to(source.name)
    symlinked = _ruling().model_copy(update={
        "id": "earthstone-link", "source": _ruling().source.model_copy(update={"path": "docs/summaries/earthstone-alias.md"}),
    })
    write_ledger(tmp_path, original.model_copy(update={"revision": 2, "records": [*original.records, dotted, symlinked]}))
    create_proposal(tmp_path, "earthstone-ruling", summaries_dir=source.parent)
    for identifier in ("earthstone-dot", "earthstone-link"):
        with pytest.raises(AuthorityError, match="AUTH_CONFLICT"):
            create_proposal(tmp_path, identifier, summaries_dir=source.parent)


def test_anchor_scope_stops_before_the_next_scene_and_rejects_duplicates():
    source = (
        b"# Chapter 54\n## Scenes\n### 054.01 One\n<!-- anchor: earthstone -->\nGM fact\n"
        b"### 054.02 Two\nPlayer fact\n"
    )
    assert resolve_anchor_span(source, "earthstone") == b"<!-- anchor: earthstone -->\nGM fact\n"
    with pytest.raises(AuthorityError, match="ambiguous"):
        resolve_anchor_span(source + b"<!-- anchor: earthstone -->\n", "earthstone")


def test_document_anchor_is_whole_file_support_only():
    data = b'{"valid": "json"}\n'
    assert resolve_anchor_span(data, DOCUMENT_ANCHOR) == data
    raw = _ruling().model_dump(mode="json")
    raw["source"]["anchor"] = DOCUMENT_ANCHOR
    with pytest.raises(ValueError, match="reserved for read-only support"):
        RulingRecord.model_validate(raw)
