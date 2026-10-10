import pytest

from pipelines.summary_native.scheduler import atomic_write_record, read_record, redact_url, select_resume, reconcile_items, EndpointState, Scheduler, WorkItem, render_report


def test_v2_record_is_atomic_and_redacts_endpoint_credentials(tmp_path):
    path = tmp_path / "record.json"
    atomic_write_record(path, {"run_id": "r", "endpoints": [{"url": "http://token@example.test/v1"}]})
    value = read_record(path)
    assert value["schema"] == 2
    assert value["endpoints"][0]["url"] == "http://***@example.test/v1"
    assert not path.with_name("record.json.tmp").exists()


def test_v1_record_is_compatible(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"run_id":"old"}', encoding="utf-8")
    assert read_record(path)["schema"] == 1


def test_redact_url_without_credentials_is_stable():
    assert redact_url("http://host:8000/v1") == "http://host:8000/v1"


def test_resume_selection_refuses_ambiguous_and_selects_named():
    records = [{"run_id": "one", "status": "incomplete"}, {"run_id": "two", "status": "interrupted"}]
    with pytest.raises(ValueError, match="exactly one"):
        select_resume(records)
    assert select_resume(records, "two")["run_id"] == "two"


def test_resume_selects_completed_run_and_ignores_topology_when_compatible():
    records = [{
        "run_id": "done", "status": "completed", "model": "m", "inputs": {"source": "same"},
        "endpoints": ["old-host"], "parallel": 1,
    }]
    selected = select_resume(
        records, compatible=lambda r: r["model"] == "m" and r["inputs"] == {"source": "same"},
    )
    assert selected["run_id"] == "done"


def test_named_resume_refuses_incompatible_input_instead_of_fresh_run():
    with pytest.raises(ValueError, match="incompatible"):
        select_resume(
            [{"run_id": "old", "status": "incomplete", "model": "old"}],
            "old", compatible=lambda r: r.get("model") == "new",
        )


def test_legacy_exit_code_journal_has_a_resumable_status(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"run_id":"old", "exit_code":3}', encoding="utf-8")
    assert read_record(path)["status"] == "incomplete"


def test_artifacts_override_stale_record_completion():
    complete, pending = reconcile_items({"items": [{"id": "good", "state": "succeeded"}, {"id": "bad", "state": "succeeded"}]}, lambda item: item["id"] == "good")
    assert [item["id"] for item in complete] == ["good"]
    assert [item["id"] for item in pending] == ["bad"]


def test_record_report_telemetry_reconciles_every_endpoint_field():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])
    result = scheduler.run([WorkItem("x", 0, "extract")], lambda *_: "ok")
    report = render_report(result, scheduler.endpoints)
    assert sum(row["attempted"] for row in report["endpoints"]) == 1
    assert sum(row["successful"] for row in report["endpoints"]) == 1
    assert sum(row["transport_failed"] for row in report["endpoints"]) == 0
    assert sum(row["usage_unavailable"] for row in report["endpoints"]) == 1
    assert all("latency_mean_ms" in row and "quarantine_duration_ms" in row for row in report["endpoints"])


def test_resume_matrix_cache_success_without_a_record_is_not_completion_truth():
    """A discovered artifact needs its operation journal before resume can skip it."""
    complete, pending = reconcile_items({}, lambda _item: True)
    assert complete == pending == []


def test_resume_matrix_record_success_without_artifact_is_pending():
    complete, pending = reconcile_items(
        {"items": [{"id": "lost-after-record", "state": "succeeded"}]}, lambda _item: False,
    )
    assert complete == []
    assert [item["id"] for item in pending] == ["lost-after-record"]


def test_resume_matrix_incomplete_cache_is_never_success_even_if_present():
    complete, pending = reconcile_items(
        {"items": [{"id": "partial", "state": "incomplete"}]}, lambda _item: True,
    )
    assert complete == []
    assert [item["id"] for item in pending] == ["partial"]


def test_resume_matrix_changed_inputs_refuse_before_any_fresh_run():
    with pytest.raises(ValueError, match="incompatible"):
        select_resume(
            [{"run_id": "r", "status": "completed", "input_digest": "old"}], "r",
            compatible=lambda record: record["input_digest"] == "new",
        )


def test_resume_matrix_topology_only_change_keeps_completed_artifact():
    record = {"run_id": "r", "status": "completed", "input_digest": "same", "endpoints": ["one"]}
    assert select_resume([record], "r", compatible=lambda item: item["input_digest"] == "same") is record


def test_resume_matrix_completed_and_ambiguous_runs_are_explicit():
    records = [{"run_id": "first", "status": "completed"}, {"run_id": "second", "status": "completed"}]
    with pytest.raises(ValueError, match="exactly one"):
        select_resume(records)
    assert select_resume(records, "second")["run_id"] == "second"
