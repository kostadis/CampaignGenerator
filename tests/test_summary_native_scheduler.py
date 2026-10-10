import threading
import hashlib

import pytest

from pipelines.summary_native.scheduler import EndpointState, Scheduler, WorkItem, render_markdown_report, render_report


class TransportFailure(RuntimeError):
    retryable_elsewhere = True


def test_scheduler_failsover_once_and_assembles_stably():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])
    items = [WorkItem("first", 0, "extract"), WorkItem("second", 1, "extract")]
    def call(item, endpoint):
        if endpoint == "a":
            raise TransportFailure("offline")
        return item.item_id
    result = scheduler.run(items, call)
    assert list(result.values) == ["first", "second"]
    assert all(a.endpoint_id in {"a", "b"} for a in result.attempts)
    assert scheduler.endpoints[0].state == "quarantined"


def test_scheduler_refuses_endpoint_identity_collision():
    try:
        Scheduler([EndpointState("same", 1), EndpointState("same", 1)])
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("collision accepted")


def test_preflight_accepts_partial_and_probe_rejoins():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])
    scheduler.preflight(lambda endpoint: endpoint.endpoint_id == "b")
    assert [e.state for e in scheduler.endpoints] == ["quarantined", "healthy"]
    assert scheduler.rejoin(lambda _: True) == ["a"]
    assert scheduler.endpoints[0].state == "healthy"


def test_report_is_stable_and_separates_failure_category():
    scheduler = Scheduler([EndpointState("b", 1)])
    result = scheduler.run([WorkItem("one", 0, "extract")], lambda *_: "ok")
    assert "| b | healthy | 1 | 1 | 0 |" in render_markdown_report(result, scheduler.endpoints)


def test_local_executor_is_ordered_and_model_free():
    scheduler = Scheduler([EndpointState("local", 2)])
    result = scheduler.run_local([WorkItem("b", 1, "npc-verify"), WorkItem("a", 0, "npc-verify")], lambda item: item.item_id)
    assert list(result.values) == ["a", "b"]


def test_each_endpoint_never_exceeds_its_independent_bound():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 2)])
    active = {"a": 0, "b": 0}
    maximum = {"a": 0, "b": 0}
    lock = threading.Lock()

    def call(item, endpoint):
        with lock:
            active[endpoint] += 1
            maximum[endpoint] = max(maximum[endpoint], active[endpoint])
        # A barrier makes every assigned call overlap without wall-clock sleeps.
        gate.wait(timeout=2)
        with lock:
            active[endpoint] -= 1
        return item.item_id

    gate = threading.Barrier(3)
    result = scheduler.run([WorkItem(str(n), n, "extract") for n in range(3)], call)
    assert list(result.values) == ["0", "1", "2"]
    assert maximum == {"a": 1, "b": 2}
    assert [endpoint.active_count for endpoint in scheduler.endpoints] == [0, 0]


def test_generation_increases_when_a_later_endpoint_handles_retry():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])

    def call(item, endpoint):
        if endpoint == "a":
            raise TransportFailure("first generation lost")
        return "canonical"

    result = scheduler.run([WorkItem("only", 0, "extract")], call)
    attempts = [attempt for attempt in result.attempts if attempt.item_id == "only"]
    assert [(attempt.endpoint_id, attempt.assignment_generation) for attempt in attempts] == [("a", 1), ("b", 2)]
    assert result.values == {"only": "canonical"}


def test_quarantined_peer_is_probed_and_rejoins_during_dispatch():
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])
    seen = []

    def call(item, endpoint):
        seen.append((item.item_id, endpoint))
        if endpoint == "a" and item.item_id == "zero":
            raise TransportFailure("temporary outage")
        return item.item_id

    # The first probe occurs after a fails; b remains usable while a recovers.
    result = scheduler.run(
        [WorkItem("zero", 0, "extract"), WorkItem("one", 1, "extract"), WorkItem("two", 2, "extract")],
        call,
        probe=lambda endpoint: endpoint.endpoint_id == "a",
    )
    assert result.values == {"zero": "zero", "one": "one", "two": "two"}
    assert scheduler.endpoints[0].recoveries == 1
    assert any(event["state"] == "healthy" and event["endpoint_id"] == "a" for event in scheduler.endpoint_events)


