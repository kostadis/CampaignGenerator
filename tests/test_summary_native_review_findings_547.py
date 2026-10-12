"""Regressions for the #547 code review and constitution audit.

Each test names the defect it pins: the failure it describes was reachable on
main before the fix.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipelines.summary_native.authority import AuthorityError, ReviewArtifactRef, sha256_bytes
from pipelines.summary_native.authority_apply import journal_path, prepare_transaction, recover_transaction
from pipelines.summary_native.review.models import canonical_bytes
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    export_review,
    import_review_bundle,
    initialize_campaign,
)
from tests.test_summary_native_review_decisions import (  # noqa: F401  (fixture)
    _decision,
    _run_json,
    _write_batch,
    decision_campaign,
)
from tests.test_summary_native_review_documents import (  # noqa: F401  (fixture)
    REVIEW_ID,
    _create,
    document_campaign,
)
from tests.test_summary_native_review_migration import _campaign as _v1_campaign
from tests.test_summary_native_review_migration import _review_decision


# ── error codes ──────────────────────────────────────────────────────────────


def test_a_refusal_spelled_only_in_its_message_carries_that_code():
    """`ReviewStoreError("REVIEW_INVALID_BATCH: ...")` used to report REVIEW_INVALID."""
    assert ReviewStoreError("REVIEW_INVALID_BATCH: too many decisions").code == "REVIEW_INVALID_BATCH"
    assert ReviewStoreError("REVIEW_UNKNOWN_ITEM: x").code == "REVIEW_UNKNOWN_ITEM"
    assert ReviewStoreError("no prefix here").code == "REVIEW_INVALID"
    assert ReviewStoreError("REVIEW_X: y", "REVIEW_EXPLICIT").code == "REVIEW_EXPLICIT"


def test_cli_emits_the_message_prefix_code(decision_campaign, tmp_path: Path, capsys):
    root, _items = decision_campaign
    selection = tmp_path / "empty-export.json"
    selection.write_text("{}", encoding="utf-8")
    code, envelope = _run_json(
        capsys,
        ["review", "export", "npc-review", "--selection", str(selection), "--campaign-dir", str(root), "--json"],
    )
    assert code != 0
    assert envelope["code"] == "REVIEW_INVALID_SELECTION"


# ── bundle import ────────────────────────────────────────────────────────────


def _exported_bundle(root: Path, items, tmp_path: Path, capsys) -> tuple[Path, dict]:
    batch = _write_batch(tmp_path / "export.json", "export-forgery", [_decision(items[0])])
    assert _run_json(
        capsys,
        ["review", "decide", "npc-review", "--decisions", str(batch), "--campaign-dir", str(root), "--json"],
    )[0] == 0
    exported = export_review(root, "npc-review", [items[0].item_id])
    path = root / exported["path"]
    return path, json.loads(path.read_text(encoding="utf-8"))


def _resign(path: Path, bundle: dict) -> None:
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    path.write_bytes(canonical_bytes({**unsigned, "bundle_sha256": sha256_bytes(canonical_bytes(unsigned))}))


def test_an_imported_withdrawal_cannot_name_a_path(decision_campaign, tmp_path: Path, capsys):
    """A withdrawal's event_id became a file name unvalidated: `../../../npcs/x` wrote into docs/npcs."""
    root, items = decision_campaign
    path, bundle = _exported_bundle(root, items, tmp_path, capsys)
    decision = bundle["events"][0]
    bundle["events"].append({
        "version": 1, "kind": "withdrawal", "event_id": "../../../npcs/x",
        "campaign_id": decision["campaign_id"], "review_id": "npc-review",
        "item_id": decision["item_id"], "item_revision": decision["item_revision"],
        "review_digest": decision["review_digest"], "decision_revision": 2,
        "supersedes_event": decision["event_id"], "withdrawal_reason": "forged",
        "reviewer": "Mallory", "recorded_at": "2026-10-12T00:00:00Z",
    })
    _resign(path, bundle)
    with pytest.raises(ReviewStoreError, match="REVIEW_INVALID_IMPORT"):
        import_review_bundle(root, path, expected_generation=1)
    assert not (root / "docs" / "npcs").exists()


def test_an_imported_authority_record_needs_its_decision_event(decision_campaign, tmp_path: Path, capsys):
    """An accepted record with no decision event behind it would stand in for a human decision."""
    root, items = decision_campaign
    path, bundle = _exported_bundle(root, items, tmp_path, capsys)
    forged = dict(bundle["authority_records"][0])
    forged.update(id="review-forged-record", event_id="event-that-never-happened")
    bundle["authority_records"].append(forged)
    _resign(path, bundle)
    before = (root / "docs" / "authority.yaml").read_bytes()
    with pytest.raises(ReviewStoreError, match="no decision event"):
        import_review_bundle(root, path, expected_generation=1)
    assert (root / "docs" / "authority.yaml").read_bytes() == before


# ── identity apply ───────────────────────────────────────────────────────────


def test_identity_apply_refuses_an_approval_record_without_its_event(tmp_path: Path):
    from pipelines.summary_native.review.identity import IdentityReviewError, _approval

    record = _review_decision(
        disposition="merge",
        proposal=ReviewArtifactRef(kind="identity_merge", id="identity-earthstone", digest="e" * 64),
    )
    proposal = SimpleNamespace(
        proposal_id="identity-earthstone",
        proposal_digest="e" * 64,
        decision_bindings=[SimpleNamespace(
            item_id=record.item_id, item_revision=record.item_revision,
            review_digest=record.review_digest, decision_revision=0,
        )],
    )
    ledger = SimpleNamespace(records=[record])
    with pytest.raises(IdentityReviewError, match="REVIEW_APPROVAL_REQUIRED"):
        _approval(ledger, record.review_id, proposal, tmp_path)


