"""Dossier selection (T019, FR-017): recent counted from range end, recurring >=, named."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from pipelines.summary_native import select
from pipelines.summary_native.cli import main
from pipelines.summary_native.select import Dossier, SelectionError, select_dossiers

FIX = Path(__file__).parent / "fixtures" / "summary_native"


def D(stem, subject, n, lo, hi, cat="npc"):
    return Dossier(stem, subject, cat, n, lo, hi, Path(f"dossiers/{stem}.md"))


DOSSIERS = [
    D("npc_a", "Alpha", 1, 60, 70),   # recent for range_end 70, recent 4 (>=67)
    D("npc_b", "Beta", 12, 1, 50),    # recurring
    D("npc_c", "Cee", 10, 1, 66),     # recurring at exactly the threshold
    D("npc_d", "Dee", 9, 1, 66),      # neither
    D("npc_e", "Eee", 2, 67, 67),     # recent at the boundary
]


def test_recent_counted_from_range_end_not_newest_dossier():
    # Newest dossier ends at 70 but the range ends at 100: nothing is recent.
    sel = select_dossiers(DOSSIERS, range_until=100, recent_chapters=4, recurring_min=10)
    assert {i.dossier.stem for i in sel.items if i.reason == "recent"} == set()
    sel = select_dossiers(DOSSIERS, range_until=70, recent_chapters=4, recurring_min=10)
    assert {i.dossier.stem for i in sel.items if i.reason == "recent"} == {"npc_a", "npc_e"}


def test_recurring_uses_greater_or_equal():
    sel = select_dossiers(DOSSIERS, 70, 4, 10)
    assert {i.dossier.stem for i in sel.items if i.reason == "recurring"} == {"npc_b", "npc_c"}
    assert "npc_d" not in {i.dossier.stem for i in sel.items}


def test_named_force_includes_and_wins_precedence():
    sel = select_dossiers(DOSSIERS, 70, 4, 10, named=("dee", "ALPHA"))
    reasons = {i.dossier.stem: i.reason for i in sel.items}
    assert reasons["npc_d"] == "named" and reasons["npc_a"] == "named"
    assert [i.dossier.stem for i in sel.items][:2] == ["npc_d", "npc_a"]  # named first, as given


def test_unmatched_named_is_an_error():
    with pytest.raises(SelectionError, match="Nobody"):
        select_dossiers(DOSSIERS, 70, 4, 10, named=("Nobody",))


def test_recent_zero_means_all_recent():
    sel = select_dossiers(DOSSIERS, 70, 0, 10)
    assert {i.dossier.stem for i in sel.items if i.reason == "recent"} == {d.stem for d in DOSSIERS}


def test_deterministic_order():
    sel = select_dossiers(DOSSIERS, 70, 4, 10)
    assert [i.dossier.stem for i in sel.items] == ["npc_a", "npc_e", "npc_b", "npc_c"]
    assert sel.to_json() == select_dossiers(list(reversed(DOSSIERS)), 70, 4, 10).to_json()


def test_to_json_records_reason_last_chapter_and_count():
    import json

    data = json.loads(select_dossiers(DOSSIERS, 70, 4, 10).to_json())
    assert data["range_end"] == 70 and data["recent_chapters"] == 4 and data["recurring_min"] == 10
    first = data["selected"][0]
    assert first == {
        "dossier": "npc_a", "subject": "Alpha", "reason": "recent", "last_chapter": 70, "n_observations": 1,
    }


def _tree_digest(d: Path):
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def test_reads_built_corpus_and_leaves_it_unchanged(tmp_path, monkeypatch):
    root = tmp_path / "camp"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text("paths: {}\n")
    shutil.copytree(FIX / "clean", root / "summaries")
    monkeypatch.chdir(root)
    assert main(["build", "--summaries-dir", "summaries"]) == 0
    rd = root / "docs/summary_native/ch002-005"
    before = _tree_digest(rd)
    ds = select.read_corpus_dossiers(rd)
    by = {d.subject: d for d in ds}
    assert by["Manshoon"].category == "npc" and by["Manshoon"].n_observations == 2
    assert (by["Manshoon"].first_chapter, by["Manshoon"].last_chapter) == (2, 5)
    sel = select_dossiers(ds, 5, 1, 99, named=("Candlekeep",))
    sel.to_json()
    assert _tree_digest(rd) == before
