"""Spec 042 US4: per-item custody at publish (FR-011..FR-013, T037-T041)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.summary_native import npc_publish, schema
from tests import _custody_fixture as cf


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


def _publish(fx, **kw):
    rd = Path(fx.rd)
    res = npc_publish.publish(fx.root, rd, names=["Aaa", "Bbb"], receipt_dir=fx.root / "receipts", **kw)
    return {r.slug: r for r in res}


def test_us4_s1_other_npc_publishes_edited_held_naming_draft(fx):
    fx.touch(fx.draft("a"))
    res = _publish(fx)
    assert res["bbb"].outcome == "published"
    a = res["aaa"]
    assert a.outcome == "held"
    assert fx.rel(fx.draft("a")) in a.reason
    assert any(c["path"] == fx.rel(fx.draft("a")) and c["state"] == "changed"
               for c in a.receipt["custody_changed"])
    assert not (fx.root / "docs/npcs/aaa.md").exists()


def test_us4_s2_summary_change_holds_dependent_npc(fx):
    fx.touch(fx.summary(2))
    res = _publish(fx)
    assert res["aaa"].outcome == "published"
    b = res["bbb"]
    assert b.outcome == "held"
    assert "NPC_DRAFT_SIGNOFF_STALE" in b.reason
    assert "docs/summaries/002-b.md" in b.reason
    assert f"--expected-generation {fx.generation}" in b.reason and "<n>" not in b.reason
    assert {"path": "docs/summaries/002-b.md", "state": "changed"} in b.receipt["custody_changed"]


def test_us4_s3_draft_changed_between_check_and_write_is_held(fx):
    real = npc_publish._current_draft_signoff

    def racing(path, digest):
        ok = real(fx.root, path, digest)
        if ok and Path(path).name == "npc_a.md":
            Path(path).write_bytes(Path(path).read_bytes() + b"\nrace.\n")
        return ok

    res = _publish(fx, _signoff_checker=racing)
    a = res["aaa"]
    assert a.outcome == "held"
    assert "NPC_DRAFT_CHANGED_AT_WRITE" in a.reason and fx.rel(fx.draft("a")) in a.reason
    assert a.receipt["custody_changed"] == [{"path": fx.rel(fx.draft("a")), "state": "changed"}]
    assert not (fx.root / "docs/npcs/aaa.md").exists()
    assert res["bbb"].outcome == "published"


def test_published_body_is_bound_to_signed_draft(fx):
    res = _publish(fx)
    assert res["bbb"].outcome == "published"
    gm = fx.gm("b").read_text(encoding="utf-8")
    header_sha = npc_publish._GM_HEADER_RE.match(gm).group("draft")
    assert header_sha == npc_publish.sha256_text(fx.draft("b").read_bytes())
    target = (fx.root / "docs/npcs/bbb.md").read_text(encoding="utf-8")
    assert npc_publish.rewrite_manual_citations(gm[npc_publish._GM_HEADER_RE.match(gm).end():]) in target


def test_bool_signoff_api_unchanged(fx):
    d = fx.draft("a")
    sha = npc_publish.sha256_text(d.read_bytes())
    cur = npc_publish._current_draft_signoff(fx.root, d, sha)
    assert cur is True
    fx.touch(fx.summary(1))
    assert npc_publish._current_draft_signoff(fx.root, d, sha) is False
    fx.restore(fx.summary(1))
    res = _publish(fx, _signoff_checker=lambda p, dg: True)
    assert res["aaa"].outcome == "published" and res["bbb"].outcome == "published"
