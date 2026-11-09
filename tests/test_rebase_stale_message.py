"""T008: CLAIMS_SOURCE_STALE is actionable (spec 040 FR-002, research R8); the code string is unchanged."""

from __future__ import annotations

import hashlib
import json

import pytest

from pipelines.summary_native.claims import selection
from pipelines.summary_native.promotion.errors import PromotionError
from tests.test_delta_claims_custody import _bundle, _ident
from tests import test_rebase_fixture as fixture_tests
from tests import _rebase_fixture as rf


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_discovered_rows_stale_names_chapter_path_expected_actual_and_hint(tmp_path):
    bundle, ch3 = _bundle(tmp_path, "New. [ch 003 / fire]\n")
    (tmp_path / "docs/summaries/003.md").write_text("corrected\n")
    with pytest.raises(PromotionError) as err:
        selection._discovered_rows(tmp_path, bundle)
    msg = str(err.value)
    assert err.value.code == "CLAIMS_SOURCE_STALE"
    assert "chapter 3" in msg and "docs/summaries/003.md" in msg
    assert f"expected sha256 {ch3.sha256}" in msg and f"actual sha256 {_sha('corrected' + chr(10))}" in msg
    assert "run: summary_native delta rebase inspect" in msg


def test_discovered_rows_missing_file_says_missing(tmp_path):
    bundle, _ = _bundle(tmp_path, "New. [ch 003 / fire]\n")
    (tmp_path / "docs/summaries/003.md").unlink()
    with pytest.raises(PromotionError) as err:
        selection._discovered_rows(tmp_path, bundle)
    assert err.value.code == "CLAIMS_SOURCE_STALE" and "actual sha256 missing" in str(err.value)


def test_read_bound_stale_message(tmp_path):
    ident = _ident(tmp_path, "docs/x.md", "one\n")
    (tmp_path / "docs/x.md").write_text("two\n")
    with pytest.raises(PromotionError) as err:
        selection._read_bound(tmp_path, ident)
    msg = str(err.value)
    assert err.value.code == "CLAIMS_SOURCE_STALE" and "docs/x.md" in msg
    assert ident.sha256 in msg and _sha("two\n") in msg and "delta rebase inspect" in msg


def test_fixture_block_message(tmp_path, capsys, monkeypatch):
    fx = rf.build(tmp_path, capsys, monkeypatch)
    with pytest.raises(PromotionError) as err:
        fixture_tests._select_pending(fx)
    assert err.value.code == "CLAIMS_SOURCE_STALE"
    assert "run: summary_native delta rebase inspect" in str(err.value)
