"""T021: the grounding baseline binds the ACTIVE generation, lists drift, and gates on adoption."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone

import pytest

from pipelines.summary_native.delta import baseline as bl
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal
from pipelines.summary_native.promotion.models import (
    ContentIdentity, GenerationKind, GenerationManifest, RangeSelection,
)
from tests.support.delta_grounding_fixture import (
    DOCUMENTS, GENERATION_ID, digest_tree, edit_live_document, history_digests, live_path,
    make_grounding_campaign, published_path,
)

SHA = "a" * 64


def test_binds_active_generation_and_four_document_digests(tmp_path):
    root = make_grounding_campaign(tmp_path)
    b = bl.bind(root)
    assert b.generation_id == GENERATION_ID
    assert len(b.manifest_sha256) == 64 and b.activation_id == "baseline-fixture"
    assert [d.name for d in b.documents] == list(DOCUMENTS)
    for d in b.documents:
        assert d.origin_sha256 == d.live_sha256  # no drift yet
        assert d.origin_ref.endswith(f"published/{d.name}.md")
        assert d.approval_ref.startswith("baseline-fixture@")
    assert b.status == "valid" and b.usable and b.drift == []


def test_a_newer_directory_is_never_selected(tmp_path):
    root = make_grounding_campaign(tmp_path)
    before = bl.bind(root)
    generations = root / "docs/grounding/generations"
    # a later-sorting, fully copied directory that is NOT the active generation
    shutil.copytree(generations / GENERATION_ID, generations / "zzz-newer-generation")
    (generations / "zzz-newer-generation" / "published" / "world_state.md").write_text("tampered\n")
    after = bl.bind(root)
    assert after.generation_id == GENERATION_ID
    assert after.manifest_sha256 == before.manifest_sha256
    assert [d.origin_sha256 for d in after.documents] == [d.origin_sha256 for d in before.documents]


def test_drift_is_listed_with_stable_hunk_ids_and_blocks_use(tmp_path):
    root = make_grounding_campaign(tmp_path, edit_live=True)
    b = bl.bind(root)
    assert b.status == "unadopted" and not b.usable
    assert [h.hunk_id for h in b.drift] == ["world_state#1", "world_state#2"]
    assert b.drift[0].kind == "replace" and "HAND-EDITED" in b.drift[0].diff
    changed = {d.name for d in b.documents if d.origin_sha256 != d.live_sha256}
    assert changed == {"world_state"}
    again = bl.bind(root)
    assert [(h.hunk_id, h.hunk_sha256) for h in again.drift] == [(h.hunk_id, h.hunk_sha256) for h in b.drift]
    with pytest.raises(DeltaRefusal, match="unreviewed drift") as exc:
        bl.baseline_documents(b, root)
    assert exc.value.exit_code == EXIT_REFUSAL


def test_adopt_requires_every_hunk_and_never_rewrites_history(tmp_path):
    root = make_grounding_campaign(tmp_path, edit_live=True)
    history = history_digests(root)
    with pytest.raises(DeltaRefusal, match="unresolved drift") as exc:
        bl.adopt(root, {"world_state#1": "accept"})
    assert exc.value.exit_code == EXIT_REFUSAL
    assert not (root / "docs/summaries/delta/baseline").exists()  # nothing written on refusal
    with pytest.raises(DeltaRefusal, match="no such drift hunk") as exc:
        bl.adopt(root, {"world_state#1": "accept", "world_state#2": "accept", "party#1": "accept"})
    assert exc.value.exit_code == EXIT_STALE

    record = bl.adopt(root, {"world_state#1": "accept", "world_state#2": "reject"})
    assert record.revision == 1
    assert [(d.hunk, d.disposition) for d in record.drift] == [
        ("world_state#1", "accept"), ("world_state#2", "reject")]
    assert history_digests(root) == history  # generations, activations, receipts untouched

    b = bl.bind(root)
    assert b.status == "adopted" and b.usable and b.adoption.revision == 1
    docs = bl.baseline_documents(b, root)
    text = docs["world_state"].decode()
    assert "HAND-EDITED" in text                       # accepted hunk applied
    assert "A hand-added closing line." not in text    # rejected hunk reverts to origin
    assert docs["party"] == published_path(root, "party").read_bytes()

    second = bl.adopt(root, {"world_state#1": "reject", "world_state#2": "reject"})  # a new revision
    assert second.revision == 2
    assert (root / "docs/summaries/delta/baseline/adoption-legacy-fixture-r1.json").is_file()
    assert "HAND-EDITED" not in bl.baseline_documents(bl.bind(root), root)["world_state"].decode()


def test_a_later_live_edit_makes_an_old_adoption_stale(tmp_path):
    root = make_grounding_campaign(tmp_path, edit_live=True)
    bl.adopt(root, {"world_state#1": "accept", "world_state#2": "accept"})
    assert bl.bind(root).status == "adopted"
    with live_path(root, "party").open("a", encoding="utf-8") as f:
        f.write("another late edit\n")
    b = bl.bind(root)
    assert b.status == "unadopted"
    assert "party#1" in {h.hunk_id for h in b.drift}


def test_clean_baseline_can_be_adopted_explicitly(tmp_path):
    root = make_grounding_campaign(tmp_path)
    record = bl.adopt(root, {})
    assert record.drift == []
    assert bl.bind(root).status == "adopted"


def test_parse_resolve_rejects_malformed_pairs():
    assert bl.parse_resolve(["world_state#1=accept", "party#3=reject"]) == {
        "world_state#1": "accept", "party#3": "reject"}
    for bad in ("world_state#1", "world_state#1=maybe", "nope#1=accept", "world_state#x=accept"):
        with pytest.raises(DeltaRefusal) as exc:
            bl.parse_resolve([bad])
        assert exc.value.exit_code == EXIT_USAGE
    with pytest.raises(DeltaRefusal):
        bl.parse_resolve(["world_state#1=accept", "world_state#1=reject"])


def test_unmanaged_campaign_refuses(tmp_path):
    with pytest.raises(DeltaRefusal, match="no managed grounding generation"):
        bl.bind(tmp_path)


def _manifest(through):
    members = (
        ContentIdentity(path="canon_events_timeline.md", sha256=SHA, size=1),
        ContentIdentity(path="reference/factions.md", sha256="b" * 64, size=1),
        ContentIdentity(path="reference/npcs.md", sha256="c" * 64, size=1),
    )
    return GenerationManifest(
        generation_id="g1", operation_id="o1", campaign_id="c1",
        selected_range=RangeSelection(since=1, until=through, out_root="docs/summary_native") if through else None,
        kind=GenerationKind.PUBLISHED if through else GenerationKind.LEGACY_ADOPTION,
        members=members, retained_records=(), external_dependencies=(),
        published_path="docs/grounding/generations/g1/published",
        live_path="docs/grounding/generations/g1/live", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        manifest_sha256=SHA)


def test_member_coverage_comes_from_the_manifest_only(tmp_path):
    members = {m.name: m for m in bl._members(_manifest(72), tmp_path)}
    assert members["timeline"].coverage_through == 72
    assert members["reference_tree"].coverage_through == 72
    assert members["timeline"].sha256 == SHA and members["timeline"].gaps == []
    # no retained reading-contract records: a gap is stated, never papered over by the range
    rc = members["reading_contract_records"]
    assert rc.coverage_through is None and rc.gaps
    legacy = {m.name: m for m in bl._members(_manifest(None), tmp_path)}
    assert legacy["timeline"].coverage_through is None and legacy["timeline"].gaps


def test_live_prose_citing_a_later_chapter_does_not_raise_coverage(tmp_path):
    root = make_grounding_campaign(tmp_path)
    before = {m.name: m.coverage_through for m in bl.bind(root).members}
    with live_path(root, "world_state").open("a", encoding="utf-8") as f:
        f.write("- Something happened later. [ch 074 / entry]\n")
    after = bl.bind(root)
    assert {m.name: m.coverage_through for m in after.members} == before
    assert all((c is None or c < 74) for c in after.coverage.values())
