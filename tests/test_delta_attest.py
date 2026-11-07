"""T043: attestation binds the exact published sha256 and never edits the dossier (N5, #585)."""

from __future__ import annotations

import pytest

from _delta_us2 import copy_fixture
from pipelines.summary_native.delta import attest as at
from pipelines.summary_native.delta import npc_baseline as nb
from pipelines.summary_native.delta.errors import EXIT_REFUSAL, EXIT_STALE, EXIT_USAGE, DeltaRefusal


def _sha(root, slug):
    return nb.baseline_for(root, slug).publication["published_sha256"]


def test_attest_binds_digest_and_leaves_dossier_byte_identical(tmp_path):
    root = copy_fixture(tmp_path)
    f = root / "docs/npcs/envoy-sella-marr.md"
    before = f.read_bytes()
    rec = at.attest(root, "Envoy Sella Marr", reason="only a passing mention in ch03",
                    publication_sha256=_sha(root, "envoy-sella-marr"),
                    added_sources=[{"path": "003", "sha256": "0" * 64}])
    assert f.read_bytes() == before
    assert rec.publication_sha256 == _sha(root, "envoy-sella-marr") and rec.horizon == 1
    b = nb.baseline_for(root, "envoy-sella-marr")
    assert b.ok and [a["id"] for a in b.attestations] == [rec.id] and b.horizon == 1


def test_missing_reason_refused(tmp_path):
    root = copy_fixture(tmp_path)
    for r in ("", "   "):
        with pytest.raises(DeltaRefusal) as e:
            at.attest(root, "Envoy Sella Marr", reason=r, publication_sha256=_sha(root, "envoy-sella-marr"))
        assert e.value.exit_code == EXIT_USAGE


def test_wrong_or_stale_digest_refused(tmp_path):
    root = copy_fixture(tmp_path)
    with pytest.raises(DeltaRefusal) as e:
        at.attest(root, "Envoy Sella Marr", reason="r", publication_sha256="a" * 64)
    assert e.value.exit_code == EXIT_STALE
    # the file changed after the GM looked: the bound digest no longer matches
    old = _sha(root, "envoy-sella-marr")
    f = root / "docs/npcs/envoy-sella-marr.md"
    f.write_text(f.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    with pytest.raises(DeltaRefusal) as e:
        at.attest(root, "Envoy Sella Marr", reason="r", publication_sha256=old)
    assert e.value.exit_code == EXIT_STALE


def test_unpublished_subject_refused(tmp_path):
    root = copy_fixture(tmp_path)
    with pytest.raises(DeltaRefusal) as e:
        at.attest(root, "Tobin Fenwick", reason="r", publication_sha256="a" * 64)
    assert e.value.exit_code == EXIT_REFUSAL
