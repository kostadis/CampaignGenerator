"""Spec 042 code-review fixes: one regression test per finding.

Governing rule: an item's dependency set is never smaller than what the item rests on; store,
refresh and publish agree because they all ask ``custody.stale_report`` / ``dependency_sets``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipelines.summary_native import npc_publish
from pipelines.summary_native.review import custody, delegated
from pipelines.summary_native.review.custody import FileState
from pipelines.summary_native.review.store import ReviewStoreError, refresh_review, review_status
from tests import _custody_fixture as cf

KIND = "npc_verification"


@pytest.fixture
def fx(tmp_path):
    f = cf.build(tmp_path)
    for npc, subject in (("a", "Aaa"), ("b", "Bbb")):
        rc, out = f.sign(npc)
        assert rc == 0, out
        v = f.draft(npc).with_name(f"npc_{npc}.verify.md")
        if not v.is_file():
            v.write_text(f"# Verification: {subject}\n\n**Verdict: pass**\n", encoding="utf-8")
    return f


def _publish(fx, root=None, rd=None, names=("Aaa", "Bbb"), **kw):
    res = npc_publish.publish(root or fx.root, rd or fx.rd, names=list(names),
                              receipt_dir=fx.root / "receipts", **kw)
    return {r.slug: r for r in res}


# ── 1. refresh must not preserve a sign-off whose NON-bound dependency changed ──

def test_f1_refresh_stales_signoff_when_unbound_summary_changed(fx):
    fx.touch(fx.summary(2))  # B's evidence names 002; B's sign-off binds only the draft
    out = refresh_review(fx.root, fx.review_id, expected_generation=fx.generation)
    b_sign = fx.signoff("b").item_id
    assert b_sign in out["stale_item_ids"]
    assert fx.signoff("a").item_id in out["preserved_item_ids"]
    res = _publish(fx)
    assert res["bbb"].outcome == "held"
    assert res["aaa"].outcome == "published"


# ── 2. a relative campaign dir ───────────────────────────────────────────────

def test_f2_relative_root_reports_only_the_edited_file(fx, monkeypatch):
    fx.touch(fx.summary(2))
    monkeypatch.chdir(fx.root.parent)
    res = _publish(fx, root=Path("camp"), rd=Path("camp") / fx.rd.relative_to(fx.root))
    b = res["bbb"]
    assert b.outcome == "held"
    assert b.receipt["custody_changed"] == [{"path": "docs/summaries/002-b.md", "state": "changed"}]
    probe = custody.disk_probe(Path("camp"))
    _m, cust, _i = fx.snapshot()
    src = next(s for s in cust.sources if s.path == "docs/summaries/001-a.md")
    assert probe(src) is FileState.current


# ── 3. corpus-dependent findings depend on every summary ─────────────────────

def _with_code(item, code):
    diags = tuple(d.model_copy(update={"legacy_code": code}) for d in item.diagnostics)
    return item.model_copy(update={"diagnostics": diags})


@pytest.mark.parametrize("code", ["outside-evidence", "invalid", "not-found"])
def test_f3_corpus_dependent_finding_depends_on_all_summaries(fx, code):
    manifest, cust, items = fx.snapshot()
    target = fx.findings("a")[0]
    items = [_with_code(i, code) if i.item_id == target.item_id else i for i in items]
    deps = custody.dependency_sets(KIND, cust, items, [target.item_id], custody.disk_probe(fx.root))
    dep = deps[target.item_id]
    all_summaries = {s.source_id for s in cust.sources if custody.role_of(s.source_id) is custody.SourceRole.summary}
    assert dep.summary_basis == "corpus" and all_summaries <= dep.source_ids
    # changing a chapter the evidence does not name stales it
    c3 = next(s for s in cust.sources if s.path == "docs/summaries/003-c.md")
    probe = custody.disk_probe(fx.root).with_overrides({c3.path: FileState.changed})
    report = custody.stale_report(KIND, cust, items, [target.item_id], probe)
    assert target.item_id in report.stale


def test_f3_advisory_and_signoff_keep_evidence_named_set(fx):
    manifest, cust, items = fx.snapshot()
    deps = custody.dependency_sets(KIND, cust, items, None, custody.disk_probe(fx.root))
    assert deps[fx.findings("a")[0].item_id].summary_basis == "evidence_sources"
    assert deps[fx.signoff("a").item_id].summary_basis == "evidence_sources"


def test_f3_message_referencing_the_corpus_counts(fx):
    manifest, cust, items = fx.snapshot()
    target = fx.findings("a")[0]
    diags = tuple(d.model_copy(update={"message": d.message + " (verbatim in the summaries, not in evidence)"})
                  for d in target.diagnostics)
    items = [i.model_copy(update={"diagnostics": diags}) if i.item_id == target.item_id else i for i in items]
    dep = custody.dependency_sets(KIND, cust, items, [target.item_id], custody.disk_probe(fx.root))[target.item_id]
    assert dep.summary_basis == "corpus"


# ── 4. submit_decisions refuses before any batch is written ──────────────────

class _Cfg:
    max_batch_decisions = 1
    max_note_chars = 2000


def _decision(item, verdict, disposition):
    return {"item_id": item.item_id, "item_revision": item.revision, "review_digest": item.review_digest,
            "expected_decision_revision": 0, "verdict": verdict, "disposition": disposition, "note": "ok"}


def test_f4_stale_item_in_last_batch_writes_nothing(fx, monkeypatch):
    monkeypatch.setattr(delegated, "load_campaign_review_config", lambda root: _Cfg())
    fx.touch(fx.summary(2))
    decisions = [
        _decision(fx.findings("a")[0], "approve", "accept_no_change"),
        _decision(fx.signoff("c"), "discuss", "defer"),
        _decision(fx.findings("b")[0], "approve", "accept_no_change"),
    ]
    before = fx.review_tree_sha()
    with pytest.raises(ReviewStoreError) as caught:
        delegated.submit_decisions(fx.root, fx.review_id, generation=fx.generation, reviewer="GM",
                                   decisions=decisions, prefix="t")
    assert caught.value.code == "REVIEW_STALE_CUSTODY"
    assert "earlier batch" not in str(caught.value)
    assert "nothing was saved" in str(caught.value)
    assert [e["item_id"] for e in caught.value.detail["stale_items"]] == [fx.findings("b")[0].item_id]
    assert fx.review_tree_sha() == before


# ── 5+6. publish freshness is computed once, through custody.stale_report ───

def test_f5_no_dependency_signoff_is_held_at_publish(fx, monkeypatch):
    real = custody.dependency_sets

    def empty_for_b(kind, cust, items, item_ids, state):
        out = real(kind, cust, items, item_ids, state)
        b = fx.signoff("b").item_id
        if b in out:
            out[b] = type(out[b])(item_id=b, npc=out[b].npc, npc_key=out[b].npc_key,
                                  source_ids=frozenset(), evidence_basis="x", summary_basis="y")
        return out

    monkeypatch.setattr(custody, "dependency_sets", empty_for_b)
    res = _publish(fx)
    assert res["bbb"].outcome == "held"
    assert res["aaa"].outcome == "published"


def test_f6_patched_checker_seam_is_final(fx):
    res = _publish(fx, _signoff_checker=lambda path, digest: False)
    assert res["aaa"].outcome == "held" and res["bbb"].outcome == "held"


def test_f6_default_checker_computes_freshness_once_per_npc(fx, monkeypatch):
    calls = []
    real = npc_publish.signoff_freshness

    def counting(*a, **k):
        calls.append(Path(a[1]).name)
        return real(*a, **k)

    monkeypatch.setattr(npc_publish, "signoff_freshness", counting)
    fx.touch(fx.summary(2))
    res = _publish(fx)
    assert res["bbb"].outcome == "held"
    assert calls.count("npc_b.md") == 1 and calls.count("npc_a.md") == 1


# ── 7. review status: one locked read; unreadable custody path is reported ───

def test_f7_symlinked_summary_is_reported_unreadable(fx):
    target = fx.summary(1)
    real = target.with_name("elsewhere.md")
    real.write_bytes(target.read_bytes())
    target.unlink()
    os.symlink(real, target)
    status = review_status(fx.root, fx.review_id)
    assert status["item_count"] > 0 and "counts" in status
    rel = "docs/summaries/001-a.md"
    entry = next(f for f in status["changed_files"] if f["path"] == rel)
    assert entry["state"] == "unreadable"
    assert any(g["npc"] == "a" for g in status["stale_by_npc"])


# ── 8. a binding whose source_id is not in custody ───────────────────────────

def _renamed_ids(cust, mapping):
    return cust.model_copy(update={"sources": tuple(
        s.model_copy(update={"source_id": mapping.get(s.source_id, s.source_id)}) for s in cust.sources)})


def test_f8_binding_with_unknown_source_id_resolves_by_path(fx):
    _m, cust, items = fx.snapshot()
    finding = fx.findings("a")[0]
    ev = next(b for b in finding.input_bindings if custody.role_of(b.source_id) is custody.SourceRole.evidence)
    moved = _renamed_ids(cust, {ev.source_id: "evidence-renamedxx"})
    assert "evidence-renamedxx" in custody._Index(moved, items).bound_ids(finding)


def test_f8_binding_with_unknown_id_and_path_widens_to_its_role(fx):
    _m, cust, items = fx.snapshot()
    finding = fx.findings("a")[0]
    ev = next(b for b in finding.input_bindings if custody.role_of(b.source_id) is custody.SourceRole.evidence)
    gone = cust.model_copy(update={"sources": tuple(s for s in cust.sources if s.source_id != ev.source_id)})
    every_evidence = {s.source_id for s in gone.sources if custody.role_of(s.source_id) is custody.SourceRole.evidence}
    assert every_evidence and every_evidence <= custody._Index(gone, items).bound_ids(finding)


# ── 9. web detail reports what the caps omitted ──────────────────────────────

def test_f9_custody_detail_reports_truncation():
    from pipelines.summary_native.review.web.app import custody_detail

    files = [{"path": f"f{n}.md", "source_id": "s", "role": "summary", "state": "changed",
              "items": [{"item_id": f"i{k}", "npc": None, "action": "x"} for k in range(5)]} for n in range(7)]
    data = {"changed_files": files,
            "stale_items": [{"item_id": f"i{n}", "npc": None, "paths": []} for n in range(9)],
            "remedy": {"command": "c"}}
    shaped = custody_detail(data, 3)
    assert shaped["truncated"] == {"changed_files": 4, "items": 3 * 2, "stale_items": 6}
    assert "truncated" not in custody_detail({**data, "changed_files": files[:1], "stale_items": []}, 10)


def test_f9_viewer_renders_and_n_more():
    js = (Path(__file__).resolve().parents[1] / "pipelines/summary_native/review/web/viewer.js").read_text()
    assert "detail.truncated" in js and "and ${cut[k]} more" in js
