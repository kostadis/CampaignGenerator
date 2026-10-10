"""T054 grounding document review, sign-off, and promotion contracts."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import pointers, state_sections, synth
from pipelines.summary_native.authority import AuthorityLedger, ReviewDecisionRecord, load_ledger, validate_record_identity
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.review.models import DocumentPromotionProposal
from pipelines.summary_native.review.store import (
    CampaignReviewIdentity,
    export_review,
    history,
    import_review_bundle,
    initialize_campaign,
    load_campaign_identity,
    read_snapshot,
)


DOCUMENTS = ("world_state", "campaign_state", "party", "planning")
REVIEW_ID = "grounding-documents"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _documents_module():
    try:
        return importlib.import_module("pipelines.summary_native.review.documents")
    except ModuleNotFoundError:
        pytest.fail("implement pipelines.summary_native.review.documents", pytrace=False)


def _call(name: str):
    function = getattr(_documents_module(), name, None)
    assert callable(function), f"implement documents.{name}"
    return function


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def document_campaign(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="document-fixture", revision=1),
        actor="test",
    )
    initialize_campaign(root)

    summaries = root / "summaries"
    summaries.mkdir()
    (summaries / "001-fixture.md").write_text("# Chapter 1\n\nGrounded evidence.\n")

    registry = root / "docs" / "entity_registry.yaml"
    registry.write_text(
        "version: 1\ncampaign: document-fixture\nentities: []\n",
        encoding="utf-8",
    )
    players = root / "config" / "players.yaml"
    players.write_text("version: 1\nplayers: []\n", encoding="utf-8")
    thread_registry = root / "docs" / "thread_registry.yaml"
    thread_registry.write_text("version: 1\nthreads: []\n", encoding="utf-8")

    range_dir = root / "docs" / "summary_native" / "ch001-001"
    state = range_dir / "state"
    drafts = state / "drafts"
    reference = drafts / "reference"
    reference.mkdir(parents=True)
    for kind in sorted({kind for values in state_sections.CONTRACT_REFERENCES.values() for kind in values}):
        (reference / f"{kind}.md").write_text(f"# {kind}\n\nCaptured evidence.\n")
    (drafts / "timeline.md").write_text("# Timeline\n\nChapter 1.\n")

    corpus_manifest = range_dir / "manifest.json"
    _write_json(corpus_manifest, {
        "kind": "summary_native",
        "schema": 1,
        "complete": True,
        "range": {"since": 1, "until": 1, "gaps": []},
        "files": [{
            "path": "summaries/001-fixture.md", "chapter": 1,
            "sha256": _sha(summaries / "001-fixture.md"),
        }],
        "canon": {"registry_sha256": _sha(registry), "canon_sha256": None},
    })
    notes_manifest = state / "notes" / "manifest.json"
    _write_json(notes_manifest, {
        "kind": "state_notes",
        "audience": "gm",
        "corpus_manifest_sha256": _sha(corpus_manifest),
        "registry_sha256": _sha(registry),
        "players_sha256": _sha(players),
    })

    selection = {"documents": []}
    for document in DOCUMENTS:
        run_id = f"run-{document}"
        record = state / "runs" / run_id / "record.json"
        _write_json(record, {
            "step": "synth",
            "doc": document,
            "run_id": run_id,
            "range": {"since": 1, "until": 1},
            "inputs": {
                "corpus_manifest_sha256": _sha(corpus_manifest),
                "notes_manifest_sha256": _sha(notes_manifest),
                "registry_sha256": _sha(registry),
                "players_sha256": _sha(players),
                **({"thread_registry_sha256": _sha(thread_registry)}
                   if document in {"campaign_state", "planning"} else {}),
            },
            "check": "passed",
            "finished": "2026-10-10T00:00:00+00:00",
        })
        contract = state_sections.reading_contract(
            (1, 1),
            {"reference": "reference", "timeline": "timeline.md", "summaries": "summaries"},
            document,
        )
        draft = drafts / f"{document}.draft.md"
        draft.write_text(
            f"<!-- summary_native draft | doc: {document} | range: ch001-001 | "
            f"record: runs/{run_id}/record.json | notes manifest sha256: {_sha(notes_manifest)} -->\n"
            f"{contract}\n"
            + "\n\n".join(f"{heading}\n\nReviewed body for {document}." for heading in synth.load_outline(document))
            + "\n",
            encoding="utf-8",
        )
        selection["documents"].append({
            "id": document,
            "path": str(draft.relative_to(root)),
        })

    selection_path = root / "selections" / "documents.json"
    _write_json(selection_path, selection)
    return root, selection_path


def _create(root: Path, selection: Path, *, review_id: str = REVIEW_ID):
    result = _call("create_document_review")(
        root, review_id, selection, created_by="GM"
    )
    manifest, custody, items = read_snapshot(root, review_id)
    return result, manifest, custody, items


def _item_by_document(items) -> dict[str, object]:
    return {
        item.proposed_action.details["document_id"]: item
        for item in items
        if item.proposed_action.action == "signoff_document"
    }


def _sign(root: Path, review_id: str, item) -> dict:
    return _call("sign_document")(
        root,
        review_id,
        document_item_id=item.item_id,
        item_sha256=item.proposed_action.details["document_sha256"],
        expected_decision_revision=0,
        reviewer="GM",
    )


def _document_error():
    return getattr(_documents_module(), "DocumentReviewError", Exception)


def test_four_document_types_create_exact_independent_signoff_items(document_campaign):
    root, selection = document_campaign
    result, manifest, custody, items = _create(root, selection)
    by_document = _item_by_document(items)

    assert result["review_id"] == REVIEW_ID
    assert manifest.kind.value == "grounding_documents"
    assert {entry.id for entry in manifest.selection} == set(DOCUMENTS)
    assert set(by_document) == set(DOCUMENTS)
    assert len(items) == 4
    for document, item in by_document.items():
        draft = root / item.locator.source_path
        assert item.domain.value == "grounding_document"
        assert item.scope.kind == "document" and item.scope.value == document
        assert item.proposed_action.details["document_sha256"] == _sha(draft)
        assert item.proposed_action.details["destination"].endswith(f"/reviewed/{document}.md")
        assert any(source.path == item.locator.source_path for source in custody.sources)


def test_long_document_is_read_in_bounded_sections_with_full_digest(document_campaign):
    root, selection = document_campaign
    selected = json.loads(selection.read_text(encoding="utf-8"))["documents"][0]
    draft = root / selected["path"]
    draft.write_text(draft.read_text(encoding="utf-8") + ("Long reviewed line.\n" * 5000), encoding="utf-8")
    _create(root, selection)

    from pipelines.summary_native.review.cli import _show_review

    first = _show_review(root, REVIEW_ID, item_id="document-world_state", cursor=None, limit=None, section_offset=0)
    section = first["document_section"]
    assert len(section["content"].encode("utf-8")) <= 64 * 1024
    assert section["next_offset"] is not None
    assert section["full_document_sha256"] == _sha(draft)
    second = _show_review(root, REVIEW_ID, item_id="document-world_state", cursor=None, limit=None, section_offset=section["next_offset"])
    assert second["document_section"]["offset"] == section["next_offset"]
    assert section["content"] + second["document_section"]["content"] == draft.read_text(encoding="utf-8")


def test_resolved_findings_never_substitute_for_independent_document_signoff(document_campaign):
    root, selection = document_campaign
    _create(root, selection)

    with pytest.raises(_document_error(), match="REVIEW_DOCUMENT_SIGNOFF_REQUIRED"):
        _call("prepare_document_promotion")(
            root, REVIEW_ID, document_ids=["world_state"]
        )


def test_one_byte_draft_change_stales_exact_document_signoff(document_campaign):
    root, selection = document_campaign
    _, _, _, items = _create(root, selection)
    item = _item_by_document(items)["world_state"]
    _sign(root, REVIEW_ID, item)
    draft = root / item.locator.source_path
    draft.write_bytes(draft.read_bytes() + b" ")

    with pytest.raises(_document_error(), match="REVIEW_DOCUMENT_STALE"):
        _call("prepare_document_promotion")(
            root, REVIEW_ID, document_ids=["world_state"]
        )


def test_missing_reading_contract_bundle_pointer_blocks_promotion(document_campaign):
    root, selection = document_campaign
    _, _, _, items = _create(root, selection)
    item = _item_by_document(items)["party"]
    _sign(root, REVIEW_ID, item)
    (root / item.locator.source_path).parent.joinpath("reference", "party.md").unlink()

    with pytest.raises(_document_error(), match="REVIEW_DOCUMENT_POINTER"):
        _call("prepare_document_promotion")(
            root, REVIEW_ID, document_ids=["party"]
        )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [("audience", "REVIEW_DOCUMENT_AUDIENCE"), ("freshness", "REVIEW_DOCUMENT_STALE")],
)
def test_existing_audience_and_freshness_gates_still_block_promotion(
    document_campaign, failure: str, expected: str,
):
    root, selection = document_campaign
    _, _, _, items = _create(root, selection)
    item = _item_by_document(items)["campaign_state"]
    _sign(root, REVIEW_ID, item)
    if failure == "audience":
        notes = root / "docs" / "summary_native" / "ch001-001" / "state" / "notes" / "manifest.json"
        value = json.loads(notes.read_text())
        value["audience"] = "players"
        _write_json(notes, value)
    else:
        (root / "docs" / "entity_registry.yaml").write_text(
            "version: 1\ncampaign: document-fixture\nentities: []\n# changed\n",
            encoding="utf-8",
        )

    with pytest.raises(_document_error(), match=expected):
        _call("prepare_document_promotion")(
            root, REVIEW_ID, document_ids=["campaign_state"]
        )


def test_explicit_selection_promotes_only_selected_exact_bundle(document_campaign):
    root, full_selection = document_campaign
    raw = json.loads(full_selection.read_text())
    selected_ids = {"world_state", "planning"}
    raw["documents"] = [entry for entry in raw["documents"] if entry["id"] in selected_ids]
    selected = root / "selections" / "selected-documents.json"
    _write_json(selected, raw)
    _, manifest, _, items = _create(root, selected)
    assert {entry.id for entry in manifest.selection} == selected_ids
    assert set(_item_by_document(items)) == selected_ids
    for item in items:
        _sign(root, REVIEW_ID, item)

    proposals = tuple(_call("prepare_document_promotion")(
        root, REVIEW_ID, document_ids=["world_state", "planning"]
    ))
    assert len(proposals) == 2
    assert all(isinstance(proposal, DocumentPromotionProposal) for proposal in proposals)
    assert {proposal.document_item_id for proposal in proposals} == {item.item_id for item in items}
    receipts = tuple(_call("promote_document_bundle")(
        root,
        REVIEW_ID,
        proposals=[{
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
        } for proposal in proposals],
    ))
    assert len(receipts) == 2
    replay = tuple(_call("promote_document_bundle")(
        root,
        REVIEW_ID,
        proposals=[{
            "proposal_id": proposal.proposal_id,
            "proposal_digest": proposal.proposal_digest,
        } for proposal in proposals],
    ))
    assert replay == receipts
    reviewed = root / "docs" / "summary_native" / "ch001-001" / "state" / "reviewed"
    assert {path.stem for path in reviewed.glob("*.md")} == selected_ids | {"timeline"}
    for proposal in proposals:
        assert not pointers.check_paths(reviewed / f"{proposal.document_item_id.removeprefix('document-')}.md", root)
    for document in selected_ids:
        source = root / _item_by_document(items)[document].locator.source_path
        assert (reviewed / f"{document}.md").read_bytes() == source.read_bytes()
    assert not (reviewed / "party.md").exists()
    assert not (reviewed / "campaign_state.md").exists()
    records = [record for record in load_ledger(root).records if isinstance(record, ReviewDecisionRecord)]
    assert len([record for record in records if record.receipt is not None]) == 2
    for record in records:
        validate_record_identity(root, record)


def test_imported_exact_signoff_event_is_the_promotion_decision_binding(
    document_campaign, tmp_path: Path,
):
    source, selection = document_campaign
    _, _, _, items = _create(source, selection)
    item = _item_by_document(items)["planning"]

    replica = tmp_path / "replica"
    shutil.copytree(source, replica)
    identity = load_campaign_identity(source)
    (replica / "docs" / "reviews" / "campaign.json").write_bytes(
        CampaignReviewIdentity(1, identity.campaign_id, str(replica.resolve())).bytes()
    )

    _sign(source, REVIEW_ID, item)
    exported = export_review(source, REVIEW_ID, [item.item_id])
    source_bundle = source / exported["path"]
    replica_bundle = replica / "import" / source_bundle.name
    replica_bundle.parent.mkdir()
    replica_bundle.write_bytes(source_bundle.read_bytes())
    imported = import_review_bundle(replica, replica_bundle, expected_generation=1)
    assert imported["imported_events"] == 1

    events = history(replica, REVIEW_ID, item_id=item.item_id)
    assert len(events) == 1 and events[0]["reviewer"] == "GM"
    proposals = tuple(_call("prepare_document_promotion")(
        replica, REVIEW_ID, document_ids=["planning"]
    ))
    assert len(proposals) == 1
    binding = proposals[0].decision_bindings[0]
    assert binding.event_id == events[0]["event_id"]
    assert binding.item_id == item.item_id
    assert binding.item_revision == item.revision
    assert binding.review_digest == item.review_digest
    assert binding.decision_revision == events[0]["decision_revision"]


@pytest.mark.parametrize("changed", ["summary", "reference"])
def test_promotion_rechecks_exact_dependencies_after_preview(document_campaign, changed: str):
    root, selection = document_campaign
    _, _, _, items = _create(root, selection)
    item = _item_by_document(items)["world_state"]
    _sign(root, REVIEW_ID, item)
    proposal = _call("prepare_document_promotion")(
        root, REVIEW_ID, document_ids=["world_state"]
    )[0]
    if changed == "summary":
        dependency = root / "summaries" / "001-fixture.md"
    else:
        dependency = root / item.locator.source_path
        dependency = dependency.parent / "reference" / "threats.md"
    dependency.write_bytes(dependency.read_bytes() + b"changed\n")
    before = {p.relative_to(root): _sha(p) for p in root.rglob("*") if p.is_file()}

    with pytest.raises(_document_error(), match="REVIEW_DOCUMENT_STALE"):
        _call("promote_document_bundle")(
            root,
            REVIEW_ID,
            proposals=[{
                "proposal_id": proposal.proposal_id,
                "proposal_digest": proposal.proposal_digest,
            }],
        )

    after = {p.relative_to(root): _sha(p) for p in root.rglob("*") if p.is_file()}
    assert after == before
    assert not (root / proposal.destination).exists()
