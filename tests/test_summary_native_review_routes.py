"""Trusted local review routes preserve the CLI contract and lifecycle."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
import subprocess
import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.platform_config_service import PlatformConfigService
from server.routers import review_routes
from server.subprocess_runner import BoundedJSONError


BASE = "/api/reviews"


def decision(note: str = "") -> dict:
    return {
        "item_id": "item-1",
        "item_revision": 1,
        "review_digest": "a" * 64,
        "expected_decision_revision": 0,
        "verdict": "approve",
        "disposition": "accept_no_change",
        "note": note,
    }


@pytest.fixture
def route_app(tmp_path: Path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.yaml").write_text("{}\n", encoding="utf-8")
    app = FastAPI()
    app.include_router(review_routes.router, prefix=BASE)
    app.state.platform = PlatformConfigService(tmp_path)
    calls: list[tuple[list[str], dict]] = []

    async def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return {
            "ok": True,
            "code": "TEST_OK",
            "message": "completed",
            "artifacts": [],
            "data": {"command": cmd[2:4]},
        }

    monkeypatch.setattr(review_routes, "run_bounded_json", fake_run)
    return app, tmp_path, calls


def test_all_us1_actions_use_fixed_bounded_cli_arrays_and_preserve_defaults(route_app):
    app, campaign, calls = route_app
    selection = campaign / "selection.json"
    selection.write_text('{"items":["item-1"]}', encoding="utf-8")
    bundle = campaign / "bundle.json"
    bundle.write_text("{}", encoding="utf-8")
    client = TestClient(app)

    requests = [
        ("post", f"{BASE}/init", {}),
        ("post", f"{BASE}/migrate", {"dry_run": True}),
        ("post", f"{BASE}/migrate", {"plan_sha256": "a" * 64}),
        ("post", f"{BASE}/recover", {"transaction": "transaction-1"}),
        ("post", f"{BASE}/create", {"kind": "npc_verification", "selection": "selection.json"}),
        ("get", BASE, None),
        ("get", f"{BASE}/review-1?item=item-1&cursor=item-0&limit=25", None),
        ("get", f"{BASE}/review-1/status", None),
        ("post", f"{BASE}/review-1/decisions", {
            "request_id": "request-1", "review_generation": 1, "reviewer": "GM",
            "decisions": [decision()],
        }),
        ("get", f"{BASE}/review-1/history?item=item-1", None),
        ("post", f"{BASE}/review-1/retract", {
            "event": "event-1", "expected_decision_revision": 1, "reason": "Renew review",
        }),
        ("post", f"{BASE}/review-1/export", {"selection": "selection.json"}),
        ("post", f"{BASE}/import", {"bundle": "bundle.json", "expected_generation": 1}),
        ("post", f"{BASE}/review-1/service/start", {
            "host": "127.0.0.1", "port": 8766, "origin": "http://127.0.0.1:8766",
        }),
        ("get", f"{BASE}/review-1/service/status", None),
        ("post", f"{BASE}/review-1/service/stop", {}),
        ("post", f"{BASE}/review-1/access/issue", {}),
        ("post", f"{BASE}/review-1/access/revoke", {"grant": "grant-1"}),
    ]
    for method, url, body in requests:
        response = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
        assert response.status_code == 200, (method, url, response.text)

    assert len(calls) == len(requests)
    for command, kwargs in calls:
        assert command[1] == "review"
        assert command[-3:] == ["--campaign-dir", str(campaign), "--json"]
        assert kwargs["cwd"] == str(campaign)
        assert kwargs["save_run_log"] is False
        assert kwargs["timeout_seconds"] == 30
        assert kwargs["max_output_bytes"] == 8 * 1024 * 1024

    commands = [command for command, _ in calls]
    assert commands[0][2:-3] == ["init"]
    assert commands[1][2:-3] == ["migrate", "--dry-run"]
    assert commands[2][2:-3] == ["migrate", "--plan-sha256", "a" * 64]
    assert commands[3][2:-3] == ["recover", "transaction-1"]
    assert commands[4][2:-3] == [
        "create", "--kind", "npc_verification", "--selection", str(selection)
    ]
    assert commands[5][2:-3] == ["list"]
    assert commands[6][2:-3] == [
        "show", "review-1", "--item", "item-1", "--cursor", "item-0", "--limit", "25"
    ]
    assert commands[7][2:-3] == ["status", "review-1"]
    assert commands[8][2:-3] == ["decide", "review-1", "--decisions", "-"]
    sent = json.loads(calls[8][1]["stdin_bytes"])
    assert sent["version"] == 1 and sent["request_id"] == "request-1"
    assert commands[9][2:-3] == ["history", "review-1", "--item", "item-1"]
    assert commands[10][2:-3] == [
        "retract", "review-1", "--event", "event-1",
        "--expected-decision-revision", "1", "--reason", "Renew review",
    ]
    assert commands[11][2:-3] == ["export", "review-1", "--selection", str(selection)]
    assert commands[12][2:-3] == [
        "import", "--bundle", str(bundle), "--expected-generation", "1"
    ]
    assert commands[13][2:-3] == [
        "service", "start", "review-1", "--host", "127.0.0.1", "--port", "8766",
        "--origin", "http://127.0.0.1:8766",
    ]
    assert commands[14][2:-3] == ["service", "status", "review-1"]
    assert commands[15][2:-3] == ["service", "stop", "review-1"]
    assert commands[16][2:-3] == ["access", "issue", "review-1"]
    assert commands[17][2:-3] == ["access", "revoke", "review-1", "--grant", "grant-1"]


def test_paths_cannot_retarget_the_local_server_campaign(route_app, tmp_path: Path):
    app, _campaign, calls = route_app
    outside = tmp_path.parent / "outside-selection.json"
    outside.write_text("{}", encoding="utf-8")

    response = TestClient(app).post(
        f"{BASE}/create",
        json={"kind": "npc_verification", "selection": str(outside)},
    )

    assert response.status_code == 400
    assert calls == []


def test_bounded_failures_keep_stable_http_classes_without_run_logs(route_app, monkeypatch):
    app, _campaign, _calls = route_app
    secret = "capability-secret-must-not-escape"

    async def stale(_cmd, **kwargs):
        assert kwargs["save_run_log"] is False
        raise BoundedJSONError(
            "changed",
            returncode=3,
            category="nonzero_exit",
            payload={
                "ok": False,
                "code": "REVIEW_STALE_DECISION",
                "message": f"Reload after checking {secret}.",
            },
        )

    monkeypatch.setattr(review_routes, "run_bounded_json", stale)
    response = TestClient(app).get(f"{BASE}/review-1/status")
    assert response.status_code == 409
    assert response.json() == {
        "ok": False,
        "code": "REVIEW_STALE_DECISION",
        "message": "Review state changed. Reload before trying again.",
    }
    assert secret not in response.text


def test_campaign_review_config_owns_route_bounds(route_app):
    app, campaign, calls = route_app
    (campaign / "config" / "review.yaml").write_text(
        "max_page_items: 2\n"
        "max_batch_decisions: 1\n"
        "max_note_chars: 3\n"
        "max_response_bytes: 2048\n"
        "command_timeout_seconds: 1.25\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    assert client.get(f"{BASE}/review-1?limit=3").status_code == 400
    assert client.post(
        f"{BASE}/review-1/decisions",
        json={
            "request_id": "request-1",
            "review_generation": 1,
            "reviewer": "GM",
            "decisions": [decision("yes"), {**decision("no"), "item_id": "item-2"}],
        },
    ).status_code == 400
    assert client.post(
        f"{BASE}/review-1/decisions",
        json={
            "request_id": "request-2",
            "review_generation": 1,
            "reviewer": "GM",
            "decisions": [decision("long")],
        },
    ).status_code == 400
    assert client.post(
        f"{BASE}/review-1/retract",
        json={"event": "event-1", "expected_decision_revision": 1, "reason": "long"},
    ).status_code == 400

    assert client.get(f"{BASE}/review-1?limit=2").status_code == 200
    _command, kwargs = calls[-1]
    assert kwargs["timeout_seconds"] == 1.25
    assert kwargs["max_output_bytes"] == 2048


def test_recovery_then_status_uses_cli_truth_after_interrupted_save(route_app, monkeypatch):
    app, _campaign, calls = route_app
    recovered = False

    async def stateful(cmd, **kwargs):
        nonlocal recovered
        calls.append((cmd, kwargs))
        action = cmd[2]
        if action == "status":
            return {"ok": True, "data": {"pending_transaction": not recovered, "settled": 1 if recovered else 0}}
        if action == "recover":
            recovered = True
            return {"ok": True, "data": {"state": "committed"}}
        raise AssertionError(cmd)

    monkeypatch.setattr(review_routes, "run_bounded_json", stateful)
    client = TestClient(app)
    assert client.get(f"{BASE}/review-1/status").json()["data"]["pending_transaction"] is True
    assert client.post(f"{BASE}/recover", json={"transaction": "tx-interrupted"}).status_code == 200
    visible = client.get(f"{BASE}/review-1/status").json()["data"]
    assert visible == {"pending_transaction": False, "settled": 1}


def test_capability_link_is_returned_once_without_argv_or_run_log(route_app, monkeypatch):
    app, _campaign, calls = route_app
    secret = "capability-secret-only-in-response"

    async def issue(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return {"ok": True, "data": {"grant_id": "grant-1", "url": f"http://private/r/{secret}/"}}

    monkeypatch.setattr(review_routes, "run_bounded_json", issue)
    response = TestClient(app).post(f"{BASE}/review-1/access/issue", json={})

    assert response.json()["data"]["url"].endswith(f"/{secret}/")
    command, kwargs = calls[-1]
    assert secret not in " ".join(command)
    assert kwargs["save_run_log"] is False


def test_service_survives_client_disconnect_and_new_client_reads_status(route_app, monkeypatch):
    app, _campaign, calls = route_app
    running = False

    async def lifecycle(cmd, **kwargs):
        nonlocal running
        calls.append((cmd, kwargs))
        action = cmd[2:5]
        if action[:2] == ["service", "start"]:
            running = True
            return {"ok": True, "data": {"running": True}}
        if action[:2] == ["service", "status"]:
            return {"ok": True, "data": {"running": running}}
        raise AssertionError(cmd)

    monkeypatch.setattr(review_routes, "run_bounded_json", lifecycle)
    with TestClient(app) as browser:
        assert browser.post(
            f"{BASE}/review-1/service/start",
            json={"host": "127.0.0.1", "port": 8766, "origin": "http://127.0.0.1:8766"},
        ).status_code == 200
    # Closing the browser/SSE client is not a service-stop command. A fresh
    # client sees the service created by the bounded lifecycle operation.
    assert TestClient(app).get(f"{BASE}/review-1/service/status").json()["data"]["running"] is True
    assert not any(command[2:4] == ["service", "stop"] for command, _ in calls)


def test_main_application_registers_the_review_router():
    from server.main import app

    paths = app.openapi()["paths"]
    assert f"{BASE}/init" in paths
    assert f"{BASE}/{{review_id}}/service/start" in paths
    assert f"{BASE}/{{review_id}}/access/issue" in paths


def test_us2_through_us4_actions_preserve_every_typed_cli_flag(route_app):
    app, campaign, calls = route_app
    operation = campaign / "operation.json"
    operation.write_text("{}", encoding="utf-8")
    selection_digest = "b" * 64
    artifact_digest = "c" * 64
    client = TestClient(app)

    requests = [
        (f"{BASE}/dependencies/migrate", {"dry_run": True}),
        (f"{BASE}/dependencies/migrate", {"plan_sha256": "a" * 64}),
        (f"{BASE}/review-1/refresh", {"expected_generation": 7}),
        (f"{BASE}/review-1/findings?expected_generation=7", {"selection": "operation.json"}),
        (f"{BASE}/review-1/rerun/preview", {"selection": "operation.json", "mode": "unresolved"}),
        (f"{BASE}/review-1/rerun/preview", {"selection": "operation.json", "mode": "selected"}),
        (f"{BASE}/review-1/rerun/run", {"selection_sha256": selection_digest}),
        (f"{BASE}/review-1/correction/prepare", {
            "item": "item-1", "target_kind": "source", "replacement": "Exact replacement",
            "expected_decision_revision": 0, "summaries_dir": "summaries",
        }),
        (f"{BASE}/review-1/correction/apply", {
            "proposal": "correction-1", "proposal_sha256": artifact_digest,
            "summaries_dir": "summaries",
        }),
        (f"{BASE}/review-1/npc/sign", {
            "item": "npc-signoff-1", "draft_sha256": artifact_digest,
            "expected_decision_revision": 0, "reviewer": "GM",
        }),
        (f"{BASE}/review-1/document/sign", {
            "item": "document-1", "document_sha256": artifact_digest,
            "expected_decision_revision": 0, "reviewer": "GM",
        }),
        (f"{BASE}/review-1/identity/prepare", {
            "item": "pair-1", "expected_decision_revision": 0, "scope_kind": "global",
        }),
        (f"{BASE}/review-1/identity/prepare", {
            "item": "pair-1", "expected_decision_revision": 0,
            "scope_kind": "chapter", "scope_value": "7",
        }),
        (f"{BASE}/review-1/identity/apply", {
            "proposal": "identity-1", "proposal_sha256": artifact_digest,
        }),
        (f"{BASE}/review-1/identity/regenerate", {
            "receipt": "receipt-identity-1", "selection": "operation.json",
        }),
        (f"{BASE}/review-1/identity/guard/prepare", {
            "proposal": "identity-blocked-1", "reviewer": "GM", "note": "Explicitly retire guard",
        }),
        (f"{BASE}/review-1/identity/guard/apply", {
            "resolution": "guard-resolution-1", "resolution_sha256": artifact_digest,
        }),
    ]
    for url, body in requests:
        response = client.post(url, json=body)
        assert response.status_code == 200, (url, response.text)
    detail = client.get(f"{BASE}/review-1/identity/identity-1")
    assert detail.status_code == 200, detail.text
    resolution = client.get(f"{BASE}/review-1/identity/identity-1/resolution")
    assert resolution.status_code == 200, resolution.text

    command_parts = [command[2:-3] for command, _kwargs in calls]
    assert command_parts == [
        ["dependencies", "migrate", "--dry-run"],
        ["dependencies", "migrate", "--plan-sha256", "a" * 64],
        ["refresh", "review-1", "--expected-generation", "7"],
        ["finding", "add", "review-1", "--finding", str(operation), "--expected-generation", "7"],
        ["rerun", "preview", "review-1", "--selection", str(operation), "--mode", "unresolved"],
        ["rerun", "preview", "review-1", "--selection", str(operation), "--mode", "selected"],
        ["rerun", "run", "review-1", "--selection-sha256", selection_digest],
        [
            "correction", "prepare", "review-1", "--item", "item-1", "--target-kind", "source",
            "--replacement", "Exact replacement", "--expected-decision-revision", "0",
            "--summaries-dir", "summaries",
        ],
        [
            "correction", "apply", "review-1", "--proposal", "correction-1",
            "--proposal-sha256", artifact_digest, "--summaries-dir", "summaries",
        ],
        [
            "npc", "sign", "review-1", "--item", "npc-signoff-1", "--draft-sha256",
            artifact_digest, "--expected-decision-revision", "0", "--reviewer", "GM",
        ],
        [
            "document", "sign", "review-1", "--item", "document-1", "--document-sha256",
            artifact_digest, "--expected-decision-revision", "0", "--reviewer", "GM",
        ],
        [
            "identity", "prepare", "review-1", "--item", "pair-1",
            "--expected-decision-revision", "0", "--scope-kind", "global",
        ],
        [
            "identity", "prepare", "review-1", "--item", "pair-1",
            "--expected-decision-revision", "0", "--scope-kind", "chapter", "--scope-value", "7",
        ],
        [
            "identity", "apply", "review-1", "--proposal", "identity-1",
            "--proposal-sha256", artifact_digest,
        ],
        [
            "identity", "regenerate", "review-1", "--receipt", "receipt-identity-1",
            "--selection", str(operation),
        ],
        [
            "identity", "guard-prepare", "review-1", "--proposal", "identity-blocked-1",
            "--reviewer", "GM", "--note", "Explicitly retire guard",
        ],
        [
            "identity", "guard-apply", "review-1", "--resolution", "guard-resolution-1",
            "--resolution-sha256", artifact_digest,
        ],
        ["identity", "detail", "review-1", "--proposal", "identity-1"],
        ["identity", "resolution", "review-1", "--proposal", "identity-1"],
    ]
    assert all(kwargs["save_run_log"] is False for _command, kwargs in calls)


def test_identity_regeneration_execution_uses_long_running_local_sse(route_app, monkeypatch):
    app, campaign, calls = route_app
    selection = campaign / "regeneration.json"
    selection.write_text('{"paths":["docs/npcs/example.md"]}\n', encoding="utf-8")
    streamed = []

    async def fake_stream(command, **kwargs):
        streamed.append((command, kwargs))
        yield 'event: done\ndata: {"returncode":0}\n\n'

    monkeypatch.setattr(review_routes, "stream_subprocess", fake_stream)
    response = TestClient(app).post(
        f"{BASE}/review-1/identity/regenerate",
        json={"receipt": "receipt-1", "selection": selection.name, "execute": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in response.text
    assert calls == []
    command, kwargs = streamed[0]
    assert command[2:-3] == [
        "identity", "regenerate", "review-1", "--receipt", "receipt-1",
        "--selection", str(selection), "--execute",
    ]
    assert kwargs["cwd"] == str(campaign)


def test_service_tls_and_grant_lifecycle_flags_are_visible_in_argv(route_app):
    app, campaign, calls = route_app
    cert = campaign / "review.crt"
    key = campaign / "review.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    client = TestClient(app)

    assert client.post(f"{BASE}/review-1/service/start", json={
        "host": "100.64.0.10", "port": 9443, "origin": "https://review.example:9443",
        "tls_cert": cert.name, "tls_key": key.name,
    }).status_code == 200
    assert client.post(
        f"{BASE}/review-1/access/issue", json={"expires_in": 3600}
    ).status_code == 200
    assert client.post(
        f"{BASE}/review-1/access/revoke", json={"grant": "grant-1"}
    ).status_code == 200

    assert calls[0][0][2:-3] == [
        "service", "start", "review-1", "--host", "100.64.0.10", "--port", "9443",
        "--origin", "https://review.example:9443", "--tls-cert", str(cert), "--tls-key", str(key),
    ]
    assert calls[1][0][2:-3] == ["access", "issue", "review-1", "--expires-in", "3600"]
    assert calls[2][0][2:-3] == ["access", "revoke", "review-1", "--grant", "grant-1"]


def test_correction_interruption_remains_visible_until_explicit_recovery(route_app, monkeypatch):
    app, _campaign, calls = route_app
    recovered = False

    async def interrupted(cmd, **kwargs):
        nonlocal recovered
        calls.append((cmd, kwargs))
        operation = cmd[2:4]
        if operation == ["correction", "apply"]:
            return {"ok": False, "code": "REVIEW_RECOVERY_REQUIRED", "data": {"transaction": "tx-correction"}}
        if cmd[2] == "status":
            return {"ok": True, "data": {"pending_transaction": None if recovered else "tx-correction"}}
        if cmd[2] == "recover":
            recovered = True
            return {"ok": True, "data": {"state": "committed"}}
        raise AssertionError(cmd)

    monkeypatch.setattr(review_routes, "run_bounded_json", interrupted)
    client = TestClient(app)
    digest = "d" * 64
    applied = client.post(f"{BASE}/review-1/correction/apply", json={
        "proposal": "correction-1", "proposal_sha256": digest,
    })
    assert applied.json()["data"]["transaction"] == "tx-correction"
    assert client.get(f"{BASE}/review-1/status").json()["data"]["pending_transaction"] == "tx-correction"
    assert client.post(f"{BASE}/recover", json={"transaction": "tx-correction"}).status_code == 200
    assert client.get(f"{BASE}/review-1/status").json()["data"]["pending_transaction"] is None


def test_retired_document_publication_routes_preserve_history_guidance(route_app):
    _app, _campaign, calls = route_app
    payload = review_routes.FileSelectionRequest(selection="operation.json")
    for action in ("prepare", "promote"):
        response = asyncio.run(getattr(review_routes, f"document_{action}")(None, "review-1", payload))
        assert response.status_code == 410
        body = json.loads(response.body)
        assert body["code"] == "DOCUMENT_PROMOTION_RETIRED"
        assert body["data"]["promotion_path"] == "/api/grounding/summary-native/promotion/preview"
        assert body["data"]["history_path"] == f"{BASE}/review-1/history"
    assert calls == []


def test_review_launcher_exposes_every_trusted_cli_control_and_binding():
    source = (
        Path(__file__).parents[1] / "frontend" / "src" / "components" / "ReviewLauncher.vue"
    ).read_text(encoding="utf-8")
    required_routes = {
        "initialize": "request('/init','POST',{})",
        "authority migration": "request('/migrate','POST',{dry_run:true})",
        "dependency migration": "request('/dependencies/migrate','POST',{dry_run:true})",
        "list": "request('','GET')",
        "status": "/status`,'GET'",
        "pagination limit": "?limit=${pageLimit}",
        "pagination cursor": "&cursor=${encodeURIComponent(cursor)}",
        "history": "/history${historyItem?",
        "retract": "/retract`,'POST'",
        "export": "/export`,'POST'",
        "import": "request('/import','POST'",
        "refresh": "/refresh`,'POST'",
        "finding add": "/findings?expected_generation=${generation}",
        "rerun preview": "/rerun/preview`,'POST'",
        "rerun execute": "/rerun/run`,'POST'",
        "correction preview": "/correction/prepare`,'POST'",
        "correction apply": "/correction/apply`,'POST'",
        "NPC signoff": "/npc/sign`,'POST'",
        "document signoff": "/document/sign`,'POST'",
        "whole-bundle guidance": "Go to whole-bundle promotion",
        "retired document actions": "per-document prepare and promote actions are retired",
        "identity prepare": "/identity/prepare`,'POST'",
        "identity detail": "/identity/${encodeURIComponent(proposalId)}`,'GET'",
        "identity apply": "/identity/apply`,'POST'",
        "identity resolution": "/resolution`,'GET'",
        "identity regeneration": "/identity/regenerate`,'POST'",
        "guard resolution prepare": "/identity/guard/prepare`,'POST'",
        "guard resolution apply": "/identity/guard/apply`,'POST'",
        "grant issue": "/access/issue`,'POST'",
        "grant revoke": "/access/revoke`,'POST'",
        "service start": "/service/start`,'POST'",
        "service status": "/service/status`,'GET'",
        "service stop": "/service/stop`,'POST'",
        "recovery": "request('/recover','POST'",
    }
    missing = [name for name, marker in required_routes.items() if marker not in source]
    assert missing == []
    for binding in (
        "expected_decision_revision:decisionRevision",
        "expected_generation:generation",
        "tls_cert:tlsCert",
        "tls_key:tlsKey",
        "expires_in:expiresIn",
        "grant_id",
        "selection_sha256:selectionSha",
        "proposal_sha256:proposalSha",
        "reviewer",
    ):
        assert binding in source


def test_service_process_identity_rejects_zombie_and_reaps_owned_child(tmp_path: Path):
    from pipelines.summary_native.review import service

    process = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        state = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                state = Path(f"/proc/{process.pid}/stat").read_text(encoding="utf-8").split()[2]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.01)

        assert state == "Z"
        assert service._process_identity(process.pid) is None

        key = (str(tmp_path.resolve()), "review-1")
        service._OWNED_PROCESSES[key] = process
        service._reap_owned(tmp_path.resolve(), "review-1")
        assert key not in service._OWNED_PROCESSES
        assert process.returncode == 0
    finally:
        process.wait()
