"""Real-process security contract for the dedicated review server (T013)."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import UUID

import pytest
import requests

from pipelines.summary_native.authority import AuthorityLedger
from pipelines.summary_native.authority_apply import initialize_ledger
from pipelines.summary_native.cli import main
from pipelines.summary_native.review.models import ReviewItem, ReviewManifest, SourceCustodyGeneration
from pipelines.summary_native.review.store import create_review, initialize_campaign


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
RAW_HTML = '<img src="http://127.0.0.1:9/leak" onerror="window.PWNED=1"><script>window.PWNED=2</script>'


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _make_review(
    root: Path,
    campaign_id: UUID,
    review_id: str,
    item_id: str,
    claim: str,
    source_sha256: str,
    source_size: int,
) -> ReviewItem:
    item = ReviewItem(
        item_id=item_id,
        revision=1,
        campaign_id=campaign_id,
        review_id=review_id,
        domain="npc_finding",
        subject_ref={"subject_id": UUID(int=1000 + len(review_id)), "kind": "claim"},
        occurrence_id=UUID(int=2000 + len(item_id)),
        locator={"source_path": "summaries/001/session-summary.md", "anchor": item_id},
        claim_text=claim,
        evidence=(
            {
                "source_id": "summary-1",
                "source_path": "summaries/001/session-summary.md",
                "anchor": item_id,
                "exact_excerpt": f"Evidence for {item_id}\n\n**bold is presentation only**",
                "selected_span_sha256": hashlib.sha256(
                    f"Evidence for {item_id}\n\n**bold is presentation only**".encode("utf-8")
                ).hexdigest(),
            },
        ),
        diagnostics=(
            {
                "diagnostic_id": f"check-{item_id}",
                "legacy_code": "citation-mismatch",
                "message": "Inspect the evidence.",
                "blocking": False,
            },
        ),
        categories={"citation_non_entailment"},
        severity="needs_judgment",
        assignment_basis="advisory_candidate",
        rationale="The citation resolves but meaning is unassessed.",
        proposed_action={"action": "accept_no_change_or_correct"},
        scope={"kind": "evidence", "value": item_id},
        rule_versions=({"rule_id": "entailment", "version": "1"},),
        input_bindings=(
            {
                "source_id": "summary-1",
                "path": "summaries/001/session-summary.md",
                "custody_sha256": source_sha256,
                "semantic_sha256": "c" * 64,
            },
        ),
    )
    custody = SourceCustodyGeneration(
        campaign_id=campaign_id,
        review_id=review_id,
        generation=1,
        recorded_at=NOW,
        sources=(
            {
                "source_id": "summary-1",
                "path": "summaries/001/session-summary.md",
                "sha256": source_sha256,
                "size": source_size,
            },
        ),
    )
    manifest = ReviewManifest(
        campaign_id=campaign_id,
        review_id=review_id,
        kind="npc_verification",
        generation=1,
        created_at=NOW,
        created_by="GM",
        selection=({"kind": "subject", "id": f"selection-{item_id}"},),
        items=(
            {
                "campaign_id": campaign_id,
                "review_id": review_id,
                "item_id": item_id,
                "revision": 1,
                "review_digest": item.review_digest,
            },
        ),
        source_manifest={
            "campaign_id": campaign_id,
            "review_id": review_id,
            "generation": 1,
            "digest": custody.custody_digest,
        },
        rule_versions=({"rule_id": "entailment", "version": "1"},),
    )
    create_review(root, manifest, custody, [item])
    return item


def _cli_json(capsys, argv: list[str]) -> tuple[int, dict]:
    try:
        returncode = main(argv)
    except SystemExit as exc:
        pytest.fail(f"review CLI command is not implemented: exit {exc.code}")
    captured = capsys.readouterr()
    assert captured.out, f"CLI emitted no JSON; stderr={captured.err!r}"
    return returncode, json.loads(captured.out)


@dataclass
class LiveReviewService:
    root: Path
    item: ReviewItem
    port: int
    origin: str
    process: subprocess.Popen[str]
    capability_url: str
    grant_id: str

    def stop(self) -> tuple[str, str]:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        stdout, stderr = self.process.communicate(timeout=1)
        return stdout, stderr

    def restart(self) -> None:
        self.stop()
        self.process = _spawn_server(self.root, self.port, self.origin)
        _wait_until_listening(self.process, self.origin)


def _server_command(root: Path, port: int, origin: str) -> list[str]:
    return [
        sys.executable,
        "-c",
        "import sys; from pipelines.summary_native.cli import main; raise SystemExit(main(sys.argv[1:]))",
        "review",
        "serve",
        "primary-review",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--origin",
        origin,
        "--campaign-dir",
        str(root),
        "--json",
    ]


def _spawn_server(root: Path, port: int, origin: str) -> subprocess.Popen[str]:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    return subprocess.Popen(
        _server_command(root, port, origin),
        cwd=Path.cwd(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_until_listening(process: subprocess.Popen[str], origin: str) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            pytest.fail(f"review serve exited before readiness: stdout={stdout!r} stderr={stderr!r}")
        try:
            requests.get(f"{origin}/r/not-a-capability/", timeout=0.2)
            return
        except requests.RequestException:
            time.sleep(0.05)
    pytest.fail("review serve did not bind within its readiness deadline")


@pytest.fixture
def live_review(tmp_path: Path, capsys) -> Iterator[LiveReviewService]:
    root = tmp_path / "campaign"
    (root / "config").mkdir(parents=True)
    (root / "config" / "config.yaml").write_text(
        "sentinel: DO_NOT_EXPOSE_THIS_CONFIG_SENTINEL\n", encoding="utf-8"
    )
    source = root / "summaries" / "001" / "session-summary.md"
    source.parent.mkdir(parents=True)
    source_bytes = (
        b"# Chapter 1\n\nEvidence for item-1\n\n"
        b"**bold is presentation only**\nEvidence for other-only\n"
    )
    source.write_bytes(source_bytes)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    initialize_ledger(
        root,
        AuthorityLedger(version=2, campaign="http-fixture", revision=1),
        actor="test",
    )
    identity = initialize_campaign(root)
    item = _make_review(
        root, identity.campaign_id, "primary-review", "item-1", RAW_HTML,
        source_sha256, len(source_bytes),
    )
    _make_review(
        root, identity.campaign_id, "other-review", "other-only", "Other review secret",
        source_sha256, len(source_bytes),
    )

    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    process = _spawn_server(root, port, origin)
    _wait_until_listening(process, origin)
    code, issued = _cli_json(
        capsys,
        [
            "review", "access", "issue", "primary-review",
            "--campaign-dir", str(root), "--json",
        ],
    )
    assert code == 0 and issued["ok"] is True
    service = LiveReviewService(
        root=root,
        item=item,
        port=port,
        origin=origin,
        process=process,
        capability_url=issued["data"]["url"],
        grant_id=issued["data"]["grant_id"],
    )
    assert service.capability_url.startswith(f"{origin}/r/")
    try:
        yield service
    finally:
        service.stop()


def _security_headers(response: requests.Response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers.get("X-Frame-Options", "").upper() in {"DENY", "SAMEORIGIN"}


def _decision_body(service: LiveReviewService, request_id: str = "browser-request-1") -> dict:
    return {
        "request_id": request_id,
        "review_generation": 1,
        "reviewer": "GM",
        "decisions": [
            {
                "item_id": service.item.item_id,
                "item_revision": service.item.revision,
                "review_digest": service.item.review_digest,
                "expected_decision_revision": 0,
                "verdict": "approve",
                "disposition": "accept_no_change",
                "note": "Checked on the phone.",
            }
        ],
    }


def test_capability_is_scoped_and_never_serves_paths_or_other_reviews(live_review: LiveReviewService):
    shell = requests.get(live_review.capability_url, timeout=2)
    assert shell.status_code == 200
    _security_headers(shell)
    snapshot = requests.get(f"{live_review.capability_url}review", timeout=2)
    assert snapshot.status_code == 200
    assert snapshot.json()["data"]["review_id"] == "primary-review"

    other = requests.get(f"{live_review.capability_url}items/other-only", timeout=2)
    traversal = requests.get(
        f"{live_review.capability_url}items/..%2F..%2Fconfig%2Fconfig.yaml", timeout=2
    )
    guessed = requests.get(f"{live_review.origin}/r/not-the-token/review", timeout=2)
    assert other.status_code == traversal.status_code == guessed.status_code == 404
    assert "Other review secret" not in other.text
    assert "DO_NOT_EXPOSE_THIS_CONFIG_SENTINEL" not in traversal.text
    assert other.text == guessed.text


def test_grant_survives_restart_then_revocation_and_expiry_are_rechecked(
    live_review: LiveReviewService, capsys
):
    assert requests.get(f"{live_review.capability_url}review", timeout=2).status_code == 200
    live_review.restart()
    assert requests.get(f"{live_review.capability_url}review", timeout=2).status_code == 200

    code, revoked = _cli_json(
        capsys,
        [
            "review", "access", "revoke", "primary-review", "--grant", live_review.grant_id,
            "--campaign-dir", str(live_review.root), "--json",
        ],
    )
    assert code == 0 and revoked["ok"] is True
    assert requests.get(f"{live_review.capability_url}review", timeout=2).status_code == 404

    code, issued = _cli_json(
        capsys,
        ["review", "access", "issue", "primary-review", "--campaign-dir", str(live_review.root), "--json"],
    )
    assert code == 0
    expiring_url = issued["data"]["url"]
    grant_path = (
        live_review.root / "docs" / "reviews" / "primary-review" / "access"
        / f"{issued['data']['grant_id']}.json"
    )
    grant = json.loads(grant_path.read_text(encoding="utf-8"))
    grant["expires_at"] = "2000-01-01T00:00:00Z"
    grant_path.write_text(json.dumps(grant, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    assert requests.get(f"{expiring_url}review", timeout=2).status_code == 404


def test_browser_writes_require_exact_origin_host_content_type_and_csrf(live_review: LiveReviewService):
    shell = requests.get(live_review.capability_url, timeout=2)
    csrf = shell.headers.get("X-Review-CSRF")
    assert csrf, "viewer shell must issue a short-lived grant-bound CSRF nonce"
    endpoint = f"{live_review.capability_url}decisions"
    body = _decision_body(live_review)

    assert requests.post(endpoint, json=body, timeout=2).status_code in {400, 404}
    assert requests.post(
        endpoint,
        json=body,
        headers={"Origin": "http://evil.invalid", "X-Review-CSRF": csrf},
        timeout=2,
    ).status_code in {400, 404}
    assert requests.post(
        endpoint,
        data=json.dumps(body),
        headers={
            "Origin": live_review.origin,
            "X-Review-CSRF": csrf,
            "Content-Type": "text/plain",
        },
        timeout=2,
    ).status_code == 400
    assert requests.post(
        endpoint,
        json=body,
        headers={
            "Origin": live_review.origin,
            "X-Review-CSRF": csrf,
            "Host": "evil.invalid",
        },
        timeout=2,
    ).status_code == 404

    saved = requests.post(
        endpoint,
        json=body,
        headers={"Origin": live_review.origin, "X-Review-CSRF": csrf},
        timeout=2,
    )
    assert saved.status_code == 200
    assert saved.json()["ok"] is True


def test_raw_html_stays_data_and_static_assets_are_a_fixed_allowlist(live_review: LiveReviewService):
    shell = requests.get(live_review.capability_url, timeout=2)
    assert RAW_HTML not in shell.text
    item = requests.get(f"{live_review.capability_url}items/item-1", timeout=2)
    assert item.status_code == 200
    assert item.json()["data"]["claim_text"] == RAW_HTML
    assert item.headers["Content-Type"].startswith("application/json")
    _security_headers(item)

    for asset in ("viewer.js", "viewer.css"):
        response = requests.get(f"{live_review.capability_url}assets/{asset}", timeout=2)
        assert response.status_code == 200
        _security_headers(response)
    for unknown in ("viewer.html", "secret.map", "../manifest.json", "%2e%2e/manifest.json"):
        assert requests.get(f"{live_review.capability_url}assets/{unknown}", timeout=2).status_code == 404


def test_oversized_payload_refuses_and_remote_admin_routes_do_not_exist(live_review: LiveReviewService):
    shell = requests.get(live_review.capability_url, timeout=2)
    csrf = shell.headers["X-Review-CSRF"]
    endpoint = f"{live_review.capability_url}decisions"
    oversized = b'{' + b'"padding":"' + (b"x" * (1024 * 1024)) + b'"}'
    response = requests.post(
        endpoint,
        data=oversized,
        headers={
            "Origin": live_review.origin,
            "X-Review-CSRF": csrf,
            "Content-Type": "application/json",
        },
        timeout=2,
    )
    assert response.status_code == 413
    assert "x" * 256 not in response.text

    for route in ("apply", "promote", "access/issue", "service/stop", "recover"):
        response = requests.post(
            f"{live_review.capability_url}{route}",
            json={},
            headers={"Origin": live_review.origin, "X-Review-CSRF": csrf},
            timeout=2,
        )
        assert response.status_code == 404


def test_capability_never_appears_in_service_output_or_error_bodies(live_review: LiveReviewService):
    token = live_review.capability_url.rstrip("/").rsplit("/", 1)[-1]
    denied = requests.get(f"{live_review.capability_url}not-a-route", timeout=2)
    assert denied.status_code == 404
    assert token not in denied.text
    stdout, stderr = live_review.stop()
    assert token not in stdout
    assert token not in stderr
