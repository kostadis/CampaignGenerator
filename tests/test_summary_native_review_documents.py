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


def _create(root: Path, selection: Path, *, review_id: str = REVIEW_ID, signoff_context: dict | None = None):
    result = _call("create_document_review")(
        root, review_id, selection, created_by="GM",
        signoff_rule_version=2 if signoff_context is not None else 1,
        signoff_context=signoff_context,
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


def test_v2_signoff_items_revise_when_current_report_context_changes(document_campaign):
    root, selection = document_campaign
    first = {
        "analysis_digest": "1" * 64, "resolution_digest": "2" * 64,
        "support_digest": "3" * 64, "authority_digest": "4" * 64,
        "audience_digest": "5" * 64, "rules_digest": "6" * 64,
    }
    _, manifest, _, items = _create(root, selection, signoff_context=first)
    old = _item_by_document(items)["world_state"]
    _sign(root, REVIEW_ID, old)
    second = {**first, "analysis_digest": "a" * 64, "resolution_digest": "b" * 64}
    result, refreshed, _, revised_items = _create(root, selection, signoff_context=second)
    revised = _item_by_document(revised_items)
    assert result["generation"] == refreshed.generation == manifest.generation + 1
    assert {item.revision for item in revised.values()} == {2}
    assert revised["world_state"].review_digest != old.review_digest
    event = history(root, REVIEW_ID, item_id=old.item_id)[-1]
    assert event["item_revision"] == 1
    assert event["review_digest"] == old.review_digest


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


@pytest.mark.parametrize("entrypoint", ["prepare_document_promotion", "promote_document_bundle"])
def test_legacy_per_document_publication_entrypoints_refuse_with_whole_bundle_instruction(
    document_campaign, entrypoint: str,
):
    root, selection = document_campaign
    _create(root, selection)
    kwargs = {"document_ids": ["world_state"]} if entrypoint.startswith("prepare") else {"proposals": []}

    with pytest.raises(_document_error(), match="PROMOTION_WHOLE_BUNDLE_REQUIRED") as exc:
        _call(entrypoint)(root, REVIEW_ID, **kwargs)

    assert "summary_native promote --since N --until N" in str(exc.value)


def test_imported_exact_signoff_event_is_the_promotion_decision_binding(
    document_campaign, tmp_path: Path,
):
    source, selection = document_campaign
    context = {
        "analysis_digest": "1" * 64,
        "resolution_digest": "2" * 64,
        "support_digest": "3" * 64,
        "authority_digest": "4" * 64,
        "audience_digest": "5" * 64,
        "rules_digest": "6" * 64,
    }
    _, _, _, items = _create(source, selection, signoff_context=context)
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
    # Import preserves the exact immutable event for the whole-bundle gate; it
    # does not revive the retired per-document publication mechanism.
    assert events[0]["item_id"] == item.item_id
    assert events[0]["review_digest"] == item.review_digest
    with pytest.raises(_document_error(), match="PROMOTION_WHOLE_BUNDLE_REQUIRED"):
        _call("prepare_document_promotion")(replica, REVIEW_ID, document_ids=["planning"])
