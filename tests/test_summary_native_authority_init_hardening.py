from __future__ import annotations

import json

import pytest

from pipelines.summary_native.authority import AuthorityError, ledger_path, new_ledger
from pipelines.summary_native.authority_apply import (
    authority_dir,
    initialize_ledger,
    ledger_tip_path,
    pending_transaction,
    recover_transaction,
    validate_ledger_tip,
)
from pipelines.summary_native.cli import main


@pytest.mark.parametrize("duplicate_key", ["source", "audience", "status"])
def test_staged_record_yaml_refuses_duplicate_nested_or_state_keys(tmp_path, capsys, duplicate_key):
    source = tmp_path / "notes" / "plan.md"
    source.parent.mkdir()
    source.write_text("<!-- anchor: plan -->\nUse the west gate.\n", encoding="utf-8")
    record = tmp_path / f"duplicate-{duplicate_key}.yaml"
    lines = [
        "id: west-gate", "kind: note", "revision: 1", "classification: PREP",
        "subject: {kind: topic, id: gate}", "effective: {horizon: future}",
        "audience: {grants: [gm]}", "projections: [planning]", "status: active",
        "recorded_at: '2026-10-09T00:00:00Z'", "recorded_by: GM",
        "source: {path: notes/plan.md, anchor: plan}",
        "content_digest: 879cb6c02f24a20a9a8921c797b4cfad34dd19050eb7c6403a6ae8bc427ae2d1",
        "planning_date: chapter-1", "selection_label: West gate",
    ]
    duplicate = {
        "source": "source: {path: notes/other.md, anchor: other}",
        "audience": "audience: {grants: [players]}",
        "status": "status: retired",
    }[duplicate_key]
    lines.insert(lines.index(next(line for line in lines if line.startswith(f"{duplicate_key}:"))) + 1, duplicate)
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["authority", "record", "stage", str(record), "--campaign-dir", str(tmp_path), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "AUTH_VALIDATION"
    assert f"duplicate YAML key '{duplicate_key}'" in payload["message"]


def test_init_journal_recovers_after_ledger_write_before_tip(tmp_path, monkeypatch):
    import pipelines.summary_native.authority_apply as authority_apply

    real_write = authority_apply.atomic_write_bytes

    def crash_after_ledger(path, data):
        real_write(path, data)
        if path == ledger_path(tmp_path):
            raise RuntimeError("simulated crash after initial ledger write")

    monkeypatch.setattr(authority_apply, "atomic_write_bytes", crash_after_ledger)
    with pytest.raises(RuntimeError, match="simulated crash"):
        initialize_ledger(tmp_path, new_ledger("fixture"), actor="GM")

    pending = pending_transaction(tmp_path)
    assert pending is not None
    assert ledger_path(tmp_path).is_file()
    assert not ledger_tip_path(tmp_path).exists()

    monkeypatch.setattr(authority_apply, "atomic_write_bytes", real_write)
    assert recover_transaction(tmp_path, pending["id"])["state"] == "committed"
    validate_ledger_tip(tmp_path)
    events = list((authority_dir(tmp_path) / "events").glob("event-init-*.json"))
    assert len(events) == 1
    assert json.loads(events[0].read_text(encoding="utf-8"))["reason"] == "init"


def test_init_refuses_orphan_ledger_or_tip_state(tmp_path):
    ledger_path(tmp_path).parent.mkdir(parents=True)
    ledger_path(tmp_path).write_text("orphan\n", encoding="utf-8")
    with pytest.raises(AuthorityError, match="incomplete"):
        initialize_ledger(tmp_path, new_ledger("fixture"), actor="GM")

    other = tmp_path / "other"
    ledger_tip_path(other).parent.mkdir(parents=True)
    ledger_tip_path(other).write_text("{}\n", encoding="utf-8")
    with pytest.raises(AuthorityError, match="incomplete"):
        initialize_ledger(other, new_ledger("fixture"), actor="GM")
