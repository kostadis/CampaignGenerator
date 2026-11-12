"""Spec 042 T045: read-only replay of per-item custody on the real stormgiants NPC review.

Skipped unless ``STORMGIANTS`` points at a checkout containing ``docs/reviews/npc-review-6ee694eebf5b``.
Nothing is written: file changes are simulated with the custody probe's override, on a baseline
that treats every RECORDED source as current (the live files have drifted since the review was
built; the review's own custody is what is being replayed). Evidence bytes are read from disk
only to parse which summaries an evidence file names.
"""
from __future__ import annotations

import functools
import hashlib
import os
import time
from collections import defaultdict
from pathlib import Path

import pytest

from pipelines.summary_native.review import custody
from pipelines.summary_native.review.custody import FileState, SourceRole, role_of
from pipelines.summary_native.review.store import read_snapshot

REVIEW_ID = "npc-review-6ee694eebf5b"
SEER = "docs/summaries/010-session-the-seer.md"
_ROOT = os.environ.get("STORMGIANTS")
_ROOT_PATH = Path(_ROOT).expanduser() if _ROOT else None
_REVIEW = _ROOT_PATH / "docs" / "reviews" / REVIEW_ID if _ROOT_PATH else None

pytestmark = pytest.mark.skipif(
    _REVIEW is None or not _REVIEW.is_dir(),
    reason="STORMGIANTS must point at a checkout containing docs/reviews/" + REVIEW_ID)


