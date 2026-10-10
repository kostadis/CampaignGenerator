from __future__ import annotations

import importlib.util
import asyncio
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from campaignlib.review_config import ReviewConfig
from pipelines.summary_native.claims.check import check_claims
from pipelines.summary_native.claims.extract import extract_candidates
from pipelines.summary_native.claims.imports import _resolve_subject, import_candidates
from pipelines.summary_native.claims.packets import assemble_packet, save_packet
from pipelines.summary_native.claims.report import _private_read, evaluate_report, write_report
from pipelines.summary_native.claims.selection import (
    _write_owner_only, confirm_selection, mandatory_source_closure,
    save_confirmed_selection, select_whole_source_chunks,
)
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.manifest import build_bundle_selection
from pipelines.summary_native.review.web.app import create_review_app


FACTORY_PATH = Path(__file__).parent / "fixtures/summary_native/promotion/create_campaign.py"
SPEC = importlib.util.spec_from_file_location("claims_privacy_factory", FACTORY_PATH)
assert SPEC and SPEC.loader
FACTORY = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(FACTORY)
NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def _private_artifacts(tmp_path: Path):
    root = FACTORY.create_campaign(tmp_path / "campaign", baseline="legacy")
    bundle = build_bundle_selection(
        root, out_root="docs/summary_native", since=1, until=3,
        campaign_id=str(FACTORY.CAMPAIGN_ID), review_id="privacy-review", rule_versions=("claims/1",),
    )
    proposed = mandatory_source_closure(
        root, bundle, effective_horizon="through-chapter-3", audience="gm", rule_versions=("claims/1",),
    )
    proposed = select_whole_source_chunks(root, proposed, (proposed.sources[0].source_id,))
    selection = confirm_selection(proposed, reviewer="gm", confirmed_at=NOW)
    selection_file = save_confirmed_selection(root, selection)
    packet = assemble_packet(root, selection); packet_file = save_packet(root, selection, packet)
    chunk = packet.chunks[0]; raw = chunk.text.encode(); end = min(len(raw), 8)
    while end and not raw[:end].decode("utf-8", errors="ignore").encode() == raw[:end]: end -= 1
    proposal = {"annotations": [{
        "occurrence_id": "private-candidate", "chunk_id": chunk.chunk_id,
        "start_byte": 0, "end_byte": end, "original_span": raw[:end].decode(),
        "subject_id": "unknown-private-subject", "subject_kind": "entity",
        "predicate": "status", "normalized_value": "active", "audience": "gm",
    }]}
    import_file = import_candidates(root, selection, packet, proposal)
    run = extract_candidates(
        root, selection, packet, selected_chunk_ids=(chunk.chunk_id,), backend="offline", model="none",
        prompt_version="privacy", rules="claims/1", invoke=lambda _prompt, _chunk: json.dumps(proposal),
        now=lambda: NOW,
    )
    report_files = write_report(root, evaluate_report(
        selection, check_claims(selection, run.annotations, extraction_run=run.run)
    ))
    return root, bundle, selection, (selection_file, packet_file, import_file, run.path / "run.json",
                                     run.path / "annotations.json", *report_files)


def test_all_claims_artifacts_are_owner_only_and_excluded_from_bundle(tmp_path: Path) -> None:
    root, bundle, _selection, files = _private_artifacts(tmp_path)
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        cursor = path.parent
        while cursor != root and "promotion" in cursor.parts:
            assert stat.S_IMODE(cursor.stat().st_mode) == 0o700
            cursor = cursor.parent
    private = {str(path.relative_to(root)) for path in files}
    members = {item.path for item in (*bundle.documents, bundle.timeline, *bundle.references,
                                     *bundle.retained_records, *bundle.dependencies)}
    assert private.isdisjoint(members)
    assert all("/state/promotion/" not in path for path in members)


def test_private_writer_refuses_parent_and_leaf_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "campaign"; root.mkdir(); outside = tmp_path / "outside"; outside.mkdir()
    (root / "claims-link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PromotionError) as caught:
        _write_owner_only(root, root / "claims-link/private.json", b"secret", conflict_code="CONFLICT")
    assert caught.value.code == "CLAIMS_PATH_INVALID" and not (outside / "private.json").exists()
    safe = root / "safe"; safe.mkdir(); target = outside / "target"; target.write_bytes(b"outside")
    (safe / "private.json").symlink_to(target)
    with pytest.raises(PromotionError) as caught:
        _write_owner_only(root, safe / "private.json", b"secret", conflict_code="CONFLICT")
    assert caught.value.code == "CLAIMS_PATH_INVALID" and target.read_bytes() == b"outside"


def test_packet_registry_and_report_reads_reject_symlinks_and_special_files(tmp_path: Path) -> None:
    root, _bundle, selection, files = _private_artifacts(tmp_path)
    selected_path = root / next(source.path for source in selection.sources
                                if source.source_id == selection.chunks[0].source_id)
    backup = selected_path.read_bytes(); selected_path.unlink(); os.mkfifo(selected_path)
    with pytest.raises(PromotionError) as caught:
        assemble_packet(root, selection)
    assert caught.value.code == "CLAIMS_PATH_INVALID"
    selected_path.unlink(); selected_path.write_bytes(backup)

    registry = root / "docs/entity_registry.yaml"; registry.unlink()
    (tmp_path / "outside-registry.yaml").write_text("entities: []\n")
    registry.symlink_to(tmp_path / "outside-registry.yaml")
    with pytest.raises(PromotionError) as caught:
        _resolve_subject(root, "anything", "entity")
    assert caught.value.code == "CLAIMS_PATH_INVALID"

    report = files[-2]; report.unlink(); os.mkfifo(report)
    with pytest.raises(PromotionError) as caught:
        _private_read(root, report)
    assert caught.value.code == "CLAIMS_REPORT_INVALID"


def test_review_service_hides_gm_evidence_without_capability_and_has_no_mutation_surface(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "campaign"; root.mkdir()
    config = ReviewConfig.model_validate({"origin": "http://review.test", "bind_host": "127.0.0.1", "port": 8765})
    monkeypatch.setattr("pipelines.summary_native.review.web.app.authenticate_token", lambda *_args, **_kwargs: None)
    app = create_review_app(root, "private-review", config)
    marker = "GM-ONLY-LOCATOR-AND-EVIDENCE"
    route = next(route for route in app.routes if getattr(route, "path", "") == "/r/{capability}/items/{item_id}")
    response = asyncio.run(route.endpoint("not-a-capability", "private-item", None))
    assert response.status_code == 404 and marker not in response.body.decode()
    paths = {route.path for route in app.routes}
    assert not any(any(word in path for word in ("publish", "promote", "migrate", "model", "extract")) for path in paths)
