"""Focused regressions for review capability and managed-service boundaries."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import socket
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from campaignlib.review_config import ReviewConfig
from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import authority_lock, initialize_ledger
from pipelines.summary_native.review import access, service
from pipelines.summary_native.review.models import AccessGrant, canonical_bytes, model_from_json
from pipelines.summary_native.review.store import (
    ReviewStoreError,
    history,
    initialize_campaign,
)
from pipelines.summary_native.review.web import app as review_web
from server.subprocess_runner import BoundedJSONError
from tests.test_summary_native_review_http import (
    RAW_HTML,
    LiveReviewService,
    _decision_body,
    _free_port,
    _make_review,
    _spawn_server,
    _wait_until_listening,
    live_review,
)


def _token(review: LiveReviewService) -> str:
    return review.capability_url.rstrip("/").rsplit("/", 1)[-1]


def _grant_path(review: LiveReviewService) -> Path:
    return (
        review.root / "docs" / "reviews" / "primary-review" / "access"
        / f"{review.grant_id}.json"
    )


def test_well_formed_expired_grant_is_denied(live_review: LiveReviewService):
    path = _grant_path(live_review)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["issued_at"] = "2000-01-01T00:00:00Z"
    raw["expires_at"] = "2000-01-02T00:00:00Z"
    path.write_bytes(canonical_bytes(raw))

    parsed = model_from_json(AccessGrant, path.read_bytes())
    assert parsed.issued_at < parsed.expires_at < datetime.now(timezone.utc)
    assert requests.get(f"{live_review.capability_url}review", timeout=2).status_code == 404


def test_chunked_oversized_body_is_bounded_without_content_length(
    live_review: LiveReviewService,
):
    shell = requests.get(live_review.capability_url, timeout=2)
    csrf = shell.headers["X-Review-CSRF"]

    def chunks():
        yield b'{"padding":"'
        for _ in range(17):
            yield b"x" * 65536
        yield b'"}'

    response = requests.post(
        f"{live_review.capability_url}decisions",
        data=chunks(),
        headers={
            "Origin": live_review.origin,
            "X-Review-CSRF": csrf,
            "Content-Type": "application/json",
        },
        timeout=4,
    )
    assert response.request.headers.get("Transfer-Encoding") == "chunked"
    assert "Content-Length" not in response.request.headers
    assert response.status_code == 413
    assert "x" * 256 not in response.text
    assert requests.get(f"{live_review.capability_url}review", timeout=2).status_code == 200


def test_copied_grant_is_denied_by_a_different_campaign(
    live_review: LiveReviewService, tmp_path: Path,
):
    other = tmp_path / "other-campaign"
    (other / "config").mkdir(parents=True)
    (other / "config" / "config.yaml").write_text("{}\n", encoding="utf-8")
    source = other / "summaries" / "001" / "session-summary.md"
    source.parent.mkdir(parents=True)
    source_bytes = b"# Chapter 1\n\nEvidence for item-1\n\n**bold is presentation only**\n"
    source.write_bytes(source_bytes)
    initialize_ledger(
        other,
        AuthorityLedger(version=2, campaign="other-http-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(other)
    _make_review(
        other,
        identity.campaign_id,
        "primary-review",
        "item-1",
        RAW_HTML,
        hashlib.sha256(source_bytes).hexdigest(),
        len(source_bytes),
    )
    copied = other / "docs" / "reviews" / "primary-review" / "access" / _grant_path(live_review).name
    copied.parent.mkdir(mode=0o700)
    copied.write_bytes(_grant_path(live_review).read_bytes())

    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    process = _spawn_server(other, port, origin)
    try:
        _wait_until_listening(process, origin)
        response = requests.get(f"{origin}/r/{_token(live_review)}/review", timeout=2)
        assert response.status_code == 404
        assert response.text == requests.get(
            f"{origin}/r/not-a-capability/review", timeout=2
        ).text
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - cleanup guard
            process.kill()
            process.wait(timeout=5)


def test_revocation_before_decision_writer_lock_prevents_commit(
    live_review: LiveReviewService,
):
    shell = requests.get(live_review.capability_url, timeout=2)
    csrf = shell.headers["X-Review-CSRF"]
    endpoint = f"{live_review.capability_url}decisions"
    headers = {"Origin": live_review.origin, "X-Review-CSRF": csrf}
    grant_path = _grant_path(live_review)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        with authority_lock(live_review.root, exclusive=True):
            pending = pool.submit(
                requests.post,
                endpoint,
                json=_decision_body(live_review, "revocation-lock-race"),
                headers=headers,
                timeout=8,
            )
            time.sleep(0.35)
            assert not pending.done(), "decision must be waiting for the campaign writer lock"
            grant = model_from_json(AccessGrant, grant_path.read_bytes())
            revoked = grant.model_copy(update={
                "revoked": True,
                "revoked_at": datetime.now(timezone.utc),
            })
            access._write_private(grant_path, canonical_bytes(revoked))
        response = pending.result(timeout=8)

    assert response.status_code == 404
    assert history(live_review.root, "primary-review", item_id=live_review.item.item_id) == []


def test_occupied_port_never_reports_an_unrelated_listener_as_ready(
    live_review: LiveReviewService,
):
    live_review.stop()
    with socket.socket() as unrelated:
        unrelated.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        unrelated.bind(("127.0.0.1", live_review.port))
        unrelated.listen()
        started = time.monotonic()
        with pytest.raises(ReviewStoreError, match="REVIEW_SERVICE_(?:BIND_FAILED|FAILED)"):
            service.start_service(
                live_review.root,
                "primary-review",
                host="127.0.0.1",
                port=live_review.port,
                origin=live_review.origin,
            )
        assert time.monotonic() - started < 5
        assert service.service_status(live_review.root, "primary-review")["running"] is False
        assert (str(live_review.root.resolve()), "primary-review") not in service._OWNED_PROCESSES


def test_runtime_and_credential_symlinks_are_refused_without_escape(
    live_review: LiveReviewService, tmp_path: Path,
):
    outside_runtime = tmp_path / "outside-runtime"
    outside_runtime.mkdir()
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    (standalone / ".review-runtime").symlink_to(outside_runtime, target_is_directory=True)
    with pytest.raises(ReviewStoreError, match="runtime directory"):
        service._write_handle(
            service.handle_path(standalone, "review-1"),
            {"review_id": "review-1"},
        )
    assert list(outside_runtime.iterdir()) == []

    outside_handle = tmp_path / "outside-handle.json"
    outside_handle.write_text('{"sentinel":true}\n', encoding="utf-8")
    safe_root = tmp_path / "safe-root"
    runtime = safe_root / ".review-runtime"
    runtime.mkdir(parents=True)
    (runtime / "review-1.json").symlink_to(outside_handle)
    with pytest.raises(ReviewStoreError, match="runtime handle"):
        service._read_handle(safe_root, "review-1")
    assert outside_handle.read_text(encoding="utf-8") == '{"sentinel":true}\n'

    outside_access = tmp_path / "outside-access"
    outside_access.mkdir()
    access_dir = live_review.root / "docs" / "reviews" / "other-review" / "access"
    access_dir.symlink_to(outside_access, target_is_directory=True)
    with pytest.raises(ReviewStoreError, match="credential"):
        access.issue_grant(
            live_review.root,
            "other-review",
            origin=live_review.origin,
        )
    assert list(outside_access.iterdir()) == []


def test_runtime_handle_replace_fsyncs_its_private_directory(tmp_path: Path, monkeypatch):
    root = tmp_path / "campaign"
    root.mkdir()
    observed: list[bool] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(service.os, "fsync", recording_fsync)
    path = service.handle_path(root, "review-1")
    service._write_handle(path, {"review_id": "review-1", "version": 1})

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert observed[-1] is True

    observed.clear()
    assert service._unlink_handle(root, "review-1") is True
    assert not path.exists()
    assert observed[-1] is True


def test_credential_replace_fsyncs_its_private_directory(tmp_path: Path, monkeypatch):
    root = tmp_path / "campaign"
    review = root / "docs" / "reviews" / "review-1"
    review.mkdir(parents=True)
    path = review / "access" / "grant-1.json"
    observed: list[bool] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        observed.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(access.os, "fsync", recording_fsync)
    access._write_private(path, b'{"version":1}\n')

    assert path.read_bytes() == b'{"version":1}\n'
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert observed[-1] is True


def test_subprocess_payload_cannot_echo_capability_or_campaign_path(
    live_review: LiveReviewService, monkeypatch,
):
    token = _token(live_review)
    secret_path = str(live_review.root / "private" / token)

    async def unsafe_failure(*_args, **_kwargs):
        raise BoundedJSONError(
            "failed",
            returncode=2,
            category="nonzero_exit",
            payload={
                "ok": False,
                "code": "UNEXPECTED_SECRET_ERROR",
                "message": f"token={token} path={secret_path}",
            },
        )

    monkeypatch.setattr(review_web, "run_bounded_json", unsafe_failure)
    config = ReviewConfig(
        bind_host="127.0.0.1",
        port=live_review.port,
        origin=live_review.origin,
    )
    app = review_web.create_review_app(live_review.root, "primary-review", config)
    host = live_review.origin.removeprefix("http://")
    response = TestClient(app).get(
        f"/r/{token}/review",
        headers={"Host": host},
    )

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "code": "REVIEW_COMMAND_FAILED",
        "message": "Review command failed safely.",
    }
    assert token not in response.text
    assert secret_path not in response.text