def _tree_fingerprint(top: Path) -> dict[str, tuple[int, str]]:
    out = {}
    for p in sorted(top.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(top))] = (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


class RecordedBaseline:
    """Every recorded source is current; bytes (for parsing evidence) come from the live disk."""

    def __init__(self, root: Path):
        self.disk = custody.disk_probe(root)

    def __call__(self, source):
        return FileState.current

    def read(self, source):
        return self.disk.read(source)


@pytest.fixture(scope="module")
def replay():
    before = _tree_fingerprint(_REVIEW)
    manifest, cust, items = read_snapshot(_ROOT_PATH, REVIEW_ID)
    base = RecordedBaseline(_ROOT_PATH)
    # Parsing an evidence file is pure in its bytes; memoise it so ~250 whole-review reports stay fast.
    original = custody.evidence_summary_paths
    cached = functools.lru_cache(maxsize=None)(
        lambda data, paths: original(data, paths))
    custody.evidence_summary_paths = lambda data, paths: cached(data, frozenset(paths))
    started = time.monotonic()
    try:
        yield {"kind": manifest.kind, "custody": cust, "items": items, "base": base,
               "before": before, "started": started}
    finally:
        custody.evidence_summary_paths = original


def _report(r, overrides=None):
    probe = custody.OverrideProbe(r["base"], overrides or {})
    return custody.stale_report(r["kind"], r["custody"], r["items"], None, probe)


def _path_id(r):
    return {s.path: s.source_id for s in r["custody"].sources}


def test_baseline_nothing_stale_and_basis(replay):
    r = replay
    report = _report(r)
    assert report.stale == {} and report.changed_files == ()
    deps = report.dependency_sets
    npc_deps = [d for d in deps.values() if d.evidence_basis != "not_applicable"]
    evidence_files = [s for s in r["custody"].sources if role_of(s.source_id) is SourceRole.evidence]
    fallback = [d for d in npc_deps if d.evidence_basis == "fallback_all_evidence"
                or d.summary_basis == "fallback_all_summaries"]
    bases = defaultdict(int)
    for d in npc_deps:
        bases[(d.evidence_basis, d.summary_basis)] += 1
    print(f"\n[custody replay] items={len(r['items'])} npc_item_deps={len(npc_deps)} "
          f"evidence_files={len(evidence_files)} fallback_items={len(fallback)} bases={dict(bases)}")
    assert len(evidence_files) == 164
    assert npc_deps and not fallback, f"fallback items: {[d.item_id for d in fallback][:10]}"
    assert all(d.summary_basis == "evidence_sources" for d in npc_deps)


def test_sc005a_each_draft_stales_only_its_npc(replay):
    r = replay
    ids = _path_id(r)
    drafts = [s.path for s in r["custody"].sources if role_of(s.source_id) is SourceRole.draft]
    assert len(drafts) == 164
    bound_to: dict[str, set[str]] = defaultdict(set)
    for item in r["items"]:
        for b in item.input_bindings:
            if role_of(b.source_id) is SourceRole.draft:
                bound_to[b.path].add(item.item_id)
    sizes = []
    for path in drafts:
        report = _report(r, {path: FileState.changed})
        assert set(report.stale) == bound_to[path], path
        assert bound_to[path], f"draft {path} is bound by no item"
        assert {report.dependency_sets[i].npc_key for i in report.stale} == {path}
        assert {c.path for c in report.changed_files} == {path}
        sizes.append(len(report.stale))
    print(f"[custody replay] SC-005a: {len(drafts)} drafts, stale items per draft "
          f"min={min(sizes)} max={max(sizes)} total={sum(sizes)}; set equality held for all")


def test_sc005b_seer_summary_stales_only_naming_npcs(replay):
    r = replay
    report = _report(r, {SEER: FileState.changed})
    stale_npcs = {report.dependency_sets[i].npc_key for i in report.stale}
    # Independent oracle: an NPC depends on the summary if one of its evidence files names it
    # (text), or if its dependency set fell back to every summary.
    index = custody._Index(r["custody"], r["items"])
    by_id = index.by_id
    expect, fallback_npcs = set(), set()
    base = _report(r)
    for item in r["items"]:
        dep = base.dependency_sets[item.item_id]
        if dep.evidence_basis == "not_applicable":
            continue
        if dep.summary_basis == "corpus":  # corpus-dependent findings rest on every summary (042 review fix 3)
            expect.add(dep.npc_key)
            continue
        if dep.summary_basis == "fallback_all_summaries":
            fallback_npcs.add(dep.npc_key)
            expect.add(dep.npc_key)
            continue
        evidence, _basis = index.evidence_of(item)
        for sid in evidence:
            data = r["base"].read(by_id[sid]) or b""
            if SEER.encode() in data:
                expect.add(dep.npc_key)
    assert stale_npcs == expect
    names = sorted(report.dependency_sets[i].npc for i in report.stale)
    print(f"[custody replay] SC-005b: {SEER} stales {len(report.stale)} items across {len(stale_npcs)} NPCs "
          f"({sorted({n for n in names if n})}); fallback NPCs={len(fallback_npcs)}")
    assert not fallback_npcs


def test_sc002_stale_iff_dependency(replay):
    r = replay
    base = _report(r)
    deps = base.dependency_sets
    ids = _path_id(r)
    summaries = [s.path for s in r["custody"].sources if role_of(s.source_id) is SourceRole.summary]
    evidence = [s.path for s in r["custody"].sources if role_of(s.source_id) is SourceRole.evidence]
    sample = summaries + evidence[::8] + [p for p in evidence if "the-seer" in p or "seer" in p][:3]
    checked = false_refuse = missed = 0
    for path in sample:
        sid = ids[path]
        expected = {i for i, d in deps.items() if sid in d.source_ids}
        got = set(_report(r, {path: FileState.changed}).stale)
        false_refuse += len(got - expected)
        missed += len(expected - got)
        checked += 1
    print(f"[custody replay] SC-002: {len(summaries)} summaries + {checked - len(summaries)} evidence files "
          f"checked; false refusals={false_refuse} missed refusals={missed}")
    assert false_refuse == 0 and missed == 0
    # Missing and unreadable states refuse the same way as changed.
    for state in (FileState.missing, FileState.unreadable):
        path = summaries[0]
        expected = {i for i, d in deps.items() if ids[path] in d.source_ids}
        assert set(_report(r, {path: state}).stale) == expected


def test_nothing_was_written(replay):
    after = _tree_fingerprint(_REVIEW)
    assert after == replay["before"]
    print(f"[custody replay] read-only: review dir unchanged ({len(after)} files); "
          f"elapsed {time.monotonic() - replay['started']:.1f}s")
