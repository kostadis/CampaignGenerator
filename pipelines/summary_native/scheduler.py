"""Provider-neutral, deterministic bounded endpoint scheduler.

Adapters retain prompts, validation and artifact authority.  This module only
dispatches stable items and records whether a final campaignlib failure may be
retried on a different endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Generic, TypeVar
import json
import os
from pathlib import Path
import re
import time

T = TypeVar("T")


@dataclass(frozen=True)
class WorkItem:
    item_id: str
    ordinal: int
    operation: str
    compatibility_key: str = ""


@dataclass
class EndpointState:
    endpoint_id: str
    limit: int
    url: str | None = None
    model: str | None = None
    state: str = "healthy"
    active_count: int = 0
    attempted: int = 0
    failures: int = 0
    recoveries: int = 0
    health_checks: int = 0
    quarantine_started_at: float | None = None
    quarantine_duration_ms: int = 0


@dataclass(frozen=True)
class FailureEnvelope:
    operational_category: str
    code: str
    message: str
    retryable_elsewhere: bool = False
    verifier_category: str | None = None


@dataclass
class AttemptRecord:
    item_id: str
    endpoint_id: str
    assignment_generation: int
    outcome: str
    duration_ms: int
    failure: FailureEnvelope | None = None
    usage: dict | None = None
    usage_available: bool = False


@dataclass
class SchedulerResult(Generic[T]):
    values: dict[str, T] = field(default_factory=dict)
    failures: dict[str, FailureEnvelope] = field(default_factory=dict)
    attempts: list[AttemptRecord] = field(default_factory=list)
    interrupted: bool = False


_URL_CREDENTIALS = re.compile(r"(https?://)[^/@]+@")


def redact_url(value: str | None) -> str | None:
    """Keep endpoint identity useful in a journal without persisting secrets."""
    return _URL_CREDENTIALS.sub(r"\1***@", value) if value else value


def atomic_write_record(path: Path, record: dict) -> None:
    """Atomically persist a schema-v2 scheduler record."""
    payload = dict(record)
    payload.setdefault("schema", 2)
    if payload["schema"] != 2:
        raise ValueError("scheduler writes schema 2 records only")
    endpoints = payload.get("endpoints")
    if isinstance(endpoints, list):
        payload["endpoints"] = [
            {**endpoint, "url": redact_url(endpoint.get("url"))}
            if isinstance(endpoint, dict) else endpoint for endpoint in endpoints
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_record(path: Path) -> dict:
    """Read v1/v2 records; v1 remains valid observable history."""
    value = json.loads(path.read_text(encoding="utf-8"))
    schema = value.get("schema", 1)
    if schema not in (1, 2):
        raise ValueError(f"unsupported scheduler record schema {schema}")
    if schema == 1:
        value = {**value, "schema": 1, "attempts": value.get("attempts", []),
                 "endpoint_events": value.get("endpoint_events", [])}
    # Pre-scheduler operation journals used exit_code only.  Preserve them as
    # resumable history instead of treating an upgrade as a reason to spend
    # again; adapters still validate every claimed artifact.
    if "status" not in value and "exit_code" in value:
        value["status"] = "completed" if value.get("exit_code") == 0 else "incomplete"
    return value


def telemetry(attempts: list[AttemptRecord], endpoints: list[EndpointState] | None = None) -> dict[str, dict[str, int]]:
    """Derive stable per-endpoint counts from append-only attempt records."""
    result: dict[str, dict[str, int]] = {}
    for attempt in attempts:
        entry = result.setdefault(attempt.endpoint_id, {"attempted": 0, "successful": 0, "transport_failed": 0,
                                                        "retries": 0, "duration_ms": 0, "usage_unavailable": 0})
        entry["attempted"] += 1; entry["duration_ms"] += attempt.duration_ms
        if attempt.outcome == "success": entry["successful"] += 1
        if attempt.outcome == "transport_failure": entry["transport_failed"] += 1
        if attempt.assignment_generation > 1:
            entry["retries"] += 1
        if not attempt.usage_available:
            entry["usage_unavailable"] += 1
    for endpoint in endpoints or ():
        entry = result.setdefault(endpoint.endpoint_id, {"attempted": 0, "successful": 0, "transport_failed": 0,
                                                         "retries": 0, "duration_ms": 0, "usage_unavailable": 0})
        durations = [a.duration_ms for a in attempts if a.endpoint_id == endpoint.endpoint_id]
        entry.update({"health_checks": endpoint.health_checks, "recoveries": endpoint.recoveries,
                      "quarantined": endpoint.state == "quarantined",
                      "quarantine_duration_ms": endpoint.quarantine_duration_ms,
                      "latency_min_ms": min(durations) if durations else 0,
                      "latency_max_ms": max(durations) if durations else 0,
                      "latency_mean_ms": (sum(durations) // len(durations)) if durations else 0})
    return result


def select_resume(records: list[dict], run_id: str | None = None, *, compatible: Callable[[dict], bool] | None = None) -> dict:
    """Select exactly one compatible journal or refuse explicitly.

    Operations still validate their own artifacts before accepting a recorded
    item as complete; a journal is an audit trail, never completion evidence.
    """
    compatible = compatible or (lambda _record: True)
    if run_id:
        matches = [record for record in records if record.get("run_id") == run_id]
        if len(matches) != 1:
            raise ValueError(f"no unique resumable run named {run_id!r}")
        selected = matches[0]
        if not compatible(selected):
            raise ValueError(f"run {run_id!r} is incompatible with this selection or inputs")
    else:
        candidates = [record for record in records
                      if record.get("status") in {"running", "incomplete", "interrupted", "completed"}
                      and compatible(record)]
        if len(candidates) != 1:
            raise ValueError("resume requires exactly one compatible run; pass --resume RUN_ID")
        selected = candidates[0]
    if selected.get("status") == "completed":
        return selected
    if selected.get("status") not in {"running", "incomplete", "interrupted"}:
        raise ValueError("selected run is not resumable")
    return selected


def render_report(result: SchedulerResult, endpoints: list[EndpointState]) -> dict:
    """Stable JSON-ready operational projection; content ordering is untouched."""
    per_endpoint = telemetry(result.attempts, endpoints)
    return {
        "completed": list(result.values),
        "failures": {key: {"category": value.operational_category, "code": value.code,
                           "message": value.message, "verifier_category": value.verifier_category}
                     for key, value in sorted(result.failures.items())},
        "endpoints": [{"id": endpoint.endpoint_id, "state": endpoint.state,
                       "limit": endpoint.limit, **per_endpoint.get(endpoint.endpoint_id, {})}
                      for endpoint in sorted(endpoints, key=lambda endpoint: endpoint.endpoint_id)],
    }


def render_markdown_report(result: SchedulerResult, endpoints: list[EndpointState]) -> str:
    report = render_report(result, endpoints)
    lines = ["# Scheduler report", "", "| Endpoint | State | Attempts | Success | Transport failures |", "|---|---:|---:|---:|---:|"]
    for endpoint in report["endpoints"]:
        lines.append(f"| {endpoint['id']} | {endpoint['state']} | {endpoint.get('attempted', 0)} | {endpoint.get('successful', 0)} | {endpoint.get('transport_failed', 0)} |")
    if report["failures"]:
        lines.extend(["", "## Failures"])
        for item, failure in report["failures"].items():
            lines.append(f"- `{item}`: {failure['category']} ({failure['code']})")
    return "\n".join(lines) + "\n"


class Scheduler:
    """Dispatch each item at most once to an endpoint, committing by ordinal."""
    def __init__(self, endpoints: list[EndpointState], *, clock: Callable[[], float] = time.monotonic):
        ids = [e.endpoint_id for e in endpoints]
        if len(ids) != len(set(ids)):
            raise ValueError("endpoint identities must be unique")
        if not endpoints:
            raise ValueError("no healthy endpoint")
        if any(e.limit <= 0 for e in endpoints):
            raise ValueError("endpoint limits must be positive")
        self.endpoints = endpoints
        self.clock = clock
        self.endpoint_events: list[dict] = []

    def preflight(self, check: Callable[[EndpointState], bool]) -> None:
        """Independently admit endpoints; refuse only when none are healthy."""
        healthy = 0
        for endpoint in self.endpoints:
            endpoint.health_checks += 1
            try:
                ok = bool(check(endpoint))
            except Exception:  # a health probe must never hide a usable peer
                ok = False
            endpoint.state = "healthy" if ok else "quarantined"
            self.endpoint_events.append({"endpoint_id": endpoint.endpoint_id, "state": endpoint.state, "at": self.clock()})
            healthy += int(ok)
        if not healthy:
            raise ValueError("no healthy endpoint")

    def rejoin(self, check: Callable[[EndpointState], bool]) -> list[str]:
        """Probe quarantined endpoints; recovered peers re-enter dispatch."""
        recovered = []
        for endpoint in self.endpoints:
            if endpoint.state != "quarantined":
                continue
            endpoint.state = "probing"
            endpoint.health_checks += 1
            try:
                ok = bool(check(endpoint))
            except Exception:
                ok = False
            endpoint.state = "healthy" if ok else "quarantined"
            if ok:
                endpoint.recoveries += 1
                if endpoint.quarantine_started_at is not None:
                    endpoint.quarantine_duration_ms += max(0, int((self.clock() - endpoint.quarantine_started_at) * 1000))
                endpoint.quarantine_started_at = None
            self.endpoint_events.append({"endpoint_id": endpoint.endpoint_id, "state": endpoint.state, "at": self.clock()})
            if ok: recovered.append(endpoint.endpoint_id)
        return recovered

    def run(self, items: list[WorkItem], call: Callable[[WorkItem, str], T], *,
            probe: Callable[[EndpointState], bool] | None = None) -> SchedulerResult[T]:
        item_ids = [item.item_id for item in items]
        ordinals = [item.ordinal for item in items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("work item identities must be unique")
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("work item ordinals must be unique")
        pending = sorted(items, key=lambda item: item.ordinal)
        seen: dict[str, set[str]] = {item.item_id: set() for item in pending}
        generations: dict[str, int] = {item.item_id: 0 for item in pending}
        result: SchedulerResult[T] = SchedulerResult()
        while pending:
            # A probe is deliberately performed between bounded dispatch waves,
            # never while an endpoint has an in-flight call.  It lets a peer
            # rejoin during a long run without racing a stale assignment.
            if probe and any(e.state == "quarantined" for e in self.endpoints):
                self.rejoin(probe)
            healthy = [e for e in self.endpoints if e.state == "healthy"]
            if not healthy:
                for item in pending:
                    result.failures[item.item_id] = FailureEnvelope("retry_exhausted", "no-healthy-endpoint", "no healthy endpoint remains")
                break
            assignments: list[tuple[WorkItem, EndpointState, int]] = []
            for endpoint in healthy:
                slots = endpoint.limit
                while slots and pending:
                    candidate = next((x for x in pending if endpoint.endpoint_id not in seen[x.item_id]), None)
                    if candidate is None:
                        break
                    pending.remove(candidate)
                    seen[candidate.item_id].add(endpoint.endpoint_id)
                    generations[candidate.item_id] += 1
                    assignments.append((candidate, endpoint, generations[candidate.item_id]))
                    slots -= 1
            if not assignments:
                for item in pending:
                    result.failures[item.item_id] = FailureEnvelope("retry_exhausted", "endpoints-exhausted", "item has attempted every endpoint")
                break
            workers = sum(endpoint.limit for endpoint in healthy)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {}
                for item, endpoint, generation in assignments:
                    endpoint.active_count += 1
                    futures[pool.submit(call, item, endpoint.endpoint_id)] = (item, endpoint, generation, time.monotonic())
                for future in as_completed(futures):
                    item, endpoint, generation, started = futures[future]
                    duration = int((time.monotonic() - started) * 1000)
                    endpoint.attempted += 1
                    try:
                        value = future.result()
                    except KeyboardInterrupt:
                        # Preserve the completed work and a durable caller-visible
                        # interruption boundary.  The operation owns journal writes.
                        result.interrupted = True
                        failure = FailureEnvelope("retry_exhausted", "interrupted", "scheduler interrupted")
                        result.attempts.append(AttemptRecord(item.item_id, endpoint.endpoint_id, generation, "interrupted", duration, failure))
                        result.failures[item.item_id] = failure
                        for remainder in pending:
                            result.failures.setdefault(remainder.item_id, failure)
                        pending.clear()
                        break
                    except Exception as exc:  # caller/campaignlib classifies final failure
                        from campaignlib.api import classify_final_failure
                        # The marker is retained for provider-neutral fake
                        # adapters; production final-call failures flow through
                        # campaignlib's public classifier.
                        retryable = bool(getattr(exc, "retryable_elsewhere", False)) or (
                            classify_final_failure(exc) == "transport_failure"
                        )
                        failure = FailureEnvelope("transport_failure" if retryable else "model_response_rejection", type(exc).__name__, str(exc), retryable)
                        result.attempts.append(AttemptRecord(item.item_id, endpoint.endpoint_id, generation, "transport_failure" if retryable else "model_rejected", duration, failure))
                        if retryable:
                            endpoint.state = "quarantined"; endpoint.failures += 1
                            endpoint.quarantine_started_at = self.clock()
                            self.endpoint_events.append({"endpoint_id": endpoint.endpoint_id, "state": "quarantined", "at": self.clock()})
                            if any(e.endpoint_id not in seen[item.item_id] and e.state == "healthy" for e in self.endpoints):
                                pending.append(item)
                            else:
                                result.failures[item.item_id] = FailureEnvelope("retry_exhausted", "endpoint-attempts-exhausted", str(exc))
                        else:
                            result.failures[item.item_id] = failure
                    else:
                        result.values[item.item_id] = value
                        result.attempts.append(AttemptRecord(item.item_id, endpoint.endpoint_id, generation, "success", duration))
                    finally:
                        endpoint.active_count -= 1
            if result.interrupted:
                # The executor has joined its in-flight work.  No endpoint may
                # retain a phantom slot when the caller journals the boundary.
                for endpoint in self.endpoints:
                    endpoint.active_count = 0
                break
        # Attempts are journaled in assignment order rather than completion-race
        # order.  That makes reports byte-stable under different response timing.
        ordinal = {item.item_id: item.ordinal for item in items}
        result.attempts.sort(key=lambda a: (ordinal[a.item_id], a.assignment_generation, a.endpoint_id))
        # Values are exposed in stable item order, independently of completion order.
        result.values = {item.item_id: result.values[item.item_id] for item in sorted(items, key=lambda x: x.ordinal) if item.item_id in result.values}
        return result

    def run_local(self, items: list[WorkItem], call: Callable[[WorkItem], T]) -> SchedulerResult[T]:
        """Execute deterministic local work through the same ordered contract."""
        return self.run(items, lambda item, _endpoint: call(item))


def reconcile_items(record: dict, artifact_ok: Callable[[dict], bool]) -> tuple[list[dict], list[dict]]:
    """Return (complete, pending), treating validated artifacts as authority."""
    complete, pending = [], []
    for item in record.get("items", []):
        if item.get("state") in {"succeeded", "cached"} and artifact_ok(item):
            complete.append(item)
        else:
            pending.append(item)
    return complete, pending
