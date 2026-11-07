"""Sanity checks on the spec 039 synthetic campaign fixture (T002/T003)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import npc_publish
from pipelines.summary_native.corpus import build_corpus
from pipelines.summary_native.validate import scan

FIX = Path(__file__).parent / "fixtures" / "delta" / "campaign"
CANARY = "CANARY-SECRET-7f3a"


@pytest.fixture
def camp(tmp_path):
    root = tmp_path / "camp"
    shutil.copytree(FIX, root)
    return root


def test_scan_and_build_corpus(camp, tmp_path):
    sd = camp / "docs" / "summaries"
    report = scan(sd, camp, None, None)
    assert report.blocking_count == 0, report.findings
    assert report.files_in_range == 3
    manifest = build_corpus(sd, camp, report, tmp_path / "out", force=False)
    assert manifest


def test_scan_baseline_range(camp):
    report = scan(camp / "docs" / "summaries", camp, 1, 2)
    assert report.blocking_count == 0 and report.files_in_range == 2


@pytest.mark.parametrize("slug,rng", [("brannoc-ironvein", "ch001-002"), ("envoy-sella-marr", "ch001-001")])
def test_published_dossier_digests(camp, slug, rng):
    text = (camp / "docs/npcs" / f"{slug}.md").read_text(encoding="utf-8")
    actual, recorded = npc_publish.published_body_sha(text)
    assert actual and actual == recorded
    entry = json.loads((camp / "docs/npcs/summary_native/publish_log.json").read_text())[slug]
    assert entry["published_sha256"] == actual
    assert entry["range"] == rng and entry["source"] == "summary_native"


def test_draft_gm_lineage_and_planning(camp):
    for rng, stem, subject in [("ch001-002", "npc_brannoc_ironvein", "Brannoc Ironvein"),
                               ("ch001-001", "npc_envoy_sella_marr", "Envoy Sella Marr")]:
        rd = camp / "docs/npcs/summary_native" / rng
        draft = (rd / "draft" / f"{stem}.md").read_bytes()
        gm = (rd / "gm" / f"{stem}.md").read_text(encoding="utf-8")
        assert f"draft sha256: {hashlib.sha256(draft).hexdigest()}" in gm
        assert "**Verdict: pass**" in (rd / "draft" / f"{stem}.verify.md").read_text()
        assert npc_publish.read_verdict(rd, stem) == "pass"
        items = npc_publish.plan_publish(camp, rd, names=[subject], _signoff_checker=lambda p, d: True)
        assert items[0].refusal is None or "published" in items[0].refusal or "hand" in items[0].refusal


def test_canary_only_in_authored_gm_and_published_brannoc(camp):
    hits = sorted(p.relative_to(camp).as_posix() for p in camp.rglob("*")
                  if p.is_file() and CANARY in p.read_text(encoding="utf-8"))
    assert hits == [
        "docs/npcs/authored/brannoc-ironvein.authored.yaml",
        "docs/npcs/brannoc-ironvein.md",
        "docs/npcs/summary_native/ch001-002/gm/npc_brannoc_ironvein.md",
    ]
