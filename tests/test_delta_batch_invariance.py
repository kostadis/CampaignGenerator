"""T067 / FR-018, Story 4 acceptance 6: batch size does not change what is selected or what happens.

Batch size only chunks an already-chosen member list (``run.materialize_batches``); the same subjects are
selected and the same semantic outcomes result at sizes 1, 2 and 10.
"""

from __future__ import annotations

import json

import pytest

from _delta_run_support import copy_fixture, gm_prep, install_fake, make_apply_plan, resume, sign_stems
from pipelines.summary_native.delta import run as run_mod

SIZES = (1, 2, 10)


def drive(tmp_path, monkeypatch, capsys, size, *, sign=("npc_brannoc_ironvein", "npc_tobin_fenwick")):
    root = copy_fixture(tmp_path / f"b{size}")
    plan = make_apply_plan(root)
    install_fake(monkeypatch)
    plan_obj = plan
    first = run_mod.advance(root, plan_obj, batch_size=size)
    stems = {k: v for k, v in {"npc_brannoc_ironvein": "Brannoc Ironvein",
                               "npc_tobin_fenwick": "Tobin Fenwick"}.items() if k in sign}
    if stems:
        sign_stems(root, capsys, stems)
    gm_prep(root, plan_obj)
    last = run_mod.advance(root, plan_obj, batch_size=size)
    state = run_mod.load_run(run_mod.run_path(root, plan.plan_id))
    batches = json.loads(run_mod.batches_path(root, plan.plan_id).read_text())
    log = json.loads((root / "docs/npcs/summary_native/publish_log.json").read_text())
    return {
        "first": first.status.value, "last": last.status.value, "exit": last.exit_code,
        "outcomes": {m.subject: m.outcome.value for m in state.members},
        "selected": batches["subjects"],
        "bodies": {s: log[s]["published_sha256"] for s in ("brannoc-ironvein", "tobin-fenwick") if s in log},
        "n_batches": len(batches["items"]), "size": batches["batch_size"],
    }


def semantic(result):
    return {k: v for k, v in result.items() if k not in ("n_batches", "size")}


def test_batch_size_changes_chunking_only(tmp_path, monkeypatch, capsys):
    results = {n: drive(tmp_path, monkeypatch, capsys, n) for n in SIZES}
    assert results[1]["n_batches"] == 2 and results[2]["n_batches"] == 1 and results[10]["n_batches"] == 1
    assert semantic(results[1]) == semantic(results[2]) == semantic(results[10])
    assert results[1]["selected"] == ["Brannoc Ironvein", "Tobin Fenwick"]
    assert results[1]["last"] == "complete"
    assert results[1]["outcomes"]["Envoy Sella Marr"] == "unchanged"  # the mention is carried, not drafted


def test_partial_outcomes_are_batch_invariant_too(tmp_path, monkeypatch, capsys):
    results = {n: drive(tmp_path, monkeypatch, capsys, n, sign=("npc_tobin_fenwick",)) for n in SIZES}
    assert semantic(results[1]) == semantic(results[2]) == semantic(results[10])
    assert results[1]["last"] == "partial"
    assert results[1]["outcomes"]["Brannoc Ironvein"] == "held" and results[1]["outcomes"]["Tobin Fenwick"] == "published"


def test_batches_are_materialised_before_dispatch_and_sorted(tmp_path):
    batches = run_mod.materialize_batches(tmp_path, "p", ["Tobin", "brannoc", "Sella", "Aeris"], 3)
    assert batches == [["Aeris", "brannoc", "Sella"], ["Tobin"]]
    record = json.loads(run_mod.batches_path(tmp_path, "p").read_text())
    assert [i["subjects"] for i in record["items"]] == batches and record["batch_size"] == 3
    with pytest.raises(run_mod.DeltaRefusal):
        run_mod.materialize_batches(tmp_path, "p", ["x"], 0)