# ── document sections and grounding reviews ──────────────────────────────────


def test_document_sections_split_on_character_boundaries_and_refuse_a_split_offset(document_campaign):
    """A boundary inside a character backs off at most three bytes; an offset inside one refuses.

    The old loop re-decoded the whole 64 KiB slice once per byte before refusing.
    """
    root, selection = document_campaign
    selected = json.loads(selection.read_text(encoding="utf-8"))["documents"][0]
    draft = root / selected["path"]
    draft.write_text(draft.read_text(encoding="utf-8") + ("é" * 70000) + "\n", encoding="utf-8")
    _create(root, selection)

    from pipelines.summary_native.review import cli

    def section(offset: int) -> dict:
        return cli._show_review(
            root, REVIEW_ID, item_id="document-world_state", cursor=None, limit=None, section_offset=offset,
        )["document_section"]

    text, offset, pages = "", 0, 0
    while offset is not None:
        page = section(offset)
        text += page["content"]
        offset = page["next_offset"]
        pages += 1
    assert pages > 1 and text == draft.read_text(encoding="utf-8")

    inside = draft.read_bytes().index("é".encode("utf-8")) + 1
    with pytest.raises(ReviewStoreError, match="REVIEW_PAGE_INVALID"):
        section(inside)


def test_review_create_builds_a_grounding_document_review(document_campaign, capsys):
    """The grounding Shared review page sends kind grounding_documents; it always refused."""
    root, selection = document_campaign
    code, envelope = _run_json(
        capsys,
        ["review", "create", "--kind", "grounding_documents", "--selection", str(selection),
         "--campaign-dir", str(root), "--json"],
    )
    assert code == 0, envelope
    review_id = envelope["data"]["review_id"]
    assert review_id.startswith("document-review-")
    code, status = _run_json(capsys, ["review", "status", review_id, "--campaign-dir", str(root), "--json"])
    assert code == 0 and status["data"]["item_count"] == 4


# ── state created as a side effect, and migration messages ───────────────────


def test_registry_reads_do_not_turn_a_campaign_into_a_review_campaign(tmp_path: Path, capsys):
    from entity_registry.registry import main as registry_main

    campaign = tmp_path / "campaign"
    assert registry_main(["init", str(campaign)]) == 0
    registry_main(["check", str(campaign)])
    assert not (campaign / "docs" / "authority").exists()


def test_migration_dry_run_does_not_create_authority_state(tmp_path: Path):
    from pipelines.summary_native.review.migrate import plan_authority_migration

    with pytest.raises(AuthorityError, match="nothing to migrate"):
        plan_authority_migration(tmp_path)
    assert not (tmp_path / "docs").exists()


def test_review_init_on_a_v1_ledger_names_the_exact_migration_command(tmp_path: Path):
    _v1_campaign(tmp_path)
    with pytest.raises(ReviewStoreError, match=r"summary_native review migrate --campaign-dir .* --dry-run"):
        initialize_campaign(tmp_path)


def test_npc_publish_reports_a_ledger_that_needs_migrating(tmp_path: Path):
    """A v1 ledger read as "no sign-off", sending the GM after a sign-off that could not help."""
    from pipelines.summary_native.npc_publish import _current_draft_signoff

    draft = tmp_path / "draft.md"
    draft.write_text("draft\n", encoding="utf-8")
    assert _current_draft_signoff(tmp_path, draft, "0" * 64) is False  # no ledger: nothing signed
    _v1_campaign(tmp_path)
    with pytest.raises(AuthorityError, match="review migrate"):
        _current_draft_signoff(tmp_path, draft, "0" * 64)


def test_recovery_does_not_rewrite_a_v1_journal_into_the_v2_shape(tmp_path: Path):
    target = tmp_path / "docs" / "legacy.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"before")
    journal = prepare_transaction(
        tmp_path, proposal_id="legacy-proposal", proposal_sha256="d" * 64,
        targets=[(target, b"before", b"after")],
    )
    path = journal_path(tmp_path, journal["id"])
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("version")
    for item in legacy["targets"]:
        item.pop("operation")
    path.write_text(json.dumps(legacy, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    assert recover_transaction(tmp_path, journal["id"])["state"] == "committed"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "version" not in saved
    assert all("operation" not in item for item in saved["targets"])


def test_service_port_defaults_to_the_campaign_review_config(decision_campaign, monkeypatch, capsys):
    root, _items = decision_campaign
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "review.yaml").write_text("port: 9911\n", encoding="utf-8")
    seen = {}

    def fake_start(campaign_dir, review_id, **kwargs):
        seen.update(kwargs)
        return {"review_id": review_id, "host": kwargs["host"], "port": kwargs["port"], "origin": kwargs["origin"], "pid": 1}

    monkeypatch.setattr("pipelines.summary_native.review.service.start_service", fake_start)
    code, _ = _run_json(
        capsys,
        ["review", "service", "start", "npc-review", "--host", "127.0.0.1",
         "--origin", "http://127.0.0.1:9911", "--campaign-dir", str(root), "--json"],
    )
    assert code == 0 and seen["port"] == 9911
