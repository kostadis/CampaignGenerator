"""T032: inherited citations resolve through baseline custody (spec 039 FR-016)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pipelines.summary_native.claims import selection
from pipelines.summary_native.promotion.errors import PromotionError
from pipelines.summary_native.promotion.models import (
    BundleSelection, ContentIdentity, DocumentMember, GroundingDocument, PathIdentity, RangeSelection,
)

ALIASES = ("docs/world_state.md", "docs/campaign_state.md", "docs/party.md", "docs/planning.md",
           "docs/canon_events_timeline.md", "docs/reference")


def _ident(root: Path, rel: str, text: str) -> ContentIdentity:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    data = text.encode()
    return ContentIdentity(path=rel, sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def _bundle(root: Path, doc_text: str):
    docs = tuple(
        DocumentMember(document_id=d, **_ident(root, f"drafts/{d.value}.md", doc_text if d is GroundingDocument.WORLD_STATE else "none\n").model_dump())
        for d in GroundingDocument
    )
    rng = root / "out/ch003-003"
    rng.mkdir(parents=True)
    ch3 = _ident(root, "docs/summaries/003.md", "chapter three\n")
    (rng / "manifest.json").write_text(json.dumps({"files": [{"chapter": 3, "path": ch3.path, "sha256": ch3.sha256}]}))
    return BundleSelection(
        campaign_id="c", selected_range=RangeSelection(since=3, until=3, out_root="out"),
        documents=docs, timeline=_ident(root, "drafts/timeline.md", "t\n"), references=(),
        retained_records=(), dependencies=(), config_identity=_ident(root, "config/config.yaml", "x: 1\n"),
        alias_identities=tuple(PathIdentity(path=a, kind="absent") for a in ALIASES),
        review_id="r1", rule_versions=("1",),
    ), ch3


def test_default_behavior_unchanged_refuses_inherited_citation(tmp_path):
    bundle, _ = _bundle(tmp_path, "Brannoc forged it. [ch 001 / forge]\n")
    with pytest.raises(PromotionError, match="absent from the selected corpus"):
        selection._discovered_rows(tmp_path, bundle)


def test_resolver_resolves_inherited_citation_through_custody(tmp_path):
    bundle, _ = _bundle(tmp_path, "Brannoc forged it. [ch 001 / forge]\nNew. [ch 003 / fire]\n")
    base = _ident(tmp_path, "baseline/001.md", "chapter one\n")
    calls = []

    def resolver(chapter, entry):
        calls.append((chapter, entry))
        return base if chapter == 1 else None

    rows, _amb = selection._discovered_rows(tmp_path, bundle, resolver)
    paths = {row[0].path for row in rows}
    assert "baseline/001.md" in paths and "docs/summaries/003.md" in paths
    assert calls == [(1, "forge")]  # the selected chapter never consults custody


def test_removed_support_gives_targeted_repair_message(tmp_path):
    bundle, _ = _bundle(tmp_path, "Gone. [ch 001 / forge]\n")
    with pytest.raises(PromotionError) as err:
        selection._discovered_rows(tmp_path, bundle, lambda c, e: None)
    assert "[ch 001 / forge]" in str(err.value) and "baseline custody" in str(err.value)
    assert err.value.code == "CLAIMS_SOURCE_MISSING"


def test_stale_custody_bytes_refused(tmp_path):
    bundle, _ = _bundle(tmp_path, "X. [ch 001 / forge]\n")
    base = _ident(tmp_path, "baseline/001.md", "chapter one\n")
    (tmp_path / "baseline/001.md").write_text("tampered\n")
    with pytest.raises(PromotionError, match="stale"):
        selection._discovered_rows(tmp_path, bundle, lambda c, e: base)
