"""Read-only scheduler journal projection used by the local workflow pages.

The CLI owns scheduling and completion authority.  This module only makes the
latest journal safe to display after reload; malformed journals never become a
successful run in the browser.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _absent(operation: str) -> dict[str, Any]:
    return {"present": False, "operation": operation, "status": "absent", "concurrency": None,
            "counts": {"total": 0, "cached": 0, "completed": 0, "unfinished": 0, "failed": 0},
            "endpoints": [], "outcomes": {}, "resume_available": False}


def project_latest(runs_dir: Path, operation: str) -> dict[str, Any]:
    """Return a conservative projection of the newest record beneath ``runs_dir``."""
    records = sorted(runs_dir.glob("*/record.json"), key=lambda p: (p.parent.name, p.stat().st_mtime))
    if not records:
        return _absent(operation)
    path = records[-1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("record must be an object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**_absent(operation), "present": True, "run_id": path.parent.name, "status": "error",
                "error": f"scheduler record is unreadable: {exc}"}

    values = raw.get("chunks") or raw.get("items") or raw.get("npcs") or []
    if isinstance(values, dict):
        values = list(values.values())
    if not isinstance(values, list):
        values = []
    results = raw.get("results") if isinstance(raw.get("results"), dict) else {}
    statuses = [
        ("completed" if isinstance(item, dict) and str(item.get("id", "")) in results
         else str(item.get("status", "pending")) if isinstance(item, dict) else "pending")
        for item in values
    ]
    cached = sum(status in {"cached", "reused"} for status in statuses)
    completed = sum(status in {"completed", "success", "succeeded", "done"} for status in statuses)
    failed = sum(status in {"failed", "error"} for status in statuses)
    unfinished = max(0, len(statuses) - cached - completed - failed)
    outcomes = raw.get("failures") or raw.get("outcomes") or {}
    if not isinstance(outcomes, dict):
        outcomes = {}
    endpoints = raw.get("endpoints") or []
    if not isinstance(endpoints, list):
        endpoints = []
    endpoint_rows = []
    for entry in endpoints:
        if not isinstance(entry, dict):
            continue
        # V2 scheduler fields are deliberately accepted alongside the public
        # projection names, so the UI does not need to know journal internals.
        row = dict(entry)
        if "id" not in row and "endpoint_id" in row:
            row["id"] = row["endpoint_id"]
        if "active" not in row and "active_count" in row:
            row["active"] = row["active_count"]
        endpoint_rows.append(row)
    concurrency = raw.get("concurrency")
    if not isinstance(concurrency, dict):
        concurrency = {"value": raw.get("parallel"), "source": raw.get("concurrency_source", "recorded"),
                       "model": raw.get("model")}
    status = str(raw.get("status") or ("completed" if raw.get("exit_code") == 0 and raw.get("finished") else "incomplete"))
    return {
        "present": True, "run_id": str(raw.get("run_id") or path.parent.name), "operation": operation,
        "status": status, "concurrency": concurrency,
        "counts": {"total": len(statuses), "cached": cached, "completed": completed,
                   "unfinished": unfinished, "failed": max(failed, len(outcomes))},
        "endpoints": endpoint_rows, "outcomes": outcomes,
        "resume_available": status in {"running", "incomplete", "interrupted"},
    }