def test_report_reconciles_usage_retries_and_endpoint_health_stably():
    scheduler = Scheduler([EndpointState("b", 1), EndpointState("a", 1)])
    result = scheduler.run([WorkItem("one", 0, "extract")], lambda *_: "ok")
    report = render_report(result, scheduler.endpoints)
    assert [endpoint["id"] for endpoint in report["endpoints"]] == ["a", "b"]
    assert sum(endpoint.get("attempted", 0) for endpoint in report["endpoints"]) == len(result.attempts)
    assert sum(endpoint.get("usage_unavailable", 0) for endpoint in report["endpoints"]) == len(result.attempts)


def test_late_generation_cannot_replace_canonical_value_or_change_bytes():
    """A retired assignment's outcome is never used to assemble the artifact."""
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)])
    calls = []

    def call(item, endpoint):
        calls.append((item.item_id, endpoint))
        if endpoint == "a":
            raise TransportFailure("lost generation")
        return f"canonical:{item.item_id}"

    items = [WorkItem("z", 1, "extract"), WorkItem("a", 0, "extract")]
    result = scheduler.run(items, call)
    first = "".join(result.values.values()).encode()
    second = "".join(result.values.values()).encode()
    assert result.values == {"a": "canonical:a", "z": "canonical:z"}
    assert first == second
    assert [(a.item_id, a.assignment_generation) for a in result.attempts] == sorted(
        [(a.item_id, a.assignment_generation) for a in result.attempts]
    )


@pytest.mark.parametrize("operation", ["extract", "audit", "npc-draft"])
def test_cross_mode_assembly_has_identical_content_hash(operation):
    """Serial and parallel endpoint timing produce the same canonical artifact bytes."""
    items = [WorkItem("second", 1, operation), WorkItem("first", 0, operation)]
    serial = Scheduler([EndpointState("only", 1)]).run(items, lambda item, _endpoint: item.item_id)
    parallel = Scheduler([EndpointState("slow", 1), EndpointState("fast", 1)]).run(
        items, lambda item, endpoint: item.item_id
    )
    serial_bytes = "\n".join(serial.values.values()).encode()
    parallel_bytes = "\n".join(parallel.values.values()).encode()
    assert serial_bytes == parallel_bytes
    assert hashlib.sha256(serial_bytes).hexdigest() == hashlib.sha256(parallel_bytes).hexdigest()


def test_telemetry_reconciles_latency_retry_usage_and_quarantine_duration():
    now = [0.0]
    scheduler = Scheduler([EndpointState("a", 1), EndpointState("b", 1)], clock=lambda: now[0])

    def call(item, endpoint):
        if endpoint == "a":
            now[0] = 2.0
            raise TransportFailure("offline")
        now[0] = 3.0
        return item.item_id

    result = scheduler.run([WorkItem("only", 0, "extract")], call, probe=lambda e: e.endpoint_id == "a")
    report = render_report(result, scheduler.endpoints)
    by_id = {entry["id"]: entry for entry in report["endpoints"]}
    assert sum(x["retries"] for x in by_id.values()) == 1
    assert by_id["a"]["quarantine_duration_ms"] >= 0
    assert sum(x["duration_ms"] for x in by_id.values()) == sum(a.duration_ms for a in result.attempts)
    assert sum(x["usage_unavailable"] for x in by_id.values()) == len(result.attempts)
    assert render_markdown_report(result, scheduler.endpoints) == render_markdown_report(result, scheduler.endpoints)


def test_interruption_keeps_completed_values_and_marks_remaining_items():
    scheduler = Scheduler([EndpointState("local", 1)])

    def call(item, _endpoint):
        if item.item_id == "stop":
            raise KeyboardInterrupt()
        return item.item_id

    result = scheduler.run([WorkItem("done", 0, "verify"), WorkItem("stop", 1, "verify")], call)
    assert result.values == {"done": "done"}
    assert result.interrupted is True
    assert result.failures["stop"].code == "interrupted"
    assert scheduler.endpoints[0].active_count == 0


def test_duplicate_item_identity_or_ordinal_is_refused_before_dispatch():
    scheduler = Scheduler([EndpointState("a", 1)])
    with pytest.raises(ValueError, match="identities"):
        scheduler.run([WorkItem("x", 0, "extract"), WorkItem("x", 1, "extract")], lambda *_: "x")
    with pytest.raises(ValueError, match="ordinals"):
        scheduler.run([WorkItem("x", 0, "extract"), WorkItem("y", 0, "extract")], lambda *_: "x")
